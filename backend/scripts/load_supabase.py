"""CSV → Supabase loader — deterministic universe into PostgreSQL.

Runs stdlib-only (psycopg optional): emits a SQL file with COPY/INSERT
statements when psycopg is unavailable, or executes directly when it is.

Usage:
    python backend/scripts/load_supabase.py --sql-only          # emit .sql
    python backend/scripts/load_supabase.py --dsn postgresql://… # live load
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "generators"))

TABLE_MAP = [
    # (csv path, target table, target columns)
    ("data/raw/shopify/customers.csv", "core.customers",
     ["customer_id", "name", "email", "phone", "city", "state", "gstin",
      "segment", "signup_date", "source", "normalized"]),
    ("data/raw/shopify/orders.csv", "core.orders",
     ["order_id", "order_number", "customer_id", "net_amount", "status",
      "placed_at", "gateway_order_id", "source"]),
    ("data/raw/razorpay/payments.csv", "core.payments",
     ["payment_id", "order_id", "gateway_payment_id", "amount", "method",
      "status", "currency", "captured_at", "settled", "source"]),
    ("data/raw/razorpay/gateway_fees.csv", "core.gateway_fees",
     ["fee_id", "payment_id", "fee_type", "amount", "tax_amount",
      "rate_card_id", "reversal_of_fee_id", "source"]),
    ("data/raw/razorpay/refunds.csv", "core.refunds",
     ["refund_id", "payment_id", "gateway_refund_id", "amount", "status",
      "processed_at", "source"]),
    ("data/raw/razorpay/settlements.csv", "core.settlements",
     ["settlement_id", "payment_id", "amount", "fee_deducted",
      "tax_deducted", "utr", "expected_credit_date", "settled_at",
      "status", "source"]),
    ("data/raw/bank/bank_transactions.csv", "core.bank_transactions",
     ["bank_txn_id", "utr", "amount", "value_date", "direction",
      "counterparty", "description", "source"]),
    ("data/raw/accounting/invoices.csv", "core.invoices",
     ["invoice_id", "order_id", "invoice_number", "taxable_value",
      "gst_amount", "total_amount", "status", "source"]),
    ("data/raw/accounting/gst_records.csv", "core.gst_records",
     ["gst_record_id", "invoice_id", "gst_type", "igst", "cgst", "sgst",
      "total_tax", "itc_eligible", "itc_matched", "source"]),
    ("data/staging/identity_matches.csv", "ops.identity_matches",
     ["identity_match_id", "entity_type", "left_system", "left_entity",
      "left_record_id", "right_system", "right_entity", "right_record_id",
      "match_method", "confidence", "status", "conflict_detail", "matched_at"]),
    ("data/staging/reconciliation_results.csv", "ops.reconciliation_results",
     ["recon_result_id", "reconcile_run_id", "direction", "left_entity",
      "left_record_id", "right_entity", "right_record_id", "status",
      "expected_amount", "actual_amount", "variance", "explained_variance",
      "unexplained_variance", "variance_class", "tolerance_id", "matched_at",
      "notes"]),
    ("data/staging/anomaly_results.csv", "ops.anomaly_results",
     ["anomaly_id", "recon_result_id", "order_id", "payment_id", "category",
      "detection_rule", "detected_amount", "variance_class", "severity",
      "explanation", "candidate_root_causes", "detected_at"]),
    ("data/staging/recovery_cases.csv", "ops.recovery_cases",
     ["case_id", "anomaly_id", "order_id", "payment_id", "customer_id",
      "category", "priority", "status", "expected_fee", "expected_tax",
      "expected_settlement", "actual_fee", "actual_tax", "actual_settlement",
      "known_adjustments", "refund_status", "recon_status",
      "potential_leakage", "confidence", "recoverability_status",
      "potential_recovery", "deadline_at", "allowed_actions",
      "approval_required", "opened_at", "closed_at"]),
    ("data/staging/evidence_records.csv", "ops.evidence_records",
     ["evidence_id", "case_id", "recon_result_id", "evidence_kind",
      "source_system", "source_reference", "description", "payload_sha256",
      "collected_at"]),
    ("data/staging/case_history.csv", "ops.case_history",
     ["history_id", "case_id", "event_type", "old_status", "new_status",
      "actor", "message", "payload", "event_at"]),
    ("data/staging/recoverability_assessments.csv", "ops.recoverability_assessments",
     ["assessment_id", "case_id", "status", "discrepancy_amount",
      "potentially_recoverable_amount", "confidence", "root_cause",
      "evidence_complete", "evidence_missing", "contractual_basis",
      "tax_review_status", "deadline_at", "deadline_open",
      "recommended_action", "assessed_at"]),
    ("data/ground_truth/ground_truth.csv", "eval.ground_truth",
     None),   # all columns
]


def esc(v: str) -> str:
    if v is None:
        return "NULL"
    s = str(v).replace("'", "''")
    return f"'{s}'" if s != "" else "NULL"


def num(v: str) -> str:
    return str(v) if v not in ("", None) else "NULL"


def emit_sql(out) -> int:
    total = 0
    out.write("-- Generated by load_supabase.py — deterministic universe load\n")
    out.write("-- Apply AFTER 001_schema.sql / seed / functions / views / 002_security\n")
    out.write("BEGIN;\n")
    for rel, table, cols in TABLE_MAP:
        path = ROOT / rel
        if not path.exists():
            out.write(f"-- SKIP missing {rel}\n")
            continue
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if not rows:
                continue
            hdr = cols or list(rows[0].keys())
            out.write(f"\n-- {table}: {len(rows)} rows from {rel}\n")
            out.write(f"TRUNCATE {table};\n")
            # batched multi-row INSERTs (portable, no COPY privileges needed)
            batch = []
            for r in rows:
                vals = ", ".join(
                    num(r.get(c, "")) if c in (
                        "net_amount", "amount", "tax_amount", "fee_deducted",
                        "tax_deducted", "expected_amount", "actual_amount",
                        "variance", "explained_variance", "unexplained_variance",
                        "detected_amount", "potential_leakage",
                        "expected_fee", "expected_tax", "expected_settlement",
                        "actual_fee", "actual_tax", "actual_settlement",
                        "known_adjustments", "potential_recovery",
                        "discrepancy_amount", "potentially_recoverable_amount",
                        "igst", "cgst", "sgst", "total_tax", "taxable_value",
                        "gst_amount", "total_amount", "confidence")
                    else esc(r.get(c, ""))
                    for c in hdr)
                batch.append(f"({vals})")
                if len(batch) == 200:
                    out.write(f"INSERT INTO {table} ({', '.join(hdr)}) VALUES\n"
                              + ",\n".join(batch) + ";\n")
                    total += len(batch)
                    batch = []
            if batch:
                out.write(f"INSERT INTO {table} ({', '.join(hdr)}) VALUES\n"
                          + ",\n".join(batch) + ";\n")
                total += len(batch)
    out.write("\nCOMMIT;\n")
    return total


def load_live(dsn: str) -> int:
    try:
        import psycopg
    except ImportError:
        print("psycopg not installed — falling back to --sql-only")
        return -1
    sql_path = ROOT / "supabase" / "generated" / "load_data.sql"
    sql_path.parent.mkdir(parents=True, exist_ok=True)
    with open(sql_path, "w", encoding="utf-8") as f:
        n = emit_sql(f)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql_path.read_text(encoding="utf-8"))
    print(f"loaded via SQL file into {dsn}")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sql-only", action="store_true")
    ap.add_argument("--dsn", default="")
    args = ap.parse_args()
    if args.dsn and not args.sql_only:
        n = load_live(args.dsn)
        print(f"total rows: {n}")
        return
    out_path = ROOT / "supabase" / "generated" / "load_data.sql"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        n = emit_sql(f)
    print(f"SQL written to {out_path} ({n} rows)")


if __name__ == "__main__":
    main()
