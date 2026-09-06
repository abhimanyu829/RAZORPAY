
```markdown
# Revenue Guard — AI Revenue Leakage Detection, Diagnosis & Autonomous Recovery Agent

Revenue Guard is an end-to-end, AI-native platform designed to detect, diagnose, and autonomously recover lost revenue (fee discrepancies, settlement mismatches, refund economics errors) across multi-leg e-commerce and fintech transaction flows (Shopify, Razorpay, Bank, Accounting).

---

## Core Philosophy: Deterministic Truth First, AI Agent Second

1. **Zero LLM Arithmetic**: LLMs are never allowed to compute financial numbers, rates, or totals. All calculations, fee validation, tax computations, and variances are calculated deterministically by standard financial algorithms.
2. **Variance ≠ Leakage**: `EXPECTED ≠ ACTUAL` is treated as a variance, not immediate leakage. A deterministic rule engine classifies variances into:
   - `LEGITIMATE`: Within defined business tolerances.
   - `TIMING`: Settlement/reconciliation window still open.
   - `ADJUSTMENT`: Documented credit note or reversal.
   - `LEAKAGE`: Unexplained shortfall past deadline $\rightarrow$ triggers **Case Creation**.
3. **Bounded Autonomous Recovery**: The AI Agent investigates cases, evaluates recoverability, generates action plans, drafts disputes, and drives recovery within human-in-the-loop (HITL) approval gates and rollout security levels (L1–L5).

---

##  Tech Stack

| Layer | Technology | Details |
|---|---|---|
| **Backend Framework** | FastAPI (Python 3.13) | Uvicorn ASGI server, Pydantic v2 data models |
| **Frontend UI** | React 19 + TypeScript | Vite 6, TailwindCSS v4, TanStack Query v5, Recharts |
| **Database / Storage** | PostgreSQL / CSV Mode | PostgreSQL 16+ DDL (Schemas: `raw`, `core`, `ops`, `cfg`, `eval`) with zero-config CSV file fallback |
| **Integrations / Connectors** | Razorpay REST API, Shopify Admin API | Direct API sync + Webhook handlers for real-time ledger updates |
| **AI / LLM Engine** | OpenAI-Compatible Client | Supports `simulated` (offline/zero key), OpenAI (`gpt-4o-mini`), Groq, or Gemini |
| **Audit & Trust** | Cryptographic Ledger | Hash-chained immutable audit trail (`audit_ledger.csv`) |

---

```

### Dataset Schema Overview:
* **`data/raw/`**: Source CSVs from Shopify (`orders.csv`, `customers.csv`), Razorpay (`payments.csv`, `gateway_fees.csv`, `settlements.csv`), Bank (`bank_transactions.csv`), and Accounting (`invoices.csv`).
* **`data/staging/`**: Engine outputs — `reconciliation_results.csv`, `anomaly_results.csv`, `recovery_cases.csv`, `evidence_records.csv`, `recoverability_assessments.csv`.
* **`data/runtime/`**: Agent state — `recovery_actions.csv`, `approvals.csv`, `verification_events.csv`, `audit_ledger.csv`, `agent_runs.csv`.
* **`data/ground_truth/`**: EVAL-ONLY sealed truth (`true_leakage`, `true_root_cause`) used solely by the evaluator script.

---

## Quick Start: Running Locally

### 1. Prerequisites
- Python 3.11+
- Node.js 18+

### 2. Environment Setup
Create a `.env` file at the root directory (`C:\Users\Abhimanyu\Desktop\RAZORPAY\.env`):

```env
REVENUEGUARD_ENV=dev
REVENUEGUARD_ROLLOUT_LEVEL=5

# LLM Configuration (simulated = offline test mode without API keys)
REVENUEGUARD_LLM_PROVIDER=simulated
REVENUEGUARD_LLM_BASE_URL=
REVENUEGUARD_LLM_API_KEY=
REVENUEGUARD_LLM_MODEL=gpt-4o-mini

# Database (leave blank for zero-config CSV mode)
REVENUEGUARD_DATABASE_URL=

# Webhook Secrets
REVENUEGUARD_WEBHOOK_SECRET_RAZORPAY=dev-secret-razorpay
REVENUEGUARD_WEBHOOK_SECRET_SHOPIFY=dev-secret-shopify

# Optional Gateway Connectors (leave blank for simulated mode)
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
SHOPIFY_SHOP_URL=
SHOPIFY_ACCESS_TOKEN=
```

