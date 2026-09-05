import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Api, fmtMoney, fmtTime, can } from '../api';
import { Badge, Card, EmptyState, ErrorBox, Spinner } from '../components';
import { navigate } from '../App';
export function ApprovalsPage() {
    const qc = useQueryClient();
    const [filter, setFilter] = useState('PENDING');
    const [note, setNote] = useState({});
    const role = Api.role();
    const canApprove = can('approve', role);
    const { data, isLoading, isError, error } = useQuery({
        queryKey: ['approvals'],
        queryFn: () => Api.get('/api/v1/approvals'),
        refetchInterval: 15_000,
    });
    const decide = useMutation({
        mutationFn: ({ id, decision }) => Api.post(`/api/v1/approvals/${id}/decide`, { decision, decided_by: role, note: note[id] || '' }),
        onSuccess: () => qc.invalidateQueries(),
    });
    if (isError)
        return _jsx(ErrorBox, { msg: error.message });
    if (isLoading)
        return _jsx(Spinner, {});
    const rows = (data?.approvals ?? []).filter(a => filter === 'ALL' || a.status === filter);
    return (_jsxs("div", { className: "space-y-4", children: [_jsxs("div", { className: "flex items-center gap-2 text-xs", children: [['PENDING', 'APPROVED', 'REJECTED', 'ALL'].map(f => (_jsx("button", { onClick: () => setFilter(f), className: `rounded-lg px-3 py-1.5 ${filter === f ? 'bg-sky-500/15 text-sky-300' : 'bg-slate-900 text-slate-400 hover:text-slate-200'}`, children: f }, f))), !canApprove && _jsx("span", { className: "ml-auto text-amber-400", children: "Your role cannot decide approvals (backend enforced)" })] }), decide.isError && _jsx(ErrorBox, { msg: decide.error.message }), rows.length === 0 && _jsx(EmptyState, { text: `No ${filter.toLowerCase()} approvals` }), _jsx("div", { className: "space-y-2", children: rows.map(a => (_jsxs(Card, { children: [_jsxs("div", { className: "flex flex-wrap items-center gap-3 text-xs", children: [_jsx("button", { className: "font-mono text-sky-300 hover:underline", onClick: () => a.case && navigate('case', a.case_id), children: a.case_id }), _jsx(Badge, { children: a.status }), _jsxs("span", { className: "text-slate-400", children: ["risk ", _jsx("span", { className: "font-mono", children: a.risk_level })] }), _jsx("span", { className: "tabular-nums text-amber-300", children: fmtMoney(a.amount) }), _jsxs("span", { className: "text-slate-500", children: ["requested ", fmtTime(a.requested_at), " by ", a.requested_by] }), a.decided_by && _jsxs("span", { className: "text-slate-500", children: ["\u2192 ", a.decided_by, " ", fmtTime(a.decided_at)] })] }), a.case && (_jsxs("div", { className: "mt-1.5 text-[11px] text-slate-400", children: [a.case.category, " \u00B7 potential recovery ", fmtMoney(a.case.potential_recovery), a.case.allowed_actions ? ` · allowed: ${a.case.allowed_actions.split('|').join(', ')}` : ''] })), a.status === 'PENDING' && canApprove && (_jsxs("div", { className: "mt-2.5 flex items-center gap-2 text-xs", children: [_jsx("input", { value: note[a.approval_id] || '', placeholder: "decision note (required for reject)", onChange: e => setNote(n => ({ ...n, [a.approval_id]: e.target.value })), className: "flex-1 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 outline-none focus:border-sky-500" }), _jsx("button", { disabled: decide.isPending, onClick: () => decide.mutate({ id: a.approval_id, decision: 'approve' }), className: "rounded-lg bg-emerald-600 px-3.5 py-1.5 font-medium text-white hover:bg-emerald-500 disabled:opacity-50", children: "Approve" }), _jsx("button", { disabled: decide.isPending || !(note[a.approval_id] || '').trim(), onClick: () => decide.mutate({ id: a.approval_id, decision: 'reject' }), className: "rounded-lg bg-rose-600 px-3.5 py-1.5 font-medium text-white hover:bg-rose-500 disabled:opacity-50", children: "Reject" })] }))] }, a.approval_id))) })] }));
}
