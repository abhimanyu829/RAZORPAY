"""HERO CASE â€” Section 39 end-to-end demonstration.

The exact scenario from the brief:
    payment â‚¹10,000 Â· expected fee â‚¹200 Â· GST on fee â‚¹36
    expected settlement â‚¹9,764 Â· actual â‚¹9,514 Â· variance â‚¹250

This module crafts the case IN THE CANONICAL PIPELINE (raw â†’ core â†’ recon â†’
anomaly â†’ case â†’ evidence), then drives it through the live agent:
LLM reason â†’ plan â†’ policy â†’ approval â†’ create_dispute â†’ verify â†’ ledger.

It runs entirely on the CSV repository (no external service), proving the
full chain with the Â§39 numbers.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "generators"))
sys.path.insert(0, str(ROOT / "backend"))

from txn_model import money, expected_settlement           # noqa: E402
import config as gcfg                                       # noqa: E402
from app.services.repository import repo, now_iso, idempotency_idkey_safe  # noqa: E402
from app.agent.runtime import runtime                       # noqa: E402
from app.agent.prompts import build_case_payload            # noqa: E402

HERO_ORDER = "ORD-9001"
HERO_PAYMENT = "PAY-9001"
HERO_FEE = "FEE-9001"
HERO_SET = "SET-9001"
HERO_UTR = "UTR009001"
HERO_BANK = "BNK-9001"
HERO_INV = "INV-9001"
HERO_CASE = "CASE-9001"


def build_hero_universe():
    """Write the Â§39 legs into the raw tables (idempotent â€” re-runnable)."""
    raw = repo.raw
    amt = 10000.00
    fee = 200.00            # 2% CARD
    tax = 36.00             # 18% on fee
    expected_set = 9764.00  # 10000 âˆ’ 200 âˆ’ 36
    actual_set = 9514.00    # 250 short

    # ---- core rows -----------------------------------------------------
    def upsert(path, key_field, key, row):
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []
        rows = [r for r in rows if r.get(key_field) != key] + [row]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()), extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    upsert(raw / "shopify" / "customers.csv", "customer_id", "CUS-9001", {
        "customer_id": "CUS-9001", "name": "Hero Merchant Customer",
        "email": "hero@example.com", "phone": "+91-9000000001",
        "city": "Mumbai", "state": "MAHARASHTRA", "gstin": "27HERO9001GSTIN",
        "segment": "SMB", "signup_date": "2025-01-01",
        "source": "SHOPIFY", "normalized": "TRUE",
    })
    upsert(raw / "shopify" / "orders.csv", "order_id", HERO_ORDER, {
        "order_id": HERO_ORDER, "order_number": "#9001",
        "customer_id": "CUS-9001", "net_amount": "10000.00",
        "status": "PAID", "placed_at": "2025-04-01T10:00:00Z",
        "gateway_order_id": "order_hero_9001", "source": "SHOPIFY",
    })
    upsert(raw / "razorpay" / "payments.csv", "payment_id", HERO_PAYMENT, {
        "payment_id": HERO_PAYMENT, "order_id": HERO_ORDER,
        "gateway_payment_id": "pay_hero_9001", "amount": "10000.00",
        "method": "CARD", "status": "CAPTURED", "currency": "INR",
        "captured_at": "2025-04-01T10:05:00Z", "settled": "TRUE", "source": "RAZORPAY",
    })
    upsert(raw / "razorpay" / "gateway_fees.csv", "fee_id", HERO_FEE, {
        "fee_id": HERO_FEE, "payment_id": HERO_PAYMENT, "fee_type": "MDR",
        "amount": "200.00", "tax_amount": "36.00", "rate_card_id": "RC-CARD-2025",
        "reversal_of_fee_id": "", "source": "RAZORPAY",
    })
    upsert(raw / "razorpay" / "settlements.csv", "settlement_id", HERO_SET, {
        "settlement_id": HERO_SET, "payment_id": HERO_PAYMENT,
        "amount": "9514.00", "fee_deducted": "200.00", "tax_deducted": "36.00",
        "utr": HERO_UTR, "expected_credit_date": "2025-04-04",
        "settled_at": "2025-04-04T10:05:00Z", "status": "PROCESSED",
        "source": "RAZORPAY",
    })
    upsert(raw / "bank" / "bank_transactions.csv", "bank_txn_id", HERO_BANK, {
        "bank_txn_id": HERO_BANK, "utr": HERO_UTR, "amount": "9514.00",
        "value_date": "2025-04-05", "direction": "CREDIT",
        "counterparty": "RAZORPAY SOFTWARE PVT LTD",
        "description": "settlement order_hero_9001", "source": "BANK",
    })
    upsert(raw / "accounting" / "invoices.csv", "invoice_id", HERO_INV, {
        "invoice_id": HERO_INV, "order_id": HERO_ORDER,
        "invoice_number": "INV/2025/9001", "taxable_value": "8474.58",
        "gst_amount": "1525.42", "total_amount": "10000.00",
        "status": "ISSUED", "source": "ACCOUNTING",
    })

    # ---- deterministic recon + anomaly + case + evidence ----------------
    def upsert_k(path, composite, row):
        k, v = composite.split(":")
        upsert(path, k, v, row)
    stage = repo.stage
    upsert_k(stage / "reconciliation_results.csv", "recon_result_id:RCN-9001", {
        "recon_result_id": "RCN-9001", "reconcile_run_id": "RUN-HERO",
        "direction": "SETTLEMENT_VS_PAYMENT", "left_entity": "core.payments",
        "left_record_id": HERO_PAYMENT, "right_entity": "core.settlements",
        "right_record_id": HERO_SET, "status": "MISMATCH",
        "expected_amount": "9764.00", "actual_amount": "9514.00",
        "variance": "250.00", "explained_variance": "0",
        "unexplained_variance": "250.00", "variance_class": "LEAKAGE",
        "tolerance_id": "TOL-SETTLEMENT", "matched_at": now_iso(),
        "notes": "LEAKAGE on SETTLEMENT_VS_PAYMENT",
    })
    upsert_k(stage / "anomaly_results.csv", "anomaly_id:ANM-9001", {
        "anomaly_id": "ANM-9001", "recon_result_id": "RCN-9001",
        "order_id": HERO_ORDER, "payment_id": HERO_PAYMENT,
        "category": "SETTLEMENT_MISMATCH", "detection_rule": "FR-SETTLE-CALC-001",
        "detected_amount": "250.00", "variance_class": "LEAKAGE",
        "severity": "MEDIUM", "explanation": "settlement short beyond tolerance",
        "candidate_root_causes":
            "settlement amount short|settlement missing|bank credit mismatch",
        "detected_at": now_iso(),
    })
    upsert_k(stage / "recovery_cases.csv", "case_id:" + HERO_CASE, {
        "case_id": HERO_CASE, "anomaly_id": "ANM-9001", "order_id": HERO_ORDER,
        "payment_id": HERO_PAYMENT, "customer_id": "CUS-9001",
        "category": "SETTLEMENT_MISMATCH", "priority": "MEDIUM", "status": "NEW",
        "expected_fee": "200.00", "expected_tax": "36.00",
        "expected_settlement": "9764.00", "actual_fee": "200.00",
        "actual_tax": "36.00", "actual_settlement": "9514.00",
        "known_adjustments": "0", "refund_status": "NONE", "recon_status": "MISMATCH",
        "potential_leakage": "250.00", "confidence": "0.90",
        "recoverability_status": "ACTION_READY", "potential_recovery": "250.00",
        "deadline_at": "2026-04-05T00:00:00Z",
        "allowed_actions": "DRAFT_DISPUTE|CREATE_DISPUTE|NOTIFY_GATEWAY|FINANCE_REVIEW|ESCALATE",
        "approval_required": "TRUE", "opened_at": now_iso(), "closed_at": "",
    })
    for evid, kind, ref, desc in [
        ("EVID-90001", "RECON_RESULT", "ops.reconciliation_results:RCN-9001",
         "settlement â‚¹9514 vs expected â‚¹9764 â€” variance â‚¹250"),
        ("EVID-90002", "RULE_RESULT", "cfg.financial_rules:FR-SETTLE-CALC-001",
         "rule engine: variance exceeds tolerance, class LEAKAGE"),
        ("EVID-90003", "RAW_PAYLOAD", "raw.raw_source_records:payments:pay_hero_9001",
         "raw gateway payload for payment pay_hero_9001"),
        ("EVID-90004", "BANK_CREDIT", f"core.bank_transactions:{HERO_BANK}",
         "bank credit â‚¹9514 UTR009001 matches settlement exactly"),
    ]:
        upsert_k(stage / "evidence_records.csv", "evidence_id:" + evid, {
            "evidence_id": evid, "case_id": HERO_CASE, "recon_result_id": "RCN-9001",
            "evidence_kind": kind, "source_system": "ENGINE",
            "source_reference": ref, "description": desc,
            "payload_sha256": "hero" + evid[-5:], "collected_at": now_iso(),
        })
    print(f"hero universe ready: {HERO_ORDER} Rs.10,000 -> expected settle Rs.9,764, "
          f"actual Rs.9,514, variance Rs.250")


def reset_runtime():
    """Clear runtime artifacts (actions/approvals/verifications/audit/runs/ledger)
    so scenario sweeps start from a clean slate. Never touches raw/core/staging.
    Tolerates transient file locks (e.g. a concurrently running API server):
    on a locked file, empties contents instead of deleting."""
    import time
    for t in ("recovery_actions", "approvals", "verification_events",
              "audit_ledger", "agent_runs", "recovery_ledger"):
        p = repo.runtime / f"{t}.csv"
        if not p.exists():
            continue
        for attempt in range(3):
            try:
                p.unlink()
                break
            except PermissionError:
                if attempt == 2:
                    # last resort: truncate contents (CSV readers then see 0 rows)
                    with open(p, "w", encoding="utf-8") as f:
                        f.truncate(0)
                else:
                    time.sleep(0.2)


def run_hero(escalation_mode: str = "success", fresh_runtime: bool = False):
    """Drive the hero case through the live agent (Section 39)."""
    if fresh_runtime:
        reset_runtime()
    build_hero_universe()
    from app.tools.simulator import simulator
    simulator.clear_forced()
    if escalation_mode:
        simulator.force(HERO_CASE, escalation_mode)
    res = runtime.run_case(HERO_CASE)
    return res


if __name__ == "__main__":
    import json
    mode = sys.argv[1] if len(sys.argv) > 1 else "success"
    res = run_hero(mode)
    print(json.dumps({
        "status": res.status,
        "proposed_action": res.proposed_action,
        "executed_action": res.executed_action,
        "action_id": res.action_id,
        "verification_status": res.verification_status,
        "recovered_amount": res.recovered_amount,
        "errors": res.errors,
    }, indent=2))
