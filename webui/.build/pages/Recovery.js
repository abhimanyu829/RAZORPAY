import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from '@tanstack/react-query';
import { Api, fmtMoney, fmtPct } from '../api';
import { Card, EmptyState, ErrorBox, Kpi, Spinner } from '../components';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { navigate } from '../App';
export function RecoveryPage() {
    const kpis = useQuery({
        queryKey: ['kpis'],
        queryFn: () => Api.get('/api/v1/dashboard/summary'),
    });
    const ledger = useQuery({
        queryKey: ['ledger'],
        queryFn: () => Api.get('/api/v1/recovery/ledger'),
    });
    const byCat = useQuery({
        queryKey: ['leakage-by-category'],
        queryFn: () => Api.get('/api/v1/analytics/leakage-by-category'),
    });
    if (kpis.isError)
        return _jsx(ErrorBox, { msg: kpis.error.message });
    if (kpis.isLoading)
        return _jsx(Spinner, {});
    const k = kpis.data.kpis;
    const rows = ledger.data?.ledger ?? [];
    const catRows = (byCat.data?.rows ?? []).map(r => ({
        category: r.category,
        potential: r.potential,
        recovered: r.recovered,
        rate: r.potential > 0 ? (r.recovered / r.potential) : 0,
    }));
    return (_jsxs("div", { className: "space-y-5", children: [_jsxs("div", { className: "grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6", children: [_jsx(Kpi, { label: "Potential Recovery", value: fmtMoney(k.recoverable_amount), tone: "amber" }), _jsx(Kpi, { label: "Recovery Initiated", value: fmtMoney(k.recovery_initiated), tone: "blue" }), _jsx(Kpi, { label: "Recovered (verified)", value: fmtMoney(k.recovered_amount), tone: "green" }), _jsx(Kpi, { label: "Unrecovered", value: fmtMoney(k.unrecovered_amount), tone: "red" }), _jsx(Kpi, { label: "Recovery Rate", value: fmtPct(k.recovery_rate), tone: "blue" }), _jsx(Kpi, { label: "Success Rate", value: k.agent_actions ? fmtPct(1 - k.failed_actions / Math.max(k.agent_actions, 1)) : '—', tone: "green" })] }), _jsx(Card, { title: "Recovery by category \u2014 potential vs verified recovered", children: catRows.length === 0 ? _jsx(EmptyState, { text: "No data" }) : (_jsx(ResponsiveContainer, { width: "100%", height: 240, children: _jsxs(BarChart, { data: catRows, margin: { top: 4, right: 8, left: 8, bottom: 4 }, children: [_jsx(XAxis, { dataKey: "category", tick: { fill: '#94a3b8', fontSize: 10 }, interval: 0, angle: -12, dy: 8 }), _jsx(YAxis, { tick: { fill: '#94a3b8', fontSize: 10 }, tickFormatter: (v) => `₹${(v / 1000).toFixed(0)}k` }), _jsx(Tooltip, { contentStyle: { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }, formatter: (v, name) => [fmtMoney(Number(v)), name === 'potential' ? 'Potential' : 'Recovered'] }), _jsx(Bar, { dataKey: "potential", fill: "#fbbf24", radius: [3, 3, 0, 0] }), _jsx(Bar, { dataKey: "recovered", fill: "#34d399", radius: [3, 3, 0, 0] })] }) })) }), _jsx(Card, { title: `Recovery ledger — ${rows.length} verified entries`, children: rows.length === 0 ? _jsx(EmptyState, { text: "Ledger empty \u2014 recoveries appear only after verification observes the financial effect" }) : (_jsx("div", { className: "max-h-[50vh] overflow-auto", children: _jsxs("table", { className: "w-full text-[11px]", children: [_jsx("thead", { className: "sticky top-0 bg-slate-900", children: _jsx("tr", { className: "text-left text-[10px] uppercase tracking-wider text-slate-500", children: ['Ledger', 'Case', 'Source', 'Amount', 'Status', 'Bank ref', 'Recorded'].map(h => (_jsx("th", { className: "px-2 py-1.5", children: h }, h))) }) }), _jsx("tbody", { children: [...rows].reverse().map(l => (_jsxs("tr", { className: "cursor-pointer border-t border-slate-800/50 hover:bg-slate-900/50", onClick: () => navigate('case', l.case_id), children: [_jsx("td", { className: "px-2 py-1 font-mono text-slate-400", children: l.ledger_id }), _jsx("td", { className: "px-2 py-1 font-mono text-sky-300", children: l.case_id }), _jsx("td", { className: "px-2 py-1 text-slate-400", children: l.source }), _jsx("td", { className: "px-2 py-1 text-right tabular-nums text-emerald-300", children: fmtMoney(l.amount) }), _jsx("td", { className: "px-2 py-1", children: l.status }), _jsx("td", { className: "px-2 py-1 font-mono text-slate-400", children: l.bank_reference || '—' }), _jsx("td", { className: "whitespace-nowrap px-2 py-1 text-slate-500", children: (l.recorded_at || '').replace('T', ' ').slice(0, 16) })] }, l.ledger_id))) })] }) })) })] }));
}
