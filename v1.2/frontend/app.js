// ─── Strategy Tester — Vanilla JS Application ─────────────────
const API = '';

// ─── App State ──────────────────────────────────────────────────
const state = {
  mt5Connected: false,
  accountInfo: null,
  symbols: [],
  timeframes: [],
  strategies: [],
  strategySettings: null,
  config: {
    symbol: '', timeframe: 'H1', dateFrom: '', dateTo: '',
    strategy: '', settings: {},
    initialBalance: 10000, lotSize: 0.1,
  },
  results: null,
  backtesting: false,
};

let equityChartInst = null;
let priceChartInst = null;

// ─── API Helpers ────────────────────────────────────────────────
async function api(url, opts = {}) {
  const res = await fetch(API + url, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || 'API error');
  return data;
}

// ─── Theme Toggle ────────────────────────────────────────────────
function toggleTheme() {
  const html = document.documentElement;
  const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  document.getElementById('theme-icon').textContent = next === 'dark' ? '☀️' : '🌙';
  localStorage.setItem('theme', next);
  if (state.results) {
    const isPrice = document.getElementById('tab-price').classList.contains('active');
    if (isPrice) renderPriceChart();
    else renderEquityChart();
  }
}

function applyThemeFromStorage() {
  const saved = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  const icon = document.getElementById('theme-icon');
  if (icon) icon.textContent = saved === 'dark' ? '☀️' : '🌙';
}

// ─── Chart Tab Switching ─────────────────────────────────────────
function switchChartTab(tab) {
  const priceWrap = document.getElementById('price-chart-wrap');
  const equityWrap = document.getElementById('equity-chart-wrap');
  const tabPrice = document.getElementById('tab-price');
  const tabEquity = document.getElementById('tab-equity');

  if (tab === 'price') {
    priceWrap.style.display = '';
    equityWrap.style.display = 'none';
    tabPrice.classList.add('active');
    tabEquity.classList.remove('active');
    if (state.results && !priceChartInst) renderPriceChart();
  } else {
    priceWrap.style.display = 'none';
    equityWrap.style.display = '';
    tabEquity.classList.add('active');
    tabPrice.classList.remove('active');
    if (state.results && !equityChartInst) renderEquityChart();
  }
}

// ─── Chart Color Helper ──────────────────────────────────────────
function getChartColors() {
  const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
  return {
    bg: isDark ? '#0d1421' : '#ffffff',
    text: isDark ? '#94a3b8' : '#64748b',
    grid: isDark ? '#1e2d42' : '#e2e8f0',
    border: isDark ? '#1e2d42' : '#e2e8f0',
  };
}

// ─── Timestamp Utilities ─────────────────────────────────────────
// backend always returns ISO strings WITHOUT timezone offset (UTC)
function toTs(isoStr) {
  // Convert "2024-01-15T09:00:00" → UNIX integer seconds (UTC)
  return Math.floor(new Date(isoStr + (isoStr.includes('+') ? '' : 'Z')).getTime() / 1000);
}

function fmtTimeUTC(isoStr) {
  if (!isoStr) return '—';
  try {
    // Treat as UTC by appending Z (backend strips tz)
    const ts = isoStr.includes('Z') || isoStr.includes('+') ? isoStr : isoStr + 'Z';
    const d = new Date(ts);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  } catch { return isoStr; }
}

// ─── Initialization ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  applyThemeFromStorage();
  renderMT5Section();
  renderConfigCols();
});

// ─── Market Type ────────────────────────────────────────────────
function setMarketType(type) {
  document.getElementById('btn-forex').classList.toggle('active', type === 'forex');
  document.getElementById('btn-crypto').classList.toggle('active', type === 'crypto');
}

// ─── MT5 Section ────────────────────────────────────────────────
function renderMT5Section() {
  const el = document.getElementById('mt5-section');
  if (state.mt5Connected && state.accountInfo) {
    const a = state.accountInfo;
    el.innerHTML = `
      <div class="sidebar-content-scroll">
        <div class="connection-status">
          <span class="status-dot connected"></span>
          <span class="status-text">MT5 Connected</span>
        </div>
        <div class="account-details">
          <div class="detail-row"><span class="detail-label">Account</span><span class="detail-value">${a.login}</span></div>
          <div class="detail-row"><span class="detail-label">Name</span><span class="detail-value">${a.name}</span></div>
          <div class="detail-row"><span class="detail-label">Server</span><span class="detail-value">${a.server}</span></div>
          <div class="detail-row"><span class="detail-label">Balance</span><span class="detail-value text-profit">${a.currency} ${a.balance?.toLocaleString()}</span></div>
          <div class="detail-row"><span class="detail-label">Broker</span><span class="detail-value">${a.company}</span></div>
        </div>
        <button class="btn-disconnect" onclick="disconnectMT5()">Disconnect</button>
      </div>`;
  } else {
    el.innerHTML = `
      <div class="sidebar-content-scroll">
        <div class="connection-status">
          <span class="status-dot disconnected"></span>
          <span class="status-text">MT5 Disconnected</span>
        </div>
        <div id="mt5-error"></div>
        <form onsubmit="connectMT5(event)">
          <div class="form-group">
            <label>Server</label>
            <input type="text" id="mt5-server" placeholder="e.g. Exness-MT5Real" required />
          </div>
          <div class="form-group">
            <label>Login</label>
            <input type="text" id="mt5-login" placeholder="Account number" required />
          </div>
          <div class="form-group">
            <label>Password</label>
            <input type="password" id="mt5-password" placeholder="Password" required />
          </div>
          <button class="btn btn-primary" type="submit" style="width:100%;margin-top:8px">Connect to MT5</button>
        </form>
      </div>`;
  }
}

