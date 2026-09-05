import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Api, can } from './api';
import { CaseDetailPage, CaseListPage } from './pages/Cases';
import { CommandCenter } from './pages/CommandCenter';
import { TransactionExplorer } from './pages/Explorer';
import { ApprovalsPage } from './pages/Approvals';
import { ConnectorsPage } from './pages/Connectors';
import { AuditPage } from './pages/Audit';
import { AgentPage } from './pages/Agent';
import { VerificationPage } from './pages/Verification';
import { RecoveryPage } from './pages/Recovery';
import { EvalAdminPage } from './pages/EvalAdmin';
import { SettingsPage } from './pages/Settings';
const queryClient = new QueryClient({
    defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 15_000 } },
});
const NAV = [
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
];
export function navigate(page, arg) {
    window.dispatchEvent(new CustomEvent('rg-nav', { detail: { page, arg } }));
}
function Shell() {
    const [page, setPage] = useState('command');
    const [caseArg, setCaseArg] = useState('');
    const [role, setRole] = useState(Api.role());
    useEffect(() => {
        const h = (e) => {
            const d = e.detail;
            setPage(d.page);
            if (d.arg)
                setCaseArg(d.arg);
        };
        window.addEventListener('rg-nav', h);
        return () => window.removeEventListener('rg-nav', h);
    }, []);
    const { data: health } = useQuery({
        queryKey: ['health'],
        queryFn: () => Api.get('/health'),
        refetchInterval: 30_000,
    });
    const visible = NAV.filter(n => can(n.cap, role));
    return (_jsxs("div", { className: "flex min-h-screen", children: [_jsxs("aside", { className: "flex w-56 shrink-0 flex-col border-r border-slate-800 bg-slate-950", children: [_jsxs("div", { className: "border-b border-slate-800 px-4 py-4", children: [_jsx("div", { className: "text-sm font-bold text-sky-400", children: "REVENUE GUARD" }), _jsx("div", { className: "text-[10px] text-slate-500", children: "AI Revenue Recovery" })] }), _jsx("nav", { className: "flex-1 space-y-0.5 p-2", children: visible.map(n => (_jsxs("button", { onClick: () => setPage(n.id), className: `flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] transition
                ${page === n.id || (page === 'case' && n.id === 'cases')
                                ? 'bg-sky-500/15 text-sky-300'
                                : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'}`, children: [_jsx("span", { className: "w-4 text-center", children: n.icon }), n.label] }, n.id))) }), _jsxs("div", { className: "border-t border-slate-800 p-3 text-[10.5px] text-slate-500", children: [_jsxs("div", { className: "flex justify-between", children: [_jsx("span", { children: "rollout" }), _jsxs("span", { className: "text-slate-300", children: ["L", health?.rollout_level ?? '—'] })] }), _jsxs("div", { className: "flex justify-between", children: [_jsx("span", { children: "LLM" }), _jsx("span", { className: "text-slate-300", children: health?.llm_provider ?? '—' })] }), _jsxs("div", { className: `mt-1 flex items-center gap-1.5 ${health?.status === 'ok' ? 'text-emerald-400' : 'text-rose-400'}`, children: [_jsx("span", { className: "inline-block h-1.5 w-1.5 rounded-full bg-current" }), "API ", health?.status ?? 'connecting…'] })] })] }), _jsxs("main", { className: "min-w-0 flex-1 overflow-x-hidden", children: [_jsxs("header", { className: "sticky top-0 z-10 flex items-center justify-between border-b border-slate-800 bg-slate-950/90 px-6 py-3 backdrop-blur", children: [_jsx("div", { className: "text-[15px] font-semibold text-slate-100", children: NAV.find(n => n.id === (page === 'case' ? 'cases' : page))?.label ?? 'Command Center' }), _jsxs("div", { className: "flex items-center gap-3 text-xs", children: [role && (_jsx("span", { className: "rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 font-medium text-sky-300", children: role })), _jsxs("select", { className: "rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300", value: Api.key(), onChange: e => { Api.setKey(e.target.value); setRole(Api.role()); queryClient.clear(); }, children: [_jsx("option", { value: "rg-admin-key", children: "admin" }), _jsx("option", { value: "rg-finance-key", children: "finance_lead" }), _jsx("option", { value: "rg-analyst-key", children: "analyst" }), _jsx("option", { value: "rg-viewer-key", children: "viewer" }), _jsx("option", { value: "rg-evaluator-key", children: "evaluator" })] })] })] }), _jsxs("div", { className: "p-6", children: [page === 'command' && _jsx(CommandCenter, {}), page === 'cases' && _jsx(CaseListPage, {}), page === 'case' && _jsx(CaseDetailPage, { caseId: caseArg }), page === 'explorer' && _jsx(TransactionExplorer, {}), page === 'pipeline' && _jsx(RecoveryPage, {}), page === 'approvals' && _jsx(ApprovalsPage, {}), page === 'agent' && _jsx(AgentPage, {}), page === 'connectors' && _jsx(ConnectorsPage, {}), page === 'verification' && _jsx(VerificationPage, {}), page === 'audit' && _jsx(AuditPage, {}), page === 'eval' && _jsx(EvalAdminPage, {}), page === 'settings' && _jsx(SettingsPage, {})] })] })] }));
}
export default function App() {
    return (_jsx(QueryClientProvider, { client: queryClient, children: _jsx(Shell, {}) }));
}
