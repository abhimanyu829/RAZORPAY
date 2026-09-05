"""FastAPI APPLICATION — Section 32 API surface.

Run:
    cd backend
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8010

Auth (dev): X-API-Key header → role mapping (settings.api_keys).
Production: Supabase Auth JWT + security.user_roles mapping (002 migration).
The frontend NEVER performs privileged DB mutations directly.
"""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException, Request, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .settings import settings, business_now
from .services.services import (case_service, agent_service,
                                approval_service, recovery_service)
from .connectors.registry import sync as connector_sync, health as connector_health
from .connectors.webhooks import processor as webhook_processor, WebhookError
from .services.repository import repo, _to_float
from .agent.prompts import build_case_payload
from .tools.registry import registry

app = FastAPI(
    title="Revenue Guard — AI Revenue Leakage Recovery API",
    version="1.0.0",
    description="Deterministic financial truth first; bounded AI agent second.",
)


# ------------------------------------------------------------------- auth
ROLE_MATRIX = {
    "admin": {"read", "write", "approve", "run_agent", "sync", "shadow", "eval"},
    "finance_lead": {"read", "write", "approve", "run_agent", "sync"},
    "finance_operator": {"read", "write"},
    "analyst": {"read", "run_agent"},
    "viewer": {"read"},
    "agent": {"read"},
    "evaluator": {"read", "eval"},
}


async def require_capability(request: Request, capability: str) -> str:
    key = request.headers.get("x-api-key", "")
    role = settings.api_keys.get(key)
    if not role or capability not in ROLE_MATRIX.get(role, set()):
        raise HTTPException(403, f"role '{role or 'unknown'}' lacks capability '{capability}'")
    return role


# ------------------------------------------------------------------ models
class ApprovalDecision(BaseModel):
    decision: str                      # approve | reject
    decided_by: str = "finance-lead@example.com"
    note: str = ""


class ShadowCompare(BaseModel):
    human_action: str


class WebhookIn(BaseModel):
    body: str


# --------------------------------------------------------------- dashboard
@app.get("/api/v1/dashboard/summary")
async def dashboard_summary(request: Request):
    await require_capability(request, "read")
    kpis = recovery_service.kpis()
    health = connector_health()
    return {"kpis": kpis,
            "connectors": health,
            "business_now": business_now().isoformat(),
            "rollout_level": settings.rollout_level,
            "llm": {"provider": settings.llm_provider, "model": settings.llm_model}}


@app.get("/api/v1/recovery/kpis")
async def recovery_kpis(request: Request):
    await require_capability(request, "read")
    return recovery_service.kpis()


@app.get("/api/v1/recovery/ledger")
async def recovery_ledger(request: Request, limit: int = Query(100, le=1000)):
    await require_capability(request, "read")
    return {"ledger": recovery_service.ledger(limit=limit)}


# ------------------------------------------------------------ transactions
@app.get("/api/v1/orders/{order_id}")
async def get_order(order_id: str, request: Request):
    await require_capability(request, "read")
    o = repo.get_order(order_id)
    if not o:
        raise HTTPException(404, f"order {order_id} not found")
    return {"order": o}


@app.get("/api/v1/orders/{order_id}/money-flow")
async def money_flow(order_id: str, request: Request):
    await require_capability(request, "read")
    flow = case_service.money_flow(order_id)
    if not flow:
        raise HTTPException(404, f"order {order_id} not found")
    return flow


@app.get("/api/v1/transactions/{txn_id}/trace")
async def txn_trace(txn_id: str, request: Request):
    await require_capability(request, "read")
    import subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    out = subprocess.run(
        [sys.executable, str(root / "evaluation" / "show_trace.py"), txn_id],
        capture_output=True, text=True, timeout=60)
    return {"trace": out.stdout}


