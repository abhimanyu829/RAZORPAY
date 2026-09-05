"""ACCOUNTING / GST CSV CONNECTOR (Section 22).

Invoices + GST records from accounting exports. GST issues stay
REVIEW_REQUIRED — this connector only ingests evidence, never tax actions.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from ..settings import settings
from .base import BaseConnector, ValidationError

INCOMING_DIR = settings.data_raw / "accounting" / "incoming"


class AccountingCsvConnector(BaseConnector):
    connector_id = "ACCOUNTING_CSV"
    source_system = "ACCOUNTING"
    entities = ["invoices", "gst_records"]

    def authenticate(self) -> bool:
        return INCOMING_DIR.exists() or (settings.data_raw / "accounting").exists()

    def health_check(self) -> dict:
        return {"healthy": self.authenticate(), "detail": "csv export source"}

    def _files(self) -> list[Path]:
        src = []
        if INCOMING_DIR.exists():
            src = sorted(INCOMING_DIR.glob("*.csv"))
        base = settings.data_raw / "accounting"
        for name in ("invoices.csv", "gst_records.csv"):
            p = base / name
            if p.exists() and p not in src:
                src.append(p)
        return src

    def fetch(self, checkpoint: dict | None) -> Iterable[tuple[str, dict]]:
        last_ids = {}
        for f in self._files():
            entity = "invoices" if f.name.startswith("invoice") else "gst_records"
            last = (checkpoint or {}).get(f"last_{entity}_id", "")
            with open(f, encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    rid = row.get("invoice_id") or row.get("gst_record_id", "")
                    if last and rid and rid <= last:
                        continue
                    yield entity, dict(row)

    def normalize(self, entity: str, payload: dict) -> dict:
        if entity == "invoices":
            return {"invoice_id": payload.get("invoice_id", ""),
                    "order_id": payload.get("order_id", ""),
                    "invoice_number": payload.get("invoice_number", ""),
                    "taxable_value": payload.get("taxable_value", ""),
                    "gst_amount": payload.get("gst_amount", ""),
                    "total_amount": payload.get("total_amount", ""),
                    "status": payload.get("status", "ISSUED"),
                    "source": self.source_system}
        return {"gst_record_id": payload.get("gst_record_id", ""),
                "invoice_id": payload.get("invoice_id", ""),
                "gst_type": payload.get("gst_type", "OUTPUT"),
                "igst": payload.get("igst", "0"),
                "cgst": payload.get("cgst", "0"),
                "sgst": payload.get("sgst", "0"),
                "total_tax": payload.get("total_tax", "0"),
                "itc_eligible": payload.get("itc_eligible", "FALSE"),
                "itc_matched": payload.get("itc_matched", ""),
                "source": self.source_system}

    def validate(self, entity: str, record: dict) -> None:
        super().validate(entity, record)
        if entity == "invoices" and not record.get("invoice_id"):
            raise ValidationError("invoice without invoice_id")
        if entity == "gst_records" and record.get("gst_type") not in ("OUTPUT", "INPUT", "RCM"):
            raise ValidationError(f"bad gst_type {record.get('gst_type')!r}")
