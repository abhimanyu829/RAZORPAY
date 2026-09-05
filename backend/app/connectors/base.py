"""CONNECTOR BASE — shared interface every external connector implements.

Section 18:
    Connector
    ├── authenticate()
    ├── health_check()
    ├── fetch()
    ├── normalize()
    ├── map_identifiers()
    ├── emit_raw_record()
    └── checkpoint()

The canonical path is mandatory:
    EXTERNAL API → CONNECTOR → RAW RECORD → VALIDATION → NORMALIZATION →
    IDENTITY RESOLUTION → CORE
A connector NEVER writes business data directly into core tables.

Incremental ingestion (Section 23): every connector keeps a checkpoint
(last_cursor / last_timestamp / last_external_id) in raw.connector_checkpoints
and fetches only new external events. Dedupe happens at emit time via
(source_system, entity, source_record_id).
"""
from __future__ import annotations

import csv
import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterable

from ..services.repository import repo, now_iso


class ValidationError(Exception):
    """Record failed canonical validation → quarantined, never dropped."""


class IngestionResult:
    def __init__(self):
        self.fetched = 0
        self.emitted = 0
        self.duplicates = 0
        self.quarantined = 0
        self.errors: list[str] = []

    def summary(self) -> dict:
        return {"fetched": self.fetched, "emitted": self.emitted,
                "duplicates": self.duplicates, "quarantined": self.quarantined,
                "errors": self.errors[:5]}


