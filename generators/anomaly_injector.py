"""ANOMALY INJECTION ENGINE — two phases:

  assign(txns, rng)         BEFORE legs are built — marks which txns carry
                            anomalies and sets pre-build flags (missing
                            settlement, refund for economics).
  apply_mutations(txns,rng) AFTER legs are built — mutates actual amounts
                            (fee excess, duplicate fee, settlement short,
                            unreturned refund fee).
  build_ground_truth(txns)  AFTER mutation — records hidden truth from FINAL
                            actuals, for ALL transactions (healthy too).

MVP anomaly codes → ops.leak_category:
  fee_excess         → FEE_DISCREPANCY
  duplicate_fee      → FEE_DISCREPANCY
  settlement_short   → SETTLEMENT_MISMATCH
  missing_settlement → SETTLEMENT_MISMATCH
  refund_economics   → REFUND_ECONOMICS
"""
import csv
from datetime import timedelta

import config as C
from txn_model import money, expected_fee, expected_settlement, d

ORDER = ["fee_excess", "settlement_short", "missing_settlement", "duplicate_fee", "refund_economics"]


# ---------------------------------------------------------------- assign ----
def assign(txns, rng):
    n = len(txns)
    eligible = [t for t in txns if not t.flags.get("abandoned")]
    counts = {k: int(len(eligible) * v / 100) for k, v in C.ANOMALY_PERCENTAGES.items()}
    rng.shuffle(eligible)
    assigned = {}
    cursor = 0

    # primary pools: disjoint slices of the shuffled eligible list
    pools = {}
    for code in ORDER:
        pools[code] = eligible[cursor:cursor + counts[code]]
        cursor += counts[code]
        for t in pools[code]:
            assigned[t.txn_id] = [code]

    # overlap: move some txns into a second pool (keep their primary too)
    overlap_n = int(len(assigned) * C.OVERLAP_PCT / 100)
    others = [t for t in eligible if t.txn_id not in assigned]
    rng.shuffle(others)
    added = 0
    i = 0
    while added < overlap_n and i < len(others) - 1:
        # pair two healthy txns, give each a primary+secondary anomaly
        a, b = others[i], others[i + 1]
        i += 2
        codes = rng.sample(ORDER, 2)
        pools[codes[0]].append(a)
        pools[codes[1]].append(b)
        assigned[a.txn_id] = codes
        assigned[b.txn_id] = list(reversed(codes))
        added += 2

    for t in txns:
        codes = assigned.get(t.txn_id, [])
        t.anomalies = codes
        # pre-build flags
        if "missing_settlement" in codes:
            t.flags["missing_settlement"] = True
        if "refund_economics" in codes and not t.refunds:
            t.flags["refund"] = True   # refund leg built normally (with fee_ret)
    return assigned


# ------------------------------------------------------------- mutations ----
def apply_mutations(txns, rng):
    for t in txns:
        for code in t.anomalies:
            MUTATORS[code](t, rng)


def _sync_bank(t, s):
    for b in t.bank_txns:
        if b["utr"] == s["utr"]:
            b["amount"] = s["amount"]


def mut_fee_excess(t, rng):
    """Charge 25-60% more fee than rate card; settlement reflects deduction."""
    for i, f in enumerate(t.fees):
        expected, _ = expected_fee(t.payments[i]["amount"], t.method)
        excess = money(expected * rng.uniform(1.25, 1.60))
        f["amount"] = excess
        f["tax_amount"] = money(excess * C.GST_ON_FEE_RATE)
        if t.settlements:
            s = t.settlements[i] if i < len(t.settlements) else t.settlements[0]
            s["amount"] = money(s["amount"] - (excess - expected))
            s["fee_deducted"] = excess
            s["tax_deducted"] = f["tax_amount"]
            _sync_bank(t, s)


