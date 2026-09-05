-- ============================================================================
-- seed.sql — versioned configuration / domain-rule data
-- Load after schema.sql:  psql -d revenue_guard -f database/seed.sql
-- ============================================================================

-- ------------------------------------------------------- source connectors --
INSERT INTO cfg.source_connectors (connector_id, source_system, name, connector_type, base_url, auth_mode, sandbox_mode) VALUES
  ('RAZORPAY_TEST',    'RAZORPAY',    'Razorpay Test/Sandbox',      'API',      'https://api.razorpay.com/v1', 'API_KEY', TRUE),
  ('RAZORPAY_WEBHOOK', 'RAZORPAY',    'Razorpay Webhooks',          'WEBHOOK',  NULL, 'NONE', TRUE),
  ('SHOPIFY_DEV',      'SHOPIFY',     'Shopify Development Store',  'API',      'https://dev-store.myshopify.com/admin/api/2025-01', 'OAUTH', TRUE),
  ('BANK_CSV',         'BANK',        'Bank Statement CSV',         'CSV',      NULL, 'NONE', TRUE),
  ('MARKETPLACE_CSV',  'MARKETPLACE', 'Marketplace Deductions CSV', 'CSV',      NULL, 'NONE', TRUE),
  ('ACCOUNTING_CSV',   'ACCOUNTING',  'Accounting Export CSV',      'CSV',      NULL, 'NONE', TRUE),
  ('GENERATOR_SYNTH',  'GENERATOR',   'Synthetic Master Generator', 'SYNTHETIC', NULL, 'NONE', TRUE);

-- schema versions: raw payload contract per source entity
INSERT INTO cfg.schema_versions (schema_version_id, source_system, entity, version, json_schema, parser_version, normalizer_version) VALUES
  ('RAZORPAY-PAYMENT-V1',     'RAZORPAY',   'payments',          1, '{"type":"object","required":["id","order_id","amount","status"]}'::jsonb, 'parser-1.0.0', 'norm-1.0.0'),
  ('RAZORPAY-REFUND-V1',      'RAZORPAY',   'refunds',           1, '{"type":"object","required":["id","payment_id","amount","status"]}'::jsonb, 'parser-1.0.0', 'norm-1.0.0'),
  ('RAZORPAY-SETTLEMENT-V1',  'RAZORPAY',   'settlements',       1, '{"type":"object","required":["id","payment_id","amount","status"]}'::jsonb, 'parser-1.0.0', 'norm-1.0.0'),
  ('SHOPIFY-ORDER-V1',        'SHOPIFY',    'orders',            1, '{"type":"object","required":["id","total_price","financial_status"]}'::jsonb, 'parser-1.0.0', 'norm-1.0.0'),
  ('BANK-TXN-V1',             'BANK',       'bank_transactions', 1, '{"type":"object","required":["utr","amount","value_date"]}'::jsonb, 'parser-1.0.0', 'norm-1.0.0'),
  ('ACCOUNTING-INVOICE-V1',   'ACCOUNTING', 'invoices',          1, '{"type":"object","required":["invoice_number","total_amount"]}'::jsonb, 'parser-1.0.0', 'norm-1.0.0'),
  ('ACCOUNTING-GST-V1',       'ACCOUNTING', 'gst_records',       1, '{"type":"object","required":["invoice_id","total_tax"]}'::jsonb, 'parser-1.0.0', 'norm-1.0.0');

