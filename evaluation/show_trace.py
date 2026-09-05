"""Sample rows for docs — pulls real, consistent rows from the generated data
for the end-to-end example transaction (Section 26/27 of the brief)."""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
STAGE = ROOT / "data" / "staging"


def load(p):
    return list(csv.DictReader(open(p, encoding="utf-8")))


def show(order_id):
    print(f"=== END-TO-END TRANSACTION TRACE: {order_id} ===\n")
    o = [r for r in load(RAW / "shopify" / "orders.csv") if r["order_id"] == order_id][0]
    print("ORDER:", {k: o[k] for k in ("order_id", "order_number", "customer_id", "net_amount", "status", "gateway_order_id")})
    pays = [r for r in load(RAW / "razorpay" / "payments.csv") if r["order_id"] == order_id]
    for p in pays:
        print("PAYMENT:", {k: p[k] for k in ("payment_id", "gateway_payment_id", "amount", "method", "status", "captured_at")})
        fees = [r for r in load(RAW / "razorpay" / "gateway_fees.csv") if r["payment_id"] == p["payment_id"]]
        for f in fees:
            print("  FEE:", {k: f[k] for k in ("fee_id", "fee_type", "amount", "tax_amount", "rate_card_id")})
        sets = [r for r in load(RAW / "razorpay" / "settlements.csv") if r["payment_id"] == p["payment_id"]]
        for s in sets:
            print("  SETTLEMENT:", {k: s[k] for k in ("settlement_id", "amount", "fee_deducted", "tax_deducted", "utr", "settled_at", "status")})
            banks = [r for r in load(RAW / "bank" / "bank_transactions.csv") if r["utr"] == s["utr"]]
            for b in banks:
                print("    BANK:", {k: b[k] for k in ("bank_txn_id", "utr", "amount", "value_date", "counterparty")})
        refs = [r for r in load(RAW / "razorpay" / "refunds.csv") if r["payment_id"] == p["payment_id"]]
        for r in refs:
            print("  REFUND:", {k: r[k] for k in ("refund_id", "amount", "status", "processed_at")})
    invs = [r for r in load(RAW / "accounting" / "invoices.csv") if r["order_id"] == order_id]
    for i in invs:
        print("INVOICE:", {k: i[k] for k in ("invoice_id", "invoice_number", "taxable_value", "gst_amount", "total_amount")})
        gsts = [r for r in load(RAW / "accounting" / "gst_records.csv") if r["invoice_id"] == i["invoice_id"]]
        for g in gsts:
            print("  GST:", {k: g[k] for k in ("gst_record_id", "gst_type", "igst", "cgst", "sgst", "total_tax", "itc_eligible", "itc_matched")})
    # engine findings
    cases = [r for r in load(STAGE / "recovery_cases.csv") if r["order_id"] == order_id]
    for c in cases:
        print("CASE:", {k: c[k] for k in ("case_id", "category", "priority", "potential_leakage",
                                          "expected_settlement", "actual_settlement", "status",
                                          "recoverability_status", "deadline_at")})
    acts = [r for r in load(STAGE / "recovery_actions.csv") if r["case_id"] in {c["case_id"] for c in cases}]
    for a in acts:
        print("ACTION:", {k: a[k] for k in ("action_id", "action_type", "risk_level", "status", "approval_id")})
    vers = [r for r in load(STAGE / "verification_events.csv") if r["case_id"] in {c["case_id"] for c in cases}]
    for v in vers:
        print("VERIFICATION:", {k: v[k] for k in ("verification_id", "status", "check_type", "observed_value")})
    print()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if target:
        show(target)
    else:
        # one healthy + one of each anomaly type
        gt = load(ROOT / "data" / "ground_truth" / "ground_truth.csv")
        shown = set()
        for g in gt:
            if g["anomaly_type"] and g["anomaly_type"] not in shown and len(shown) < 5:
                shown.add(g["anomaly_type"])
                show(g["order_id"])
        healthy = next(g for g in gt if g["has_anomaly"] == "FALSE")
        show(healthy["order_id"])
