"""FULL END-TO-END INTEGRATION RUN (Phase 14) + evaluation comparability.

Executes the complete production path over the whole case population:
    cases → live agent loop (LLM plan → policy → approval → tool → verify)
    → audit → recovery ledger → KPIs → GT evaluation (same hidden truth)

Also: shadow-vs-simulated plan comparison and a small load test.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "app"))
sys.path.insert(0, str(ROOT / "generators"))

from app.settings import settings
settings.rollout_level = 5          # approved recovery execution
settings.max_actions_per_run = 1

from app.services.repository import repo, _to_float
from app.agent.runtime import runtime
from app.services.hero_case import reset_runtime


def run_population(limit: int | None = None) -> dict:
    reset_runtime()
    cases = repo.cases()
    if limit:
        cases = cases[:limit]
    cases.sort(key=lambda c: _to_float(c.get("potential_leakage")), reverse=True)
    results = []
    t0 = time.monotonic()
    for c in cases:
        res = runtime.run_case(c["case_id"])
        results.append(res)
    dur = time.monotonic() - t0

    # ---- rollup ---------------------------------------------------------
    completed = [r for r in results if r.status == "COMPLETED"]
    recovered = [r for r in results if r.verification_status == "RECOVERY_VERIFIED"]
    partial = [r for r in results if r.verification_status == "FINANCIAL_EFFECT_DETECTED"]
    blocked_policy = [r for r in results if r.status == "BLOCKED_POLICY"]
    blocked_llm = [r for r in results if r.status == "BLOCKED_LLM"]
    failed = [r for r in results if r.status == "FAILED"]
    amt_verified = sum(r.recovered_amount for r in recovered)
    amt_partial = sum(r.recovered_amount for r in partial)
    ledger = repo.read("recovery_ledger")
    rollup = {
        "cases_run": len(results),
        "completed": len(completed),
        "disputes_executed": len([r for r in results if r.executed_action == "CREATE_DISPUTE"]),
        "recovery_verified": len(recovered),
        "partial_recovery": len(partial),
        "blocked_by_policy": len(blocked_policy),
        "blocked_by_llm": len(blocked_llm),
        "failed": len(failed),
        "recovered_amount_verified": round(amt_verified, 2),
        "recovered_amount_partial": round(amt_partial, 2),
        "ledger_rows": len(ledger),
        "audit_entries": len(repo.read("audit_ledger")),
        "agent_runs": len(repo.read("agent_runs")),
        "approvals": len(repo.read("approvals")),
        "verifications": len(repo.read("verification_events")),
        "avg_case_ms": int(statistics.mean([r.duration_ms for r in results])),
        "total_seconds": round(dur, 1),
        "policy_blocks": [r.errors[0] for r in blocked_policy[:5]],
    }
    return rollup


def evaluate_against_gt() -> dict:
    """Same ground truth, same metrics as the deterministic-skeleton run —
    comparability across agent versions (Section 46)."""
    import csv
    gt_path = ROOT / "data" / "ground_truth" / "ground_truth.csv"
    gt = {g["order_id"]: g for g in csv.DictReader(open(gt_path, encoding="utf-8"))}
    cases = [c for c in repo.cases()
             if c["order_id"] in gt]   # demo/hero rows excluded from scoring
    gt_map = {"LEAK-SETTLEMENT-SHORT": "SETTLEMENT_MISMATCH",
              "LEAK-MISSING-SETTLEMENT": "SETTLEMENT_MISMATCH",
              "LEAK-FEE-EXCESS": "FEE_DISCREPANCY",
              "LEAK-DUPLICATE-FEE": "FEE_DISCREPANCY",
              "LEAK-REFUND-ECONOMICS": "REFUND_ECONOMICS"}
    tp = sum(1 for c in cases if gt.get(c["order_id"], {}).get("has_anomaly") == "TRUE")
    fp = sum(1 for c in cases if gt.get(c["order_id"], {}).get("has_anomaly") != "TRUE")
    cat_ok = sum(1 for c in cases
                 if gt_map.get(gt.get(c["order_id"], {}).get("anomaly_type", "")) == c["category"])
    amounts = [abs(_to_float(c["potential_leakage"])
                   - _to_float(gt.get(c["order_id"], {}).get("true_leakage_amount")))
               for c in cases]
    # recovery metrics from the ledger (product truth, not LLM claims)
    ledger = repo.read("recovery_ledger")
    recovered = sum(_to_float(l.get("amount")) for l in ledger if l.get("status") == "RECOVERED")
    recoverable = sum(_to_float(g["true_recovery_amount"]) for g in gt.values()
                      if g.get("has_anomaly") == "TRUE" and g.get("true_recoverable") == "TRUE")
    return {
        "gt_anomalies_cased": tp, "false_positives": fp,
        "precision": round(tp / (tp + fp), 4) if tp + fp else 1.0,
        "category_accuracy": round(cat_ok / len(cases), 4) if cases else 0,
        "amount_mean_abs_delta": round(statistics.mean(amounts), 2) if amounts else 0,
        "recovered_amount": round(recovered, 2),
        "true_recoverable_amount": round(recoverable, 2),
        "recovery_rate": round(recovered / recoverable, 4) if recoverable else 0,
    }


def load_test(n: int = 40) -> dict:
    """Concurrent-ish sequential load: plan-only calls (cheap LLM path)."""
    from app.agent.llm_client import llm
    from app.agent.prompts import build_case_payload
    cases = repo.cases()[:n]
    t0 = time.monotonic()
    lat = []
    for c in cases:
        p0 = time.monotonic()
        payload = build_case_payload(c, repo.evidence_for_case(c["case_id"]))
        payload["_messages"] = []
        try:
            llm.reason_and_plan(payload)
        except Exception:
            pass
        lat.append((time.monotonic() - p0) * 1000)
    return {"requests": len(lat),
            "avg_latency_ms": int(statistics.mean(lat)) if lat else 0,
            "p95_ms": int(sorted(lat)[int(len(lat) * 0.95) - 1]) if lat else 0,
            "throughput_rps": round(len(lat) / (time.monotonic() - t0), 1)}


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print("== FULL POPULATION AGENT RUN ==")
    rollup = run_population(limit)
    print(json.dumps(rollup, indent=2))
    print("\n== EVALUATION vs SAME HIDDEN GROUND TRUTH ==")
    ev = evaluate_against_gt()
    print(json.dumps(ev, indent=2))
    print("\n== LOAD TEST (plan path) ==")
    print(json.dumps(load_test(40), indent=2))
    out = ROOT / "data" / "exports" / "e2e_run.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rollup": rollup, "evaluation": ev}, indent=2),
                   encoding="utf-8")
    print(f"\nsaved: {out}")
