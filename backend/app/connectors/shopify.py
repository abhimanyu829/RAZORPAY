"""SHOPIFY CONNECTOR — development/test store integration (Section 20).

Orders, customers, order state, payment references via the Admin REST API
(without or with token). Maps Shopify order ID ↔ gateway order ID through the
existing identity resolver. Degrades gracefully without credentials.
"""
from __future__ import annotations

import json
from typing import Iterable

from ..settings import settings
from .base import BaseConnector

API_VERSION = "2025-01"


class ShopifyConnector(BaseConnector):
    connector_id = "SHOPIFY_DEV"
    source_system = "SHOPIFY"
    entities = ["orders", "customers"]

    def _get_client(self):
        if self._client is not None:
            return self._client
        import httpx
        base = f"https://{settings.shopify_domain}/admin/api/{API_VERSION}"
        self._client = httpx.Client(
            base_url=base,
            headers={"X-Shopify-Access-Token": settings.shopify_access_token},
            timeout=20.0)
        return self._client

    def __init__(self):
        self._client = None

    def authenticate(self) -> bool:
        if not (settings.shopify_domain and settings.shopify_access_token):
            return False
        try:
            r = self._get_client().get("/shop.json")
            return r.status_code == 200
        except Exception:
            return False

    def health_check(self) -> dict:
        if not (settings.shopify_domain and settings.shopify_access_token):
            return {"healthy": False,
                    "detail": "SHOPIFY_DOMAIN/TOKEN not configured — "
                              "connector idle (synthetic mode active)"}
        try:
            ok = self.authenticate()
            return {"healthy": ok, "detail": "dev store reachable" if ok else "auth failed"}
        except Exception as e:
            return {"healthy": False, "detail": f"transport error: {e}"}

    def fetch(self, checkpoint: dict | None) -> Iterable[tuple[str, dict]]:
        if not (settings.shopify_domain and settings.shopify_access_token):
            return
        client = self._get_client()
        since_id = (checkpoint or {}).get("last_external_id", "")
        params = {"limit": 250, "status": "any"}
        if since_id:
            params["since_id"] = since_id
        try:
            r = client.get("/orders.json", params=params)
            r.raise_for_status()
            orders = r.json().get("orders", [])
        except Exception:
            return
        for o in orders:
            self._last_ext = str(o.get("id", ""))
            self._last_cursor = self._last_ext
            yield "orders", o
            for tx in o.get("transactions", []) or []:
                pass  # payment references flow through gateway connector
        try:
            cr = client.get("/customers.json", params={"limit": 250})
            cr.raise_for_status()
            for c in cr.json().get("customers", []):
                yield "customers", c
        except Exception:
            pass

    def normalize(self, entity: str, payload: dict) -> dict:
        if entity == "orders":
            total = payload.get("total_price") or "0"
            return {
                "order_id": "",
                "order_number": f"#{payload.get('order_number', '')}",
                "customer_id": "",
                "gateway_customer_id": str(payload.get("customer", {}).get("id", "")),
                "net_amount": str(total),
                "status": self._status(payload),
                "placed_at": self._iso(payload.get("created_at")),
                "gateway_order_id": str(payload.get("id", "")),
                "source": self.source_system,
            }
        if entity == "customers":
            return {
                "customer_id": "",
                "gateway_customer_id": str(payload.get("id", "")),
                "name": f"{payload.get('first_name', '')} {payload.get('last_name', '')}".strip(),
                "email": payload.get("email", ""),
                "phone": payload.get("phone", ""),
                "city": (payload.get("addresses") or [{}])[0].get("city", ""),
                "state": (payload.get("addresses") or [{}])[0].get("province", ""),
                "segment": "RETAIL",
                "signup_date": (payload.get("created_at") or "")[:10],
                "source": self.source_system,
                "normalized": "TRUE",
            }
        return {}

    def map_identifiers(self, entity: str, record: dict) -> dict:
        if entity == "orders":
            # find existing canonical customer by gateway id (weak identity);
            # the identity resolver handles the rest downstream
            pass
        return record

    @staticmethod
    def _status(o: dict) -> str:
        if o.get("cancelled_at"):
            return "CANCELLED"
        fin = o.get("financial_status")
        return {"paid": "PAID", "pending": "PENDING",
                "refunded": "REFUNDED", "partially_refunded": "PARTIALLY_REFUNDED",
                "voided": "VOIDED"}.get(fin, fin or "PENDING").upper()

    @staticmethod
    def _iso(ts: str) -> str:
        if not ts:
            return ""
        return ts.replace("T", "T").replace("+05:30", "Z")[:20] + "Z"