def mut_duplicate_fee(t, rng):
    """Second identical fee event charged; settlement reduced by the duplicate."""
    if not t.fees or not t.settlements:
        return
    base = t.fees[0]
    dup = dict(base)
    dup["fee_id"] = base["fee_id"] + "-D"
    t.fees.append(dup)
    s = t.settlements[0]
    s["amount"] = money(s["amount"] - dup["amount"] - dup["tax_amount"])
    _sync_bank(t, s)


def mut_settlement_short(t, rng):
    """Settlement credited below expectation by 1-8% (beyond tolerance)."""
    if not t.settlements:
        return
    s = t.settlements[0]
    tol = C.TOLERANCES["SETTLEMENT"]["amount"]
    short = money(s["amount"] * rng.uniform(0.01, 0.08))
    if short <= tol:
        short = money(tol + max(s["amount"] * 0.01, 1.0))
    s["amount"] = money(s["amount"] - short)
    _sync_bank(t, s)


def mut_missing_settlement(t, rng):
    """Pre-build flag already suppressed settlement+bank legs. Nothing here."""
    return


def mut_refund_economics(t, rng):
    """Refund processed but fee NOT returned pro-rata (FR-REFUND-ECON-001
    violated): the healthy builder added fee_ret to the credit; remove it."""
    if not t.settlements or not t.refunds:
        return
    p = t.payments[0]
    fee, tax = expected_fee(p["amount"], t.method)
    refunded = sum(r["amount"] for r in t.refunds)
    fee_ret = money(fee * (refunded / p["amount"]))
    s = t.settlements[0]
    s["amount"] = money(s["amount"] - fee_ret)
    _sync_bank(t, s)


MUTATORS = {
    "fee_excess": mut_fee_excess,
    "duplicate_fee": mut_duplicate_fee,
    "settlement_short": mut_settlement_short,
    "missing_settlement": mut_missing_settlement,
    "refund_economics": mut_refund_economics,
}


# ----------------------------------------------------------- ground truth --
def build_ground_truth(txns):
    """Hidden truth from FINAL actuals — for every transaction, healthy or not.
    NEVER exposed to the agent (eval schema / data/ground_truth only)."""
    rows = []
    for t in txns:
        # refund-aware expectation (mirrors rule engine FR-SETTLE-CALC-001)
        expected_total = 0.0
        for p in t.payments:
            exp_s, fee, tax = expected_settlement(p["amount"], t.method)
            refunded = sum(r["amount"] for r in t.refunds if r["payment_id"] == p["payment_id"])
            fee_ret = money(fee * (refunded / p["amount"])) if refunded else 0.0
            expected_total += money(p["amount"] - fee - tax - refunded + fee_ret)
        expected_total = money(expected_total)
        actual_total = money(sum(s["amount"] for s in t.settlements))
        codes = t.anomalies
        t.ground_truth = _gt_row_or_healthy(t, expected_total, actual_total, codes)
        rows.append(t.ground_truth)
    return rows


