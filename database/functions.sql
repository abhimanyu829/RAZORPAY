-- ============================================================================
-- functions.sql — deterministic financial calculation engine (PostgreSQL)
-- The AI agent NEVER computes money; it calls these via tools and reads results.
-- Load after seed.sql:  psql -d revenue_guard -f database/functions.sql
-- ============================================================================

-- ------------------------------------------------------------- fee engine --

-- Expected fee for a payment from its applicable rate card. Deterministic.
CREATE OR REPLACE FUNCTION cfg.fn_expected_fee(p_payment_id TEXT)
RETURNS TABLE (expected_fee NUMERIC, expected_tax NUMERIC, rate_card_id TEXT)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  p core.payments%ROWTYPE;
  rc cfg.rate_cards%ROWTYPE;
  fee NUMERIC(18,4);
BEGIN
  SELECT * INTO p FROM core.payments WHERE payment_id = p_payment_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'payment % not found', p_payment_id; END IF;
  SELECT * INTO rc FROM cfg.rate_cards
   WHERE payment_method = p.method
     AND (instrument_brand IS NULL OR instrument_brand = p.instrument_brand)
     AND p.captured_at::date >= valid_from
     AND (valid_to IS NULL OR p.captured_at::date <= valid_to)
   ORDER BY valid_from DESC LIMIT 1;
  IF NOT FOUND THEN RAISE EXCEPTION 'no rate card for method %', p.method; END IF;
  fee := rc.pct_rate * p.amount + rc.fixed_fee;
  IF rc.min_fee > 0 AND fee < rc.min_fee THEN fee := rc.min_fee; END IF;
  IF rc.max_fee IS NOT NULL AND fee > rc.max_fee THEN fee := rc.max_fee; END IF;
  fee := ROUND(fee, 2);
  IF rc.gst_on_fee THEN
    RETURN QUERY SELECT fee, ROUND(fee * 0.18, 2), rc.rate_card_id;
  ELSE
    RETURN QUERY SELECT fee, 0::numeric, rc.rate_card_id;
  END IF;
END $$;

-- Expected settlement for a payment: gross - fee - tax.
CREATE OR REPLACE FUNCTION cfg.fn_expected_settlement(p_payment_id TEXT)
RETURNS TABLE (expected_settlement NUMERIC, expected_fee NUMERIC, expected_tax NUMERIC)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  p core.payments%ROWTYPE;
  f NUMERIC(18,4); t NUMERIC(18,4); rc_id TEXT;
BEGIN
  SELECT * INTO p FROM core.payments WHERE payment_id = p_payment_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'payment % not found', p_payment_id; END IF;
  SELECT expected_fee, expected_tax, rate_card_id INTO f, t, rc_id FROM cfg.fn_expected_fee(p_payment_id);
  RETURN QUERY SELECT ROUND(p.amount - f - t, 2), f, t;
END $$;

-- Full refund economics: expected settlement net of refunds with pro-rata fee return.
-- Contract FR-REFUND-ECON-001: gateway returns fee pro-rata on refunded amount.
CREATE OR REPLACE FUNCTION cfg.fn_expected_settlement_with_refund(p_payment_id TEXT)
RETURNS TABLE (expected_settlement NUMERIC, expected_fee NUMERIC, expected_tax NUMERIC,
               refunded_amount NUMERIC, fee_returned NUMERIC)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  p core.payments%ROWTYPE;
  f NUMERIC(18,4); t NUMERIC(18,4); rc_id TEXT;
  refunded NUMERIC(18,4); fee_ret NUMERIC(18,4);
BEGIN
  SELECT * INTO p FROM core.payments WHERE payment_id = p_payment_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'payment % not found', p_payment_id; END IF;
  SELECT expected_fee, expected_tax, rate_card_id INTO f, t, rc_id FROM cfg.fn_expected_fee(p_payment_id);
  SELECT COALESCE(SUM(amount), 0) INTO refunded
    FROM core.refunds WHERE payment_id = p_payment_id AND status IN ('INITIATED','PROCESSED');
  fee_ret := ROUND(f * (refunded / p.amount), 2);
  RETURN QUERY SELECT ROUND(p.amount - f - t - refunded + fee_ret, 2), f, t, refunded, fee_ret;
