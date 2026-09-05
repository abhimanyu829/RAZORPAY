import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Api, fmtMoney, fmtTime, can, type ApprovalRow, type CaseRow } from '../api'
import { Badge, Card, EmptyState, ErrorBox, Spinner } from '../components'
import { navigate } from '../App'

export function ApprovalsPage() {
  const qc = useQueryClient()
  const [filter, setFilter] = useState('PENDING')
  const [note, setNote] = useState<Record<string, string>>({})
  const role = Api.role()
  const canApprove = can('approve', role)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['approvals'],
    queryFn: () => Api.get<{ approvals: (ApprovalRow & { case?: CaseRow })[] }>('/api/v1/approvals'),
    refetchInterval: 15_000,
  })

  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: string }) =>
      Api.post(`/api/v1/approvals/${id}/decide`, { decision, decided_by: role, note: note[id] || '' }),
    onSuccess: () => qc.invalidateQueries(),
  })

  if (isError) return <ErrorBox msg={(error as Error).message} />
  if (isLoading) return <Spinner />

  const rows = (data?.approvals ?? []).filter(a => filter === 'ALL' || a.status === filter)

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-xs">
        {['PENDING', 'APPROVED', 'REJECTED', 'ALL'].map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`rounded-lg px-3 py-1.5 ${filter === f ? 'bg-sky-500/15 text-sky-300' : 'bg-slate-900 text-slate-400 hover:text-slate-200'}`}>
            {f}
          </button>
        ))}
        {!canApprove && <span className="ml-auto text-amber-400">Your role cannot decide approvals (backend enforced)</span>}
      </div>

      {decide.isError && <ErrorBox msg={(decide.error as Error).message} />}

      {rows.length === 0 && <EmptyState text={`No ${filter.toLowerCase()} approvals`} />}

      <div className="space-y-2">
        {rows.map(a => (
          <Card key={a.approval_id}>
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <button className="font-mono text-sky-300 hover:underline"
                onClick={() => a.case && navigate('case', a.case_id)}>{a.case_id}</button>
              <Badge>{a.status}</Badge>
              <span className="text-slate-400">risk <span className="font-mono">{a.risk_level}</span></span>
              <span className="tabular-nums text-amber-300">{fmtMoney(a.amount)}</span>
              <span className="text-slate-500">requested {fmtTime(a.requested_at)} by {a.requested_by}</span>
              {a.decided_by && <span className="text-slate-500">→ {a.decided_by} {fmtTime(a.decided_at)}</span>}
            </div>
            {a.case && (
              <div className="mt-1.5 text-[11px] text-slate-400">
                {a.case.category} · potential recovery {fmtMoney(a.case.potential_recovery)}
                {a.case.allowed_actions ? ` · allowed: ${a.case.allowed_actions.split('|').join(', ')}` : ''}
              </div>
            )}
            {a.status === 'PENDING' && canApprove && (
              <div className="mt-2.5 flex items-center gap-2 text-xs">
                <input value={note[a.approval_id] || ''} placeholder="decision note (required for reject)"
                  onChange={e => setNote(n => ({ ...n, [a.approval_id]: e.target.value }))}
                  className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 outline-none focus:border-sky-500" />
                <button disabled={decide.isPending}
                  onClick={() => decide.mutate({ id: a.approval_id, decision: 'approve' })}
                  className="rounded-lg bg-emerald-600 px-3.5 py-1.5 font-medium text-white hover:bg-emerald-500 disabled:opacity-50">
                  Approve
                </button>
                <button disabled={decide.isPending || !(note[a.approval_id] || '').trim()}
                  onClick={() => decide.mutate({ id: a.approval_id, decision: 'reject' })}
                  className="rounded-lg bg-rose-600 px-3.5 py-1.5 font-medium text-white hover:bg-rose-500 disabled:opacity-50">
                  Reject
                </button>
              </div>
            )}
          </Card>
        ))}
      </div>
    </div>
  )
}
