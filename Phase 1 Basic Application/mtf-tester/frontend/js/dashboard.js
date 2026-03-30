/**
 * DASHBOARD.JS v2 — Navigation, MT5 connection, account info, dynamic strategy panels
 *                   Uses TradingView LightweightCharts for live candlestick rendering.
 */

// ── Global State ──────────────────────────────────────────────
let _strategies = [];
let _activeScanners = {};   // id → { ws, config, name }
let _scannerIdCounter = 0;
let _chartInstances = {};   // `${scannerId}-${tf}` → { chart, candleSeries, indicatorSeries, markers }
let _expandedState = { chart: null, candles: null, tf: null, scannerId: null };
let _mt5Symbols = [];       // [{name, description, spread, ...}] loaded from MT5
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
        // Show the dropdown with initial symbols
        filterSymbolList();
    } catch (err) {
        console.error('Failed to load symbols:', err);
        _mt5Symbols = [];
    }
}

function filterSymbolList() {
    const input = document.getElementById('cfg-symbol');
    const dropdown = document.getElementById('cfg-symbol-dropdown');
    if (!input || !dropdown) return;

    const q = input.value.trim().toLowerCase();

    if (_mt5Symbols.length === 0) {
        dropdown.innerHTML = '<div class="sym-empty">Connect to MT5 to load symbols</div>';
        dropdown.classList.add('open');
        return;
    }

    // Filter
    const filtered = _mt5Symbols.filter(s =>
        s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q)
    );

    if (filtered.length === 0) {
        dropdown.innerHTML = '<div class="sym-empty">No symbols match your search</div>';
        dropdown.classList.add('open');
        return;
    }

    // Show max 40 results
    dropdown.innerHTML = filtered.slice(0, 40).map(s => `
        <div class="sym-item ${input.value === s.name ? 'active' : ''}" onclick="selectSymbol('${s.name}')">
            <span class="sym-name">${s.name}</span>
            <span class="sym-desc">${s.description || ''}</span>
        </div>
    `).join('');
    dropdown.classList.add('open');
}

function selectSymbol(name) {
    const input = document.getElementById('cfg-symbol');
    const dropdown = document.getElementById('cfg-symbol-dropdown');
    if (input) input.value = name;
    if (dropdown) dropdown.classList.remove('open');
}

// Close symbol dropdown when clicking outside
document.addEventListener('click', (e) => {
    const dropdown = document.getElementById('cfg-symbol-dropdown');
    const input = document.getElementById('cfg-symbol');
    if (dropdown && !dropdown.contains(e.target) && e.target !== input) {
        dropdown.classList.remove('open');
    }
});

// Show dropdown when focusing on the symbol input
document.addEventListener('focusin', (e) => {
    if (e.target && e.target.id === 'cfg-symbol') {
        filterSymbolList();
    }
});

async function refreshAccountInfo() {
    try {
        const info = await api('/api/order/account');
        updateAccountDisplay(info);
        // Also update positions count
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

        sel.addEventListener('change', () => renderStratSettings(sel.value));
        if (_strategies.length > 0) renderStratSettings(_strategies[0].name);

        // Timeframe chips
        document.querySelectorAll('.tf-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                chip.classList.toggle('selected');
            });
        });

        // Launch form
        document.getElementById('mtf-config-form').addEventListener('submit', (e) => {
            e.preventDefault();
            handleLaunchScanner();
        });
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

