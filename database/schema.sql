-- ============================================================================
-- AI REVENUE LEAKAGE DETECTION, DIAGNOSIS & AUTONOMOUS RECOVERY AGENT
-- Complete PostgreSQL Schema — MVP (Phase 1) + Phase 2 + Phase 3 markers
-- PostgreSQL 15+.  Money: NUMERIC(18,4).  Timestamps: TIMESTAMPTZ (UTC).  Currency: INR.
--
-- Schemas:
--   raw  — immutable ingestion plane (raw payloads, batches, quarantine)
--   core — canonical financial entities (the transaction graph)
--   ops  — engine + agent derived data (cases, actions, audit, approvals, verification)
--   cfg  — versioned configuration / domain rules / tool registry
--   eval — evaluator-only ground truth (agent DB role has NO SELECT on eval)
--
-- Load order: schema.sql → seed.sql → functions.sql → views.sql → indexes.sql
--   psql -d revenue_guard -f database/schema.sql   (etc.)
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS cfg;
CREATE SCHEMA IF NOT EXISTS eval;

-- Note on enum strategy: PostgreSQL ENUM types are used for the stable, engine-
-- critical domains (recon status, recoverability, risk). They are created with
-- explicit values and ALTER TYPE ... ADD VALUE is the only extension path.
-- Softer domains (source_system, category labels) stay TEXT + CHECK for
-- extensibility without migration downtime.

-- ---------------------------------------------------------------- enums ----
CREATE TYPE ops.recon_status AS ENUM (
  'MATCHED','PARTIAL','TIMING_DIFFERENCE','UNMATCHED','MISMATCH','DUPLICATE','CONFLICT','PENDING','REVIEW_REQUIRED');
CREATE TYPE ops.case_status AS ENUM (
  'NEW','INVESTIGATING','PLANNED','PENDING_APPROVAL','ACTING','VERIFYING',
  'RECOVERED','PARTIALLY_RECOVERED','UNRECOVERABLE','ESCALATED','CLOSED');
CREATE TYPE ops.approval_status AS ENUM ('REQUESTED','APPROVED','REJECTED','EXPIRED');
CREATE TYPE ops.tool_risk AS ENUM ('L0_READ','L1_DRAFT','L2_REVERSIBLE','L3_FINANCIAL','L4_TAX_LEGAL');
CREATE TYPE ops.recon_direction AS ENUM (
  'PAYMENT_VS_ORDER','SETTLEMENT_VS_PAYMENT','BANK_VS_SETTLEMENT','REFUND_VS_PAYMENT',
  'FEE_VS_RATE_CARD','INVOICE_VS_ORDER','GST_VS_INVOICE','MARKETPLACE_VS_SETTLEMENT',
  'SUBSCRIPTION_VS_RECEIVABLE','CHARGEBACK_VS_PAYMENT','RECEIVABLE_VS_INVOICE');
CREATE TYPE ops.recoverability_status AS ENUM (
  'DETECTED','VALIDATING','EXPLAINABLE','UNEXPLAINED','ELIGIBILITY_CHECK','EVIDENCE_CHECK',
  'DEADLINE_CHECK','RECOVERABLE','REVIEW_REQUIRED','NOT_RECOVERABLE','ACTION_READY');
CREATE TYPE ops.leak_category AS ENUM (
  'PAYMENT_MISMATCH','SETTLEMENT_MISMATCH','FEE_DISCREPANCY','REFUND_ECONOMICS',        -- MVP 1-4
  'MARKETPLACE_DEDUCTION','GST_ITC_REVIEW','FAILED_PAYMENT','SUBSCRIPTION_FAILURE',     -- Phase 2 5-8
  'RECEIVABLE_OVERDUE','CHARGEBACK','CHECKOUT_ABANDONMENT');                            -- Phase 3 9-11
CREATE TYPE ops.match_method AS ENUM (
  'EXACT_REF','SHARED_ORDER','INVOICE_REF','UTR','AMOUNT_WINDOW','METADATA','PROBABILISTIC','MANUAL');
CREATE TYPE ops.verification_status AS ENUM (
  'ACTION_SUBMITTED','ACKNOWLEDGED','IN_PROGRESS','SUCCESS','FAILED','EXPIRED',
  'FINANCIAL_EFFECT_DETECTED','RECOVERY_VERIFIED','DUPLICATE_AVOIDED');
CREATE TYPE ops.identity_status AS ENUM ('RESOLVED','AUTO_MERGED','REVIEW_REQUIRED','CONFLICT','UNRESOLVED');
CREATE TYPE ops.adjustment_kind AS ENUM (
  'NONE','GATEWAY_ADJUSTMENT','RATE_DIFFERENCE','ROUNDING','TAX_ADJUSTMENT',
  'REFUND_REVERSAL','CURRENCY','DISCOUNT','OTHER');
CREATE TYPE ops.data_class AS ENUM ('LEGITIMATE','TIMING','ADJUSTMENT','LEAKAGE','REVIEW_ONLY');
CREATE TYPE raw.validation_status AS ENUM ('VALID','QUARANTINED','REJECTED');
CREATE TYPE ops.evidence_kind AS ENUM (
  'RECON_RESULT','RULE_RESULT','RAW_PAYLOAD','RATE_CARD','SCHEMA_CONTRACT','IDENTITY',
  'EXPLANATION','ADJUSTMENT','CALCULATION','STATUS','TIMESTAMP','AMOUNT','REFERENCE');

-- =========================================================== CONFIG (cfg) ==

-- Source connector catalog: which external systems can feed ingestion.
CREATE TABLE cfg.source_connectors (
  connector_id     TEXT PRIMARY KEY,                -- e.g. 'RAZORPAY_TEST'
  source_system    TEXT NOT NULL,                   -- RAZORPAY|SHOPIFY|BANK|MARKETPLACE|ACCOUNTING|APPLICATION|GENERATOR
  name             TEXT NOT NULL,
  connector_type   TEXT NOT NULL,                   -- API | WEBHOOK | CSV | SYNTHETIC
  base_url         TEXT,
  auth_mode        TEXT NOT NULL DEFAULT 'NONE',    -- NONE | API_KEY | OAUTH | TOKEN
  sandbox_mode     BOOLEAN NOT NULL DEFAULT TRUE,
  enabled          BOOLEAN NOT NULL DEFAULT TRUE,
  config           JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (connector_type IN ('API','WEBHOOK','CSV','SYNTHETIC')),
  CHECK (auth_mode IN ('NONE','API_KEY','OAUTH','TOKEN')),
  CHECK (source_system IN ('RAZORPAY','SHOPIFY','BANK','MARKETPLACE','ACCOUNTING','APPLICATION','GENERATOR'))
);

-- Registry of raw payload shapes per source; enables parser versioning.
CREATE TABLE cfg.schema_versions (
  schema_version_id TEXT PRIMARY KEY,               -- 'RAZORPAY-PAYMENT-V1'
  source_system     TEXT NOT NULL,
  entity            TEXT NOT NULL,                  -- payments | refunds | settlements | orders ...
  version           INTEGER NOT NULL,
  json_schema       JSONB NOT NULL,                  -- JSON Schema of raw payload
  parser_version    TEXT NOT NULL,
  normalizer_version TEXT NOT NULL,
  valid_from        TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_to          TIMESTAMPTZ,
  UNIQUE (source_system, entity, version)
);

-- Field mapping: source field -> canonical column (per source + entity).
CREATE TABLE cfg.normalization_mappings (
  mapping_id       TEXT PRIMARY KEY,                -- 'RAZORPAY-PAYMENT-V1'
  source_system    TEXT NOT NULL,
  entity           TEXT NOT NULL,
  schema_version_id TEXT NOT NULL REFERENCES cfg.schema_versions(schema_version_id),
  source_field     TEXT NOT NULL,                   -- 'notes.shopify_order_id'
  canonical_entity TEXT NOT NULL,                   -- 'core.payments'
  canonical_field  TEXT NOT NULL,                   -- 'order_id'
  transform        TEXT,                            -- 'uppercase' | 'parse_inr' | 'iso8601_to_utc' | SQL expression
  UNIQUE (source_system, entity, source_field, canonical_field)
);

