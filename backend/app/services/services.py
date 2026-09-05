"""SERVICE LAYER — business services backing the API.

Thin orchestration over the repository + agent runtime + connectors. The
deterministic financial logic stays in the pipeline/generators modules (never
duplicated here).
"""
from __future__ import annotations

import json
from typing import Any

from ..settings import settings
from .repository import repo, now_iso, _to_float
from ..agent.runtime import runtime, AgentRunResult
from ..agent.prompts import build_case_payload
from ..tools.registry import registry


# ------------------------------------------------------------------ cases
class CaseService:
    def list_cases(self, status: str | None = None, category: str | None = None,
                   limit: int = 100) -> list[dict]:
        rows = repo.cases(status=status, category=category)
        rows.sort(key=lambda c: _to_float(c.get("potential_leakage")), reverse=True)
        return rows[:limit]

    def get_case(self, case_id: str) -> dict | None:
        c = repo.get_case(case_id)
        if not c:
            return None
        c = dict(c)
        c["evidence"] = repo.evidence_for_case(case_id)
        c["history"] = repo.history_for_case(case_id)
        c["actions"] = repo.actions_for_case(case_id)
        c["approvals"] = repo.approvals_for_case(case_id)
        c["verifications"] = repo.verifications_for_case(case_id)
        return c

    def timeline(self, case_id: str) -> dict | None:
        c = repo.get_case(case_id)
        if not c:
            return None
        events = []
        for h in repo.history_for_case(case_id):
            events.append({"ts": h.get("event_at"), "kind": "history",
                          "actor": h.get("actor"), "event": h.get("event_type"),
                          "detail": h.get("message")})
        for a in repo.actions_for_case(case_id):
            events.append({"ts": a.get("executed_at"), "kind": "action",
                          "actor": a.get("actor"), "event": a.get("action_type"),
                          "detail": f"{a.get('status')} risk={a.get('risk_level')}"})
        for v in repo.verifications_for_case(case_id):
            events.append({"ts": v.get("checked_at"), "kind": "verification",
                          "actor": "SERVICE", "event": v.get("status"),
                          "detail": v.get("notes", "")})
        for e in repo.evidence_for_case(case_id):
            events.append({"ts": e.get("collected_at"), "kind": "evidence",
                          "actor": "ENGINE", "event": e.get("evidence_kind"),
                          "detail": e.get("description", "")[:120]})
        for a in repo.read("audit_ledger"):
            if a.get("case_id") == case_id:
                events.append({"ts": a.get("created_at"), "kind": "audit",
                              "actor": a.get("actor"), "event": a.get("event_type"),
                              "detail": a.get("decision", "")[:120]})
        events.sort(key=lambda e: e.get("ts") or "")
        return {"case_id": case_id, "events": events}

    def money_flow(self, order_id: str) -> dict | None:
        o = repo.get_order(order_id)
        if not o:
            return None
        pays = repo.payments_for_order(order_id)
        flow = {"order": _pick(o, ["order_id", "order_number", "customer_id",
                                   "net_amount", "status", "placed_at"]),
                "payments": [], "invoice": None, "gst": []}
        for p in pays:
            pf = _pick(p, ["payment_id", "gateway_payment_id", "amount",
                           "method", "status", "captured_at"])
            fees = repo.fees_for_payment(p["payment_id"])
            refs = repo.refunds_for_payment(p["payment_id"])
            sets = repo.settlements_for_payment(p["payment_id"])
            pf["fees"] = [_pick(f, ["fee_id", "amount", "tax_amount", "rate_card_id"]) for f in fees]
            pf["refunds"] = [_pick(r, ["refund_id", "amount", "status"]) for r in refs]
            pf["settlements"] = []
            for s in sets:
                sf = _pick(s, ["settlement_id", "amount", "fee_deducted",
                               "tax_deducted", "utr", "status", "settled_at"])
                b = repo.bank_by_utr(s.get("utr", ""))
                sf["bank"] = _pick(b, ["bank_txn_id", "amount", "value_date"]) if b else None
                pf["settlements"].append(sf)
            flow["payments"].append(pf)
        for i in repo.read("invoices"):
            if i.get("order_id") == order_id:
                flow["invoice"] = _pick(i, ["invoice_id", "invoice_number",
                                            "taxable_value", "gst_amount", "total_amount"])
                inv_id = i.get("invoice_id")
                flow["gst"] = [_pick(g, ["gst_record_id", "gst_type", "igst",
                                         "cgst", "sgst", "total_tax", "itc_matched"])
                               for g in repo.read("gst_records")
                               if g.get("invoice_id") == inv_id]
                break
        return flow


