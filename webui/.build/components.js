import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export function Card({ title, children, className = '' }) {
    return (_jsxs("div", { className: `rounded-xl border border-slate-800 bg-slate-900/60 p-4 ${className}`, children: [title && _jsx("h3", { className: "mb-3 text-xs font-semibold uppercase tracking-wider text-sky-400", children: title }), children] }));
}
export function Kpi({ label, value, sub, tone = 'default', icon }) {
    const tones = {
        default: 'text-slate-100',
        green: 'text-emerald-400',
        red: 'text-rose-400',
        amber: 'text-amber-400',
        blue: 'text-sky-400',
    };
    return (_jsxs("div", { className: "rounded-xl border border-slate-800 bg-slate-900/60 p-4", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsx("div", { className: "text-[11px] font-medium uppercase tracking-wider text-slate-400", children: label }), icon && _jsx("span", { className: "text-slate-500", children: icon })] }), _jsx("div", { className: `mt-1 text-2xl font-semibold tabular-nums ${tones[tone]}`, children: value }), sub && _jsx("div", { className: "mt-0.5 text-xs text-slate-500", children: sub })] }));
}
const badgeTones = {
    NEW: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
    INVESTIGATING: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
    PENDING_APPROVAL: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    ESCALATED: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    RESOLVED: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    COMPLETED: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    ACTION_READY: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    REVIEW_REQUIRED: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    MISMATCH: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
    LEAKAGE: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
    HIGH: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
    MEDIUM: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    LOW: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
    APPROVED: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    REJECTED: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
    EXECUTED: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    RECOVERY_VERIFIED: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    FINANCIAL_EFFECT_DETECTED: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
    IN_PROGRESS: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
    FAILED: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
};
export function Badge({ children }) {
    const tone = badgeTones[children] || 'bg-slate-500/15 text-slate-300 border-slate-500/30';
    return _jsx("span", { className: `inline-block rounded-full border px-2 py-0.5 text-[10.5px] font-semibold ${tone}`, children: children });
}
export function MoneyBar({ expected, actual, label }) {
    // Values are pre-computed by the backend; this is purely visual scaling.
    const max = Math.max(expected, actual, 1);
    const wpct = (v) => `${Math.max((v / max) * 100, 2)}%`;
    const variance = expected - actual;
    return (_jsxs("div", { className: "space-y-2", children: [_jsxs("div", { children: [_jsxs("div", { className: "flex justify-between text-xs", children: [_jsxs("span", { className: "text-slate-400", children: ["Expected ", label] }), _jsxs("span", { className: "font-semibold tabular-nums text-slate-200", children: ["\u20B9", expected.toLocaleString('en-IN')] })] }), _jsx("div", { className: "mt-1 h-3 w-full rounded bg-slate-800", children: _jsx("div", { className: "h-3 rounded bg-sky-500/80", style: { width: wpct(expected) } }) })] }), _jsxs("div", { children: [_jsxs("div", { className: "flex justify-between text-xs", children: [_jsxs("span", { className: "text-slate-400", children: ["Actual ", label] }), _jsxs("span", { className: "font-semibold tabular-nums text-slate-200", children: ["\u20B9", actual.toLocaleString('en-IN')] })] }), _jsx("div", { className: "mt-1 h-3 w-full rounded bg-slate-800", children: _jsx("div", { className: "h-3 rounded bg-slate-500/70", style: { width: wpct(actual) } }) })] }), _jsxs("div", { className: "flex justify-between rounded border border-slate-800 bg-slate-950 px-2 py-1.5 text-xs", children: [_jsx("span", { className: "text-slate-400", children: "Variance" }), _jsxs("span", { className: `font-bold tabular-nums ${variance > 0 ? 'text-rose-400' : 'text-emerald-400'}`, children: ["\u20B9", variance.toLocaleString('en-IN')] })] })] }));
}
export function Spinner() {
    return _jsx("span", { className: "inline-block animate-spin rounded-full border-2 border-slate-600 border-t-sky-400 px-2 py-0.5" });
}
export function EmptyState({ text }) {
    return _jsx("div", { className: "rounded-xl border border-dashed border-slate-700 p-8 text-center text-sm text-slate-500", children: text });
}
export function ErrorBox({ msg }) {
    return _jsx("div", { className: "rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-300", children: msg });
}