-- Negotiated fee schedules: the contractual basis for expected_fee.
CREATE TABLE cfg.rate_cards (
  rate_card_id     TEXT PRIMARY KEY,                -- 'RC-DEFAULT-2025'
  card_name        TEXT NOT NULL,
  payment_method   TEXT NOT NULL,                   -- CARD | NETBANKING | UPI | WALLET | EMI
  instrument_brand TEXT,                            -- VISA | MASTERCARD | RUPAY | NULL=all
  pct_rate         NUMERIC(8,5)  NOT NULL,          -- 0.02000 = 2%
  fixed_fee        NUMERIC(18,4) NOT NULL DEFAULT 0,
  min_fee          NUMERIC(18,4) NOT NULL DEFAULT 0,
  max_fee          NUMERIC(18,4),                   -- NULL = no cap
  gst_on_fee       BOOLEAN NOT NULL DEFAULT TRUE,   -- GST(18%) charged on fee
  currency         TEXT NOT NULL DEFAULT 'INR',
  valid_from       DATE NOT NULL,
  valid_to         DATE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (pct_rate >= 0 AND fixed_fee >= 0 AND min_fee >= 0),
  CHECK (max_fee IS NULL OR max_fee >= min_fee),
  CHECK (payment_method IN ('CARD','NETBANKING','UPI','WALLET','EMI'))
);
COMMENT ON TABLE cfg.rate_cards IS 'Contractual fee expectations; expected_fee derived deterministically from these rows.';

-- Deterministic financial rules (fee/tax/settlement/refund economics).
CREATE TABLE cfg.financial_rules (
  rule_id          TEXT PRIMARY KEY,                -- 'FR-FEE-CALC-001'
  rule_name        TEXT NOT NULL,
  category         TEXT NOT NULL,                   -- FEE | TAX | SETTLEMENT | REFUND | MARKETPLACE | GST
  leak_category    TEXT,                            -- optional link to ops.leak_category
  rule_type        TEXT NOT NULL,                   -- FORMULA | THRESHOLD | CONTRACT | BEHAVIOUR
  expression       TEXT NOT NULL,                   -- SQL expression evaluated by the rule engine
  description      TEXT NOT NULL,
  severity         TEXT NOT NULL DEFAULT 'MEDIUM',  -- INFO | LOW | MEDIUM | HIGH | CRITICAL
  is_active        BOOLEAN NOT NULL DEFAULT TRUE,
  valid_from       TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_to         TIMESTAMPTZ,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (rule_type IN ('FORMULA','THRESHOLD','CONTRACT','BEHAVIOUR')),
  CHECK (severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL'))
);

-- Tolerances: what differences are acceptable before flagging (never leak-proof zero).
CREATE TABLE cfg.tolerance_rules (
  tolerance_id     TEXT PRIMARY KEY,                -- 'TOL-SETTLEMENT-INR'
  scope            TEXT NOT NULL,                   -- PAYMENT | SETTLEMENT | FEE | REFUND | BANK | TIMING
  amount_tolerance NUMERIC(18,4) NOT NULL,          -- absolute INR allowance
  pct_tolerance    NUMERIC(8,5)  NOT NULL,          -- relative allowance (0.00100 = 0.1%)
  time_tolerance   INTERVAL,                        -- timing allowance
  currency         TEXT NOT NULL DEFAULT 'INR',
  is_active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (amount_tolerance >= 0 AND pct_tolerance >= 0),
  CHECK (scope IN ('PAYMENT','SETTLEMENT','FEE','REFUND','BANK','TIMING'))
);

-- Deadlines / SLA: when a temporary difference becomes a permanent claim.
CREATE TABLE cfg.sla_rules (
  sla_rule_id      TEXT PRIMARY KEY,                -- 'SLA-SETTLEMENT-T3'
  scope            TEXT NOT NULL,                   -- SETTLEMENT | BANK_CREDIT | DISPUTE | CHARGEBACK | RECEIVABLE | SUBSCRIPTION_RETRY
  reference_days   INTEGER NOT NULL,                -- contractual net days (e.g. T+3)
  grace_days       INTEGER NOT NULL DEFAULT 2,      -- operational grace before escalation
  hard_deadline_days INTEGER NOT NULL,              -- after this, recovery window closes
  description      TEXT,
  is_active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (reference_days >= 0 AND grace_days >= 0 AND hard_deadline_days >= reference_days + grace_days)
);

-- Recovery policies: bounded autonomy per leak category and amount band.
CREATE TABLE cfg.recovery_policies (
  policy_id        TEXT PRIMARY KEY,                -- 'RP-SETTLEMENT-STD'
  category         TEXT NOT NULL,                   -- leak category or 'DEFAULT'
  min_amount       NUMERIC(18,4) NOT NULL DEFAULT 0,
  max_amount       NUMERIC(18,4),                   -- NULL = no cap
  allowed_actions  TEXT[] NOT NULL,                 -- {'DRAFT_DISPUTE','CREATE_DISPUTE',...}
  auto_approve_below NUMERIC(18,4) NOT NULL DEFAULT 0,  -- below this amount L2 actions run without human gate
  requires_evidence TEXT[] NOT NULL DEFAULT '{}',   -- evidence kinds required before ACTION_READY
  max_attempts     INTEGER NOT NULL DEFAULT 3,
  escalation_after_attempts INTEGER NOT NULL DEFAULT 2,
  deadline_days    INTEGER NOT NULL DEFAULT 30,
  is_active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (min_amount >= 0),
  CHECK (max_amount IS NULL OR max_amount >= min_amount)
);

-- Agent tool registry: schemas + risk classification + audit contract.
CREATE TABLE ops.agent_tools (
  tool_id          TEXT PRIMARY KEY,                -- 'get_order'
  tool_name        TEXT NOT NULL,
  tool_class       TEXT NOT NULL,                  -- READ | ANALYSIS | ACTION | VERIFICATION
  risk_level       ops.tool_risk NOT NULL,
  input_schema     JSONB NOT NULL,                  -- JSON Schema
  output_schema    JSONB NOT NULL,
  allowed_actors   TEXT[] NOT NULL DEFAULT '{AGENT,HUMAN}', -- AGENT | HUMAN | SERVICE
  side_effects     TEXT[] NOT NULL DEFAULT '{}',
  idempotency_key  TEXT,                           -- how to make it idempotent (e.g. case_id+action_type)
  failure_behavior TEXT NOT NULL,                  -- description of on-failure semantics
  audit_required   BOOLEAN NOT NULL DEFAULT TRUE,
  is_active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (tool_class IN ('READ','ANALYSIS','ACTION','VERIFICATION'))
);
COMMENT ON TABLE ops.agent_tools IS 'Every callable the agent may use; registry is the single source of tool truth.';

-- ===================================================== INGESTION (raw) =====

-- One row per ingest run of one connector (file pull, API page, webhook batch).
CREATE TABLE raw.ingestion_batches (
  batch_id         TEXT PRIMARY KEY,                -- 'B-2025-01-15-RAZORPAY-001'
  connector_id     TEXT NOT NULL REFERENCES cfg.source_connectors(connector_id),
  source_system    TEXT NOT NULL,
  entity          TEXT NOT NULL,                   -- payments | orders | settlements ...
  schema_version_id TEXT NOT NULL REFERENCES cfg.schema_versions(schema_version_id),
  batch_type       TEXT NOT NULL DEFAULT 'INCREMENTAL',  -- FULL | INCREMENTAL | WEBHOOK
  record_count    INTEGER NOT NULL DEFAULT 0,
  valid_count      INTEGER NOT NULL DEFAULT 0,
  quarantined_count INTEGER NOT NULL DEFAULT 0,
  rejected_count   INTEGER NOT NULL DEFAULT 0,
  checksum         TEXT,                           -- sha256 of source payload file
  started_at       TIMESTAMPTZ NOT NULL,
  completed_at     TIMESTAMPTZ,
  status           TEXT NOT NULL DEFAULT 'RUNNING', -- RUNNING | COMPLETED | FAILED | PARTIAL
  error_summary    TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (batch_type IN ('FULL','INCREMENTAL','WEBHOOK')),
  CHECK (status IN ('RUNNING','COMPLETED','FAILED','PARTIAL')),
  CHECK (valid_count + quarantined_count + rejected_count <= record_count)
);

-- Immutable raw payload store: never discard source evidence.
CREATE TABLE raw.raw_source_records (
  raw_record_id    TEXT PRIMARY KEY,                -- 'RAW-000001'
  batch_id         TEXT NOT NULL REFERENCES raw.ingestion_batches(batch_id),
  source_system    TEXT NOT NULL,
  entity           TEXT NOT NULL,
  source_record_id TEXT NOT NULL,                   -- ID in the source system (razorpay payment id)
  event_timestamp  TIMESTAMPTZ NOT NULL,            -- when it happened at source
  ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload          JSONB NOT NULL,                  -- verbatim source payload
  payload_sha256   TEXT NOT NULL,                   -- integrity hash
  schema_version_id TEXT NOT NULL REFERENCES cfg.schema_versions(schema_version_id),
  parser_version   TEXT NOT NULL,
  normalizer_version TEXT NOT NULL,
  validation_status raw.validation_status NOT NULL DEFAULT 'VALID',
  UNIQUE (source_system, entity, source_record_id),
  CHECK (length(payload_sha256) = 64)
);
CREATE INDEX idx_raw_payload_lookup ON raw.raw_source_records (batch_id);
CREATE INDEX idx_raw_sr_entity_time ON raw.raw_source_records (source_system, entity, event_timestamp);

-- Quarantined records: failed validation, with reason + remediation.
CREATE TABLE raw.quarantine_records (
  quarantine_id   TEXT PRIMARY KEY,                 -- 'Q-000001'
  raw_record_id   TEXT NOT NULL REFERENCES raw.raw_source_records(raw_record_id),
  batch_id        TEXT NOT NULL REFERENCES raw.ingestion_batches(batch_id),
  error_code      TEXT NOT NULL,                    -- DUP_ID | MISSING_ID | INVALID_AMOUNT | ...
  error_reason    TEXT NOT NULL,
  severity        TEXT NOT NULL DEFAULT 'ERROR',    -- ERROR | WARNING
  remediation     TEXT,                            -- suggested fix path
  resolved        BOOLEAN NOT NULL DEFAULT FALSE,
  resolved_at     TIMESTAMPTZ,
  resolved_by     TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (severity IN ('ERROR','WARNING'))
);
CREATE INDEX idx_quarantine_open ON raw.quarantine_records (resolved) WHERE NOT resolved;

-- ================================================== CANONICAL (core) ======

-- Customer master (from commerce system; MVP: referenced by orders).
CREATE TABLE core.customers (
  customer_id     TEXT PRIMARY KEY,                -- 'CUS-1001'
  name            TEXT NOT NULL,
  email           TEXT NOT NULL,
  phone           TEXT,
  source_system   TEXT NOT NULL DEFAULT 'SHOPIFY',
  source_record_id TEXT NOT NULL,
  ingestion_batch_id TEXT REFERENCES raw.ingestion_batches(batch_id),
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_record_id)
);

