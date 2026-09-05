-- ============================================================================
-- queries.sql — reference operational queries (Sections 32, 10 of the brief)
-- Reconciliation, transaction trace, anomaly-case, recoverability, KPI, audit.
-- ============================================================================

-- ============================================================================
-- A. RECONCILIATION QUERIES (deterministic matching)
-- ============================================================================

-- A1. Payment ↔ Order: exact equality within tolerance (PAYMENT_VS_ORDER)
-- One-to-many aware: multiple payments may fund one order.
SELECT o.order_id, o.net_amount,
       SUM(p.amount) AS paid_total, COUNT(*) AS payments,
       o.net_amount - SUM(p.amount) AS variance,
       CASE WHEN abs(o.net_amount - SUM(p.amount)) <= 0.01 THEN 'MATCHED'
            ELSE 'MISMATCH' END AS status
FROM core.orders o
JOIN core.payments p ON p.order_id = o.order_id
WHERE p.status = 'CAPTURED'
GROUP BY o.order_id, o.net_amount
HAVING abs(o.net_amount - SUM(p.amount)) > 0.01;

-- A2. Settlement ↔ Payment: expected settlement from the rule engine vs actual.
SELECT p.payment_id, p.amount,
       exp.expected_fee, exp.expected_tax,
       exp.expected_settlement,
       SUM(s.amount) AS actual_settlement,
       exp.expected_settlement - SUM(s.amount) AS variance,
       CASE WHEN abs(exp.expected_settlement - SUM(s.amount)) <= 2.00 THEN 'MATCHED'
            WHEN SUM(s.amount) = 0 THEN 'UNMATCHED'
            ELSE 'MISMATCH' END AS status
FROM core.payments p
CROSS JOIN LATERAL cfg.fn_expected_settlement(p.payment_id) exp
LEFT JOIN core.settlements s ON s.payment_id = p.payment_id
WHERE p.status = 'CAPTURED'
GROUP BY p.payment_id, p.amount, exp.expected_fee, exp.expected_tax, exp.expected_settlement
HAVING abs(exp.expected_settlement - SUM(s.amount)) > 2.00;

-- A3. Bank ↔ Settlement: via UTR, amount equality.
SELECT s.settlement_id, s.utr, s.amount AS settlement_amount,
       b.amount AS bank_amount, s.amount - b.amount AS variance,
       CASE WHEN abs(s.amount - b.amount) <= 0.01 THEN 'MATCHED'
            ELSE 'MISMATCH' END AS status
FROM core.settlements s
LEFT JOIN core.bank_transactions b ON b.utr = s.utr AND b.txn_type = 'CREDIT'
WHERE s.status = 'PROCESSED';

-- A4. Fee ↔ Rate card: gateway-charged fee vs contractual expected fee.
SELECT p.payment_id, p.method, p.amount,
       rc.pct_rate, exp.expected_fee,
       SUM(f.amount) AS actual_fee,
       SUM(f.amount) - exp.expected_fee AS fee_variance,
       CASE WHEN abs(SUM(f.amount) - exp.expected_fee) <= GREATEST(1.00, exp.expected_fee * 0.005) THEN 'LEGITIMATE'
            ELSE 'FEE_EXCESS' END AS status
FROM core.payments p
JOIN core.gateway_fees f ON f.payment_id = p.payment_id
CROSS JOIN LATERAL cfg.fn_expected_fee(p.payment_id) exp
LEFT JOIN cfg.rate_cards rc ON rc.payment_method = p.method AND rc.valid_from <= p.captured_at::date
GROUP BY p.payment_id, p.method, p.amount, rc.pct_rate, exp.expected_fee
HAVING SUM(f.amount) - exp.expected_fee > GREATEST(1.00, exp.expected_fee * 0.005);

-- A5. Refund ↔ Payment: over-refund and fee-return economics.
SELECT p.payment_id, p.amount,
       SUM(r.amount) AS refunded_total,
       p.amount - SUM(r.amount) AS net_after_refund,
       CASE WHEN SUM(r.amount) > p.amount THEN 'OVER_REFUND'
            ELSE 'OK' END AS status