// ═══ LAUNCH SCANNER → CREATE DYNAMIC PANEL ════════════════════
async function handleLaunchScanner() {
    const name = document.getElementById('cfg-name').value.trim();
    const symbol = document.getElementById('cfg-symbol').value.trim();
    const strategy = document.getElementById('cfg-strategy').value;
    const tfChips = document.querySelectorAll('#cfg-timeframes .tf-chip.selected');
    const timeframes = Array.from(tfChips).map(c => c.dataset.tf);

    if (!name) { showToast('Enter a session name', 'warning'); return; }
    if (!symbol) { showToast('Enter a symbol', 'warning'); return; }
    if (timeframes.length === 0) { showToast('Select at least one timeframe', 'warning'); return; }
    if (timeframes.length > 4) { showToast('Maximum 4 timeframes allowed', 'warning'); return; }

    const id = `strat-${++_scannerIdCounter}`;
    const config = { symbol, timeframes, strategy_name: strategy, settings: getStratSettings(), provider: 'mt5' };

    // Create panel with loading spinners first
    createDynamicPanel(id, name, config);
    switchPanel(id);

    // Update status to "Loading..."
    const status = document.getElementById(`${id}-status`);
    if (status) status.innerHTML = `<span class="dot dot-pending"></span><span>Loading data...</span>`;

    // ── Step 1: REST call to fetch historical data ────────────
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

        // Store scanner info with backend scanner_id
        _activeScanners[id] = { ws: null, config: { ...config, _name: name }, signals: [], name, autoTrade: false, scannerId };

        // ── Step 2: Render historical charts immediately ──────
        const candles = data.historical_candles || {};
        const indicators = data.historical_indicators || {};
        const signals = data.historical_signals || [];

        for (const [tf, bars] of Object.entries(candles)) {
            if (bars && bars.length > 0) {
                initLWChart(id, tf, bars, indicators[tf] || {});
            }
        }

        // Process historical signals (markers + badges)
        const markersByTf = {};
        for (const sig of signals) {
            _activeScanners[id].signals.push(sig);
            updateGlobalSignals(sig);
            const sigEl = document.getElementById(`${id}-sig-${sig.timeframe}`);
            if (sigEl) {
                const cls = sig.direction === 'BUY' ? 'long' : 'short';
                sigEl.innerHTML = `<span class="badge badge-${cls}">${sig.direction}</span>`;
            }
            if (!markersByTf[sig.timeframe]) markersByTf[sig.timeframe] = [];
            markersByTf[sig.timeframe].push({
                time: _toChartTs(sig.bar_time),
                position: sig.direction === 'BUY' ? 'belowBar' : 'aboveBar',
                color: sig.direction === 'BUY' ? '#22c55e' : '#ef4444',
                shape: sig.direction === 'BUY' ? 'arrowUp' : 'arrowDown',
                text: sig.direction,
            });
        }
        for (const tf in markersByTf) {
            const key = `${id}-${tf}`;
            if (_chartInstances[key]) {
                const markers = markersByTf[tf].sort((a, b) => a.time - b.time);
                _chartInstances[key].markers = markers;
                try { _chartInstances[key].candleSeries.setMarkers(markers); } catch(e) {}
            }
        }
        if (signals.length > 0) updateSignalStrip(id);

        showToast(`✓ Data loaded — ${Object.keys(candles).length} timeframes rendered`, 'success');

        // ── Step 3: Connect WebSocket for live updates ────────
        if (status) status.innerHTML = `<span class="dot dot-on"></span><span>Live</span>`;
        startScannerWS(id, scannerId);

    } catch (err) {
        console.error('Scanner start failed:', err);
        if (status) status.innerHTML = `<span class="dot dot-off"></span><span>Error</span>`;
        showToast(`Scanner failed: ${err.message}`, 'error');
    }

    setTimeout(() => refreshAutoTradeList(), 500);
}

function createDynamicPanel(id, name, config) {
    // ── Add Nav Item ──────────────────────────────────────────
    const divider = document.getElementById('strat-divider');
    divider.style.display = '';

    const navList = document.getElementById('strat-nav-list');
    const navItem = document.createElement('div');
    navItem.className = 'nav-item';
    navItem.dataset.panel = id;
    navItem.innerHTML = `
        <span class="nav-icon">📈</span>
        <span class="nav-label">${name}</span>
        <span class="nav-badge">${config.timeframes.length}TF</span>
        <span class="nav-close" data-remove="${id}" title="Remove">✕</span>
    `;
    navItem.addEventListener('click', (e) => {
        if (e.target.classList.contains('nav-close')) return;
        switchPanel(id);
    });
    navList.appendChild(navItem);

    // Close button
    navItem.querySelector('.nav-close').addEventListener('click', (e) => {
        e.stopPropagation();
        removeScanner(id, name);
    });

    // ── Create Panel ──────────────────────────────────────────
    const colClass = `cols-${Math.min(config.timeframes.length, 4)}`;
    const panel = document.createElement('div');
    panel.className = 'panel';
    panel.id = `panel-${id}`;

    panel.innerHTML = `
        <div class="panel-header">
            <div style="display:flex; align-items:center; gap: var(--sp-3);">
                <span class="panel-header-title">${name}</span>
                <span class="badge badge-info">${config.symbol}</span>
                <span class="badge badge-muted">${config.strategy_name}</span>
            </div>
            <div class="panel-header-actions">
                <div class="conn-pill" id="${id}-status">
                    <span class="dot dot-pending"></span>
                    <span>Connecting...</span>
                </div>
            </div>
        </div>
        <div class="signal-strip" id="${id}-strip">
            <span style="color:var(--text-3);">Loading charts...</span>
        </div>
        <div class="chart-grid ${colClass}" id="${id}-charts">
            ${config.timeframes.map(tf => `
                <div class="chart-cell" id="${id}-cell-${tf}">
                    <div class="chart-cell-header">
                        <span class="chart-cell-tf">${tf}</span>
                        <div style="display:flex; align-items:center; gap: 6px;">
                            <span class="chart-cell-price mono" id="${id}-price-${tf}">—</span>
                            <button class="chart-expand-btn" onclick="openExpandedChart('${id}', '${tf}')" title="Expand Chart">&#x26F6;</button>
                        </div>
                    </div>
                    <div class="chart-cell-body" id="${id}-canvas-${tf}">
                        <div class="empty-state" style="padding: 40px;"><div class="spinner-lg"></div></div>
                    </div>
                    <div class="chart-cell-signal" id="${id}-sig-${tf}"></div>
                </div>
            `).join('')}
        </div>
    `;

    document.getElementById('dynamic-panels').appendChild(panel);
}