async function connectMT5(e) {
  e.preventDefault();
  const errEl = document.getElementById('mt5-error');
  errEl.innerHTML = '';
  const server = document.getElementById('mt5-server').value;
  const login = document.getElementById('mt5-login').value;
  const password = document.getElementById('mt5-password').value;
  const btn = e.target.querySelector('button');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Connecting...';
  try {
    const data = await api('/api/mt5/connect', {
      method: 'POST',
      body: JSON.stringify({ server, login: parseInt(login), password }),
    });
    state.mt5Connected = true;
    state.accountInfo = data.account;
    renderMT5Section();
    await loadConfigData();
    renderConfigCols();
    document.getElementById('btn-run').disabled = false;
  } catch (err) {
    errEl.innerHTML = `<div class="error-msg">${err.message}</div>`;
    btn.disabled = false;
    btn.textContent = 'Connect to MT5';
  }
}

async function disconnectMT5() {
  try { await api('/api/mt5/disconnect', { method: 'POST' }); } catch (_) { }
  state.mt5Connected = false;
  state.accountInfo = null;
  state.results = null;
  renderMT5Section();
  renderConfigCols();
  document.getElementById('btn-run').disabled = true;
  document.getElementById('results-section').style.display = 'none';
}

// ─── Load Symbols, Timeframes, Strategies ───────────────────────
async function loadConfigData() {
  try {
    const [symRes, tfRes, stratRes] = await Promise.all([
      api('/api/symbols'), api('/api/timeframes'), api('/api/strategies'),
    ]);
    state.symbols = symRes.symbols || [];
    state.timeframes = tfRes.timeframes || [];
    state.strategies = stratRes.strategies || [];
  } catch (err) { console.error('Failed to load config data:', err); }
}

// ─── Two-Column Config Panel ─────────────────────────────────────
function renderConfigCols() {
  const leftEl = document.getElementById('config-col-left');
  const rightEl = document.getElementById('config-col-right');

  if (!state.mt5Connected) {
    leftEl.innerHTML = `<div class="config-disabled"><div class="disabled-icon">🔌</div><p>Connect to MT5 to configure your backtest</p></div>`;
    rightEl.innerHTML = '';
    return;
  }

  // ── LEFT COLUMN ─────────────────────────────────────────────
  leftEl.innerHTML = `
    <!-- Symbol -->
    <div class="config-section">
      <h3 class="config-section-title">Asset Symbol</h3>
      <div class="form-group">
        <input type="text" id="symbol-search" placeholder="Search symbols (e.g. EURUSD)" oninput="filterSymbols()" />
      </div>
      <div class="symbol-list" id="symbol-list"></div>
    </div>

    <!-- Timeframe -->
    <div class="config-section">
      <h3 class="config-section-title">Timeframe</h3>
      <div class="timeframe-grid" id="tf-grid"></div>
    </div>

    <!-- Date Range -->
    <div class="config-section">
      <h3 class="config-section-title">Test Range</h3>
      <div class="date-row">
        <div class="form-group">
          <label>From</label>
          <input type="datetime-local" id="date-from" value="${state.config.dateFrom}" onchange="state.config.dateFrom=this.value" />
        </div>
        <div class="form-group">
          <label>To</label>
          <input type="datetime-local" id="date-to" value="${state.config.dateTo}" onchange="state.config.dateTo=this.value" />
        </div>
      </div>
    </div>

    <!-- Strategy -->
    <div class="config-section">
      <h3 class="config-section-title">Strategy</h3>
      <div class="form-group">
        <select id="strategy-select" onchange="selectStrategy(this.value)">
          <option value="">Select a strategy...</option>
          ${state.strategies.map(s => `<option value="${s.name}" ${state.config.strategy === s.name ? 'selected' : ''}>${s.name}</option>`).join('')}
        </select>
      </div>
      <div id="strategy-desc"></div>
    </div>
  `;

  filterSymbols();
  renderTimeframes();
  if (state.config.strategy) selectStrategy(state.config.strategy);

  // ── RIGHT COLUMN ─────────────────────────────────────────────
  renderRightColumn();
}