# ------------------------------------------------------------------ cases
@app.get("/api/v1/cases")
async def list_cases(request: Request, status: str | None = None,
                     category: str | None = None, limit: int = Query(100, le=500)):
    await require_capability(request, "read")
    return {"cases": case_service.list_cases(status=status, category=category,
                                            limit=limit)}


@app.get("/api/v1/cases/{case_id}")
async def get_case(case_id: str, request: Request):
    await require_capability(request, "read")
    c = case_service.get_case(case_id)
    if not c:
        raise HTTPException(404, f"case {case_id} not found")
    return c


@app.get("/api/v1/cases/{case_id}/timeline")
async def case_timeline(case_id: str, request: Request):
    await require_capability(request, "read")
    t = case_service.timeline(case_id)
    if not t:
        raise HTTPException(404, f"case {case_id} not found")
    return t


@app.get("/api/v1/cases/{case_id}/evidence")
async def case_evidence(case_id: str, request: Request):
    await require_capability(request, "read")
    c = repo.get_case(case_id)
    if not c:
        raise HTTPException(404)
    return {"evidence": repo.evidence_for_case(case_id)}


@app.get("/api/v1/cases/{case_id}/recovery")
async def case_recovery(case_id: str, request: Request):
    await require_capability(request, "read")
    c = repo.get_case(case_id)
    if not c:
        raise HTTPException(404)
    return {"actions": repo.actions_for_case(case_id),
            "verifications": repo.verifications_for_case(case_id),
            "approvals": repo.approvals_for_case(case_id),
            "ledger": [l for l in repo.read("recovery_ledger")
                      if l.get("case_id") == case_id]}


# ------------------------------------------------------------------ agent
@app.post("/api/v1/cases/{case_id}/investigate")
async def investigate(case_id: str, request: Request):
    """Observe + investigate only — no LLM plan, no action."""
    await require_capability(request, "run_agent")
    c = repo.get_case(case_id)
    if not c:
        raise HTTPException(404)
    payload = build_case_payload(
        c, repo.evidence_for_case(case_id),
        recoverability=repo.read_one("recoverability_assessments", "case_id", case_id),
        case_history=repo.history_for_case(case_id))
    payload.pop("_messages", None)
    return {"case_id": case_id, "agent_safe_payload": payload,
            "isolation": "ground-truth columns physically absent (allowlist build)"}


@app.post("/api/v1/cases/{case_id}/plan")
async def plan_case(case_id: str, request: Request):
    """Full LLM reason+plan WITHOUT executing (proposal only)."""
    await require_capability(request, "run_agent")
    from .agent.llm_client import llm
    from .agent.prompts import build_messages
    c = repo.get_case(case_id)
    if not c:
        raise HTTPException(404)
    payload = build_case_payload(
        c, repo.evidence_for_case(case_id),
        recoverability=repo.read_one("recoverability_assessments", "case_id", case_id),
        case_history=repo.history_for_case(case_id))
    payload["_messages"] = build_messages(payload)
    plan = llm.reason_and_plan(payload)
    return {"case_id": case_id, "llm_plan": plan}


@app.post("/api/v1/cases/{case_id}/execute")
async def execute_case(case_id: str, request: Request, scenario: str | None = None):
    """Full loop: LLM plan → policy → approval → tool → verify → audit."""
    await require_capability(request, "run_agent")
    try:
        res = agent_service.run_case(case_id, scenario=scenario)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"run_id": res.run_id, "case_id": res.case_id, "status": res.status,
            "proposed_action": res.proposed_action,
            "executed_action": res.executed_action,
            "action_id": res.action_id,
            "verification_status": res.verification_status,
            "recovered_amount": res.recovered_amount,
            "policy_decision": res.policy_decision,
            "llm_diagnosis": res.llm_plan.get("diagnosis", {}) if res.llm_plan else {},
            "errors": res.errors, "steps": res.steps,
            "tool_calls": res.tool_calls, "duration_ms": res.duration_ms}