-- Orders: the commerce root of the transaction graph.
CREATE TABLE core.orders (
  order_id        TEXT PRIMARY KEY,                -- 'ORD-1001' (canonical); source: Shopify #1001
  customer_id     TEXT REFERENCES core.customers(customer_id),
  order_number    TEXT NOT NULL,                   -- Shopify order number '#1001'
  source_system   TEXT NOT NULL DEFAULT 'SHOPIFY',
  source_record_id TEXT NOT NULL,
  gateway_order_id TEXT,                           -- razorpay order id (identity link)
  order_date      TIMESTAMPTZ NOT NULL,
  status          TEXT NOT NULL,                   -- PENDING|PAID|PARTIALLY_PAID|REFUNDED|CANCELLED|ABANDONED
  currency        TEXT NOT NULL DEFAULT 'INR',
  gross_amount    NUMERIC(18,4) NOT NULL,          -- order value incl. taxes, excl. shipping (MVP: total)
  tax_amount      NUMERIC(18,4) NOT NULL DEFAULT 0,-- GST on order value (output tax)
  shipping_amount NUMERIC(18,4) NOT NULL DEFAULT 0,
  discount_amount NUMERIC(18,4) NOT NULL DEFAULT 0,
  net_amount      NUMERIC(18,4) NOT NULL,          -- what customer should pay (gross - discount + shipping)
  payment_method  TEXT,                            -- CARD|NETBANKING|UPI|WALLET|EMI
  financial_status TEXT NOT NULL DEFAULT 'PENDING',-- commerce financial status
  ingestion_batch_id TEXT REFERENCES raw.ingestion_batches(batch_id),
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_record_id),
  CHECK (gross_amount >= 0 AND net_amount >= 0 AND tax_amount >= 0),
  CHECK (status IN ('PENDING','PAID','PARTIALLY_PAID','REFUNDED','CANCELLED','ABANDONED')),
  CHECK (financial_status IN ('PENDING','AUTHORIZED','PAID','PARTIALLY_REFUNDED','REFUNDED','VOIDED','ABANDONED'))
);
CREATE INDEX idx_orders_customer ON core.orders (customer_id);
CREATE INDEX idx_orders_date ON core.orders (order_date);
CREATE INDEX idx_orders_gateway ON core.orders (gateway_order_id);

-- Payments: gateway capture events (Razorpay).
CREATE TABLE core.payments (
  payment_id      TEXT PRIMARY KEY,                -- 'PAY-1001' (canonical); source: razorpay pay_XXX
  order_id        TEXT NOT NULL REFERENCES core.orders(order_id),
  gateway_payment_id TEXT NOT NULL,                -- 'pay_abc123' raw gateway id
  gateway_order_id  TEXT NOT NULL,                -- 'order_abc123'
  source_system   TEXT NOT NULL DEFAULT 'RAZORPAY',
  source_record_id TEXT NOT NULL,
  status          TEXT NOT NULL,                   -- CREATED|AUTHORIZED|CAPTURED|FAILED|REFUNDED|PARTIALLY_REFUNDED|DISPUTE
  method          TEXT NOT NULL,                   -- CARD|NETBANKING|UPI|WALLET|EMI
  instrument_brand TEXT,                           -- VISA|RUPAY|...
  currency        TEXT NOT NULL DEFAULT 'INR',
  amount          NUMERIC(18,4) NOT NULL,          -- amount charged to customer
  amount_authorized NUMERIC(18,4),
  captured_at     TIMESTAMPTZ,                     -- when money moved at gateway
  fee_amount      NUMERIC(18,4),                   -- gateway-reported fee (filled by gateway_fees if reported)
  tax_on_fee      NUMERIC(18,4),                   -- gateway-reported GST on fee
  settled_amount  NUMERIC(18,4),                   -- gateway-reported settled to bank (actual)
  acquirer_data   JSONB,
  webhook_payload JSONB,                           -- last webhook state
  ingestion_batch_id TEXT REFERENCES raw.ingestion_batches(batch_id),
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_record_id),
  UNIQUE (gateway_payment_id),
  CHECK (amount > 0),
  CHECK (status IN ('CREATED','AUTHORIZED','CAPTURED','FAILED','REFUNDED','PARTIALLY_REFUNDED','DISPUTE')),
  CHECK (method IN ('CARD','NETBANKING','UPI','WALLET','EMI')),
  CHECK (fee_amount IS NULL OR fee_amount >= 0)
);
CREATE INDEX idx_payments_order ON core.payments (order_id);
CREATE INDEX idx_payments_gateway_order ON core.payments (gateway_order_id);
CREATE INDEX idx_payments_captured ON core.payments (captured_at);
CREATE INDEX idx_payments_status ON core.payments (status);

