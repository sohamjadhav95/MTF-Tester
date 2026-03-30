/**
 * DASHBOARD.JS v2 — Navigation, MT5 connection, account info, dynamic strategy panels
 */

// ── Global State ──────────────────────────────────────────────
let _strategies = [];
let _activeScanners = {};   // id → { ws, config, name }
let _scannerIdCounter = 0;

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

    // Check initial status
    api('/api/data/mt5/status').then(d => setMT5Connected(d.connected, d.account)).catch(() => {});

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
function handleLaunchScanner() {
    const name = document.getElementById('cfg-name').value.trim();
    const symbol = document.getElementById('cfg-symbol').value.trim().toUpperCase();
    const strategy = document.getElementById('cfg-strategy').value;
    const tfChips = document.querySelectorAll('#cfg-timeframes .tf-chip.selected');
    const timeframes = Array.from(tfChips).map(c => c.dataset.tf);

    if (!name) { showToast('Enter a session name', 'warning'); return; }
    if (!symbol) { showToast('Enter a symbol', 'warning'); return; }
    if (timeframes.length === 0) { showToast('Select at least one timeframe', 'warning'); return; }
    if (timeframes.length > 4) { showToast('Maximum 4 timeframes allowed', 'warning'); return; }

    const id = `strat-${++_scannerIdCounter}`;
    const config = { symbol, timeframes, strategy_name: strategy, settings: getStratSettings(), provider: 'mt5' };

    createDynamicPanel(id, name, config);
    switchPanel(id);
    showToast(`Scanner "${name}" launched`, 'success');
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
            <span style="color:var(--text-3);">Waiting for signals...</span>
        </div>
        <div class="chart-grid ${colClass}" id="${id}-charts">
            ${config.timeframes.map(tf => `
                <div class="chart-cell" id="${id}-cell-${tf}">
                    <div class="chart-cell-header">
                        <span class="chart-cell-tf">${tf}</span>
                        <span class="chart-cell-price mono" id="${id}-price-${tf}">—</span>
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

    // ── Start WebSocket ───────────────────────────────────────
    startScannerWS(id, config);
}

async function removeScanner(id, name) {
    const ok = await showConfirm('Remove Scanner', `Stop and remove "${name}"?`);
    if (!ok) return;

    // Close WebSocket
    if (_activeScanners[id]) {
        const ws = _activeScanners[id].ws;
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: 'stop' }));
            ws.close();
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

// ═══ WEBSOCKET SCANNER ════════════════════════════════════════
function startScannerWS(id, config) {
    const token = Auth.getToken();
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/api/chart/ws/${id}`);

    _activeScanners[id] = { ws, config, signals: [] };

    ws.onopen = () => {
        ws.send(JSON.stringify({ action: 'start', config }));
        const status = document.getElementById(`${id}-status`);
        if (status) status.innerHTML = `<span class="dot dot-on"></span><span>Live</span>`;
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleScannerMsg(id, msg);
        } catch (e) { console.error('WS parse error:', e); }
    };

    ws.onerror = () => {
        showToast('Scanner connection error', 'error');
    };

    ws.onclose = () => {
        const status = document.getElementById(`${id}-status`);
        if (status) status.innerHTML = `<span class="dot dot-off"></span><span>Stopped</span>`;
    };
}

function handleScannerMsg(id, msg) {
    const scanner = _activeScanners[id];
    if (!scanner) return;

    if (msg.type === 'bar_update' || msg.type === 'historical') {
        // Render chart candles
        const bars = msg.data.bars || msg.data;
        const tf = msg.data.timeframe || msg.timeframe;
        if (tf && bars) renderCandleChart(id, tf, bars);
    }

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

        // Update signal strip
        updateSignalStrip(id);

        // Update global signals log
        updateGlobalSignals(sig);

        showToast(`${sig.direction} · ${sig.symbol} [${sig.timeframe}] @ ${fmtPrice(sig.price)}`,
            sig.direction === 'BUY' ? 'success' : 'error', 5000);
    }

    if (msg.type === 'price') {
        const tf = msg.data.timeframe;
        const price = msg.data.price;
        const priceEl = document.getElementById(`${id}-price-${tf}`);
        if (priceEl) priceEl.textContent = fmtPrice(price);
    }

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

