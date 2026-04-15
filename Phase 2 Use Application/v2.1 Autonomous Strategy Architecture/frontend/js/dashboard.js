/**
 * DASHBOARD.JS v3 — Decoupled Architecture
 *
 * Three independent systems:
 *  1. Watchlist Charts — independent live candlestick charts (no strategy dependency)
 *  2. Strategy Scanner — headless signal generator (no chart rendering)
 *  3. Signal Bus      — one-way broadcast: strategy → matching charts + signal list
 *
 * Uses TradingView LightweightCharts for live candlestick rendering.
 */

// ── Global State ──────────────────────────────────────────────
let _strategies = [];
let _activeScanners = {};   // scannerId → { config, name, autoTrade }
let _watchCharts = {};      // watchId → { ws, symbol, tf, chartKey }
let _chartInstances = {};   // watchId → { chart, candleSeries, markers }
let _expandedState = { chart: null, candles: null, watchId: null };
let _mt5Symbols = [];
let _signalWs = null;       // Global signal WebSocket
let _globalIndicators = {};  // Tracks globally-applied indicators: type → settings
let _renderedSignalIds = new Set(); // Dedup: track displayed signal IDs

document.addEventListener('DOMContentLoaded', () => {
    if (!guardAuth()) return;

    // ── User Init ─────────────────────────────────────────────
    const username = Auth.getUsername();
    document.getElementById('user-name').textContent = username;
    document.getElementById('user-avatar').textContent = username.charAt(0).toUpperCase();

    // ── Navigation ────────────────────────────────────────────
    initNavigation();
    initMarketTabs();
    initMT5Connection();
    loadStrategies();
    pollAccountInfo();
    initDeployTrades();
    initStrategyUpload();
    initWatchlistPanel();
    connectGlobalSignalWS();

    // One-time form submit handler — never re-added on strategy refresh
    const launchForm = document.getElementById('mtf-config-form');
    if (launchForm) {
        launchForm.addEventListener('submit', (e) => {
            e.preventDefault();
            handleLaunchScanner();
        });
    }

    // ── Logout ────────────────────────────────────────────────
    document.getElementById('logout-btn').addEventListener('click', async () => {
        const ok = await showConfirm('Logout', 'End your session and return to login?');
        if (ok) Auth.logout();
    });
});

// ═══ NAVIGATION ═══════════════════════════════════════════════
function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item[data-panel]');
    navItems.forEach(item => {
        item.addEventListener('click', () => switchPanel(item.dataset.panel));
    });
}

function switchPanel(panelId) {
    // Nav items
    document.querySelectorAll('.nav-item[data-panel]').forEach(n => n.classList.remove('active'));
    const nav = document.querySelector(`.nav-item[data-panel="${panelId}"]`);
    if (nav) nav.classList.add('active');

    // Panels
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    const panel = document.getElementById(`panel-${panelId}`);
    if (panel) panel.classList.add('active');

    // Resize charts when switching to charts panel
    if (panelId === 'charts') {
        setTimeout(() => resizeAllWatchCharts(), 50);
    }

    // Save state
    api('/api/auth/session', 'PUT', { last_panel: panelId }).catch(() => {});
}

// ═══ MARKET TABS ══════════════════════════════════════════════
function initMarketTabs() {
    document.querySelectorAll('.market-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            if (tab.classList.contains('disabled')) {
                showToast('Coming soon — this market is not yet supported', 'info');
                return;
            }
            document.querySelectorAll('.market-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
        });
    });
}

// ═══ MT5 CONNECTION ═══════════════════════════════════════════
function initMT5Connection() {
    const form = document.getElementById('mt5-connect-form');
    const btn = document.getElementById('mt5-connect-btn');
    const loadBtn = document.getElementById('mt5-load-saved');

    // Check initial status — and load symbols if already connected
    api('/api/data/mt5/status').then(d => {
        setMT5Connected(d.connected, d.account);
        if (d.connected) loadMT5Symbols();
    }).catch(() => {});

    // Connect form
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const server = document.getElementById('mt5-server').value.trim();
        const login = parseInt(document.getElementById('mt5-login').value);
        const password = document.getElementById('mt5-password').value;
        const save = document.getElementById('mt5-save').checked;

        if (!server || !login || !password) { showToast('Fill all MT5 fields', 'warning'); return; }

        setLoading(btn, true, 'Connecting...');
        try {
            const r = await api('/api/data/mt5/connect', 'POST', { server, login, password, save_credentials: save });
            setMT5Connected(true, r.account);
            showToast('Connected to MT5', 'success');
            document.getElementById('mt5-password').value = '';
            refreshAccountInfo();
            loadMT5Symbols();
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            setLoading(btn, false, 'Connect');
        }
    });

    // Load saved
    loadBtn.addEventListener('click', async () => {
        try {
            const r = await api('/api/data/mt5/connect-saved', 'POST');
            setMT5Connected(true, r.account);
            showToast('Connected with saved credentials', 'success');
            refreshAccountInfo();
            loadMT5Symbols();
        } catch (err) {
            showToast(err.message, 'error');
        }
    });
}

function setMT5Connected(on, info = null) {
    const dot = document.getElementById('conn-dot');
    const txt = document.getElementById('conn-text');
    const badge = document.getElementById('mt5-status-badge');

    if (on) {
        dot.className = 'dot dot-on';
        txt.textContent = info ? `${info.server || 'Connected'}` : 'Connected';
        badge.className = 'badge badge-success';
        badge.textContent = 'Connected';
        if (info) updateAccountDisplay(info);
    } else {
        dot.className = 'dot dot-off';
        txt.textContent = 'Disconnected';
        badge.className = 'badge badge-error';
        badge.textContent = 'Disconnected';
    }
}

function updateAccountDisplay(info) {
    if (!info) return;
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set('acc-balance', fmtMoney(info.balance));
    set('acc-equity', fmtMoney(info.equity || info.balance));
    set('acc-margin', fmtMoney(info.free_margin));
    set('acc-server', info.server || '—');

    const pnl = info.profit;
    const pnlEl = document.getElementById('acc-pnl');
    if (pnlEl) {
        pnlEl.textContent = pnl != null ? fmtMoney(pnl) : '—';
        if (pnl != null) pnlEl.style.color = colorVal(pnl);
    }
}

// ═══ SYMBOL LOADING & AUTOCOMPLETE ═══════════════════════════
async function loadMT5Symbols() {
    try {
        const data = await api('/api/data/symbols?group=*');
        _mt5Symbols = data.symbols || [];
        console.log(`Loaded ${_mt5Symbols.length} symbols from MT5`);
        filterSymbolList();
    } catch (err) {
        console.error('Failed to load symbols:', err);
        _mt5Symbols = [];
    }
}

function _renderSymbolDropdown(inputId, dropdownId, selectFn) {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    if (!input || !dropdown) return;

    const q = input.value.trim().toLowerCase();

    if (_mt5Symbols.length === 0) {
        dropdown.innerHTML = '<div class="sym-empty">Connect to MT5 to load symbols</div>';
        dropdown.classList.add('open');
        return;
    }

    const filtered = _mt5Symbols.filter(s =>
        s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q)
    );

    if (filtered.length === 0) {
        dropdown.innerHTML = '<div class="sym-empty">No symbols match your search</div>';
        dropdown.classList.add('open');
        return;
    }

    dropdown.innerHTML = filtered.slice(0, 40).map(s => `
        <div class="sym-item ${input.value === s.name ? 'active' : ''}" onclick="${selectFn}('${s.name}')">
            <span class="sym-name">${s.name}</span>
            <span class="sym-desc">${s.description || ''}</span>
        </div>
    `).join('');
    dropdown.classList.add('open');
}