-- Refunds: gateway refund events, tie to payment.
CREATE TABLE core.refunds (
  refund_id       TEXT PRIMARY KEY,                -- 'REF-1001'
  payment_id      TEXT NOT NULL REFERENCES core.payments(payment_id),
  order_id        TEXT NOT NULL REFERENCES core.orders(order_id),
  gateway_refund_id TEXT NOT NULL,
  source_system   TEXT NOT NULL DEFAULT 'RAZORPAY',
  source_record_id TEXT NOT NULL,
  status          TEXT NOT NULL,                   -- INITIATED|PROCESSED|FAILED|CANCELLED
  amount          NUMERIC(18,4) NOT NULL,
  speed           TEXT DEFAULT 'NORMAL',           -- NORMAL|OPTIMUM|IMMEDIATE
  refund_reason   TEXT,
  processed_at    TIMESTAMPTZ,
  bank_reference  TEXT,                            -- refund UTR if any
  ingestion_batch_id TEXT REFERENCES raw.ingestion_batches(batch_id),
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_record_id),
  UNIQUE (gateway_refund_id),
  CHECK (amount > 0),
  CHECK (status IN ('INITIATED','PROCESSED','FAILED','CANCELLED'))
);
CREATE INDEX idx_refunds_payment ON core.refunds (payment_id);
CREATE INDEX idx_refunds_order ON core.refunds (order_id);
CREATE INDEX idx_refunds_processed ON core.refunds (processed_at);

-- Gateway fees: fee line items per payment (derived from gateway reporting).
-- Contract: payments captured exactly once; gateway_fees rows are 1..N per payment
-- (N>1 happens on adjustment events; the engine must handle 1:N here).
CREATE TABLE core.gateway_fees (
  fee_id          TEXT PRIMARY KEY,                -- 'FEE-1001'
  payment_id      TEXT NOT NULL REFERENCES core.payments(payment_id),
  order_id        TEXT NOT NULL REFERENCES core.orders(order_id),
  source_system   TEXT NOT NULL DEFAULT 'RAZORPAY',
  source_record_id TEXT NOT NULL,
  fee_type        TEXT NOT NULL DEFAULT 'MDR',     -- MDR | FIXED | ADJUSTMENT | LATE_CAPTURE | EMI
  amount          NUMERIC(18,4) NOT NULL,          -- fee charged
  tax_amount      NUMERIC(18,4) NOT NULL DEFAULT 0, -- GST on fee
  rate_card_id    TEXT REFERENCES cfg.rate_cards(rate_card_id),  -- applied expectation basis
  fee_event_at    TIMESTAMPTZ NOT NULL,
  reversal_of_fee_id TEXT REFERENCES core.gateway_fees(fee_id), -- adjustments may reverse earlier fees
  settlement_id   TEXT,                            -- settlement that carried this fee (set later)
  notes           TEXT,
  ingestion_batch_id TEXT REFERENCES raw.ingestion_batches(batch_id),
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_record_id),
  CHECK (fee_type IN ('MDR','FIXED','ADJUSTMENT','LATE_CAPTURE','EMI')),
  CHECK (amount <> 0)
);
CREATE INDEX idx_fees_payment ON core.gateway_fees (payment_id);
CREATE INDEX idx_fees_order ON core.gateway_fees (order_id);
CREATE INDEX idx_fees_event_time ON core.gateway_fees (fee_event_at);

-- Settlements: gateway-to-bank payout credits (one payment may span batches).
CREATE TABLE core.settlements (
  settlement_id   TEXT PRIMARY KEY,                -- 'SET-1001' (canonical); source: set_XXX
  gateway_settlement_id TEXT NOT NULL,
  payment_id      TEXT NOT NULL REFERENCES core.payments(payment_id),
  order_id        TEXT NOT NULL REFERENCES core.orders(order_id),
  source_system   TEXT NOT NULL DEFAULT 'RAZORPAY',
  source_record_id TEXT NOT NULL,
  utr             TEXT,                            -- bank unique transaction reference
  status          TEXT NOT NULL,                   -- PENDING|IN_PROGRESS|PROCESSED|REVERSED|ON_HOLD|CANCELLED
  settlement_type TEXT NOT NULL DEFAULT 'SETTLEMENT', -- SETTLEMENT | ADJUSTMENT | REFUND_REVERSAL
  amount          NUMERIC(18,4) NOT NULL,          -- credited toward bank (gross of fee deduction)
  fee_deducted    NUMERIC(18,4) NOT NULL DEFAULT 0,
  tax_deducted    NUMERIC(18,4) NOT NULL DEFAULT 0,
  opening_balance NUMERIC(18,4),
  closing_balance NUMERIC(18,4),
  settled_at      TIMESTAMPTZ NOT NULL,            -- when gateway claims settlement executed
  expected_credit_date DATE,                       -- T+n contractual date
  ingestion_batch_id TEXT REFERENCES raw.ingestion_batches(batch_id),
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_record_id),
  UNIQUE (gateway_settlement_id),
  CHECK (amount <> 0),
  CHECK (status IN ('PENDING','IN_PROGRESS','PROCESSED','REVERSED','ON_HOLD','CANCELLED')),
  CHECK (settlement_type IN ('SETTLEMENT','ADJUSTMENT','REFUND_REVERSAL'))
);
CREATE INDEX idx_settlements_payment ON core.settlements (payment_id);
CREATE INDEX idx_settlements_order ON core.settlements (order_id);
CREATE INDEX idx_settlements_utr ON core.settlements (utr);
CREATE INDEX idx_settlements_date ON core.settlements (settled_at);

-- Bank transactions: statement lines from the merchant bank account.
CREATE TABLE core.bank_transactions (
  bank_txn_id     TEXT PRIMARY KEY,                -- 'BNK-1001'
  utr             TEXT NOT NULL,                   -- bank reference; links settlements.utr
  source_system   TEXT NOT NULL DEFAULT 'BANK',
  source_record_id TEXT NOT NULL,
  txn_type        TEXT NOT NULL,                   -- CREDIT | DEBIT
  direction       TEXT NOT NULL,                   -- IN | OUT
  amount          NUMERIC(18,4) NOT NULL,
  currency        TEXT NOT NULL DEFAULT 'INR',
  value_date      DATE NOT NULL,
  txn_timestamp   TIMESTAMPTZ NOT NULL,
  narration      TEXT,
  counterparty    TEXT,                            -- 'RAZORPAY SOFTWARE PVT LTD'
  matched_settlement_id TEXT,                     -- filled by identity resolution
  ingestion_batch_id TEXT REFERENCES raw.ingestion_batches(batch_id),
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_record_id),
  UNIQUE (utr, value_date, amount),
  CHECK (amount <> 0),
  CHECK (txn_type IN ('CREDIT','DEBIT')),
  CHECK (direction IN ('IN','OUT'))
);
CREATE INDEX idx_bank_utr ON core.bank_transactions (utr);
CREATE INDEX idx_bank_value_date ON core.bank_transactions (value_date);
CREATE INDEX idx_bank_matched ON core.bank_transactions (matched_settlement_id);