// ═══ CANDLESTICK CHART RENDERER ═══════════════════════════════
function renderCandleChart(scannerId, tf, bars) {
    const container = document.getElementById(`${scannerId}-canvas-${tf}`);
    if (!container || !bars || bars.length === 0) return;

    const W = container.offsetWidth || 400;
    const H = container.offsetHeight || 250;
    const pad = { t: 10, r: 55, b: 20, l: 8 };
    const plotW = W - pad.l - pad.r;
    const plotH = H - pad.t - pad.b;

    // Take last N bars that fit
    const candleW = Math.max(3, Math.min(12, Math.floor(plotW / 80)));
    const gap = Math.max(1, Math.floor(candleW * 0.4));
    const maxBars = Math.floor(plotW / (candleW + gap));
    const data = bars.slice(-maxBars);

    if (data.length === 0) return;

    const highs = data.map(b => b.high);
    const lows = data.map(b => b.low);
    const maxPrice = Math.max(...highs);
    const minPrice = Math.min(...lows);
    const range = maxPrice - minPrice || 0.0001;

    const yScale = (p) => pad.t + plotH - ((p - minPrice) / range) * plotH;
    const xPos = (i) => pad.l + i * (candleW + gap) + gap;

    let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="display:block;width:100%;height:100%;" preserveAspectRatio="none">`;

    // Background
    svg += `<rect width="${W}" height="${H}" fill="var(--bg-card)" rx="0"/>`;

    // Grid lines
    const gridLines = 5;
    for (let i = 0; i <= gridLines; i++) {
        const y = pad.t + (plotH / gridLines) * i;
        const price = maxPrice - (range / gridLines) * i;
        svg += `<line x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}" stroke="var(--border-1)" stroke-width="0.5"/>`;
        svg += `<text x="${W - pad.r + 4}" y="${y + 3}" fill="var(--text-3)" font-size="9" font-family="var(--ff-mono)">${price.toFixed(price > 100 ? 2 : 5)}</text>`;
    }

    // Candles
    data.forEach((b, i) => {
        const x = xPos(i);
        const isBull = b.close >= b.open;
        const color = isBull ? 'var(--long)' : 'var(--short)';
        const bodyTop = yScale(Math.max(b.open, b.close));
        const bodyBot = yScale(Math.min(b.open, b.close));
        const bodyH = Math.max(1, bodyBot - bodyTop);
        const wickX = x + candleW / 2;

        // Wick
        svg += `<line x1="${wickX}" y1="${yScale(b.high)}" x2="${wickX}" y2="${yScale(b.low)}" stroke="${color}" stroke-width="1"/>`;
        // Body
        if (isBull) {
            svg += `<rect x="${x}" y="${bodyTop}" width="${candleW}" height="${bodyH}" fill="none" stroke="${color}" stroke-width="1" rx="0.5"/>`;
        } else {
            svg += `<rect x="${x}" y="${bodyTop}" width="${candleW}" height="${bodyH}" fill="${color}" rx="0.5"/>`;
        }
    });

    // Current price line
    const lastClose = data[data.length - 1].close;
    const lastY = yScale(lastClose);
    const lineColor = data[data.length - 1].close >= data[data.length - 1].open ? 'var(--long)' : 'var(--short)';
    svg += `<line x1="${pad.l}" y1="${lastY}" x2="${W - pad.r}" y2="${lastY}" stroke="${lineColor}" stroke-width="0.7" stroke-dasharray="3,3" opacity="0.6"/>`;
    svg += `<rect x="${W - pad.r}" y="${lastY - 8}" width="50" height="16" fill="${lineColor}" rx="2"/>`;
    svg += `<text x="${W - pad.r + 4}" y="${lastY + 3}" fill="#fff" font-size="9" font-weight="600" font-family="var(--ff-mono)">${lastClose.toFixed(lastClose > 100 ? 2 : 5)}</text>`;

    svg += '</svg>';
    container.innerHTML = svg;

    // Update price display
    const priceEl = document.getElementById(`${scannerId}-price-${tf}`);
    if (priceEl) priceEl.textContent = fmtPrice(lastClose);
}
