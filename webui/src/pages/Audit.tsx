import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Api, fmtMoney, fmtTime, type AuditRow } from '../api'
import { Card, EmptyState, ErrorBox, Spinner } from '../components'

export function AuditPage() {
  const [caseFilter, setCaseFilter] = useState('')
  const [limit, setLimit] = useState(300)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['audit', caseFilter, limit],
    queryFn: () => Api.get<{ audit: AuditRow[] }>(`/api/v1/audit?limit=${limit}${caseFilter ? `&case_id=${caseFilter}` : ''}`),
  })

  const rows = data?.audit ?? []

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <input value={caseFilter} onChange={e => setCaseFilter(e.target.value)} placeholder="Filter by case ID…"
          className="w-48 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 outline-none focus:border-sky-500" />
        <select value={limit} onChange={e => setLimit(Number(e.target.value))} className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5">
          {[100, 300, 1000, 2000].map(n => <option key={n} value={n}>last {n}</option>)}
        </select>
        <span className="ml-auto text-slate-500">
          append-only hash chain — ordinary users cannot mutate history
        </span>
      </div>

      {isError && <ErrorBox msg={(error as Error).message} />}
      {isLoading && <Spinner />}

      <Card title={`Audit chain — ${rows.length} entries`}>
        {rows.length === 0 ? <EmptyState text="No audit entries" /> : (
          <div className="max-h-[65vh] overflow-auto">
            <table className="w-full text-[11px]">
              <thead className="sticky top-0 bg-slate-900">
                <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500">
                  {['Time', 'Audit ID', 'Case', 'Actor', 'Event', 'Decision', 'Amount', 'prev → hash'].map(h => (
                    <th key={h} className="px-2 py-1.5">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...rows].reverse().map(r => (
                  <tr key={r.audit_id} className="border-t border-slate-800/50 hover:bg-slate-900/50">
                    <td className="whitespace-nowrap px-2 py-1 text-slate-500">{fmtTime(r.created_at)}</td>
                    <td className="px-2 py-1 font-mono text-slate-400">{r.audit_id}</td>
                    <td className="px-2 py-1 font-mono text-sky-300">{r.case_id}</td>
                    <td className="px-2 py-1 text-slate-400">{r.actor}</td>
                    <td className="px-2 py-1 font-mono">{r.event_type}</td>
                    <td className="px-2 py-1">{r.decision || '—'}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{r.amount ? fmtMoney(r.amount) : '—'}</td>
                    <td className="px-2 py-1 font-mono text-[9.5px] text-slate-600">
                      {r.prev_hash?.slice(0, 6)}→{r.entry_hash?.slice(0, 6)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