function filterSymbolList() { _renderSymbolDropdown('cfg-symbol', 'cfg-symbol-dropdown', 'selectSymbol'); }
function filterOrderSymbolList() { _renderSymbolDropdown('order-symbol', 'order-symbol-dropdown', 'selectOrderSymbol'); }
function filterWatchSymbolList() { _renderSymbolDropdown('watch-symbol', 'watch-symbol-dropdown', 'selectWatchSymbol'); }

function selectSymbol(name) {
    document.getElementById('cfg-symbol').value = name;
    document.getElementById('cfg-symbol-dropdown').classList.remove('open');
}
function selectOrderSymbol(name) {
    document.getElementById('order-symbol').value = name;
    document.getElementById('order-symbol-dropdown').classList.remove('open');
}
function selectWatchSymbol(name) {
    document.getElementById('watch-symbol').value = name;
    document.getElementById('watch-symbol-dropdown').classList.remove('open');
}

// Close symbol dropdowns when clicking outside
document.addEventListener('click', (e) => {
    ['cfg-symbol-dropdown', 'order-symbol-dropdown', 'watch-symbol-dropdown'].forEach(id => {
        const dd = document.getElementById(id);
        const inputId = id.replace('-dropdown', '');
        const inp = document.getElementById(inputId);
        if (dd && !dd.contains(e.target) && e.target !== inp) {
            dd.classList.remove('open');
        }
    });
});

// Show dropdown when focusing on symbol inputs
document.addEventListener('focusin', (e) => {
    if (e.target && e.target.id === 'cfg-symbol') filterSymbolList();
    if (e.target && e.target.id === 'order-symbol') filterOrderSymbolList();
    if (e.target && e.target.id === 'watch-symbol') filterWatchSymbolList();
});

async function refreshAccountInfo() {
    try {
        const info = await api('/api/order/account');
        updateAccountDisplay(info);
        const posEl = document.getElementById('acc-positions');
        if (posEl && info.positions_count != null) posEl.textContent = info.positions_count;
        refreshPositions();
    } catch (e) { /* not connected */ }
}

async function refreshPositions() {
    try {
        const data = await api('/api/order/positions');
        const container = document.getElementById('dash-positions');
        const positions = data.positions || [];
        const posEl = document.getElementById('acc-positions');
        if (posEl) posEl.textContent = positions.length;

        if (positions.length === 0) {
            container.innerHTML = `<div class="empty-state" style="padding: 24px;"><div class="empty-state-desc">No open positions</div></div>`;
            return;
        }

        container.innerHTML = positions.map(p => {
            const dir = (p.type || '').toUpperCase().includes('BUY') ? 'BUY' : 'SELL';
            const cls = dir === 'BUY' ? 'long' : 'short';
            const pnlCls = p.profit >= 0 ? 'profit' : 'loss';
            return `<div class="pos-row">
                <span class="badge badge-${cls}">${dir}</span>
                <div class="pos-col" style="flex:1;">
                    <span class="pos-symbol">${p.symbol}</span>
                    <span class="pos-detail">Vol: ${p.volume}  ·  Ticket: ${p.ticket}</span>
                </div>
                <div class="pos-col" style="text-align:right;">
                    <span class="mono" style="font-size:var(--fs-xs); color:var(--text-2);">Open: ${fmtPrice(p.price_open)}</span>
                    <span class="mono" style="font-size:var(--fs-xs); color:var(--text-2);">Curr: ${fmtPrice(p.price_current)}</span>
                </div>
                <span class="pos-pnl ${pnlCls}">${fmtMoney(p.profit)}</span>
            </div>`;
        }).join('');
    } catch (e) { /* not connected */ }
}

function pollAccountInfo() {
    setInterval(() => {
        if (document.getElementById('conn-dot')?.classList.contains('dot-on')) {
            refreshAccountInfo();
        }
    }, 10000);
}

// ═══ STRATEGY LOADING ═════════════════════════════════════════
async function loadStrategies() {
    try {
        const data = await api('/api/chart/strategies');
        _strategies = data.strategies || [];

        const sel = document.getElementById('cfg-strategy');
        if (!sel) return;
        sel.innerHTML = _strategies.map(s => `<option value="${s.name}">${s.name}</option>`).join('');

        // Use .onchange (not addEventListener) so re-calls don't stack handlers
        sel.onchange = () => renderStratSettings(sel.value);
        if (_strategies.length > 0) renderStratSettings(_strategies[0].name);

    } catch (err) {
        console.error('Failed to load strategies:', err);
    }
}

function renderStratSettings(name) {
    const container = document.getElementById('cfg-strat-settings');
    if (!container) return;
    const strat = _strategies.find(s => s.name === name);
    if (!strat || !strat.schema || !strat.schema.properties) { container.innerHTML = ''; return; }

    const props = strat.schema.properties;
    let html = '<div class="strat-settings-section"><div class="dash-section-title">Strategy Parameters</div>';

    for (const [key, prop] of Object.entries(props)) {
        const label = prop.description || key;
        const def = prop.default;

        if (prop.enum) {
            const opts = prop.enum.map(v => `<option value="${v}" ${v === def ? 'selected' : ''}>${v}</option>`).join('');
            html += `<div class="form-group"><label class="form-label">${label}</label><select class="form-input form-select" data-setting="${key}">${opts}</select></div>`;
        } else if (prop.type === 'integer' || prop.type === 'number') {
            const step = prop.type === 'integer' ? 1 : 0.1;
            html += `<div class="form-group"><label class="form-label">${label}</label><input class="form-input" type="number" data-setting="${key}" value="${def ?? ''}" step="${step}"></div>`;
        }
    }

    html += '</div>';
    container.innerHTML = html;
}

function getStratSettings() {
    const inputs = document.querySelectorAll('#cfg-strat-settings [data-setting]');
    const s = {};
    inputs.forEach(el => {
        const k = el.dataset.setting;
        const v = el.value;
        s[k] = el.type === 'number' ? (el.step === '1' ? parseInt(v) : parseFloat(v)) : v;
    });
    return s;
}

// ═══ STRATEGY UPLOAD ══════════════════════════════════════════

function initStrategyUpload() {
    const fileInput = document.getElementById('strat-file-input');
    const dropZone  = document.getElementById('strat-drop-zone');

    if (fileInput) {
        fileInput.addEventListener('change', e => {
            if (e.target.files[0]) {
                uploadStrategyFile(e.target.files[0]);
                e.target.value = '';
            }
        });
    }

    if (dropZone) {
        dropZone.addEventListener('click', e => {
            if (e.target.tagName !== 'LABEL' && e.target.tagName !== 'INPUT' &&
                !e.target.closest('label')) {
                fileInput && fileInput.click();
            }
        });

        dropZone.addEventListener('dragover', e => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });
        dropZone.addEventListener('dragleave', e => {
            if (!dropZone.contains(e.relatedTarget)) {
                dropZone.classList.remove('drag-over');
            }
        });
        dropZone.addEventListener('drop', e => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
            const file = e.dataTransfer.files[0];
            if (!file) return;
            if (!file.name.endsWith('.py')) {
                showToast('Only .py Python files are accepted', 'warning');
                return;
            }
            uploadStrategyFile(file);
        });
    }

    refreshUploadedStrategies();
}

