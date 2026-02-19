/**
 * API Client — all backend communication
 */

const API_BASE = '/api';

async function request(url, options = {}) {
    const res = await fetch(`${API_BASE}${url}`, {
        headers: { 'Content-Type': 'application/json', ...options.headers },
        ...options,
    });
    const data = await res.json();
    if (!res.ok) {
        throw new Error(data.detail || `API error: ${res.status}`);
    }
    return data;
}

// ─── MT5 ────────────────────────────────────────────────
export async function connectMT5(server, login, password) {
    return request('/mt5/connect', {
        method: 'POST',
        body: JSON.stringify({ server, login: Number(login), password }),
    });
}

export async function disconnectMT5() {
    return request('/mt5/disconnect', { method: 'POST' });
}

export async function getMT5Status() {
    return request('/mt5/status');
}

// ─── Symbols ────────────────────────────────────────────
export async function getSymbols(group = '*') {
    return request(`/symbols?group=${encodeURIComponent(group)}`);
}

export async function getSymbolInfo(name) {
    return request(`/symbol/${encodeURIComponent(name)}`);
}

// ─── Timeframes ─────────────────────────────────────────
export async function getTimeframes() {
    return request('/timeframes');
}

// ─── Strategies ─────────────────────────────────────────
export async function getStrategies() {
    return request('/strategies');
}

export async function getStrategySettings(name) {
    return request(`/strategies/${encodeURIComponent(name)}/settings`);
}

// ─── Backtest ───────────────────────────────────────────
export async function runBacktest(params) {
    return request('/backtest', {
        method: 'POST',
        body: JSON.stringify(params),
    });
}