function renderRightColumn() {
  const rightEl = document.getElementById('config-col-right');
  if (!state.strategySettings || Object.keys(state.strategySettings).length === 0) {
    rightEl.innerHTML = `
      <div class="config-placeholder">
        <span class="config-placeholder-icon">⚙️</span>
        <p>Select a strategy to configure its settings</p>
      </div>`;
    return;
  }

  rightEl.innerHTML = `
    <!-- Strategy Settings -->
    <div class="config-section">
      <h3 class="config-section-title">Strategy Settings</h3>
      <div class="settings-grid" id="strategy-settings"></div>
    </div>

    <!-- Backtest Settings -->
    <div class="config-section">
      <h3 class="config-section-title">Backtest Settings</h3>
      <div class="settings-grid">
        <div class="setting-item">
          <label class="setting-label">Initial Balance</label>
          <input type="number" value="${state.config.initialBalance}" min="100" step="100"
            onchange="state.config.initialBalance=parseFloat(this.value)" />
        </div>
        <div class="setting-item">
          <label class="setting-label">Lot Size</label>
          <input type="number" value="${state.config.lotSize}" min="0.01" max="100" step="0.01"
            onchange="state.config.lotSize=parseFloat(this.value)" />
        </div>
      </div>
    </div>
  `;

  buildStrategySettingsGrid();
}

function buildStrategySettingsGrid() {
  const settings = state.strategySettings;
  if (!settings) return;
  const grid = document.getElementById('strategy-settings');
  if (!grid) return;

  grid.innerHTML = Object.entries(settings).map(([key, spec]) => {
    const val = state.config.settings[key] ?? spec.default;
    let inputHTML = '';

    if (spec.type === 'int' || spec.type === 'float') {
      const step = spec.step || (spec.type === 'float' ? 0.1 : 1);
      inputHTML = `
        <input type="number" value="${val}" min="${spec.min ?? ''}" max="${spec.max ?? ''}" step="${step}"
          onchange="updateSetting('${key}', ${spec.type === 'int' ? 'parseInt(this.value)' : 'parseFloat(this.value)'})" />
        ${spec.min !== undefined ? `<span class="setting-range">${spec.min} — ${spec.max}</span>` : ''}`;
    } else if (spec.type === 'select') {
      inputHTML = `
        <select onchange="updateSetting('${key}', this.value)">
          ${(spec.options || []).map(o => `<option value="${o}" ${val === o ? 'selected' : ''}>${o.replace(/_/g, ' ')}</option>`).join('')}
        </select>`;
    } else if (spec.type === 'bool') {
      inputHTML = `
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="checkbox" ${val ? 'checked' : ''}
            onchange="updateSetting('${key}', this.checked)" />
          <span style="font-size:0.8rem;color:var(--text-muted)">${val ? 'Enabled' : 'Disabled'}</span>
        </label>`;
    }

    return `
      <div class="setting-item" data-setting-key="${key}" data-visible-when='${spec.visible_when ? JSON.stringify(spec.visible_when) : ""}'>
        <label class="setting-label">${spec.description || key}</label>
        ${inputHTML}
      </div>`;
  }).join('');

  refreshSettingVisibility();
}

// ─── Conditional Settings Visibility ────────────────────────────
function refreshSettingVisibility() {
  const items = document.querySelectorAll('[data-setting-key]');
  items.forEach(item => {
    const raw = item.getAttribute('data-visible-when');
    if (!raw) return;  // no condition → always visible
    let cond;
    try { cond = JSON.parse(raw); } catch { return; }

    const shouldShow = Object.entries(cond).every(([key, allowedVals]) => {
      const curr = state.config.settings[key];
      return allowedVals.includes(curr);
    });

    item.classList.toggle('setting-item--hidden', !shouldShow);
  });
}

function updateSetting(key, value) {
  state.config.settings[key] = value;
  refreshSettingVisibility();
}

// ─── Symbols / Timeframes ────────────────────────────────────────
function filterSymbols() {
  const q = (document.getElementById('symbol-search')?.value || '').toLowerCase();
  const filtered = state.symbols.filter(s =>
    s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q)
  );
  const list = document.getElementById('symbol-list');
  if (!list) return;
  list.innerHTML = filtered.slice(0, 50).map(s => `
    <button class="symbol-item ${state.config.symbol === s.name ? 'active' : ''}"
      onclick="selectSymbol('${s.name}')">
      <span class="symbol-name">${s.name}</span>
      <span class="symbol-spread">${s.spread} pts</span>
    </button>`).join('');
  if (filtered.length === 0) list.innerHTML = '<div style="padding:14px;text-align:center;color:var(--text-muted)">No symbols found</div>';
}

function selectSymbol(name) {
  state.config.symbol = name;
  document.getElementById('symbol-search').value = name;
  filterSymbols();
}

function renderTimeframes() {
  const grid = document.getElementById('tf-grid');
  if (!grid) return;
  grid.innerHTML = state.timeframes.map(tf => `
    <button class="tf-btn ${state.config.timeframe === tf.value ? 'active' : ''}"
      onclick="selectTimeframe('${tf.value}')">
      ${tf.value}
    </button>`).join('');
}

function selectTimeframe(tf) {
  state.config.timeframe = tf;
  renderTimeframes();
}