-- normalization mappings: source field -> canonical field
INSERT INTO cfg.normalization_mappings (mapping_id, source_system, entity, schema_version_id, source_field, canonical_entity, canonical_field, transform) VALUES
  ('NM-RZP-PAY-01', 'RAZORPAY', 'payments', 'RAZORPAY-PAYMENT-V1', 'id',                   'core.payments', 'gateway_payment_id', NULL),
  ('NM-RZP-PAY-02', 'RAZORPAY', 'payments', 'RAZORPAY-PAYMENT-V1', 'order_id',             'core.payments', 'gateway_order_id',   NULL),
  ('NM-RZP-PAY-03', 'RAZORPAY', 'payments', 'RAZORPAY-PAYMENT-V1', 'amount',               'core.payments', 'amount',             'ps_to_number'),
  ('NM-RZP-PAY-04', 'RAZORPAY', 'payments', 'RAZORPAY-PAYMENT-V1', 'method',               'core.payments', 'method',             NULL),
  ('NM-RZP-PAY-05', 'RAZORPAY', 'payments', 'RAZORPAY-PAYMENT-V1', 'notes.order_number',   'core.orders',   'order_number',       'str'),
  ('NM-RZP-PAY-06', 'RAZORPAY', 'payments', 'RAZORPAY-PAYMENT-V1', 'captured_at',          'core.payments', 'captured_at',        'epoch_to_utc'),
  ('NM-RZP-PAY-07', 'RAZORPAY', 'payments', 'RAZORPAY-PAYMENT-V1', 'fee',                  'core.gateway_fees', 'amount',       'ps_to_number'),
  ('NM-RZP-PAY-08', 'RAZORPAY', 'payments', 'RAZORPAY-PAYMENT-V1', 'tax',                  'core.gateway_fees', 'tax_amount',   'ps_to_number'),
  ('NM-RZP-PAY-09', 'RAZORPAY', 'payments', 'RAZORPAY-PAYMENT-V1', 'acquirer_data',        'core.payments', 'acquirer_data',      'json'),
  ('NM-RZP-PAY-10', 'RAZORPAY', 'payments', 'RAZORPAY-PAYMENT-V1', 'status',               'core.payments', 'status',             'razorpay_status_map'),
  ('NM-RZP-SET-01', 'RAZORPAY', 'settlements', 'RAZORPAY-SETTLEMENT-V1', 'id',             'core.settlements', 'gateway_settlement_id', NULL),
  ('NM-RZP-SET-02', 'RAZORPAY', 'settlements', 'RAZORPAY-SETTLEMENT-V1', 'payment_id',     'core.settlements', 'payment_id',       'str'),
  ('NM-RZP-SET-03', 'RAZORPAY', 'settlements', 'RAZORPAY-SETTLEMENT-V1', 'amount',         'core.settlements', 'amount',           'ps_to_number'),
  ('NM-RZP-SET-04', 'RAZORPAY', 'settlements', 'RAZORPAY-SETTLEMENT-V1', 'fee',            'core.settlements', 'fee_deducted',     'ps_to_number'),
  ('NM-RZP-SET-05', 'RAZORPAY', 'settlements', 'RAZORPAY-SETTLEMENT-V1', 'tax',            'core.settlements', 'tax_deducted',     'ps_to_number'),
  ('NM-RZP-SET-06', 'RAZORPAY', 'settlements', 'RAZORPAY-SETTLEMENT-V1', 'utr',            'core.settlements', 'utr',              'str'),
  ('NM-RZP-SET-07', 'RAZORPAY', 'settlements', 'RAZORPAY-SETTLEMENT-V1', 'created_at',     'core.settlements', 'settled_at',       'epoch_to_utc'),
  ('NM-SHO-ORD-01', 'SHOPIFY', 'orders', 'SHOPIFY-ORDER-V1', 'id',                                 'core.orders', 'source_record_id',   'str'),
  ('NM-SHO-ORD-02', 'SHOPIFY', 'orders', 'SHOPIFY-ORDER-V1', 'order_number',                       'core.orders', 'order_number',       NULL),
  ('NM-SHO-ORD-03', 'SHOPIFY', 'orders', 'SHOPIFY-ORDER-V1', 'total_price',                       'core.orders', 'net_amount',         'shopify_money_to_inr'),
  ('NM-SHO-ORD-04', 'SHOPIFY', 'orders', 'SHOPIFY-ORDER-V1', 'financial_status',                  'core.orders', 'financial_status',   'shopify_status_map'),
  ('NM-SHO-ORD-05', 'SHOPIFY', 'orders', 'SHOPIFY-ORDER-V1', 'created_at',                        'core.orders', 'order_date',         'iso8601_to_utc'),
  ('NM-SHO-ORD-06', 'SHOPIFY', 'orders', 'SHOPIFY-ORDER-V1', 'customer.id',                       'core.orders', 'customer_id',        'str'),
  ('NM-SHO-ORD-07', 'SHOPIFY', 'orders', 'SHOPIFY-ORDER-V1', 'note_attributes.gateway_order_id',  'core.orders', 'gateway_order_id',   'json_path'),
  ('NM-BNK-TXN-01', 'BANK', 'bank_transactions', 'BANK-TXN-V1', 'utr',       'core.bank_transactions', 'utr',        NULL),
  ('NM-BNK-TXN-02', 'BANK', 'bank_transactions', 'BANK-TXN-V1', 'amount',   'core.bank_transactions', 'amount',     'signed_to_unsigned'),
  ('NM-BNK-TXN-03', 'BANK', 'bank_transactions', 'BANK-TXN-V1', 'narration','core.bank_transactions', 'narration',  NULL),
  ('NM-BNK-TXN-04', 'BANK', 'bank_transactions', 'BANK-TXN-V1', 'date',     'core.bank_transactions', 'value_date', 'ddmmyyyy_to_date'),
  ('NM-BNK-TXN-05', 'BANK', 'bank_transactions', 'BANK-TXN-V1', 'type',     'core.bank_transactions', 'txn_type',   'credit_debit_map'),
  ('NM-ACC-INV-01', 'ACCOUNTING', 'invoices', 'ACCOUNTING-INVOICE-V1', 'number',    'core.invoices', 'invoice_number', NULL),
  ('NM-ACC-INV-02', 'ACCOUNTING', 'invoices', 'ACCOUNTING-INVOICE-V1', 'total',     'core.invoices', 'total_amount',  'ps_to_number'),
  ('NM-ACC-INV-03', 'ACCOUNTING', 'invoices', 'ACCOUNTING-INVOICE-V1', 'issued_at', 'core.invoices', 'issue_date',    'iso_to_date'),
  ('NM-ACC-INV-04', 'ACCOUNTING', 'invoices', 'ACCOUNTING-INVOICE-V1', 'order_id',  'core.invoices', 'order_id',      'str'),
  ('NM-ACC-GST-01', 'ACCOUNTING', 'gst_records', 'ACCOUNTING-GST-V1', 'invoice_id', 'core.gst_records', 'invoice_id',     'str'),
  ('NM-ACC-GST-02', 'ACCOUNTING', 'gst_records', 'ACCOUNTING-GST-V1', 'cgst',       'core.gst_records', 'cgst',           'ps_to_number'),
  ('NM-ACC-GST-03', 'ACCOUNTING', 'gst_records', 'ACCOUNTING-GST-V1', 'sgst',       'core.gst_records', 'sgst',           'ps_to_number'),
  ('NM-ACC-GST-04', 'ACCOUNTING', 'gst_records', 'ACCOUNTING-GST-V1', 'igst',       'core.gst_records', 'igst',           'ps_to_number'),
  ('NM-ACC-GST-05', 'ACCOUNTING', 'gst_records', 'ACCOUNTING-GST-V1', 'period',     'core.gst_records', 'return_period',  'yyyymm_format'),
  ('NM-ACC-GST-06', 'ACCOUNTING', 'gst_records', 'ACCOUNTING-GST-V1', 'gstin',      'core.gst_records', 'gstin',          NULL);