### 3. Generate Data & Run Pipeline

```powershell
# Install Python dependencies
pip install -r backend\requirements.txt

# 1. Generate 1,000 synthetic master transactions with injected anomalies
python generators\master_transaction_generator.py

# 2. Audit internal dataset consistency
python evaluation\data_audit.py

# 3. Run deterministic 3-way reconciliation & anomaly detection
python pipeline\engine.py

# 4. Build recovery cases, evidence records, and recoverability assessments
python pipeline\cases.py

# 5. Seed Section 39 Hero Demonstration Case (CASE-9001)
python -c "import sys; sys.path.insert(0,'backend'); sys.path.insert(0,'generators'); from app.services.hero_case import build_hero_universe; build_hero_universe()"
```

### 4. Start the Application

#### Start Backend API (FastAPI on Port 8010):
```powershell
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

#### Start Frontend Web UI (Vite + React on Port 5173):
```powershell
cd webui
npm install
npm run dev
```

Access the Web Dashboard at: **`http://localhost:5173`**

---

##  Repository Structure

```text
RAZORPAY/
├── backend/                  # FastAPI backend server
│   ├── app/
│   │   ├── agent/            # Bounded AI agent loop, tools & prompt builder
│   │   ├── connectors/       # Razorpay, Shopify & Bank connectors + webhooks
│   │   ├── services/         # Repository pattern, Audit trail & Hero Case engine
│   │   ├── main.py           # FastAPI application routes
│   │   └── settings.py       # Centralized env configuration
│   └── requirements.txt      # Backend dependencies
├── webui/                    # React + TypeScript Frontend
│   ├── src/
│   │   ├── pages/            # Dashboard, Cases, Explorer, Pipeline, Audit, Eval pages
│   │   ├── App.tsx           # Main Application Shell
│   │   └── api.ts            # Typed API client
│   ├── vite.config.ts        # Vite configuration + API proxy
│   └── package.json          # Frontend dependencies
├── database/                 # PostgreSQL DDL
│   ├── schema.sql            # Table definitions
│   ├── seed.sql              # Initial configuration seed
│   ├── functions.sql         # SQL reconciliation logic
│   ├── views.sql             # Analytics views
│   └── indexes.sql           # Performance indexes
├── generators/               # Master Causal Transaction & Anomaly Generator
├── pipeline/                 # Python Reconciliation Engine & Case Builder
├── evaluation/               # Audit validator & Ground Truth Evaluator
├── deploy/                   # Deployment environment templates (.env.prod.example)
└── README.md                 # Project documentation
```

---

##  API Endpoints Summary

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Server health check & rollout level status |
| `GET` | `/api/v1/dashboard/summary` | High-level metrics (leakage, recovery rate, cases) |
| `GET` | `/api/v1/cases` | Filterable list of recovery cases |
| `GET` | `/api/v1/cases/{case_id}` | Detailed case inspection + evidence list |
| `POST`| `/api/v1/cases/{case_id}/plan` | Generate AI Agent recovery action plan |
| `POST`| `/api/v1/cases/{case_id}/execute` | Execute recovery action (with policy check) |
| `GET` | `/api/v1/connectors/health` | Live gateway connector health status |
| `GET` | `/api/v1/audit` | Cryptographic hash-chained audit ledger |
| `GET` | `/api/v1/eval/scorecard` | Benchmark scores against ground truth |

---

##  Cloud Deployment Guide

### Backend: Render (Web Service)
1. Create a new **Web Service** on Render pointing to your GitHub repository.
2. Root Directory: `backend`
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Set Environment Variables (`REVENUEGUARD_ENV=prod`, `REVENUEGUARD_ROLLOUT_LEVEL=5`, `REVENUEGUARD_LLM_PROVIDER=simulated`).

### Frontend: Vercel (Static Site)
1. Add `webui/vercel.json` to proxy `/api/*` requests to your live Render backend URL:
   ```json
   {
     "rewrites": [
       {
         "source": "/api/:path*",
         "destination": "https://<YOUR-RENDER-BACKEND-URL>/api/:path*"
       }
     ]
   }
   ```
2. Import project in Vercel. Root Directory: `webui`, Framework: `Vite`. Build command: `npm run build`.

---

##  Evaluation & Benchmark

Run evaluation against hidden ground truth:
```powershell
python evaluation\evaluate.py
```
Outputs precision, recall, category classification accuracy, and recovery rate to `data/exports/scorecard.json`.
```