async function removeScanner(id, name) {
    const ok = await showConfirm('Remove Scanner', `Stop and remove "${name}"?`);
    if (!ok) return;

    // Close WebSocket + stop backend scanner
    if (_activeScanners[id]) {
        const ws = _activeScanners[id].ws;
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: 'stop' }));
            ws.close();
        }
        // Stop backend scanner via REST
        const scannerId = _activeScanners[id].scannerId;
        if (scannerId) {
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
        }
        // Destroy LightweightCharts instances for this scanner
        const config = _activeScanners[id].config;
        if (config && config.timeframes) {
            config.timeframes.forEach(tf => {
                const key = `${id}-${tf}`;
                if (_chartInstances[key]) {
                    try { _chartInstances[key].chart.remove(); } catch(e) {}
                    delete _chartInstances[key];
                }
            });
        }
        delete _activeScanners[id];
    }

    // Remove nav item
    const nav = document.querySelector(`.nav-item[data-panel="${id}"]`);
    if (nav) nav.remove();

    // Remove panel
    const panel = document.getElementById(`panel-${id}`);
    if (panel) panel.remove();

    // Hide divider if no more strategy panels
    const navList = document.getElementById('strat-nav-list');
    if (navList && navList.children.length === 0) {
        document.getElementById('strat-divider').style.display = 'none';
    }

    // Switch to dashboard
    switchPanel('dashboard');
    showToast(`Scanner "${name}" removed`, 'info');
}

