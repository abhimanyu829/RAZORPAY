"""BANK CSV CONNECTOR — MVP external integration (Section 21).

Reads bank statement CSVs (the same format as the synthetic universe) with
UTR as the primary identity signal. Incremental via value_date cursor.
Runnable offline today against data/raw/bank/incoming/.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable

from ..settings import settings
from ..services.repository import repo, now_iso
from .base import BaseConnector, IngestionResult

INCOMING_DIR = settings.data_raw / "bank" / "incoming"


class BankCsvConnector(BaseConnector):
    connector_id = "BANK_CSV"
    source_system = "BANK"
    entities = ["bank_transactions"]

    def authenticate(self) -> bool:
        # CSV source: "auth" = directory exists or a default file present
        return INCOMING_DIR.exists() or (settings.data_raw / "bank" / "bank_transactions.csv").exists()

    def health_check(self) -> dict:
        ok = self.authenticate()
        return {"healthy": ok,
                "detail": f"incoming dir: {INCOMING_DIR.exists()}"}

    def fetch(self, checkpoint: dict | None) -> Iterable[tuple[str, dict]]:
        last_date = (checkpoint or {}).get("last_timestamp", "")
        sources: list[Path] = []
        if INCOMING_DIR.exists():
            sources = sorted(INCOMING_DIR.glob("*.csv"))
        else:
            p = settings.data_raw / "bank" / "bank_transactions.csv"
            if p.exists():
                sources = [p]
        self._last_ts = last_date
        self._last_cursor = ""
        self._last_ext = ""
        for path in sources:
            with open(path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    vd = row.get("value_date", "")
                    if last_date and vd and vd <= last_date:
                        continue                      # incremental skip
                    self._last_ts = max(self._last_ts, vd) if vd else self._last_ts
                    self._last_ext = row.get("bank_txn_id", "")
                    yield "bank_transactions", dict(row)

    def normalize(self, entity: str, payload: dict) -> dict:
        return {
            "bank_txn_id": payload.get("bank_txn_id", ""),
            "utr": payload.get("utr", ""),
            "amount": payload.get("amount", ""),
            "value_date": payload.get("value_date", ""),
            "direction": payload.get("direction", "CREDIT"),
            "counterparty": payload.get("counterparty", ""),
            "description": payload.get("description", ""),
            "source": self.source_system,
        }

    def validate(self, entity: str, record: dict) -> None:
        super().validate(entity, record)
        if not record.get("utr"):
            raise ValidationError("bank transaction without UTR — cannot identity-match")
        if record.get("direction") not in ("CREDIT", "DEBIT"):
            # normalize common bank exports
            d = (record.get("direction") or "").upper()
            if d in ("CR", "C", "IN"):
                record["direction"] = "CREDIT"
            elif d in ("DR", "D", "OUT"):
                record["direction"] = "DEBIT"
            else:
                raise ValidationError(f"unknown direction {record.get('direction')!r}")


from .base import ValidationError  # noqa: E402  (kept close to use)