// ─── Strategy Selection ──────────────────────────────────────────
async function selectStrategy(name) {
  state.config.strategy = name;
  const strat = state.strategies.find(s => s.name === name);
  const descEl = document.getElementById('strategy-desc');
  if (descEl) {
    descEl.innerHTML = strat?.description
      ? `<p class="strategy-desc">${strat.description}</p>` : '';
  }

  if (!name) {
    state.strategySettings = null;
    renderRightColumn();
    return;
  }

  try {
    const res = await api(`/api/strategies/${encodeURIComponent(name)}/settings`);
    state.strategySettings = res.settings;
    state.config.settings = {};
    Object.entries(res.settings).forEach(([key, spec]) => {
      state.config.settings[key] = spec.default;
    });
    renderRightColumn();
  } catch (err) {
    console.error('Failed to load strategy settings:', err);
  }
}

// ─── Run Backtest ───────────────────────────────────────────────
async function runBacktest() {
  const c = state.config;
  const errEl = document.getElementById('error-box');

  if (!c.symbol || !c.timeframe || !c.dateFrom || !c.dateTo || !c.strategy) {
    errEl.textContent = 'Fill in all fields: symbol, timeframe, date range, and strategy.';
    errEl.style.display = 'block';
    return;
  }
  errEl.style.display = 'none';

  state.backtesting = true;
  const btn = document.getElementById('btn-run');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Running...';
  document.getElementById('loading-overlay').style.display = 'flex';
  document.getElementById('results-section').style.display = 'none';

  if (priceChartInst) { priceChartInst.remove(); priceChartInst = null; }
  if (equityChartInst) { equityChartInst.remove(); equityChartInst = null; }

  try {
    const result = await api('/api/backtest', {
      method: 'POST',
      body: JSON.stringify({
        symbol: c.symbol,
        timeframe: c.timeframe,
        date_from: c.dateFrom,
        date_to: c.dateTo,
        strategy: c.strategy,
        settings: c.settings || {},
        initial_balance: c.initialBalance,
        lot_size: c.lotSize,
      }),
    });
    state.results = result;
    renderResults();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.style.display = 'block';
  } finally {
    state.backtesting = false;
    btn.disabled = false;
    btn.innerHTML = '<span class="run-icon">▶</span> Run Backtest';
    document.getElementById('loading-overlay').style.display = 'none';
  }
}

// ─── Render Results ─────────────────────────────────────────────
function renderResults() {
  const r = state.results;
  if (!r) return;

  const m = r.metrics;
  const sec = document.getElementById('results-section');
  sec.style.display = 'flex';

  document.getElementById('results-header').innerHTML = `
    <div class="results-header">
      <h2 class="results-title">Backtest Results</h2>
      <div class="results-meta">
        <span class="meta-tag">${r.config?.symbol || ''}</span>
        <span class="meta-tag">${r.config?.timeframe || ''}</span>
        <span class="meta-tag">${r.config?.strategy || ''}</span>
        <span class="meta-tag">${r.total_bars} bars</span>
      </div>
    </div>`;

  const isProfit = m.net_pnl_money >= 0;
  document.getElementById('pnl-hero').innerHTML = `
    <div class="pnl-hero ${isProfit ? 'profit' : 'loss'}">
      <div class="pnl-label">Net Profit / Loss</div>
      <div class="pnl-value">${isProfit ? '+' : ''}$${m.net_pnl_money?.toLocaleString()}</div>
      <div class="pnl-sub">${m.net_pnl_pips >= 0 ? '+' : ''}${m.net_pnl_pips} pips · ${m.total_return_pct >= 0 ? '+' : ''}${m.total_return_pct}% return</div>
    </div>`;

  const metrics = [
    { l: 'Total Trades', v: m.total_trades },
    { l: 'Win Rate', v: m.win_rate + '%', p: m.win_rate >= 50 },
    { l: 'Profit Factor', v: m.profit_factor === Infinity ? '∞' : m.profit_factor, p: m.profit_factor > 1 },
    { l: 'Max Drawdown', v: m.max_drawdown_pct + '%', s: '$' + m.max_drawdown_money?.toLocaleString(), n: true },
    { l: 'Sharpe Ratio', v: m.sharpe_ratio, p: m.sharpe_ratio > 0 },
    { l: 'Recovery Factor', v: m.recovery_factor },
    { l: 'Gross Profit', v: '$' + m.gross_profit?.toLocaleString(), p: true },
    { l: 'Gross Loss', v: '$' + m.gross_loss?.toLocaleString(), n: true },
    { l: 'Avg Win', v: m.avg_win_pips + ' pips', s: '$' + m.avg_win_money, p: true },
    { l: 'Avg Loss', v: m.avg_loss_pips + ' pips', s: '$' + m.avg_loss_money, n: true },
    { l: 'Largest Win', v: m.largest_win_pips + ' pips', s: '$' + m.largest_win_money, p: true },
    { l: 'Largest Loss', v: m.largest_loss_pips + ' pips', s: '$' + m.largest_loss_money, n: true },
    { l: 'Winning Trades', v: m.winning_trades, p: true },
    { l: 'Losing Trades', v: m.losing_trades, n: true },
    { l: 'Consec. Wins', v: m.max_consecutive_wins },
    { l: 'Consec. Losses', v: m.max_consecutive_losses },
    { l: 'Avg Bars Held', v: m.avg_bars_held },
    { l: 'Spread Cost', v: m.total_spread_cost_pips + ' pips' },
    { l: 'Final Balance', v: '$' + m.final_balance?.toLocaleString(), p: m.final_balance > (r.config?.initial_balance || 10000) },
  ];

  document.getElementById('metrics-grid').innerHTML = metrics.map(c => `
    <div class="metric-card">
      <div class="metric-label">${c.l}</div>
      <div class="metric-value ${c.p ? 'text-profit' : ''} ${c.n ? 'text-loss' : ''}">${c.v}</div>
      ${c.s ? `<div class="metric-sub">${c.s}</div>` : ''}
    </div>`).join('');

  // Reset to price tab
  document.getElementById('tab-price').classList.add('active');
  document.getElementById('tab-equity').classList.remove('active');
  document.getElementById('price-chart-wrap').style.display = '';
  document.getElementById('equity-chart-wrap').style.display = 'none';

  renderPriceChart();
  renderTradeLog();
  sec.scrollIntoView({ behavior: 'smooth' });
}

