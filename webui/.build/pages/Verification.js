import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from '@tanstack/react-query';
import { Api, fmtMoney, fmtTime } from '../api';
import { Badge, Card, EmptyState, ErrorBox, Spinner } from '../components';
import { navigate } from '../App';
const STAGES = ['SUBMITTED', 'ACKNOWLEDGED', 'IN_PROGRESS', 'FINANCIAL_EFFECT_DETECTED', 'RECOVERY_VERIFIED'];
export function VerificationPage() {
    const { data, isLoading, isError, error } = useQuery({
        queryKey: ['verification-events'],
        queryFn: () => Api.get('/api/v1/verification/events?limit=500'),
        refetchInterval: 15_000,
    });
    if (isError)
        return _jsx(ErrorBox, { msg: error.message });
    if (isLoading)
        return _jsx(Spinner, {});
    const events = [...(data?.events ?? [])].reverse();
    return (_jsxs("div", { className: "space-y-4", children: [_jsxs(Card, { title: "Recovery verification pipeline", children: [_jsx("div", { className: "flex flex-wrap items-center gap-1.5 text-[11px]", children: STAGES.map((s, i) => (_jsxs("span", { className: "flex items-center gap-1.5", children: [i > 0 && _jsx("span", { className: "text-slate-600", children: "\u2192" }), _jsx("span", { className: "rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-slate-300", children: s })] }, s))) }), _jsx("p", { className: "mt-2 text-[11px] text-slate-500", children: "Recovery is only counted when the verification service observes the financial effect (e.g. a bank credit). A ledger entry cannot exist without verification evidence." })] }), events.length === 0 && _jsx(EmptyState, { text: "No verification events yet \u2014 execute a recovery action" }), _jsx("div", { className: "space-y-2", children: events.map(v => (_jsxs("div", { className: "cursor-pointer rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs hover:border-slate-700", onClick: () => navigate('case', v.case_id), children: [_jsxs("div", { className: "flex flex-wrap items-center gap-2.5", children: [_jsx("span", { className: "font-mono text-sky-300", children: v.verification_id }), _jsxs("span", { className: "text-slate-500", children: ["case ", v.case_id] }), _jsx(Badge, { children: v.status }), _jsx("span", { className: "text-slate-400", children: v.check_type }), v.observed_value && _jsx("span", { className: "tabular-nums text-emerald-300", children: fmtMoney(v.observed_value) }), _jsx("span", { className: "ml-auto text-slate-600", children: fmtTime(v.checked_at) })] }), v.notes && _jsx("div", { className: "mt-1 text-[11px] text-slate-500", children: v.notes })] }, v.verification_id))) })] }));
}