@app.get("/api/v1/agent/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    await require_capability(request, "read")
    r = agent_service.get_run(run_id)
    if not r:
        raise HTTPException(404)
    return r


@app.get("/api/v1/agent/runs")
async def list_runs(request: Request, limit: int = Query(50, le=200)):
    await require_capability(request, "read")
    return {"runs": agent_service.list_runs(limit=limit)}


@app.post("/api/v1/cases/{case_id}/shadow-compare")
async def shadow_compare(case_id: str, request: Request, body: ShadowCompare):
    await require_capability(request, "shadow")
    return agent_service.shadow_compare(case_id, body.human_action)


@app.get("/api/v1/agent/tools")
async def agent_tools(request: Request):
    await require_capability(request, "read")
    return {"tools": registry.all_contracts()}


# -------------------------------------------------------------- approvals
@app.get("/api/v1/approvals")
async def list_approvals(request: Request, status: str | None = None):
    await require_capability(request, "read")
    return {"approvals": approval_service.list(status=status)}


@app.post("/api/v1/approvals/{approval_id}/decide")
async def decide_approval(approval_id: str, body: ApprovalDecision, request: Request):
    await require_capability(request, "approve")
    a = approval_service.decide(approval_id, body.decision,
                               body.decided_by, body.note)
    if not a:
        raise HTTPException(404)
    return a


# -------------------------------------------------------------- connectors
@app.post("/api/v1/connectors/{connector_id}/sync")
async def sync_connector(connector_id: str, request: Request,
                         limit: int | None = Query(None, le=1000)):
    await require_capability(request, "sync")
    try:
        result = connector_sync(connector_id, limit=limit)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"connector_id": connector_id, "result": result}


@app.get("/api/v1/connectors/health")
async def connectors_health(request: Request):
    await require_capability(request, "read")
    return connector_health()


@app.post("/api/v1/webhooks/{source}")
async def receive_webhook(source: str, request: Request):
    """Signature-validated, idempotent webhook ingestion (Section 24)."""
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        return webhook_processor.process(source, headers, body)
    except WebhookError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# -------------------------------------------------------------- analytics
@app.get("/api/v1/analytics/leakage-by-category")
async def analytics_leakage_by_category(request: Request):
    """Leakage + recovered amounts grouped by case category (dashboard charts)."""
    await require_capability(request, "read")
    from collections import defaultdict
    agg = defaultdict(lambda: {"count": 0, "potential": 0.0, "recovered": 0.0})
    rec = {l.get("case_id"): _to_float(l.get("amount"))
           for l in repo.read("recovery_ledger") if l.get("status") == "RECOVERED"}
    for c in repo.cases():
        a = agg[c.get("category", "UNKNOWN")]
        a["count"] += 1
        a["potential"] += _to_float(c.get("potential_recovery") or c.get("potential_leakage"))
        a["recovered"] += rec.get(c.get("case_id"), 0.0)
    return {"rows": [{"category": k, **{kk: round(vv, 2) if isinstance(vv, float) else vv
                                       for kk, vv in v.items()}} for k, v in agg.items()]}


@app.get("/api/v1/analytics/cases-by-priority")
async def analytics_cases_by_priority(request: Request):
    await require_capability(request, "read")
    from collections import Counter
    counts = Counter(c.get("priority") for c in repo.cases())
    return {"rows": [{"priority": k, "count": v} for k, v in counts.items()]}


@app.get("/api/v1/analytics/action-distribution")
async def analytics_action_distribution(request: Request):
    await require_capability(request, "read")
    from collections import Counter
    counts = Counter(a.get("action_type") for a in repo.read("recovery_actions"))
    return {"rows": [{"action": k, "count": v} for k, v in counts.items()]}