-- ---------------------------------------------------------------- rate cards
-- Realistic Indian gateway MDR schedule (basis for deterministic expected_fee).
INSERT INTO cfg.rate_cards (rate_card_id, card_name, payment_method, instrument_brand, pct_rate, fixed_fee, min_fee, max_fee, gst_on_fee, valid_from) VALUES
  ('RC-CARD-2025',  'Default Card MDR 2%',        'CARD',       NULL,        0.02000, 0.00, 0.00,  NULL,   TRUE, '2025-01-01'),
  ('RC-UPI-2025',   'Default UPI 0.40% (<=2k), 0.65% above', 'UPI', NULL,    0.00400, 0.00, 0.00,  NULL,   TRUE, '2025-01-01'),
  ('RC-NB-2025',    'Netbanking Flat ₹12',        'NETBANKING', NULL,       0.00000, 12.00, 0.00, NULL,  TRUE, '2025-01-01'),
  ('RC-WALLET-2025','Wallet 1.90%',               'WALLET',     NULL,        0.01900, 0.00, 0.00,  NULL,   TRUE, '2025-01-01'),
  ('RC-EMI-2025',   'EMI 2.35%',                  'EMI',        NULL,        0.02350, 0.00, 0.00,  NULL,   TRUE, '2025-01-01');

