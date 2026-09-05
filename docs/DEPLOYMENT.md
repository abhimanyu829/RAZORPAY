# Revenue Guard — Deployment (Phase 16)

## Environment separation (Section 55)

| | development | staging | production |
|---|---|---|---|
| Data | synthetic CSV/seed-42 universe | synthetic + sandbox connector data | real merchants (migrated via Supabase load) |
| Connectors | offline CSV connectors | Razorpay test mode / Shopify dev store | Razorpay live (read-only first) |
| Credentials | dev demo keys (`rg-*-key`) | test keys via env | real secrets via secret manager |
| LLM | `simulated` provider | real model, strict validation | real model, strict validation |
| Rollout level | 5 (testing recovery) | 3–4 (read-only / shadow) | **starts at 3, never above 5 without explicit approval** |
| Database | CSV repository | Supabase staging project | Supabase production project |

Credentials never cross environments. `REVENUEGUARD_ENV` (`dev|staging|prod`)
selects `.env.{dev,staging,prod}` — see `deploy/env/`.

## Deployment architecture (Section 62)

```
USERS → webui (static dist, CDN or static host)
          ↓ /api/*
       FastAPI (uvicorn, ≥2 workers)
          ↓
   services / agent / connectors
          ↓
   Supabase PostgreSQL (raw core ops cfg eval) + Storage (case-documents)
```

## First production deployment — ordered procedure

1. **Database migrations** (never manual schema edits):
   ```powershell
   psql "$SUPABASE_DB_URL" -f database\schema.sql
   psql "$SUPABASE_DB_URL" -f database\seed.sql
   psql "$SUPABASE_DB_URL" -f database\functions.sql
   psql "$SUPABASE_DB_URL" -f database\views.sql
   psql "$SUPABASE_DB_URL" -f database\indexes.sql
   psql "$SUPABASE_DB_URL" -f supabase\migrations\002_security_rls_storage.sql
   # then load data (staging: synthetic; production: real connector backfill)
   psql "$SUPABASE_DB_URL" -f supabase\generated\load_data.sql
   ```
2. **Secrets** — set in the platform secret manager, never in git/images/logs:
   `SUPABASE_DB_URL`, `REVENUEGUARD_DATABASE_URL`, `RAZORPAY_KEY_ID/SECRET`,
   `SHOPIFY_*`, `REVENUEGUARD_LLM_API_KEY/BASE_URL/MODEL`,
   `REVENUEGUARD_WEBHOOK_SECRET_RAZORPAY/SHOPIFY`, `REVENUEGUARD_ROLLOUT_LEVEL`.
3. **Backend**: `docker compose up -d api` (image builds offline-safe).
4. **Frontend**: `cd webui && npm run build` → serve `dist/` behind the same
   domain (or set `VITE_API_URL` and deploy the static bundle to any CDN).
5. **Webhooks**: point Razorpay/Shopify webhook URLs at
   `https://<host>/api/v1/webhooks/{razorpay|shopify}` with the real secrets.
6. **Verification**: run `python scripts/deploy_check.py` (Section 63 gates).

## Production tool gating (Section 58)

The rollout ladder is enforced in code — the agent physically cannot
side-effect below level 5:

```
L3 READ-ONLY  → L4 SHADOW (proposals only, zero side effects — tested)
              → L5 HUMAN-APPROVED actions (current gate)
              → L6+ limited autonomy only after sustained verified recovery
```

Deploy production at `REVENUEGUARD_ROLLOUT_LEVEL=3`. Raise to 4 (shadow) after
a week of clean audit. Raise to 5 only with finance sign-off. **Never deploy
above 5 initially.**

## Database protection (Section 59)

Agent DB role: SELECT on ops views it needs; INSERT on ops.recovery_actions /
ops.agent_runs / ops.audit_ledger via service functions only; **no** UPDATE/
DELETE on financial tables; **no** access to eval.* (REVOKE + deny-all RLS in
migration 002). Finance roles: controlled financial permissions. Admin:
infrastructure/configuration. Evaluator: eval-only.

## Backups & recovery (Section 60)

- Supabase automatic daily backups + PITR (7–14 day window on paid tiers).
- `RPO`: 24h (daily backup) or minutes (PITR) — set by your Supabase plan.
- `RTO`: restore project → re-run migrations 001–002 → replay
  `load_data.sql` for reference data → restart api containers. Target < 2h.
- Migration rollback: 002 is additive (roles/policies/tables) — rollback by
  reverting the file in a new migration; never edit applied migrations.
- Audit preservation: audit_ledger is append-only + hash-chained; include
  `data/runtime/*.csv` (dev) / `ops.audit_ledger` (prod) in backup scope.

## Monitoring & alerts (Section 61)

`deploy/monitoring/alerts.json` defines the alert rules; wire into your
platform (Grafana/PagerDuty/Sentry equivalents):

| Alert | Condition |
|---|---|
| API health | /health non-200 for 2 min |
| High error rate | 5xx > 1% over 5 min |
| Connector outage | any connector unhealthy > 15 min |
| Duplicate action | any second CREATE_DISPUTE per case |
| Verification backlog | IN_PROGRESS verifications > 20 for 1h |
| Audit chain failure | any broken prev_hash link (validator: `scripts/validate_audit_chain.py`) |
| Authorization anomaly | 403 rate > 5/min |
| Unexpected recovery | ledger entry without verification event |
| LLM latency | p95 plan latency > 10s |
| Approval backlog | PENDING approvals > 10 for 4h |

## Failure recovery (Section 51)

All financial truth is in the database (or CSV dev plane). The agent holds no
in-memory financial state — every run reads its case from the repo and
appends idempotently (idempotency_key `case_id:ACTION`). On backend/agent/
worker restart, re-running a case continues or safely replays. Tested in the
67-check suite + E2E scenarios 5–7.

## Deployment checklist (Section 63)

Run `python scripts/deploy_check.py --target prod` — it verifies:
environment separation, migrations applied, RLS verified, roles verified,
secrets secured (no secrets in git/bundle — scanned), webhook signatures,
agent permissions restricted, tool gating, approval gates, idempotency,
verification, audit chain, backups configured, monitoring, logging, rate
limits, failure recovery, load tests, security tests, evaluation regression.
