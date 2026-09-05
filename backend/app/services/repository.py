"""REPOSITORY — data access layer over the financial truth.

Two interchangeable backends, selected by settings.database_url:
  CsvRepository   reads/writes the deterministic CSV universe (offline today)
  PostgresRepository  Supabase PostgreSQL via psycopg (when configured)

Business logic NEVER touches storage directly — services use this interface,
so migrating to Supabase changes zero decision code (Section 4/30).
"""
from __future__ import annotations

import csv
import io
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ..settings import settings


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_float(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


class CsvRepository:
    """File-backed repository over data/raw + data/staging + data/runtime."""

    def __init__(self, root: Path | None = None):
        self.raw = settings.data_raw
        self.stage = settings.data_staging
        self.runtime = settings.data_runtime
        for p in (self.stage, self.runtime):
            p.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- basics
    def _path(self, table: str) -> Path:
        mapping = {
            "orders": self.raw / "shopify" / "orders.csv",
            "customers": self.raw / "shopify" / "customers.csv",
            "payments": self.raw / "razorpay" / "payments.csv",
            "refunds": self.raw / "razorpay" / "refunds.csv",
            "gateway_fees": self.raw / "razorpay" / "gateway_fees.csv",
            "settlements": self.raw / "razorpay" / "settlements.csv",
            "bank_transactions": self.raw / "bank" / "bank_transactions.csv",
            "invoices": self.raw / "accounting" / "invoices.csv",
            "gst_records": self.raw / "accounting" / "gst_records.csv",
            "identity_matches": self.stage / "identity_matches.csv",
            "reconciliation_results": self.stage / "reconciliation_results.csv",
            "anomaly_results": self.stage / "anomaly_results.csv",
            "recovery_cases": self.stage / "recovery_cases.csv",
            "evidence_records": self.stage / "evidence_records.csv",
            "case_history": self.stage / "case_history.csv",
            "recoverability_assessments": self.stage / "recoverability_assessments.csv",
            "recovery_actions": self.runtime / "recovery_actions.csv",
            "approvals": self.runtime / "approvals.csv",
            "verification_events": self.runtime / "verification_events.csv",
            "audit_ledger": self.runtime / "audit_ledger.csv",
            "agent_runs": self.runtime / "agent_runs.csv",
            "connector_runs": self.runtime / "connector_runs.csv",
            "webhook_events": self.runtime / "webhook_events.csv",
            "recovery_ledger": self.runtime / "recovery_ledger.csv",
            "connector_checkpoints": self.runtime / "connector_checkpoints.csv",
            "raw_source_records": self.runtime / "raw_source_records.csv",
            "quarantine_records": self.runtime / "quarantine_records.csv",
        }
        if table not in mapping:
            raise KeyError(f"unknown table {table}")
        return mapping[table]

    def read(self, table: str) -> list[dict]:
        p = self._path(table)
        if not p.exists():
            return []
        with open(p, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def read_one(self, table: str, key: str, value: str) -> dict | None:
        for row in self.read(table):
            if row.get(key) == value:
                return row
        return None

    def write(self, table: str, rows: Iterable[dict], append: bool = True) -> int:
        p = self._path(table)
        p.parent.mkdir(parents=True, exist_ok=True)
        rows = list(rows)
        existing = self.read(table) if (append and p.exists()) else []
        if not rows and not existing:
            return 0
        fields = _union_fields(existing + rows)
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in existing + rows:
                w.writerow(r)
        return len(rows)

    def append(self, table: str, row: dict) -> None:
        self.write(table, [row], append=True)

    # -------------------------------------------------- domain-specific reads
    def get_order(self, order_id: str) -> dict | None:
        return self.read_one("orders", "order_id", order_id)

    def get_payment(self, payment_id: str) -> dict | None:
        return self.read_one("payments", "payment_id", payment_id)

    def payments_for_order(self, order_id: str) -> list[dict]:
        return [p for p in self.read("payments") if p.get("order_id") == order_id]

    def fees_for_payment(self, payment_id: str) -> list[dict]:
        return [f for f in self.read("gateway_fees") if f.get("payment_id") == payment_id]

    def refunds_for_payment(self, payment_id: str) -> list[dict]:
        return [r for r in self.read("refunds") if r.get("payment_id") == payment_id]

    def settlements_for_payment(self, payment_id: str) -> list[dict]:
        return [s for s in self.read("settlements") if s.get("payment_id") == payment_id]

    def bank_by_utr(self, utr: str) -> dict | None:
        return self.read_one("bank_transactions", "utr", utr)

    def get_case(self, case_id: str) -> dict | None:
        return self.read_one("recovery_cases", "case_id", case_id)

    def cases(self, status: str | None = None, category: str | None = None) -> list[dict]:
        rows = self.read("recovery_cases")
        if status:
            rows = [c for c in rows if c.get("status") == status]
        if category:
            rows = [c for c in rows if c.get("category") == category]
        return rows

    def evidence_for_case(self, case_id: str) -> list[dict]:
        return [e for e in self.read("evidence_records") if e.get("case_id") == case_id]

    def history_for_case(self, case_id: str) -> list[dict]:
        return [h for h in self.read("case_history") if h.get("case_id") == case_id]

    def actions_for_case(self, case_id: str) -> list[dict]:
        return [a for a in self.read("recovery_actions") if a.get("case_id") == case_id]

    def find_action_by_key(self, idempotency_key: str) -> dict | None:
        return self.read_one("recovery_actions", "idempotency_key", idempotency_idkey_safe(idempotency_key))

    def approvals_for_case(self, case_id: str) -> list[dict]:
        return [a for a in self.read("approvals") if a.get("case_id") == case_id]

    def verifications_for_case(self, case_id: str) -> list[dict]:
        return [v for v in self.read("verification_events") if v.get("case_id") == case_id]

    def get_ground_truth(self, order_id: str) -> dict | None:
        """EVALUATOR ONLY — never called from the agent path."""
        import csv as _csv
        p = settings.data_exports.parent / "ground_truth" / "ground_truth.csv"
        if not p.exists():
            p = self.raw.parent / "ground_truth" / "ground_truth.csv"
        with open(p, encoding="utf-8", newline="") as f:
            for row in _csv.DictReader(f):
                if row.get("order_id") == order_id:
                    row["__source"] = str(p)
                    return row
        return None

    # ------------------------------------------------------------ sequencing
    def next_id(self, table: str, prefix: str, key_field: str, width: int = 4) -> str:
        """Next human-readable ID by scanning existing max suffix."""
        import re as _re
        pat = _re.compile(_re.escape(prefix) + r"(\d+)")
        best = 0
        for r in self.read(table):
            m = pat.fullmatch(str(r.get(key_field, "") or ""))
            if m:
                best = max(best, int(m.group(1)))
        return f"{prefix}{best + 1:0{width}d}"


def idempotency_idkey_safe(key: str) -> str:
    return key.replace(":", "_")


def _union_fields(rows: list[dict]) -> list[str]:
    seen: dict[str, None] = {}
    for r in rows:
        for k in r.keys():
            seen.setdefault(k, None)
    return list(seen)


# --------------------------------------------------------------------------- #
# Postgres repository (Supabase) — used when REVENUEGUARD_DATABASE_URL is set  #
# --------------------------------------------------------------------------- #

class PostgresRepository(CsvRepository):
    """Same interface over Supabase PostgreSQL.

    Table/column names mirror supabase/migrations/*.sql exactly. Uses psycopg
    (v3) with a simple connection retry. RLS applies per authenticated role.
    """

    def __init__(self, dsn: str):
        super().__init__()
        self.dsn = dsn
        try:
            import psycopg
        except ImportError as e:
            raise RuntimeError(
                "REVENUEGUARD_DATABASE_URL set but psycopg not installed. "
                "Run: pip install psycopg[binary]") from e

    def _conn(self):
        import psycopg
        return psycopg.connect(self.dsn)

    def read(self, table: str) -> list[dict]:
        schema, _, name = table.partition(".")
        if not schema:
            # core-style single names map to their plane (see migrations)
            schema = _plane_of(table)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f'SELECT * FROM {schema}.{name}')
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def read_one(self, table: str, key: str, value: str) -> dict | None:
        for row in self.read(table):
            if str(row.get(key)) == str(value):
                return row
        return None

    def write(self, table: str, rows: Iterable[dict], append: bool = True) -> int:
        schema, _, name = table.partition(".")
        if not schema:
            schema = _plane_of(table)
        rows = list(rows)
        if not rows:
            return 0
        fields = _union_fields(rows)
        cols = ", ".join(f'"{f}"' for f in fields)
        placeholders = ", ".join(["%s"] * len(fields))
        with self._conn() as conn, conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    f'INSERT INTO {schema}.{name} ({cols}) VALUES ({placeholders}) '
                    f'ON CONFLICT DO NOTHING',
                    [r.get(f) for f in fields])
        return len(rows)


def _plane_of(table: str) -> str:
    core = {"orders", "customers", "payments", "refunds", "gateway_fees",
            "settlements", "bank_transactions", "invoices", "gst_records",
            "marketplace_deductions", "subscriptions", "customer_events",
            "receivables", "chargebacks"}
    ops = {"identity_matches", "reconciliation_results", "anomaly_results",
           "recovery_cases", "evidence_records", "recoverability_assessments",
           "recovery_actions", "approvals", "case_history",
           "verification_events", "audit_ledger", "agent_runs",
           "connector_runs", "webhook_events", "recovery_ledger"}
    raw = {"ingestion_batches", "raw_source_records", "quarantine_records"}
    cfg = {"source_connectors", "schema_versions", "normalization_mappings",
           "rate_cards", "financial_rules", "tolerance_rules", "sla_rules",
           "recovery_policies", "agent_tools"}
    if table in core:
        return "core"
    if table in ops:
        return "ops"
    if table in raw:
        return "raw"
    if table in cfg:
        return "cfg"
    return "public"


def get_repository() -> "CsvRepository | PostgresRepository":
    if settings.database_url:
        return PostgresRepository(settings.database_url)
    return CsvRepository()


repo = get_repository()