// ═══ WEBSOCKET — LIVE UPDATES ONLY ═══════════════════════════
function startScannerWS(id, scannerId) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/api/chart/ws/${scannerId}`);

    if (_activeScanners[id]) {
        _activeScanners[id].ws = ws;
    }

    ws.onopen = () => {
        console.log(`WS connected for scanner ${scannerId}`);
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleScannerMsg(id, msg);
        } catch (e) { console.error('WS parse error:', e); }
    };

    ws.onerror = () => {
        console.warn('Scanner WS error — live updates may be delayed');
    };

    ws.onclose = () => {
        const status = document.getElementById(`${id}-status`);
        if (status && _activeScanners[id]) {
            status.innerHTML = `<span class="dot dot-off"></span><span>Reconnecting...</span>`;
            // Auto-reconnect after 3 seconds
            setTimeout(() => {
                if (_activeScanners[id]) {
                    startScannerWS(id, scannerId);
                }
            }, 3000);
        }
    };
}

function handleScannerMsg(id, msg) {
    const scanner = _activeScanners[id];
    if (!scanner) return;

    // ── Historical: contains candles keyed by TF ─────────────
    if (msg.type === 'historical') {
        const candles = msg.data.candles || {};
        const indicators = msg.data.indicators || {};

        for (const [tf, bars] of Object.entries(candles)) {
            if (bars && bars.length > 0) {
                initLWChart(id, tf, bars, indicators[tf] || {});
            }
        }

        // Process historical signals
        const signals = msg.data.signals || [];
        // Group markers by timeframe
        const markersByTf = {};
        for (const sig of signals) {
            scanner.signals.push(sig);
            updateGlobalSignals(sig);
            const sigEl = document.getElementById(`${id}-sig-${sig.timeframe}`);
            if (sigEl) {
                const cls = sig.direction === 'BUY' ? 'long' : 'short';
                sigEl.innerHTML = `<span class="badge badge-${cls}">${sig.direction}</span>`;
            }
            // Collect markers
            if (!markersByTf[sig.timeframe]) markersByTf[sig.timeframe] = [];
            markersByTf[sig.timeframe].push({
                time: _toChartTs(sig.bar_time),
                position: sig.direction === 'BUY' ? 'belowBar' : 'aboveBar',
                color: sig.direction === 'BUY' ? '#22c55e' : '#ef4444',
                shape: sig.direction === 'BUY' ? 'arrowUp' : 'arrowDown',
                text: sig.direction,
            });
        }
        // Apply markers to charts
        for (const tf in markersByTf) {
            const key = `${id}-${tf}`;
            if (_chartInstances[key]) {
                const markers = markersByTf[tf].sort((a, b) => a.time - b.time);
                _chartInstances[key].markers = markers;
                try { _chartInstances[key].candleSeries.setMarkers(markers); } catch(e) {}
            }
        }
        if (signals.length > 0) updateSignalStrip(id);
    }

    // ── Bar updates (plural): array of {symbol, timeframe, bar}
    if (msg.type === 'bar_updates') {
        const updates = msg.data || [];
        for (const upd of updates) {
            const tf = upd.timeframe;
            const bar = upd.bar;
            if (!tf || !bar) continue;

            const key = `${id}-${tf}`;
            const inst = _chartInstances[key];
            if (inst && inst.candleSeries) {
                // Incremental update — no full re-render!
                try {
                    inst.candleSeries.update({
                        time: _toChartTs(bar.time),
                        open: bar.open,
                        high: bar.high,
                        low: bar.low,
                        close: bar.close,
                    });
                } catch(e) { console.error('Chart update error:', e); }

                // Also update expanded chart if it's viewing this tf
                if (_expandedState.scannerId === id && _expandedState.tf === tf && _expandedState.candles) {
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
            // Update price display
            const priceEl = document.getElementById(`${id}-price-${tf}`);
            if (priceEl) priceEl.textContent = fmtPrice(bar.close);
        }
    }

    // ── Single bar update (legacy compat) ────────────────────
    if (msg.type === 'bar_update') {
        const bar = msg.data.bar || msg.data;
        const tf = msg.data.timeframe || msg.timeframe;
        if (tf && bar) {
            const key = `${id}-${tf}`;
            const inst = _chartInstances[key];
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
        }
    }

    // ── Signal ───────────────────────────────────────────────
    if (msg.type === 'signal') {
        const sig = msg.data;
        scanner.signals.unshift(sig);
        if (scanner.signals.length > 50) scanner.signals = scanner.signals.slice(0, 50);

        // Update signal badge on chart cell
        const sigEl = document.getElementById(`${id}-sig-${sig.timeframe}`);
        if (sigEl) {
            const cls = sig.direction === 'BUY' ? 'long' : 'short';
            sigEl.innerHTML = `<span class="badge badge-${cls}">${sig.direction}</span>`;
        }

        // Add marker to chart
        const key = `${id}-${sig.timeframe}`;
        const inst = _chartInstances[key];
        if (inst) {
            const marker = {
                time: _toChartTs(sig.bar_time),
                position: sig.direction === 'BUY' ? 'belowBar' : 'aboveBar',
                color: sig.direction === 'BUY' ? '#22c55e' : '#ef4444',
                shape: sig.direction === 'BUY' ? 'arrowUp' : 'arrowDown',
                text: sig.direction,
            };
            if (!inst.markers) inst.markers = [];
            inst.markers.push(marker);
            inst.markers.sort((a, b) => a.time - b.time);
            try { inst.candleSeries.setMarkers(inst.markers); } catch(e) {}

            // Glow animation on the chart cell
            const cell = document.getElementById(`${id}-cell-${sig.timeframe}`);
            if (cell) {
                cell.classList.remove('chart-glow-buy', 'chart-glow-sell');
                void cell.offsetWidth; // force reflow
                cell.classList.add(sig.direction === 'BUY' ? 'chart-glow-buy' : 'chart-glow-sell');
            }

            // Update expanded chart markers if viewing this tf
            if (_expandedState.scannerId === id && _expandedState.tf === sig.timeframe && _expandedState.candles) {
                try { _expandedState.candles.setMarkers(inst.markers); } catch(e) {}
            }
        }

        // Update signal strip
        updateSignalStrip(id);

        // Update global signals log
        updateGlobalSignals(sig);

        showToast(`${sig.direction} · ${sig.symbol} [${sig.timeframe}] @ ${fmtPrice(sig.price)}`,
            sig.direction === 'BUY' ? 'success' : 'error', 5000);
    }

    // ── Price tick ───────────────────────────────────────────
    if (msg.type === 'price') {
        const tf = msg.data.timeframe;
        const price = msg.data.price;
        const priceEl = document.getElementById(`${id}-price-${tf}`);
        if (priceEl) priceEl.textContent = fmtPrice(price);
    }

    // ── Error ────────────────────────────────────────────────
    if (msg.type === 'error') {
        showToast(msg.data || 'Scanner error', 'error');
    }
}

function updateSignalStrip(id) {
    const scanner = _activeScanners[id];
    if (!scanner) return;
    const strip = document.getElementById(`${id}-strip`);
    if (!strip) return;

    const items = scanner.signals.slice(0, 8).map(s => {
        const cls = s.direction === 'BUY' ? 'buy' : 'sell';
        return `<div class="signal-strip-item ${cls}">
            <span>${s.direction}</span>
            <span class="mono">${s.timeframe}</span>
            <span class="mono">${fmtPrice(s.price)}</span>
            <span style="opacity:0.6;">${fmtTime(s.bar_time || s.time)}</span>
        </div>`;
    }).join('');

    strip.innerHTML = items || '<span style="color:var(--text-3);">No signals yet</span>';
}

function updateGlobalSignals(sig) {
    const log = document.getElementById('signals-log');
    if (!log) return;

    // Remove empty state
    const empty = log.querySelector('.empty-state');
    if (empty) empty.remove();

    const cls = sig.direction === 'BUY' ? 'long' : 'short';
    const el = document.createElement('div');
    el.className = 'sig-entry';
    el.innerHTML = `
        <span class="badge badge-${cls}">${sig.direction}</span>
        <div class="sig-entry-info">
            <span class="sig-entry-pair">${sig.symbol} · ${sig.timeframe}</span>
            <span class="sig-entry-time">${fmtTime(sig.bar_time || sig.time)}</span>
        </div>
        <span class="sig-entry-price">${fmtPrice(sig.price)}</span>
    `;
    log.insertBefore(el, log.firstChild);

    // Keep max 30 entries
    while (log.children.length > 30) log.removeChild(log.lastChild);
}

// ═══ LIGHTWEIGHT CHARTS — TIMESTAMP UTILITY ═══════════════════
function _toChartTs(isoStr) {
    if (!isoStr) return 0;
    return Math.floor(new Date(isoStr + (isoStr.includes('+') || isoStr.includes('Z') ? '' : 'Z')).getTime() / 1000);
}

function _getChartColors() {
    return {
        bg: '#0d1421',
        text: '#94a3b8',
        grid: '#1e2d42',
        border: '#1e2d42',
    };
}

// ═══ LIGHTWEIGHT CHARTS — INIT ════════════════════════════════
function initLWChart(scannerId, tf, bars, indicatorData) {
    const key = `${scannerId}-${tf}`;
    const container = document.getElementById(`${scannerId}-canvas-${tf}`);
    if (!container) return;

    // Destroy previous chart instance if exists
    if (_chartInstances[key]) {
        try { _chartInstances[key].chart.remove(); } catch(e) {}
        delete _chartInstances[key];
    }

    // Clear loading spinner
    container.innerHTML = '';

    const colors = _getChartColors();
    const chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: container.clientHeight || 250,
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

    // Add indicator line series
    const indicatorSeriesMap = {};
    if (indicatorData && Object.keys(indicatorData).length > 0) {
        const lineColors = ['#3b82f6', '#f59e0b', '#8b5cf6', '#06b6d4', '#ec4899', '#14b8a6'];
        let colorIdx = 0;

        for (const [indName, dataPoints] of Object.entries(indicatorData)) {
            if (!dataPoints || dataPoints.length === 0) continue;

            const line = chart.addLineSeries({
                color: lineColors[colorIdx % lineColors.length],
                lineWidth: 1,
                title: indName,
            });

            const sortedPts = [...dataPoints]
                .map(p => ({ time: _toChartTs(p.time), value: p.value }))
                .sort((a, b) => a.time - b.time);

            // Deduplicate
            const uniquePts = [];
            const ptSeen = new Set();
            for (const pt of sortedPts) {
                if (!ptSeen.has(pt.time)) {
                    ptSeen.add(pt.time);
                    uniquePts.push(pt);
                }
            }

            try { line.setData(uniquePts); } catch(e) {}
            indicatorSeriesMap[indName] = line;
            colorIdx++;
        }
    }

    // Store instance
    _chartInstances[key] = {
        chart,
        candleSeries,
        indicatorSeriesMap,
        markers: [],
    };

    // Update price display
    if (uniqueBars.length > 0) {
        const lastClose = uniqueBars[uniqueBars.length - 1].close;
        const priceEl = document.getElementById(`${scannerId}-price-${tf}`);
        if (priceEl) priceEl.textContent = fmtPrice(lastClose);
    }
}

// ═══ CHART EXPAND MODAL ═══════════════════════════════════════
function openExpandedChart(scannerId, tf) {
    const key = `${scannerId}-${tf}`;
    const inst = _chartInstances[key];
    if (!inst) return;

    const modal = document.getElementById('chart-expand-modal');
    const container = document.getElementById('chart-modal-container');
    const title = document.getElementById('chart-modal-title');
    const scanner = _activeScanners[scannerId];
    const symbol = scanner ? scanner.config.symbol : '';

    title.innerHTML = `${symbol} <span style="color: var(--accent); font-weight: 600;">${tf}</span>`;
    container.innerHTML = '';

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

    // Clone indicators
    if (inst.indicatorSeriesMap) {
        for (const [indName, indSeries] of Object.entries(inst.indicatorSeriesMap)) {
            try {
                const line = chart.addLineSeries({
                    color: indSeries.options().color,
                    lineWidth: indSeries.options().lineWidth,
                    title: indName,
                });
                line.setData(indSeries.data());
            } catch(e) {}
        }
    }

    // Store expanded state for live updates
    _expandedState = { chart, candles: candleSeries, tf, scannerId };

    modal.classList.add('open');

    // Force resize after modal animation
    setTimeout(() => {
        chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
    }, 50);
}

function closeExpandedChart() {
    const modal = document.getElementById('chart-expand-modal');
    modal.classList.remove('open');

    if (_expandedState.chart) {
        try { _expandedState.chart.remove(); } catch(e) {}
        _expandedState = { chart: null, candles: null, tf: null, scannerId: null };
    }
}

// ── Bind chart modal close ───────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const closeBtn = document.getElementById('chart-modal-close');
    if (closeBtn) closeBtn.addEventListener('click', closeExpandedChart);

    const modal = document.getElementById('chart-expand-modal');
    if (modal) modal.addEventListener('click', (e) => {
        if (e.target === modal) closeExpandedChart();
    });

    // Handle window resize for all active charts
    window.addEventListener('resize', () => {
        for (const key in _chartInstances) {
            const inst = _chartInstances[key];
            const parts = key.split('-');
            const tf = parts[parts.length - 1];
            const scannerId = parts.slice(0, -1).join('-');
            const container = document.getElementById(`${scannerId}-canvas-${tf}`);
            if (container && inst.chart) {
                try {
                    inst.chart.applyOptions({ width: container.clientWidth });
                } catch(e) {}
            }
        }
    });
});

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
            const symbol = document.getElementById('order-symbol').value.trim().toUpperCase();
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

            // ── SAFETY: Confirmation Dialog ─────────────────────
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
        // Load current risk state
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

    // ── Auto Trade: populate scanner list ─────────────────────
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

    container.innerHTML = ids.map(id => {
        const sc = _activeScanners[id];
        const cfg = sc.config;
        const name = sc.name || id;
        const autoOn = sc.autoTrade || false;
        return `<div class="auto-scanner-row">
            <div class="auto-scanner-info">
                <span class="auto-scanner-name">${name}</span>
                <span class="auto-scanner-meta">${cfg.symbol} · ${cfg.strategy_name} · ${cfg.timeframes.join(', ')}</span>
            </div>
            <div class="auto-toggle-wrap">
                <label class="toggle-switch">
                    <input type="checkbox" ${autoOn ? 'checked' : ''} data-scanner="${id}" class="auto-trade-toggle">
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

