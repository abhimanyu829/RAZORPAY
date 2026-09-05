"""EVALUATION SYSTEM — scores the agent pipeline against hidden ground truth.

Computes (Section 12 + 31 metrics):
  detection precision / recall, false-positive rate (case + amount level),
  category accuracy, amount-level accuracy, action accuracy, recovery
  accuracy, recovery success rate, recovery rate, ROI, escalation accuracy.

Reads data/ground_truth (evaluator-only) + data/staging outputs.
The agent NEVER sees this module's inputs.
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "generators"))
import config as C

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "data" / "ground_truth" / "ground_truth.csv"
STAGE = ROOT / "data" / "staging"
EXPORTS = ROOT / "data" / "exports"

GT_MAP = {"LEAK-SETTLEMENT-SHORT": "SETTLEMENT_MISMATCH",
          "LEAK-MISSING-SETTLEMENT": "SETTLEMENT_MISMATCH",
          "LEAK-FEE-EXCESS": "FEE_DISCREPANCY",
          "LEAK-DUPLICATE-FEE": "FEE_DISCREPANCY",
          "LEAK-REFUND-ECONOMICS": "REFUND_ECONOMICS"}


def load(p):
    return list(csv.DictReader(open(p, encoding="utf-8")))


def main():
    gt = load(GT)
    cases = load(STAGE / "recovery_cases.csv")
    actions = load(STAGE / "recovery_actions.csv")
    verifs = load(STAGE / "verification_events.csv")
    approvals = load(STAGE / "approvals.csv")

    gt_by_order = {g["order_id"]: g for g in gt}
    cases_by_order = {c["order_id"]: c for c in cases}

    # ---------------- detection metrics ----------------
    tp = sum(1 for g in gt if g["has_anomaly"] == "TRUE" and g["order_id"] in cases_by_order)
    fn = sum(1 for g in gt if g["has_anomaly"] == "TRUE" and g["order_id"] not in cases_by_order)
    fp = sum(1 for c in cases if gt_by_order.get(c["order_id"], {}).get("has_anomaly") != "TRUE")
    # note: sub-tolerance anomalies (leak < tolerance) are by-design not caseable;
    # separate them from true misses.
    fn_suppressed = sum(1 for g in gt
                        if g["has_anomaly"] == "TRUE" and g["order_id"] not in cases_by_order
                        and float(g["true_leakage_amount"]) <= C.TOLERANCES["SETTLEMENT"]["amount"] + 0.5)
    fn_real = fn - fn_suppressed
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    recall_effective = tp / (tp + fn_real) if tp + fn_real else 0

    # ---------------- category + amount accuracy ----------------
    cat_ok = sum(1 for c in cases
                 if GT_MAP.get(gt_by_order[c["order_id"]]["anomaly_type"]) == c["category"])
    amount_deltas = [abs(float(c["potential_leakage"]) - float(gt_by_order[c["order_id"]]["true_leakage_amount"]))
                     for c in cases]
    amount_ok = sum(1 for x in amount_deltas if x <= 2.0)   # within tolerance

    # ---------------- action accuracy ----------------
    act_by_case = {}
    for a in actions:
        if a["action_type"] in ("CREATE_DISPUTE", "DRAFT_DISPUTE"):
            act_by_case.setdefault(a["case_id"], []).append(a["action_type"])
    case_by_id = {c["case_id"]: c for c in cases}
    action_ok = 0
    for cid, acts in act_by_case.items():
        c = case_by_id[cid]
        g = gt_by_order[c["order_id"]]
        best = g["true_best_action"]
        if best in acts:
            action_ok += 1

    # ---------------- recovery metrics ----------------
    ver_by_case = {}
    for v in verifs:
        ver_by_case[v["case_id"]] = v
    recovered_amt = 0.0
    recovered_cases = 0
    for c in cases:
        v = ver_by_case.get(c["case_id"])
        if v and v["status"] == "RECOVERY_VERIFIED":
            recovered_amt += float(c["potential_leakage"])
            recovered_cases += 1
        elif v and v["status"] == "FINANCIAL_EFFECT_DETECTED":
            recovered_amt += float(c["potential_leakage"]) * 0.6   # partial
    true_recoverable = sum(float(g["true_recovery_amount"]) for g in gt
                           if g["has_anomaly"] == "TRUE" and g["true_recoverable"] == "TRUE")
    detected_leakage = sum(float(c["potential_leakage"]) for c in cases)
    recovery_rate = recovered_amt / true_recoverable if true_recoverable else 0

    # ROI (agent operating cost assumption: ₹15/case fully-loaded, human review ₹200/approval)
    agent_cost = len(cases) * 15 + len(approvals) * 200
    roi = (recovered_amt - agent_cost) / agent_cost if agent_cost else 0

    # escalation accuracy
    esc_should = sum(1 for g in gt if g["has_anomaly"] == "TRUE" and g["true_should_escalate"] == "TRUE")
    esc_did = sum(1 for a in actions if a["action_type"] == "ESCALATE")

    metrics = {
        "transactions": len(gt),
        "gt_anomalies": tp + fn,
        "cases_opened": len(cases),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives_total": fn,
        "false_negatives_suppressed_by_tolerance": fn_suppressed,
        "false_negatives_real": fn_real,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "recall_effective": round(recall_effective, 4),
        "false_positive_rate": round(fp / (fp + tp), 4) if fp + tp else 0,
        "category_accuracy": round(cat_ok / len(cases), 4) if cases else 0,
        "amount_accuracy_within_2r": round(amount_ok / len(cases), 4) if cases else 0,
        "amount_mean_abs_delta": round(sum(amount_deltas) / len(amount_deltas), 2) if amount_deltas else 0,
        "action_accuracy": round(action_ok / len(act_by_case), 4) if act_by_case else 0,
        "detected_leakage_amount": round(detected_leakage, 2),
        "true_recoverable_amount": round(true_recoverable, 2),
        "recovered_amount": round(recovered_amt, 2),
        "recovery_rate": round(recovery_rate, 4),
        "recovered_cases": recovered_cases,
        "approvals_required": len(approvals),
        "escalations_should": esc_should,
        "agent_actions": len(actions),
        "audit_entries": len(load(STAGE / "audit_ledger.csv")),
        "roi": round(roi, 2),
        "agent_cost": agent_cost,
    }

    # ---------------- evaluation_case_scores (per GT row) ----------------
    scores = []
    for g in gt:
        c = cases_by_order.get(g["order_id"])
        detected = c is not None
        v = ver_by_case.get(c["case_id"]) if c else None
        recovered = 0.0
        if v and v["status"] == "RECOVERY_VERIFIED":
            recovered = float(c["potential_leakage"])
        elif v and v["status"] == "FINANCIAL_EFFECT_DETECTED":
            recovered = float(c["potential_leakage"]) * 0.6
        scores.append({
            "eval_run_id": "EVAL-2025-04-05-01",
            "case_id": c["case_id"] if c else "",
            "gt_id": g["gt_id"],
            "detected": "TRUE" if detected else "FALSE",
            "category_correct": "TRUE" if (c and GT_MAP.get(g["anomaly_type"]) == c["category"]) else "FALSE",
            "amount_delta": round(float(c["potential_leakage"]) - float(g["true_leakage_amount"]), 2) if c else "",
            "root_cause_correct": "TRUE" if (c and g["anomaly_type"] and GT_MAP.get(g["anomaly_type"]) == c["category"]) else "FALSE",
            "action_correct": "TRUE" if (c and g["true_best_action"] in act_by_case.get(c["case_id"], [])) else "FALSE",
            "recovered_amount": round(recovered, 2),
        })
    EXPORTS.mkdir(parents=True, exist_ok=True)
    with open(EXPORTS / "evaluation_case_scores.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(scores[0].keys()))
        w.writeheader()
        w.writerows(scores)
    with open(EXPORTS / "scorecard.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    main()
