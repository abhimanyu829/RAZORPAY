"""AI RECOVERY AGENT — bounded loop: OBSERVE → INVESTIGATE → REASON → PLAN →
ACT → VERIFY → STOP/ESCALATE.

The agent consumes ONLY the structured case object (ops.v_case_full shape)
plus tool results. It NEVER computes money — all amounts come from the case
and tools (rule engine outputs). The LLM role in production is: root-cause
narrative, evidence selection, prioritization, dispute drafting. This module
executes the deterministic skeleton of that loop and records every step to
the audit ledger with a hash chain, so the full lifecycle is demonstrable
end-to-end (and evaluable) without an actual LLM call.

Risk gating (mirror of cfg.recovery_policies + ops.agent_tools):
  L0/L1  read/draft        → automatic
  L2     reversible        → automatic below policy auto_approve_below
  L3     financial        → human approval ALWAYS
  L4     tax/legal        → human approval ALWAYS (mandatory)
"""
import csv
import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "generators"))
import config as C
from txn_model import d, money

STAGE = Path(__file__).resolve().parents[1] / "data" / "staging"
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
EXPORTS = Path(__file__).resolve().parents[1] / "data" / "exports"
NOW = d(C.EVAL_NOW)

# risk levels per action (mirror ops.agent_tools)
ACTION_RISK = {
    "DRAFT_DISPUTE": "L1_DRAFT",
    "CREATE_DISPUTE": "L3_FINANCIAL",
    "NOTIFY_GATEWAY": "L2_REVERSIBLE",
    "NOTIFY_CUSTOMER": "L2_REVERSIBLE",
    "FINANCE_REVIEW": "L2_REVERSIBLE",
    "SCHEDULE_RETRY": "L2_REVERSIBLE",
    "ESCALATE": "L2_REVERSIBLE",
    "CLOSE_NO_ACTION": "L2_REVERSIBLE",
    "PREPARE_CHARGEBACK_PACKET": "L1_DRAFT",
    "CREATE_PAYMENT_LINK": "L3_FINANCIAL",
    "SEND_RECEIVABLE_REMINDER": "L2_REVERSIBLE",
}
# policy auto-approve thresholds per category (mirror seed.sql)
AUTO_APPROVE_BELOW = {
    "FEE_DISCREPANCY": 250,
    "SETTLEMENT_MISMATCH": 500,
    "REFUND_ECONOMICS": 250,
    "PAYMENT_MISMATCH": 250,
    "GST_ITC_REVIEW": 0,
}

seq = {"act": 0, "apr": 0, "ver": 0, "ch": 0}


def load(p):
    return list(csv.DictReader(open(p, encoding="utf-8")))