def _gt_row_or_healthy(t, expected_total, actual_total, codes):
    if not codes or t.flags.get("abandoned"):
        return _gt_row(t, expected_total, actual_total, False, "", "", 0.0, False, 0.0,
                       "", "", "FALSE")
    total_leak = money(max(expected_total - actual_total, 0))
    # per-category components (fee mutations propagate into settlement, so the
    # settlement residual is the total minus fee/refund components)
    fee_component = 0.0
    for i, f in enumerate(t.fees):
        expected, _ = expected_fee(t.payments[i]["amount"] if i < len(t.payments) else t.payments[0]["amount"], t.method)
        fee_component += (f["amount"] + f["tax_amount"]) - (expected + money(expected * C.GST_ON_FEE_RATE))
    refund_component = 0.0
    if "refund_economics" in codes and t.refunds:
        p = t.payments[0]
        fee, _ = expected_fee(p["amount"], t.method)
        refunded = sum(r["amount"] for r in t.refunds)
        refund_component = money(fee * (refunded / p["amount"]))
    settlement_component = money(max(total_leak - max(fee_component, 0) - refund_component, 0))
    if "missing_settlement" in codes:
        settlement_component = money(max(total_leak - max(fee_component, 0) - refund_component, 0))

    comp = {
        "fee_excess": max(fee_component, 0) if "fee_excess" in codes else 0,
        "duplicate_fee": max(fee_component, 0) if "duplicate_fee" in codes else 0,
        "settlement_short": settlement_component if "settlement_short" in codes else 0,
        "missing_settlement": settlement_component if "missing_settlement" in codes else 0,
        "refund_economics": refund_component,
    }
    primary = max(codes, key=lambda c: comp.get(c, 0))
    leakage = total_leak
    if primary == "missing_settlement":
        root = "payment captured but settlement never issued; funds held at gateway"
        best = "CREATE_DISPUTE"
        ev = "RECON_RESULT|RULE_RESULT|RAW_PAYLOAD"
    elif primary == "fee_excess":
        root = "gateway charged MDR above negotiated rate card beyond tolerance"
        best = "DRAFT_DISPUTE"
        ev = "RECON_RESULT|RULE_RESULT|RATE_CARD"
    elif primary == "duplicate_fee":
        root = "duplicate MDR fee event charged for the same payment"
        best = "CREATE_DISPUTE"
        ev = "RECON_RESULT|RATE_CARD|RAW_PAYLOAD"
    elif primary == "settlement_short":
        root = "settlement credited below expected net of contractual fees and taxes"
        best = "DRAFT_DISPUTE" if t.amount <= C.LARGE_SETTLEMENT_CAP else "CREATE_DISPUTE"
        ev = "RECON_RESULT|RULE_RESULT|RAW_PAYLOAD"
    else:  # refund_economics
        root = "gateway did not return MDR fee pro-rata on processed refund"
        best = "CREATE_DISPUTE"
        ev = "RECON_RESULT|RULE_RESULT|RAW_PAYLOAD"
    recoverable = leakage > 0
    esc = "TRUE" if (primary == "missing_settlement" or t.amount > C.LARGE_SETTLEMENT_CAP) else "FALSE"
    return _gt_row(t, expected_total, actual_total, True, primary, root, leakage,
                   recoverable, leakage if recoverable else 0.0,
                   best, ev, esc)


def _primary_code(codes):
    """When anomalies overlap, the dominant leak category for scoring."""
    rank = ["missing_settlement", "duplicate_fee", "fee_excess", "settlement_short", "refund_economics"]
    for r in rank:
        if r in codes:
            return r
    return codes[0]


def _gt_row(t, exp, act, has_an, primary, root, leak, recov, recov_amt, best, ev, esc):
    return {
        "gt_id": f"GT-{t.idx:04d}",
        "txn_id": t.txn_id,
        "order_id": t.order_id,
        "payment_id": t.payments[0]["payment_id"] if t.payments else "",
        "has_anomaly": "TRUE" if has_an else "FALSE",
        "actual_problem": f"{primary} on {t.order_number}" if has_an else "",
        "anomaly_type": f"LEAK-{primary.upper().replace('_', '-')}" if has_an else "",
        "true_expected_amount": exp,
        "true_actual_amount": act,
        "true_leakage_amount": leak,
        "true_recoverable": "TRUE" if recov else "FALSE",
        "true_recovery_amount": recov_amt,
        "true_root_cause": root,
        "true_required_evidence": ev,
        "true_best_action": best,
        "true_deadline": (d(C.EVAL_NOW) + timedelta(days=C.SLA_SETTLEMENT_HARD_DAYS)).date().isoformat(),
        "true_should_escalate": esc,
    }


def write_ground_truth(gt_rows, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "ground_truth.csv"
    fields = ["gt_id", "txn_id", "order_id", "payment_id", "has_anomaly", "actual_problem",
              "anomaly_type", "true_expected_amount", "true_actual_amount", "true_leakage_amount",
              "true_recoverable", "true_recovery_amount", "true_root_cause",
              "true_required_evidence", "true_best_action", "true_deadline", "true_should_escalate"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in gt_rows:
            w.writerow(r)
    return path
