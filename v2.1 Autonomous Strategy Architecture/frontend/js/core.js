/**
 * CORE.JS v2 — Shared API client, auth, toast, formatters, confirm modal
 */

const API = '';

// ── Auth ──────────────────────────────────────────────────────
const Auth = {
    getToken()     { return localStorage.getItem('mtf_token'); },
    setToken(t)    { localStorage.setItem('mtf_token', t); },
    clearToken()   { localStorage.removeItem('mtf_token'); },
    getUsername()   { return localStorage.getItem('mtf_user') || 'User'; },
    setUsername(n)  { localStorage.setItem('mtf_user', n); },
    isLoggedIn()   { return !!this.getToken(); },
    logout() {
        const t = this.getToken();
        if (t) api('/api/auth/logout', 'POST').catch(() => {});
        this.clearToken();
        localStorage.removeItem('mtf_user');
        window.location.href = '/auth';
    }
};

function guardAuth()   { if (!Auth.isLoggedIn()) { window.location.href = '/auth'; return false; } return true; }
function guardNoAuth() { if (Auth.isLoggedIn()) { window.location.href = '/'; return false; } return true; }

// ── API Client ────────────────────────────────────────────────
async function api(path, method = 'GET', body = null) {
    const h = { 'Content-Type': 'application/json' };
    const t = Auth.getToken();
    if (t) h['Authorization'] = `Bearer ${t}`;
    const opts = { method, headers: h };
    if (body && method !== 'GET') opts.body = JSON.stringify(body);
    const res = await fetch(`${API}${path}`, opts);
    if (res.status === 401) { Auth.clearToken(); window.location.href = '/auth'; throw new Error('Session expired'); }
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || data.message || 'Request failed');
    return data;
}

// ── Toast ─────────────────────────────────────────────────────
function showToast(msg, type = 'info', duration = 4000) {
    const c = document.getElementById('toast-container');
    if (!c) return;
    const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.innerHTML = `<span>${icons[type] || '•'}</span><span>${msg}</span>`;
    c.appendChild(el);
    setTimeout(() => {
        el.style.opacity = '0';
        el.style.transform = 'translateX(60px)';
        el.style.transition = 'all 0.3s ease';
        setTimeout(() => el.remove(), 300);
    }, duration);
}

// ── Confirm Modal ─────────────────────────────────────────────
function showConfirm(title, message) {
    return new Promise(resolve => {
        const ov = document.getElementById('confirm-modal');
        if (!ov) return resolve(false);
        document.getElementById('confirm-title').textContent = title;
        document.getElementById('confirm-message').textContent = message;
        ov.classList.add('open');
        const done = r => { ov.classList.remove('open'); resolve(r); };
        document.getElementById('confirm-ok').onclick = () => done(true);
        document.getElementById('confirm-cancel').onclick = () => done(false);
        ov.onclick = e => { if (e.target === ov) done(false); };
    });
}

// ── Formatters ────────────────────────────────────────────────
function fmtMoney(v, c = '$') {
    if (v == null || isNaN(v)) return '—';
    return `${c}${parseFloat(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function fmtPrice(v, d = 5) { return v == null ? '—' : parseFloat(v).toFixed(d); }
function fmtPct(v) { return v == null ? '—' : `${parseFloat(v).toFixed(2)}%`; }
function fmtTime(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('en-US', { timeZone: 'UTC', hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
function fmtDateTime(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('en-US', { timeZone: 'UTC', hour12: false });
}
function colorVal(v) {
    if (v > 0) return 'var(--long)';
    if (v < 0) return 'var(--short)';
    return 'var(--text-3)';
}

// ── Button Loading ────────────────────────────────────────────
function setLoading(btn, on, txt = null) {
    if (on) {
        btn._orig = btn.textContent;
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner"></span>${txt || 'Loading...'}`;
    } else {
        btn.disabled = false;
        btn.textContent = btn._orig || txt || 'Submit';
    }
}
