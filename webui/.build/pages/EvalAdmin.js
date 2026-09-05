import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from '@tanstack/react-query';
import { Api, can } from '../api';
import { Card, EmptyState, ErrorBox, Spinner } from '../components';
export function EvalAdminPage() {
    const canEval = can('eval', Api.role());
    const scorecard = useQuery({
        queryKey: ['scorecard'],
        queryFn: () => Api.get('/api/v1/eval/scorecard'),
        enabled: canEval,
        retry: false,
    });
    if (!canEval) {
        return _jsx(EmptyState, { text: "Evaluation / Admin requires the evaluator or admin role (backend enforced)." });
    }
    if (scorecard.isLoading)
        return _jsx(Spinner, {});
    if (scorecard.isError)
        return _jsx(ErrorBox, { msg: scorecard.error.message });
    const s = scorecard.data ?? {};
    const fmtBlock = (obj, title) => (_jsx(Card, { title: title, children: !obj ? _jsx(EmptyState, { text: "not present in scorecard" }) : (_jsx("table", { className: "w-full text-xs", children: _jsx("tbody", { children: Object.entries(obj).map(([k2, v]) => (_jsxs("tr", { className: "border-t border-slate-800/50", children: [_jsx("td", { className: "py-1.5 text-slate-500", children: k2 }), _jsx("td", { className: "py-1.5 text-right tabular-nums text-slate-200", children: typeof v === 'number' ? (v < 1 && v > 0 ? v.toFixed(4) : v.toLocaleString('en-IN')) : String(v ?? '—') })] }, k2))) }) })) }));
    return (_jsxs("div", { className: "space-y-4", children: [_jsx("p", { className: "text-xs text-slate-500", children: "Scoring against the hidden ground truth. The ground truth is sealed: the production agent cannot read it (RLS-restricted; structurally absent from agent payloads). The same evaluation runs across agent versions \u2014 results are comparable." }), _jsxs("div", { className: "grid gap-4 md:grid-cols-2 xl:grid-cols-3", children: [fmtBlock(s.detection, 'Detection'), fmtBlock(s.categories, 'Categories'), fmtBlock(s.amounts, 'Amounts'), fmtBlock(s.actions, 'Actions'), fmtBlock(s.recovery, 'Recovery'), fmtBlock(s.safety, 'Safety')] })] }));
}
