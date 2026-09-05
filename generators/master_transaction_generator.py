"""MASTER TRANSACTION GENERATOR — entry point.

Builds the causal universe from txn_model.Txn, applies behavioural flags,
then hands off to anomaly_injector (separate pass) and writes source CSVs.

Run:  python generators/master_transaction_generator.py
"""
import csv
import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from generators import config as C
from generators.txn_model import Txn, d, money, iso, expected_settlement

rng = random.Random(C.RANDOM_SEED)

# behavioural flag thresholds (cumulative % of transactions)
F_ABANDONED = C.ABANDONED_ORDER_PCT / 100
F_SPLIT = F_ABANDONED + C.SPLIT_PAYMENT_PCT / 100
F_REFUND = F_SPLIT + C.NORMAL_REFUND_PCT / 100
F_BANK_DELAY = F_REFUND + C.BANK_DELAY_PCT / 100
F_BANK_NOT_ARRIVED = F_BANK_DELAY + C.BANK_NOT_ARRIVED_YET_PCT / 100


def spread_dates(start, n, days):
    lo = d(start + "T00:00:00Z")
    hi = lo + timedelta(days=days)
    out = []
    total = (hi - lo).total_seconds()
    for i in range(n):
        base = lo + timedelta(seconds=total * i / max(n - 1, 1))
        out.append(base + timedelta(seconds=rng.randint(-3600 * 4, 3600 * 4))
                   if i > 0 else base)
    return out


def roll_flags(t):
    """Assign behavioural flags deterministically (uniform rolls)."""
    r = rng.random()
    if r < F_ABANDONED:
        t.flags["abandoned"] = True
    elif r < F_SPLIT:
        t.flags["split"] = True
    elif r < F_REFUND:
        t.flags["refund"] = True
    elif r < F_BANK_DELAY:
        t.flags["bank_delay"] = True
    elif r < F_BANK_NOT_ARRIVED:
        t.flags["bank_not_arrived"] = True
    return t


def build_universe():
    n = C.N_TRANSACTIONS
    dates = spread_dates(C.DATE_RANGE[0], n, (d(C.DATE_RANGE[1]) - d(C.DATE_RANGE[0])).days)
    txns = []
    for idx in range(1, n + 1):
        t = Txn(idx, dates[idx - 1], rng)
        roll_flags(t)
        txns.append(t)
    from generators import anomaly_injector as inj
    inj.assign(txns, rng)          # mark anomalies BEFORE legs are built
    for t in txns:
        t.build_legs()
    inj.apply_mutations(txns, rng) # mutate actuals AFTER legs are built
    inj.build_ground_truth(txns)   # hidden truth from final actuals (all txns)
    return txns


# ------------------------------------------------------------------ writers --
def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def customers_from(orders):
    out, seen = [], set()
    for o in orders:
        cid = o["customer_id"]
        if cid in seen:
            continue
        seen.add(cid)
        out.append({
            "customer_id": cid,
            "name": f"Customer {cid[-4:]}",
            "email": f"customer{cid[-4:]}@example.com",
            "phone": f"+9198{rng.randint(10**8, 10**9 - 1)}",
            "source_system": "SHOPIFY",
            "source_record_id": cid,
        })
    return out


def main():
    txns = build_universe()

    orders, payments, fees, refunds, settlements, banks, invoices, gst = [], [], [], [], [], [], [], []
    for t in txns:
        tax_part = money(t.amount - t.amount / (1 + C.INVOICE_GST_RATE))
        if t.flags.get("abandoned"):
            orders.append({
                "order_id": t.order_id, "order_number": t.order_number,
                "customer_id": t.customer_id, "gateway_order_id": t.gateway_order_id,
                "order_date": iso(t.order_dt), "status": "ABANDONED",
                "financial_status": "ABANDONED", "gross_amount": money(t.amount),
                "tax_amount": tax_part, "shipping_amount": 0.0,
                "discount_amount": 0.0, "net_amount": money(t.amount),
                "payment_method": t.method,
            })
            continue
        orders.append({
            "order_id": t.order_id, "order_number": t.order_number,
            "customer_id": t.customer_id, "gateway_order_id": t.gateway_order_id,
            "order_date": iso(t.order_dt), "status": "PAID",
            "financial_status": "PAID", "gross_amount": money(t.amount),
            "tax_amount": tax_part, "shipping_amount": 0.0,
            "discount_amount": 0.0, "net_amount": money(t.amount),
            "payment_method": t.method,
        })
        payments.extend(t.payments)
        fees.extend(t.fees)
        refunds.extend(t.refunds)
        settlements.extend(t.settlements)
        banks.extend(t.bank_txns)
        if t.invoice:
            invoices.append(t.invoice)
            gst.extend(t.gst_lines)

    customers = customers_from(orders)
    raw = C.raw_dir()
    write_csv(raw / "shopify" / "orders.csv", orders,
              ["order_id", "order_number", "customer_id", "gateway_order_id", "order_date", "status",
               "financial_status", "gross_amount", "tax_amount", "shipping_amount", "discount_amount",
               "net_amount", "payment_method"])
    write_csv(raw / "shopify" / "customers.csv", customers,
              ["customer_id", "name", "email", "phone", "source_system", "source_record_id"])
    write_csv(raw / "razorpay" / "payments.csv", payments,
              ["payment_id", "gateway_payment_id", "order_id", "gateway_order_id", "customer_id",
               "amount", "method", "instrument_brand", "status", "captured_at"])
    write_csv(raw / "razorpay" / "refunds.csv", refunds,
              ["refund_id", "payment_id", "order_id", "gateway_refund_id", "status",
               "amount", "refund_reason", "processed_at"])
    write_csv(raw / "razorpay" / "settlements.csv", settlements,
              ["settlement_id", "gateway_settlement_id", "payment_id", "order_id", "utr", "status",
               "settlement_type", "amount", "fee_deducted", "tax_deducted", "settled_at", "expected_credit_date"])
    write_csv(raw / "razorpay" / "gateway_fees.csv", fees,
              ["fee_id", "payment_id", "order_id", "fee_type", "amount", "tax_amount",
               "rate_card_id", "fee_event_at"])
    write_csv(raw / "bank" / "bank_transactions.csv", banks,
              ["bank_txn_id", "utr", "txn_type", "direction", "amount", "value_date",
               "txn_timestamp", "narration", "counterparty"])
    write_csv(raw / "accounting" / "invoices.csv", invoices,
              ["invoice_id", "order_id", "customer_id", "invoice_number", "status", "issue_date",
               "due_date", "taxable_value", "gst_rate", "gst_amount", "total_amount", "place_of_supply"])
    write_csv(raw / "accounting" / "gst_records.csv", gst,
              ["gst_record_id", "invoice_id", "order_id", "gst_type", "return_period",
               "gstin", "taxable_value", "igst", "cgst", "sgst", "cess", "total_tax",
               "itc_eligible", "itc_matched", "filed_status"])

    # ground truth (eval-only) + manifest
    gt_rows = [t.ground_truth for t in txns if t.ground_truth]
    from generators import anomaly_injector as inj
    inj.write_ground_truth(gt_rows, C.ground_truth_dir())

    print(f"transactions: {len(txns)}  orders: {len(orders)}  payments: {len(payments)}  "
          f"fees: {len(fees)}  refunds: {len(refunds)}  settlements: {len(settlements)}  "
          f"bank: {len(banks)}  invoices: {len(invoices)}  gst: {len(gst)}  gt: {len(gt_rows)}")

if __name__ == "__main__":
    main()
