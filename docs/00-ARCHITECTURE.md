# AI Revenue Leakage Detection, Diagnosis & Autonomous Recovery Agent
## Master Data Architecture Document

PostgreSQL 15+. Money columns: `NUMERIC(18,4)`. Timestamps: `TIMESTAMPTZ` (UTC). Currency: INR (MVP).

This document governs design rules. The executable truth is `database/schema.sql`, `database/views.sql`, `database/functions.sql`, `database/seed/*.sql`. The full 37-section design response is delivered in the session answer and mirrored across `docs/`.

---

## 1. Architecture backbone (authoritative)

```
DATA SOURCES → INGESTION/CONNECTOR → NORMALIZATION → IDENTITY RESOLVER
→ TRANSACTION GRAPH → RECONCILIATION → FINANCIAL/RULE ENGINE → ANOMALY ENGINE
→ RECOVERABILITY ENGINE → AI AGENT → TOOL/ACTION REGISTRY → HUMAN APPROVAL GATE
→ RECOVERY VERIFICATION → AUDIT + RECOVERY LEDGER
```

Deterministic layers: ingestion validation, schema normalization, identity resolution, exact/partial/1:N/N:1 reconciliation, fee/tax/expected-settlement calculation, contractual rule evaluation, discrepancy calculation, verification, audit.
AI agent: investigation, root-cause reasoning, evidence selection, case prioritization, recovery workflow selection, tool selection, bounded planning, dispute drafting, escalation, stopping decisions. **The LLM never performs financial arithmetic.**

## 2. Data planes (one PostgreSQL database, four schemas — no microservices, no graph DB)

| Plane | PG schema | Contents |
|---|---|---|
| Ingestion | `raw` | raw_source_records, ingestion_batches, quarantine_records |
| Canonical | `core` | orders, payments, refunds, settlements, gateway_fees, bank_transactions, invoices, gst_records, customers, marketplace_deductions, subscriptions, receivables, chargebacks, customer_events |
| Derived | `ops` | identity_matches, reconciliation_results, anomaly_results, recoverability_assessments, evidence_records, recovery_cases, recovery_actions, case_history, approvals, verification_events, audit_ledger |
| Config | `cfg` | rate_cards, financial_rules, recovery_policies, tolerance_rules, sla_rules, source_connectors, schema_versions, normalization_mappings, agent_tools |
| Eval | `eval` | ground_truth, evaluation_runs, evaluation_case_scores (evaluator-only) |

## 3. Variance classification (project-critical business rule)

`EXPECTED ≠ ACTUAL` is a **variance**, not leakage. The rule engine classifies:

| Class | Meaning | Resolution |
|---|---|---|
| LEGITIMATE | explained by rate card / contract / documented adjustment | no case |
| TIMING | inside open settlement/bank window | re-check at deadline |
| ADJUSTMENT | documented by counterparty with reason code | no case |
| LEAKAGE | unexplained, rule-violating, beyond deadline/tolerance | case |

GST/ITC discrepancies are always `FINANCE_REVIEW` — never auto-recovery.

## 4. Phase scope

- **MVP (Phase 0–1 core)**: payment mismatch, settlement mismatch, fee discrepancy, refund economics. Tables: see schema.sql §MVP.
- **Phase 2**: marketplace_deductions, subscriptions, customer_events; anomaly types 5–8.
- **Phase 3**: receivables, chargebacks (+ checkout abandonment detection); anomaly types 9–11.

## 5. Identity resolution hierarchy

1. exact external ID (gateway order ref = commerce order id)
2. shared order/payment reference
3. invoice reference
4. UTR / bank reference
5. amount + time window (± tolerance, ± hours)
6. customer/order metadata
7. probabilistic score (weighted identifiers) — stored, never silently auto-merged
8. human review queue (identity_matches.status = REVIEW_REQUIRED)

Confidence score 0.00–1.00; method enum EXACT_REF/SHARED_ORDER/INVOICE_REF/UTR/AMOUNT_WINDOW/METADATA/PROBABILISTIC/MANUAL; conflict table for conflicting identifiers; unresolved state preserved (never guessed).