FROM core.payments p
JOIN core.refunds r ON r.payment_id = p.payment_id AND r.status = 'PROCESSED'
GROUP BY p.payment_id, p.amount
HAVING SUM(r.amount) > p.amount;

-- ============================================================================
-- B. TRANSACTION-TRACE QUERY ("show me everything for this order")
-- ============================================================================
SELECT * FROM core.v_order_money_flow WHERE order_id = 'ORD-1001';

-- B2. Case-level traversal: every reconciliation finding for the order.
SELECT rr.*
FROM ops.reconciliation_results rr
WHERE rr.left_record_id = 'ORD-1001'
   OR rr.right_record_id = 'ORD-1001'
ORDER BY rr.created_at;

-- ============================================================================
-- C. ANOMALY-CASE QUERY (leakage candidates → open cases)
-- ============================================================================
SELECT an.category, an.detected_amount, an.severity, an.explanation,
       an.candidate_root_causes, c.case_id, c.status, c.priority,
       c.recoverability_status, c.potential_recovery
FROM ops.anomaly_results an
LEFT JOIN ops.recovery_cases c ON c.case_id IS NOT NULL AND c.anomaly_id = an.anomaly_id
WHERE an.variance_class = 'LEAKAGE'
ORDER BY an.detected_amount DESC;

-- ============================================================================
-- D. RECOVERABILITY QUERY
-- ============================================================================
SELECT c.case_id, c.category, c.potential_leakage,
       rca.status, rca.potentially_recoverable_amount, rca.confidence,
       rca.evidence_complete, rca.deadline_open, rca.recommended_action
FROM ops.recovery_cases c
JOIN ops.recoverability_assessments rca ON rca.case_id = c.case_id
WHERE rca.status = 'ACTION_READY' AND rca.deadline_open
ORDER BY rca.potentially_recoverable_amount DESC;

-- ============================================================================
-- E. RECOVERY KPI QUERY
-- ============================================================================
SELECT * FROM ops.v_recovery_kpi;
-- Per-category detail:
SELECT * FROM ops.v_detection_kpi;

-- ============================================================================
-- F. AUDIT TIMELINE QUERY (case timeline with tools, approvals, hashes)
-- ============================================================================
SELECT a.created_at, a.actor, a.event_type, a.tool_called, a.previous_state,
       a.new_state, a.amount, a.decision, a.entry_hash
FROM ops.audit_ledger a
WHERE a.case_id = 'CASE-1001'
ORDER BY a.created_at;

-- ============================================================================
-- G. EVALUATION QUERIES (eval schema; agent never sees these)
-- ============================================================================
-- G1. Detection precision/recall per category (join cases to ground truth)
SELECT gt.anomaly_type,
       COUNT(*) AS gt_count,
       COUNT(ecs.case_id) AS detected_count,
       ROUND(COUNT(ecs.case_id)::numeric / NULLIF(COUNT(*),0) * 100, 2) AS recall_pct,
       COUNT(*) FILTER (WHERE ecs.category_correct) AS category_correct,
       ROUND(AVG(abs(ecs.amount_delta)) FILTER (WHERE ecs.detected), 2) AS avg_amount_error
FROM eval.ground_truth gt
LEFT JOIN eval.evaluation_case_scores ecs ON ecs.gt_id = gt.gt_id
WHERE gt.has_anomaly
GROUP BY gt.anomaly_type;

-- G2. False positives: cases opened against healthy transactions
SELECT c.case_id, c.category, c.potential_leakage
FROM ops.recovery_cases c
LEFT JOIN eval.ground_truth gt ON gt.order_id = c.order_id
WHERE COALESCE(gt.has_anomaly, FALSE) = FALSE;

-- G3. Recovery rate vs ground truth
SELECT
  SUM(ecs.recovered_amount) AS recovered,
  SUM(gt.true_recovery_amount) AS true_recoverable,
  ROUND(SUM(ecs.recovered_amount)::numeric / NULLIF(SUM(gt.true_recovery_amount),0) * 100, 2) AS recovery_rate_pct
FROM eval.evaluation_case_scores ecs
JOIN eval.ground_truth gt ON gt.gt_id = ecs.gt_id
WHERE gt.has_anomaly AND gt.true_recoverable;
