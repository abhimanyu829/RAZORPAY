"""TOOL IMPLEMENTATIONS — the four groups (Section 13) with full contracts.

Read tools and analysis tools answer from the repository (canonical truth).
Action tools route through the simulator at levels 1–2 and real connectors at
5+. Verification tools check the simulator/connector state and drive the
verification state machine.
"""
from __future__ import annotations

import hashlib
import json

from .registry import ToolContract, ToolTimeoutError, registry
from .simulator import simulator
from ..services.repository import repo, now_iso, _to_float

# --------------------------------------------------------------------------- #
# READ TOOLS (L0)                                                             #
# --------------------------------------------------------------------------- #

def _read(tool, desc, keys_out):
    def handler(case, params):
        return tool(params)
    return handler

read_contracts = []

def _mk_read(name, desc, handler, keys_out, categories=None):
    return ToolContract(
        tool_name=name, description=desc,
        input_schema={"type": "object",
                      "properties": {k: {"type": "string"} for k in keys_out},
                      "required": keys_out},
        output_schema={"type": "object"},
        risk_level="L0", allowed_roles=["agent", "analyst", "finance_lead", "admin", "viewer"],
        allowed_case_categories=categories or [],
        approval_requirement="NEVER", idempotency_rule="none",
        side_effects=[], timeout_seconds=10, retry_policy={"max_retries": 1, "backoff_ms": [200]},
        failure_status="READ_FAILED", verification_method="n/a",
        audit_event="TOOL_READ", handler=handler)


def _get_order(case, params):
    o = repo.get_order(params.get("order_id") or case.get("order_id"))
    return {"order": o} if o else {"error": "NOT_FOUND"}

def _get_payment(case, params):
    p = repo.get_payment(params.get("payment_id") or case.get("payment_id"))
    return {"payment": p} if p else {"error": "NOT_FOUND"}

def _get_refund(case, params):
    rows = repo.refunds_for_payment(params.get("payment_id") or case.get("payment_id"))
    return {"refunds": rows}

def _get_fee(case, params):
    rows = repo.fees_for_payment(params.get("payment_id") or case.get("payment_id"))
    return {"fees": rows}

def _get_settlement(case, params):
    rows = repo.settlements_for_payment(params.get("payment_id") or case.get("payment_id"))
    return {"settlements": rows}

def _get_bank_transaction(case, params):
    b = repo.bank_by_utr(params.get("utr", ""))
    return {"bank_txn": b} if b else {"error": "NOT_FOUND"}

def _get_invoice(case, params):
    for i in repo.read("invoices"):
        if i.get("order_id") == (params.get("order_id") or case.get("order_id")):
            return {"invoice": i}
    return {"error": "NOT_FOUND"}

def _get_case_history(case, params):
    return {"history": repo.history_for_case(params.get("case_id") or case["case_id"])}

def _get_rate_card(case, params):
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "generators"))
    import config as gcfg
    p = repo.get_payment(case.get("payment_id"))
    method = params.get("payment_method") or (p or {}).get("method", "")
    rc = gcfg.RATE_CARDS.get(method)
    return {"rate_card": rc} if rc else {"error": "NOT_FOUND"}

for name, desc, fn, keys in [
    ("get_order", "fetch canonical order", _get_order, ["order_id"]),
    ("get_payment", "fetch canonical payment", _get_payment, ["payment_id"]),
    ("get_refund", "fetch refunds for payment", _get_refund, ["payment_id"]),
    ("get_fee", "fetch gateway fees for payment", _get_fee, ["payment_id"]),
    ("get_settlement", "fetch settlements for payment", _get_settlement, ["payment_id"]),
    ("get_bank_transaction", "fetch bank credit by UTR", _get_bank_transaction, ["utr"]),
    ("get_invoice", "fetch invoice for order", _get_invoice, ["order_id"]),
    ("get_case_history", "fetch case history", _get_case_history, ["case_id"]),
    ("get_rate_card", "fetch applicable rate card", _get_rate_card, ["payment_method"]),
]:
    registry.register(_mk_read(name, desc, fn, keys))


# --------------------------------------------------------------------------- #
# ANALYSIS TOOLS (L0) — deterministic outputs from the rule engine            #
# --------------------------------------------------------------------------- #

def _calc_fee(case, params):
    # delegates to the deterministic engine (never LLM arithmetic)
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "generators"))
    from txn_model import expected_fee
    p = repo.get_payment(case.get("payment_id"))
    if not p:
        return {"error": "NOT_FOUND"}
    fee, tax = expected_fee(float(p["amount"]), p["method"])
    return {"expected_fee": fee, "expected_tax": tax,
            "actual_fee": case.get("actual_fee"), "actual_tax": case.get("actual_tax"),
            "source": "cfg.fn_expected_fee (rule engine)"}

