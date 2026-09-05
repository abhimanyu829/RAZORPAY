import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Api, can, fmtTime } from '../api'
import { Card, ErrorBox, Spinner } from '../components'

interface ConnStat {
  connector_id: string
  last_run: Record<string, string> | null
  checkpoint: Record<string, string> | null
  records_processed: number
  duplicates: number
  quarantined: number
  errors: number
  webhook_events: number
}

export function ConnectorsPage() {
  const qc = useQueryClient()
  const canSync = can('sync', Api.role())

  const stats = useQuery({
    queryKey: ['connector-stats'],
    queryFn: () => Api.get<{ connectors: ConnStat[]; webhook_total: number }>('/api/v1/connectors/stats'),
  })
  const health = useQuery({
    queryKey: ['connector-health'],
    queryFn: () => Api.get<Record<string, { healthy: boolean; detail: string }>>('/api/v1/connectors/health'),
    refetchInterval: 20_000,
  })

  const sync = useMutation({
    mutationFn: (id: string) => Api.post(`/api/v1/connectors/${id}/sync`),
    onSuccess: () => qc.invalidateQueries(),
  })

  if (stats.isLoading) return <Spinner />
  if (stats.isError) return <ErrorBox msg={(stats.error as Error).message} />

  const webhookNote = (id: string) => id === 'RAZORPAY_TEST' ? 'Webhook: ' + (health.data?.RAZORPAY_TEST ? 'signature-verified' : 'idle') : null

  return (
    <div className="space-y-4">
      {sync.isError && <ErrorBox msg={(sync.error as Error).message} />}
      <div className="grid gap-4 md:grid-cols-2">
        {(stats.data?.connectors ?? []).map(c => {
          const h = health.data?.[c.connector_id]
          return (
            <Card key={c.connector_id}>
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-slate-200">{c.connector_id}</span>
                <span className={`flex items-center gap-1.5 text-xs ${h?.healthy ? 'text-emerald-400' : 'text-slate-500'}`}>
                  <span className="inline-block h-2 w-2 rounded-full bg-current" />
                  {h?.healthy ? 'Healthy' : (h?.detail || 'idle').slice(0, 30)}
                </span>
              </div>
              <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
                <div className="flex justify-between"><dt className="text-slate-500">last sync</dt><dd className="text-slate-300">{c.last_run ? fmtTime(c.last_run.finished_at || c.last_run.started_at) : '—'}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">records</dt><dd className="tabular-nums text-slate-300">{c.records_processed}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">duplicates</dt><dd className="tabular-nums text-slate-300">{c.duplicates}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">quarantine</dt><dd className="tabular-nums text-slate-300">{c.quarantined}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">errors</dt><dd className={`tabular-nums ${c.errors ? 'text-rose-400' : 'text-slate-300'}`}>{c.errors}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">webhook events</dt><dd className="tabular-nums text-slate-300">{c.webhook_events}</dd></div>
                <div className="col-span-2 flex justify-between"><dt className="text-slate-500">checkpoint</dt><dd className="truncate font-mono text-[10px] text-slate-400">
                  {c.checkpoint ? `${c.checkpoint.last_cursor || c.checkpoint.last_timestamp || '—'} @ ${fmtTime(c.checkpoint.updated_at)}` : '—'}
                </dd></div>
              </dl>
              {canSync && (
                <button disabled={sync.isPending && sync.variables === c.connector_id}
                  onClick={() => sync.mutate(c.connector_id)}
                  className="mt-3 w-full rounded-lg border border-slate-700 bg-slate-900 py-1.5 text-xs text-slate-200 hover:border-sky-500 disabled:opacity-50">
                  {sync.isPending && sync.variables === c.connector_id ? 'Syncing…' : 'Run incremental sync'}
                </button>
              )}
            </Card>
          )
        })}
      </div>
      <Card title="Webhook inbox">
        <div className="text-xs text-slate-400">
          {stats.data?.webhook_total ?? 0} webhook events received (deduplicated by provider event ID, HMAC-verified).
          {webhookNote('RAZORPAY_TEST')}
        </div>
      </Card>
    </div>
  )
}