Chain: Shopify order id → razorpay_order_id on payments → settlements.payment_id → bank_transactions.utr → invoices.order_id → gst_records.invoice_id.

## 6. Financial model (deterministic, rule engine only)

```
expected_fee      = rate_card lookup(payment method, amount, instrument) → pct_of(amount) + fixed
expected_tax      = expected_fee × gst_rate (18% on MDR)
expected_settlement = gross − expected_fee − expected_tax − refunds_in_flight_adjustments
actual_*          = SUM of normalized actual records
variance          = expected − actual
unexplained_variance = variance − explained_adjustments − timing_in_flight
```

Example (canonical): gross ₹10,000, MDR 2% = ₹200, GST 18% on fee = ₹36, expected settlement ₹9,764; actual ₹9,514; variance ₹250.

## 7. Status models

**Reconciliation**: MATCHED, PARTIAL, TIMING_DIFFERENCE, UNMATCHED, MISMATCH, DUPLICATE, CONFLICT, PENDING, REVIEW_REQUIRED (transition rules in schema comments + functions).

**Recoverability**: DETECTED → VALIDATING → EXPLAINABLE/UNEXPLAINED → ELIGIBILITY_CHECK → EVIDENCE_CHECK → DEADLINE_CHECK → RECOVERABLE / REVIEW_REQUIRED / NOT_RECOVERABLE → ACTION_READY.

**Case**: NEW → INVESTIGATING → PLANNED → PENDING_APPROVAL → ACTING → VERIFYING → RECOVERED / PARTIALLY_RECOVERED / UNRECOVERABLE / ESCALATED / CLOSED.

**Approval**: REQUESTED → APPROVED / REJECTED / EXPIRED. Risk levels 0–4 (L0 read auto; L1 draft auto; L2 reversible configurable; L3 financial human; L4 tax/legal mandatory human).

**Verification**: ACTION_SUBMITTED → ACKNOWLEDGED → IN_PROGRESS → SUCCESS/FAILED/EXPIRED → FINANCIAL_EFFECT_DETECTED → RECOVERY_VERIFIED (+ DUPLICATE_AVOIDED check).

## 8. Data volume plan

- Development: 1,000 master transactions (~35–40k rows total across tables)
- Testing: 10,000 (~350–400k rows)
- Stress: 100,000+ (~3.5–4M rows)
- Approx multipliers per transaction: 1.15 payments, 0.15 refunds, 1.05 fees, 1.1 settlements, 1.05 bank, 1.0 invoice, 1.2 gst lines, 0.2 cases, 2.5 case history, 1.5 actions, 8+ audit rows.

## 9. Synthetic distribution (configurable, defaults)

healthy 87%, fee_excess 5%, settlement_mismatch 3%, missing_settlement 2%, duplicate_fee 1%, refund_economics 3% → of anomalies: recoverable ~55%, review_required ~25%, not_recoverable ~20%; overlap enabled (one transaction may carry 2 anomalies, e.g., fee + settlement). Config in `generators/config/distributions.yaml` — never hard-coded.

## 10. AI boundary

AI receives: structured case object (v_case_full view), evidence references, calculated expectations, discrepancy + recoverability assessment, allowed actions, deadlines, case history. AI never receives: ground-truth columns, raw arithmetic responsibility, ledger mutation rights, tax filing, unrestricted money movement.

## 11. Provenance & quality

Every canonical row carries source_system, source_record_id, ingestion_batch_id, ingested_at, schema_version, parser_version, normalization_version. Raw payloads retained in `raw.raw_source_records` (JSONB + sha256). Validation: duplicate/missing IDs, invalid currency/amount, timestamp inconsistency, impossible statuses, missing relationships, inconsistent totals, negative where forbidden, orphans, conflicting identifiers → `raw.quarantine_records` with error reason + remediation path.

## 12. Evaluation

`eval.ground_truth` (actual_problem, anomaly_type, true_* fields) is evaluator-only; the agent's runtime DB role has no SELECT on schema `eval`. Metrics: detection precision/recall, amount-level accuracy, recovery accuracy/success rate, false-positive rate, ROI.