END $$;

-- ------------------------------------------------------ variance classifier --
-- Classifies a variance into ops.data_class using tolerance rules.
-- Deterministic; used by the anomaly engine. Timing/deadline logic lives in
-- fn_recoverability (it needs SLA dates); here a NULL actual within window = TIMING.
CREATE OR REPLACE FUNCTION cfg.fn_classify_variance(
  p_expected NUMERIC, p_actual NUMERIC, p_scope TEXT, p_deadline_at TIMESTAMPTZ DEFAULT NULL,
  p_now TIMESTAMPTZ DEFAULT now()
)
RETURNS ops.data_class
LANGUAGE plpgsql STABLE AS $$
DECLARE
  tol_amount NUMERIC(18,4) := 0;
  tol_pct NUMERIC(8,5) := 0;
  var_ NUMERIC(18,4);
  rec RECORD;
BEGIN
  var_ := p_expected - COALESCE(p_actual, 0);
  SELECT amount_tolerance, pct_tolerance INTO tol_amount, tol_pct
    FROM cfg.tolerance_rules WHERE scope = p_scope AND is_active LIMIT 1;
  IF p_actual IS NULL THEN
    IF p_deadline_at IS NULL OR p_now <= p_deadline_at THEN
      RETURN 'TIMING';   -- not yet due: temporary difference, never leakage
    END IF;
    RETURN 'LEAKAGE';    -- past deadline and nothing arrived
  END IF;
  IF abs(var_) <= GREATEST(tol_amount, abs(p_expected) * tol_pct) THEN
    RETURN 'LEGITIMATE'; -- within tolerance: rounding drift etc.
  END IF;
  -- Above tolerance: LEAKAGE candidate. The anomaly engine re-examines the
  -- candidate and may reclassify as ADJUSTMENT (documented adjustment present)
  -- or TIMING (re-check at deadline) before opening a case.
  RETURN 'LEAKAGE';
END $$;

-- ------------------------------------------------- recoverability pipeline --
-- Full deterministic recoverability assessment for a case. Writes nothing;
-- returns the verdict for the recoverability engine to persist.
CREATE OR REPLACE FUNCTION cfg.fn_assess_recoverability(p_case_id TEXT)
RETURNS TABLE (status ops.recoverability_status, potentially_recoverable NUMERIC,
               confidence NUMERIC, evidence_complete BOOLEAN, deadline_open BOOLEAN,
               recommended_action TEXT, reasons TEXT[])
LANGUAGE plpgsql STABLE AS $$
DECLARE
  c ops.recovery_cases%ROWTYPE;
  a ops.anomaly_results%ROWTYPE;
  pol cfg.recovery_policies%ROWTYPE;
  ev_count INTEGER;
  i INTEGER;
  missing TEXT[] := '{}';
  sla_deadline TIMESTAMPTZ;
  days_left INTEGER;