-- Invoices: tax invoices issued for orders.
CREATE TABLE core.invoices (
  invoice_id      TEXT PRIMARY KEY,                -- 'INV-1001'
  order_id        TEXT NOT NULL REFERENCES core.orders(order_id),
  customer_id     TEXT REFERENCES core.customers(customer_id),
  invoice_number  TEXT NOT NULL,                   -- 'INV/2025/1001'
  source_system   TEXT NOT NULL DEFAULT 'ACCOUNTING',
  source_record_id TEXT NOT NULL,
  status          TEXT NOT NULL,                   -- DRAFT|ISSUED|PAID|PARTIALLY_PAID|CANCELLED
  issue_date      DATE NOT NULL,
  due_date        DATE NOT NULL,
  taxable_value   NUMERIC(18,4) NOT NULL,
  gst_rate        NUMERIC(8,5)  NOT NULL DEFAULT 0.18,
  gst_amount      NUMERIC(18,4) NOT NULL,
  total_amount    NUMERIC(18,4) NOT NULL,          -- taxable + gst
  place_of_supply TEXT,                            -- state code for GST
  isd_document    BOOLEAN NOT NULL DEFAULT FALSE,  -- Input Service Distributor flag
  ingestion_batch_id TEXT REFERENCES raw.ingestion_batches(batch_id),
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_record_id),
  UNIQUE (invoice_number),
  CHECK (taxable_value >= 0 AND gst_amount >= 0 AND total_amount >= 0),
  CHECK (status IN ('DRAFT','ISSUED','PAID','PARTIALLY_PAID','CANCELLED')),
  CHECK (abs(total_amount - (taxable_value + gst_amount)) < 0.01)
);
CREATE INDEX idx_invoices_order ON core.invoices (order_id);
CREATE INDEX idx_invoices_customer ON core.invoices (customer_id);
CREATE INDEX idx_invoices_due ON core.invoices (due_date);

-- GST records: tax lines per invoice — ITC evidence (review workflow, NOT auto-recovery).
CREATE TABLE core.gst_records (
  gst_record_id   TEXT PRIMARY KEY,                -- 'GST-1001'
  invoice_id      TEXT NOT NULL REFERENCES core.invoices(invoice_id),
  order_id        TEXT NOT NULL REFERENCES core.orders(order_id),  -- denormalized for graph traversal
  source_system   TEXT NOT NULL DEFAULT 'ACCOUNTING',
  source_record_id TEXT NOT NULL,
  gst_type        TEXT NOT NULL,                   -- OUTPUT | INPUT (ITC) | RCM
  return_period   TEXT NOT NULL,                   -- '2025-01' GSTR month
  gstin           TEXT,                            -- counterparty GSTIN
  taxable_value   NUMERIC(18,4) NOT NULL,
  igst            NUMERIC(18,4) NOT NULL DEFAULT 0,
  cgst            NUMERIC(18,4) NOT NULL DEFAULT 0,
  sgst            NUMERIC(18,4) NOT NULL DEFAULT 0,
  cess            NUMERIC(18,4) NOT NULL DEFAULT 0,
  total_tax       NUMERIC(18,4) NOT NULL,
  itc_eligible    BOOLEAN NOT NULL DEFAULT TRUE,
  itc_matched     BOOLEAN,                         -- ITC matched to supplier GSTR-2B
  itc_matched_period TEXT,                        -- period in which ITC appears in 2B
  filed_status    TEXT NOT NULL DEFAULT 'NOT_FILED',-- NOT_FILED|FILED|RECONCILED|MISMATCH
  remarks         TEXT,
  ingestion_batch_id TEXT REFERENCES raw.ingestion_batches(batch_id),
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_record_id),
  CHECK (gst_type IN ('OUTPUT','INPUT','RCM')),
  CHECK (taxable_value >= 0 AND total_tax >= 0),
  CHECK (abs(total_tax - (igst + cgst + sgst + cess)) < 0.01),
  CHECK (filed_status IN ('NOT_FILED','FILED','RECONCILED','MISMATCH'))
);
CREATE INDEX idx_gst_invoice ON core.gst_records (invoice_id);
CREATE INDEX idx_gst_order ON core.gst_records (order_id);
CREATE INDEX idx_gst_period ON core.gst_records (return_period);

-- ============================================== PHASE 2 CANONICAL (core) ===

-- Marketplace deductions (P2): platform-level charges against settlements.
CREATE TABLE core.marketplace_deductions (
  deduction_id    TEXT PRIMARY KEY,                -- 'MKT-1001'
  order_id        TEXT NOT NULL REFERENCES core.orders(order_id),
  settlement_id   TEXT REFERENCES core.settlements(settlement_id),
  source_system   TEXT NOT NULL DEFAULT 'MARKETPLACE',
  source_record_id TEXT NOT NULL,
  deduction_type  TEXT NOT NULL,                   -- COMMISSION | SHIPPING | AD_SPEND | CLAIM | PENALTY | SERVICE_TAX
  amount          NUMERIC(18,4) NOT NULL,
  description     TEXT,
  deduction_date  TIMESTAMPTZ NOT NULL,
  dispute_window_days INTEGER NOT NULL DEFAULT 30, -- contractual window to dispute
  status          TEXT NOT NULL DEFAULT 'APPLIED', -- APPLIED | DISPUTED | REFUNDED | ACCEPTED
  reversal_ref    TEXT,
  ingestion_batch_id TEXT REFERENCES raw.ingestion_batches(batch_id),
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_record_id),
  CHECK (amount <> 0),
  CHECK (deduction_type IN ('COMMISSION','SHIPPING','AD_SPEND','CLAIM','PENALTY','SERVICE_TAX')),
  CHECK (status IN ('APPLIED','DISPUTED','REFUNDED','ACCEPTED'))
);
CREATE INDEX idx_mkt_order ON core.marketplace_deductions (order_id);
CREATE INDEX idx_mkt_settlement ON core.marketplace_deductions (settlement_id);

-- Subscriptions (P2): recurring billing plans per customer.
CREATE TABLE core.subscriptions (
  subscription_id TEXT PRIMARY KEY,                -- 'SUB-1001'
  customer_id     TEXT NOT NULL REFERENCES core.customers(customer_id),
  source_system   TEXT NOT NULL DEFAULT 'APPLICATION',
  source_record_id TEXT NOT NULL,
  plan_name       TEXT NOT NULL,
  billing_cycle   TEXT NOT NULL,                   -- MONTHLY | QUARTERLY | ANNUAL
  amount          NUMERIC(18,4) NOT NULL,
  currency        TEXT NOT NULL DEFAULT 'INR',
  status          TEXT NOT NULL,                   -- ACTIVE|PAST_DUE|CANCELLED|EXPIRED|PAUSED
  started_at      TIMESTAMPTZ NOT NULL,
  current_period_start TIMESTAMPTZ NOT NULL,
  current_period_end   TIMESTAMPTZ NOT NULL,
  next_billing_at TIMESTAMPTZ,
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  last_order_id   TEXT REFERENCES core.orders(order_id), -- most recent renewal order
  ingestion_batch_id TEXT REFERENCES raw.ingestion_batches(batch_id),
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_record_id),
  CHECK (amount > 0),
  CHECK (billing_cycle IN ('MONTHLY','QUARTERLY','ANNUAL')),
  CHECK (status IN ('ACTIVE','PAST_DUE','CANCELLED','EXPIRED','PAUSED'))
);
CREATE INDEX idx_sub_customer ON core.subscriptions (customer_id);
CREATE INDEX idx_sub_next_billing ON core.subscriptions (next_billing_at);

-- Customer events (P2): lifecycle event log (appends only).
CREATE TABLE core.customer_events (
  event_id        TEXT PRIMARY KEY,                -- 'CEV-1001'
  customer_id     TEXT NOT NULL REFERENCES core.customers(customer_id),
  order_id        TEXT REFERENCES core.orders(order_id),
  event_type      TEXT NOT NULL,                   -- SIGNUP|LOGIN|CHECKOUT_STARTED|CHECKOUT_ABANDONED|PAYMENT_FAILED|SUBSCRIPTION_RENEWED|CHURN_RISK
  event_timestamp TIMESTAMPTZ NOT NULL,
  properties      JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_system   TEXT NOT NULL DEFAULT 'SHOPIFY',
  source_record_id TEXT,
  ingestion_batch_id TEXT REFERENCES raw.ingestion_batches(batch_id),
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (event_type IN ('SIGNUP','LOGIN','CHECKOUT_STARTED','CHECKOUT_ABANDONED','PAYMENT_FAILED','SUBSCRIPTION_RENEWED','CHURN_RISK'))
);
CREATE INDEX idx_cev_customer ON core.customer_events (customer_id);
CREATE INDEX idx_cev_order ON core.customer_events (order_id);
CREATE INDEX idx_cev_time ON core.customer_events (event_timestamp);