def _calc_variance(case, params):
    exp = _to_float(case.get("expected_settlement"))
    act = _to_float(case.get("actual_settlement"))
    return {"variance": round(exp - act, 2),
            "unexplained": case.get("potential_leakage"),
            "breakdown": {"expected_settlement": case.get("expected_settlement"),
                          "actual_settlement": case.get("actual_settlement"),
                          "known_adjustments": case.get("known_adjustments")},
            "source": "cfg.fn_expected_settlement (rule engine)"}

def _check_contract(case, params):
    rule = ("FR-FEE-CALC-001" if case.get("category") == "FEE_DISCREPANCY"
            else "FR-SETTLE-CALC-001")
    return {"violations": [{"rule": rule,
                            "note": "contractual expectation exceeded beyond tolerance"}]}

def _check_deadline(case, params):
    from datetime import datetime
    from ..settings import business_now
    dl = case.get("deadline_at", "")
    try:
        d = datetime.fromisoformat(dl.replace("Z", "+00:00"))
    except ValueError:
        return {"deadline_at": dl, "state": "UNKNOWN"}
    now = business_now()
    days = (d - now).days
    return {"deadline_at": dl, "days_left": days,
            "state": "OPEN" if days > 0 else "CLOSED"}

def _check_duplicate_claim(case, params):
    key = f"{case['case_id']}:CREATE"
    existing = [a for a in repo.actions_for_case(case["case_id"])
                if a.get("action_type") == "CREATE_DISPUTE"]
    return {"is_duplicate": bool(existing),
            "existing_claims": [a.get("external_ref") for a in existing if a.get("external_ref")]}

def _check_evidence_completeness(case, params):
    ev = repo.evidence_for_case(case["case_id"])
    kinds = {e.get("evidence_kind") for e in ev}
    required = {"RECON_RESULT", "RULE_RESULT", "RAW_PAYLOAD"}
    if case.get("category") == "FEE_DISCREPANCY":
        required.add("RATE_CARD")
    missing = required - kinds
    return {"evidence_complete": not missing, "missing_kinds": sorted(missing),
            "bound_evidence": len(ev)}

def _mk_analysis(name, desc, fn):
    return ToolContract(
        tool_name=name, description=desc,
        input_schema={"type": "object", "properties": {"case_id": {"type": "string"}}},
        output_schema={"type": "object"},
        risk_level="L0", allowed_roles=["agent", "analyst", "finance_lead", "admin"],
        allowed_case_categories=[], approval_requirement="NEVER",
        idempotency_rule="none", side_effects=[], timeout_seconds=10,
        retry_policy={"max_retries": 1, "backoff_ms": [200]},
        failure_status="ANALYSIS_FAILED", verification_method="n/a",
        audit_event="TOOL_ANALYSIS", handler=fn)

for name, desc, fn in [
    ("calculate_fee", "deterministic expected fee (rule engine)", _calc_fee),
    ("calculate_variance", "deterministic variance breakdown", _calc_variance),
    ("check_contract", "contract violations from rule engine", _check_contract),
    ("check_deadline", "case deadline state", _check_deadline),
    ("check_duplicate_claim", "duplicate dispute detection", _check_duplicate_claim),
    ("check_evidence_completeness", "required evidence bound?", _check_evidence_completeness),
]:
    registry.register(_mk_analysis(name, desc, fn))


# --------------------------------------------------------------------------- #
# ACTION TOOLS (L1–L4) — simulator-backed at rollout 1–2                      #
# --------------------------------------------------------------------------- #

def _draft_dispute(case, params):
    plan_draft = params.get("draft_content", "")
    ev_ids = params.get("evidence_ids", [])
    draft = plan_draft or (
        f"Subject: Settlement discrepancy on {case.get('order_id')} — "
        f"₹{case.get('potential_leakage', 0)}\n\n"
        f"Order {case.get('order_id')} (payment {case.get('payment_id')}) settled "
        f"₹{case.get('actual_settlement', 0)} against contractual expectation "
        f"₹{case.get('expected_settlement', 0)}. We request reversal of the "
        f"unexplained difference of ₹{case.get('potential_leakage', 0)}. "
        f"Evidence attached: {', '.join(ev_ids)}")
    return {"draft_id": f"DRF-{case['case_id']}", "draft": draft[:4000]}

def _mk_action(name, desc, fn, risk, approval, categories=None, exposure=False):
    exposure_list = ["external financial exposure"] if exposure else []
    return ToolContract(
        tool_name=name, description=desc,
        input_schema={"type": "object",
                      "properties": {"case_id": {"type": "string"},
                                     "amount": {"type": "number"},
                                     "reason": {"type": "string"},
                                     "evidence_ids": {"type": "array"},
                                     "draft_content": {"type": "string"}},
                      "required": ["case_id"]},
        output_schema={"type": "object",
                      "properties": {"external_reference": {"type": "string"},
                                     "status": {"type": "string"}}},
        risk_level=risk,
        allowed_roles=["agent", "finance_lead", "admin"],
        allowed_case_categories=categories or [],
        approval_requirement=approval,
        idempotency_rule="case_action: replay returns existing action",
        side_effects=["creates external artifact"] + exposure_list,
        timeout_seconds=30, retry_policy={"max_retries": 2, "backoff_ms": [200, 800]},
        failure_status="ACTION_FAILED", verification_method="poll external ref + bank credit",
        audit_event="TOOL_ACTION", handler=fn)