async function uploadStrategyFile(file) {
    const statusDiv = document.getElementById('strat-upload-status');
    if (!statusDiv) return;

    statusDiv.style.display = 'block';
    statusDiv.innerHTML = `
        <div class="badge badge-muted" style="display:inline-flex; align-items:center; gap:6px;">
            <span class="spinner" style="width:10px;height:10px;"></span>
            Uploading ${file.name}...
        </div>`;

    const formData = new FormData();
    formData.append('file', file);

    try {
        const token = Auth.getToken();
        const res = await fetch('/api/chart/strategies/upload', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData,
        });
        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.detail || 'Upload failed');
        }

        statusDiv.innerHTML = `
            <div style="display:flex; align-items:center; gap: var(--sp-2); padding: var(--sp-2) var(--sp-3);
                        background: color-mix(in srgb, var(--long) 12%, var(--surface-2));
                        border: 1px solid color-mix(in srgb, var(--long) 30%, transparent);
                        border-radius: var(--radius-sm);">
                <span style="color:var(--long);">✓</span>
                <span style="font-size:0.85rem; color:var(--text-1);">
                    <strong>"${data.strategy_name}"</strong> loaded successfully
                </span>
            </div>`;

        showToast(`Strategy "${data.strategy_name}" is now available`, 'success');
        await loadStrategies();
        await refreshUploadedStrategies();

        setTimeout(() => {
            if (statusDiv) statusDiv.style.display = 'none';
        }, 5000);

    } catch (err) {
        statusDiv.innerHTML = `
            <div style="display:flex; align-items:flex-start; gap: var(--sp-2); padding: var(--sp-2) var(--sp-3);
                        background: color-mix(in srgb, var(--short) 12%, var(--surface-2));
                        border: 1px solid color-mix(in srgb, var(--short) 30%, transparent);
                        border-radius: var(--radius-sm);">
                <span style="color:var(--short); flex-shrink:0;">✗</span>
                <span style="font-size:0.82rem; color:var(--text-1);">${err.message}</span>
            </div>`;
        showToast('Upload failed — see details in panel', 'error');
    }
}

async function refreshUploadedStrategies() {
    const section   = document.getElementById('strat-uploaded-section');
    const container = document.getElementById('strat-uploaded-list');
    if (!container) return;

    try {
        const data = await api('/api/chart/strategies/uploaded/list');
        const uploaded = data.uploaded || [];

        if (uploaded.length === 0) {
            if (section) section.style.display = 'none';
            return;
        }

        if (section) section.style.display = 'block';

        container.innerHTML = uploaded.map(s => `
            <div class="uploaded-strat-row" id="uploaded-row-${CSS.escape(s.filename)}">
                <div class="uploaded-strat-info">
                    <span class="uploaded-strat-name">${s.strategy_name}</span>
                    <span class="uploaded-strat-file">${s.filename} · ${s.size_kb}KB</span>
                </div>
                <div class="uploaded-strat-actions">
                    <span class="badge badge-success" style="font-size:10px;">Active</span>
                    <button class="btn btn-error btn-xs"
                            onclick="deleteUploadedStrategy('${s.filename}', '${s.strategy_name}')"
                            title="Remove strategy">
                        Remove
                    </button>
                </div>
            </div>
        `).join('');

    } catch (err) {
        container.innerHTML = `<p style="color:var(--text-3); font-size:0.82rem;">
            Could not load uploaded strategies list.</p>`;
    }
}

async function deleteUploadedStrategy(filename, strategyName) {
    const ok = await showConfirm(
        'Remove Strategy',
        `Remove "${strategyName}"? It will no longer appear in the strategy dropdown. ` +
        `This cannot be undone.`
    );
    if (!ok) return;

    try {
        await api(`/api/chart/strategies/uploaded/${encodeURIComponent(filename)}`, 'DELETE');
        showToast(`"${strategyName}" removed`, 'info');
        await loadStrategies();
        await refreshUploadedStrategies();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// ═══ HEADLESS SCANNER — LAUNCH & MANAGE ═══════════════════════
async function handleLaunchScanner() {
    const name = document.getElementById('cfg-name').value.trim();
    const symbol = document.getElementById('cfg-symbol').value.trim();
    const strategy = document.getElementById('cfg-strategy').value;

    if (!name) { showToast('Enter a session name', 'warning'); return; }
    if (!symbol) { showToast('Enter a symbol', 'warning'); return; }

    const btn = document.getElementById('cfg-launch-btn');
    setLoading(btn, true, 'Starting...');

    const config = { symbol, strategy_name: strategy, settings: { ...getStratSettings(), _name: name }, provider: 'mt5' };

    try {
        const resp = await fetch('/api/chart/scanner/start', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${Auth.getToken()}`,
            },
            body: JSON.stringify(config),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: 'Request failed' }));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }

        const data = await resp.json();
        const scannerId = data.scanner_id;

        // Store scanner info
        _activeScanners[scannerId] = {
            config: { ...config, _name: name },
            name,
            autoTrade: false,
            symbol,
            timeframe: 'M1',
            strategyName: strategy,
            signals: [],  // Store all signals for late-added charts
        };

        // Create nav item + signal panel for this scanner
        createScannerNavAndPanel(scannerId, _activeScanners[scannerId]);

        // Load historical signals from API response into panel + chart markers
        const signals = data.historical_signals || [];
        showToast(`✓ Scanner "${name}" started — ${signals.length} historical signals loaded`, 'success');

        // Store historical signals — stamp scanner_id on each so panel routing is ID-based
        _activeScanners[scannerId].signals = signals.map(s => ({ ...s, scanner_id: scannerId }));
        for (const sig of _activeScanners[scannerId].signals) {
            addSignalToScannerPanel(sig);
        }

        // Inject historical signals as markers on matching charts
        _addHistoricalSignalMarkersToCharts(signals);

        // Update active strategies list
        refreshActiveStrategies();
        refreshAutoTradeList();

    } catch (err) {
        console.error('Scanner start failed:', err);
        showToast(`Scanner failed: ${err.message}`, 'error');
    } finally {
        setLoading(btn, false, '⚡ Launch Scanner');
    }
}

async function stopScanner(scannerId) {
    const scanner = _activeScanners[scannerId];
    const name = scanner ? scanner.name : scannerId;

    const ok = await showConfirm('Stop Scanner', `Stop "${name}"? It will stop generating signals.`);
    if (!ok) return;

    try {
        await fetch('/api/chart/scanner/stop', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${Auth.getToken()}`,
            },
            body: JSON.stringify({ scanner_id: scannerId }),
        });
    } catch(e) {}

    // Clean up: remove this scanner's signal IDs from the global dedup Set
    const sc = _activeScanners[scannerId];
    if (sc && sc.signals) {
        sc.signals.forEach(s => { if (s.id) _renderedSignalIds.delete(s.id); });
    }

    delete _activeScanners[scannerId];
    removeScannerNavAndPanel(scannerId);
    refreshActiveStrategies();
    refreshAutoTradeList();
    showToast(`Scanner "${name}" stopped`, 'info');
}

function refreshActiveStrategies() {
    const container = document.getElementById('active-strategies-list');
    if (!container) return;

    const ids = Object.keys(_activeScanners);
    if (ids.length === 0) {
        container.innerHTML = `<div class="empty-state" style="padding: 24px;">
            <div class="empty-state-desc">No active scanners. Launch a strategy above.</div>
        </div>`;
        return;
    }

    container.innerHTML = ids.map(sid => {
        const sc = _activeScanners[sid];
        const autoOn = sc.autoTrade || false;
        return `<div class="active-strat-row">
            <div class="active-strat-info">
                <div class="active-strat-name">${sc.name}</div>
                <div class="active-strat-meta">${sc.symbol} · ${sc.strategyName} · ${sc.timeframe || 'M1'}</div>
            </div>
            <div class="active-strat-actions">
                <span class="badge badge-success" style="font-size:9px;">LIVE</span>
                <div class="auto-toggle-wrap">
                    <label class="toggle-switch">
                        <input type="checkbox" ${autoOn ? 'checked' : ''} data-scanner="${sid}" class="auto-trade-toggle-strat">
                        <span class="toggle-slider"></span>
                    </label>
                    <span class="auto-trade-status ${autoOn ? 'on' : 'off'}" style="font-size:9px;">${autoOn ? 'AUTO' : 'OFF'}</span>
                </div>
                <button class="btn btn-error btn-xs" onclick="stopScanner('${sid}')">Stop</button>
            </div>
        </div>`;
    }).join('');

    // Attach auto-trade toggle handlers
    container.querySelectorAll('.auto-trade-toggle-strat').forEach(toggle => {
        toggle.addEventListener('change', async function() {
            const sid = this.dataset.scanner;
            const on = this.checked;
            if (on) {
                const ok = await showConfirm('Enable Auto Trading', 'This scanner will automatically execute trades. Are you sure?');
                if (!ok) { this.checked = false; return; }
            }
            if (_activeScanners[sid]) {
                _activeScanners[sid].autoTrade = on;
                const label = this.closest('.auto-toggle-wrap').querySelector('.auto-trade-status');
                if (label) { label.textContent = on ? 'AUTO' : 'OFF'; label.className = `auto-trade-status ${on ? 'on' : 'off'}`; }
                showToast(on ? 'Auto-trade enabled' : 'Auto-trade disabled', on ? 'success' : 'info');
                refreshAutoTradeList();
            }
        });
    });
}