-- ============================================== PHASE 3 CANONICAL (core) ===

-- Receivables (P3): outstanding AR per invoice.
CREATE TABLE core.receivables (
  receivable_id   TEXT PRIMARY KEY,                -- 'AR-1001'
  invoice_id      TEXT NOT NULL REFERENCES core.invoices(invoice_id),
  order_id        TEXT NOT NULL REFERENCES core.orders(order_id),
  customer_id     TEXT NOT NULL REFERENCES core.customers(customer_id),
  source_system   TEXT NOT NULL DEFAULT 'ACCOUNTING',
  source_record_id TEXT NOT NULL,
  amount_due      NUMERIC(18,4) NOT NULL,
  amount_paid     NUMERIC(18,4) NOT NULL DEFAULT 0,
  days_outstanding INTEGER NOT NULL DEFAULT 0,
  aging_bucket    TEXT NOT NULL,                   -- CURRENT|1-30|31-60|61-90|90+
  due_date        DATE NOT NULL,
  status          TEXT NOT NULL,                   -- OPEN | PAID | OVERDUE | WRITE_OFF | DISPUTED
  last_reminder_at TIMESTAMPTZ,
  ingestion_batch_id TEXT REFERENCES raw.ingestion_batches(batch_id),
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_record_id),
  CHECK (amount_due >= 0 AND amount_paid >= 0),
  CHECK (aging_bucket IN ('CURRENT','1-30','31-60','61-90','90+')),
  CHECK (status IN ('OPEN','PAID','OVERDUE','WRITE_OFF','DISPUTED'))
);
CREATE INDEX idx_ar_invoice ON core.receivables (invoice_id);
CREATE INDEX idx_ar_customer ON core.receivables (customer_id);
CREATE INDEX idx_ar_status ON core.receivables (status, due_date);

-- Chargebacks (P3): card-network disputes against payments.
CREATE TABLE core.chargebacks (
  chargeback_id   TEXT PRIMARY KEY,                -- 'CBK-1001'
  payment_id      TEXT NOT NULL REFERENCES core.payments(payment_id),
  order_id        TEXT NOT NULL REFERENCES core.orders(order_id),
  source_system   TEXT NOT NULL DEFAULT 'RAZORPAY',
  source_record_id TEXT NOT NULL,
  reason_code     TEXT NOT NULL,                   -- e.g. '10.4' fraud; '13.1' merchandise
  reason_description TEXT,
  disputed_amount NUMERIC(18,4) NOT NULL,
  currency        TEXT NOT NULL DEFAULT 'INR',
  status          TEXT NOT NULL,                   -- OPEN | WON | LOST | ACCEPTED | UNDER_REVIEW
  opened_at       TIMESTAMPTZ NOT NULL,
  respond_by      TIMESTAMPTZ NOT NULL,            -- network deadline
  resolved_at     TIMESTAMPTZ,
  evidence_bundle JSONB,                           -- packet refs
  ingestion_batch_id TEXT REFERENCES raw.ingestion_batches(batch_id),
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_record_id),
  CHECK (disputed_amount > 0),
  CHECK (status IN ('OPEN','WON','LOST','ACCEPTED','UNDER_REVIEW'))
);
CREATE INDEX idx_cbk_payment ON core.chargebacks (payment_id);
CREATE INDEX idx_cbk_status ON core.chargebacks (status, respond_by);

-- ==================================================== DERIVED (ops) =======

-- Identity matches: cross-system linkage with confidence + method.
CREATE TABLE ops.identity_matches (
  identity_match_id TEXT PRIMARY KEY,              -- 'IDM-1001'
  entity_type      TEXT NOT NULL,                  -- ORDER|PAYMENT|SETTLEMENT|BANK_TXN|INVOICE|GST|REFUND|FEE
  left_system      TEXT NOT NULL,
  left_entity      TEXT NOT NULL,
  left_record_id   TEXT NOT NULL,
  right_system     TEXT NOT NULL,
  right_entity     TEXT NOT NULL,
  right_record_id  TEXT NOT NULL,
  match_method     ops.match_method NOT NULL,
  confidence       NUMERIC(5,2) NOT NULL,          -- 0.00-1.00
  status           ops.identity_status NOT NULL,
  conflict_detail  JSONB,                         -- conflicting identifiers when status=CONFLICT
  matched_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewed_by      TEXT,
  reviewed_at      TIMESTAMPTZ,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (confidence >= 0 AND confidence <= 1),
  CHECK (entity_type IN ('ORDER','PAYMENT','SETTLEMENT','BANK_TXN','INVOICE','GST','REFUND','FEE','DEDUCTION','RECEIVABLE','CHARGEBACK','SUBSCRIPTION')),
  UNIQUE (left_system, left_entity, left_record_id, right_system, right_entity, right_record_id)
);
CREATE INDEX idx_idm_left ON ops.identity_matches (left_entity, left_record_id);
CREATE INDEX idx_idm_right ON ops.identity_matches (right_entity, right_record_id);
CREATE INDEX idx_idm_status ON ops.identity_matches (status);

-- Reconciliation results: pairwise engine output. Append per run (reconcile_run_id).
CREATE TABLE ops.reconciliation_results (
  recon_result_id TEXT PRIMARY KEY,                -- 'RCN-1001'
  reconcile_run_id TEXT NOT NULL,                  -- 'RUN-2025-01-20-01' groups a pass
  direction       ops.recon_direction NOT NULL,
  left_entity     TEXT NOT NULL,                   -- 'core.orders'
  left_record_id  TEXT NOT NULL,
  right_entity    TEXT NOT NULL,                  -- 'core.settlements'
  right_record_id TEXT,
  status          ops.recon_status NOT NULL,
  expected_amount NUMERIC(18,4) NOT NULL,
  actual_amount   NUMERIC(18,4),
  variance        NUMERIC(18,4),                   -- expected - actual
  explained_variance NUMERIC(18,4) NOT NULL DEFAULT 0,  -- legitimate + timing + adjustment
  unexplained_variance NUMERIC(18,4) NOT NULL DEFAULT 0,
  variance_class  ops.data_class,                 -- LEGITIMATE|TIMING|ADJUSTMENT|LEAKAGE|REVIEW_ONLY
  tolerance_id    TEXT REFERENCES cfg.tolerance_rules(tolerance_id),
  matched_at      TIMESTAMPTZ,
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (variance IS NULL OR abs(variance - (expected_amount - COALESCE(actual_amount,0))) < 0.01),
  CHECK (unexplained_variance <= variance + 0.01 OR variance IS NULL)
);
CREATE INDEX idx_rcn_left ON ops.reconciliation_results (left_entity, left_record_id);
CREATE INDEX idx_rcn_right ON ops.reconciliation_results (right_entity, right_record_id);
CREATE INDEX idx_rcn_run ON ops.reconciliation_results (reconcile_run_id);
CREATE INDEX idx_rcn_status ON ops.reconciliation_results (status);
CREATE INDEX idx_rcn_direction ON ops.reconciliation_results (direction);

-- Evidence records: pointers to facts that back a case (hashed for immutability).
CREATE TABLE ops.evidence_records (
  evidence_id     TEXT PRIMARY KEY,                -- 'EVID-1001'
  case_id         TEXT,                            -- set when bound to a case (FK added after cases)
  recon_result_id TEXT REFERENCES ops.reconciliation_results(recon_result_id),
  evidence_kind   ops.evidence_kind NOT NULL,
  source_system   TEXT NOT NULL,
  source_reference TEXT NOT NULL,                  -- table:pk or raw payload ref
  description     TEXT NOT NULL,
  payload         JSONB,                           -- snapshot of the evidence fact
  payload_sha256  TEXT NOT NULL,                   -- integrity hash
  collected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (length(payload_sha256) = 64)
);
CREATE INDEX idx_evid_case ON ops.evidence_records (case_id);
CREATE INDEX idx_evid_recon ON ops.evidence_records (recon_result_id);

