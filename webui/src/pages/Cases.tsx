import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Api, fmtMoney, fmtPct, fmtTime, can, Api as A, type CaseRow, type ExecuteResult } from '../api'
import { Badge, Card, EmptyState, ErrorBox, MoneyBar, Spinner } from '../components'
import { navigate } from '../App'

// ----------------------------------------------------------------- list
export function CaseListPage() {
  const [category, setCategory] = useState('')
  const [status, setStatus] = useState('')
  const [priority, setPriority] = useState('')
  const [recoverability, setRecoverability] = useState('')
  const [minAmt, setMinAmt] = useState('')
  const [sort, setSort] = useState('exposure')
  const [q, setQ] = useState('')

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['cases'],
    queryFn: () => Api.get<{ cases: CaseRow[] }>('/api/v1/cases?limit=500'),
  })

  const rows = useMemo(() => {
    let r = data?.cases ?? []
    if (category) r = r.filter(c => c.category === category)
    if (status) r = r.filter(c => c.status === status)
    if (priority) r = r.filter(c => c.priority === priority)
    if (recoverability) r = r.filter(c => c.recoverability_status === recoverability)
    if (minAmt) r = r.filter(c => Number(c.potential_leakage) >= Number(minAmt))
    if (q) {
      const s = q.toLowerCase()
      r = r.filter(c => c.case_id.toLowerCase().includes(s) || c.order_id.toLowerCase().includes(s)
        || (c.customer_id || '').toLowerCase().includes(s))
    }
    const num = (v: string | undefined) => Number(v || 0)
    const sorts: Record<string, (a: CaseRow, b: CaseRow) => number> = {
      exposure: (a, b) => num(b.potential_leakage) - num(a.potential_leakage),
      deadline: (a, b) => (a.deadline_at || '9').localeCompare(b.deadline_at || '9'),
      confidence: (a, b) => num(b.confidence) - num(a.confidence),
      oldest: (a, b) => (a.opened_at || '').localeCompare(b.opened_at || ''),
      priority: (a, b) => (b.priority || '').localeCompare(a.priority || ''),
    }
    return [...r].sort(sorts[sort])
  }, [data, category, status, priority, recoverability, minAmt, sort, q])

  const cats = [...new Set((data?.cases ?? []).map(c => c.category))]

  return (
    <div className="space-y-4">
      {/* filters */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search case / order / customer…"
          className="w-56 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 outline-none placeholder:text-slate-600 focus:border-sky-500" />
        <select value={category} onChange={e => setCategory(e.target.value)} className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5">
          <option value="">All categories</option>
          {cats.map(c => <option key={c}>{c}</option>)}
        </select>
        <select value={status} onChange={e => setStatus(e.target.value)} className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5">
          <option value="">All statuses</option>
          {['NEW', 'INVESTIGATING', 'ACTION_READY', 'PENDING_APPROVAL', 'ESCALATED', 'RESOLVED', 'REVIEW_REQUIRED'].map(s => <option key={s}>{s}</option>)}
        </select>
        <select value={priority} onChange={e => setPriority(e.target.value)} className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5">
          <option value="">All priorities</option>
          {['HIGH', 'MEDIUM', 'LOW'].map(s => <option key={s}>{s}</option>)}
        </select>
        <select value={recoverability} onChange={e => setRecoverability(e.target.value)} className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5">
          <option value="">All recoverability</option>
          {['RECOVERABLE', 'PARTIALLY_RECOVERABLE', 'NOT_RECOVERABLE', 'REVIEW_REQUIRED'].map(s => <option key={s}>{s}</option>)}
        </select>
        <input value={minAmt} onChange={e => setMinAmt(e.target.value)} type="number" placeholder="min ₹"
          className="w-24 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5" />
        <select value={sort} onChange={e => setSort(e.target.value)} className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5">
          <option value="exposure">Highest exposure</option>
          <option value="deadline">Nearest deadline</option>
          <option value="confidence">Highest confidence</option>
          <option value="oldest">Oldest unresolved</option>
          <option value="priority">Highest priority</option>
        </select>
        <span className="ml-auto text-slate-500">{rows.length} cases</span>
      </div>

      {isError && <ErrorBox msg={(error as Error).message} />}
      {isLoading && <Spinner />}

      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full text-xs">
          <thead className="bg-slate-900/80">
            <tr className="text-left text-[10.5px] uppercase tracking-wider text-slate-500">
              {['Case', 'Order', 'Category', 'Pri', 'Potential ₹', 'Recoverable ₹', 'Status', 'Conf', 'Deadline', ''].map(h => (
                <th key={h} className="px-2.5 py-2">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 100).map(c => (
              <tr key={c.case_id} className="cursor-pointer border-t border-slate-800/60 hover:bg-slate-900"
                onClick={() => navigate('case', c.case_id)}>
                <td className="px-2.5 py-1.5 font-mono text-sky-300">{c.case_id}</td>
                <td className="px-2.5 py-1.5 font-mono text-slate-400">{c.order_id}</td>
                <td className="px-2.5 py-1.5">{c.category}</td>
                <td className="px-2.5 py-1.5"><Badge>{c.priority || '—'}</Badge></td>
                <td className="px-2.5 py-1.5 text-right tabular-nums text-rose-300">{fmtMoney(c.potential_leakage)}</td>
                <td className="px-2.5 py-1.5 text-right tabular-nums text-amber-300">{fmtMoney(c.potential_recovery)}</td>
                <td className="px-2.5 py-1.5"><Badge>{c.status}</Badge></td>
                <td className="px-2.5 py-1.5 tabular-nums text-slate-400">{c.confidence ? fmtPct(Number(c.confidence)) : '—'}</td>
                <td className="px-2.5 py-1.5 text-slate-500">{(c.deadline_at || '').slice(0, 10) || '—'}</td>
                <td className="px-2.5 py-1.5 text-slate-600">→</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && !isLoading && <EmptyState text="No cases match the filters" />}
      </div>
    </div>
  )
}

// --------------------------------------------------------------- detail
export function CaseDetailPage({ caseId }: { caseId: string }) {
  const qc = useQueryClient()
  const [runResult, setRunResult] = useState<ExecuteResult | null>(null)
  const [running, setRunning] = useState<'plan' | 'execute' | null>(null)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['case', caseId],
    queryFn: () => Api.get<CaseRow>(`/api/v1/cases/${caseId}`),
    enabled: !!caseId,
  })

  const { data: timeline } = useQuery({
    queryKey: ['timeline', caseId],
    queryFn: () => Api.get<{ events: { ts: string; kind: string; actor: string; event: string; detail?: string }[] }>(`/api/v1/cases/${caseId}/timeline`),
    enabled: !!caseId,
  })

  const { data: flow } = useQuery({
    queryKey: ['moneyflow', caseId],
    queryFn: () => Api.get<Record<string, unknown>>(`/api/v1/orders/${data?.order_id}/money-flow`),
    enabled: !!data?.order_id,
  })

  const plan = useMutation({
    mutationFn: () => A.post<{ case_id: string; llm_plan: Record<string, unknown> }>(`/api/v1/cases/${caseId}/plan`),
    onMutate: () => setRunning('plan'),
    onSettled: () => setRunning(null),
  })

  const execute = useMutation({
    mutationFn: () => A.post<ExecuteResult>(`/api/v1/cases/${caseId}/execute`),
    onMutate: () => setRunning('execute'),
    onSuccess: (r) => { setRunResult(r); qc.invalidateQueries() },
    onSettled: () => setRunning(null),
  })

  if (!caseId) return <EmptyState text="Select a case from Recovery Cases" />
  if (isLoading) return <Spinner />
  if (isError) return <ErrorBox msg={(error as Error).message} />

  const c = data!
  const role = A.role()
  const canRun = can('run_agent', role)
  const ev = c.evidence ?? []

  // pre-computed by backend
  const expSettle = Number(c.expected_settlement || 0)
  const actSettle = Number(c.actual_settlement || 0)

  const flowData = flow as {
    payments?: { payment_id: string; amount: string; method?: string; captured_at?: string;
      fees: { fee_id: string; amount: string; tax_amount?: string; rate_card_id?: string }[]
      refunds: { refund_id: string; amount: string; status?: string }[]
      settlements: { settlement_id: string; amount: string; utr?: string; status?: string; settled_at?: string }[] }[]
    order?: Record<string, string>
    invoice?: Record<string, string> | null
    gst?: Record<string, string>[]
  } | undefined

  return (
    <div className="space-y-5">
      {/* header */}
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="font-mono text-lg font-bold text-sky-300">{c.case_id}</h2>
            <Badge>{c.status}</Badge>
            <Badge>{c.priority || '—'}</Badge>
          </div>
          <div className="mt-0.5 text-xs text-slate-400">
            {c.category} · order <button className="font-mono text-sky-400 hover:underline"
              onClick={() => navigate('explorer')}>{c.order_id}</button> · payment <span className="font-mono">{c.payment_id}</span>
          </div>
        </div>
        <div className="ml-auto flex gap-2 text-xs">
          {canRun && (
            <>
              <button disabled={running !== null}
                onClick={() => plan.mutate()}
                className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-slate-200 hover:border-sky-500 disabled:opacity-50">
                {running === 'plan' ? 'Planning…' : 'Run AI Plan'}
              </button>
              <button disabled={running !== null}
                onClick={() => execute.mutate()}
                className="rounded-lg bg-sky-600 px-3 py-1.5 font-medium text-white hover:bg-sky-500 disabled:opacity-50">
                {running === 'execute' ? 'Executing…' : 'Execute Recovery'}
              </button>
            </>
          )}
        </div>
      </div>

      {execute.isError && <ErrorBox msg={(execute.error as Error).message} />}

      {/* summary + expected vs actual */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Expected vs Actual settlement" className="lg:col-span-2">
          <MoneyBar expected={expSettle} actual={actSettle} label="settlement" />
          <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-400 md:grid-cols-4">
            <div>Known adjustments: <span className="tabular-nums text-slate-200">{fmtMoney(c.known_adjustments)}</span></div>
            <div>Expected fee: <span className="tabular-nums text-slate-200">{fmtMoney(c.expected_fee)}</span></div>
            <div>Expected tax: <span className="tabular-nums text-slate-200">{fmtMoney(c.expected_tax)}</span></div>
            <div>Refund: <span className="text-slate-200">{c.refund_status || '—'}</span></div>
          </div>
          <div className="mt-2 rounded-lg border border-slate-800 bg-slate-950 p-2.5 text-[11px] leading-relaxed text-slate-500">
            Expected = gross − contractual fee − applicable tax − legitimate adjustments.
            All values are computed by the deterministic backend engine — never in the browser.
          </div>
        </Card>

        <div className="space-y-4">
          <Card title="Case summary">
            <dl className="space-y-1.5 text-xs">
              {[
                ['Potential leakage', fmtMoney(c.potential_leakage), 'text-rose-300'],
                ['Potential recovery', fmtMoney(c.potential_recovery), 'text-amber-300'],
                ['Confidence', fmtPct(Number(c.confidence || 0)), 'text-slate-200'],
                ['Recoverability', c.recoverability_status || '—', 'text-slate-200'],
                ['Deadline', (c.deadline_at || '').replace('T', ' ').slice(0, 16) || '—', 'text-slate-200'],
                ['Recon status', c.recon_status || '—', 'text-slate-200'],
                ['Opened', fmtTime(c.opened_at), 'text-slate-400'],
              ].map(([k2, v, cls]) => (
                <div key={k2 as string} className="flex justify-between">
                  <dt className="text-slate-500">{k2}</dt>
                  <dd className={`tabular-nums ${cls}`}>{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      </div>

      {/* AI panel */}
      {(plan.data || runResult) && (
        <Card title="AI Investigation">
          {(() => {
            const p = ((runResult ? {
              diagnosis: runResult.llm_diagnosis,
              evidence_selection: [] as { evidence_id: string; reason: string }[],
              recommended_action: runResult.proposed_action,
              reason_for_action: runResult.policy_decision.reasons.join('; '),
            } : plan.data!.llm_plan)) as {
              diagnosis: { root_cause?: string; confidence?: number; explanation?: string }
              evidence_selection: { evidence_id: string; reason: string }[]
              recommended_action: string
              reason_for_action: string
            }
            const diag = p.diagnosis || {}
            const evidenceSel = p.evidence_selection || []
            return (
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2.5">
                  <div>
                    <div className="text-[10.5px] uppercase tracking-wider text-slate-500">Root cause</div>
                    <div className="text-sm text-slate-200">{diag.root_cause}</div>
                  </div>
                  <div>
                    <div className="text-[10.5px] uppercase tracking-wider text-slate-500">Confidence</div>
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-28 overflow-hidden rounded bg-slate-800">
                        <div className="h-full bg-sky-500" style={{ width: `${(diag.confidence || 0) * 100}%` }} />
                      </div>
                      <span className="text-sm tabular-nums text-slate-200">{fmtPct(diag.confidence || 0)}</span>
                    </div>
                  </div>
                  <div>
                    <div className="text-[10.5px] uppercase tracking-wider text-slate-500">Explanation</div>
                    <div className="text-xs leading-relaxed text-slate-400">{diag.explanation}</div>
                  </div>
                </div>
                <div className="space-y-2.5">
                  <div>
                    <div className="text-[10.5px] uppercase tracking-wider text-slate-500">Recommended action</div>
                    <div className="font-mono text-sm font-bold text-sky-300">{p.recommended_action}</div>
                  </div>
                  <div>
                    <div className="text-[10.5px] uppercase tracking-wider text-slate-500">Why this action</div>
                    <div className="text-xs leading-relaxed text-slate-400">{p.reason_for_action || ''}</div>
                  </div>
                  <div>
                    <div className="text-[10.5px] uppercase tracking-wider text-slate-500">Evidence selected</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {evidenceSel.map(e => (
                        <span key={e.evidence_id} className="rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-300">
                          ✓ {e.evidence_id}
                        </span>
                      ))}
                    </div>
                  </div>
                  {runResult && (
                    <div className="rounded-lg border border-slate-800 bg-slate-950 p-2.5 text-xs">
                      <div className="flex gap-2">
                        <span className="text-slate-500">executed:</span>
                        <span className="font-mono text-emerald-300">{runResult.executed_action}</span>
                        <span className="ml-auto"><Badge>{runResult.verification_status}</Badge></span>
                      </div>
                      <div className="mt-1 flex gap-2">
                        <span className="text-slate-500">recovered:</span>
                        <span className="font-bold tabular-nums text-emerald-300">{fmtMoney(runResult.recovered_amount)}</span>
                      </div>
                      <div className="mt-1 text-[10.5px] text-slate-500">
                        risk {runResult.policy_decision.risk_level} · approval {runResult.policy_decision.approval_required ? 'required+granted' : 'not required'} · {runResult.tool_calls} tool calls · {runResult.duration_ms}ms
                      </div>
                      {runResult.errors.length > 0 && <div className="mt-1 text-rose-300">{runResult.errors.join('; ')}</div>}
                    </div>
                  )}
                </div>
              </div>
            )
          })()}
        </Card>
      )}

      {/* evidence chain + money flow */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Financial evidence chain">
          {ev.length === 0 ? <EmptyState text="No evidence bound" /> : (
            <div className="space-y-1">
              {ev.map((e, i) => (
                <div key={e.evidence_id} className="flex items-start gap-2 rounded-lg border border-slate-800 bg-slate-950 p-2">
                  <span className="mt-0.5 text-slate-600">{i + 1}.</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[10.5px] text-sky-300">{e.evidence_id}</span>
                      <Badge>{e.evidence_kind}</Badge>
                    </div>
                    <div className="truncate text-[11px] text-slate-400">{e.description}</div>
                    <div className="text-[10px] text-slate-600">{e.source_reference} · sha {e.payload_sha256?.slice(0, 12)}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Money flow — order → bank">
          {!flowData?.payments?.length ? <EmptyState text="No payment records" /> : (
            <div className="space-y-2">
              {flowData.payments.map(p => (
                <div key={p.payment_id} className="rounded-lg border border-slate-800 bg-slate-950 p-2.5 text-[11px]">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sky-300">{p.payment_id}</span>
                    <span className="tabular-nums text-slate-200">{fmtMoney(p.amount)}</span>
                  </div>
                  <div className="mt-1 space-y-0.5 text-slate-400">
                    {p.fees?.map(f => (
                      <div key={f.fee_id} className="flex justify-between pl-4">
                        <span>↳ fee {f.fee_id} {f.rate_card_id ? `(${f.rate_card_id})` : ''}</span>
                        <span className="tabular-nums">-{fmtMoney(f.amount)}{f.tax_amount ? ` +tax ${fmtMoney(f.tax_amount)}` : ''}</span>
                      </div>
                    ))}
                    {p.refunds?.map(r => (
                      <div key={r.refund_id} className="flex justify-between pl-4">
                        <span>↳ refund {r.refund_id} {r.status ? `(${r.status})` : ''}</span>
                        <span className="tabular-nums">-{fmtMoney(r.amount)}</span>
                      </div>
                    ))}
                    {p.settlements?.map(s => (
                      <div key={s.settlement_id} className="flex justify-between pl-4">
                        <span>↳ settlement {s.settlement_id} {s.utr ? `UTR ${s.utr}` : ''}</span>
                        <span className="tabular-nums text-emerald-300">{fmtMoney(s.amount)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              {flowData.invoice && (
                <div className="rounded-lg border border-slate-800 bg-slate-950 p-2 text-[11px] text-slate-400">
                  Invoice <span className="font-mono text-sky-300">{flowData.invoice.invoice_id}</span>
                  {flowData.gst?.length ? ` · GST rows: ${flowData.gst.length}` : ''}
                </div>
              )}
            </div>
          )}
        </Card>
      </div>

      {/* timeline */}
      <Card title="Agent activity timeline">
        {(timeline?.events ?? []).length === 0 ? <EmptyState text="No activity yet — run the AI plan" /> : (
          <div className="relative space-y-0 pl-4">
            {(timeline?.events ?? []).map((t, i) => (
              <div key={i} className="relative border-l border-slate-700 py-1.5 pl-4">
                <span className="absolute -left-[4.5px] top-3 h-2 w-2 rounded-full bg-sky-500" />
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-mono text-[10px] uppercase tracking-wider text-sky-400">{t.kind}</span>
                  <Badge>{t.event}</Badge>
                  <span className="text-slate-500">{t.actor}</span>
                  <span className="ml-auto text-[10px] tabular-nums text-slate-600">{fmtTime(t.ts)}</span>
                </div>
                {t.detail && <div className="mt-0.5 text-[11px] text-slate-400">{t.detail}</div>}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* actions + approvals */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Recovery actions">
          {(c.actions ?? []).length === 0 ? <EmptyState text="No actions yet" /> : (
            <table className="w-full text-[11px]">
              <thead><tr className="text-left text-slate-500"><th className="py-1">Action</th><th>Risk</th><th>Status</th><th className="text-right">Amount</th></tr></thead>
              <tbody>
                {(c.actions ?? []).map(a => (
                  <tr key={a.action_id} className="border-t border-slate-800/50">
                    <td className="py-1 font-mono">{a.action_type}</td>
                    <td>{a.risk_level}</td>
                    <td><Badge>{a.status}</Badge></td>
                    <td className="text-right tabular-nums">{a.amount ? fmtMoney(a.amount) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Approvals">
          {(c.approvals ?? []).length === 0 ? <EmptyState text="No approvals required / yet" /> : (
            <table className="w-full text-[11px]">
              <thead><tr className="text-left text-slate-500"><th className="py-1">Approval</th><th>Amount</th><th>Status</th><th>Decided by</th></tr></thead>
              <tbody>
                {(c.approvals ?? []).map(a => (
                  <tr key={a.approval_id} className="border-t border-slate-800/50">
                    <td className="py-1 font-mono">{a.approval_id}</td>
                    <td className="tabular-nums">{fmtMoney(a.amount)}</td>
                    <td><Badge>{a.status}</Badge></td>
                    <td className="text-slate-400">{a.decided_by || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      {/* verification */}
      {(c.verifications ?? []).length > 0 && (
        <Card title="Recovery verification">
          <table className="w-full text-[11px]">
            <thead><tr className="text-left text-slate-500">
              <th className="py-1">Check</th><th>Status</th><th>Expected ref</th><th>Observed</th><th>When</th>
            </tr></thead>
            <tbody>
              {(c.verifications ?? []).map(v => (
                <tr key={v.verification_id} className="border-t border-slate-800/50">
                  <td className="py-1 font-mono">{v.check_type}</td>
                  <td><Badge>{v.status}</Badge></td>
                  <td className="font-mono text-slate-400">{v.expected_ref || '—'}</td>
                  <td className="tabular-nums text-emerald-300">{v.observed_value || '—'}</td>
                  <td className="text-slate-500">{fmtTime(v.checked_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
