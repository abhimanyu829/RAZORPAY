# Revenue Guard — AI Revenue Leakage Detection, Diagnosis & Autonomous Recovery Agent

Deterministic financial truth first. AI agent second. PostgreSQL as the single
source of truth. Zero LLM arithmetic.

## Quick start

```powershell
# 1. Generate the synthetic financial universe (1000 master transactions)
python generators\master_transaction_generator.py

# 2. Audit internal consistency (must pass)
python evaluation\data_audit.py

# 3. Run the deterministic pipeline: identity → recon → anomaly
python pipeline\engine.py

# 4. Build cases + recoverability + evidence
python pipeline\cases.py

# 5. Run the agent loop: observe→investigate→reason→plan→act→verify, with
#    human gate, verification, and hash-chained audit
python agent\agent_loop.py

# 6. Score against hidden ground truth
python evaluation\evaluate.py
```

Latest scorecard: `data/exports/scorecard.json`
(precision 1.00, effective recall 1.00, category accuracy 0.99, recovery rate 0.83)

## PostgreSQL deployment

```powershell
# create DB then:
psql -d revenue_guard -f database\schema.sql
psql -d revenue_guard -f database\seed.sql
psql -d revenue_guard -f database\functions.sql
psql -d revenue_guard -f database\views.sql
psql -d revenue_guard -f database\indexes.sql
```

Schemas: `raw` (ingestion) · `core` (canonical graph) · `ops` (cases/actions/audit) ·
`cfg` (rate cards, rules, policies, SLAs, tools) · `eval` (ground truth — sealed
from the agent role).

## Layout

| Path | Purpose |
|---|---|
| `generators/` | causal master-transaction generator + anomaly injector (ground truth) |
| `data/raw/` | source-system CSVs (shopify / razorpay / bank / accounting) |
| `data/staging/` | engine outputs: recon results, anomalies, cases, actions, audit |
| `data/ground_truth/` | EVAL-ONLY hidden truth (`true_*` columns) |
| `data/exports/` | scorecards, KPI, case scores |
| `database/` | full PostgreSQL DDL: schema, seed, functions, views, indexes, queries |
| `pipeline/` | deterministic reconciliation / case builder (mirrors SQL functions) |
| `agent/` | bounded agent loop with tool registry + approval gate |
| `evaluation/` | data audit + scoring vs ground truth |

## Core principle

EXPECTED ≠ ACTUAL is a **variance**, not leakage. The rule engine classifies
LEGITIMATE (tolerance) / TIMING (window open) / ADJUSTMENT (documented) /
LEAKAGE (unexplained past deadline). Only LEAKAGE opens a case. The LLM never
computes money — it investigates, plans, drafts, and escalates within policy.
