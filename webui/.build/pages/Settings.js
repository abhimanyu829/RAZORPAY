import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from '@tanstack/react-query';
import { Api, KEY_ROLES, ROLE_CAPS, can } from '../api';
import { Card, EmptyState } from '../components';
export function SettingsPage() {
    const { data: health } = useQuery({
        queryKey: ['health'],
        queryFn: () => Api.get('/health'),
    });
    const role = Api.role();
    return (_jsxs("div", { className: "space-y-5", children: [_jsx(Card, { title: "Runtime", children: _jsx("dl", { className: "grid gap-2 text-xs md:grid-cols-2", children: Object.entries(health ?? {}).map(([k2, v]) => (_jsxs("div", { className: "flex justify-between rounded-lg border border-slate-800 bg-slate-950 px-3 py-2", children: [_jsx("dt", { className: "text-slate-500", children: k2 }), _jsx("dd", { className: "font-mono text-slate-300", children: String(v) })] }, k2))) }) }), _jsx(Card, { title: "Role matrix (frontend visibility only \u2014 the backend is authoritative)", children: _jsx("div", { className: "overflow-x-auto", children: _jsxs("table", { className: "w-full text-[11px]", children: [_jsx("thead", { children: _jsxs("tr", { className: "text-left text-[10px] uppercase tracking-wider text-slate-500", children: [_jsx("th", { className: "px-2 py-1.5", children: "Role" }), _jsx("th", { children: "Capabilities" }), _jsx("th", { children: "Notes" })] }) }), _jsx("tbody", { children: Object.entries(ROLE_CAPS).map(([r, caps]) => (_jsxs("tr", { className: `border-t border-slate-800/50 ${r === role ? 'bg-sky-500/5' : ''}`, children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-sky-300", children: r }), _jsx("td", { className: "px-2 py-1.5 text-slate-400", children: caps.join(', ') }), _jsxs("td", { className: "px-2 py-1.5 text-slate-500", children: [r === 'viewer' && 'read-only — cannot execute or approve', r === 'analyst' && 'can trigger agent runs, cannot approve', r === 'finance_operator' && 'operational actions per policy', r === 'finance_lead' && 'approval authority', r === 'admin' && 'full administration', r === 'agent' && 'machine workflow only — restricted server-side', r === 'evaluator' && 'evaluation-only — no production actions'] })] }, r))) })] }) }) }), _jsx(Card, { title: "Rollout levels", children: _jsx("div", { className: "space-y-1.5 text-[11px] text-slate-400", children: [
                        [1, 'Synthetic-only — side-effecting tools blocked'],
                        [2, 'Sandbox connectors'],
                        [3, 'Live read-only'],
                        [4, 'Shadow mode — proposals recorded, zero side effects'],
                        [5, 'Approved recovery execution (human approval gates active)'],
                        [6, 'Limited autonomous actions within policy caps'],
                        [7, 'Production bounded autonomy'],
                    ].map(([lvl, desc]) => (_jsxs("div", { className: `flex gap-3 rounded-lg border px-3 py-1.5
              ${Number(health?.rollout_level) === lvl ? 'border-sky-500/40 bg-sky-500/10' : 'border-slate-800 bg-slate-950'}`, children: [_jsxs("span", { className: "font-mono text-sky-300", children: ["L", lvl] }), _jsx("span", { children: desc })] }, lvl))) }) }), _jsxs(Card, { title: "API key (dev session)", children: [_jsxs("p", { className: "text-[11px] text-slate-500", children: ["Development uses static demo keys (", Object.keys(KEY_ROLES).join(', '), "). Production uses Supabase Auth \u2014 the frontend never holds database credentials, and every privileged call is re-checked server-side."] }), !can('read', role) && _jsx(EmptyState, { text: "No valid key \u2014 select a role in the header" })] })] }));
}