// ─── Price Chart ─────────────────────────────────────────────────
function renderPriceChart() {
  const r = state.results;
  if (!r?.bar_data?.length) return;

  const container = document.getElementById('price-chart');
  container.innerHTML = '';
  if (priceChartInst) { priceChartInst.remove(); priceChartInst = null; }

  const colors = getChartColors();
  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: 420,
    layout: { background: { type: 'solid', color: colors.bg }, textColor: colors.text, fontFamily: "'Inter', sans-serif", fontSize: 11 },
    grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
    rightPriceScale: { borderColor: colors.border },
    timeScale: { borderColor: colors.border, timeVisible: true, secondsVisible: false },
    crosshair: {
      vertLine: { color: 'rgba(59,130,246,0.4)', style: 2 },
      horzLine: { color: 'rgba(59,130,246,0.4)', style: 2 },
    },
  });
  priceChartInst = chart;

  // Candlestick
  const candleSeries = chart.addCandlestickSeries({
    upColor: '#22c55e', downColor: '#ef4444',
    borderUpColor: '#22c55e', borderDownColor: '#ef4444',
    wickUpColor: '#22c55e', wickDownColor: '#ef4444',
  });
  candleSeries.setData(r.bar_data.map(b => ({
    time: toTs(b.time), open: b.open, high: b.high, low: b.low, close: b.close,
  })));

  // Trade markers
  const trades = r.trades || [];
  if (trades.length > 0) {
    const markers = [];
    trades.forEach(t => {
      const entryTs = toTs(t.entry_time);
      const exitTs = toTs(t.exit_time);
      const isBuy = t.direction === 'BUY';

      markers.push({
        time: entryTs,
        position: isBuy ? 'belowBar' : 'aboveBar',
        color: isBuy ? '#22c55e' : '#ef4444',
        shape: isBuy ? 'arrowUp' : 'arrowDown',
        text: isBuy ? `B ${t.entry_price}` : `S ${t.entry_price}`,
        size: 1.2,
      });

      const exitColor = t.exit_reason === 'tp' ? '#22c55e' : t.exit_reason === 'sl' ? '#ef4444' : '#f59e0b';
      const exitLabel = t.exit_reason === 'tp' ? 'TP' : t.exit_reason === 'sl' ? 'SL' : 'X';
      markers.push({
        time: exitTs,
        position: isBuy ? 'aboveBar' : 'belowBar',
        color: exitColor,
        shape: 'circle',
        text: `${exitLabel} ${t.exit_price}`,
        size: 0.8,
      });
    });
    markers.sort((a, b) => a.time - b.time);
    candleSeries.setMarkers(markers);
  }

  // EMA / indicator overlays
  const indColors = ['#3b82f6', '#f59e0b', '#8b5cf6', '#06b6d4', '#ec4899'];
  let ci = 0;
  if (r.indicator_data) {
    Object.entries(r.indicator_data).forEach(([name, values]) => {
      let color = indColors[ci % indColors.length];
      if (name.includes('↑') || name.includes('Bull')) color = '#22c55e';
      else if (name.includes('↓') || name.includes('Bear')) color = '#ef4444';

      let chunks = [];
      let currentChunk = [];
      r.bar_data.forEach((b, i) => {
        if (values[i] != null) {
          currentChunk.push({ time: toTs(b.time), value: values[i] });
        } else {
          if (currentChunk.length > 0) {
            chunks.push(currentChunk);
            currentChunk = [];
          }
        }
      });
      if (currentChunk.length > 0) chunks.push(currentChunk);

      chunks.forEach((chunk, idx) => {
        const line = chart.addLineSeries({
          color: color, lineWidth: 1.5,
          title: idx === 0 ? name : '',
          priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        line.setData(chunk);
      });
      ci++;
    });
  }

  chart.timeScale().fitContent();
  window.addEventListener('resize', () => {
    if (priceChartInst) priceChartInst.applyOptions({ width: container.clientWidth });
  });
}

// ─── Equity Chart ───────────────────────────────────────────────
function renderEquityChart() {
  const r = state.results;
  if (!r?.equity_curve?.length) return;

  const container = document.getElementById('equity-chart');
  container.innerHTML = '';
  if (equityChartInst) { equityChartInst.remove(); equityChartInst = null; }

  const colors = getChartColors();
  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: 380,
    layout: { background: { type: 'solid', color: colors.bg }, textColor: colors.text, fontFamily: "'Inter', sans-serif", fontSize: 11 },
    grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
    rightPriceScale: { borderColor: colors.border },
    timeScale: { borderColor: colors.border, timeVisible: true, secondsVisible: false },
    crosshair: {
      vertLine: { color: 'rgba(59,130,246,0.3)', style: 2 },
      horzLine: { color: 'rgba(59,130,246,0.3)', style: 2 },
    },
  });
  equityChartInst = chart;

  const eq = chart.addLineSeries({ color: '#3b82f6', lineWidth: 2, title: 'Equity', priceFormat: { type: 'price', precision: 2, minMove: 0.01 } });
  eq.setData(r.equity_curve.map(p => ({ time: toTs(p.time), value: p.equity })));

  const bal = chart.addLineSeries({ color: '#8b5cf6', lineWidth: 1, lineStyle: 2, title: 'Balance', priceFormat: { type: 'price', precision: 2, minMove: 0.01 } });
  bal.setData(r.equity_curve.map(p => ({ time: toTs(p.time), value: p.balance })));

  chart.timeScale().fitContent();
  window.addEventListener('resize', () => {
    if (equityChartInst) equityChartInst.applyOptions({ width: container.clientWidth });
  });
}