-- Anomaly results: leakage findings from anomaly engine (deterministic first).
CREATE TABLE ops.anomaly_results (
  anomaly_id      TEXT PRIMARY KEY,                -- 'ANM-1001'
  recon_result_id TEXT NOT NULL REFERENCES ops.reconciliation_results(recon_result_id),
  order_id        TEXT REFERENCES core.orders(order_id),
  payment_id      TEXT REFERENCES core.payments(payment_id),
  category        ops.leak_category NOT NULL,
  detection_rule  TEXT NOT NULL,                   -- cfg.financial_rules.rule_id
  detected_amount NUMERIC(18,4) NOT NULL,          -- absolute unexplained variance
  variance_class  ops.data_class NOT NULL,
  severity        TEXT NOT NULL DEFAULT 'MEDIUM',
  explanation     TEXT,                            -- deterministic explanation if any
  candidate_root_causes TEXT[],                   -- deterministic candidates
  detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')),
  CHECK (detected_amount >= 0)
);
CREATE INDEX idx_anm_order ON ops.anomaly_results (order_id);
CREATE INDEX idx_anm_payment ON ops.anomaly_results (payment_id);
CREATE INDEX idx_anm_category ON ops.anomaly_results (category);
CREATE INDEX idx_anm_recon ON ops.anomaly_results (recon_result_id);

-- Recovery cases: the structured object the AI agent consumes (one case = one anomaly).
CREATE TABLE ops.recovery_cases (
  case_id         TEXT PRIMARY KEY,                -- 'CASE-1001'
  anomaly_id      TEXT NOT NULL UNIQUE REFERENCES ops.anomaly_results(anomaly_id),
  order_id        TEXT NOT NULL REFERENCES core.orders(order_id),
  payment_id      TEXT REFERENCES core.payments(payment_id),
  customer_id     TEXT REFERENCES core.customers(customer_id),
  category        ops.leak_category NOT NULL,
  priority        TEXT NOT NULL DEFAULT 'MEDIUM',  -- LOW|MEDIUM|HIGH|URGENT (amount + deadline derived)
  status          ops.case_status NOT NULL DEFAULT 'NEW',
  expected_fee    NUMERIC(18,4),
  expected_tax    NUMERIC(18,4),
  expected_settlement NUMERIC(18,4),
  actual_fee      NUMERIC(18,4),
  actual_tax      NUMERIC(18,4),
  actual_settlement NUMERIC(18,4),
  known_adjustments NUMERIC(18,4) NOT NULL DEFAULT 0,
  refund_status   TEXT,
  recon_status    ops.recon_status,
  potential_leakage NUMERIC(18,4) NOT NULL,       -- = anomaly.detected_amount (unexplained)
  confidence      NUMERIC(5,2) NOT NULL DEFAULT 0.50,
  recoverability_status ops.recoverability_status NOT NULL DEFAULT 'DETECTED',
  potential_recovery NUMERIC(18,4),
  deadline_at     TIMESTAMPTZ,                     -- action deadline from SLA rules
  allowed_actions TEXT[] NOT NULL DEFAULT '{}',   -- from recovery_policies
  approval_required BOOLEAN NOT NULL DEFAULT TRUE,
  opened_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at       TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (priority IN ('LOW','MEDIUM','HIGH','URGENT')),
  CHECK (potential_leakage >= 0),
  CHECK (confidence >= 0 AND confidence <= 1)
);
CREATE INDEX idx_case_order ON ops.recovery_cases (order_id);
CREATE INDEX idx_case_status ON ops.recovery_cases (status);
CREATE INDEX idx_case_category ON ops.recovery_cases (category);
CREATE INDEX idx_case_deadline ON ops.recovery_cases (deadline_at);

-- back-fill evidence FK now that cases exist
ALTER TABLE ops.evidence_records
  ADD CONSTRAINT evidence_case_fk FOREIGN KEY (case_id) REFERENCES ops.recovery_cases(case_id);

-- Recoverability assessments: the formal state machine per case.
CREATE TABLE ops.recoverability_assessments (
  assessment_id  TEXT PRIMARY KEY,                -- 'RCA-1001'
  case_id         TEXT NOT NULL UNIQUE REFERENCES ops.recovery_cases(case_id),
  status          ops.recoverability_status NOT NULL,
  discrepancy_amount NUMERIC(18,4) NOT NULL,
  potentially_recoverable_amount NUMERIC(18,4),
  confidence      NUMERIC(5,2) NOT NULL,
  root_cause      TEXT,                            -- best deterministic candidate at assessment time
  evidence_complete BOOLEAN NOT NULL DEFAULT FALSE,
  evidence_missing TEXT[],
  contractual_basis TEXT,                         -- rule_id / rate_card_id relied on
  tax_review_status TEXT NOT NULL DEFAULT 'NOT_APPLICABLE', -- NOT_APPLICABLE|PENDING|REVIEW|CLEARED
  deadline_at     TIMESTAMPTZ,
  deadline_open   BOOLEAN NOT NULL DEFAULT TRUE,
  recommended_action TEXT,                         -- action_type from tool registry
  assessed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (confidence >= 0 AND confidence <= 1),
  CHECK (tax_review_status IN ('NOT_APPLICABLE','PENDING','REVIEW','CLEARED')),
  CHECK (discrepancy_amount >= 0)
);
CREATE INDEX idx_rca_case ON ops.recoverability_assessments (case_id);
CREATE INDEX idx_rca_status ON ops.recoverability_assessments (status);

-- Recovery actions: what was actually executed (tool invocations with effects).
CREATE TABLE ops.recovery_actions (
  action_id       TEXT PRIMARY KEY,                -- 'ACT-1001'
  case_id         TEXT NOT NULL REFERENCES ops.recovery_cases(case_id),
  tool_id         TEXT NOT NULL REFERENCES ops.agent_tools(tool_id),
  action_type     TEXT NOT NULL,                   -- DISPUTE | DRAFT_DISPUTE | ... (action_type enum values)
  actor           TEXT NOT NULL DEFAULT 'AGENT',   -- AGENT | HUMAN | SERVICE
  status          TEXT NOT NULL DEFAULT 'PLANNED', -- PLANNED|EXECUTED|FAILED|CANCELLED
  risk_level      ops.tool_risk NOT NULL,
  input_payload   JSONB NOT NULL,
  result_payload  JSONB,
  external_ref    TEXT,                            -- dispute id / ticket id at counterparty
  idempotency_key TEXT NOT NULL,
  approval_id     TEXT,                            -- FK added after approvals
  amount          NUMERIC(18,4),
  executed_at     TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (idempotency_key),
  CHECK (actor IN ('AGENT','HUMAN','SERVICE')),
  CHECK (status IN ('PLANNED','EXECUTED','FAILED','CANCELLED'))
);
CREATE INDEX idx_act_case ON ops.recovery_actions (case_id);
CREATE INDEX idx_act_tool ON ops.recovery_actions (tool_id);
CREATE INDEX idx_act_external ON ops.recovery_actions (external_ref);

-- Approvals: human gate records with full state machine.
CREATE TABLE ops.approvals (
  approval_id     TEXT PRIMARY KEY,                -- 'APR-1001'
  case_id         TEXT NOT NULL REFERENCES ops.recovery_cases(case_id),
  action_id       TEXT REFERENCES ops.recovery_actions(action_id),
  risk_level      ops.tool_risk NOT NULL,
  amount          NUMERIC(18,4),
  requested_by    TEXT NOT NULL DEFAULT 'AGENT',
  status          ops.approval_status NOT NULL DEFAULT 'REQUESTED',
  requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_by      TEXT,
  decided_at      TIMESTAMPTZ,
  decision_note   TEXT,
  expires_at      TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (risk_level IN ('L0_READ','L1_DRAFT','L2_REVERSIBLE','L3_FINANCIAL','L4_TAX_LEGAL')::text::ops.tool_risk
         OR TRUE)  -- enum type enforced by column; placeholder for lint
);
ALTER TABLE ops.approvals DROP CONSTRAINT IF EXISTS approvals_check;
CREATE INDEX idx_apr_case ON ops.approvals (case_id);
CREATE INDEX idx_apr_status ON ops.approvals (status);

