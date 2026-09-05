"""WEBHOOK PROCESSOR — idempotent event ingestion (Section 24).

Webhook → signature validation → raw persistence → dedupe → normalize →
affected transaction lookup → reconciliation refresh flag → case update.

Every webhook is persisted exactly once (unique provider event id); replays
return the stored result with replayed=true. Razorpay signs with HMAC-SHA256
(X-Razorpay-Signature); Shopify with HMAC-SHA256 base64 (X-Shopify-Hmac-Sha256).
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from ..settings import settings
from ..services.repository import repo, now_iso


class WebhookError(Exception):
    pass


class WebhookProcessor:
    def __init__(self):
        self._handlers: dict[str, Any] = {}
        self._register_defaults()

    # ------------------------------------------------------------- dispatch
    def process(self, source: str, headers: dict, body: bytes) -> dict:
        # 1) signature validation (fail closed)
        self._verify_signature(source, headers, body)

        # 2) parse
        try:
            payload = json.loads(body)
        except ValueError as e:
            raise WebhookError(f"invalid JSON: {e}") from e

        # 3) provider event id (dedupe key)
        event_id = self._event_id(source, payload)
        webhook_id = f"{source}:{event_id}" if event_id else \
            f"{source}:{hashlib.sha256(body).hexdigest()[:16]}"

        # 4) dedupe — exact one-time processing
        existing = repo.read_one("webhook_events", "webhook_id", webhook_id)
        if existing:
            return {"status": "DUPLICATE", "webhook_id": webhook_id,
                    "replayed": True,
                    "detail": existing.get("status", "RECEIVED")}

        # 5) raw persistence FIRST (never discard the raw response)
        sha = hashlib.sha256(body).hexdigest()
        row = {
            "webhook_id": webhook_id, "source_system": source,
            "event_type": self._event_type(source, payload),
            "payload": payload, "payload_sha256": sha,
            "received_at": now_iso(), "status": "RECEIVED", "processed_at": "",
        }
        repo.append("webhook_events", row)

        # 6) normalize + affected-transaction lookup
        affected = self._route(source, payload)

        # 7) mark processed
        rows = repo.read("webhook_events")
        for r in rows:
            if r.get("webhook_id") == webhook_id:
                r["status"] = "PROCESSED"
                r["processed_at"] = now_iso()
        repo.write("webhook_events", rows, append=False)

        return {"status": "PROCESSED", "webhook_id": webhook_id,
                "event_type": row["event_type"], "affected": affected}

    # ------------------------------------------------------------ signature
    def _verify_signature(self, source: str, headers: dict, body: bytes) -> None:
        secret = settings.webhook_secrets.get(source)
        if not secret:
            raise WebhookError(f"no webhook secret configured for {source}")
        if source == "razorpay":
            sig = headers.get("x-razorpay-signature", "")
            expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                raise WebhookError("razorpay signature mismatch")
        elif source == "shopify":
            sig = headers.get("x-shopify-hmac-sha256", "")
            expected = hmac.new(secret.encode(), body, hashlib.sha256).b64encode().decode()
            if not hmac.compare_digest(sig, expected):
                raise WebhookError("shopify signature mismatch")
        else:
            raise WebhookError(f"unknown webhook source {source}")

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _event_id(source: str, payload: dict) -> str:
        if source == "razorpay":
            return payload.get("event", "") + ":" + \
                str((payload.get("payload") or {}).get("payment", {}).get("entity", {}).get("id", ""))
        return ""

    @staticmethod
    def _event_type(source: str, payload: dict) -> str:
        if source == "razorpay":
            return payload.get("event", "unknown")
        if source == "shopify":
            return payload.get("topic", "unknown")
        return "unknown"

    def _route(self, source: str, payload: dict) -> dict:
        """Affected transaction lookup → which case/order needs recon refresh."""
        if source == "razorpay":
            ent = (payload.get("payload") or {}).get("payment", {}).get("entity", {})
            gpid = ent.get("id", "")
            if gpid:
                p = self._payment_by_gateway(gpid)
                if p:
                    return {"payment_id": p.get("payment_id", ""),
                            "order_id": p.get("order_id", ""),
                            "case_ids": self._cases_for_order(p.get("order_id", "")),
                            "action": "RECON_REFRESH"}
            return {"payment_id": "", "order_id": "", "case_ids": [],
                    "action": "NEW_PAYMENT_RECON"}
        return {"action": "NO_OP"}

    @staticmethod
    def _payment_by_gateway(gateway_payment_id: str):
        from ..services.repository import repo
        for p in repo.read("payments"):
            if p.get("gateway_payment_id") == gateway_payment_id:
                return p
        return None

    @staticmethod
    def _cases_for_order(order_id: str) -> list[str]:
        from ..services.repository import repo
        return [c.get("case_id", "") for c in repo.read("recovery_cases")
                if c.get("order_id") == order_id]

    # ------------------------------------------------------ default routing
    def _register_defaults(self) -> None:
        pass


processor = WebhookProcessor()


def demo_webhook() -> dict:                                  # pragma: no cover
    """Build + process a valid demo razorpay webhook (dev-secret)."""
    import base64
    body = json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": "pay_000001axkkkk",
                                           "amount": 150000,
                                           "status": "captured"}}},
    }).encode()
    sig = hmac.new(b"dev-secret-razorpay", body, hashlib.sha256).hexdigest()
    return processor.process("razorpay",
                             {"x-razorpay-signature": sig}, body)


if __name__ == "__main__":
    print(json.dumps(demo_webhook(), indent=2))
