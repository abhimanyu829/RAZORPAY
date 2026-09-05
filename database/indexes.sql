-- ============================================================================
-- indexes.sql — performance indexes (beyond PK/FK inline indexes in schema.sql)
-- Load after views.sql:  psql -d revenue_guard -f database/indexes.sql
-- ============================================================================

-- Reconciliation scanning: match by entity-pair across a run
CREATE INDEX IF NOT EXISTS idx_rcn_pair ON ops.reconciliation_results (left_entity, right_entity, left_record_id);
-- Hot case worklist: status + priority + deadline
CREATE INDEX IF NOT EXISTS idx_case_worklist ON ops.recovery_cases (status, priority DESC, deadline_at);
-- Case history timeline pagination
CREATE INDEX IF NOT EXISTS idx_ch_case_time ON ops.case_history (case_id, event_at DESC);
-- Audit chain verification
CREATE INDEX IF NOT EXISTS idx_aud_chain ON ops.audit_ledger (case_id, created_at DESC);
-- Evidence lookup by kind (policy requires_evidence checks)
CREATE INDEX IF NOT EXISTS idx_evid_kind ON ops.evidence_records (evidence_kind);
-- Bank UTR partial: only unmatched bank lines need re-scanning
CREATE INDEX IF NOT EXISTS idx_bank_unmatched_utr ON core.bank_transactions (utr) WHERE matched_settlement_id IS NULL;
-- Settlements pending verification
CREATE INDEX IF NOT EXISTS idx_set_pending ON core.settlements (status) WHERE status IN ('PENDING','IN_PROGRESS');
-- Payments captured recently (incremental recon windows)
CREATE INDEX IF NOT EXISTS idx_pay_recent_capture ON core.payments (captured_at DESC);
-- GT join for evaluator
CREATE INDEX IF NOT EXISTS idx_eval_gt_txn ON eval.ground_truth (txn_id);
-- Utility: canonical id → numeric suffix extractor for ordering
CREATE OR REPLACE FUNCTION core.fn_id_seq(TEXT) RETURNS BIGINT
LANGUAGE sql IMMUTABLE AS 'SELECT split_part($1, ''-'', 2)::BIGINT';

-- Security: the agent runtime role must NOT access eval schema.
-- Run once as superuser:
--   CREATE ROLE agent_ro LOGIN;
--   GRANT USAGE ON SCHEMA raw, core, ops, cfg TO agent_ro;
--   GRANT SELECT ON ALL TABLES IN SCHEMA raw, core, ops, cfg TO agent_ro;
--   GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA cfg TO agent_ro;
--   REVOKE ALL ON SCHEMA eval FROM agent_ro;
--   REVOKE ALL ON ALL TABLES IN SCHEMA eval FROM agent_ro;