# ------------------------------------------------------------------ agent
class AgentService:
    def run_case(self, case_id: str, scenario: str | None = None) -> AgentRunResult:
        return runtime.run_case(case_id, force_scenario=scenario)

    def get_run(self, run_id: str) -> dict | None:
        for r in repo.read("agent_runs"):
            if r.get("run_id") == run_id:
                return r
        return None

    def list_runs(self, limit: int = 50) -> list[dict]:
        return repo.read("agent_runs")[-limit:]

    def tools(self) -> list[dict]:
        return registry.all_contracts()

    def shadow_compare(self, case_id: str, human_action: str) -> dict:
        """Shadow-mode scoring: agent proposal vs human decision (Section 47)."""
        res = runtime.run_case(case_id)
        return {"case_id": case_id,
                "agent_proposed": res.proposed_action,
                "human_decision": human_action,
                "match": res.proposed_action == human_action,
                "run_id": res.run_id}


# -------------------------------------------------------------- approvals
class ApprovalService:
    def list(self, status: str | None = None) -> list[dict]:
        rows = repo.read("approvals")
        if status:
            rows = [a for a in rows if a.get("status") == status]
        return rows

    def decide(self, approval_id: str, decision: str, decided_by: str,
               note: str = "") -> dict | None:
        rows = repo.read("approvals")
        for a in rows:
            if a.get("approval_id") == approval_id:
                if a.get("status") in ("APPROVED", "REJECTED"):
                    return a            # idempotent decision
                a["status"] = "APPROVED" if decision == "approve" else "REJECTED"
                a["decided_by"] = decided_by
                a["decided_at"] = now_iso()
                a["decision_note"] = note
                repo.write("approvals", rows, append=False)
                return a
        return None


# ---------------------------------------------------------------- recovery
class RecoveryService:
    def kpis(self) -> dict:
        cases = repo.cases()
        actions = repo.read("recovery_actions")
        ledger = repo.read("recovery_ledger")
        approvals = repo.read("approvals")
        gt_orders = set()
        recoverable = sum(_to_float(c.get("potential_recovery")) for c in cases)
        recovered = sum(_to_float(l.get("amount")) for l in ledger
                        if l.get("status") == "RECOVERED")
        revenue = sum(_to_float(p.get("amount")) for p in repo.read("payments"))
        failed = [a for a in actions if a.get("status") not in ("EXECUTED", "EXISTING")]
        return {
            "revenue_analysed": round(revenue, 2),
            "cases_open": len(cases),
            "leakage_detected": round(sum(_to_float(c.get("potential_leakage")) for c in cases), 2),
            "recoverable_amount": round(recoverable, 2),
            "recovery_initiated": len([a for a in actions
                                       if a.get("action_type") in ("CREATE_DISPUTE", "CREATE_PAYMENT_LINK")]),
            "recovered_amount": round(recovered, 2),
            "unrecovered_amount": round(max(recoverable - recovered, 0), 2),
            "recovery_rate": round(recovered / recoverable, 4) if recoverable else 0,
            "agent_actions": len(actions),
            "failed_actions": len(failed),
            "human_escalations": len([c for c in cases if c.get("status") == "ESCALATED"]),
            "pending_approvals": len([a for a in approvals if a.get("status") == "PENDING"]),
            "rollout_level": settings.rollout_level,
        }

    def ledger(self, limit: int = 100) -> list[dict]:
        return repo.read("recovery_ledger")[-limit:]


def _pick(row: dict | None, keys: list[str]) -> dict:
    if not row:
        return {}
    return {k: row.get(k, "") for k in keys}


case_service = CaseService()
agent_service = AgentService()
approval_service = ApprovalService()
recovery_service = RecoveryService()
