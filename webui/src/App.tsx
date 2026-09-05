import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Api, can, type Role } from './api'
import { CaseDetailPage, CaseListPage } from './pages/Cases'
import { CommandCenter } from './pages/CommandCenter'
import { TransactionExplorer } from './pages/Explorer'
import { ApprovalsPage } from './pages/Approvals'
import { ConnectorsPage } from './pages/Connectors'
import { AuditPage } from './pages/Audit'
import { AgentPage } from './pages/Agent'
import { VerificationPage } from './pages/Verification'
import { RecoveryPage } from './pages/Recovery'
import { EvalAdminPage } from './pages/EvalAdmin'
import { SettingsPage } from './pages/Settings'

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 15_000 } },
})

export type Page =
  | 'command' | 'cases' | 'case' | 'explorer' | 'pipeline'
  | 'approvals' | 'agent' | 'connectors' | 'verification' | 'audit'
  | 'eval' | 'settings'

interface NavItem { id: Page; label: string; icon: string; cap: string }

const NAV: NavItem[] = [
  { id: 'command', label: 'Command Center', icon: '◉', cap: 'read' },
  { id: 'cases', label: 'Recovery Cases', icon: '▤', cap: 'read' },
  { id: 'explorer', label: 'Transaction Explorer', icon: '⌕', cap: 'read' },
  { id: 'pipeline', label: 'Recovery Pipeline', icon: '⇉', cap: 'read' },
  { id: 'approvals', label: 'Approvals', icon: '✓', cap: 'read' },
  { id: 'agent', label: 'Agent Activity', icon: '⚙', cap: 'read' },
  { id: 'connectors', label: 'Connectors', icon: '⇄', cap: 'read' },
  { id: 'verification', label: 'Verification', icon: '✔', cap: 'read' },
  { id: 'audit', label: 'Audit Trail', icon: '⛓', cap: 'read' },
  { id: 'eval', label: 'Evaluation / Admin', icon: '★', cap: 'eval' },
  { id: 'settings', label: 'Settings', icon: '⚒', cap: 'read' },
]

export function navigate(page: Page, arg?: string) {
  window.dispatchEvent(new CustomEvent('rg-nav', { detail: { page, arg } }))
}

function Shell() {
  const [page, setPage] = useState<Page>('command')
  const [caseArg, setCaseArg] = useState<string>('')
  const [role, setRole] = useState<Role | null>(Api.role())

  useEffect(() => {
    const h = (e: Event) => {
      const d = (e as CustomEvent).detail
      setPage(d.page)
      if (d.arg) setCaseArg(d.arg)
    }
    window.addEventListener('rg-nav', h)
    return () => window.removeEventListener('rg-nav', h)
  }, [])

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: () => Api.get<{ status: string; rollout_level: number; llm_provider: string }>('/health'),
    refetchInterval: 30_000,
  })

  const visible = NAV.filter(n => can(n.cap, role))

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 shrink-0 flex-col border-r border-slate-800 bg-slate-950">
        <div className="border-b border-slate-800 px-4 py-4">
          <div className="text-sm font-bold text-sky-400">REVENUE GUARD</div>
          <div className="text-[10px] text-slate-500">AI Revenue Recovery</div>
        </div>
        <nav className="flex-1 space-y-0.5 p-2">
          {visible.map(n => (
            <button key={n.id}
              onClick={() => setPage(n.id)}
              className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] transition
                ${page === n.id || (page === 'case' && n.id === 'cases')
                  ? 'bg-sky-500/15 text-sky-300'
                  : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'}`}>
              <span className="w-4 text-center">{n.icon}</span>{n.label}
            </button>
          ))}
        </nav>
        <div className="border-t border-slate-800 p-3 text-[10.5px] text-slate-500">
          <div className="flex justify-between">
            <span>rollout</span>
            <span className="text-slate-300">L{health?.rollout_level ?? '—'}</span>
          </div>
          <div className="flex justify-between">
            <span>LLM</span>
            <span className="text-slate-300">{health?.llm_provider ?? '—'}</span>
          </div>
          <div className={`mt-1 flex items-center gap-1.5 ${health?.status === 'ok' ? 'text-emerald-400' : 'text-rose-400'}`}>
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-current" />
            API {health?.status ?? 'connecting…'}
          </div>
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-x-hidden">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-800 bg-slate-950/90 px-6 py-3 backdrop-blur">
          <div className="text-[15px] font-semibold text-slate-100">
            {NAV.find(n => n.id === (page === 'case' ? 'cases' : page))?.label ?? 'Command Center'}
          </div>
          <div className="flex items-center gap-3 text-xs">
            {role && (
              <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 font-medium text-sky-300">
                {role}
              </span>
            )}
            <select
              className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300"
              value={Api.key()}
              onChange={e => { Api.setKey(e.target.value); setRole(Api.role()); queryClient.clear() }}>
              <option value="rg-admin-key">admin</option>
              <option value="rg-finance-key">finance_lead</option>
              <option value="rg-analyst-key">analyst</option>
              <option value="rg-viewer-key">viewer</option>
              <option value="rg-evaluator-key">evaluator</option>
            </select>
          </div>
        </header>
        <div className="p-6">
          {page === 'command' && <CommandCenter />}
          {page === 'cases' && <CaseListPage />}
          {page === 'case' && <CaseDetailPage caseId={caseArg} />}
          {page === 'explorer' && <TransactionExplorer />}
          {page === 'pipeline' && <RecoveryPage />}
          {page === 'approvals' && <ApprovalsPage />}
          {page === 'agent' && <AgentPage />}
          {page === 'connectors' && <ConnectorsPage />}
          {page === 'verification' && <VerificationPage />}
          {page === 'audit' && <AuditPage />}
          {page === 'eval' && <EvalAdminPage />}
          {page === 'settings' && <SettingsPage />}
        </div>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Shell />
    </QueryClientProvider>
  )
}