// ─── Trade Log ──────────────────────────────────────────────────
let tradeSort = { field: null, dir: 'asc' };

function renderTradeLog() {
  const trades = state.results?.trades;
  if (!trades?.length) {
    document.getElementById('trade-log').innerHTML = '';
    return;
  }

  let sorted = [...trades];
  if (tradeSort.field) {
    sorted.sort((a, b) => {
      let va = a[tradeSort.field], vb = b[tradeSort.field];
      if (typeof va === 'string') { va = va.toLowerCase(); vb = (vb || '').toLowerCase(); }
      if (va < vb) return tradeSort.dir === 'asc' ? -1 : 1;
      if (va > vb) return tradeSort.dir === 'asc' ? 1 : -1;
      return 0;
    });
  }

  document.getElementById('trade-log').innerHTML = `
    <div class="trade-log-header">
      <h3 class="trade-log-title">Trade Log</h3>
      <span class="trade-count">${trades.length} trades</span>
    </div>
    <div class="table-wrapper">
      <table class="trades-table">
        <thead><tr>
          <th>#</th>
          <th onclick="sortTrades('direction')">Side${sortArrow('direction')}</th>
          <th onclick="sortTrades('entry_time')">Entry Time (UTC)${sortArrow('entry_time')}</th>
          <th onclick="sortTrades('exit_time')">Exit Time (UTC)${sortArrow('exit_time')}</th>
          <th onclick="sortTrades('entry_price')">Entry${sortArrow('entry_price')}</th>
          <th onclick="sortTrades('exit_price')">Exit${sortArrow('exit_price')}</th>
          <th onclick="sortTrades('exit_reason')">Reason${sortArrow('exit_reason')}</th>
          <th onclick="sortTrades('lot_size')">Lots${sortArrow('lot_size')}</th>
          <th onclick="sortTrades('pnl_pips')">P&L (pips)${sortArrow('pnl_pips')}</th>
          <th onclick="sortTrades('pnl_money')">P&L ($)${sortArrow('pnl_money')}</th>
          <th onclick="sortTrades('bars_held')">Bars${sortArrow('bars_held')}</th>
          <th onclick="sortTrades('spread_cost_pips')">Spread${sortArrow('spread_cost_pips')}</th>
        </tr></thead>
        <tbody>
          ${sorted.map((t, i) => `
            <tr class="${t.pnl_pips >= 0 ? 'row-win' : 'row-loss'}">
              <td style="color:var(--text-muted)">${i + 1}</td>
              <td><span class="side-badge ${t.direction === 'BUY' ? 'buy' : 'sell'}">${t.direction}</span></td>
              <td style="font-family:var(--font-mono)">${fmtTimeUTC(t.entry_time)}</td>
              <td style="font-family:var(--font-mono)">${fmtTimeUTC(t.exit_time)}</td>
              <td style="font-family:var(--font-mono)">${t.entry_price}</td>
              <td style="font-family:var(--font-mono)">${t.exit_price}</td>
              <td><span class="reason-badge ${t.exit_reason || 'signal'}">${(t.exit_reason || 'signal').toUpperCase()}</span></td>
              <td style="font-family:var(--font-mono)">${t.lot_size}</td>
              <td style="font-family:var(--font-mono)" class="${t.pnl_pips >= 0 ? 'text-profit' : 'text-loss'}">${t.pnl_pips >= 0 ? '+' : ''}${t.pnl_pips}</td>
              <td style="font-family:var(--font-mono)" class="${t.pnl_money >= 0 ? 'text-profit' : 'text-loss'}">${t.pnl_money >= 0 ? '+' : ''}$${t.pnl_money}</td>
              <td style="font-family:var(--font-mono);color:var(--text-muted)">${t.bars_held}</td>
              <td style="font-family:var(--font-mono);color:var(--text-muted)">${t.spread_cost_pips}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

function sortTrades(field) {
  if (tradeSort.field === field) {
    tradeSort.dir = tradeSort.dir === 'asc' ? 'desc' : 'asc';
  } else {
    tradeSort.field = field;
    tradeSort.dir = 'asc';
  }
  renderTradeLog();
}

function sortArrow(field) {
  if (tradeSort.field !== field) return '';
  return tradeSort.dir === 'asc' ? ' ↑' : ' ↓';
}

// ─── Measurement Tool ─────────────────────────────────────────────────────
const measure = {
  active: false,      // tool is toggled on?
  drawing: false,     // mouse is held down?
  startX: 0, startY: 0,
  endX: 0, endY: 0,
};

function toggleMeasureTool() {
  measure.active = !measure.active;
  const btn = document.getElementById('btn-measure');
  const overlay = document.getElementById('measure-overlay');

  if (measure.active) {
    btn.classList.add('active');
    // Size the overlay exactly like the chart canvas
    const chartDiv = document.getElementById('price-chart');
    overlay.style.display = 'block';
    overlay.style.top = chartDiv.offsetTop + 'px';
    overlay.style.left = chartDiv.offsetLeft + 'px';
    overlay.style.width = chartDiv.offsetWidth + 'px';
    overlay.style.height = chartDiv.offsetHeight + 'px';
    const canvas = document.getElementById('measure-canvas');
    canvas.width = chartDiv.offsetWidth;
    canvas.height = chartDiv.offsetHeight;
    clearMeasureCanvas();
    hideMeasureTooltip();
  } else {
    btn.classList.remove('active');
    overlay.style.display = 'none';
    clearMeasureCanvas();
    hideMeasureTooltip();
    measure.drawing = false;
  }
}

function clearMeasureCanvas() {
  const canvas = document.getElementById('measure-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function hideMeasureTooltip() {
  const tip = document.getElementById('measure-tooltip');
  if (tip) tip.style.display = 'none';
}

function initMeasureTool() {
  const overlay = document.getElementById('measure-overlay');
  if (!overlay) return;

  // Reattach fresh listeners each time chart is rendered
  const fresh = overlay.cloneNode(false);
  // keep child elements
  while (overlay.firstChild) fresh.appendChild(overlay.firstChild);
  overlay.parentNode.replaceChild(fresh, overlay);
  const ov = document.getElementById('measure-overlay');

  ov.addEventListener('mousedown', (e) => {
    if (!measure.active) return;
    measure.drawing = true;
    const r = ov.getBoundingClientRect();
    measure.startX = e.clientX - r.left;
    measure.startY = e.clientY - r.top;
    measure.endX = measure.startX;
    measure.endY = measure.startY;
    clearMeasureCanvas();
    hideMeasureTooltip();
  });

  ov.addEventListener('mousemove', (e) => {
    if (!measure.active || !measure.drawing) return;
    const r = ov.getBoundingClientRect();
    measure.endX = e.clientX - r.left;
    measure.endY = e.clientY - r.top;
    drawMeasureRect();
  });

  ov.addEventListener('mouseup', (e) => {
    if (!measure.active || !measure.drawing) return;
    measure.drawing = false;
    const r = ov.getBoundingClientRect();
    measure.endX = e.clientX - r.left;
    measure.endY = e.clientY - r.top;
    drawMeasureRect();
    showMeasureTooltip();
  });

  // Cancel on Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && measure.active) {
      toggleMeasureTool();
    }
  });
}

