"""CONNECTOR REGISTRY — one sync entry point for all connectors (Section 32 API)."""
from __future__ import annotations

from ..services.repository import repo
from .bank_csv import BankCsvConnector
from .accounting_csv import AccountingCsvConnector
from .razorpay import RazorpayConnector
from .shopify import ShopifyConnector

_bank = BankCsvConnector()
_accounting = AccountingCsvConnector()
_razorpay = RazorpayConnector()
_shopify = ShopifyConnector()

CONNECTORS = {
    "BANK_CSV": _bank,
    "ACCOUNTING_CSV": _accounting,
    "RAZORPAY_TEST": _razorpay,
    "SHOPIFY_DEV": _shopify,
}


def sync(connector_id: str, limit: int | None = None) -> dict:
    if connector_id not in CONNECTORS:
        raise KeyError(f"unknown connector {connector_id}; "
                       f"known: {list(CONNECTORS)}")
    return CONNECTORS[connector_id].sync(limit=limit)


def health() -> dict:
    return {cid: c.health_check() for cid, c in CONNECTORS.items()}