-- ------------------------------------------------------- financial rules ----
-- expression is evaluated by the SQL rule engine (functions.sql) — deterministic.
INSERT INTO cfg.financial_rules (rule_id, rule_name, category, leak_category, rule_type, expression, description, severity) VALUES
  ('FR-FEE-CALC-001',   'Expected MDR fee from rate card',            'FEE',        'FEE_DISCREPANCY',      'FORMULA',  'expected_fee = rc.pct_rate * p.amount + rc.fixed_fee (min_fee/max_fee applied)', 'Deterministic expected fee per payment from negotiated rate card.', 'HIGH'),
  ('FR-FEE-TOL-001',    'Fee tolerance ±₹1 or 0.5%',                  'FEE',        'FEE_DISCREPANCY',      'THRESHOLD','abs(actual_fee - expected_fee) <= GREATEST(1.00, expected_fee*0.005) => LEGITIMATE', 'Rounding/precision drift on fees is legitimate.', 'LOW'),
  ('FR-FEE-EXCESS-001', 'Fee above rate card beyond tolerance',       'FEE',        'FEE_DISCREPANCY',      'THRESHOLD','actual_fee - expected_fee > GREATEST(1.00, expected_fee*0.005) => LEAKAGE',   'Gateway charged above contract.', 'HIGH'),
  ('FR-GST-ON-FEE-001', 'GST 18% charged on fee, not on gross',       'TAX',        'FEE_DISCREPANCY',      'FORMULA',  'expected_tax = expected_fee * 0.18', 'GST applies to MDR only.', 'MEDIUM'),
  ('FR-SETTLE-CALC-001','Expected settlement = gross - fee - tax',    'SETTLEMENT', 'SETTLEMENT_MISMATCH',  'FORMULA',  'expected_settlement = p.amount - expected_fee - expected_tax - refund_in_flight', 'Core settlement expectation.', 'HIGH'),
  ('FR-SETTLE-TOL-001', 'Settlement tolerance ±₹2 or 0.1%',           'SETTLEMENT', 'SETTLEMENT_MISMATCH',  'THRESHOLD','abs(variance) <= GREATEST(2.00, expected*0.001) => LEGITIMATE', 'Rounding drift on settlements is legitimate.', 'LOW'),
  ('FR-SETTLE-TIMING-001','Settlement within T+3+grace => TIMING',    'SETTLEMENT', 'SETTLEMENT_MISMATCH',  'BEHAVIOUR','now() < settled_at_expected + grace => TIMING_DIFFERENCE', 'Not-yet-due settlements are timing, not leakage.', 'LOW'),
  ('FR-REFUND-ECON-001','Refund fee not returned on partial refund',  'REFUND',     'REFUND_ECONOMICS',    'CONTRACT', 'gateway_fee_returned == expected_fee * (refund_amount / payment_amount)', 'Proportional fee return on refunds is contractual.', 'MEDIUM'),
  ('FR-REFUND-EXCESS-001','Refunded more than paid',                  'REFUND',     'REFUND_ECONOMICS',    'THRESHOLD','SUM(refund.amount) > payment.amount => LEAKAGE', 'Over-refund is immediate leakage.', 'HIGH'),
  ('FR-PAY-MATCH-001',  'Payment amount equals order net amount',     'SETTLEMENT', 'PAYMENT_MISMATCH',    'CONTRACT', 'abs(p.amount - o.net_amount) <= 0.01 => MATCHED', 'Order-vs-payment equality check.', 'HIGH'),
  ('FR-BANK-MATCH-001', 'Bank credit equals settlement amount',       'SETTLEMENT', 'SETTLEMENT_MISMATCH',  'CONTRACT', 'abs(b.amount - s.amount) <= 0.01 => MATCHED', 'Settlement-vs-bank equality via UTR.', 'HIGH'),
  ('FR-GST-ITC-001',    'ITC on MDR GST must appear in GSTR-2B',      'GST',        'GST_ITC_REVIEW',      'CONTRACT', 'gst_record.itc_matched == TRUE => eligible else REVIEW', 'ITC review workflow, never auto-recovery.', 'MEDIUM');

