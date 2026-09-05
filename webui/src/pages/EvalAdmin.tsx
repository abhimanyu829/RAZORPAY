import { useQuery } from '@tanstack/react-query'
import { Api, can } from '../api'
import { Card, EmptyState, ErrorBox, Spinner } from '../components'

export function EvalAdminPage() {
  const canEval = can('eval', Api.role())
  const scorecard = useQuery({
    queryKey: ['scorecard'],
    queryFn: () => Api.get<Record<string, unknown>>('/api/v1/eval/scorecard'),
    enabled: canEval,
    retry: false,
  })

  if (!canEval) {
    return <EmptyState text="Evaluation / Admin requires the evaluator or admin role (backend enforced)." />
  }

  if (scorecard.isLoading) return <Spinner />
  if (scorecard.isError) return <ErrorBox msg={(scorecard.error as Error).message} />

  const s = scorecard.data ?? {}

  const fmtBlock = (obj: Record<string, unknown> | undefined, title: string) => (
    <Card title={title}>
      {!obj ? <EmptyState text="not present in scorecard" /> : (
        <table className="w-full text-xs">
          <tbody>
            {Object.entries(obj).map(([k2, v]) => (
              <tr key={k2} className="border-t border-slate-800/50">
                <td className="py-1.5 text-slate-500">{k2}</td>
                <td className="py-1.5 text-right tabular-nums text-slate-200">
                  {typeof v === 'number' ? (v < 1 && v > 0 ? v.toFixed(4) : v.toLocaleString('en-IN')) : String(v ?? '—')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        Scoring against the hidden ground truth. The ground truth is sealed: the production agent
        cannot read it (RLS-restricted; structurally absent from agent payloads).
        The same evaluation runs across agent versions — results are comparable.
      </p>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {fmtBlock(s.detection as Record<string, unknown>, 'Detection')}
        {fmtBlock(s.categories as Record<string, unknown>, 'Categories')}
        {fmtBlock(s.amounts as Record<string, unknown>, 'Amounts')}
        {fmtBlock(s.actions as Record<string, unknown>, 'Actions')}
        {fmtBlock(s.recovery as Record<string, unknown>, 'Recovery')}
        {fmtBlock(s.safety as Record<string, unknown>, 'Safety')}
      </div>
    </div>
  )
}
