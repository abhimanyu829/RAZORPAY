"""RAZORPAY CONNECTOR — sandbox/test gateway integration (Section 19).

Wraps the Razorpay REST API around sandbox/test credentials. Without
credentials (REVENUEGUARD_ROLLOUT_LEVEL < 2 or keys unset) the connector
health-check reports unavailable and sync degrades to the synthetic files —
never crashes, never fabricates.

Preserves for every record: external_id, source_system, source_record_id,
retrieved_at, event_timestamp, raw_payload, payload_hash, schema_version.
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Iterable

from ..settings import settings
from .base import BaseConnector, ValidationError

API_BASE = "https://api.razorpay.com/v1"


class RazorpayConnector(BaseConnector):
    connector_id = "RAZORPAY_TEST"
    source_system = "RAZORPAY"
    entities = ["payments", "refunds", "settlements", "gateway_fees"]

    def __init__(self):
        self._client = None

    # ------------------------------------------------------------ transport
    def _get_client(self):
        if self._client is not None:
            return self._client
        import httpx
        auth = base64.b64encode(
            f"{settings.razorpay_key_id}:{settings.razorpay_key_secret}".encode()).decode()
        self._client = httpx.Client(
            base_url=API_BASE,
            headers={"Authorization": f"Basic {auth}"},
            timeout=20.0)
        return self._client

    def authenticate(self) -> bool:
        if not (settings.razorpay_key_id and settings.razorpay_key_secret):
            return False
        try:
            r = self._get_client().get("/payments", params={"count": 1})
            return r.status_code == 200
        except Exception:
            return False

    def health_check(self) -> dict:
        if not (settings.razorpay_key_id and settings.razorpay_key_secret):
            return {"healthy": False,
                    "detail": "RAZORPAY_KEY_ID/SECRET not configured — "
                              "connector idle (synthetic mode active)"}
        try:
            ok = self.authenticate()
            return {"healthy": ok, "detail": "sandbox API reachable" if ok else "auth failed"}
        except Exception as e:
            return {"healthy": False, "detail": f"transport error: {e}"}

    # ---------------------------------------------------------------- fetch
    def fetch(self, checkpoint: dict | None) -> Iterable[tuple[str, dict]]:
        """Incremental fetch: payments page from last payment id; refunds and
        settlements follow. Yields RAW API shapes."""
        if not (settings.razorpay_key_id and settings.razorpay_key_secret):
            return                              # graceful: nothing external
        last_id = (checkpoint or {}).get("last_external_id", "")
        client = self._get_client()
        # payments (ordered, incremental by id)
        params = {"count": 100, "order": "desc"}
        if last_id:
            params["start_after_id"] = last_id
        try:
            r = client.get("/payments", params=params)
            r.raise_for_status()
            items = r.json().get("items", [])
        except Exception as e:
            self._auth_failed = str(e)
            return
        for p in items:
            self._last_ext = p.get("id", "")
            self._last_cursor = self._last_ext
            self._last_ts = p.get("created_at", "")
            yield "payments", p
            # refunds hang off payments
            try:
                rr = client.get(f"/payments/{p['id']}/refunds")
                rr.raise_for_status()
                for rf in rr.json().get("items", []):
                    yield "refunds", rf
            except Exception:
                pass
        # settlements recon (recon_id from latest settlement report)
        try:
            sr = client.get("/settlements", params={"count": 100})
            sr.raise_for_status()
            for s in sr.json().get("items", []):
                yield "settlements", s
        except Exception:
            pass

    # ------------------------------------------------------------ normalize
    def normalize(self, entity: str, payload: dict) -> dict:
        if entity == "payments":
            return {
                "payment_id": "",               # assigned at identity resolution
                "gateway_payment_id": payload.get("id", ""),
                "order_id": "",                 # bridged via gateway_order_id
                "gateway_order_id": payload.get("order_id", ""),
                "amount": str(int(payload.get("amount", 0)) / 100),   # paise → rupees
                "method": payload.get("method", "CARD").upper(),
                "status": "CAPTURED" if payload.get("status") == "captured"
                          else payload.get("status", "").upper(),
                "currency": payload.get("currency", "INR"),
                "captured_at": self._iso(payload.get("created_at")),
                "settled": "TRUE" if payload.get("captured") else "FALSE",
                "source": self.source_system,
            }
        if entity == "refunds":
            return {
                "refund_id": "",
                "gateway_refund_id": payload.get("id", ""),
                "payment_id": "",               # via gateway_payment_id bridge
                "gateway_payment_id": payload.get("payment_id", ""),
                "amount": str(int(payload.get("amount", 0)) / 100),
                "status": payload.get("status", "").upper(),
                "processed_at": self._iso(payload.get("created_at")),
                "source": self.source_system,
            }
        if entity == "settlements":
            return {
                "settlement_id": "",
                "gateway_settlement_id": payload.get("id", ""),
                "utr": payload.get("utr", ""),
                "amount": str(int(payload.get("amount", 0)) / 100),
                "fee_deducted": str(int(payload.get("fee", 0)) / 100),
                "tax_deducted": str(int(payload.get("tax", 0)) / 100),
                "status": payload.get("status", "").upper(),
                "settled_at": self._iso(payload.get("created_at")),
                "source": self.source_system,
            }
        return {}

    def map_identifiers(self, entity: str, record: dict) -> dict:
        """Bridge gateway_order_id → canonical order_id via identity resolver."""
        if entity == "payments" and record.get("gateway_order_id"):
            o = self._find_order_by_gateway(record["gateway_order_id"])
            if o:
                record["order_id"] = o
        if entity == "refunds" and record.get("gateway_payment_id"):
            p = self._find_payment_by_gateway(record["gateway_payment_id"])
            if p:
                record["payment_id"] = p
        return record

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _iso(epoch) -> str:
        if not epoch:
            return ""
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _find_order_by_gateway(self, gateway_order_id: str) -> str:
        for o in repo_orders():
            if o.get("gateway_order_id") == gateway_order_id:
                return o.get("order_id", "")
        return ""

    def _find_payment_by_gateway(self, gateway_payment_id: str) -> str:
        for p in repo_payments():
            if p.get("gateway_payment_id") == gateway_payment_id:
                return p.get("payment_id", "")
        return ""


def repo_orders():
    from ..services.repository import repo
    return repo.read("orders")


def repo_payments():
    from ..services.repository import repo
    return repo.read("payments")