-- ------------------------------------------------------- tolerance rules ---
INSERT INTO cfg.tolerance_rules (tolerance_id, scope, amount_tolerance, pct_tolerance, time_tolerance) VALUES
  ('TOL-PAYMENT',   'PAYMENT',    0.50,  0.00050, NULL),
  ('TOL-SETTLEMENT','SETTLEMENT', 2.00,  0.00100, 'P3D'),
  ('TOL-FEE',       'FEE',        1.00,  0.00500, NULL),
  ('TOL-REFUND',    'REFUND',     0.50,  0.00050, NULL),
  ('TOL-BANK',      'BANK',       2.00,  0.00100, 'P5D'),
  ('TOL-TIMING',    'TIMING',     0.00,  0.00000, 'P3D');

-- ---------------------------------------------------------- SLA rules ------
INSERT INTO cfg.sla_rules (sla_rule_id, scope, reference_days, grace_days, hard_deadline_days, description) VALUES
  ('SLA-SETTLEMENT-T3',   'SETTLEMENT',       3,  2, 45, 'Razorpay T+3 settlement cycle; 2d grace; 45d recovery window'),
  ('SLA-BANK-CREDIT-T1',  'BANK_CREDIT',     1,  1, 30, 'Bank credit lands within 1 day of settlement processing'),
  ('SLA-DISPUTE-WINDOW',  'DISPUTE',         7,  2, 60, 'Gateway dispute acknowledgement window'),
  ('SLA-CHARGEBACK-NETWORK','CHARGEBACK',    7,  0, 20, 'Card network chargeback response window'),
  ('SLA-RECEIVABLE-NET30','RECEIVABLE',    30,  7, 90, 'Invoice net-30 + 7d grace; 90d write-off horizon'),
  ('SLA-SUBSCRIPTION-RETRY','SUBSCRIPTION_RETRY', 3, 1, 15, 'Dunning retry cycle over 3 days');

-- ----------------------------------------------------- recovery policies ---
-- Bounded autonomy: which actions are allowed per category, per amount band.
INSERT INTO cfg.recovery_policies (policy_id, category, min_amount, max_amount, allowed_actions, auto_approve_below, requires_evidence, max_attempts, escalation_after_attempts, deadline_days) VALUES
  ('RP-DEFAULT',           'DEFAULT',             0,      NULL,   '{DRAFT_DISPUTE,CREATE_DISPUTE,NOTIFY_GATEWAY,FINANCE_REVIEW,ESCALATE,CLOSE_NO_ACTION}', 0,      '{RECON_RESULT,RULE_RESULT,RAW_PAYLOAD}', 3, 2, 30),
  ('RP-FEE-SMALL',         'FEE_DISCREPANCY',     0,      500,    '{NOTIFY_GATEWAY,DRAFT_DISPUTE,FINANCE_REVIEW,ESCALATE,CLOSE_NO_ACTION}',             250,    '{RECON_RESULT,RULE_RESULT,RATE_CARD}',   2, 1, 30),
  ('RP-FEE-LARGE',         'FEE_DISCREPANCY',     500,    NULL,   '{DRAFT_DISPUTE,CREATE_DISPUTE,NOTIFY_GATEWAY,FINANCE_REVIEW,ESCALATE}',              0,      '{RECON_RESULT,RULE_RESULT,RATE_CARD,RAW_PAYLOAD}', 3, 2, 30),
  ('RP-SETTLEMENT-STD',    'SETTLEMENT_MISMATCH', 0,      5000,   '{DRAFT_DISPUTE,CREATE_DISPUTE,NOTIFY_GATEWAY,FINANCE_REVIEW,ESCALATE}',              500,    '{RECON_RESULT,RULE_RESULT,RAW_PAYLOAD}', 3, 2, 45),
  ('RP-SETTLEMENT-LARGE',  'SETTLEMENT_MISMATCH', 5000,   NULL,   '{DRAFT_DISPUTE,FINANCE_REVIEW,ESCALATE}',                                            0,      '{RECON_RESULT,RULE_RESULT,RAW_PAYLOAD,IDENTITY}', 2, 1, 45),
  ('RP-REFUND-ECON',       'REFUND_ECONOMICS',    0,      NULL,   '{DRAFT_DISPUTE,CREATE_DISPUTE,FINANCE_REVIEW,ESCALATE,CLOSE_NO_ACTION}',             250,    '{RECON_RESULT,RULE_RESULT,RAW_PAYLOAD}', 3, 2, 30),
  ('RP-PAYMENT-MISMATCH',  'PAYMENT_MISMATCH',    0,      NULL,   '{NOTIFY_CUSTOMER,DRAFT_DISPUTE,FINANCE_REVIEW,ESCALATE}',                            250,    '{RECON_RESULT,RAW_PAYLOAD}',             2, 1, 30),
  ('RP-GST-ITC',           'GST_ITC_REVIEW',      0,      NULL,   '{FINANCE_REVIEW,ESCALATE}',                                                            0,      '{RAW_PAYLOAD,RULE_RESULT}',              2, 1, 60);