// ═══ GLOBAL SIGNAL WEBSOCKET ══════════════════════════════════
function connectGlobalSignalWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    _signalWs = new WebSocket(`${proto}://${location.host}/api/signals/ws`);

    _signalWs.onopen = () => {
        console.log('Global signal WS connected');
    };

    _signalWs.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleGlobalSignalMsg(msg);
        } catch (e) { console.error('Signal WS parse error:', e); }
    };

    _signalWs.onerror = () => {
        console.warn('Global signal WS error');
    };

    _signalWs.onclose = () => {
        console.log('Global signal WS disconnected — reconnecting in 3s');
        setTimeout(connectGlobalSignalWS, 3000);
    };
}

function handleGlobalSignalMsg(msg) {
    if (msg.type === 'signal') {
        const sig = msg.data;

        // Deduplicate: skip if already rendered from API historical response
        if (sig.id && _renderedSignalIds.has(sig.id)) return;
        if (sig.id) _renderedSignalIds.add(sig.id);  // track it

        // Route signal to scanner's full panel
        addSignalToScannerPanel(sig);

        // Add marker to ALL open charts for this symbol (Bug 4 fix)
        for (const [watchId, w] of Object.entries(_watchCharts)) {
            if (w.symbol === sig.symbol) {
                _addSignalMarkerToChart(watchId, sig);
            }
        }

        // Toast notification
        const stratLabel = sig.strategy ? `${sig.strategy}: ` : '';
        showToast(`${stratLabel}${sig.direction} · ${sig.symbol} [${sig.timeframe}] @ ${fmtPrice(sig.price)}`,
            sig.direction === 'BUY' ? 'success' : 'error', 5000);
    }

    if (msg.type === 'trade_update') {
        const update = msg.data;
        updateGlobalSignalDOM(update);
    }
}

// ═══ SCANNER NAV + SIGNAL PANELS ══════════════════════════════════

/**
 * Create a nav item in the left pane + a full signal panel in the main area.
 * The nav label uses the user-defined session name.
 */
function createScannerNavAndPanel(scannerId, scannerInfo) {
    const scannerNavSection = document.getElementById('scanner-nav-section');
    const mainArea = document.querySelector('.main-area');
    if (!scannerNavSection || !mainArea) return;

    // Show the scanner nav section
    scannerNavSection.style.display = '';

    // Don't duplicate
    if (document.getElementById(`nav-scanner-${scannerId}`)) return;

    const sessionName = scannerInfo.name || 'Scanner';
    const stratName = scannerInfo.strategyName || 'Unknown';
    const symbol = scannerInfo.symbol || '—';
    const tfs = 'M1';
    const panelId = `scanner-${scannerId}`;

    // 1. Create nav item
    const navItem = document.createElement('div');
    navItem.className = 'nav-item';
    navItem.id = `nav-scanner-${scannerId}`;
    navItem.dataset.panel = panelId;
    navItem.innerHTML = `
        <span class="nav-icon">📡</span>
        <span class="nav-label">${sessionName}</span>
        <span class="nav-badge" id="nav-badge-${scannerId}">0</span>
    `;
    navItem.addEventListener('click', () => switchPanel(panelId));
    scannerNavSection.appendChild(navItem);

    // 2. Create full signal panel in main area
    const panel = document.createElement('div');
    panel.className = 'panel';
    panel.id = `panel-${panelId}`;
    panel.innerHTML = `
        <div class="panel-header">
            <div style="display:flex; align-items:center; gap: var(--sp-3);">
                <span class="panel-header-title">${sessionName}</span>
                <span class="badge badge-success" style="font-size:9px;">LIVE</span>
            </div>
            <div class="panel-header-actions">
                <span class="scanner-panel-meta">${stratName} · ${symbol} · ${tfs}</span>
                <span class="badge badge-muted" id="panel-sig-count-${scannerId}">0 signals</span>
            </div>
        </div>
        <div class="panel-body scanner-signal-panel-body" id="scanner-panel-body-${scannerId}">
            <div class="scanner-signals-table">
                <div class="scanner-signals-header">
                    <span>Direction</span>
                    <span>Symbol</span>
                    <span>Timeframe</span>
                    <span>Price</span>
                    <span>SL</span>
                    <span>TP</span>
                    <span>Status</span>
                    <span>Time</span>
                </div>
                <div class="scanner-signals-body" id="scanner-signals-${scannerId}">
                    <div class="scanner-signals-empty">Waiting for signals…</div>
                </div>
            </div>
        </div>
    `;
    mainArea.appendChild(panel);
}

/**
 * Remove nav item + panel when scanner is stopped.
 */
function removeScannerNavAndPanel(scannerId) {
    const panelId = `scanner-${scannerId}`;

    // If currently viewing this panel, switch back to MTF config
    const activePanel = document.querySelector('.panel.active');
    if (activePanel && activePanel.id === `panel-${panelId}`) {
        switchPanel('mtf-config');
    }

    // Remove nav item
    const navItem = document.getElementById(`nav-scanner-${scannerId}`);
    if (navItem) navItem.remove();

    // Remove panel
    const panel = document.getElementById(`panel-${panelId}`);
    if (panel) panel.remove();

    // Hide scanner nav section if no scanners remain
    const scannerNavSection = document.getElementById('scanner-nav-section');
    if (scannerNavSection) {
        const remaining = scannerNavSection.querySelectorAll('.nav-item');
        if (remaining.length === 0) {
            scannerNavSection.style.display = 'none';
        }
    }
}

/**
 * Route a signal to its scanner's full panel.
 * Matches by scanner ID (via strategy name) or creates orphan panel.
 */
function addSignalToScannerPanel(sig) {
    // Route by scanner_id first (reliable), fall back to strategy+symbol match
    let scannerId = sig.scanner_id || null;

    if (!scannerId) {
        for (const [sid, sc] of Object.entries(_activeScanners)) {
            if (sc.strategyName === (sig.strategy || '') && sc.symbol === sig.symbol) {
                scannerId = sid;
                break;
            }
        }
    }

    // If no scanner found, ignore — don't create orphan panels
    if (!scannerId || !_activeScanners[scannerId]) return;

    // Store live signal in scanner's signal store for late-added charts
    if (_activeScanners[scannerId] && _activeScanners[scannerId].signals) {
        _activeScanners[scannerId].signals.push(sig);
    }

    const signalsBody = document.getElementById(`scanner-signals-${scannerId}`);
    if (!signalsBody) return;

    // Remove empty placeholder
    const empty = signalsBody.querySelector('.scanner-signals-empty');
    if (empty) empty.remove();

    // Update badge counts with a local variable (not DOM re-read)
    const navBadge = document.getElementById(`nav-badge-${scannerId}`);
    const panelCount = document.getElementById(`panel-sig-count-${scannerId}`);
    const currentCount = parseInt(navBadge?.textContent || '0') + 1;
    if (navBadge) navBadge.textContent = currentCount;
    if (panelCount) panelCount.textContent = `${currentCount} signal${currentCount !== 1 ? 's' : ''}`;

    const cls = sig.direction === 'BUY' ? 'long' : 'short';
    const status = sig.status || 'RUNNING';
    let statusCls = 'run';
    if (status === 'TP HIT') statusCls = 'tp';
    else if (status === 'SL HIT') statusCls = 'sl';

    const elId = `global-sig-${sig.id || Date.now()}`;

    // Track rendered signal ID for deduplication
    if (sig.id) _renderedSignalIds.add(sig.id);
    const row = document.createElement('div');
    row.className = 'scanner-signal-row';
    row.id = elId;
    row.innerHTML = `
        <span><span class="badge badge-${cls}">${sig.direction}</span></span>
        <span class="mono">${sig.symbol}</span>
        <span>${sig.timeframe}</span>
        <span class="mono">${fmtPrice(sig.price)}</span>
        <span class="mono">${sig.sl != null ? fmtPrice(sig.sl) : '—'}</span>
        <span class="mono">${sig.tp != null ? fmtPrice(sig.tp) : '—'}</span>
        <span><span class="sig-entry-status sig-status-${statusCls}" id="${elId}-status">${status}</span></span>
        <span class="sig-entry-time" id="${elId}-time">${fmtTime(sig.bar_time || sig.time)}</span>
    `;
    signalsBody.insertBefore(row, signalsBody.firstChild);

    // Keep max 100 entries
    while (signalsBody.children.length > 100) signalsBody.removeChild(signalsBody.lastChild);
}