@app.get("/api/v1/analytics/recovery-funnel")
async def analytics_recovery_funnel(request: Request):
    await require_capability(request, "read")
    cases = repo.cases()
    actions = repo.read("recovery_actions")
    verifs = repo.read("verification_events")
    ledger = repo.read("recovery_ledger")
    disputes = [a for a in actions if a.get("action_type") == "CREATE_DISPUTE"]
    return {"funnel": [
        {"stage": "Cases", "count": len(cases)},
        {"stage": "Investigated", "count": len([c for c in cases if c.get("status") != "NEW"])},
        {"stage": "Disputes", "count": len(disputes)},
        {"stage": "Verified", "count": len([v for v in verifs if v.get("status") == "RECOVERY_VERIFIED"])},
        {"stage": "Ledger", "count": len([l for l in ledger if l.get("status") == "RECOVERED"])},
    ]}


@app.get("/api/v1/analytics/approaching-deadline")
async def analytics_approaching_deadline(request: Request):
    """Open cases sorted by nearest deadline (business clock aware)."""
    await require_capability(request, "read")
    from .settings import business_now
    from datetime import datetime
    now = business_now()
    rows = []
    for c in repo.cases():
        dl = c.get("deadline_at", "")
        if not dl or c.get("status") in ("RESOLVED", "CLOSED"):
            continue
        try:
            d = datetime.fromisoformat(dl.replace("Z", "+00:00"))
        except ValueError:
            continue
        rows.append({"case_id": c["case_id"], "order_id": c.get("order_id"),
                     "category": c.get("category"), "deadline_at": dl,
                     "days_left": (d - now).days,
                     "potential_leakage": c.get("potential_leakage"),
                     "priority": c.get("priority")})
    rows.sort(key=lambda r: r["days_left"])
    return {"rows": rows[:20]}


@app.get("/api/v1/search")
async def search(request: Request, q: str = Query("", min_length=2)):
    """Transaction explorer: one query, any ID type → connected money view."""
    await require_capability(request, "read")
    q2 = q.strip()
    result: dict = {"query": q2, "matches": []}
    o = repo.get_order(q2)
    if not o:
        for cand in repo.read("orders"):
            if cand.get("order_number") == q2 or cand.get("gateway_order_id") == q2:
                o = cand
                break
    if o:
        flow = case_service.money_flow(o["order_id"])
        cases = [c for c in repo.cases() if c.get("order_id") == o["order_id"]]
        result["matches"].append({"type": "ORDER", "order": o, "flow": flow, "cases": cases})
    p = repo.get_payment(q2)
    if not p:
        for cand in repo.read("payments"):
            if cand.get("gateway_payment_id") == q2:
                p = cand
                break
    if p and not any(m.get("order", {}).get("order_id") == p.get("order_id")
                     for m in result["matches"]):
        result["matches"].append({"type": "PAYMENT", "payment": p,
                                  "flow": case_service.money_flow(p["order_id"]), "cases": []})
    s = None
    for cand in repo.read("settlements"):
        if cand.get("utr") == q2 or cand.get("settlement_id") == q2:
            s = cand
            break
    if s and not any(m.get("order", {}).get("order_id") == s.get("payment_id")
                     or m.get("order", {}).get("order_id") == s.get("payment_id")
                     for m in result["matches"]):
        p2 = repo.get_payment(s.get("payment_id", ""))
        if p2 and not any(m.get("order", {}).get("order_id") == p2.get("order_id")
                          for m in result["matches"]):
            result["matches"].append({
                "type": "SETTLEMENT", "settlement": s,
                "flow": case_service.money_flow(p2.get("order_id", "")), "cases": []})
    b = repo.bank_by_utr(q2)
    if b:
        result["matches"].append({"type": "BANK", "bank": b})
    for cand in repo.read("invoices"):
        if cand.get("invoice_id") == q2 or cand.get("invoice_number") == q2:
            result["matches"].append({"type": "INVOICE", "invoice": cand,
                                      "flow": case_service.money_flow(cand.get("order_id", "")),
                                      "cases": []})
            break
    for cand in repo.read("customers"):
        if cand.get("customer_id") == q2 or cand.get("email") == q2:
            orders = [x.get("order_id") for x in repo.read("orders")
                      if x.get("customer_id") == q2]
            result["matches"].append({"type": "CUSTOMER", "customer": cand,
                                      "orders": orders})
            break
    c = repo.get_case(q2)
    if c:
        result["matches"].append({"type": "CASE", "case": c,
                                  "flow": case_service.money_flow(c.get("order_id", ""))})
    return result


