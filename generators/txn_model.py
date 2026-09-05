"""Causal transaction model: one master transaction and every financial event
it spawns. Fee/settlement math lives ONLY here (deterministic, mirrors seed.sql).
"""
from datetime import datetime, timedelta, timezone
import random
import config as C

UTC = timezone.utc

def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def d(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def money(x):
    return round(x, 2)

def expected_fee(amount, method):
    rc = C.RATE_CARDS[method]
    fee = rc["pct"] * amount + rc["fixed"]
    if rc["min"] and fee < rc["min"]:
        fee = rc["min"]
    if rc["max"] and fee > rc["max"]:
        fee = rc["max"]
    fee = money(fee)
    tax = money(fee * C.GST_ON_FEE_RATE) if rc["gst_on_fee"] else 0.0
    return fee, tax

def expected_settlement(amount, method):
    fee, tax = expected_fee(amount, method)
    return money(amount - fee - tax), fee, tax


class Txn:
    def __init__(self, idx, order_dt, rng):
        self.rng = rng
        self.idx = idx
        self.txn_id = f"TXN-{idx:03d}"
        self.order_id = f"ORD-{idx}"
        self.order_number = f"#{1000 + idx}"
        self.gateway_order_id = f"order_{idx:06d}"
        self.customer_id = f"CUS-{self.rng.randint(1, C.CUSTOMER_POOL):04d}"
        self.order_dt = order_dt
        self.method = self._pick_method()
        self.brand = self.rng.choice(C.INSTRUMENT_BRANDS["CARD"]) if self.method == "CARD" else ""
        self.amount = self._pick_amount()
        self.anomalies = []
        self.flags = {}
        self.payments = []
        self.fees = []
        self.refunds = []
        self.settlements = []
        self.bank_txns = []
        self.invoice = None
        self.gst_lines = []
        self.ground_truth = None

    def _pick_method(self):
        keys = list(C.PAYMENT_METHOD_WEIGHTS)
        weights = list(C.PAYMENT_METHOD_WEIGHTS.values())
        return self.rng.choices(keys, weights=weights)[0]

    def _pick_amount(self):
        x = self.rng.lognormvariate(0, 1.05) * 1100
        return round(min(max(x, C.AMOUNT_MIN), C.AMOUNT_MAX), 2)

    def build_legs(self):
        self._payment()
        self._fees()
        self._refunds_if_any()
        self._settlement()
        self._bank()
        self._invoice_and_gst()
        return self

    def _payment(self):
        if self.flags.get("abandoned"):
            return
        if self.flags.get("split"):
            part1 = money(self.amount * 0.6)
            parts = [part1, money(self.amount - part1)]
        else:
            parts = [self.amount]
        for seq, amt in enumerate(parts):
            pid = f"PAY-{self.idx:04d}" if seq == 0 else f"PAY-{self.idx:04d}-2"
            gid = f"pay_{self.idx:06d}{'abcdefghij'[seq]}x" + "k" * self.rng.randint(4, 10)
            self.payments.append({
                "payment_id": pid,
                "gateway_payment_id": gid,
                "order_id": self.order_id,
                "gateway_order_id": self.gateway_order_id,
                "customer_id": self.customer_id,
                "amount": amt,
                "method": self.method,
                "instrument_brand": self.brand,
                "status": "CAPTURED",
                "captured_at": iso(self.order_dt + timedelta(minutes=self.rng.randint(1, 20))),
            })

    def _fees(self):
        for i, p in enumerate(self.payments):
            fee, tax = expected_fee(p["amount"], self.method)
            fid = f"FEE-{self.idx:04d}" if i == 0 else f"FEE-{self.idx:04d}-2"
            self.fees.append({
                "fee_id": fid,
                "payment_id": p["payment_id"],
                "order_id": self.order_id,
                "fee_type": "MDR",
                "amount": fee,
                "tax_amount": tax,
                "rate_card_id": C.RATE_CARDS[self.method]["rate_card_id"],
                "fee_event_at": p["captured_at"],
            })

    def _refunds_if_any(self):
        if self.flags.get("refund"):
            amt = money(self.amount * self.rng.uniform(0.2, 0.5))
            self.refunds.append({
                "refund_id": f"REF-{self.idx:04d}",
                "payment_id": self.payments[0]["payment_id"],
                "order_id": self.order_id,
                "gateway_refund_id": f"rfnd_{self.idx:06d}",
                "status": "PROCESSED",
                "amount": amt,
                "refund_reason": "customer request",
                "processed_at": iso(self.order_dt + timedelta(days=self.rng.randint(1, 5))),
            })

    def _settlement(self):
        if self.flags.get("missing_settlement"):
            return
        for i, p in enumerate(self.payments):
            exp_settle, fee, tax = expected_settlement(p["amount"], self.method)
            refunded = sum(r["amount"] for r in self.refunds if r["payment_id"] == p["payment_id"])
            fee_ret = money(fee * (refunded / p["amount"])) if refunded else 0.0
            credit = money(p["amount"] - fee - tax - refunded + fee_ret)
            sid = f"SET-{self.idx:04d}" if i == 0 else f"SET-{self.idx:04d}-2"
            utr = f"UTR{self.idx:08d}" if i == 0 else f"UTR{self.idx:08d}B"
            settled_dt = self.order_dt + timedelta(days=C.SETTLEMENT_T_DAYS + self.rng.randint(0, 1))
            self.settlements.append({
                "settlement_id": sid,
                "gateway_settlement_id": f"set_{self.idx:06d}{'ab'[i]}",
                "payment_id": p["payment_id"],
                "order_id": self.order_id,
                "utr": utr,
                "status": "PROCESSED",
                "settlement_type": "SETTLEMENT",
                "amount": credit,
                "fee_deducted": fee,
                "tax_deducted": tax,
                "settled_at": iso(settled_dt),
                "expected_credit_date": (self.order_dt + timedelta(days=C.SETTLEMENT_T_DAYS)).date().isoformat(),
            })

    def _bank(self):
        for i, s in enumerate(self.settlements):
            if s["status"] != "PROCESSED":
                continue
            if self.flags.get("bank_not_arrived"):
                continue
            lag = C.BANK_LAG_DAYS
            if self.flags.get("bank_delay"):
                lag = C.BANK_LAG_DAYS + 3
            bid = f"BNK-{self.idx:04d}" if i == 0 else f"BNK-{self.idx:04d}-2"
            self.bank_txns.append({
                "bank_txn_id": bid,
                "utr": s["utr"],
                "txn_type": "CREDIT",
                "direction": "IN",
                "amount": s["amount"],
                "value_date": (d(s["settled_at"]) + timedelta(days=lag)).date().isoformat(),
                "txn_timestamp": iso(d(s["settled_at"]) + timedelta(days=lag)),
                "narration": f"RAZORPAY SOFTWARE PVT LTD {s['utr']}",
                "counterparty": "RAZORPAY SOFTWARE PVT LTD",
            })

    def _invoice_and_gst(self):
        if not self.payments:
            return
        p = self.payments[0]
        taxable = money(self.amount / (1 + C.INVOICE_GST_RATE))
        gst_amt = money(self.amount - taxable)
        intra = self.rng.random() < C.INTRA_STATE_PCT / 100
        issue_dt = d(p["captured_at"]) + timedelta(days=1)
        self.invoice = {
            "invoice_id": f"INV-{self.idx:04d}",
            "order_id": self.order_id,
            "customer_id": self.customer_id,
            "invoice_number": f"INV/2025/{1000 + self.idx}",
            "status": "PAID",
            "issue_date": issue_dt.date().isoformat(),
            "due_date": (issue_dt + timedelta(days=30)).date().isoformat(),
            "taxable_value": taxable,
            "gst_rate": C.INVOICE_GST_RATE,
            "gst_amount": gst_amt,
            "total_amount": money(taxable + gst_amt),
            "place_of_supply": "27" if intra else "29",
        }
        fee_tax = self.fees[0]["tax_amount"] if self.fees else 0
        fee_amt = self.fees[0]["amount"] if self.fees else 0
        self.gst_lines = [
            {
                "gst_record_id": f"GST-{self.idx:04d}-OUT",
                "invoice_id": self.invoice["invoice_id"],
                "order_id": self.order_id,
                "gst_type": "OUTPUT",
                "return_period": issue_dt.strftime("%Y-%m"),
                "gstin": f"29ABCDE{self.idx:04d}F1Z5",
                "taxable_value": taxable,
                "igst": 0 if intra else gst_amt,
                "cgst": money(gst_amt / 2) if intra else 0,
                "sgst": money(gst_amt - money(gst_amt / 2)) if intra else 0,
                "cess": 0,
                "total_tax": gst_amt,
                "itc_eligible": "FALSE",
                "itc_matched": "",
                "filed_status": "FILED",
            },
            {
                "gst_record_id": f"GST-{self.idx:04d}-IN",
                "invoice_id": self.invoice["invoice_id"],
                "order_id": self.order_id,
                "gst_type": "INPUT",
                "return_period": issue_dt.strftime("%Y-%m"),
                "gstin": "29AAACR2288E1ZK",
                "taxable_value": fee_amt,
                "igst": 0,
                "cgst": money(fee_tax / 2),
                "sgst": money(fee_tax - money(fee_tax / 2)),
                "cess": 0,
                "total_tax": fee_tax,
                "itc_eligible": "TRUE",
                "itc_matched": "TRUE",
                "filed_status": "RECONCILED",
            },
        ]