-- ------------------------------------------------------ agent tool registry -
INSERT INTO ops.agent_tools (tool_id, tool_name, tool_class, risk_level, input_schema, output_schema, allowed_actors, side_effects, idempotency_key, failure_behavior, audit_required) VALUES
  ('get_order',              'Fetch canonical order',                'READ',        'L0_READ',      '{"order_id":"string"}', '{"order":"object"}', '{AGENT,HUMAN}', '{}', NULL, 'Returns NOT_FOUND; agent may re-query.', TRUE),
  ('get_payment',            'Fetch canonical payment',              'READ',        'L0_READ',      '{"payment_id":"string"}', '{"payment":"object"}', '{AGENT,HUMAN}', '{}', NULL, 'Returns NOT_FOUND.', TRUE),
  ('get_refund',             'Fetch refunds for payment',            'READ',        'L0_READ',      '{"payment_id":"string"}', '{"refunds":"array"}', '{AGENT,HUMAN}', '{}', NULL, 'Empty array on none.', TRUE),
  ('get_settlement',         'Fetch settlements for payment',        'READ',        'L0_READ',      '{"payment_id":"string"}', '{"settlements":"array"}', '{AGENT,HUMAN}', '{}', NULL, 'Empty array on none.', TRUE),
  ('get_bank_transaction',   'Fetch bank lines by UTR',               'READ',        'L0_READ',      '{"utr":"string"}', '{"bank_txns":"array"}', '{AGENT,HUMAN}', '{}', NULL, 'Empty array on none.', TRUE),
  ('get_invoice',            'Fetch invoice for order',              'READ',        'L0_READ',      '{"order_id":"string"}', '{"invoice":"object"}', '{AGENT,HUMAN}', '{}', NULL, 'NULL if not invoiced.', TRUE),
  ('get_rate_card',          'Fetch applicable rate card',            'READ',        'L0_READ',      '{"payment_method":"string","date":"string"}', '{"rate_card":"object"}', '{AGENT,HUMAN}', '{}', NULL, 'NULL if no card matches.', TRUE),
  ('get_case_history',       'Fetch case timeline',                  'READ',        'L0_READ',      '{"case_id":"string"}', '{"history":"array"}', '{AGENT,HUMAN}', '{}', NULL, 'Empty array on new case.', TRUE),
  ('calculate_fee',          'Deterministic fee calc (rule engine)',  'ANALYSIS',    'L0_READ',      '{"payment_id":"string"}', '{"expected_fee":"number","expected_tax":"number","calculation":"object"}', '{AGENT,HUMAN,SERVICE}', '{}', NULL, 'Never estimates; errors if rate card missing.', TRUE),
  ('calculate_variance',     'Deterministic variance calc',          'ANALYSIS',    'L0_READ',      '{"case_id":"string"}', '{"variance":"number","unexplained":"number","breakdown":"object"}', '{AGENT,HUMAN,SERVICE}', '{}', NULL, 'Errors if reconciliation missing.', TRUE),
  ('check_contract',         'Evaluate contract rule for case',       'ANALYSIS',    'L0_READ',      '{"case_id":"string"}', '{"violations":"array"}', '{AGENT,HUMAN,SERVICE}', '{}', NULL, 'Empty array if compliant.', TRUE),
  ('check_deadline',         'Check SLA deadline state',              'ANALYSIS',    'L0_READ',      '{"case_id":"string"}', '{"deadline_at":"string","days_left":"integer","state":"string"}', '{AGENT,HUMAN,SERVICE}', '{}', NULL, 'Errors if no SLA applies.', TRUE),
  ('check_duplicate_claim',  'Duplicate recovery claim guard',        'ANALYSIS',    'L0_READ',      '{"case_id":"string"}', '{"is_duplicate":"boolean","existing_claims":"array"}', '{AGENT,HUMAN,SERVICE}', '{}', NULL, 'Never assumes; returns evidence.', TRUE),
  ('draft_dispute',          'Draft dispute document (no submit)',   'ACTION',      'L1_DRAFT',     '{"case_id":"string","evidence_ids":"array"}', '{"draft":"object","draft_id":"string"}', '{AGENT}', '{"creates_dispute_draft"}', 'case_id+draft', 'Draft persisted; safe to retry.', TRUE),
  ('create_dispute',         'Submit dispute to gateway',             'ACTION',      'L3_FINANCIAL', '{"case_id":"string","draft_id":"string"}', '{"dispute_id":"string","status":"string"}', '{AGENT,HUMAN}', '{"submits_dispute","financial_claim"}', 'case_id+dispute', 'Idempotent by external dispute id; returns existing on retry.', TRUE),
  ('prepare_chargeback_packet','Assemble chargeback evidence packet','ACTION',      'L1_DRAFT',     '{"case_id":"string"}', '{"packet_id":"string","documents":"array"}', '{AGENT}', '{"creates_packet"}', 'case_id+packet', 'Packet persisted; retry-safe.', TRUE),
  ('create_payment_link',    'Create recovery payment link',         'ACTION',      'L3_FINANCIAL', '{"case_id":"string","amount":"number","customer_id":"string"}', '{"link_id":"string","url":"string"}', '{AGENT,HUMAN}', '{"creates_payment_link"}', 'case_id+link', 'Idempotent per case+amount.', TRUE),
  ('schedule_retry',         'Schedule payment retry (subscription)','ACTION',      'L2_REVERSIBLE','{"case_id":"string","when":"string"}', '{"retry_id":"string"}', '{AGENT,HUMAN}', '{"schedules_retry"}', 'case_id+when', 'Retry can be cancelled before run.', TRUE),
  ('send_receivable_reminder','Send AR reminder to customer',        'ACTION',      'L2_REVERSIBLE','{"case_id":"string","invoice_id":"string"}', '{"reminder_id":"string"}', '{AGENT,HUMAN}', '{"sends_communication"}', 'invoice_id+seq', 'Max 1 per period; suppressible.', TRUE),
  ('create_finance_review',  'Open finance review ticket (GST/ITC)',  'ACTION',      'L2_REVERSIBLE','{"case_id":"string","notes":"string"}', '{"review_id":"string"}', '{AGENT,HUMAN}', '{"creates_ticket"}', 'case_id+review', 'One open review per case.', TRUE),
  ('check_settlement',       'Verify settlement changed',            'VERIFICATION','L0_READ',      '{"case_id":"string","since":"string"}', '{"changed":"boolean","new_amount":"number"}', '{AGENT,HUMAN,SERVICE}', '{}', NULL, 'Read-only check.', TRUE),
  ('check_dispute_status',   'Poll dispute state at gateway',        'VERIFICATION','L0_READ',      '{"dispute_id":"string"}', '{"status":"string","resolved_at":"string"}', '{AGENT,HUMAN,SERVICE}', '{}', NULL, 'Read-only poll.', TRUE),
  ('check_payment_status',   'Poll payment state',                   'VERIFICATION','L0_READ',      '{"payment_id":"string"}', '{"status":"string"}', '{AGENT,HUMAN,SERVICE}', '{}', NULL, 'Read-only poll.', TRUE),
  ('check_recovery',         'Did money actually return?',           'VERIFICATION','L0_READ',      '{"case_id":"string"}', '{"recovered_amount":"number","evidence":"array"}', '{AGENT,HUMAN,SERVICE}', '{}', NULL, 'Deterministic bank/settlement check.', TRUE);
