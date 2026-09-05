import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from '@tanstack/react-query';
import { Api, fmtMoney, fmtPct } from '../api';
import { Card, Kpi, Badge, EmptyState, ErrorBox, Spinner } from '../components';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend, } from 'recharts';
import { navigate } from '../App';
const CAT_COLORS = ['#38bdf8', '#f472b6', '#facc15', '#34d399', '#a78bfa', '#fb923c'];
export function CommandCenter() {
    const kpis = useQuery({
        queryKey: ['kpis'],
        queryFn: () => Api.get('/api/v1/dashboard/summary'),
        refetchInterval: 20_000,
    });
    const byCat = useQuery({
        queryKey: ['leakage-by-category'],
        queryFn: () => Api.get('/api/v1/analytics/leakage-by-category'),
    });
    const funnel = useQuery({
        queryKey: ['recovery-funnel'],
        queryFn: () => Api.get('/api/v1/analytics/recovery-funnel'),
    });
    const byPriority = useQuery({
        queryKey: ['cases-by-priority'],
        queryFn: () => Api.get('/api/v1/analytics/cases-by-priority'),
    });
    const actionDist = useQuery({
        queryKey: ['action-distribution'],
        queryFn: () => Api.get('/api/v1/analytics/action-distribution'),
    });
    const deadline = useQuery({
        queryKey: ['approaching-deadline'],
        queryFn: () => Api.get('/api/v1/analytics/approaching-deadline'),
    });
    const connectors = useQuery({
        queryKey: ['connector-health'],
        queryFn: () => Api.get('/api/v1/connectors/health'),
    });
    if (kpis.isError)
        return _jsx(ErrorBox, { msg: kpis.error.message });
    if (kpis.isLoading)
        return _jsx(Spinner, {});
    const k = kpis.data.kpis;
    const catRows = byCat.data?.rows ?? [];
    const funnelRows = funnel.data?.funnel ?? [];
    const priorityRows = byPriority.data?.rows ?? [];
    const actionRows = actionDist.data?.rows ?? [];
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("div", { className: "grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5", children: [_jsx(Kpi, { label: "Revenue Analysed", value: fmtMoney(k.revenue_analysed), sub: `${k.rollout_level >= 1 ? 'deterministic core' : ''}`, icon: "\u20B9" }), _jsx(Kpi, { label: "Leakage Detected", value: fmtMoney(k.leakage_detected), tone: "red", icon: "\u26A0" }), _jsx(Kpi, { label: "Recoverable Amount", value: fmtMoney(k.recoverable_amount), tone: "amber", icon: "\u25CE" }), _jsx(Kpi, { label: "Money Recovered", value: fmtMoney(k.recovered_amount), tone: "green", icon: "\u2713" }), _jsx(Kpi, { label: "Recovery Rate", value: fmtPct(k.recovery_rate), tone: "blue", icon: "\u2197" })] }), _jsxs("div", { className: "grid grid-cols-2 gap-3 md:grid-cols-4", children: [_jsx(Kpi, { label: "Open Cases", value: String(k.cases_open), sub: "awaiting action" }), _jsx(Kpi, { label: "Approval Queue", value: String(k.pending_approvals), tone: "amber", sub: "human decisions pending" }), _jsx(Kpi, { label: "Failed Actions", value: String(k.failed_actions), tone: "red", sub: "recovery failures" }), _jsx(Kpi, { label: "Human Escalations", value: String(k.human_escalations), tone: "amber" })] }), _jsxs("div", { className: "grid gap-4 lg:grid-cols-2", children: [_jsx(Card, { title: "Leakage by category \u2014 potential vs recovered", children: catRows.length === 0 ? _jsx(EmptyState, { text: "No cases" }) : (_jsx(ResponsiveContainer, { width: "100%", height: 260, children: _jsxs(BarChart, { data: catRows, margin: { top: 4, right: 8, left: 8, bottom: 4 }, children: [_jsx(XAxis, { dataKey: "category", tick: { fill: '#94a3b8', fontSize: 10 }, interval: 0, angle: -12, dy: 8 }), _jsx(YAxis, { tick: { fill: '#94a3b8', fontSize: 10 }, tickFormatter: (v) => `₹${(v / 1000).toFixed(0)}k` }), _jsx(Tooltip, { contentStyle: { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }, formatter: (v, name) => [fmtMoney(Number(v)), name === 'potential' ? 'Potential' : 'Recovered'] }), _jsx(Legend, { wrapperStyle: { fontSize: 11 }, formatter: (v) => v === 'potential' ? 'Potential' : 'Recovered' }), _jsx(Bar, { dataKey: "potential", fill: "#f472b6", radius: [3, 3, 0, 0] }), _jsx(Bar, { dataKey: "recovered", fill: "#34d399", radius: [3, 3, 0, 0] })] }) })) }), _jsx(Card, { title: "Recovery funnel", children: funnelRows.length === 0 ? _jsx(EmptyState, { text: "No data" }) : (_jsx(ResponsiveContainer, { width: "100%", height: 260, children: _jsxs(BarChart, { data: funnelRows, layout: "vertical", margin: { top: 4, right: 16, left: 8, bottom: 4 }, children: [_jsx(XAxis, { type: "number", tick: { fill: '#94a3b8', fontSize: 10 }, allowDecimals: false }), _jsx(YAxis, { type: "category", dataKey: "stage", tick: { fill: '#94a3b8', fontSize: 11 }, width: 80 }), _jsx(Tooltip, { contentStyle: { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 } }), _jsx(Bar, { dataKey: "count", fill: "#38bdf8", radius: [0, 4, 4, 0] })] }) })) })] }), _jsxs("div", { className: "grid gap-4 lg:grid-cols-3", children: [_jsx(Card, { title: "Open cases by priority", children: priorityRows.length === 0 ? _jsx(EmptyState, { text: "No cases" }) : (_jsx(ResponsiveContainer, { width: "100%", height: 220, children: _jsxs(PieChart, { children: [_jsx(Pie, { data: priorityRows, dataKey: "count", nameKey: "priority", cx: "50%", cy: "50%", innerRadius: 45, outerRadius: 80, paddingAngle: 3, children: priorityRows.map((_, i) => _jsx(Cell, { fill: CAT_COLORS[i % CAT_COLORS.length] }, i)) }), _jsx(Legend, { wrapperStyle: { fontSize: 11 } }), _jsx(Tooltip, { contentStyle: { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 } })] }) })) }), _jsx(Card, { title: "Agent action distribution", children: actionRows.length === 0 ? _jsx(EmptyState, { text: "No actions yet \u2014 run the agent" }) : (_jsx(ResponsiveContainer, { width: "100%", height: 220, children: _jsxs(BarChart, { data: actionRows, margin: { top: 4, right: 8, left: 8, bottom: 4 }, children: [_jsx(XAxis, { dataKey: "action", tick: { fill: '#94a3b8', fontSize: 9 }, interval: 0, angle: -14, dy: 9 }), _jsx(YAxis, { tick: { fill: '#94a3b8', fontSize: 10 }, allowDecimals: false }), _jsx(Tooltip, { contentStyle: { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 } }), _jsx(Bar, { dataKey: "count", fill: "#a78bfa", radius: [3, 3, 0, 0] })] }) })) }), _jsx(Card, { title: "Connector health", children: _jsx("div", { className: "space-y-2", children: Object.entries(connectors.data ?? {}).map(([id, h]) => (_jsxs("div", { className: "flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950 px-3 py-2", children: [_jsx("span", { className: "text-xs font-medium text-slate-300", children: id }), _jsxs("span", { className: `flex items-center gap-1.5 text-[11px] ${h.healthy ? 'text-emerald-400' : 'text-slate-500'}`, children: [_jsx("span", { className: "inline-block h-1.5 w-1.5 rounded-full bg-current" }), h.healthy ? 'Healthy' : h.detail?.slice(0, 24)] })] }, id))) }) })] }), _jsx(Card, { title: "Cases approaching deadline", children: (deadline.data?.rows ?? []).length === 0 ? _jsx(EmptyState, { text: "No deadlines in window" }) : (_jsxs("table", { className: "w-full text-xs", children: [_jsx("thead", { children: _jsxs("tr", { className: "border-b border-slate-800 text-left text-[10.5px] uppercase tracking-wider text-slate-500", children: [_jsx("th", { className: "py-1.5 pr-3", children: "Case" }), _jsx("th", { className: "pr-3", children: "Category" }), _jsx("th", { className: "pr-3", children: "Priority" }), _jsx("th", { className: "pr-3", children: "Deadline" }), _jsx("th", { className: "pr-3 text-right", children: "Potential" })] }) }), _jsx("tbody", { children: (deadline.data?.rows ?? []).slice(0, 8).map(r => (_jsxs("tr", { className: "cursor-pointer border-b border-slate-800/50 hover:bg-slate-900", onClick: () => navigate('case', r.case_id), children: [_jsx("td", { className: "py-1.5 pr-3 font-mono text-sky-300", children: r.case_id }), _jsx("td", { className: "pr-3", children: r.category }), _jsx("td", { className: "pr-3", children: _jsx(Badge, { children: r.priority }) }), _jsx("td", { className: "pr-3 text-slate-400", children: r.days_left >= 0 ? `${r.days_left}d left` : `${-r.days_left}d OVERDUE` }), _jsx("td", { className: "pr-3 text-right tabular-nums text-rose-300", children: fmtMoney(r.potential_leakage) })] }, r.case_id))) })] })) })] }));
}
