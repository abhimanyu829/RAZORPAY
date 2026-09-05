# Revenue Guard — Phases 13–16 Completion (Product Build)

The deterministic foundation and live LLM agent (Phases 1–12, see
`docs/NEXT-STAGE.md`) are now wrapped in a complete product: React control
center, end-to-end integration, release-tested security/reliability, and
deployment prerequisites.

| Phase | Deliverable | Evidence |
|---|---|---|
| 13 | React 19 + TypeScript + Tailwind v4 + React Query control center — 12 sections: Command Center (KPIs + charts), Recovery Cases (filters/sorts), Case Investigation (evidence chain, expected-vs-actual bars, AI panel, agent timeline, action/approval/verification panels), Transaction Explorer, Recovery Pipeline, Approvals, Agent Activity, Connectors, Verification, Audit Trail, Evaluation/Admin, Settings | `webui/` — build verified, all 19 API contracts checked |
| 14 | 8 end-to-end scenarios through the **live API**: healthy txn (no FP), settlement leakage (hero ₹250 recovered via execute → ledger → dashboard), timing (LEGITIMATE never leaks), GST review (FINANCE_REVIEW only, no tax tool), duplicate action (idempotent), verification failure (no ledger entry), LLM failure (no unsafe action), policy attack (denied + audited) | `backend/scripts/e2e_scenarios.py` — **37/37 pass**, results in `data/exports/e2e_scenarios.json` |
| 15 | Stress + security + evaluation release suite: API load (117 rps, p50 98ms, p95 118ms, p99 121ms, 0 errors), concurrent KPI reads, webhook burst (exactly-once: 1 processed + 19 dupes), 8 agent runs (no duplicate disputes), authz matrix (403s), SQLi/path traversal inert, GT isolation, prompt injection scrubbing, agent safety attacks, secret scan, evaluation regression (precision 1.00 / category 0.9866 / amount Δ₹0.67 vs same GT), recovery accounting (verified ≤ submitted ≤ approved ≤ potential; 0 unbacked ledger entries), audit chain (0 broken), **8 release gates all green** | `backend/scripts/stress_security_eval.py` — **53/53 pass**, `data/exports/phase15_release_suite.json` |
| 16 | Deployment prerequisites: env separation (dev/staging/prod templates), Dockerfile + compose (non-root, healthcheck), monitoring alerts (10 rules + 2 cron jobs), audit-chain validator cron, deploy checklist script | `deploy/`, `docs/DEPLOYMENT.md` — `deploy_check.py --target prod` → **27/27, PROD GATE: GO** |

## Real bugs found and fixed by integration testing

Phase 14/15 integration testing caught three genuine defects — each fixed
and re-verified:

1. **Frontend/backend contract drift** — case detail returned flat (no
   wrapper), timeline returned `events` (not `timeline`), plan returned
   `llm_plan`. All three fixed in the UI; 19/19 endpoint contracts now
   machine-verified.
2. **`force_scenario` not reaching the dispute chain** — the draft→dispute
   continuation dispatch skipped the simulator force, so scenario-forced
   runs replayed stale outcomes. Fixed in `runtime.py`.
3. **Audit-chain integrity violations** — audit IDs collided across runs
   (`AUD-00001` reused), and chains restarted at GENESIS per run instead of
   extending the case's chain. Fixed: globally-unique run-scoped IDs and
   per-case chain continuation from the last persisted entry_hash.

## Regression status

- Core suite: **67/67**
- E2E scenarios: **37/37**
- Phase 15 release suite: **53/53** (all 8 release gates green)
- Deploy check: **27/27**

## Section 64 final product scenario (via live API)

```
execute:         CREATE_DISPUTE -> RECOVERY_VERIFIED, recovered ₹250 (122ms, 12 tools)
dashboard:       recovered ₹250 rendered in KPIs
case detail:     4 evidence, 2 actions, 1 verification
timeline:        30 events (DRAFT_DISPUTE -> STOP)
ledger:          ₹250 entry backed by verification event
audit:           23 chained entries for the case
control center:  http://127.0.0.1:5173
```

DETECT → PROVE → DIAGNOSE → PRIORITIZE → DECIDE → APPROVE → ACT → VERIFY →
RECOVER → MEASURE — the complete loop, witnessed through the product.

## Run it

```powershell
# API (rollout 5 for full recovery demo)
cd backend ; $env:REVENUEGUARD_ROLLOUT_LEVEL='5' ; python -m uvicorn app.main:app --port 8010

# Control center (build + serve with API proxy)
cd webui ; npm install --ignore-scripts --legacy-peer-deps ; npm run build
node scripts\dev.cjs        # http://127.0.0.1:5173

# Test batteries
cd backend
python -m app.tests.run_tests            # 67 checks
python scripts\e2e_scenarios.py          # 37 checks (API on :8010)
python scripts\stress_security_eval.py  # 53 checks + release gates
python scripts\deploy_check.py --target prod   # 27 checks → GO/NO-GO
python scripts\validate_audit_chain.py   # cron validator
```

Dev roles for the UI role switcher: `rg-admin-key`, `rg-finance-key`,
`rg-analyst-key`, `rg-viewer-key`, `rg-evaluator-key` (backend-enforced).

Deployment procedure, environment separation, gating ladder, backups
(RPO/RTO), and monitoring: **`docs/DEPLOYMENT.md`**.
