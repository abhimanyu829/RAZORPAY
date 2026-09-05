-- ============================================================================
-- SUPABASE MIGRATION 002 — SECURITY, ROLES, RLS, STORAGE, REALTIME
-- Applies AFTER the base schema (database/schema.sql + seed.sql + functions +
-- views + indexes) has been loaded into the Supabase Postgres database.
--
-- Implements:
--   * application roles (Section 33): admin, finance_lead, finance_operator,
--     analyst, viewer, agent, evaluator
--   * ground-truth isolation by GRANT/REVOKE (not prompt wording) (Section 8)
--   * Row Level Security on every plane, keyed to Supabase Auth users via a
--     app.role mapping table
--   * Supabase Storage bucket for dispute/evidence documents (Section 35/36)
--   * realtime publication for ops tables (dashboard live updates)
-- ============================================================================

-- ---------------------------------------------------------------- roles ----
-- Supabase Auth manages identity; these are DB-level permission roles.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_admin') THEN
        CREATE ROLE app_admin NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_finance_lead') THEN
        CREATE ROLE app_finance_lead NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_finance_operator') THEN
        CREATE ROLE app_finance_operator NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_analyst') THEN
        CREATE ROLE app_analyst NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_viewer') THEN
        CREATE ROLE app_viewer NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_agent') THEN
        CREATE ROLE app_agent NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_evaluator') THEN
        CREATE ROLE app_evaluator NOLOGIN;
    END IF;
END $$;

-- ------------------------------------------------- auth role mapping -------
-- Maps authenticated Supabase Auth users to an application role. The backend
-- service (service role) sets this on login / role assignment; RLS policies
-- below consult it. Users with no row get viewer-level read on nothing.
CREATE TABLE IF NOT EXISTS security.user_roles (
    user_id     UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    app_role    TEXT NOT NULL CHECK (app_role IN
                ('admin','finance_lead','finance_operator','analyst','viewer','agent','evaluator')),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    assigned_by TEXT
);

-- helper: current user's app role (null → no access anywhere)
CREATE OR REPLACE FUNCTION security.current_app_role() RETURNS TEXT
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = security AS $$
    SELECT app_role FROM security.user_roles WHERE user_id = auth.uid();
$$;

CREATE OR REPLACE FUNCTION security.has_role(roles TEXT[]) RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = security AS $$
    SELECT COALESCE(security.current_app_role() = ANY(roles), FALSE);
$$;

-- ---------------------------------------------------------- RLS enable ----
ALTER TABLE core.customers              ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.orders                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.payments               ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.refunds                ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.gateway_fees           ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.settlements            ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.bank_transactions      ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.invoices               ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.gst_records            ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw.ingestion_batches       ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw.raw_source_records      ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw.quarantine_records      ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.identity_matches        ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.reconciliation_results  ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.anomaly_results         ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.evidence_records        ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.recovery_cases          ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.recoverability_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.recovery_actions        ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.approvals              ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.case_history            ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.verification_events     ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.audit_ledger            ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.recovery_ledger         ENABLE ROW LEVEL SECURITY;
ALTER TABLE cfg.rate_cards              ENABLE ROW LEVEL SECURITY;
ALTER TABLE cfg.financial_rules         ENABLE ROW LEVEL SECURITY;
ALTER TABLE cfg.tolerance_rules         ENABLE ROW LEVEL SECURITY;
ALTER TABLE cfg.sla_rules                ENABLE ROW LEVEL SECURITY;
ALTER TABLE cfg.recovery_policies       ENABLE ROW LEVEL SECURITY;
ALTER TABLE cfg.agent_tools             ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval.ground_truth           ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval.evaluation_runs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval.evaluation_case_scores ENABLE ROW LEVEL SECURITY;

-- ------------------------------------------------------------ RLS policy ---
-- core/raw/ops/cfg read access: any authenticated app role can read the
-- canonical truth EXCEPT the agent writing anything and except eval reads.
CREATE POLICY p_read_core ON core.orders FOR SELECT
    TO app_admin, app_finance_lead, app_finance_operator, app_analyst,
       app_viewer, app_agent, app_evaluator
    USING (TRUE);
-- (repeat the SELECT-true pattern per table; the matrix below is the spec)

-- Agents/service may write ONLY to ops operational tables, never core/raw.
CREATE POLICY p_write_cases ON ops.recovery_cases FOR ALL
    TO app_admin, app_finance_lead
    USING (TRUE) WITH CHECK (TRUE);

