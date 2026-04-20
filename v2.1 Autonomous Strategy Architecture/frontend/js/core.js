/**
 * CORE.JS v2 — Shared API client, auth, toast, formatters, confirm modal
 */

const API = '';


// ── API Client ────────────────────────────────────────────────
async function api(path, method = 'GET', body = null) {
    const h = { 'Content-Type': 'application/json' };
    const opts = { method, headers: h };
    if (body && method !== 'GET') opts.body = JSON.stringify(body);
    const res = await fetch(`${API}${path}`, opts);
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

// ── App Initialization ─────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Initialize Lucide icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }

    // Header Clock
    const timeEl = document.getElementById('server-time');
    if (timeEl) {
        setInterval(() => {
            const now = new Date();
            timeEl.textContent = now.toISOString().substring(11, 19) + ' UTC';
        }, 1000);
        timeEl.textContent = new Date().toISOString().substring(11, 19) + ' UTC';
    }

    initCmdK();
});

// ── Command Palette (cmdk) ────────────────────────────────────
function initCmdK() {
    const overlay = document.getElementById('cmdk-overlay');
    const input = document.getElementById('cmdk-input');
    const listEl = document.getElementById('cmdk-list');
    if (!overlay || !input || !listEl) return;

    let isOpen = false;
    let selectedIndex = 0;
    let currentResults = [];

    const commands = [
        { id: 'dash', title: 'Go to Dashboard', category: 'Navigation', icon: 'layout-dashboard', action: () => switchPanel('dashboard') },
        { id: 'strat', title: 'Go to Strategies', category: 'Navigation', icon: 'cpu', action: () => switchPanel('mtf-config') },
        { id: 'chart', title: 'Go to Technical Charts', category: 'Navigation', icon: 'line-chart', action: () => switchPanel('charts') },
        { id: 'close-all', title: 'Close All Open Positions', category: 'Trading', icon: 'x-circle', action: () => {
            document.getElementById('rp-close-all-btn')?.click();
        } },
        { id: 'kill-switch', title: 'Show Kill-Switch Status', category: 'System', icon: 'alert-triangle', action: () => {
            document.getElementById('header-kill-btn')?.click();
        } }
    ];

    const fuse = new Fuse(commands, { keys: ['title', 'category'], threshold: 0.3 });

    function render(results) {
        currentResults = results;
        listEl.innerHTML = '';
        if (results.length === 0) {
            listEl.innerHTML = '<div style="padding:16px; text-align:center; color:var(--text-3); font-size:12px;">No commands found</div>';
            return;
        }
        results.forEach((cmd, idx) => {
            const el = document.createElement('div');
            el.className = 'cmdk-item';
            if (idx === selectedIndex) el.setAttribute('aria-selected', 'true');
            el.innerHTML = `
                <div class="cmdk-item-left">
                    <i data-lucide="${cmd.icon}" class="cmdk-item-icon"></i>
                    <span style="font-size:13px;">${cmd.title}</span>
                </div>
                <span style="font-size:10px; color:var(--text-3); text-transform:uppercase;">${cmd.category}</span>
            `;
            el.addEventListener('mouseover', () => { selectedIndex = idx; render(currentResults); });
            el.addEventListener('click', () => { exec(idx); });
            listEl.appendChild(el);
        });
        if (typeof lucide !== 'undefined') lucide.createIcons();
        
        // Scroll into view
        const selEl = listEl.children[selectedIndex];
        if (selEl) selEl.scrollIntoView({ block: 'nearest' });
    }

    function toggle() {
        isOpen = !isOpen;
        if (isOpen) {
            overlay.classList.add('open');
            input.value = '';
            selectedIndex = 0;
            render(commands);
            setTimeout(() => input.focus(), 50);
        } else {
            overlay.classList.remove('open');
            input.blur();
        }
    }

    function exec(idx) {
        if (!currentResults[idx]) return;
        const cmd = currentResults[idx];
        toggle();
        cmd.action();
    }

    // Toggle shortcut
    document.addEventListener('keydown', e => {
        if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            toggle();
        }
        if (isOpen) {
            if (e.key === 'Escape') toggle();
            else if (e.key === 'ArrowDown') { e.preventDefault(); selectedIndex = Math.min(selectedIndex + 1, currentResults.length - 1); render(currentResults); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); selectedIndex = Math.max(selectedIndex - 1, 0); render(currentResults); }
            else if (e.key === 'Enter') { e.preventDefault(); exec(selectedIndex); }
        }
    });

    // Close on backdrop click
    overlay.addEventListener('click', e => { if (e.target === overlay) toggle(); });

    // Handle typing search
    input.addEventListener('input', e => {
        const q = e.target.value.trim();
        selectedIndex = 0;
        if (!q) render(commands);
        else {
            const res = fuse.search(q).map(r => r.item);
            render(res);
        }
    });

    // Trigger button
    const trigger = document.querySelector('.cmdk-trigger');
    if (trigger) trigger.addEventListener('click', toggle);
}