BEGIN
  SELECT * INTO c FROM ops.recovery_cases WHERE case_id = p_case_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'case % not found', p_case_id; END IF;
  SELECT * INTO a FROM ops.anomaly_results WHERE anomaly_id = c.anomaly_id;
  SELECT * INTO pol FROM cfg.recovery_policies
    WHERE category = c.category::text AND is_active
    ORDER BY (CASE WHEN c.potential_leakage BETWEEN min_amount AND COALESCE(max_amount, c.potential_leakage + 1) THEN 0 ELSE 1 END), min_amount DESC
    LIMIT 1;
  IF NOT FOUND THEN
    SELECT * INTO pol FROM cfg.recovery_policies WHERE category = 'DEFAULT' AND is_active LIMIT 1;
  END IF;

  -- Evidence check
  SELECT COUNT(*) INTO ev_count FROM ops.evidence_records WHERE case_id = p_case_id;
  FOR i IN 1..COALESCE(array_length(pol.requires_evidence, 1), 0) LOOP
    IF NOT EXISTS (SELECT 1 FROM ops.evidence_records WHERE case_id = p_case_id AND evidence_kind::text = pol.requires_evidence[i]) THEN
      missing := missing || pol.requires_evidence[i];
    END IF;
  END LOOP;

  -- Deadline check (SLA: settlement window from detection time)
  SELECT now() + (hard_deadline_days || ' days')::interval INTO sla_deadline
    FROM cfg.sla_rules WHERE scope = 'SETTLEMENT' AND is_active LIMIT 1;
  days_left := EXTRACT(DAY FROM (sla_deadline - now()))::integer;

  -- Verdict
  IF c.category::text = 'GST_ITC_REVIEW' THEN
    RETURN QUERY SELECT 'REVIEW_REQUIRED'::ops.recoverability_status, a.detected_amount,
                        0.80::numeric, (ev_count > 0), TRUE, 'FINANCE_REVIEW'::text,
                        ARRAY['GST/ITC is always a finance review workflow, never auto-recovery'];
  ELSIF array_length(missing, 1) > 0 THEN
    RETURN QUERY SELECT 'REVIEW_REQUIRED'::ops.recoverability_status, a.detected_amount,
                        0.50::numeric, FALSE, (days_left > 0), 'COLLECT_EVIDENCE'::text,
                        ARRAY['missing evidence: ' || array_to_string(missing, ',')];
  ELSIF days_left <= 0 THEN
    RETURN QUERY SELECT 'NOT_RECOVERABLE'::ops.recoverability_status, a.detected_amount,
                        0.30::numeric, TRUE, FALSE, 'CLOSE_NO_ACTION'::text,
                        ARRAY['recovery window closed'];
  ELSE
    RETURN QUERY SELECT 'ACTION_READY'::ops.recoverability_status,
                        ROUND(a.detected_amount * CASE WHEN c.category::text = 'FEE_DISCREPANCY' THEN 1.0 ELSE 0.95 END, 2),
                        LEAST(0.95, 0.60 + 0.05 * LEAST(ev_count, 5))::numeric,
                        TRUE, TRUE,
                        (pol.allowed_actions[1])::text,
                        ARRAY['unexplained variance beyond tolerance within recovery window'];
  END IF;
END $$;

-- --------------------------------------------------------------- KPI rollup --
-- Recovery KPIs: the single source for the dashboard and evaluation.
CREATE OR REPLACE VIEW ops.v_recovery_kpi AS
SELECT
  COUNT(*)                                                        AS total_cases,
  COALESCE(SUM(potential_leakage), 0)                             AS leakage_detected_amount,
  COALESCE(SUM(potential_recovery), 0)                            AS recoverable_amount,
  COUNT(*) FILTER (WHERE status = 'RECOVERED')                     AS cases_recovered,
  COUNT(*) FILTER (WHERE status IN ('ESCALATED','PENDING_APPROVAL')) AS human_escalations,
  COALESCE(SUM(CASE WHEN status = 'RECOVERED' THEN potential_recovery ELSE 0 END), 0) AS recovered_amount,
  ROUND(COALESCE(SUM(CASE WHEN status = 'RECOVERED' THEN potential_recovery ELSE 0 END),0)
        / NULLIF(SUM(potential_recovery), 0) * 100, 2)            AS recovery_rate_pct,
  ROUND(COALESCE(SUM(CASE WHEN status = 'RECOVERED' THEN potential_recovery ELSE 0 END),0)
        / NULLIF(SUM(potential_leakage), 0) * 100, 2)             AS leakage_recovered_pct
FROM ops.recovery_cases;