function updateGlobalSignalDOM(update) {
    const elId = `global-sig-${update.id}`;
    const statusEl = document.getElementById(`${elId}-status`);
    const closeTimeEl = document.getElementById(`${elId}-close`);
    
    if (statusEl) {
        statusEl.textContent = update.status;
        statusEl.className = 'sig-entry-status'; // reset
        if (update.status === 'TP HIT') statusEl.classList.add('sig-status-tp');
        else if (update.status === 'SL HIT') statusEl.classList.add('sig-status-sl');
        else statusEl.classList.add('sig-status-run');
    }
    
    if (closeTimeEl && update.close_time) {
        closeTimeEl.textContent = fmtTime(update.close_time);
    }
}

// ═══ WATCHLIST CHARTS (Independent) ═══════════════════════════

function initWatchlistPanel() {
    // TF chip selection for watchlist
    document.querySelectorAll('#watch-tf-select .tf-chip-sm').forEach(chip => {
        chip.addEventListener('click', () => {
            // Single-select for watchlist
            document.querySelectorAll('#watch-tf-select .tf-chip-sm').forEach(c => c.classList.remove('selected'));
            chip.classList.add('selected');
        });
    });
}

async function handleAddWatchChart() {
    const symbol = document.getElementById('watch-symbol').value.trim();
    const tfChip = document.querySelector('#watch-tf-select .tf-chip-sm.selected');
    const tf = tfChip ? tfChip.dataset.tf : null;

    if (!symbol) { showToast('Enter a symbol', 'warning'); return; }
    if (!tf) { showToast('Select a timeframe', 'warning'); return; }

    // Check limit
    if (Object.keys(_watchCharts).length >= 6) {
        showToast('Maximum 6 charts allowed', 'warning');
        return;
    }

    // Check duplicate
    for (const wid of Object.keys(_watchCharts)) {
        const w = _watchCharts[wid];
        if (w.symbol === symbol && w.tf === tf) {
            showToast(`Chart for ${symbol} ${tf} already exists`, 'info');
            return;
        }
    }

    const btn = document.getElementById('watch-add-btn');
    setLoading(btn, true, 'Adding...');

    try {
        const resp = await api('/api/watchlist/start', 'POST', { symbol, timeframe: tf, provider: 'mt5' });
        const watchId = resp.watch_id;
        const bars = resp.historical_bars || [];

        _watchCharts[watchId] = { symbol, tf, ws: null };

        // Render chart
        renderWatchGrid();
        if (bars.length > 0) {
            initWatchChart(watchId, symbol, tf, bars);
        }

        // Apply global indicators to new chart
        applyGlobalIndicatorsToChart(watchId);

        // Inject signals from already-running scanners as chart markers
        _injectExistingSignalsToChart(watchId, symbol, tf);

        // Connect WS
        startWatchWS(watchId);

        // Update badge
        updateChartCountBadge();
        document.getElementById('watch-symbol').value = '';
        showToast(`Chart added: ${symbol} ${tf}`, 'success');

    } catch (err) {
        showToast(`Failed to add chart: ${err.message}`, 'error');
    } finally {
        setLoading(btn, false, '+ Add Chart');
    }
}

/**
 * Add a single signal as a marker to a specific chart instance.
 * Reusable for both live signals and historical signal injection.
 * Floors the signal timestamp to the chart's bar boundary so markers
 * always align to an existing candle (Bug 2 fix).
 */
function _addSignalMarkerToChart(watchId, sig) {
    const inst = _chartInstances[watchId];
    if (!inst || !inst.candleSeries) return;

    const w = _watchCharts[watchId];
    const chartTf = w ? w.tf : null;

    // Use session name (user-defined) for marker label instead of strategy class name
    const sessionName = (sig.scanner_id && _activeScanners[sig.scanner_id]?.name)
        || sig.session_name
        || sig.strategy
        || '';
    const stratLabel = sessionName ? `${sessionName}: ${sig.direction}` : sig.direction;

    // Floor signal timestamp to chart's bar boundary so marker aligns to an existing bar
    const rawTs = _toChartTs(sig.bar_time || sig.time);
    const ts = chartTf ? _alignTsToTf(rawTs, chartTf) : rawTs;

    // Deduplicate: skip if a marker with same time + text already exists
    if (!inst.markers) inst.markers = [];
    const exists = inst.markers.some(m => m.time === ts && m.text === stratLabel);
    if (exists) return;

    const marker = {
        time: ts,
        position: sig.direction === 'BUY' ? 'belowBar' : 'aboveBar',
        color: sig.direction === 'BUY' ? '#22c55e' : '#ef4444',
        shape: sig.direction === 'BUY' ? 'arrowUp' : 'arrowDown',
        text: stratLabel,
    };
    inst.markers.push(marker);
    inst.markers.sort((a, b) => a.time - b.time);
    try { inst.candleSeries.setMarkers(inst.markers); } catch(e) {}
}

/**
 * Inject a batch of historical signals as markers onto matching charts.
 * Matches signals to charts by symbol + timeframe.
 */
/**
 * Inject existing signals from all active scanners onto a newly added chart.
 * Solves: strategy started first, chart added later.
 */
function _injectExistingSignalsToChart(watchId, symbol, tf) {
    const inst = _chartInstances[watchId];
    if (!inst || !inst.candleSeries) return;

    for (const [sid, sc] of Object.entries(_activeScanners)) {
        if (!sc.signals || sc.signals.length === 0) continue;
        // Match by symbol only — timeframe alignment handled in _addSignalMarkerToChart (Bug 3 fix)
        const matching = sc.signals.filter(sig => sig.symbol === symbol);
        for (const sig of matching) {
            _addSignalMarkerToChart(watchId, sig);
        }
    }
}

function _addHistoricalSignalMarkersToCharts(signals) {
    if (!signals || signals.length === 0) return;

    // Match signals to existing charts by symbol only — timeframe alignment
    // handled in _addSignalMarkerToChart via _alignTsToTf (Bug 3 fix)
    for (const [watchId, w] of Object.entries(_watchCharts)) {
        const inst = _chartInstances[watchId];
        if (!inst || !inst.candleSeries) continue;

        const matchingSignals = signals.filter(sig => sig.symbol === w.symbol);

        for (const sig of matchingSignals) {
            _addSignalMarkerToChart(watchId, sig);
        }
    }
}

