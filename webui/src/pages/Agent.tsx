import { useQuery } from '@tanstack/react-query'
import { Api, fmtMoney, fmtTime, can, type AgentRun } from '../api'
import { Badge, Card, EmptyState, ErrorBox, Spinner } from '../components'
import { navigate } from '../App'

export function AgentPage() {
  const runs = useQuery({
    queryKey: ['agent-runs'],
    queryFn: () => Api.get<{ runs: AgentRun[] }>('/api/v1/agent/runs?limit=100'),
    refetchInterval: 15_000,
  })
  const tools = useQuery({
    queryKey: ['agent-tools'],
    queryFn: () => Api.get<{ tools: Record<string, unknown>[] }>('/api/v1/agent/tools'),
  })

  const canRun = can('run_agent', Api.role())

  return (
    <div className="space-y-4">
      {runs.isError && <ErrorBox msg={(runs.error as Error).message} />}
      {runs.isLoading && <Spinner />}

      <Card title="Recent agent runs">
        {(runs.data?.runs ?? []).length === 0 ? <EmptyState text="No agent runs yet" /> : (
          <div className="max-h-[45vh] overflow-auto">
            <table className="w-full text-[11px]">
              <thead className="sticky top-0 bg-slate-900">
                <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500">
                  {['Run', 'Case', 'LLM', 'Status', 'Proposed', 'Executed', 'Verified', 'Recovered', 'When'].map(h => (
                    <th key={h} className="px-2 py-1.5">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...runs.data!.runs].reverse().slice(0, 50).map(r => (
                  <tr key={r.run_id} className="cursor-pointer border-t border-slate-800/50 hover:bg-slate-900/50"
                    onClick={() => navigate('case', r.case_id)}>
                    <td className="px-2 py-1 font-mono text-slate-400">{r.run_id}</td>
                    <td className="px-2 py-1 font-mono text-sky-300">{r.case_id}</td>
                    <td className="px-2 py-1 text-slate-500">{r.llm_provider}/{r.llm_model}</td>
                    <td className="px-2 py-1"><Badge>{r.status}</Badge></td>
                    <td className="px-2 py-1 font-mono text-slate-400">{r.proposed_action || '—'}</td>
                    <td className="px-2 py-1 font-mono">{r.executed_action || '—'}</td>
                    <td className="px-2 py-1">{r.verification_status ? <Badge>{r.verification_status}</Badge> : '—'}</td>
                    <td className="px-2 py-1 text-right tabular-nums text-emerald-300">{Number(r.recovered_amount) ? fmtMoney(r.recovered_amount) : '—'}</td>
                    <td className="whitespace-nowrap px-2 py-1 text-slate-500">{fmtTime(r.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title={`Tool registry — ${tools.data?.tools.length ?? 0} registered tools`}>
        {!tools.data ? <Spinner /> : (
          <div className="max-h-[50vh] overflow-auto">
            <table className="w-full text-[11px]">
              <thead className="sticky top-0 bg-slate-900">
                <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500">
                  {['Tool', 'Risk', 'Approval', 'Categories', 'Side effects', 'Idempotency'].map(h => (
                    <th key={h} className="px-2 py-1.5">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tools.data!.tools.map((t: Record<string, any>) => (
                  <tr key={t.tool_name} className="border-t border-slate-800/50">
                    <td className="px-2 py-1 font-mono text-sky-300">{t.tool_name}</td>
                    <td className="px-2 py-1">{t.risk_level}</td>
                    <td className="px-2 py-1 text-slate-400">{t.approval_requirement}</td>
                    <td className="px-2 py-1 text-slate-500">{Array.isArray(t.allowed_case_categories) ? t.allowed_case_categories.join(', ') : t.allowed_case_categories}</td>
                    <td className="px-2 py-1 text-slate-500">{t.side_effects}</td>
                    <td className="px-2 py-1 font-mono text-[9.5px] text-slate-600">{t.idempotency_rule}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {!canRun && <p className="text-xs text-amber-400">Your role can view agent activity but cannot trigger runs (backend enforced).</p>}
    </div>
  )
}
