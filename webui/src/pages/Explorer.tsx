import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Api, fmtMoney } from '../api'
import { Badge, Card, EmptyState, Spinner } from '../components'
import { navigate } from '../App'

interface SearchMatch {
  type: string
  order?: Record<string, string>
  payment?: Record<string, string>
  settlement?: Record<string, string>
  bank?: Record<string, string>
  invoice?: Record<string, string>
  customer?: Record<string, string>
  case?: Record<string, string>
  cases?: Record<string, string>[]
  orders?: string[]
  flow?: {
    payments?: { payment_id: string; amount: string; method?: string; captured_at?: string
      fees: { fee_id: string; amount: string; tax_amount?: string }[]
      refunds: { refund_id: string; amount: string; status?: string }[]
      settlements: { settlement_id: string; amount: string; utr?: string }[] }[]
  }
}

export function TransactionExplorer() {
  const [q, setQ] = useState('')
  const [submitted, setSubmitted] = useState('')

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['search', submitted],
    queryFn: () => Api.get<{ matches: SearchMatch[] }>(`/api/v1/search?q=${encodeURIComponent(submitted)}`),
    enabled: submitted.length >= 2,
  })

  return (
    <div className="space-y-4">
      <form onSubmit={e => { e.preventDefault(); setSubmitted(q) }} className="flex gap-2">
        <input value={q} onChange={e => setQ(e.target.value)}
          placeholder="Search by order ID · payment ID · gateway ID · settlement ID · UTR · invoice · customer · case ID…"
          className="w-full rounded-xl border border-slate-700 bg-slate-900 px-4 py-2.5 text-sm outline-none placeholder:text-slate-600 focus:border-sky-500" />
        <button className="rounded-xl bg-sky-600 px-5 text-sm font-medium text-white hover:bg-sky-500">Search</button>
      </form>
      <p className="text-[11px] text-slate-500">
        Traverses the transaction graph: customer → order → payment → fee → refund → settlement → bank → invoice → GST → case.
      </p>

      {isLoading && <Spinner />}
      {isError && <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-300">{(error as Error).message}</div>}

      {submitted && !isLoading && (data?.matches ?? []).length === 0 && (
        <EmptyState text={`No matches for "${submitted}"`} />
      )}

      {(data?.matches ?? []).map((m, i) => (
        <Card key={i} title={`Match — ${m.type}`}>
          {m.type === 'ORDER' && (
            <div>
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                <span className="font-mono text-sky-300">{m.order?.order_id}</span>
                <span className="text-slate-400">{m.order?.order_number}</span>
                <Badge>{m.order?.status || '—'}</Badge>
                <span className="ml-auto tabular-nums">{fmtMoney(m.order?.gross_amount)}</span>
              </div>
              {m.flow?.payments?.map(p => (
                <div key={p.payment_id} className="rounded-lg border border-slate-800 bg-slate-950 p-2.5 text-[11px]">
                  <div className="flex justify-between">
                    <span className="font-mono text-sky-300">{p.payment_id} · {p.method}</span>
                    <span className="tabular-nums">{fmtMoney(p.amount)}</span>
                  </div>
                  {p.fees?.map(f => <div key={f.fee_id} className="flex justify-between pl-4 text-slate-400"><span>fee {f.fee_id}</span><span>-{fmtMoney(f.amount)}</span></div>)}
                  {p.refunds?.map(r => <div key={r.refund_id} className="flex justify-between pl-4 text-slate-400"><span>refund {r.refund_id}</span><span>-{fmtMoney(r.amount)}</span></div>)}
                  {p.settlements?.map(s => <div key={s.settlement_id} className="flex justify-between pl-4 text-emerald-300"><span>settle {s.settlement_id} · {s.utr}</span><span>{fmtMoney(s.amount)}</span></div>)}
                </div>
              ))}
              {(m.cases ?? []).length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {m.cases!.map(c => (
                    <button key={c.case_id} onClick={() => navigate('case', c.case_id)}
                      className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-0.5 text-[11px] text-amber-300 hover:bg-amber-500/20">
                      {c.case_id} · {c.category} · {fmtMoney(c.potential_leakage)}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {m.type === 'PAYMENT' && (
            <div className="flex flex-wrap gap-3 text-xs">
              <span className="font-mono text-sky-300">{m.payment?.payment_id}</span>
              <span className="text-slate-400">order {m.payment?.order_id}</span>
              <span className="tabular-nums">{fmtMoney(m.payment?.amount)}</span>
              <Badge>{m.payment?.status || ''}</Badge>
            </div>
          )}
          {m.type === 'SETTLEMENT' && (
            <div className="flex flex-wrap gap-3 text-xs">
              <span className="font-mono text-sky-300">{m.settlement?.settlement_id}</span>
              <span className="text-slate-400">UTR {m.settlement?.utr}</span>
              <span className="tabular-nums">{fmtMoney(m.settlement?.amount)}</span>
            </div>
          )}
          {m.type === 'BANK' && (
            <div className="flex flex-wrap gap-3 text-xs">
              <span className="font-mono text-sky-300">{m.bank?.bank_txn_id}</span>
              <span className="text-slate-400">UTR {m.bank?.utr}</span>
              <span className="tabular-nums">{fmtMoney(m.bank?.amount)}</span>
              <span className="text-slate-500">{m.bank?.value_date}</span>
            </div>
          )}
          {m.type === 'INVOICE' && (
            <div className="flex flex-wrap gap-3 text-xs">
              <span className="font-mono text-sky-300">{m.invoice?.invoice_id}</span>
              <span className="text-slate-400">{m.invoice?.invoice_number}</span>
              <span className="tabular-nums">{fmtMoney(m.invoice?.total_amount)}</span>
            </div>
          )}
          {m.type === 'CUSTOMER' && (
            <div className="flex flex-wrap gap-3 text-xs">
              <span className="font-mono text-sky-300">{m.customer?.customer_id}</span>
              <span className="text-slate-400">{m.customer?.email}</span>
              <span className="text-slate-500">{(m.orders ?? []).length} orders</span>
            </div>
          )}
          {m.type === 'CASE' && (
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <button className="font-mono text-sky-300 hover:underline" onClick={() => navigate('case', m.case?.case_id)}>
                {m.case?.case_id}
              </button>
              <Badge>{m.case?.status || ''}</Badge>
              <span>{m.case?.category}</span>
              <span className="tabular-nums text-rose-300">{fmtMoney(m.case?.potential_leakage)}</span>
            </div>
          )}
        </Card>
      ))}
    </div>
  )
}
