import { useQuery } from '@tanstack/react-query'
import { Api, KEY_ROLES, ROLE_CAPS, can } from '../api'
import { Card, EmptyState } from '../components'

export function SettingsPage() {
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: () => Api.get<Record<string, unknown>>('/health'),
  })

  const role = Api.role()

  return (
    <div className="space-y-5">
      <Card title="Runtime">
        <dl className="grid gap-2 text-xs md:grid-cols-2">
          {Object.entries(health ?? {}).map(([k2, v]) => (
            <div key={k2} className="flex justify-between rounded-lg border border-slate-800 bg-slate-950 px-3 py-2">
              <dt className="text-slate-500">{k2}</dt>
              <dd className="font-mono text-slate-300">{String(v)}</dd>
            </div>
          ))}
        </dl>
      </Card>

      <Card title="Role matrix (frontend visibility only — the backend is authoritative)">
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500">
                <th className="px-2 py-1.5">Role</th><th>Capabilities</th><th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(ROLE_CAPS).map(([r, caps]) => (
                <tr key={r} className={`border-t border-slate-800/50 ${r === role ? 'bg-sky-500/5' : ''}`}>
                  <td className="px-2 py-1.5 font-mono text-sky-300">{r}</td>
                  <td className="px-2 py-1.5 text-slate-400">{caps.join(', ')}</td>
                  <td className="px-2 py-1.5 text-slate-500">
                    {r === 'viewer' && 'read-only — cannot execute or approve'}
                    {r === 'analyst' && 'can trigger agent runs, cannot approve'}
                    {r === 'finance_operator' && 'operational actions per policy'}
                    {r === 'finance_lead' && 'approval authority'}
                    {r === 'admin' && 'full administration'}
                    {r === 'agent' && 'machine workflow only — restricted server-side'}
                    {r === 'evaluator' && 'evaluation-only — no production actions'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Rollout levels">
        <div className="space-y-1.5 text-[11px] text-slate-400">
          {[
            [1, 'Synthetic-only — side-effecting tools blocked'],
            [2, 'Sandbox connectors'],
            [3, 'Live read-only'],
            [4, 'Shadow mode — proposals recorded, zero side effects'],
            [5, 'Approved recovery execution (human approval gates active)'],
            [6, 'Limited autonomous actions within policy caps'],
            [7, 'Production bounded autonomy'],
          ].map(([lvl, desc]) => (
            <div key={lvl} className={`flex gap-3 rounded-lg border px-3 py-1.5
              ${Number(health?.rollout_level) === lvl ? 'border-sky-500/40 bg-sky-500/10' : 'border-slate-800 bg-slate-950'}`}>
              <span className="font-mono text-sky-300">L{lvl}</span>
              <span>{desc}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card title="API key (dev session)">
        <p className="text-[11px] text-slate-500">
          Development uses static demo keys ({Object.keys(KEY_ROLES).join(', ')}).
          Production uses Supabase Auth — the frontend never holds database credentials,
          and every privileged call is re-checked server-side.
        </p>
        {!can('read', role) && <EmptyState text="No valid key — select a role in the header" />}
      </Card>
    </div>
  )
}
