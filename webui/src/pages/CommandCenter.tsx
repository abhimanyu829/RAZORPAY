import { useQuery } from '@tanstack/react-query'
import { Api, fmtMoney, fmtPct, type Kpis } from '../api'
import { Card, Kpi, Badge, EmptyState, ErrorBox, Spinner } from '../components'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts'
import { navigate } from '../App'

const CAT_COLORS = ['#38bdf8', '#f472b6', '#facc15', '#34d399', '#a78bfa', '#fb923c']

export function CommandCenter() {
  const kpis = useQuery({
    queryKey: ['kpis'],
    queryFn: () => Api.get<{ kpis: Kpis }>('/api/v1/dashboard/summary'),
    refetchInterval: 20_000,
  })
  const byCat = useQuery({
    queryKey: ['leakage-by-category'],
    queryFn: () => Api.get<{ rows: { category: string; count: number; potential: number; recovered: number }[] }>('/api/v1/analytics/leakage-by-category'),
  })
  const funnel = useQuery({
    queryKey: ['recovery-funnel'],
    queryFn: () => Api.get<{ funnel: { stage: string; count: number }[] }>('/api/v1/analytics/recovery-funnel'),
  })
  const byPriority = useQuery({
    queryKey: ['cases-by-priority'],
    queryFn: () => Api.get<{ rows: { priority: string; count: number }[] }>('/api/v1/analytics/cases-by-priority'),
  })
  const actionDist = useQuery({
    queryKey: ['action-distribution'],
    queryFn: () => Api.get<{ rows: { action: string; count: number }[] }>('/api/v1/analytics/action-distribution'),
  })
  const deadline = useQuery({
    queryKey: ['approaching-deadline'],
    queryFn: () => Api.get<{ rows: { case_id: string; category: string; days_left: number; deadline_at: string; potential_leakage: string; priority: string }[] }>('/api/v1/analytics/approaching-deadline'),
  })
  const connectors = useQuery({
    queryKey: ['connector-health'],
    queryFn: () => Api.get<Record<string, { healthy: boolean; detail: string }>>('/api/v1/connectors/health'),
  })

  if (kpis.isError) return <ErrorBox msg={(kpis.error as Error).message} />
  if (kpis.isLoading) return <Spinner />

  const k = kpis.data!.kpis
  const catRows = byCat.data?.rows ?? []
  const funnelRows = funnel.data?.funnel ?? []
  const priorityRows = byPriority.data?.rows ?? []
  const actionRows = actionDist.data?.rows ?? []

  return (
    <div className="space-y-6">
      {/* KPI strip */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <Kpi label="Revenue Analysed" value={fmtMoney(k.revenue_analysed)} sub={`${k.rollout_level >= 1 ? 'deterministic core' : ''}`} icon="₹" />
        <Kpi label="Leakage Detected" value={fmtMoney(k.leakage_detected)} tone="red" icon="⚠" />
        <Kpi label="Recoverable Amount" value={fmtMoney(k.recoverable_amount)} tone="amber" icon="◎" />
        <Kpi label="Money Recovered" value={fmtMoney(k.recovered_amount)} tone="green" icon="✓" />
        <Kpi label="Recovery Rate" value={fmtPct(k.recovery_rate)} tone="blue" icon="↗" />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Open Cases" value={String(k.cases_open)} sub="awaiting action" />
        <Kpi label="Approval Queue" value={String(k.pending_approvals)} tone="amber" sub="human decisions pending" />
        <Kpi label="Failed Actions" value={String(k.failed_actions)} tone="red" sub="recovery failures" />
        <Kpi label="Human Escalations" value={String(k.human_escalations)} tone="amber" />
      </div>

      {/* charts row 1 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Leakage by category — potential vs recovered">
          {catRows.length === 0 ? <EmptyState text="No cases" /> : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={catRows} margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
                <XAxis dataKey="category" tick={{ fill: '#94a3b8', fontSize: 10 }} interval={0} angle={-12} dy={8} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={(v: number) => `₹${(v / 1000).toFixed(0)}k`} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }}
                  formatter={(v, name) => [fmtMoney(Number(v)), name === 'potential' ? 'Potential' : 'Recovered'] as [string, string]} />
                <Legend wrapperStyle={{ fontSize: 11 }} formatter={(v) => v === 'potential' ? 'Potential' : 'Recovered'} />
                <Bar dataKey="potential" fill="#f472b6" radius={[3, 3, 0, 0]} />
                <Bar dataKey="recovered" fill="#34d399" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Recovery funnel">
          {funnelRows.length === 0 ? <EmptyState text="No data" /> : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={funnelRows} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
                <XAxis type="number" tick={{ fill: '#94a3b8', fontSize: 10 }} allowDecimals={false} />
                <YAxis type="category" dataKey="stage" tick={{ fill: '#94a3b8', fontSize: 11 }} width={80} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="count" fill="#38bdf8" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      {/* charts row 2 */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Open cases by priority">
          {priorityRows.length === 0 ? <EmptyState text="No cases" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={priorityRows} dataKey="count" nameKey="priority"
                  cx="50%" cy="50%" innerRadius={45} outerRadius={80} paddingAngle={3}>
                  {priorityRows.map((_, i) => <Cell key={i} fill={CAT_COLORS[i % CAT_COLORS.length]} />)}
                </Pie>
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Agent action distribution">
          {actionRows.length === 0 ? <EmptyState text="No actions yet — run the agent" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={actionRows} margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
                <XAxis dataKey="action" tick={{ fill: '#94a3b8', fontSize: 9 }} interval={0} angle={-14} dy={9} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} allowDecimals={false} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="count" fill="#a78bfa" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Connector health">
          <div className="space-y-2">
            {Object.entries(connectors.data ?? {}).map(([id, h]) => (
              <div key={id} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950 px-3 py-2">
                <span className="text-xs font-medium text-slate-300">{id}</span>
                <span className={`flex items-center gap-1.5 text-[11px] ${h.healthy ? 'text-emerald-400' : 'text-slate-500'}`}>
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-current" />
                  {h.healthy ? 'Healthy' : h.detail?.slice(0, 24)}
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* deadline table */}
      <Card title="Cases approaching deadline">
        {(deadline.data?.rows ?? []).length === 0 ? <EmptyState text="No deadlines in window" /> : (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-left text-[10.5px] uppercase tracking-wider text-slate-500">
                <th className="py-1.5 pr-3">Case</th><th className="pr-3">Category</th>
                <th className="pr-3">Priority</th><th className="pr-3">Deadline</th>
                <th className="pr-3 text-right">Potential</th>
              </tr>
            </thead>
            <tbody>
              {(deadline.data?.rows ?? []).slice(0, 8).map(r => (
                <tr key={r.case_id} className="cursor-pointer border-b border-slate-800/50 hover:bg-slate-900"
                  onClick={() => navigate('case', r.case_id)}>
                  <td className="py-1.5 pr-3 font-mono text-sky-300">{r.case_id}</td>
                  <td className="pr-3">{r.category}</td>
                  <td className="pr-3"><Badge>{r.priority}</Badge></td>
                  <td className="pr-3 text-slate-400">{r.days_left >= 0 ? `${r.days_left}d left` : `${-r.days_left}d OVERDUE`}</td>
                  <td className="pr-3 text-right tabular-nums text-rose-300">{fmtMoney(r.potential_leakage)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}