class BaseConnector(ABC):
    """Interface contract — all connectors implement exactly these methods."""

    connector_id: str = "base"
    source_system: str = "BASE"
    entities: list[str] = []

    # ------------------------------------------------------------ interface
    @abstractmethod
    def authenticate(self) -> bool:
        """Establish/verify credentials. Returns False when unavailable."""

    @abstractmethod
    def health_check(self) -> dict:
        """Liveness probe: {'healthy': bool, 'detail': str}."""

    @abstractmethod
    def fetch(self, checkpoint: dict | None) -> Iterable[tuple[str, dict]]:
        """Yield (entity, raw_payload_dict) new since checkpoint.
        The payload dict is the RAW external shape — normalization comes later."""

    @abstractmethod
    def normalize(self, entity: str, payload: dict) -> dict:
        """Map raw payload → canonical column dict for core.<entity>."""

    # ---------------------------------------------------------- shared flow
    def map_identifiers(self, entity: str, record: dict) -> dict:
        """Hook for connector-specific ID bridging (e.g. Shopify→gateway IDs).
        Default: identity mapping is done downstream by the identity resolver."""
        return record

    def validate(self, entity: str, record: dict) -> None:
        """Canonical validation gate before core insert. Raises ValidationError."""
        amount_fields = {"orders": ["net_amount"], "payments": ["amount"],
                          "refunds": ["amount"], "gateway_fees": ["amount", "tax_amount"],
                          "settlements": ["amount"], "bank_transactions": ["amount"],
                          "invoices": ["total_amount"]}
        for f in amount_fields.get(entity, []):
            v = record.get(f)
            if v in (None, ""):
                continue
            try:
                if float(v) < 0:
                    raise ValidationError(f"{entity}.{f} negative: {v}")
            except ValueError:
                raise ValidationError(f"{entity}.{f} not numeric: {v!r}")
        for f in ("order_id", "payment_id", "settlement_id", "bank_txn_id", "invoice_id"):
            if record.get(f) == "":
                if f in record:      # present but empty → invalid
                    raise ValidationError(f"{entity}.{f} empty")

    def emit_raw_record(self, entity: str, payload: dict,
                        result: IngestionResult) -> dict | None:
        """Persist the raw payload with provenance + dedupe. Returns the raw row
        or None when duplicate."""
        source_record_id = self.source_id(entity, payload)
        sha = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        existing = repo.read_one("raw_source_records", "source_record_id", source_record_id) \
            if self._raw_rows_available() else None
        if existing and existing.get("source_system") == self.source_system \
                and existing.get("entity") == entity:
            result.duplicates += 1
            return None
        row = {
            "raw_record_id": f"RSR-{sha[:12].upper()}",
            "batch_id": self._batch_id,
            "source_system": self.source_system,
            "entity": entity,
            "source_record_id": source_record_id,
            "event_timestamp": str(payload.get("created_at")
                                    or payload.get("captured_at")
                                    or payload.get("value_date") or now_iso()),
            "payload": json.dumps(payload, default=str),
            "payload_sha256": sha,
            "schema_version": self.schema_version(entity),
            "retrieved_at": now_iso(),
        }
        self._raw_rows.append(row)
        result.emitted += 1
        return row

    def source_id(self, entity: str, payload: dict) -> str:
        """Natural key of the external record."""
        keys = {"orders": ("id", "order_id"), "payments": ("id", "payment_id"),
                "refunds": ("id", "refund_id"), "settlements": ("id", "settlement_id"),
                "gateway_fees": ("id", "fee_id"), "bank_transactions": ("bank_txn_id", "id"),
                "invoices": ("id", "invoice_id"), "gst_records": ("gst_record_id", "id"),
                "customers": ("id", "customer_id")}
        for k in keys.get(entity, ("id",)):
            if payload.get(k):
                return str(payload[k])
        return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                         default=str).encode()).hexdigest()[:16]

    def schema_version(self, entity: str) -> str:
        return "v1"

    # ------------------------------------------------------------- run sync
    def sync(self, limit: int | None = None) -> dict:
        """Full connector run: checkpoint → fetch → validate → normalize → emit.
        Returns IngestionResult.summary(). Raw rows are flushed to the repo;
        normalized core rows are staged into runtime/connector_staging for the
        canonical loader (which runs identity resolution → core)."""
        result = IngestionResult()
        self._raw_rows: list[dict] = []
        self._staged: dict[str, list[dict]] = {}
        self._batch_id = f"BAT-{self.connector_id}-{now_iso().replace(':', '').replace('-', '')[:14]}"
        ck = self.get_checkpoint()

        try:
            if not self.authenticate():
                result.errors.append("authentication failed")
                return result.summary()
        except Exception as e:
            result.errors.append(f"auth error: {e}")
            return result.summary()

        quarantined_rows = []
        for entity, payload in self.fetch(ck):
            result.fetched += 1
            try:
                self.emit_raw_record(entity, payload, result)
                record = self.normalize(entity, payload)
                record = self.map_identifiers(entity, record)
                self.validate(entity, record)
                self._staged.setdefault(entity, []).append(record)
            except ValidationError as ve:
                result.quarantined += 1
                quarantined_rows.append({
                    "quarantine_id": f"QAR-{self.connector_id}-{result.quarantined}",
                    "batch_id": self._batch_id,
                    "source_record_id": self.source_id(entity, payload),
                    "reason": "SCHEMA_VIOLATION", "details": str(ve)[:500],
                    "payload": json.dumps(payload, default=str)[:2000],
                    "quarantined_at": now_iso(),
                })
            except Exception as e:
                result.errors.append(f"{entity}: {e}")
            if limit and result.fetched >= limit:
                break

        # flush raw + staged + quarantine + checkpoint
        for raw_row in self._raw_rows:
            repo.append("raw_source_records", raw_row)
        for entity, rows in self._staged.items():
            p = repo.runtime / "connector_staging" / f"{entity}.csv"
            p.parent.mkdir(parents=True, exist_ok=True)
            existing = list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []
            ids = {r.get(self._key_of(entity)) for r in existing}
            merged = existing + [r for r in rows
                                 if r.get(self._key_of(entity)) not in ids]
            if merged:
                fields = list({k for r in merged for k in r.keys()})
                with open(p, "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(merged)
        for q in quarantined_rows:
            repo.append("quarantine_records", q)
        self.save_checkpoint()
        self._log_run(result)
        return result.summary()

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _key_of(entity: str) -> str:
        return {"orders": "order_id", "payments": "payment_id",
                "refunds": "refund_id", "gateway_fees": "fee_id",
                "settlements": "settlement_id", "bank_transactions": "bank_txn_id",
                "invoices": "invoice_id", "gst_records": "gst_record_id",
                "customers": "customer_id"}.get(entity, "id")

    def _raw_rows_available(self) -> bool:
        return True

    # ----------------------------------------------------------- checkpoint
    def get_checkpoint(self) -> dict:
        rows = repo.read("connector_checkpoints")
        for r in rows:
            if r.get("connector_id") == self.connector_id:
                return r
        return {}

    def save_checkpoint(self, last_cursor: str = "", last_timestamp: str = "",
                        last_external_id: str = "") -> None:
        rows = [r for r in repo.read("connector_checkpoints")
                if r.get("connector_id") != self.connector_id]
        rows.append({
            "connector_id": self.connector_id,
            "last_cursor": last_cursor or getattr(self, "_last_cursor", ""),
            "last_timestamp": last_timestamp or getattr(self, "_last_ts", ""),
            "last_external_id": last_external_id or getattr(self, "_last_ext", ""),
            "updated_at": now_iso(),
        })
        repo.write("connector_checkpoints", rows, append=False)

    def _log_run(self, result: IngestionResult) -> None:
        run_id = f"CRUN-{self.connector_id}-{now_iso().replace(':', '').replace('-', '')[:14]}"
        repo.append("connector_runs", {
            "run_id": run_id, "connector_id": self.connector_id,
            "status": "COMPLETED" if not result.errors else "PARTIAL",
            **result.summary(),
            "started_at": now_iso(), "finished_at": now_iso(),
        })