function renderWatchGrid() {
    const grid = document.getElementById('watch-chart-grid');
    if (!grid) return;

    const ids = Object.keys(_watchCharts);

    // Remove orphan cells (cells for removed charts)
    grid.querySelectorAll('.chart-cell').forEach(cell => {
        const cellWid = cell.id.replace('watch-cell-', '');
        if (!_watchCharts[cellWid]) cell.remove();
    });

    if (ids.length === 0) {
        grid.innerHTML = `<div class="empty-state" style="padding: 60px 24px; background: var(--bg-card);">
            <div style="font-size: 40px; opacity: 0.15;">📈</div>
            <div class="empty-state-desc">Add a symbol to start watching live charts</div>
        </div>`;
        grid.className = 'watch-chart-grid';
        return;
    }

    // Remove empty state if present
    const emptyState = grid.querySelector('.empty-state');
    if (emptyState) emptyState.remove();

    // TradingView-style grid layout
    const count = ids.length;
    let colClass = 'cols-1';
    if (count === 2) colClass = 'cols-2';
    else if (count === 3) colClass = 'cols-3';
    else if (count === 4) colClass = 'cols-4';
    else if (count === 5) colClass = 'cols-5';
    else if (count >= 6) colClass = 'cols-6';
    grid.className = `watch-chart-grid ${colClass}`;

    // Only add cells that don't exist yet
    for (const wid of ids) {
        if (document.getElementById(`watch-cell-${wid}`)) continue;
        const w = _watchCharts[wid];
        const cell = document.createElement('div');
        cell.className = 'chart-cell';
        cell.id = `watch-cell-${wid}`;
        cell.innerHTML = `
            <div class="chart-cell-header">
                <div style="display:flex; align-items:center; gap:6px;">
                    <span class="chart-cell-tf">${w.tf}</span>
                    <span style="font-size:var(--fs-xs); color:var(--text-2); font-weight:600;">${w.symbol}</span>
                </div>
                <div style="display:flex; align-items:center; gap: 6px;">
                    <span class="chart-cell-price mono" id="watch-price-${wid}">—</span>
                    <button class="chart-expand-btn" onclick="openExpandedWatch('${wid}')" title="Expand Chart">&#x26F6;</button>
                    <button class="chart-expand-btn" onclick="removeWatchChart('${wid}')" title="Remove Chart" style="color:var(--short);">✕</button>
                </div>
            </div>
            <div class="indicator-chips-bar" id="indicator-chips-${wid}" style="display:none;"></div>
            <div class="chart-cell-body" id="watch-canvas-${wid}">
                <div class="empty-state" style="padding: 40px;"><div class="spinner-lg"></div></div>
            </div>
        `;
        grid.appendChild(cell);

        // Attach ResizeObserver to auto-resize chart when cell changes size
        _observeChartCell(wid, cell);
    }

    // Schedule resize for all charts after DOM settles
    requestAnimationFrame(() => {
        setTimeout(() => resizeAllWatchCharts(), 30);
    });
}

/** Attach ResizeObserver to a chart cell to handle auto-resize */
function _observeChartCell(watchId, cell) {
    if (!window.ResizeObserver) return;

    const body = cell.querySelector('.chart-cell-body');
    if (!body) return;

    const observer = new ResizeObserver(() => {
        const inst = _chartInstances[watchId];
        if (!inst || !inst.chart) return;
        const w = body.clientWidth;
        const h = body.clientHeight;
        if (w > 0 && h > 0) {
            try { inst.chart.applyOptions({ width: w, height: h }); } catch(e) {}
        }
    });
    observer.observe(body);

    // Store observer for cleanup
    if (!_watchCharts[watchId]) return;
    _watchCharts[watchId]._resizeObserver = observer;
}

function initWatchChart(watchId, symbol, tf, bars) {
    const container = document.getElementById(`watch-canvas-${watchId}`);
    if (!container) return;

    // Destroy previous
    if (_chartInstances[watchId]) {
        try { _chartInstances[watchId].chart.remove(); } catch(e) {}
        delete _chartInstances[watchId];
    }

    container.innerHTML = '';

    // Calculate available dimensions (fallback for initial 0-height)
    let chartW = container.clientWidth || container.parentElement?.clientWidth || 400;
    let chartH = container.clientHeight || 200;

    const colors = _getChartColors();
    const chart = LightweightCharts.createChart(container, {
        width: chartW,
        height: chartH,
        layout: {
            background: { type: 'solid', color: colors.bg },
            textColor: colors.text,
            fontFamily: "'Inter', 'Segoe UI', sans-serif",
            fontSize: 11,
        },
        grid: {
            vertLines: { color: colors.grid },
            horzLines: { color: colors.grid },
        },
        rightPriceScale: {
            borderColor: colors.border,
            scaleMargins: { top: 0.1, bottom: 0.05 },
        },
        timeScale: {
            borderColor: colors.border,
            timeVisible: true,
            secondsVisible: false,
            rightOffset: 5,
        },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        handleScale: { axisPressedMouseMove: { time: true, price: true } },
        handleScroll: { mouseWheel: true, pressedMouseMove: true },
    });

    const candleSeries = chart.addCandlestickSeries({
        upColor: '#22c55e', downColor: '#ef4444',
        borderUpColor: '#22c55e', borderDownColor: '#ef4444',
        wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    });

    // Deduplicate and sort bars
    const uniqueBars = [];
    const seen = new Set();
    const sorted = bars.map(b => ({
        time: _toChartTs(b.time),
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
    })).sort((a, b) => a.time - b.time);

    for (const bar of sorted) {
        if (!seen.has(bar.time)) {
            seen.add(bar.time);
            uniqueBars.push(bar);
        }
    }

    try {
        candleSeries.setData(uniqueBars);
    } catch(e) {
        console.error('Error setting candle data:', e);
    }

    _chartInstances[watchId] = {
        chart,
        candleSeries,
        markers: [],
        symbol,
        tf,
    };

    // Initialize indicator state for this chart
    initIndicatorState(watchId);

    // Update price display
    if (uniqueBars.length > 0) {
        const lastClose = uniqueBars[uniqueBars.length - 1].close;
        const priceEl = document.getElementById(`watch-price-${watchId}`);
        if (priceEl) priceEl.textContent = fmtPrice(lastClose);
    }

    // Deferred resize — wait for CSS layout to settle then fit correctly
    requestAnimationFrame(() => {
        const w = container.clientWidth;
        const h = container.clientHeight;
        if (w > 0 && h > 0) {
            chart.applyOptions({ width: w, height: h });
        }
        chart.timeScale().fitContent();
    });
}