@app.get("/api/v1/connectors/stats")
async def connector_stats(request: Request):
    await require_capability(request, "read")
    runs = repo.read("connector_runs")
    checkpoints = repo.read("connector_checkpoints")
    webhooks = repo.read("webhook_events")
    out = []
    for cid in ("RAZORPAY_TEST", "SHOPIFY_DEV", "BANK_CSV", "ACCOUNTING_CSV"):
        runs_c = [r for r in runs if r.get("connector_id") == cid]
        ck = next((c2 for c2 in checkpoints if c2.get("connector_id") == cid), None)
        out.append({
            "connector_id": cid,
            "last_run": runs_c[-1] if runs_c else None,
            "checkpoint": ck,
            "records_processed": sum(int(r.get("emitted", 0) or 0) for r in runs_c),
            "duplicates": sum(int(r.get("duplicates", 0) or 0) for r in runs_c),
            "quarantined": sum(int(r.get("quarantined", 0) or 0) for r in runs_c),
            "errors": sum(1 for r in runs_c if r.get("errors")),
            "webhook_events": len([w for w in webhooks
                                   if cid.split("_")[0].startswith("RAZORPAY") and w.get("source_system") == "RAZORPAY"
                                   or cid == "SHOPIFY_DEV" and w.get("source_system") == "SHOPIFY"
                                   or cid == "BANK_CSV" and w.get("source_system") == "BANK"
                                   or cid == "ACCOUNTING_CSV" and w.get("source_system") == "ACCOUNTING"]),
        })
    return {"connectors": out, "webhook_total": len(webhooks)}


@app.get("/api/v1/audit")
async def audit_list(request: Request, case_id: str | None = None,
                     limit: int = Query(200, le=2000)):
    await require_capability(request, "read")
    rows = repo.read("audit_ledger")
    if case_id:
        rows = [r for r in rows if r.get("case_id") == case_id]
    return {"audit": rows[-limit:]}


@app.get("/api/v1/verification/events")
async def verification_events(request: Request, limit: int = Query(200, le=1000)):
    await require_capability(request, "read")
    return {"events": repo.read("verification_events")[-limit:]}


# ------------------------------------------------------------------- eval
@app.get("/api/v1/eval/scorecard")
async def eval_scorecard(request: Request):
    """Evaluator-only: scoring vs hidden ground truth (Section 46)."""
    await require_capability(request, "eval")
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "data" / "exports" / "scorecard.json"
    if not p.exists():
        raise HTTPException(404, "no scorecard generated yet — run evaluation/evaluate.py")
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/health")
async def health():
    return {"status": "ok", "rollout_level": settings.rollout_level,
            "llm_provider": settings.llm_provider}


# ------------------------------------------------------------- static webui
# Serve the built control center (webui/dist) at / so the API port also
# renders the UI. /api/* routes take precedence.
from pathlib import Path as _Path

_WEBUI = _Path(__file__).resolve().parents[2] / "webui" / "dist"
if _WEBUI.exists():
    from fastapi.staticfiles import StaticFiles as _StaticFiles
    # html=True serves index.html at "/" and for unknown non-API paths
    app.mount("/", _StaticFiles(directory=str(_WEBUI), html=True),
              name="webui")
else:  # keep / meaningful even without a build present
    @app.get("/")
    async def root():
        return {"service": "Revenue Guard API",
                "ui": "webui/dist not built — run: cd webui && npm run build",
                "api": "/api/v1/*"}
