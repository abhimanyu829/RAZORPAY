// Central API client + role model. The frontend NEVER computes financial
// values; every number displayed comes from these backend responses.
const API_KEY_STORAGE = 'rg_api_key';
export class Api {
    static key() {
        return localStorage.getItem(API_KEY_STORAGE) || 'rg-admin-key';
    }
    static setKey(k) {
        localStorage.setItem(API_KEY_STORAGE, k);
    }
    static role() {
        return KEY_ROLES[this.key()] ?? null;
    }
    static async req(path, init) {
        const r = await fetch(path, {
            ...init,
            headers: {
                'X-API-Key': this.key(),
                'Content-Type': 'application/json',
                ...(init?.headers || {}),
            },
        });
        if (r.status === 403)
            throw new Error('403: your role cannot perform this action');
        if (r.status === 404)
            throw new Error('404: not found');
        if (!r.ok)
            throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`);
        return r.json();
    }
    static get(path) { return this.req(path); }
    static post(path, body) {
        return this.req(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined });
    }
}
export const KEY_ROLES = {
    'rg-admin-key': 'admin',
    'rg-finance-key': 'finance_lead',
    'rg-analyst-key': 'analyst',
    'rg-viewer-key': 'viewer',
    'rg-agent-key': 'agent',
    'rg-evaluator-key': 'evaluator',
};
export const ROLE_CAPS = {
    admin: ['read', 'write', 'approve', 'run_agent', 'sync', 'shadow', 'eval', 'admin'],
    finance_lead: ['read', 'write', 'approve', 'run_agent', 'sync'],
    finance_operator: ['read', 'write'],
    analyst: ['read', 'run_agent'],
    viewer: ['read'],
    agent: ['read'],
    evaluator: ['read', 'eval'],
};
export function can(cap, role) {
    return !!role && ROLE_CAPS[role]?.includes(cap);
}
export const fmtMoney = (n) => {
    const v = Number(n || 0);
    return '₹' + v.toLocaleString('en-IN', { maximumFractionDigits: 2 });
};
export const fmtPct = (v) => `${((Number(v) || 0) * 100).toFixed(1)}%`;
export const fmtTime = (iso) => (iso || '').replace('T', ' ').replace('Z', '') || '—';
