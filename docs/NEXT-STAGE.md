# Revenue Guard — Next-Stage Build (Phases 8.5 → 16)

This stage continues the validated deterministic foundation (see `docs/00-ARCHITECTURE.md`
and the Phase 1–8 pipeline) into a live, bounded, auditable AI recovery agent with a
FastAPI backend, Supabase migration path, connectors, control-center UI, and full test suite.

**Nothing from the foundation was redesigned.** The REASON/PLAN steps of the existing
skeleton loop were replaced with live LLM calls behind the same input/output contract.

## What was built in this stage

| Phase | Deliverable | Where | Verified |
|---|---|---|---|
| 8.5 | Live LLM REASON+PLAN (provider abstraction: simulated + OpenAI-compatible) with strict structured-output validation and bounded retry | `backend/app/agent/llm_client.py` | test suite §1 |
| 8.5 | Agent-safe case payload (allowlist construction — GT physically absent) | `backend/app/agent/prompts.py` | test suite §7 |
| 8.5 | Policy engine: allowed-actions, L0–L4 risk, approval gates, one-primary-action, exposure cap, injection scrubbing | `backend/app/agent/policies.py` | test suite §3, §8 |
| 8.5 | Live agent runtime: OBSERVE→INVESTIGATE→LLM→POLICY→APPROVAL→TOOL→VERIFY→STOP, hash-chained audit per run | `backend/app/agent/runtime.py` | §39 demo + E2E |
| 9 | Tool registry: 30 tools, full 14-field contracts, idempotency (`case_id:action`), rollout gating | `backend/app/tools/` | test suite §2, §5 |
| 9 | Recovery simulator: success/partial/failure/timeout/duplicate/none/already_resolved | `backend/app/tools/simulator.py` | test suite §9 |
| 9 | §39 hero case: ₹10,000 → fee ₹200 + GST ₹36 → expected ₹9,764 / actual ₹9,514 → **₹250 verified recovery** through the entire loop | `backend/app/services/hero_case.py` | all 7 scenarios |
| Supabase | Migration 002: 7 app roles, RLS on every plane, deny-all agent policies on `eval`, storage bucket + document metadata, realtime, live KPI view | `supabase/migrations/002_security_rls_storage.sql` | SQL review |
| Supabase | Data loader: 17,578 rows → single transactional SQL | `backend/scripts/load_supabase.py` → `supabase/generated/load_data.sql` | generated |
| 10 | Connector framework: authenticate/health/fetch/normalize/map/emit_raw/checkpoint, incremental cursors, dedupe, quarantine | `backend/app/connectors/base.py` | test suite §10 |
| 10 | Bank CSV + Accounting CSV connectors (runnable offline) | `backend/app/connectors/{bank,accounting}_csv.py` | synced 20+15 rows, dedupe verified |
| 10 | Razorpay + Shopify sandbox clients (paise→rupee, ID bridging, graceful idle without creds) | `backend/app/connectors/{razorpay,shopify}.py` | health checks |
| 10 | Webhook processor: HMAC signatures, raw-first persistence, exact-once dedupe, affected-transaction routing | `backend/app/connectors/webhooks.py` | test suite §6 |
| 12 | FastAPI backend: 20+ endpoints (dashboard, cases, money-flow, plan/investigate/execute, approvals, connectors, webhooks, eval) with API-key→role authorization | `backend/app/main.py` | live smoke test |
| 12 | Service layer + repository (CSV today / Supabase Postgres via `REVENUEGUARD_DATABASE_URL`) | `backend/app/services/` | live |
| 13 | Control-center dashboard (KPIs, case list, case timeline, plan/execute) | `frontend/index.html` | API preflight 7/7 |
| 14 | Full E2E: 150 cases → 96 gated disputes → ₹21,664 verified recovery, 1,685 audit entries (0 broken links) | `backend/scripts/e2e_run.py` → `data/exports/e2e_run.json` | below |
| 15 | Test suite 67/67 + load test (202 req/s plan path, p95 6ms) | `backend/app/tests/run_tests.py` | below |
| Shadow | Rollout level 4 records proposals with zero side effects | runtime + policies | test suite §11 |

## End-to-end results (same hidden ground truth as the foundation run)

```
Full population:  150 cases · 150 completed · 0 policy violations · 0 LLM failures
Disputes:         96 executed (all approval-gated) · 47 RECOVERY_VERIFIED · 23 partial
Recovery ledger:  ₹21,663.83 — every rupee backed by a verification event
Audit chain:      1,685 entries, 0 broken hash links
Evaluation:       precision 1.00 · category accuracy 0.9866 · amount |Δ| ₹0.67
Load:             plan path 202 rps, p95 6ms
```

Recovery rate (49.5%) is measured against actually-observed recovery in this run —
the old 83.3% assumed simulated full recovery; the live loop only counts money the
verification service saw arrive. Both share the same GT.

## Run it

```powershell
# 1. foundation (regression): generators → pipeline → cases
python generators\master_transaction_generator.py
python pipeline\engine.py ; python pipeline\cases.py

# 2. test suite (67 checks)
cd backend ; python -m app.tests.run_tests

# 3. §39 hero demo (any scenario)
python -m app.services.hero_case success

# 4. API server + frontend control center
python -m uvicorn app.main:app --port 8010        # API (X-API-Key: rg-admin-key)
python ..\backend\scripts\serve_frontend.py        # UI at http://127.0.0.1:8020

# 5. full E2E population run + GT evaluation + load test
python scripts\e2e_run.py

# 6. Supabase load (when a project exists)
psql "$SUPABASE_DB_URL" -f database\schema.sql -f database\seed.sql \
  -f database\functions.sql -f database\views.sql -f database\indexes.sql \
  -f supabase\migrations\002_security_rls_storage.sql \
  -f supabase\generated\load_data.sql
# or: python scripts\load_supabase.py --dsn "$SUPABASE_DB_URL"
```

## Live LLM provider

`REVENUEGUARD_LLM_PROVIDER=simulated` (default, deterministic baseline) or
`openai_compat` with `REVENUEGUARD_LLM_BASE_URL` + `REVENUEGUARD_LLM_API_KEY` +
`REVENUEGUARD_LLM_MODEL`. Any OpenAI-chat-compatible endpoint works (OpenAI, Azure,
vLLM, llama.cpp server). Output must pass `validate_agent_plan` regardless of provider —
malformed output is rejected, logged, retried bounded, then escalated to a human.

## Rollout levels (Section 48)

`REVENUEGUARD_ROLLOUT_LEVEL`: 1 synthetic · 2 sandbox connectors · 3 live read-only ·
4 shadow (proposal-only, proven zero side effects) · 5 approved recovery execution ·
6 limited autonomy · 7 production bounded autonomy. Side-effecting tools refuse to
run below level 5 — verified in the test suite.