-- back-fill recovery_actions.approval_id FK
ALTER TABLE ops.recovery_actions
  ADD CONSTRAINT action_approval_fk FOREIGN KEY (approval_id) REFERENCES ops.approvals(approval_id);

-- Case history: append-only timeline per case (every state change).
CREATE TABLE ops.case_history (
  history_id      TEXT PRIMARY KEY,                -- 'CH-1001'
  case_id         TEXT NOT NULL REFERENCES ops.recovery_cases(case_id),
  event_type      TEXT NOT NULL,                   -- CREATED|STATUS_CHANGE|INVESTIGATION_NOTE|PLAN|TOOL_CALL|APPROVAL_REQUEST|APPROVAL_DECISION|VERIFICATION|ESCALATION|COMMENT
  old_status      ops.case_status,
  new_status      ops.case_status,
  actor           TEXT NOT NULL DEFAULT 'AGENT',
  message         TEXT NOT NULL,
  payload         JSONB,
  event_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (event_type IN ('CREATED','STATUS_CHANGE','INVESTIGATION_NOTE','PLAN','TOOL_CALL','APPROVAL_REQUEST','APPROVAL_DECISION','VERIFICATION','ESCALATION','COMMENT'))
);
CREATE INDEX idx_ch_case ON ops.case_history (case_id, event_at);
CREATE INDEX idx_ch_event ON ops.case_history (event_type);

-- Verification events: post-action outcome tracking (append-only).
CREATE TABLE ops.verification_events (
  verification_id TEXT PRIMARY KEY,                -- 'VER-1001'
  action_id       TEXT NOT NULL REFERENCES ops.recovery_actions(action_id),
  case_id         TEXT NOT NULL REFERENCES ops.recovery_cases(case_id),
  status          ops.verification_status NOT NULL,
  check_type      TEXT NOT NULL,                   -- DISPUTE_ID_CREATED|ACTION_ACCEPTED|FINANCIAL_STATUS_CHANGED|SETTLEMENT_CHANGED|BANK_CREDIT_APPEARED|DUPLICATE_CHECK|AMOUNT_RECOVERED
  expected_ref    TEXT,                           -- external ref to verify (dispute id / UTR)
  observed_value  JSONB,
  checked_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (check_type IN ('DISPUTE_ID_CREATED','ACTION_ACCEPTED','FINANCIAL_STATUS_CHANGED','SETTLEMENT_CHANGED','BANK_CREDIT_APPEARED','DUPLICATE_CHECK','AMOUNT_RECOVERED'))
);
CREATE INDEX idx_ver_action ON ops.verification_events (action_id);
CREATE INDEX idx_ver_case ON ops.verification_events (case_id);
CREATE INDEX idx_ver_status ON ops.verification_events (status);

-- Audit ledger: immutable hash-chained event log of EVERY agent/engine action.
-- Chain: row(n).prev_hash = row(n-1 for same case).hash = sha256(canonical row).
CREATE TABLE ops.audit_ledger (
  audit_id        TEXT PRIMARY KEY,                -- 'AUD-1001'
  case_id         TEXT REFERENCES ops.recovery_cases(case_id),
  action_id       TEXT REFERENCES ops.recovery_actions(action_id),
  actor           TEXT NOT NULL,                   -- AGENT | HUMAN | SERVICE | ENGINE
  event_type      TEXT NOT NULL,                   -- full vocabulary in docs; e.g. TOOL_CALL, APPROVAL, STATE_CHANGE
  tool_called     TEXT,
  tool_parameters JSONB,
  tool_result     JSONB,
  input_payload   JSONB,
  decision        TEXT,
  previous_state  TEXT,
  new_state       TEXT,
  amount          NUMERIC(18,4),
  evidence_ids    TEXT[],
  approval_id     TEXT REFERENCES ops.approvals(approval_id),
  correlation_id  TEXT NOT NULL,                   -- run/correlation grouping
  prev_hash       TEXT NOT NULL,                   -- hash chain: '' for first entry per case
  entry_hash      TEXT NOT NULL,                   -- sha256(prev_hash + canonical fields)
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_aud_case ON ops.audit_ledger (case_id, created_at);
CREATE INDEX idx_aud_actor ON ops.audit_ledger (actor);
CREATE INDEX idx_aud_correlation ON ops.audit_ledger (correlation_id);
CREATE INDEX idx_aud_event ON ops.audit_ledger (event_type);

-- ================================================= EVALUATION (eval) ======
-- Evaluator-only plane. The agent runtime role must have NO privileges here:
--   REVOKE ALL ON SCHEMA eval FROM agent_ro;  (see indexes.sql / security notes)

-- Hidden ground truth per generated transaction (NEVER shown to agent).
CREATE TABLE eval.ground_truth (
  gt_id            TEXT PRIMARY KEY,               -- 'GT-1001'
  txn_id           TEXT NOT NULL UNIQUE,          -- master transaction id 'TXN-001' (links generator manifest)
  order_id         TEXT NOT NULL,                  -- links to core.orders for the evaluator join
  payment_id       TEXT,
  has_anomaly      BOOLEAN NOT NULL DEFAULT FALSE,
  actual_problem   TEXT,                           -- human description
  anomaly_type     TEXT,                           -- injected anomaly code (LEAK-SETTLEMENT-SHORT etc.)
  injection_detail JSONB,                          -- what exactly was perturbed
  true_expected_amount NUMERIC(18,4),
  true_actual_amount   NUMERIC(18,4),
  true_leakage_amount  NUMERIC(18,4),
  true_recoverable     BOOLEAN,
  true_recovery_amount NUMERIC(18,4),
  true_root_cause      TEXT,
  true_required_evidence TEXT[],
  true_best_action     TEXT,
  true_deadline        DATE,
  true_should_escalate BOOLEAN,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_gt_order ON eval.ground_truth (order_id);
CREATE INDEX idx_gt_anomaly ON eval.ground_truth (has_anomaly, anomaly_type);

-- Evaluation runs + per-case scores (evaluator output).
CREATE TABLE eval.evaluation_runs (
  eval_run_id     TEXT PRIMARY KEY,                -- 'EVAL-2025-01-20-01'
  run_type        TEXT NOT NULL,                   -- DETECTION | RECOVERY | FULL
  started_at      TIMESTAMPTZ NOT NULL,
  completed_at    TIMESTAMPTZ,
  dataset_scope   TEXT NOT NULL,                   -- 'DEV-1000' etc.
  config          JSONB,
  summary         JSONB                            -- precision/recall/FPR/amount-accuracy...
);
CREATE TABLE eval.evaluation_case_scores (
  eval_run_id     TEXT NOT NULL REFERENCES eval.evaluation_runs(eval_run_id),
  case_id         TEXT,                            -- agent case if detected
  gt_id           TEXT NOT NULL REFERENCES eval.ground_truth(gt_id),
  detected        BOOLEAN NOT NULL,
  category_correct BOOLEAN,
  amount_delta    NUMERIC(18,4),                   -- agent_leakage - true_leakage
  root_cause_correct BOOLEAN,
  action_correct  BOOLEAN,
  recovered_amount NUMERIC(18,4),
  score           JSONB,
  PRIMARY KEY (eval_run_id, gt_id)
);

-- ============================================================================
-- END schema.sql — continue with seed.sql (config data), functions.sql,
-- views.sql, indexes.sql.
-- ============================================================================
