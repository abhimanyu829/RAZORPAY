import { useQuery } from '@tanstack/react-query'
import { Api, fmtMoney, fmtTime, type VerificationRow } from '../api'
import { Badge, Card, EmptyState, ErrorBox, Spinner } from '../components'
import { navigate } from '../App'

const STAGES = ['SUBMITTED', 'ACKNOWLEDGED', 'IN_PROGRESS', 'FINANCIAL_EFFECT_DETECTED', 'RECOVERY_VERIFIED']

export function VerificationPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['verification-events'],
    queryFn: () => Api.get<{ events: VerificationRow[] }>('/api/v1/verification/events?limit=500'),
    refetchInterval: 15_000,
  })

  if (isError) return <ErrorBox msg={(error as Error).message} />
  if (isLoading) return <Spinner />

  const events = [...(data?.events ?? [])].reverse()

  return (
    <div className="space-y-4">
      <Card title="Recovery verification pipeline">
        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
          {STAGES.map((s, i) => (
            <span key={s} className="flex items-center gap-1.5">
              {i > 0 && <span className="text-slate-600">→</span>}
              <span className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-slate-300">{s}</span>
            </span>
          ))}
        </div>
        <p className="mt-2 text-[11px] text-slate-500">
          Recovery is only counted when the verification service observes the financial effect (e.g. a bank credit).
          A ledger entry cannot exist without verification evidence.
        </p>
      </Card>

      {events.length === 0 && <EmptyState text="No verification events yet — execute a recovery action" />}

      <div className="space-y-2">
        {events.map(v => (
          <div key={v.verification_id}
            className="cursor-pointer rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs hover:border-slate-700"
            onClick={() => navigate('case', v.case_id)}>
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="font-mono text-sky-300">{v.verification_id}</span>
              <span className="text-slate-500">case {v.case_id}</span>
              <Badge>{v.status}</Badge>
              <span className="text-slate-400">{v.check_type}</span>
              {v.observed_value && <span className="tabular-nums text-emerald-300">{fmtMoney(v.observed_value)}</span>}
              <span className="ml-auto text-slate-600">{fmtTime(v.checked_at)}</span>
            </div>
            {v.notes && <div className="mt-1 text-[11px] text-slate-500">{v.notes}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}
