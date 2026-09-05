import { useQuery } from '@tanstack/react-query'
import { Api, fmtMoney, fmtPct, type Kpis, type LedgerRow } from '../api'
import { Card, EmptyState, ErrorBox, Kpi, Spinner } from '../components'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { navigate } from '../App'

export function RecoveryPage() {
  const kpis = useQuery({
    queryKey: ['kpis'],
    queryFn: () => Api.get<{ kpis: Kpis }>('/api/v1/dashboard/summary'),
  })
  const ledger = useQuery({
    queryKey: ['ledger'],
    queryFn: () => Api.get<{ ledger: LedgerRow[] }>('/api/v1/recovery/ledger'),
  })
  const byCat = useQuery({
    queryKey: ['leakage-by-category'],
    queryFn: () => Api.get<{ rows: { category: string; count: number; potential: number; recovered: number }[] }>('/api/v1/analytics/leakage-by-category'),
  })

  if (kpis.isError) return <ErrorBox msg={(kpis.error as Error).message} />
  if (kpis.isLoading) return <Spinner />

  const k = kpis.data!.kpis
  const rows = ledger.data?.ledger ?? []
  const catRows = (byCat.data?.rows ?? []).map(r => ({
    category: r.category,
    potential: r.potential,
    recovered: r.recovered,
    rate: r.potential > 0 ? (r.recovered / r.potential) : 0,
  }))

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Potential Recovery" value={fmtMoney(k.recoverable_amount)} tone="amber" />
        <Kpi label="Recovery Initiated" value={fmtMoney(k.recovery_initiated)} tone="blue" />
        <Kpi label="Recovered (verified)" value={fmtMoney(k.recovered_amount)} tone="green" />
        <Kpi label="Unrecovered" value={fmtMoney(k.unrecovered_amount)} tone="red" />
        <Kpi label="Recovery Rate" value={fmtPct(k.recovery_rate)} tone="blue" />
        <Kpi label="Success Rate" value={k.agent_actions ? fmtPct(1 - k.failed_actions / Math.max(k.agent_actions, 1)) : '—'} tone="green" />
      </div>

      <Card title="Recovery by category — potential vs verified recovered">
        {catRows.length === 0 ? <EmptyState text="No data" /> : (
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={catRows} margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
              <XAxis dataKey="category" tick={{ fill: '#94a3b8', fontSize: 10 }} interval={0} angle={-12} dy={8} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={(v: number) => `₹${(v / 1000).toFixed(0)}k`} />
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }}
                formatter={(v, name) => [fmtMoney(Number(v)), name === 'potential' ? 'Potential' : 'Recovered'] as [string, string]} />
              <Bar dataKey="potential" fill="#fbbf24" radius={[3, 3, 0, 0]} />
              <Bar dataKey="recovered" fill="#34d399" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </Card>

      <Card title={`Recovery ledger — ${rows.length} verified entries`}>
        {rows.length === 0 ? <EmptyState text="Ledger empty — recoveries appear only after verification observes the financial effect" /> : (
          <div className="max-h-[50vh] overflow-auto">
            <table className="w-full text-[11px]">
              <thead className="sticky top-0 bg-slate-900">
                <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500">
                  {['Ledger', 'Case', 'Source', 'Amount', 'Status', 'Bank ref', 'Recorded'].map(h => (
                    <th key={h} className="px-2 py-1.5">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...rows].reverse().map(l => (
                  <tr key={l.ledger_id} className="cursor-pointer border-t border-slate-800/50 hover:bg-slate-900/50"
                    onClick={() => navigate('case', l.case_id)}>
                    <td className="px-2 py-1 font-mono text-slate-400">{l.ledger_id}</td>
                    <td className="px-2 py-1 font-mono text-sky-300">{l.case_id}</td>
                    <td className="px-2 py-1 text-slate-400">{l.source}</td>
                    <td className="px-2 py-1 text-right tabular-nums text-emerald-300">{fmtMoney(l.amount)}</td>
                    <td className="px-2 py-1">{l.status}</td>
                    <td className="px-2 py-1 font-mono text-slate-400">{l.bank_reference || '—'}</td>
                    <td className="whitespace-nowrap px-2 py-1 text-slate-500">{(l.recorded_at || '').replace('T', ' ').slice(0, 16)}</td>
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