def dump(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def sha(s):
    return hashlib.sha256(str(s).encode()).hexdigest()[:16]


class AuditChain:
    """Per-case hash-chained audit ledger (mirror of ops.audit_ledger)."""

    def __init__(self):
        self.rows = []
        self.last = {}

    def add(self, case_id, actor, event_type, tool_called=None, tool_params=None,
            tool_result=None, decision=None, prev_state=None, new_state=None,
            amount=None, evidence_ids=None, approval_id=None, corr=None):
        prev = self.last.get(case_id, "GENESIS")
        entry = {
            "audit_id": f"AUD-{len(self.rows) + 1:05d}", "case_id": case_id,
            "actor": actor, "event_type": event_type, "tool_called": tool_called or "",
            "tool_parameters": json.dumps(tool_params or {}),
            "tool_result": json.dumps(tool_result or {}),
            "decision": decision or "", "previous_state": prev_state or "",
            "new_state": new_state or "", "amount": amount or 0,
            "evidence_ids": "|".join(evidence_ids or []), "approval_id": approval_id or "",
            "correlation_id": corr or f"CORR-{case_id}",
            "prev_hash": prev, "created_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        entry["entry_hash"] = sha(prev + entry["audit_id"] + event_type + str(amount))
        self.last[case_id] = entry["entry_hash"]
        self.rows.append(entry)
        return entry


# ------------------------------------------------------------- tool registry --
class Tools:
    """Deterministic tool implementations bound to the registry (seed.sql).
    Every call is auditable; action tools are idempotent via idempotency keys."""

    def __init__(self, data, audit):
        self.data = data
        self.audit = audit
        self.disputes = {}          # idempotency_key → dispute record
        self.reviews = {}
        self.links = {}

    # ---- READ tools (L0) ----
    def get_order(self, case, params):
        o = self.data["orders_by_id"].get(params["order_id"])
        return {"order": o} if o else {"error": "NOT_FOUND"}

    def get_payment(self, case, params):
        p = self.data["pays_by_id"].get(params["payment_id"])
        return {"payment": p} if p else {"error": "NOT_FOUND"}

    def get_refund(self, case, params):
        rows = self.data["refunds_by_pay"].get(params["payment_id"], [])
        return {"refunds": rows}

    def get_settlement(self, case, params):
        rows = self.data["sets_by_pay"].get(params["payment_id"], [])
        return {"settlements": rows}

    def get_bank_transaction(self, case, params):
        b = self.data["banks_by_utr"].get(params["utr"])
        return {"bank_txns": [b] if b else []}

    def get_invoice(self, case, params):
        i = self.data["invoice_by_order"].get(params["order_id"])
        return {"invoice": i} if i else {"error": "NOT_FOUND"}

    def get_rate_card(self, case, params):
        rc = C.RATE_CARDS.get(params.get("payment_method") or case.get("method_hint", ""))
        return {"rate_card": rc} if rc else {"error": "NOT_FOUND"}

    def get_case_history(self, case, params):
        rows = [h for h in self.data["history"] if h["case_id"] == params["case_id"]]
        return {"history": rows}

    # ---- ANALYSIS tools (L0) ----
    def calculate_fee(self, case, params):
        # returns rule-engine output already stored on the case (deterministic)
        return {"expected_fee": case["expected_fee"], "expected_tax": case["expected_tax"],
                "actual_fee": case["actual_fee"], "actual_tax": case["actual_tax"],
                "source": "cfg.fn_expected_fee (rule engine)"}

    def calculate_variance(self, case, params):
        return {"variance": money(float(case["expected_settlement"]) - float(case["actual_settlement"])),
                "unexplained": case["potential_leakage"],
                "breakdown": {"expected_settlement": case["expected_settlement"],
                              "actual_settlement": case["actual_settlement"],
                              "known_adjustments": case["known_adjustments"]},
                "source": "cfg.fn_expected_settlement (rule engine)"}

    def check_contract(self, case, params):
        basis = "FR-FEE-CALC-001" if case["category"] == "FEE_DISCREPANCY" else "FR-SETTLE-CALC-001"
        return {"violations": [{"rule": basis,
                                "note": "contractual expectation exceeded beyond tolerance"}]}

    def check_deadline(self, case, params):
        dl = d(case["deadline_at"])
        days = (dl - NOW).days
        return {"deadline_at": case["deadline_at"], "days_left": days,
                "state": "OPEN" if days > 0 else "CLOSED"}

    def check_duplicate_claim(self, case, params):
        key = case["case_id"]
        dup = self.disputes.get(key)
        return {"is_duplicate": dup is not None,
                "existing_claims": [dup["dispute_id"]] if dup else []}

    # ---- ACTION tools ----
    def draft_dispute(self, case, params):
        # L1: automatic. Produces the dispute document from case + evidence.
        draft = {
            "draft_id": f"DRF-{case['case_id']}", "case_id": case["case_id"],
            "to": "payments-support@razorpay.com",
            "subject": f"Settlement discrepancy on {case['order_id']} — ₹{case['potential_leakage']}",
            "body": (f"Order {case['order_id']} (payment {case['payment_id']}) was settled "
                     f"₹{case['actual_settlement']} against a contractual expectation of "
                     f"₹{case['expected_settlement']} (rate card + GST on MDR). "
                     f"We request a review and reversal of the unexplained difference of "
                     f"₹{case['potential_leakage']}. Evidence attached: "
                     + ", ".join(params.get("evidence_ids", []))),
            "amount": case["potential_leakage"],
        }
        return {"draft": draft, "draft_id": draft["draft_id"]}

    def create_dispute(self, case, params):
        # L3: requires approval (checked by caller). Idempotent by case key.
        key = case["case_id"]
        if key in self.disputes:
            return {"dispute_id": self.disputes[key]["dispute_id"], "status": "EXISTING"}
        dispute = {"dispute_id": f"DIS-{case['case_id']}", "case_id": key,
                   "amount": case["potential_leakage"],
                   "status": "SUBMITTED", "submitted_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ")}
        self.disputes[key] = dispute
        return {"dispute_id": dispute["dispute_id"], "status": "SUBMITTED"}

    def notify_gateway(self, case, params):
        return {"ticket_id": f"TIC-{case['case_id']}", "status": "SENT"}

    def create_finance_review(self, case, params):
        key = case["case_id"]
        if key in self.reviews:
            return {"review_id": self.reviews[key], "status": "EXISTING"}
        rid = f"REV-{case['case_id']}"
        self.reviews[key] = rid
        return {"review_id": rid, "status": "OPENED"}

    def escalate(self, case, params):
        return {"escalation_id": f"ESC-{case['case_id']}", "status": "ESCALATED"}

    def close_no_action(self, case, params):
        return {"status": "CLOSED_NO_ACTION", "reason": params.get("reason", "below tolerance / not recoverable")}

    def create_payment_link(self, case, params):
        key = f"{case['case_id']}:{params.get('amount')}"
        if key in self.links:
            return self.links[key]
        link = {"link_id": f"PL-{sha(key)}", "url": f"https://rzp.io/i/{sha(key)}",
                "amount": params.get("amount")}
        self.links[key] = link
        return link

    # ---- VERIFICATION tools (L0) ----
    def check_settlement(self, case, params):
        rows = self.data["sets_by_pay"].get(case["payment_id"], [])
        return {"changed": False, "new_amount": rows[0]["amount"] if rows else None}

    def check_dispute_status(self, case, params):
        dip = self.disputes.get(case["case_id"])
        if not dip:
            return {"status": "NOT_FOUND"}
        return {"status": dip["status"], "dispute_id": dip["dispute_id"]}

    def check_payment_status(self, case, params):
        p = self.data["pays_by_id"].get(case["payment_id"])
        return {"status": p["status"] if p else "NOT_FOUND"}

    def check_recovery(self, case, params):
        # deterministic: does the money appear? (recovery simulator sets this)
        rec = self.data["recoveries"].get(case["case_id"])
        return {"recovered_amount": rec["amount"] if rec else 0,
                "evidence": [rec["bank_ref"]] if rec else []}


# ---------------------------------------------------------------- gating ----
def requires_approval(action, case):
    risk = ACTION_RISK.get(action)
    if risk in ("L0_READ", "L1_DRAFT"):
        return False, risk
    if risk == "L2_REVERSIBLE":
        cap = AUTO_APPROVE_BELOW.get(case["category"], 0)
        return float(case["potential_leakage"]) > cap, risk
    # L3_FINANCIAL, L4_TAX_LEGAL
    return True, risk


# ------------------------------------------------------------------ loop ----
def run_agent():
    data = {
        "orders_by_id": {o["order_id"]: o for o in load(RAW / "shopify" / "orders.csv")},
        "pays_by_id": {p["payment_id"]: p for p in load(RAW / "razorpay" / "payments.csv")},
        "pays_by_order": {},
        "refunds_by_pay": {}, "sets_by_pay": {}, "banks_by_utr": {},
        "invoice_by_order": {i["order_id"]: i for i in load(RAW / "accounting" / "invoices.csv")},
        "history": load(STAGE / "case_history.csv"),
        "recoveries": {},          # filled by recovery simulator
    }
    for p in load(RAW / "razorpay" / "payments.csv"):
        data["pays_by_order"].setdefault(p["order_id"], []).append(p)
    for r in load(RAW / "razorpay" / "refunds.csv"):
        data["refunds_by_pay"].setdefault(r["payment_id"], []).append(r)
    for s in load(RAW / "razorpay" / "settlements.csv"):
        data["sets_by_pay"].setdefault(s["payment_id"], []).append(s)
    for b in load(RAW / "bank" / "bank_transactions.csv"):
        data["banks_by_utr"][b["utr"]] = b

    cases = load(STAGE / "recovery_cases.csv")
    evidence = load(STAGE / "evidence_records.csv")
    evidence_by_case = {}
    for e in evidence:
        evidence_by_case.setdefault(e["case_id"], []).append(e["evidence_id"])

    # recovery simulator (ground truth-driven outcomes, deterministic sample):
    # 70% of disputes succeed fully, 20% partial (60%), 10% fail.
    import random
    rng = random.Random(C.RANDOM_SEED)
    for c in cases:
        r = rng.random()
        if r < 0.70:
            data["recoveries"][c["case_id"]] = {"amount": c["potential_leakage"], "bank_ref": f"RCV-{c['case_id']}", "mode": "FULL"}
        elif r < 0.90:
            data["recoveries"][c["case_id"]] = {"amount": money(float(c["potential_leakage"]) * 0.6), "bank_ref": f"RCV-{c['case_id']}", "mode": "PARTIAL"}
        else:
            data["recoveries"][c["case_id"]] = {"amount": 0, "bank_ref": "", "mode": "FAILED"}

    audit = AuditChain()
    tools = Tools(data, audit)
    approvals, actions, verifications, history = [], [], [], []

    # priority ordering: amount desc (bounded planning: agent works the biggest first)
    cases.sort(key=lambda c: float(c["potential_leakage"]), reverse=True)

    for c in cases:
        cid = c["case_id"]
        corr = f"CORR-{cid}"
        ev_ids = evidence_by_case.get(cid, [])

        # OBSERVE (read-only tool calls, all audited)
        audit.add(cid, "AGENT", "OBSERVE", tool_called="get_case_history",
                  tool_params={"case_id": cid}, decision="case loaded",
                  new_state="INVESTIGATING", evidence_ids=ev_ids, corr=corr)
        seq["ch"] += 1
        history.append({"history_id": f"CH-A{seq['ch']:05d}", "case_id": cid,
                        "event_type": "STATUS_CHANGE", "old_status": "NEW",
                        "new_status": "INVESTIGATING", "actor": "AGENT",
                        "message": "agent began investigation", "payload": "",
                        "event_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ")})

        # INVESTIGATE: read tools for the financial neighborhood
        r1 = tools.get_order(c, {"order_id": c["order_id"]})
        r2 = tools.get_settlement(c, {"payment_id": c["payment_id"]})
        r3 = tools.get_bank_transaction(c, {"utr": (r2.get("settlements") or [{}])[0].get("utr", "")})
        audit.add(cid, "AGENT", "INVESTIGATE", tool_called="get_order|get_settlement|get_bank_transaction",
                  tool_params={"order_id": c["order_id"], "payment_id": c["payment_id"]},
                  tool_result={"settlements_found": len(r2.get("settlements") or []),
                               "bank_found": bool(r3.get("bank_txns"))},
                  decision="financial neighborhood assembled", evidence_ids=ev_ids, corr=corr)

        # REASON: rule-engine outputs (never LLM arithmetic)
        v = tools.calculate_variance(c, {})
        k = tools.check_contract(c, {})
        dl = tools.check_deadline(c, {})
        dup = tools.check_duplicate_claim(c, {})
        audit.add(cid, "AGENT", "REASON", tool_called="calculate_variance|check_contract|check_deadline|check_duplicate_claim",
                  tool_params={"case_id": cid},
                  tool_result={"variance": v["variance"], "unexplained": v["unexplained"],
                               "violations": len(k["violations"]), "deadline_state": dl["state"],
                               "is_duplicate": dup["is_duplicate"]},
                  decision="root cause candidates: " + c["category"], evidence_ids=ev_ids, corr=corr)

        # PLAN: pick action by policy (bounded; from allowed_actions only)
        allowed = c["allowed_actions"].split("|")
        planned = c["recommended"] if "recommended" in c else None
        if dup["is_duplicate"]:
            planned = "CLOSE_NO_ACTION"
        elif dl["state"] == "CLOSED":
            planned = "ESCALATE"
        else:
            planned = next((a for a in ["DRAFT_DISPUTE", "CREATE_DISPUTE", "NOTIFY_GATEWAY",
                                        "FINANCE_REVIEW", "ESCALATE"] if a in allowed), "ESCALATE")
        audit.add(cid, "AGENT", "PLAN", decision=f"planned action: {planned}",
                  tool_params={"allowed": allowed}, tool_result={"planned": planned},
                  evidence_ids=ev_ids, corr=corr)

        # ACT (with human gate where policy demands)
        needs_approval, risk = requires_approval(planned, c)
        approval_id = ""
        if planned == "DRAFT_DISPUTE":
            res = tools.draft_dispute(c, {"evidence_ids": ev_ids})
            seq["act"] += 1
            actions.append(_action(cid, "draft_dispute", planned, risk, res, ev_ids))
            audit.add(cid, "AGENT", "ACT", tool_called="draft_dispute",
                      tool_result={"draft_id": res["draft_id"]},
                      decision="dispute drafted (L1 automatic)", amount=c["potential_leakage"],
                      evidence_ids=ev_ids, corr=corr)
            # drafting done → escalate to CREATE_DISPUTE if allowed (needs approval)
            if "CREATE_DISPUTE" in allowed:
                planned = "CREATE_DISPUTE"
                needs_approval, risk = requires_approval(planned, c)
            else:
                planned = None

        if planned:
            if needs_approval:
                seq["apr"] += 1
                approval_id = f"APR-{seq['apr']:04d}"
                approvals.append({
                    "approval_id": approval_id, "case_id": cid, "action_id": f"ACT-{seq['act'] + 1:04d}",
                    "risk_level": risk, "amount": c["potential_leakage"],
                    "requested_by": "AGENT", "status": "APPROVED",  # simulated human decision
                    "requested_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "decided_by": "finance-lead@example.com",
                    "decided_at": (NOW + timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "decision_note": "evidence verified; within dispute window",
                })
                audit.add(cid, "AGENT", "APPROVAL_REQUEST", decision=f"requested approval for {planned}",
                          tool_params={"action": planned, "risk": risk},
                          amount=c["potential_leakage"], approval_id=approval_id,
                          new_state="PENDING_APPROVAL", evidence_ids=ev_ids, corr=corr)
                seq["ch"] += 1
                history.append({"history_id": f"CH-A{seq['ch']:05d}", "case_id": cid,
                                "event_type": "APPROVAL_REQUEST", "old_status": "INVESTIGATING",
                                "new_status": "PENDING_APPROVAL", "actor": "AGENT",
                                "message": f"approval {approval_id} requested for {planned}",
                                "payload": "", "event_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ")})
                audit.add(cid, "HUMAN", "APPROVAL_DECISION", decision=f"approved {planned}",
                          approval_id=approval_id, new_state="ACTING",
                          evidence_ids=ev_ids, corr=corr)

            tool_name = {
                "CREATE_DISPUTE": "create_dispute",
                "NOTIFY_GATEWAY": "notify_gateway",
                "FINANCE_REVIEW": "create_finance_review",
                "ESCALATE": "escalate",
                "CLOSE_NO_ACTION": "close_no_action",
                "NOTIFY_CUSTOMER": "notify_gateway",
                "CREATE_PAYMENT_LINK": "create_payment_link",
            }[planned]
            fn = getattr(tools, tool_name)
            res = fn(c, {"case_id": cid, "evidence_ids": ev_ids, "amount": c["potential_leakage"]})
            seq["act"] += 1
            act = _action(cid, tool_name, planned, risk, res, ev_ids, approval_id)
            actions.append(act)
            audit.add(cid, "AGENT", "ACT", tool_called=tool_name,
                      tool_params={"case_id": cid}, tool_result={"ok": True, "k": list(res)[:3]},
                      decision=f"executed {planned}", amount=c["potential_leakage"],
                      approval_id=approval_id, evidence_ids=ev_ids, corr=corr, new_state="ACTING")

            # VERIFY (verification state machine)
            if planned in ("CREATE_DISPUTE", "NOTIFY_GATEWAY"):
                st = tools.check_dispute_status(c, {})
                rec = tools.check_recovery(c, {})
                rec_amt = float(rec["recovered_amount"] or 0)
                status = ("RECOVERY_VERIFIED" if rec_amt > 0
                          and rec_amt >= float(c["potential_leakage"]) * 0.99
                          else ("FINANCIAL_EFFECT_DETECTED" if rec_amt > 0 else "IN_PROGRESS"))
                seq["ver"] += 1
                verifications.append({
                    "verification_id": f"VER-{seq['ver']:04d}", "action_id": act["action_id"],
                    "case_id": cid, "status": status,
                    "check_type": "AMOUNT_RECOVERED",
                    "expected_ref": res.get("dispute_id") or res.get("ticket_id") or "",
                    "observed_value": json.dumps({"recovered_amount": rec_amt,
                                                  "bank_ref": rec["evidence"][0] if rec["evidence"] else ""}),
                    "checked_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "notes": f"dispute {st.get('status')}; recovery {rec_amt}",
                })
                audit.add(cid, "SERVICE", "VERIFY", tool_called="check_dispute_status|check_recovery",
                          tool_result={"status": status, "recovered": rec_amt},
                          decision="verification recorded", amount=rec["recovered_amount"],
                          evidence_ids=ev_ids, corr=corr, new_state="VERIFYING")

    # ---------------------------------------------------------------- write --
    dump(STAGE / "recovery_actions.csv", actions,
         ["action_id", "case_id", "tool_id", "action_type", "actor", "status",
          "risk_level", "input_payload", "result_payload", "external_ref",
          "idempotency_key", "approval_id", "amount", "executed_at"])
    dump(STAGE / "approvals.csv", approvals,
         ["approval_id", "case_id", "action_id", "risk_level", "amount", "requested_by",
          "status", "requested_at", "decided_by", "decided_at", "decision_note"])
    dump(STAGE / "verification_events.csv", verifications,
         ["verification_id", "action_id", "case_id", "status", "check_type",
          "expected_ref", "observed_value", "checked_at", "notes"])
    dump(STAGE / "audit_ledger.csv", audit.rows,
         ["audit_id", "case_id", "actor", "event_type", "tool_called", "tool_parameters",
          "tool_result", "decision", "previous_state", "new_state", "amount",
          "evidence_ids", "approval_id", "correlation_id", "prev_hash", "entry_hash", "created_at"])
    all_hist = load(STAGE / "case_history.csv") + history
    dump(STAGE / "case_history.csv", all_hist,
         ["history_id", "case_id", "event_type", "old_status", "new_status", "actor",
          "message", "payload", "event_at"])

    print(f"agent processed {len(cases)} cases")
    print(f"actions: {len(actions)}  approvals: {len(approvals)}  verifications: {len(verifications)}  audit entries: {len(audit.rows)}")
    from collections import Counter
    print("actions by type:", dict(Counter(a["action_type"] for a in actions)))
    print("verifications:", dict(Counter(v["status"] for v in verifications)))
    return cases, actions, approvals, verifications, audit.rows


def _action(cid, tool_name, planned, risk, res, ev_ids, approval_id=""):
    seq_act = seq["act"]
    return {
        "action_id": f"ACT-{seq_act:04d}", "case_id": cid, "tool_id": tool_name,
        "action_type": planned, "actor": "AGENT", "status": "EXECUTED",
        "risk_level": risk,
        "input_payload": json.dumps({"case_id": cid, "evidence_ids": ev_ids}),
        "result_payload": json.dumps(res), "external_ref": res.get("dispute_id") or res.get("ticket_id") or res.get("review_id") or res.get("draft_id") or "",
        "idempotency_key": f"{cid}:{planned}", "approval_id": approval_id,
        "amount": "", "executed_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


if __name__ == "__main__":
    run_agent()
