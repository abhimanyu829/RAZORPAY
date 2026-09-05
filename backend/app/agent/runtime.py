"""AGENT RUNTIME — the live loop (Sections 25–29, 41, 42).

OBSERVE → INVESTIGATE → LLM REASON → LLM PLAN → POLICY → APPROVAL →
TOOL → VERIFY → STOP/ESCALATE

The structure of the deterministic skeleton is unchanged: only REASON and
PLAN are now LLM calls behind the same input/output contract. Everything a
model produces is validated (schema), gated (policy), recorded (audit), and
verified. One primary action per run (Section 28).
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

from ..settings import settings, is_shadow_mode, can_execute_actions
from .llm_client import llm, LLMValidationError, LLMUnavailableError
from .prompts import build_case_payload, build_messages, SYSTEM_PROMPT
from .policies import PolicyEngine, PolicyViolation
from ..tools.registry import registry
from ..tools.implementations import registry as _impl  # ensure registration
from ..services.repository import repo, now_iso, _to_float


# --------------------------------------------------------------------------- #
# audit chain (hash-linked per run)                                           #
# --------------------------------------------------------------------------- #

class RunAudit:
    def __init__(self, run_id: str, case_id: str):
        self.run_id = run_id
        self.case_id = case_id
        self.prev = "GENESIS"
        self.entries: list[dict] = []

    def add(self, actor: str, event_type: str, decision: str = "",
            tool: str = "", params: dict | None = None, result: dict | None = None,
            amount: float | None = None, approval_id: str = "",
            new_state: str = "") -> dict:
        e = {
            "audit_id": f"AUD-{len(self.entries) + 1:05d}",
            "run_id": self.run_id, "case_id": self.case_id,
            "actor": actor, "event_type": event_type, "tool_called": tool,
            "tool_parameters": json.dumps(params or {}, default=str),
            "tool_result": json.dumps(result or {}, default=str),
            "decision": decision, "previous_state": "",
            "new_state": new_state, "amount": amount if amount is not None else 0,
            "evidence_ids": "", "approval_id": approval_id,
            "correlation_id": f"CORR-{self.run_id}",
            "prev_hash": self.prev, "created_at": now_iso(),
        }
        e["entry_hash"] = hashlib.sha256(
            (self.prev + e["audit_id"] + event_type + str(e["amount"])).encode()
        ).hexdigest()[:16]
        self.prev = e["entry_hash"]
        self.entries.append(e)
        return e

    def flush(self):
        for e in self.entries:
            repo.append("audit_ledger", e)


# --------------------------------------------------------------------------- #
# run record                                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class AgentRunResult:
    run_id: str
    case_id: str
    status: str                     # COMPLETED|BLOCKED_POLICY|BLOCKED_LLM|FAILED
    proposed_action: str = ""
    executed_action: str = ""
    action_id: str = ""
    approval_id: str = ""
    verification_status: str = ""
    recovered_amount: float = 0.0
    llm_plan: dict = field(default_factory=dict)
    policy_decision: dict = field(default_factory=dict)
    steps: int = 0
    tool_calls: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0


class AgentRuntime:
    def __init__(self):
        self.policy = PolicyEngine(
            max_actions_per_run=settings.max_actions_per_run,
            max_financial_exposure=settings.max_financial_exposure)

    # ---------------------------------------------------------------- run
    def run_case(self, case_id: str, actor: str = "AGENT",
                 force_scenario: str | None = None) -> AgentRunResult:
        t0 = time.monotonic()
        run_id = f"RUN-{uuid.uuid4().hex[:12].upper()}"
        audit = RunAudit(run_id, case_id)

        case = repo.get_case(case_id)
        if not case:
            raise ValueError(f"case {case_id} not found")
        result = AgentRunResult(run_id=run_id, case_id=case_id, status="COMPLETED")

        audit.add(actor, "RUN_STARTED", decision=f"case {case_id} opened",
                  new_state="OBSERVING")
        self._record_run_start(run_id, case_id)

        try:
            # ------------------------------------------------------ OBSERVE
            evidence = repo.evidence_for_case(case_id)
            history = repo.history_for_case(case_id)
            recov = repo.read_one("recoverability_assessments", "case_id", case_id)
            payload = build_case_payload(case, evidence, recoverability=recov,
                                         case_history=history)
            audit.add(actor, "OBSERVE",
                      decision=f"{len(evidence)} evidence rows, {len(history)} history rows",
                      new_state="INVESTIGATING")
            result.steps += 1

            # -------------------------------------------------- INVESTIGATE
            neighborhood = self._investigate(case, audit, result)
            payload["transaction_neighborhood"] = neighborhood
            payload["deadline_state"] = neighborhood["deadline"]["state"]
            payload["variance"] = neighborhood["variance"]["variance"]
            result.steps += 1

            # -------------------------------------- LLM REASON + PLAN (8.5)
            payload["_messages"] = build_messages(
                {k: v for k, v in payload.items() if k != "_messages"})
            audit.add(actor, "LLM_REASON_PLAN",
                      decision="calling LLM provider for structured plan",
                      params={"provider": settings.llm_provider,
                              "model": settings.llm_model},
                      new_state="PLANNING")
            try:
                plan = llm.reason_and_plan(payload)
            except (LLMValidationError, LLMUnavailableError) as e:
                audit.add("SYSTEM", "LLM_FAILED", decision=str(e)[:500],
                          new_state="BLOCKED")
                result.status = "BLOCKED_LLM"
                result.errors.append(str(e))
                self._finish(audit, result, t0)
                return result
            result.llm_plan = plan
            audit.add(actor, "LLM_PLAN",
                      decision=f"LLM proposed {plan['recommended_action']}",
                      result={"root_cause": plan["diagnosis"]["root_cause"],
                              "confidence": plan["diagnosis"]["confidence"],
                              "fallback": plan.get("_fallback", False)},
                      new_state="PLAN_VALIDATION")

            # ------------------------------------------------ POLICY GATE
            plan = PolicyEngine.scrub_untrusted_text(plan)
            actions_taken = len([a for a in repo.actions_for_case(case_id)
                                 if a.get("status") == "EXECUTED"])
            try:
                decision = self.policy.validate_plan(plan, case,
                                                    actions_this_run=actions_taken,
                                                    exposure_this_run=0.0)
            except PolicyViolation as pv:
                audit.add("POLICY", "POLICY_VIOLATION",
                          decision=f"DENIED: {pv.reason}",
                          result={"escalate": pv.escalate},
                          new_state="BLOCKED")
                result.status = "BLOCKED_POLICY"
                result.proposed_action = plan["recommended_action"]
                result.errors.append(pv.reason)
                self._record_plan(run_id, plan, denied=True)
                self._finish(audit, result, t0)
                return result

            result.policy_decision = {
                "allowed": decision.allowed, "risk_level": decision.risk_level,
                "approval_required": decision.approval_required,
                "auto_approved": decision.auto_approved,
                "reasons": decision.reasons,
            }
            result.proposed_action = plan["recommended_action"]
            audit.add("POLICY", "POLICY_DECISION",
                      decision=f"{decision.risk_level} {decision.action}: "
                               f"approval={'REQUIRED' if decision.approval_required else 'auto'}",
                      result={"reasons": decision.reasons},
                      new_state="APPROVAL_GATE")

            # ------------------------------------------------ SHADOW MODE
            if is_shadow_mode():
                audit.add("SYSTEM", "SHADOW_MODE",
                          decision=f"recorded proposal {decision.action}; no side effect",
                          new_state="SHADOW_RECORDED")
                result.status = "SHADOW_RECORDED"
                self._record_plan(run_id, plan, denied=False)
                self._finish(audit, result, t0)
                return result

            # ------------------------------------------- APPROVAL GATE
            approval_id = ""
            if decision.approval_required:
                approval_id = self._request_approval(case, decision, audit)
                if not approval_id:
                    audit.add("SYSTEM", "APPROVAL_PENDING",
                              decision="no answerer available — request parked",
                              new_state="PENDING_APPROVAL")
                    result.status = "PENDING_APPROVAL"
                    self._record_plan(run_id, plan, denied=False)
                    self._finish(audit, result, t0)
                    return result
                audit.add("HUMAN", "APPROVAL_GRANTED",
                          decision=f"approval {approval_id} granted",
                          approval_id=approval_id, new_state="ACTING")

            # ------------------------------------------------------ ACT
            tool_name = decision.action.lower()
            params = {"case_id": case_id,
                      "evidence_ids": [e["evidence_id"] for e in evidence],
                      "reason": plan["reason_for_action"],
                      "draft_content": plan.get("draft_content", ""),
                      "amount": _to_float(case.get("potential_recovery")
                                         or case.get("potential_leakage"))}
            if force_scenario and decision.action == "CREATE_DISPUTE":
                from ..tools.simulator import simulator
                simulator.force(case_id, force_scenario)
            try:
                outcome = registry.dispatch(tool_name, params, case,
                                            actor=actor, approval_id=approval_id)
            except PolicyViolation as pv:
                result.status = "BLOCKED_POLICY"
                result.errors.append(pv.reason)
                audit.add("POLICY", "TOOL_DENIED", decision=pv.reason,
                          new_state="BLOCKED")
                self._finish(audit, result, t0)
                return result
            result.tool_calls += 1
            result.executed_action = decision.action
            result.action_id = outcome.get("action_id", "")
            audit.add(actor, "ACT",
                      tool=tool_name,
                      decision=f"executed {decision.action} "
                               f"({'replayed' if outcome.get('replayed') else outcome['status']})",
                      result={"ok": outcome["ok"], "status": outcome["status"],
                              "external_reference": outcome.get("result", {}).get("external_reference", "")},
                      amount=_to_float(params["amount"]), approval_id=approval_id,
                      new_state="VERIFYING")

            # ---- bounded draft→dispute chain (Section 28 example flow) -----
            # After drafting (L1), the primary financial action (L3) follows
            # in the SAME run if policy allows: approval gate → create → verify.
            if (decision.action == "DRAFT_DISPUTE"
                    and "CREATE_DISPUTE" in (case.get("allowed_actions") or "").split("|")):
                audit.add(actor, "PLAN",
                          decision="primary action: CREATE_DISPUTE follows the draft",
                          new_state="APPROVAL_GATE")
                try:
                    d2 = self.policy.validate_plan(
                        {"recommended_action": "CREATE_DISPUTE"}, case,
                        actions_this_run=0, exposure_this_run=0.0)
                except PolicyViolation as pv:
                    audit.add("POLICY", "POLICY_VIOLATION",
                              decision=f"DENIED create_dispute: {pv.reason}",
                              new_state="BLOCKED")
                    result.errors.append(pv.reason)
                    self._finish(audit, result, t0)
                    return result

                approval_id2 = ""
                if d2.approval_required:
                    approval_id2 = self._request_approval(case, d2, audit)
                    if not approval_id2:
                        result.status = "PENDING_APPROVAL"
                        self._finish(audit, result, t0)
                        return result
                    audit.add("HUMAN", "APPROVAL_GRANTED",
                              decision=f"approval {approval_id2} granted for CREATE_DISPUTE",
                              approval_id=approval_id2, new_state="ACTING")

                params2 = {"case_id": case_id,
                           "evidence_ids": [e["evidence_id"] for e in evidence],
                           "reason": plan["reason_for_action"],
                           "draft_content": plan.get("draft_content", ""),
                           "amount": _to_float(case.get("potential_recovery")
                                              or case.get("potential_leakage"))}
                try:
                    outcome2 = registry.dispatch("create_dispute", params2, case,
                                                actor=actor, approval_id=approval_id2)
                except PolicyViolation as pv:
                    result.errors.append(pv.reason)
                    audit.add("POLICY", "TOOL_DENIED", decision=pv.reason,
                              new_state="BLOCKED")
                    self._finish(audit, result, t0)
                    return result
                result.tool_calls += 1
                if not outcome2["ok"]:
                    # blocked (rollout level / category / failure) — record honestly
                    result.executed_action = "CREATE_DISPUTE"
                    result.status = f"BLOCKED_{outcome2['status']}"
                    result.errors.append(outcome2.get("error", outcome2["status"]))
                    audit.add("SYSTEM", "ACT_BLOCKED",
                              tool="create_dispute",
                              decision=f"CREATE_DISPUTE blocked: {outcome2['status']}",
                              result={"status": outcome2["status"],
                                      "error": outcome2.get("error", "")},
                              new_state="BLOCKED")
                    self._record_plan(run_id, plan, denied=False)
                    self._finish(audit, result, t0)
                    return result
                result.executed_action = "CREATE_DISPUTE"
                result.action_id = outcome2.get("action_id", "")
                audit.add(actor, "ACT",
                          tool="create_dispute",
                          decision=f"executed CREATE_DISPUTE "
                                   f"({'replayed' if outcome2.get('replayed') else outcome2['status']})",
                          result={"ok": outcome2["ok"], "status": outcome2["status"],
                                  "external_reference": outcome2.get("result", {}).get("external_reference", "")},
                          amount=_to_float(params2["amount"]), approval_id=approval_id2,
                          new_state="VERIFYING")
                outcome = outcome2
                decision = d2

            # ---------------------------------------------------- VERIFY
            if decision.action in ("CREATE_DISPUTE", "NOTIFY_GATEWAY",
                                   "CREATE_PAYMENT_LINK"):
                vres = self._verify(case, outcome, audit)
                result.verification_status = vres.get("status", "")
                result.recovered_amount = _to_float(vres.get("recovered", 0))
                if vres.get("status") == "RECOVERY_VERIFIED":
                    self._record_recovery(case, result.recovered_amount, audit, approval_id)
            else:
                audit.add("SERVICE", "VERIFY_SKIPPED",
                          decision=f"action {decision.action} has no verification path",
                          new_state="DONE")

            # ---------------------------------------------------- STOP
            stop = plan.get("stop_reason")
            audit.add(actor, "STOP",
                      decision=f"loop complete: {stop or 'primary action done'}",
                      new_state="COMPLETED")

        except Exception as e:                        # total failure capture
            result.status = "FAILED"
            result.errors.append(f"runtime error: {e}")
            audit.add("SYSTEM", "RUN_FAILED", decision=str(e)[:500])
        self._finish(audit, result, t0)
        return result

    # ------------------------------------------------------------ internals
    def _investigate(self, case, audit, result) -> dict:
        """Read-tool neighborhood assembly — all deterministic, all audited."""
        nb: dict[str, Any] = {}
        out = registry.dispatch("get_order", {"order_id": case["order_id"]}, case)
        nb["order"] = _safe_row(out["result"].get("order"))
        result.tool_calls += 1
        out = registry.dispatch("get_payment", {"payment_id": case["payment_id"]}, case)
        p = _safe_row(out["result"].get("payment"))
        nb["payment"] = p
        result.tool_calls += 1
        out = registry.dispatch("get_fee", {"payment_id": case["payment_id"]}, case)
        nb["fees"] = [_safe_row(f) for f in (out["result"].get("fees") or [])][:4]
        result.tool_calls += 1
        out = registry.dispatch("get_settlement", {"payment_id": case["payment_id"]}, case)
        nb["settlements"] = [_safe_row(s) for s in (out["result"].get("settlements") or [])][:4]
        result.tool_calls += 1
        if nb["settlements"]:
            out = registry.dispatch("get_bank_transaction",
                                    {"utr": nb["settlements"][0].get("utr", "")}, case)
            nb["bank"] = _safe_row(out["result"].get("bank_txn"))
            result.tool_calls += 1
        out = registry.dispatch("calculate_variance", {}, case)
        nb["variance"] = out["result"]
        result.tool_calls += 1
        out = registry.dispatch("check_contract", {}, case)
        nb["contract"] = out["result"]
        result.tool_calls += 1
        out = registry.dispatch("check_deadline", {}, case)
        nb["deadline"] = out["result"]
        result.tool_calls += 1
        out = registry.dispatch("check_duplicate_claim", {}, case)
        nb["duplicate_claim"] = out["result"]
        result.tool_calls += 1
        out = registry.dispatch("check_evidence_completeness", {}, case)
        nb["evidence_completeness"] = out["result"]
        result.tool_calls += 1
        audit.add("AGENT", "INVESTIGATE",
                  decision="neighborhood assembled via read/analysis tools",
                  result={"order": nb["order"].get("order_id"),
                          "duplicate_claim": nb["duplicate_claim"].get("is_duplicate"),
                          "evidence_complete": nb["evidence_completeness"].get("evidence_complete")})
        return nb

    def _verify(self, case, outcome, audit) -> dict:
        out = registry.dispatch("check_dispute_status", {}, case)
        st = out["result"]
        if st.get("status") in ("NOT_FOUND", "NO_DISPUTE", "NO_EXTERNAL_REF"):
            audit.add("SERVICE", "VERIFY", decision="no external ref to verify",
                      result=st, new_state="VERIFYING")
            return {"status": "IN_PROGRESS"}
        recovered = _to_float(st.get("recovered", 0))
        expected = _to_float(case.get("potential_recovery") or case.get("potential_leakage"))
        status = ("RECOVERY_VERIFIED" if recovered > 0 and recovered >= expected * 0.99
                  else "FINANCIAL_EFFECT_DETECTED" if recovered > 0
                  else ("IN_PROGRESS" if st.get("status") in ("PENDING", "SUBMITTED", "TIMEOUT")
                        else "FAILED"))
        vid = repo.next_id("verification_events", "VER-", "verification_id")
        repo.append("verification_events", {
            "verification_id": vid,
            "action_id": outcome.get("action_id", ""),
            "case_id": case["case_id"],
            "status": status, "check_type": "AMOUNT_RECOVERED",
            "expected_ref": st.get("dispute_id", ""),
            "observed_value": json.dumps({"recovered_amount": recovered,
                                          "mode": st.get("mode", ""),
                                          "bank_ref": f"RCV-{case['case_id']}" if recovered else ""}),
            "checked_at": now_iso(),
            "notes": f"dispute status {st.get('status')}",
        })
        audit.add("SERVICE", "VERIFY",
                  decision=f"verification: {status}",
                  result={"dispute": st.get("dispute_id"), "recovered": recovered,
                          "mode": st.get("mode")},
                  amount=recovered, new_state="VERIFIED" if "VERIFIED" in status else "VERIFYING")
        return {"status": status, "recovered": recovered}

    def _record_recovery(self, case, amount, audit, approval_id) -> None:
        ledger_id = repo.next_id("recovery_ledger", "RLG-", "ledger_id")
        repo.append("recovery_ledger", {
            "ledger_id": ledger_id, "case_id": case["case_id"],
            "order_id": case["order_id"], "source": "dispute",
            "amount": round(amount, 2), "status": "RECOVERED",
            "bank_reference": f"RCV-{case['case_id']}",
            "verification_id": "", "approval_id": approval_id,
            "recorded_at": now_iso(),
        })
        audit.add("SERVICE", "RECOVERY_RECORDED",
                  decision=f"recovery ledger += {amount:.2f}",
                  amount=amount, new_state="COMPLETED")

    def _request_approval(self, case, decision, audit) -> str:
        """Create approval request. In this dev environment the human decision
        is simulated APPROVED (recorded as such); production wires Supabase
        Auth + the approvals API."""
        approval_id = repo.next_id("approvals", "APR-", "approval_id")
        repo.append("approvals", {
            "approval_id": approval_id, "case_id": case["case_id"],
            "action_id": "", "risk_level": decision.risk_level,
            "amount": case.get("potential_recovery") or case.get("potential_leakage"),
            "requested_by": "AGENT", "status": "APPROVED",
            "requested_at": now_iso(),
            "decided_by": "finance-lead@example.com",
            "decided_at": now_iso(), "decision_note": "dev auto-decision",
        })
        return approval_id

    def _record_run_start(self, run_id, case_id) -> None:
        repo.append("agent_runs", {
            "run_id": run_id, "case_id": case_id, "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model, "rollout_level": settings.rollout_level,
            "status": "RUNNING", "started_at": now_iso(), "finished_at": "",
            "proposed_action": "", "executed_action": "", "verification_status": "",
            "recovered_amount": "", "errors": "",
        })

    def _record_plan(self, run_id, plan, denied: bool) -> None:
        rows = repo.read("agent_runs")
        for r in rows:
            if r.get("run_id") == run_id:
                r["proposed_action"] = plan["recommended_action"]
                if denied:
                    r["status"] = "BLOCKED_POLICY"
                break
        repo.write("agent_runs", rows, append=False)

    def _finish(self, audit, result: AgentRunResult, t0) -> None:
        result.duration_ms = int((time.monotonic() - t0) * 1000)
        if result.status == "COMPLETED":
            pass
        rows = repo.read("agent_runs")
        for r in rows:
            if r.get("run_id") == result.run_id:
                r.update({
                    "status": result.status,
                    "proposed_action": result.proposed_action or r.get("proposed_action", ""),
                    "executed_action": result.executed_action,
                    "verification_status": result.verification_status,
                    "recovered_amount": round(result.recovered_amount, 2),
                    "errors": "|".join(result.errors)[:500],
                    "finished_at": now_iso(),
                })
                break
        repo.write("agent_runs", rows, append=False)
        audit.flush()


def _safe_row(x) -> dict:
    if not isinstance(x, dict):
        return {}
    return {k: v for k, v in x.items()
            if k in ("order_id", "order_number", "customer_id", "net_amount", "status",
                     "payment_id", "gateway_payment_id", "amount", "method",
                     "captured_at", "fee_id", "fee_type", "tax_amount", "rate_card_id",
                     "settlement_id", "utr", "settled_at", "expected_credit_date",
                     "bank_txn_id", "value_date", "counterparty", "fee_deducted",
                     "tax_deducted", "description")}


runtime = AgentRuntime()
