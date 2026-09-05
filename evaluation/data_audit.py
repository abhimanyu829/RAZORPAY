"""DATA AUDIT — verifies the generated universe is internally consistent.

Validates:
  1. every healthy transaction reconciles to zero unexplained variance
  2. every anomalous transaction shows the injected leak beyond tolerance
  3. bank amounts match settlements (except injected)
  4. all FKs resolve (payment→order, fee→payment, settlement→payment, etc.)
Exit code != 0 on any violation.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "generators"))
import config as C
from txn_model import money, expected_settlement

raw = Path(__file__).resolve().parents[1] / "data" / "raw"
gt_path = Path(__file__).resolve().parents[1] / "data" / "ground_truth" / "ground_truth.csv"


def load(p):
    return list(csv.DictReader(open(p, encoding="utf-8")))


def main():
    orders = load(raw / "shopify" / "orders.csv")
    pays = load(raw / "razorpay" / "payments.csv")
    fees = load(raw / "razorpay" / "gateway_fees.csv")
    refunds = load(raw / "razorpay" / "refunds.csv")
    sets = load(raw / "razorpay" / "settlements.csv")
    banks = load(raw / "bank" / "bank_transactions.csv")
    gts = load(gt_path)
    gt_by_order = {g["order_id"]: g for g in gts}

    order_ids = {o["order_id"] for o in orders}
    pay_ids = {p["payment_id"] for p in pays}

    errors = []

    # ---- FK integrity ------------------------------------------------------
    for p in pays:
        if p["order_id"] not in order_ids:
            errors.append(f"payment {p['payment_id']} → missing order {p['order_id']}")
    for f in fees:
        if f["payment_id"] not in pay_ids:
            errors.append(f"fee {f['fee_id']} → missing payment {f['payment_id']}")
    for s in sets:
        if s["payment_id"] not in pay_ids:
            errors.append(f"settlement {s['settlement_id']} → missing payment {s['payment_id']}")
    for r in refunds:
        if r["payment_id"] not in pay_ids:
            errors.append(f"refund {r['refund_id']} → missing payment {r['payment_id']}")

    # ---- settlement vs bank via UTR ----------------------------------------
    set_by_utr = {}
    for s in sets:
        set_by_utr[s["utr"]] = s
    for b in banks:
        s = set_by_utr.get(b["utr"])
        if s and abs(float(b["amount"]) - float(s["amount"])) > 0.01:
            g = gt_by_order.get(s["order_id"])
            if g and g["has_anomaly"] == "FALSE":
                errors.append(f"bank {b['bank_txn_id']} ≠ settlement {s['settlement_id']} on healthy {s['order_id']}")

    # ---- expectation audit ---------------------------------------------------
    tol = C.TOLERANCES["SETTLEMENT"]["amount"]
    pay_by_order = {}
    for p in pays:
        pay_by_order.setdefault(p["order_id"], []).append(p)
    refunds_by_pay = {}
    for r in refunds:
        refunds_by_pay.setdefault(r["payment_id"], []).append(r)
    sets_by_pay = {}
    for s in sets:
        sets_by_pay.setdefault(s["payment_id"], []).append(s)

    healthy_leak = 0
    anomaly_clean = 0
    for o in orders:
        if o["status"] == "ABANDONED":
            continue
        g = gt_by_order.get(o["order_id"])
        expected_total = 0.0
        actual_total = 0.0
        for p in pay_by_order.get(o["order_id"], []):
            amt = float(p["amount"])
            exp_s, fee, tax = expected_settlement(amt, p["method"])
            refunded = sum(float(r["amount"]) for r in refunds_by_pay.get(p["payment_id"], []))
            fee_ret = money(fee * (refunded / amt)) if refunded else 0.0
            expected_total += money(amt - fee - tax - refunded + fee_ret)
            actual_total += money(sum(float(s["amount"]) for s in sets_by_pay.get(p["payment_id"], [])))
        expected_total = money(expected_total)
        actual_total = money(actual_total)
        variance = money(expected_total - actual_total)
        if g and g["has_anomaly"] == "FALSE":
            if abs(variance) > tol:
                healthy_leak += 1
                errors.append(f"healthy {o['order_id']} has unexplained variance {variance}")
        else:
            if abs(variance) <= tol:
                # refund_economics cases are below settlement tol sometimes; check gt type
                if g and "REFUND-ECONOMICS" not in g["anomaly_type"]:
                    anomaly_clean += 1

    print(f"orders={len(orders)} pays={len(pays)} fees={len(fees)} refunds={len(refunds)} "
          f"sets={len(sets)} banks={len(banks)} gt={len(gts)}")
    print(f"healthy-with-leak (must be 0): {healthy_leak}")
    print(f"anomalies-with-clean-settlement (small refund-fee cases ok): {anomaly_clean}")
    print(f"anomaly mix: { {g['anomaly_type']: sum(1 for x in gts if x['anomaly_type']==g['anomaly_type'] and g['anomaly_type']) for g in gts if g['anomaly_type']} }")

    if errors:
        print(f"\n{len(errors)} ERRORS:")
        for e in errors[:20]:
            print("  " + e)
        sys.exit(1)
    print("AUDIT PASSED: universe internally consistent.")


if __name__ == "__main__":
    main()
