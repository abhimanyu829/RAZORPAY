import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Api, can, fmtTime } from '../api';
import { Card, ErrorBox, Spinner } from '../components';
export function ConnectorsPage() {
    const qc = useQueryClient();
    const canSync = can('sync', Api.role());
    const stats = useQuery({
        queryKey: ['connector-stats'],
        queryFn: () => Api.get('/api/v1/connectors/stats'),
    });
    const health = useQuery({
        queryKey: ['connector-health'],
        queryFn: () => Api.get('/api/v1/connectors/health'),
        refetchInterval: 20_000,
    });
    const sync = useMutation({
        mutationFn: (id) => Api.post(`/api/v1/connectors/${id}/sync`),
        onSuccess: () => qc.invalidateQueries(),
    });
    if (stats.isLoading)
        return _jsx(Spinner, {});
    if (stats.isError)
        return _jsx(ErrorBox, { msg: stats.error.message });
    const webhookNote = (id) => id === 'RAZORPAY_TEST' ? 'Webhook: ' + (health.data?.RAZORPAY_TEST ? 'signature-verified' : 'idle') : null;
    return (_jsxs("div", { className: "space-y-4", children: [sync.isError && _jsx(ErrorBox, { msg: sync.error.message }), _jsx("div", { className: "grid gap-4 md:grid-cols-2", children: (stats.data?.connectors ?? []).map(c => {
                    const h = health.data?.[c.connector_id];
                    return (_jsxs(Card, { children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsx("span", { className: "text-sm font-semibold text-slate-200", children: c.connector_id }), _jsxs("span", { className: `flex items-center gap-1.5 text-xs ${h?.healthy ? 'text-emerald-400' : 'text-slate-500'}`, children: [_jsx("span", { className: "inline-block h-2 w-2 rounded-full bg-current" }), h?.healthy ? 'Healthy' : (h?.detail || 'idle').slice(0, 30)] })] }), _jsxs("dl", { className: "mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]", children: [_jsxs("div", { className: "flex justify-between", children: [_jsx("dt", { className: "text-slate-500", children: "last sync" }), _jsx("dd", { className: "text-slate-300", children: c.last_run ? fmtTime(c.last_run.finished_at || c.last_run.started_at) : '—' })] }), _jsxs("div", { className: "flex justify-between", children: [_jsx("dt", { className: "text-slate-500", children: "records" }), _jsx("dd", { className: "tabular-nums text-slate-300", children: c.records_processed })] }), _jsxs("div", { className: "flex justify-between", children: [_jsx("dt", { className: "text-slate-500", children: "duplicates" }), _jsx("dd", { className: "tabular-nums text-slate-300", children: c.duplicates })] }), _jsxs("div", { className: "flex justify-between", children: [_jsx("dt", { className: "text-slate-500", children: "quarantine" }), _jsx("dd", { className: "tabular-nums text-slate-300", children: c.quarantined })] }), _jsxs("div", { className: "flex justify-between", children: [_jsx("dt", { className: "text-slate-500", children: "errors" }), _jsx("dd", { className: `tabular-nums ${c.errors ? 'text-rose-400' : 'text-slate-300'}`, children: c.errors })] }), _jsxs("div", { className: "flex justify-between", children: [_jsx("dt", { className: "text-slate-500", children: "webhook events" }), _jsx("dd", { className: "tabular-nums text-slate-300", children: c.webhook_events })] }), _jsxs("div", { className: "col-span-2 flex justify-between", children: [_jsx("dt", { className: "text-slate-500", children: "checkpoint" }), _jsx("dd", { className: "truncate font-mono text-[10px] text-slate-400", children: c.checkpoint ? `${c.checkpoint.last_cursor || c.checkpoint.last_timestamp || '—'} @ ${fmtTime(c.checkpoint.updated_at)}` : '—' })] })] }), canSync && (_jsx("button", { disabled: sync.isPending && sync.variables === c.connector_id, onClick: () => sync.mutate(c.connector_id), className: "mt-3 w-full rounded-lg border border-slate-700 bg-slate-900 py-1.5 text-xs text-slate-200 hover:border-sky-500 disabled:opacity-50", children: sync.isPending && sync.variables === c.connector_id ? 'Syncing…' : 'Run incremental sync' }))] }, c.connector_id));
                }) }), _jsx(Card, { title: "Webhook inbox", children: _jsxs("div", { className: "text-xs text-slate-400", children: [stats.data?.webhook_total ?? 0, " webhook events received (deduplicated by provider event ID, HMAC-verified).", webhookNote('RAZORPAY_TEST')] }) })] }));
}