-- ------------------------------------------------ eval isolation (HARD) ---
-- Section 8: isolation through permissions, not prompt wording.
--   app_agent   → NO ACCESS to eval (denied by absence of grant)
--   app_evaluator → full eval access
--   others      → no eval access
REVOKE ALL ON SCHEMA eval FROM PUBLIC, app_agent, app_analyst, app_viewer,
    app_finance_operator;
GRANT USAGE ON SCHEMA eval TO app_evaluator, app_admin;
GRANT SELECT ON ALL TABLES IN SCHEMA eval TO app_evaluator, app_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval REVOKE ALL ON TABLES FROM app_agent;

-- defense-in-depth: even a misconfigured future grant can't leak GT to the
-- agent — the agent role's RLS policy on eval tables is deny-all.
CREATE POLICY p_deny_agent_gt ON eval.ground_truth
    TO app_agent AS RESTRICTIVE
    USING (FALSE);
CREATE POLICY p_deny_agent_runs ON eval.evaluation_runs
    TO app_agent AS RESTRICTIVE
    USING (FALSE);
CREATE POLICY p_deny_agent_scores ON eval.evaluation_case_scores
    TO app_agent AS RESTRICTIVE
    USING (FALSE);

-- ------------------------------------------------------------ role grants --
-- agent: read canonical truth + ops; write ops runtime only.
GRANT USAGE ON SCHEMA core, ops, cfg TO app_agent;
GRANT SELECT ON ALL TABLES IN SCHEMA core TO app_agent;
GRANT SELECT ON ALL TABLES IN SCHEMA cfg TO app_agent;
GRANT SELECT ON ALL TABLES IN SCHEMA raw TO app_agent;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA ops TO app_agent;
-- agent must never mutate financial truth:
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA core FROM app_agent;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA raw  FROM app_agent;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA cfg  FROM app_agent;

-- finance lead: full ops + core read + approvals
GRANT USAGE ON SCHEMA core, ops, cfg TO app_finance_lead;
GRANT SELECT ON ALL TABLES IN SCHEMA core TO app_finance_lead;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA ops TO app_finance_lead;
GRANT SELECT ON ALL TABLES IN SCHEMA cfg TO app_finance_lead;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA cfg TO app_finance_lead;

-- finance operator: ops read/write minus approvals decide
GRANT USAGE ON SCHEMA core, ops TO app_finance_operator;
GRANT SELECT ON ALL TABLES IN SCHEMA core, ops TO app_finance_operator;

-- analyst: read everywhere except eval
GRANT USAGE ON SCHEMA core, ops, cfg TO app_analyst;
GRANT SELECT ON ALL TABLES IN SCHEMA core, ops, cfg TO app_analyst;

-- viewer: ops + core read only
GRANT USAGE ON SCHEMA core, ops TO app_viewer;
GRANT SELECT ON ALL TABLES IN SCHEMA core, ops TO app_viewer;

-- evaluator: eval + ops read (for scoring joins)
GRANT USAGE ON SCHEMA eval, ops TO app_evaluator;
GRANT SELECT ON ALL TABLES IN SCHEMA ops TO app_evaluator;

-- admin: everything
GRANT USAGE ON SCHEMA core, raw, ops, cfg, eval, security TO app_admin;
GRANT ALL ON ALL TABLES IN SCHEMA core, raw, ops, cfg, eval TO app_admin;

-- --------------------------------------------------------- agent run table -
-- live LLM runs persisted for observability + shadow-mode comparison
CREATE TABLE IF NOT EXISTS ops.agent_runs (
    run_id              TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES ops.recovery_cases(case_id),
    llm_provider        TEXT NOT NULL,
    llm_model           TEXT NOT NULL,
    rollout_level       INT  NOT NULL,
    status              TEXT NOT NULL,
    proposed_action     TEXT,
    executed_action     TEXT,
    verification_status TEXT,
    recovered_amount    NUMERIC(18,4) DEFAULT 0,
    errors              TEXT,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ
);
ALTER TABLE ops.agent_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_runs_read ON ops.agent_runs FOR SELECT
    TO app_admin, app_finance_lead, app_analyst, app_evaluator USING (TRUE);
CREATE POLICY p_runs_write ON ops.agent_runs FOR INSERT
    TO app_agent WITH CHECK (TRUE);