function startWatchWS(watchId) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/api/watchlist/ws/${watchId}`);

    if (_watchCharts[watchId]) {
        _watchCharts[watchId].ws = ws;
    }

    ws.onopen = () => {
        console.log(`Watchlist WS connected for ${watchId}`);
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWatchMsg(watchId, msg);
        } catch (e) { console.error('Watch WS parse error:', e); }
    };

    ws.onerror = () => {
        console.warn(`Watchlist WS error for ${watchId}`);
    };

    ws.onclose = () => {
        if (_watchCharts[watchId]) {
            setTimeout(() => {
                if (_watchCharts[watchId]) {
                    startWatchWS(watchId);
                }
            }, 3000);
        }
    };
}

function handleWatchMsg(watchId, msg) {
    const inst = _chartInstances[watchId];

    // ── Bar updates from WatchlistEngine (new format: {bars, indicators})
    if (msg.type === 'bar_updates') {
        const payload = msg.data || {};
        const bars = payload.bars || payload || [];
        const indicators = payload.indicators || null;

        // Handle bars array (backward compat: data could be array or object)
        const barList = Array.isArray(bars) ? bars : [];
        for (const bar of barList) {
            if (inst && inst.candleSeries) {
                try {
                    inst.candleSeries.update({
                        time: _toChartTs(bar.time),
                        open: bar.open,
                        high: bar.high,
                        low: bar.low,
                        close: bar.close,
                    });
                } catch(e) {}
            }
            // Update price display
            const priceEl = document.getElementById(`watch-price-${watchId}`);
            if (priceEl) priceEl.textContent = fmtPrice(bar.close);

            // Update expanded chart if viewing this watch
            if (_expandedState.watchId === watchId && _expandedState.candles) {
                try {
                    _expandedState.candles.update({
                        time: _toChartTs(bar.time),
                        open: bar.open,
                        high: bar.high,
                        low: bar.low,
                        close: bar.close,
                    });
                } catch(e) {}
            }
        }

        // ── Update indicators from the same payload
        if (indicators) {
            handleIndicatorUpdates(watchId, indicators);
            // Also update expanded chart indicators if open
            updateExpandedIndicators(watchId, indicators);
        }
    }

    // ── Indicator lifecycle messages from backend ──
    if (msg.type === 'indicator_added') {
        const d = msg.data;
        renderIndicator(watchId, d.indicator_id, d.type, d.settings, d.data);
    }
    if (msg.type === 'indicator_removed') {
        const d = msg.data;
        _removeIndicatorSeries(watchId, d.indicator_id);
        renderIndicatorChips(watchId);
    }
    if (msg.type === 'indicator_updated') {
        const d = msg.data;
        renderIndicator(watchId, d.indicator_id, d.type, d.settings, d.data);
    }
    if (msg.type === 'indicator_sync') {
        handleIndicatorSync(watchId, msg.data);
    }

    // ── Signal from SignalBus (matched by symbol+timeframe)
    if (msg.type === 'signal') {
        const sig = msg.data;
        if (inst) {
            _addSignalMarkerToChart(watchId, sig);

            // Glow animation
            const cell = document.getElementById(`watch-cell-${watchId}`);
            if (cell) {
                cell.classList.remove('chart-glow-buy', 'chart-glow-sell');
                void cell.offsetWidth;
                cell.classList.add(sig.direction === 'BUY' ? 'chart-glow-buy' : 'chart-glow-sell');
            }

            // Update expanded chart markers
            if (_expandedState.watchId === watchId && _expandedState.candles) {
                try { _expandedState.candles.setMarkers(inst.markers); } catch(e) {}
            }
        }
    }
}

async function removeWatchChart(watchId) {
    const w = _watchCharts[watchId];
    if (!w) return;

    // Close WS
    if (w.ws && w.ws.readyState === WebSocket.OPEN) {
        w.ws.close();
    }

    // Stop backend
    try {
        await fetch('/api/watchlist/stop', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${Auth.getToken()}`,
            },
            body: JSON.stringify({ watch_id: watchId }),
        });
    } catch(e) {}

    // Clean up ResizeObserver
    if (w._resizeObserver) {
        w._resizeObserver.disconnect();
    }

    // Destroy indicator state and series
    destroyIndicatorState(watchId);

    // Destroy chart
    if (_chartInstances[watchId]) {
        try { _chartInstances[watchId].chart.remove(); } catch(e) {}
        delete _chartInstances[watchId];
    }

    // Remove from DOM
    const cell = document.getElementById(`watch-cell-${watchId}`);
    if (cell) cell.remove();

    delete _watchCharts[watchId];
    renderWatchGrid();
    updateChartCountBadge();
    showToast(`Chart removed: ${w.symbol} ${w.tf}`, 'info');
}

function updateChartCountBadge() {
    const badge = document.getElementById('charts-count-badge');
    if (badge) badge.textContent = `${Object.keys(_watchCharts).length} / 6`;
}

function resizeAllWatchCharts() {
    for (const watchId in _chartInstances) {
        const inst = _chartInstances[watchId];
        const container = document.getElementById(`watch-canvas-${watchId}`);
        if (container && inst.chart) {
            const w = container.clientWidth;
            const h = container.clientHeight;
            if (w > 0 && h > 0) {
                try { inst.chart.applyOptions({ width: w, height: h }); } catch(e) {}
            }
        }
    }
    // Also resize indicator panes
    resizeAllIndicatorPanes();
}

// ═══ LIGHTWEIGHT CHARTS — TIMESTAMP UTILITIES ═════════════════

// Timeframe in seconds — used to align signal markers to chart bar boundaries
const TF_SECONDS = {
    'M1': 60, 'M3': 180, 'M5': 300, 'M15': 900, 'M30': 1800,
    'H1': 3600, 'H2': 7200, 'H4': 14400, 'H6': 21600,
    'H8': 28800, 'H12': 43200, 'D1': 86400, 'W1': 604800,
};

/**
 * Floor a Unix timestamp to the nearest bar boundary for the given timeframe.
 * E.g. an M5 signal at 08:37 on an H1 chart → floors to 08:00.
 * Ensures markers always land on an existing candle bar.
 */
function _alignTsToTf(unixTs, chartTf) {
    const tfSec = TF_SECONDS[chartTf];
    if (!tfSec) return unixTs;
    return Math.floor(unixTs / tfSec) * tfSec;
}

function _toChartTs(isoStr) {
    if (!isoStr) return 0;
    let s = String(isoStr);
    if (!s.endsWith('Z') && !s.includes('+') && !s.includes('-', 10)) {
        s += 'Z';
    }
    return Math.floor(new Date(s).getTime() / 1000);
}

function _getChartColors() {
    return {
        bg: '#0d1421',
        text: '#94a3b8',
        grid: '#1e2d42',
        border: '#1e2d42',
    };
}

// ═══ CHART EXPAND MODAL ═══════════════════════════════════════
function openExpandedWatch(watchId) {
    const inst = _chartInstances[watchId];
    if (!inst) return;

    const modal = document.getElementById('chart-expand-modal');
    const container = document.getElementById('chart-modal-container');
    const title = document.getElementById('chart-modal-title');

    // Clean up any prior expanded indicator panes
    cleanupExpandedIndicators();

    title.innerHTML = `${inst.symbol} <span style="color: var(--accent); font-weight: 600;">${inst.tf}</span>`;
    container.innerHTML = '';
    container.style.height = '';
    container.style.flex = '1';

    const colors = _getChartColors();
    const chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: container.clientHeight,
        layout: {
            background: { type: 'solid', color: colors.bg },
            textColor: colors.text,
            fontFamily: "'Inter', 'Segoe UI', sans-serif",
            fontSize: 12,
        },
        grid: {
            vertLines: { color: colors.grid },
            horzLines: { color: colors.grid },
        },
        rightPriceScale: { borderColor: colors.border },
        timeScale: {
            borderColor: colors.border,
            timeVisible: true,
            secondsVisible: false,
        },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    });

    const candleSeries = chart.addCandlestickSeries({
        upColor: '#22c55e', downColor: '#ef4444',
        borderUpColor: '#22c55e', borderDownColor: '#ef4444',
        wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    });

    // Clone data from original chart
    try {
        const data = inst.candleSeries.data();
        candleSeries.setData(data);
    } catch(e) {
        console.error('Error cloning chart data:', e);
    }

    // Clone markers
    if (inst.markers && inst.markers.length > 0) {
        try { candleSeries.setMarkers(inst.markers); } catch(e) {}
    }

    // Store expanded state for live updates
    _expandedState = { chart, candles: candleSeries, watchId };

    modal.classList.add('open');

    setTimeout(() => {
        chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
        // Render indicators on the expanded chart
        renderIndicatorsOnExpandedChart(watchId, chart, candleSeries);
    }, 50);
}

function closeExpandedChart() {
    const modal = document.getElementById('chart-expand-modal');
    modal.classList.remove('open');

    // Clean up expanded indicator series + pane charts
    cleanupExpandedIndicators();

    if (_expandedState.chart) {
        try { _expandedState.chart.remove(); } catch(e) {}
        _expandedState = { chart: null, candles: null, watchId: null };
    }

    // Restore modal body flex
    const container = document.getElementById('chart-modal-container');
    if (container) {
        container.style.height = '';
        container.style.flex = '1';
    }
}