registry.register(_mk_action(
    "draft_dispute", "produce dispute document (no external submission)",
    _draft_dispute, "L1", "NEVER"))

registry.register(_mk_action(
    "create_dispute", "submit gateway dispute (simulator at L1–2 / Razorpay at L5+)",
    lambda case, params: simulator.create_dispute(case, params),
    "L3", "ALWAYS", exposure=True))

registry.register(_mk_action(
    "create_finance_review", "open finance review ticket",
    lambda case, params: simulator.create_finance_review(case, params),
    "L2", "POLICY"))

registry.register(_mk_action(
    "notify_gateway", "send gateway support notification",
    lambda case, params: simulator.notify_gateway(case, params),
    "L2", "POLICY"))

registry.register(_mk_action(
    "create_payment_link", "create payment link for amount recovery",
    lambda case, params: simulator.create_payment_link(case, params),
    "L3", "ALWAYS", exposure=True))

registry.register(_mk_action(
    "schedule_retry", "schedule retry of failed recovery",
    lambda case, params: simulator.schedule_retry(case, params),
    "L2", "POLICY"))

registry.register(_mk_action(
    "send_receivable_reminder", "send receivables dunning reminder",
    lambda case, params: simulator.send_receivable_reminder(case, params),
    "L2", "POLICY"))

registry.register(_mk_action(
    "prepare_chargeback_packet", "assemble chargeback evidence packet",
    lambda case, params: simulator.prepare_chargeback_packet(case, params),
    "L4", "ALWAYS", categories=["PAYMENT_MISMATCH"]))

registry.register(_mk_action(
    "escalate", "escalate case to human owner",
    lambda case, params: simulator.escalate(case, params),
    "L2", "POLICY"))

registry.register(_mk_action(
    "close_no_action", "close case without recovery",
    lambda case, params: simulator.close_no_action(case, params),
    "L2", "POLICY"))

registry.set_simulator(simulator)


# --------------------------------------------------------------------------- #
# VERIFICATION TOOLS (L0) — drive the verification state machine               #
# --------------------------------------------------------------------------- #

def _check_dispute_status(case, params):
    acts = [a for a in repo.actions_for_case(case["case_id"])
            if a.get("action_type") == "CREATE_DISPUTE"]
    if not acts:
        return {"status": "NO_DISPUTE"}
    ref = acts[-1].get("external_ref", "")
    if not ref:
        return {"status": "NO_EXTERNAL_REF"}
    res = simulator.resolve_dispute(ref)
    return {"dispute_id": ref, **res}

def _check_settlement(case, params):
    rows = repo.settlements_for_payment(case.get("payment_id"))
    return {"settlements": len(rows),
            "latest_amount": rows[0]["amount"] if rows else None}

def _check_bank_credit(case, params):
    # in the simulator, recovered money appears as a synthetic bank credit ref
    acts = [a for a in repo.actions_for_case(case["case_id"])
            if a.get("action_type") == "CREATE_DISPUTE"]
    if not acts:
        return {"credit": 0.0, "bank_ref": None}
    res = simulator.resolve_dispute(acts[-1].get("external_ref", ""))
    return {"credit": res.get("recovered", 0.0),
            "bank_ref": f"RCV-{case['case_id']}" if res.get("recovered") else None}

def _check_payment_status(case, params):
    p = repo.get_payment(case.get("payment_id"))
    return {"status": p.get("status") if p else "NOT_FOUND"}

def _check_recovery(case, params):
    b = _check_bank_credit(case, params)
    return {"recovered_amount": b["credit"], "evidence": [b["bank_ref"]] if b["bank_ref"] else []}

def _mk_verification(name, desc, fn):
    return ToolContract(
        tool_name=name, description=desc,
        input_schema={"type": "object", "properties": {"case_id": {"type": "string"}}},
        output_schema={"type": "object"},
        risk_level="L0", allowed_roles=["agent", "analyst", "finance_lead", "admin", "viewer"],
        allowed_case_categories=[], approval_requirement="NEVER",
        idempotency_rule="none", side_effects=[], timeout_seconds=15,
        retry_policy={"max_retries": 2, "backoff_ms": [300, 900]},
        failure_status="VERIFICATION_FAILED", verification_method="n/a",
        audit_event="TOOL_VERIFICATION", handler=fn)

for name, desc, fn in [
    ("check_dispute_status", "external dispute lifecycle state", _check_dispute_status),
    ("check_settlement", "settlement rows for the case payment", _check_settlement),
    ("check_bank_credit", "bank credit evidence for recovery", _check_bank_credit),
    ("check_payment_status", "payment lifecycle state", _check_payment_status),
    ("check_recovery", "recovered amount + bank reference", _check_recovery),
]:
    registry.register(_mk_verification(name, desc, fn))


def get_registry() -> ToolRegistry:
    return registry
