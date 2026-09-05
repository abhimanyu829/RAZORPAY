-- ============================================================================
-- views.sql — engine-facing and dashboard-facing views
-- Load after functions.sql:  psql -d revenue_guard -f database/views.sql
-- ============================================================================

-- 1. Full money-flow trace of one order: every financial event in the graph.
CREATE OR REPLACE VIEW core.v_order_money_flow AS
SELECT
  o.order_id, o.order_number, o.customer_id, o.status AS order_status, o.net_amount AS order_net,
  p.payment_id, p.gateway_payment_id, p.status AS payment_status, p.amount AS payment_amount, p.captured_at,
  f.fee_id, f.amount AS fee_amount, f.tax_amount AS fee_tax,
  s.settlement_id, s.gateway_settlement_id, s.utr, s.amount AS settlement_amount, s.settled_at, s.status AS settlement_status,
  b.bank_txn_id, b.amount AS bank_amount, b.value_date AS bank_value_date,
  r.refund_id, r.amount AS refund_amount, r.status AS refund_status, r.processed_at,
  i.invoice_id, i.invoice_number, i.total_amount AS invoice_total,
  g.gst_record_id, g.total_tax AS gst_tax, g.gst_type, g.itc_matched
FROM core.orders o
LEFT JOIN core.payments p ON p.order_id = o.order_id
LEFT JOIN core.gateway_fees f ON f.payment_id = p.payment_id
LEFT JOIN core.settlements s ON s.payment_id = p.payment_id
LEFT JOIN core.bank_transactions b ON b.utr = s.utr AND b.txn_type = 'CREDIT'
LEFT JOIN core.refunds r ON r.payment_id = p.payment_id
LEFT JOIN core.invoices i ON i.order_id = o.order_id
LEFT JOIN core.gst_records g ON g.invoice_id = i.invoice_id;

-- 2. Reconciliation status overview per order.
CREATE OR REPLACE VIEW ops.v_reconciliation_status AS
SELECT
  o.order_id, o.order_number, o.net_amount AS order_net,
  COUNT(DISTINCT p.payment_id) AS payment_count,
  COUNT(DISTINCT s.settlement_id) AS settlement_count,
  COALESCE((SELECT SUM(amount) FROM core.gateway_fees f WHERE f.order_id = o.order_id), 0) AS fees_total,
  COALESCE((SELECT SUM(amount) FROM core.refunds r WHERE r.order_id = o.order_id AND r.status IN ('INITIATED','PROCESSED')), 0) AS refunds_total,
  COALESCE((SELECT SUM(total_tax) FROM core.gst_records g WHERE g.order_id = o.order_id AND g.gst_type = 'INPUT'), 0) AS itc_total,
  EXISTS (SELECT 1 FROM ops.reconciliation_results rr WHERE rr.left_record_id = o.order_id AND rr.status = 'MISMATCH') AS has_mismatch
FROM core.orders o
LEFT JOIN core.payments p ON p.order_id = o.order_id
LEFT JOIN core.settlements s ON s.order_id = o.order_id
GROUP BY o.order_id, o.order_number, o.net_amount;

-- 3. Leakage summary (dashboard).
CREATE OR REPLACE VIEW ops.v_leakage_summary AS
SELECT ar.category, ar.variance_class, COUNT(*) AS findings,
       SUM(ar.detected_amount) AS total_detected,
       ROUND(AVG(ar.detected_amount), 2) AS avg_detected,
       MAX(ar.detected_at) AS last_detected_at
FROM ops.anomaly_results ar
GROUP BY ar.category, ar.variance_class;