// ── Bind chart modal close + window resize ────────────────────
(function() {
    const closeBtn = document.getElementById('chart-modal-close');
    if (closeBtn) closeBtn.addEventListener('click', closeExpandedChart);

    const modal = document.getElementById('chart-expand-modal');
    if (modal) modal.addEventListener('click', (e) => {
        if (e.target === modal) closeExpandedChart();
    });

    // Handle window resize for all active charts
    window.addEventListener('resize', () => {
        resizeAllWatchCharts();
    });
})();

// ═══ DEPLOY TRADES PANEL ══════════════════════════════════════
function initDeployTrades() {
    // ── Mode Tabs ─────────────────────────────────────────────
    const modeTabs = document.querySelectorAll('.trade-mode-tab');
    const manualSection = document.getElementById('manual-trade-section');
    const autoSection = document.getElementById('auto-trade-section');

    if (!modeTabs.length) return;

    modeTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            modeTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            if (tab.dataset.mode === 'manual') {
                manualSection.style.display = '';
                autoSection.style.display = 'none';
            } else {
                manualSection.style.display = 'none';
                autoSection.style.display = '';
            }
        });
    });

    // ── Manual Order Form ─────────────────────────────────────
    const orderForm = document.getElementById('manual-order-form');
    if (orderForm) {
        orderForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = document.getElementById('place-order-btn');
            const symbol = document.getElementById('order-symbol').value.trim();
            const orderType = document.getElementById('order-type').value;
            const direction = document.getElementById('order-direction').value;
            const volume = parseFloat(document.getElementById('order-volume').value);
            const slEnabled = document.getElementById('sl-enabled').checked;
            const tpEnabled = document.getElementById('tp-enabled').checked;
            const sl = slEnabled ? parseFloat(document.getElementById('order-sl').value) : null;
            const tp = tpEnabled ? parseFloat(document.getElementById('order-tp').value) : null;
            const price = orderType === 'pending' ? parseFloat(document.getElementById('order-price').value) : null;

            if (!symbol) { showToast('Enter a symbol', 'warning'); return; }
            if (!volume || volume <= 0) { showToast('Enter a valid volume', 'warning'); return; }

            const dirLabel = direction.toUpperCase();
            const ok = await showConfirm(
                'Confirm Order',
                `Place ${dirLabel} ${orderType} order: ${volume} lots ${symbol}` +
                (sl ? ` | SL: ${sl}` : '') +
                (tp ? ` | TP: ${tp}` : '') +
                '\n\nThis will execute a REAL trade on your MT5 account.'
            );
            if (!ok) return;

            setLoading(btn, true, 'Placing...');
            try {
                const result = await api('/api/order/place', 'POST', {
                    symbol, order_type: orderType, direction, volume, price,
                    sl, tp, sl_enabled: slEnabled, tp_enabled: tpEnabled, confirm: true
                });
                showToast(`Order placed — Ticket #${result.ticket}`, 'success');
                refreshAccountInfo();
            } catch (err) {
                showToast(err.message, 'error');
            } finally {
                setLoading(btn, false, 'Place Order');
            }
        });
    }

    // ── SL / TP Toggle ────────────────────────────────────────
    const slCheck = document.getElementById('sl-enabled');
    const tpCheck = document.getElementById('tp-enabled');
    const slInput = document.getElementById('order-sl');
    const tpInput = document.getElementById('order-tp');
    if (slCheck) slCheck.addEventListener('change', () => { slInput.disabled = !slCheck.checked; });
    if (tpCheck) tpCheck.addEventListener('change', () => { tpInput.disabled = !tpCheck.checked; });

    // ── Pending order price visibility ────────────────────────
    const orderTypeSelect = document.getElementById('order-type');
    const priceGroup = document.getElementById('order-price-group');
    if (orderTypeSelect && priceGroup) {
        orderTypeSelect.addEventListener('change', () => {
            priceGroup.style.display = orderTypeSelect.value === 'pending' ? '' : 'none';
        });
    }

    // ── Close All Positions ───────────────────────────────────
    const closeAllBtn = document.getElementById('close-all-btn');
    if (closeAllBtn) {
        closeAllBtn.addEventListener('click', async () => {
            const ok = await showConfirm('Close All Positions', 'This will close ALL open positions on your MT5 account. This action cannot be undone.');
            if (!ok) return;
            setLoading(closeAllBtn, true, 'Closing...');
            try {
                const r = await api('/api/order/close-all', 'POST');
                showToast(`Closed ${r.closed_count || 0} positions`, 'success');
                refreshAccountInfo();
            } catch (err) {
                showToast(err.message, 'error');
            } finally {
                setLoading(closeAllBtn, false, 'Close All');
            }
        });
    }

    // ── Risk Guard ────────────────────────────────────────────
    const riskForm = document.getElementById('risk-guard-form');
    if (riskForm) {
        api('/api/order/risk').then(state => {
            document.getElementById('risk-enabled').checked = state.enabled;
            document.getElementById('risk-threshold').value = state.threshold_pct || 5;
            document.getElementById('risk-auto-close').checked = state.auto_close;
        }).catch(() => {});

        riskForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const enabled = document.getElementById('risk-enabled').checked;
            const threshold_pct = parseFloat(document.getElementById('risk-threshold').value);
            const auto_close = document.getElementById('risk-auto-close').checked;

            if (auto_close) {
                const ok = await showConfirm('Enable Auto-Close', 'When capital risk exceeds the threshold, ALL positions will be automatically closed. Are you sure?');
                if (!ok) return;
            }

            try {
                await api('/api/order/risk', 'POST', { enabled, threshold_pct, auto_close });
                showToast('Risk guard updated', 'success');
            } catch (err) {
                showToast(err.message, 'error');
            }
        });
    }

    refreshAutoTradeList();
}

function refreshAutoTradeList() {
    const container = document.getElementById('auto-scanner-list');
    if (!container) return;

    const ids = Object.keys(_activeScanners);
    if (ids.length === 0) {
        container.innerHTML = `<div class="empty-state" style="padding: 24px;"><div class="empty-state-desc">No active scanners. Launch an MTF Strategy first.</div></div>`;
        return;
    }

    container.innerHTML = ids.map(sid => {
        const sc = _activeScanners[sid];
        const cfg = sc.config;
        const name = sc.name || sid;
        const autoOn = sc.autoTrade || false;
        return `<div class="auto-scanner-row">
            <div class="auto-scanner-info">
                <span class="auto-scanner-name">${name}</span>
                <span class="auto-scanner-meta">${sc.symbol} · ${sc.strategyName} · ${sc.timeframe || 'M1'}</span>
            </div>
            <div class="auto-toggle-wrap">
                <label class="toggle-switch">
                    <input type="checkbox" ${autoOn ? 'checked' : ''} data-scanner="${sid}" class="auto-trade-toggle">
                    <span class="toggle-slider"></span>
                </label>
                <span class="auto-trade-status ${autoOn ? 'on' : 'off'}">${autoOn ? 'AUTO' : 'OFF'}</span>
            </div>
        </div>`;
    }).join('');

    // Attach toggle handlers
    container.querySelectorAll('.auto-trade-toggle').forEach(toggle => {
        toggle.addEventListener('change', async function() {
            const sid = this.dataset.scanner;
            const on = this.checked;
            if (on) {
                const ok = await showConfirm('Enable Auto Trading', 'This scanner will automatically execute trades based on its strategy signals. Are you sure?');
                if (!ok) { this.checked = false; return; }
            }
            if (_activeScanners[sid]) {
                _activeScanners[sid].autoTrade = on;
                const label = this.closest('.auto-toggle-wrap').querySelector('.auto-trade-status');
                if (label) { label.textContent = on ? 'AUTO' : 'OFF'; label.className = `auto-trade-status ${on ? 'on' : 'off'}`; }
                showToast(on ? 'Auto-trade enabled' : 'Auto-trade disabled', on ? 'success' : 'info');
            }
        });
    });
}