function drawMeasureRect() {
  const canvas = document.getElementById('measure-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const x1 = measure.startX, y1 = measure.startY;
  const x2 = measure.endX, y2 = measure.endY;
  const rx = Math.min(x1, x2), ry = Math.min(y1, y2);
  const rw = Math.abs(x2 - x1), rh = Math.abs(y2 - y1);

  // Fill rectangle
  ctx.fillStyle = 'rgba(59,130,246,0.12)';
  ctx.fillRect(rx, ry, rw, rh);

  // Border
  ctx.strokeStyle = 'rgba(59,130,246,0.85)';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(rx, ry, rw, rh);

  // Vertical arrow on left edge (price axis)
  const midX = rx + rw / 2;
  drawArrow(ctx, midX, y1, midX, y2, 'rgba(59,130,246,0.9)');

  // Horizontal arrow on bottom edge (time axis)
  const midY = ry + rh / 2;
  drawArrow(ctx, x1, midY, x2, midY, 'rgba(59,130,246,0.9)');
}

function drawArrow(ctx, x1, y1, x2, y2, color) {
  if (Math.abs(x2 - x1) < 4 && Math.abs(y2 - y1) < 4) return;
  const headLen = 8;
  const angle = Math.atan2(y2 - y1, x2 - x1);
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 1.5;

  // Line
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();

  // Arrowhead at end
  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - headLen * Math.cos(angle - Math.PI / 7), y2 - headLen * Math.sin(angle - Math.PI / 7));
  ctx.lineTo(x2 - headLen * Math.cos(angle + Math.PI / 7), y2 - headLen * Math.sin(angle + Math.PI / 7));
  ctx.closePath();
  ctx.fill();

  // Arrowhead at start (double-headed)
  const a2 = angle + Math.PI;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x1 - headLen * Math.cos(a2 - Math.PI / 7), y1 - headLen * Math.sin(a2 - Math.PI / 7));
  ctx.lineTo(x1 - headLen * Math.cos(a2 + Math.PI / 7), y1 - headLen * Math.sin(a2 + Math.PI / 7));
  ctx.closePath();
  ctx.fill();
}