-- 4. Case full view: the structured case object the AI agent consumes.
--    Ground-truth columns live in eval schema only; never exposed here.
CREATE OR REPLACE VIEW ops.v_case_full AS
SELECT
  c.case_id, c.category, c.priority, c.status,
  c.order_id, c.payment_id, c.customer_id, o.order_number,
  cust.name AS customer_name, cust.email AS customer_email,
  c.expected_fee, c.expected_tax, c.expected_settlement,
  c.actual_fee, c.actual_tax, c.actual_settlement, c.known_adjustments,
  c.refund_status, c.recon_status, c.potential_leakage, c.confidence,
  c.recoverability_status, c.potential_recovery, c.deadline_at,
  c.allowed_actions, c.approval_required, c.opened_at, c.closed_at,
  (SELECT json_agg(json_build_object('evidence_id', ev.evidence_id, 'kind', ev.evidence_kind, 'description', ev.description))
     FROM ops.evidence_records ev WHERE ev.case_id = c.case_id) AS evidence,
  (SELECT json_agg(json_build_object('event_at', ch.event_at, 'event_type', ch.event_type, 'actor', ch.actor, 'message', ch.message))
     FROM (SELECT * FROM ops.case_history ch2 WHERE ch2.case_id = c.case_id ORDER BY ch2.event_at) ch) AS case_history,
  (SELECT json_agg(json_build_object('action_id', ra.action_id, 'type', ra.action_type, 'status', ra.status, 'amount', ra.amount))
     FROM ops.recovery_actions ra WHERE ra.case_id = c.case_id) AS actions,
  (SELECT json_build_object('status', rca.status, 'recoverable', rca.potentially_recoverable_amount,
                            'confidence', rca.confidence, 'evidence_complete', rca.evidence_complete,
                            'deadline_open', rca.deadline_open, 'recommended_action', rca.recommended_action)
     FROM ops.recoverability_assessments rca WHERE rca.case_id = c.case_id) AS recoverability
FROM ops.recovery_cases c
JOIN core.orders o ON o.order_id = c.order_id
LEFT JOIN core.customers cust ON cust.customer_id = c.customer_id;

-- 5. Case evidence chain (flat).
CREATE OR REPLACE VIEW ops.v_case_evidence AS
SELECT c.case_id, c.category, c.status, ev.evidence_id, ev.evidence_kind,
       ev.source_system, ev.source_reference, ev.description, ev.collected_at, ev.payload_sha256
FROM ops.recovery_cases c
JOIN ops.evidence_records ev ON ev.case_id = c.case_id;

-- 6. Audit timeline per case.
CREATE OR REPLACE VIEW ops.v_audit_timeline AS
SELECT a.audit_id, a.case_id, a.actor, a.event_type, a.tool_called, a.tool_parameters,
       a.tool_result, a.previous_state, a.new_state, a.amount, a.decision,
       a.evidence_ids, a.approval_id, a.correlation_id, a.created_at, a.entry_hash
FROM ops.audit_ledger a;

-- 7. Verification pipeline view.
CREATE OR REPLACE VIEW ops.v_verification_pipeline AS
SELECT v.verification_id, v.action_id, v.case_id, v.status, v.check_type,
       v.expected_ref, v.observed_value, v.checked_at, v.notes,
       ra.action_type, ra.external_ref
FROM ops.verification_events v
JOIN ops.recovery_actions ra ON ra.action_id = v.action_id;

-- 8. Detection KPI per category.
CREATE OR REPLACE VIEW ops.v_detection_kpi AS
SELECT c.category, COUNT(*) AS cases_opened, SUM(c.potential_leakage) AS detected_amount,
       COUNT(*) FILTER (WHERE c.status IN ('RECOVERED','PARTIALLY_RECOVERED')) AS recovered_cases,
       SUM(CASE WHEN c.status IN ('RECOVERED','PARTIALLY_RECOVERED') THEN c.potential_recovery ELSE 0 END) AS recovered_amount,
       COUNT(*) FILTER (WHERE c.status = 'ESCALATED') AS escalated,
       COUNT(*) FILTER (WHERE c.status = 'UNRECOVERABLE') AS unrecoverable
FROM ops.recovery_cases c
GROUP BY c.category;

-- 9. Identity overview: cross-system linkage per order.
CREATE OR REPLACE VIEW ops.v_identity_overview AS
SELECT o.order_id, o.order_number, o.gateway_order_id,
       p.payment_id, p.gateway_payment_id,
       s.settlement_id, s.gateway_settlement_id, s.utr,
       b.bank_txn_id, i.invoice_id, i.invoice_number, g.gst_record_id,
       im.confidence AS identity_confidence, im.match_method, im.status AS identity_status
FROM core.orders o
LEFT JOIN core.payments p ON p.order_id = o.order_id
LEFT JOIN core.settlements s ON s.payment_id = p.payment_id
LEFT JOIN core.bank_transactions b ON b.utr = s.utr
LEFT JOIN core.invoices i ON i.order_id = o.order_id
LEFT JOIN core.gst_records g ON g.invoice_id = i.invoice_id
LEFT JOIN ops.identity_matches im ON im.left_record_id = o.order_id AND im.left_entity = 'core.orders';
