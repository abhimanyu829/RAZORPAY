// Central API client + role model. The frontend NEVER computes financial
// values; every number displayed comes from these backend responses.

export type Role = 'admin' | 'finance_lead' | 'finance_operator' | 'analyst' | 'viewer' | 'agent' | 'evaluator'

export interface Kpis {
  revenue_analysed: number
  cases_open: number
  leakage_detected: number
  recoverable_amount: number
  recovery_initiated: number
  recovered_amount: number
  unrecovered_amount: number
  recovery_rate: number
  agent_actions: number
  failed_actions: number
  human_escalations: number
  pending_approvals: number
  rollout_level: number
}

export interface CaseRow {
  case_id: string
  anomaly_id?: string
  order_id: string
  payment_id: string
  customer_id?: string
  category: string
  priority: string
  status: string
  expected_fee?: string
  expected_tax?: string
  expected_settlement?: string
  actual_fee?: string
  actual_tax?: string
  actual_settlement?: string
  known_adjustments?: string
  refund_status?: string
  recon_status?: string
  potential_leakage: string
  confidence?: string
  recoverability_status?: string
  potential_recovery?: string
  deadline_at?: string
  allowed_actions?: string
  approval_required?: string
  opened_at?: string
  closed_at?: string
  // detail extras
  evidence?: EvidenceRow[]
  history?: HistoryRow[]
  actions?: ActionRow[]
  approvals?: ApprovalRow[]
  verifications?: VerificationRow[]
}

export interface EvidenceRow {
  evidence_id: string
  case_id: string
  evidence_kind: string
  source_reference: string
  description: string
  payload_sha256?: string
  collected_at?: string
}

export interface HistoryRow {
  history_id: string
  case_id: string
  event_type: string
  old_status?: string
  new_status?: string
  actor: string
  message?: string
  event_at: string
}

export interface ActionRow {
  action_id: string
  case_id: string
  tool_id: string
  action_type: string
  actor: string
  status: string
  risk_level: string
  external_ref?: string
  approval_id?: string
  amount?: string
  executed_at: string
}

export interface ApprovalRow {
  approval_id: string
  case_id: string
  risk_level: string
  amount: string
  status: string
  requested_by: string
  requested_at: string
  decided_by?: string
  decided_at?: string
  decision_note?: string
}

export interface VerificationRow {
  verification_id: string
  action_id?: string
  case_id: string
  status: string
  check_type: string
  expected_ref?: string
  observed_value?: string
  checked_at: string
  notes?: string
}

export interface AuditRow {
  audit_id: string
  case_id: string
  actor: string
  event_type: string
  tool_called?: string
  decision?: string
  new_state?: string
  amount?: string
  prev_hash?: string
  entry_hash?: string
  created_at: string
}

export interface TimelineEvent {
  ts: string
  kind: string
  actor: string
  event: string
  detail?: string
}

export interface MoneyFlow {
  order: Record<string, string>
  payments: {
    payment_id: string
    gateway_payment_id?: string
    amount: string
    method?: string
    status?: string
    captured_at?: string
    fees: { fee_id: string; amount: string; tax_amount?: string; rate_card_id?: string }[]
    refunds: { refund_id: string; amount: string; status?: string }[]
    settlements: {
      settlement_id: string
      amount: string
      fee_deducted?: string
      tax_deducted?: string
      utr?: string
      status?: string
      settled_at?: string
      bank: { bank_txn_id: string; amount: string; value_date?: string } | null
    }[]
  }[]
  invoice: Record<string, string> | null
  gst: Record<string, string>[]
}

export interface AgentRun {
  run_id: string
  case_id: string
  llm_provider: string
  llm_model: string
  rollout_level: number | string
  status: string
  proposed_action?: string
  executed_action?: string
  verification_status?: string
  recovered_amount?: string | number
  errors?: string
  started_at: string
  finished_at?: string
}

export interface ExecuteResult {
  run_id: string
  case_id: string
  status: string
  proposed_action: string
  executed_action: string
  action_id: string
  verification_status: string
  recovered_amount: number
  policy_decision: { allowed: boolean; risk_level: string; approval_required: boolean; reasons: string[] }
  llm_diagnosis: { root_cause?: string; confidence?: number; explanation?: string }
  errors: string[]
  steps: number
  tool_calls: number
  duration_ms: number
}

export interface ConnectorHealth {
  [id: string]: { healthy: boolean; detail: string }
}

export interface LedgerRow {
  ledger_id: string
  case_id: string
  order_id?: string
  source: string
  amount: string
  status: string
  bank_reference?: string
  recorded_at: string
}

const API_KEY_STORAGE = 'rg_api_key'

export class Api {
  static key(): string {
    return localStorage.getItem(API_KEY_STORAGE) || 'rg-admin-key'
  }
  static setKey(k: string) {
    localStorage.setItem(API_KEY_STORAGE, k)
  }
  static role(): Role | null {
    return KEY_ROLES[this.key()] ?? null
  }

  private static async req<T>(path: string, init?: RequestInit): Promise<T> {
    const r = await fetch(path, {
      ...init,
      headers: {
        'X-API-Key': this.key(),
        'Content-Type': 'application/json',
        ...(init?.headers || {}),
      },
    })
    if (r.status === 403) throw new Error('403: your role cannot perform this action')
    if (r.status === 404) throw new Error('404: not found')
    if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`)
    return r.json() as Promise<T>
  }

  static get<T>(path: string) { return this.req<T>(path) }
  static post<T>(path: string, body?: unknown) {
    return this.req<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined })
  }
}

export const KEY_ROLES: Record<string, Role> = {
  'rg-admin-key': 'admin',
  'rg-finance-key': 'finance_lead',
  'rg-analyst-key': 'analyst',
  'rg-viewer-key': 'viewer',
  'rg-agent-key': 'agent',
  'rg-evaluator-key': 'evaluator',
}

export const ROLE_CAPS: Record<Role, string[]> = {
  admin: ['read', 'write', 'approve', 'run_agent', 'sync', 'shadow', 'eval', 'admin'],
  finance_lead: ['read', 'write', 'approve', 'run_agent', 'sync'],
  finance_operator: ['read', 'write'],
  analyst: ['read', 'run_agent'],
  viewer: ['read'],
  agent: ['read'],
  evaluator: ['read', 'eval'],
}

export function can(cap: string, role: Role | null): boolean {
  return !!role && ROLE_CAPS[role]?.includes(cap)
}

export const fmtMoney = (n: number | string | undefined | null): string => {
  const v = Number(n || 0)
  return '₹' + v.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

export const fmtPct = (v: number | undefined): string =>
  `${((Number(v) || 0) * 100).toFixed(1)}%`

export const fmtTime = (iso: string | undefined): string =>
  (iso || '').replace('T', ' ').replace('Z', '') || '—'