function showMeasureTooltip() {
  if (!priceChartInst || !state.results?.bar_data?.length) return;

  const chart = priceChartInst;
  const barData = state.results.bar_data;

  // ── Convert pixel Y → price ───────────────────────────────────────────
  // Use the chart's right price scale (convert pixel to price)
  const priceScale = chart.priceScale('right');
  const startPrice = priceScale.coordinateToPrice(measure.startY);
  const endPrice = priceScale.coordinateToPrice(measure.endY);

  // ── Convert pixel X → bar index (logical) ────────────────────────────
  const timeScale = chart.timeScale();
  const startLogical = timeScale.coordinateToLogical(measure.startX);
  const endLogical = timeScale.coordinateToLogical(measure.endX);

  if (startPrice == null || endPrice == null ||
    startLogical == null || endLogical == null) return;

  const priceDiff = endPrice - startPrice;
  const pricePct = startPrice !== 0 ? (priceDiff / Math.abs(startPrice)) * 100 : 0;
  const barsCount = Math.abs(Math.round(endLogical - startLogical));

  // ── Time duration (from bar data) ────────────────────────────────────
  const iStart = Math.max(0, Math.min(Math.round(Math.min(startLogical, endLogical)), barData.length - 1));
  const iEnd = Math.max(0, Math.min(Math.round(Math.max(startLogical, endLogical)), barData.length - 1));
  let timeDurStr = '';
  if (iStart < barData.length && iEnd < barData.length) {
    const t1 = new Date(barData[iStart].time + (barData[iStart].time.includes('+') ? '' : 'Z'));
    const t2 = new Date(barData[iEnd].time + (barData[iEnd].time.includes('+') ? '' : 'Z'));
    const diffMs = Math.abs(t2 - t1);
    const diffMin = Math.round(diffMs / 60000);
    if (diffMin < 60) timeDurStr = `${diffMin}m`;
    else if (diffMin < 1440) timeDurStr = `${Math.round(diffMin / 60)}h`;
    else timeDurStr = `${Math.round(diffMin / 1440)}d`;
  }

  // ── Format numbers ───────────────────────────────────────────────────
  const digits = state.results?.config?.digits ?? 5;
  const fmtPrice = (v) => v.toFixed(digits);
  const sign = priceDiff >= 0 ? '+' : '';

  // ── Position tooltip near the drag rectangle ────────────────────────
  const tip = document.getElementById('measure-tooltip');
  const rx = Math.min(measure.startX, measure.endX);
  const ry = Math.min(measure.startY, measure.endY);
  const rw = Math.abs(measure.endX - measure.startX);

  tip.innerHTML = `
    <div class="mt-row mt-price">${sign}${fmtPrice(priceDiff)} <span class="mt-pct">(${sign}${pricePct.toFixed(2)}%)</span></div>
    <div class="mt-row mt-bars">${barsCount} bars${timeDurStr ? `,&nbsp;${timeDurStr}` : ''}</div>`;

  tip.style.display = 'block';
  // Place tooltip just above/below the rect, centred horizontally
  const tipW = 220;
  const rawLeft = rx + rw / 2 - tipW / 2;
  const canvas = document.getElementById('measure-canvas');
  const clampedLeft = Math.max(4, Math.min(rawLeft, canvas.width - tipW - 4));
  const topPos = ry > 60 ? ry - 68 : ry + Math.abs(measure.endY - measure.startY) + 10;
  tip.style.left = clampedLeft + 'px';
  tip.style.top = topPos + 'px';
  tip.style.width = tipW + 'px';
}

// Wire up measurement tool whenever the price chart is re-rendered
const _origRenderPriceChart = renderPriceChart;
renderPriceChart = function () {
  _origRenderPriceChart();
  // Deactivate measure tool on chart re-render (chart is brand new)
  if (measure.active) toggleMeasureTool();
  initMeasureTool();
};

