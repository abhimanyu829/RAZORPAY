"""Central configuration for all generators and engines.

All anomaly percentages live HERE (and only here) — configurable, never
hard-coded in generator logic. Mirrors database/seed.sql contractual truth.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# ---------------------------------------------------------------- universe --
N_TRANSACTIONS = 1000            # dev volume (testing: 10k, stress: 100k+)
RANDOM_SEED = 42                 # reproducible synthetic universe
EVAL_NOW = "2025-04-05T00:00:00Z"  # fixed evaluation horizon (all data due by now)
DATE_RANGE = ("2025-01-05", "2025-03-25")  # order dates spread

CUSTOMER_POOL = 250

# amount distribution (INR): lognormal-ish, realistic Indian e-commerce
AMOUNT_MIN, AMOUNT_MAX = 299.0, 45000.0
AMOUNT_MEDIAN = 2400.0

PAYMENT_METHOD_WEIGHTS = {"CARD": 45, "UPI": 30, "NETBANKING": 10, "WALLET": 10, "EMI": 5}
INSTRUMENT_BRANDS = {"CARD": ["VISA", "MASTERCARD", "RUPAY"]}

# ---------------------------------------------------------------- contracts --
# Mirrors cfg.rate_cards rows in database/seed.sql exactly.
RATE_CARDS = {
    "CARD":       {"rate_card_id": "RC-CARD-2025",   "pct": 0.02000, "fixed": 0.00,  "min": 0.00, "max": None, "gst_on_fee": True},
    "UPI":        {"rate_card_id": "RC-UPI-2025",    "pct": 0.00400, "fixed": 0.00,  "min": 0.00, "max": None, "gst_on_fee": True},
    "NETBANKING": {"rate_card_id": "RC-NB-2025",     "pct": 0.00000, "fixed": 12.00, "min": 0.00, "max": None, "gst_on_fee": True},
    "WALLET":     {"rate_card_id": "RC-WALLET-2025", "pct": 0.01900, "fixed": 0.00,  "min": 0.00, "max": None, "gst_on_fee": True},
    "EMI":        {"rate_card_id": "RC-EMI-2025",    "pct": 0.02350, "fixed": 0.00,  "min": 0.00, "max": None, "gst_on_fee": True},
}
GST_ON_FEE_RATE = 0.18           # GST charged on MDR
INVOICE_GST_RATE = 0.18          # GST-inclusive invoice pricing (18%)
INTRA_STATE_PCT = 60             # % of invoices that are intra-state (CGST+SGST vs IGST)

SETTLEMENT_T_DAYS = 3            # Razorpay-style T+3 settlement
BANK_LAG_DAYS = 1                # bank credit lands 1 day after settlement

# SLA (mirrors cfg.sla_rules)
SLA_SETTLEMENT_GRACE_DAYS = 2
SLA_SETTLEMENT_HARD_DAYS = 45

# ---------------------------------------------------------------- tolerances (mirrors cfg.tolerance_rules)
TOLERANCES = {
    "PAYMENT":    {"amount": 0.50, "pct": 0.0005},
    "SETTLEMENT": {"amount": 2.00, "pct": 0.0010},
    "FEE":        {"amount": 1.00, "pct": 0.0050},
    "REFUND":     {"amount": 0.50, "pct": 0.0005},
    "BANK":       {"amount": 2.00, "pct": 0.0010},
}

# ---------------------------------------------------- anomaly distribution --
# % of transactions receiving each injected anomaly. CONFIGURABLE.
ANOMALY_PERCENTAGES = {
    "fee_excess": 5.0,        # gateway charged above rate card (MVP cat: FEE_DISCREPANCY)
    "settlement_short": 3.0,  # settlement credited below expectation (MVP cat: SETTLEMENT_MISMATCH)
    "missing_settlement": 2.0,# settlement never arrived, past deadline (SETTLEMENT_MISMATCH, escalate)
    "duplicate_fee": 1.0,     # fee charged twice (FEE_DISCREPANCY)
    "refund_economics": 3.0,  # fee not returned pro-rata on refund (REFUND_ECONOMICS)
}
OVERLAP_PCT = 20.0            # % of anomalous txns that receive a SECOND anomaly
NORMAL_REFUND_PCT = 8.0      # healthy txns with a legitimate refund (no anomaly)
SPLIT_PAYMENT_PCT = 3.0      # healthy txns paid in two captures (one-to-many recon)
BANK_DELAY_PCT = 12.0        # healthy txns whose bank credit lands late (within grace)
ABANDONED_ORDER_PCT = 2.0   # healthy orders never paid (no anomaly, no case)
BANK_NOT_ARRIVED_YET_PCT = 1.0  # healthy: bank credit still inside window => TIMING class
DELIBERATELY_BAD_ROWS = 3    # rows for the validation/quarantine demo

# recovery simulation (ground truth drives outcomes; these shape variety)
LARGE_SETTLEMENT_CAP = 5000.0   # RP-SETTLEMENT-LARGE boundary (disputes must escalate)

# --------------------------------------------------------------- phase flags --
PHASE2_ENABLED = False   # marketplace_deductions, subscriptions, customer_events
PHASE3_ENABLED = False   # receivables, chargebacks

PHASE2_PERCENTAGES = {"marketplace_deduction": 2.0, "subscription_failure": 2.0}
PHASE3_PERCENTAGES = {"receivable_overdue": 2.0, "chargeback": 1.5}

# ------------------------------------------------------------------- output --
def raw_dir():   return DATA / "raw"
def normalized_dir(): return DATA / "normalized"
def staging_dir(): return DATA / "staging"
def ground_truth_dir(): return DATA / "ground_truth"
def evaluation_dir(): return DATA / "evaluation"
def exports_dir(): return DATA / "exports"