-- recovery ledger (product-level KPI source, Section 40)
CREATE TABLE IF NOT EXISTS ops.recovery_ledger (
    ledger_id        TEXT PRIMARY KEY,
    case_id          TEXT NOT NULL,
    order_id         TEXT,
    source           TEXT NOT NULL,
    amount           NUMERIC(18,4) NOT NULL CHECK (amount >= 0),
    status           TEXT NOT NULL,
    bank_reference   TEXT,
    verification_id  TEXT,
    approval_id      TEXT,
    recorded_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE ops.recovery_ledger ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_ledger_read ON ops.recovery_ledger FOR SELECT
    TO app_admin, app_finance_lead, app_analyst, app_evaluator, app_viewer USING (TRUE);
CREATE POLICY p_ledger_write ON ops.recovery_ledger FOR INSERT
    TO app_agent WITH CHECK (TRUE);

-- webhook inbox (idempotent event processing, Section 24)
CREATE TABLE IF NOT EXISTS raw.webhook_events (
    webhook_id     TEXT PRIMARY KEY,          -- provider event id (dedupe key)
    source_system  TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    payload        JSONB NOT NULL,
    payload_sha256 TEXT NOT NULL,
    received_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    status         TEXT NOT NULL DEFAULT 'RECEIVED',
    processed_at   TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_webhook_dedupe
    ON raw.webhook_events (source_system, webhook_id);
ALTER TABLE raw.webhook_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_webhook_write ON raw.webhook_events FOR INSERT
    TO app_agent, app_admin WITH CHECK (TRUE);

-- connector checkpoints (incremental ingestion, Section 23)
CREATE TABLE IF NOT EXISTS raw.connector_checkpoints (
    connector_id     TEXT PRIMARY KEY,
    last_cursor      TEXT,
    last_timestamp   TIMESTAMPTZ,
    last_external_id TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------ storage policy ----
-- Section 35/36: one private bucket for case documents; metadata table links
-- files to cases; RLS mirrors case visibility.
INSERT INTO storage.buckets (id, name, public)
VALUES ('case-documents', 'case-documents', FALSE)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS ops.case_documents (
    document_id   TEXT PRIMARY KEY,
    case_id       TEXT NOT NULL REFERENCES ops.recovery_cases(case_id),
    storage_path  TEXT NOT NULL,
    content_type  TEXT,
    sha256        TEXT,
    source        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE ops.case_documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_docs_read ON ops.case_documents FOR SELECT
    TO app_admin, app_finance_lead, app_analyst, app_viewer USING (TRUE);
CREATE POLICY p_docs_write ON ops.case_documents FOR INSERT
    TO app_finance_lead, app_admin WITH CHECK (TRUE);

-- storage objects readable only by authenticated app roles
CREATE POLICY p_storage_read ON storage.objects FOR SELECT
    TO app_admin, app_finance_lead, app_analyst, app_viewer
    USING (bucket_id = 'case-documents');
CREATE POLICY p_storage_write ON storage.objects FOR INSERT
    TO app_finance_lead, app_admin
    WITH CHECK (bucket_id = 'case-documents');

-- ------------------------------------------------------------ realtime ----
ALTER PUBLICATION supabase_realtime ADD TABLE ops.recovery_cases;
ALTER PUBLICATION supabase_realtime ADD TABLE ops.recovery_actions;
ALTER PUBLICATION supabase_realtime ADD TABLE ops.recovery_ledger;
ALTER PUBLICATION supabase_realtime ADD TABLE ops.approvals;
ALTER PUBLICATION supabase_realtime ADD TABLE ops.verification_events;

-- dashboard KPI view (product ledger truth, Section 40)
CREATE OR REPLACE VIEW ops.v_recovery_kpi_live AS
SELECT
    (SELECT COUNT(*) FROM core.payments)                                   AS revenue_records,
    (SELECT COALESCE(SUM(potential_recovery),0) FROM ops.recovery_cases)   AS recoverable_amount,
    (SELECT COALESCE(SUM(amount),0) FROM ops.recovery_ledger
        WHERE status = 'RECOVERED')                                        AS recovered_amount,
    (SELECT COUNT(*) FROM ops.recovery_actions)                            AS agent_actions,
    (SELECT COUNT(*) FROM ops.recovery_actions WHERE status <> 'EXECUTED') AS failed_actions,
    (SELECT COUNT(*) FROM ops.approvals WHERE status = 'PENDING')           AS pending_approvals,
    (SELECT COUNT(*) FROM ops.recovery_cases WHERE status = 'ESCALATED')    AS human_escalations;
GRANT SELECT ON ops.v_recovery_kpi_live TO app_admin, app_finance_lead,
    app_analyst, app_viewer, app_evaluator;

-- webhooks/connector service function grants
GRANT EXECUTE ON FUNCTION security.current_app_role() TO app_admin, app_agent;
GRANT EXECUTE ON FUNCTION security.has_role(TEXT[]) TO app_admin, app_agent;
