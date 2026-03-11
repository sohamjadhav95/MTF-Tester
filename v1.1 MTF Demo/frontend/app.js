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
  marketType: 'forex',   // 'forex' | 'crypto'
  config: {
    symbol: '', timeframes: ['M5', 'M15', 'H1'],
    strategy: '', settings: {},
    initialBalance: 10000, lotSize: 0.1,
  },
  scannerActive: false,
};

let wsConnection = null;
let mtfCharts = {}; // { [timeframe]: { wrapEl, chartInst, candleSeries } }

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
async function setMarketType(type) {
  state.marketType = type;
  const isCrypto = type === 'crypto';

  // Toggle button active state
  document.getElementById('btn-forex').classList.toggle('active', !isCrypto);
  document.getElementById('btn-crypto').classList.toggle('active', isCrypto);

  // Switch CSS theme via data-market attribute (triggers CSS variable transition)
  document.documentElement.setAttribute('data-market', isCrypto ? 'crypto' : 'forex');

  // Reset symbol & timeframes
  state.config.symbol = '';
  state.config.timeframes = isCrypto ? ['H1'] : ['M5', 'H1'];

  // Update sidebar immediately (before async loads)
  renderMT5Section();

  if (isCrypto) {
    // Load Binance Futures symbols and timeframes
    document.getElementById('config-col-left').innerHTML = '<div class="config-disabled"><div class="disabled-icon">⏳</div><p>Loading Binance Futures symbols...</p></div>';
    try {
      const [symRes, tfRes, stratRes] = await Promise.all([
        api('/api/crypto/symbols'),
        api('/api/crypto/timeframes'),
        api('/api/strategies'),
      ]);
      state.symbols = symRes.symbols || [];
      state.timeframes = tfRes.timeframes || [];
      state.strategies = stratRes.strategies || [];
      // Crypto also uses smaller default lot size
      state.config.lotSize = 0.01;
      // Enable run button for crypto (no login needed)
      document.getElementById('btn-run').disabled = false;
    } catch (err) {
      console.error('Failed to load crypto data:', err);
    }
    renderConfigCols();
  } else {
    // Restore MT5 symbols/timeframes if connected
    if (state.mt5Connected) {
      await loadConfigData();
    } else {
      state.symbols = [];
      state.timeframes = [];
    }
    renderConfigCols();
    if (!state.mt5Connected) document.getElementById('btn-run').disabled = true;
  }
}

// ─── MT5 / Connection Section ────────────────────────────────────
function renderMT5Section() {
  const el = document.getElementById('mt5-section');

  // ── Crypto mode: no MT5 login needed ──────────────────────────
  if (state.marketType === 'crypto') {
    el.innerHTML = `
      <div class="sidebar-content-scroll">
        <div class="connection-status">
          <span class="status-dot connected"></span>
          <span class="status-text">Binance Futures</span>
        </div>
        <div class="account-details">
          <div class="detail-row"><span class="detail-label">Source</span><span class="detail-value">Binance FAPI</span></div>
          <div class="detail-row"><span class="detail-label">Market</span><span class="detail-value">USDT Perpetuals</span></div>
          <div class="detail-row"><span class="detail-label">Auth</span><span class="detail-value text-profit">Public API ✓</span></div>
        </div>
        <button class="btn-disconnect" onclick="setMarketType('forex')" style="margin-top:12px">
          ← Switch to Forex
        </button>
      </div>`;
    return;
  }

  // ── Forex mode: MT5 login or connected view ────────────────────
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
  const isCrypto = state.marketType === 'crypto';

  if (!state.mt5Connected && !isCrypto) {
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
      <h3 class="config-section-title">Timeframes (Multi-Select)</h3>
      <div class="timeframe-grid" id="tf-grid"></div>
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
  const schema = state.strategySettings;
  if (!schema || !schema.properties) return;
  const grid = document.getElementById('strategy-settings');
  if (!grid) return;

  const props = schema.properties;
  grid.innerHTML = Object.entries(props).map(([key, prop]) => {
    const val = state.config.settings[key] ?? prop.default;
    let inputHTML = '';
    const desc = prop.description || key;
    // Read x-visible-when from JSON Schema extra
    const visibleWhen = prop['x-visible-when'] || null;

    if (prop.enum) {
      // Enum → dropdown select
      inputHTML = `
        <select onchange="updateSetting('${key}', this.value)">
          ${prop.enum.map(o => `<option value="${o}" ${val === o ? 'selected' : ''}>${String(o).replace(/_/g, ' ')}</option>`).join('')}
        </select>`;
    } else if (prop.type === 'integer' || prop.type === 'number') {
      const step = prop.step || (prop.type === 'number' ? 0.1 : 1);
      const min = prop.minimum ?? prop.exclusiveMinimum ?? '';
      const max = prop.maximum ?? prop.exclusiveMaximum ?? '';
      const parser = prop.type === 'integer' ? 'parseInt(this.value)' : 'parseFloat(this.value)';
      inputHTML = `
        <input type="number" value="${val}" min="${min}" max="${max}" step="${step}"
          onchange="updateSetting('${key}', ${parser})" />
        ${min !== '' && max !== '' ? `<span class="setting-range">${min} — ${max}</span>` : ''}`;
    } else if (prop.type === 'boolean') {
      inputHTML = `
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="checkbox" ${val ? 'checked' : ''}
            onchange="updateSetting('${key}', this.checked)" />
          <span style="font-size:0.8rem;color:var(--text-muted)">${val ? 'Enabled' : 'Disabled'}</span>
        </label>`;
    } else if (prop.type === 'string') {
      inputHTML = `
        <input type="text" value="${val || ''}" onchange="updateSetting('${key}', this.value)" />`;
    }

    return `
      <div class="setting-item" data-setting-key="${key}" data-visible-when='${visibleWhen ? JSON.stringify(visibleWhen) : ""}'>
        <label class="setting-label">${desc}</label>
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
    <button class="tf-btn ${state.config.timeframes.includes(tf.value) ? 'active' : ''}"
      onclick="selectTimeframe('${tf.value}')">
      ${tf.value}
    </button>`).join('');
}

function selectTimeframe(tf) {
  if (state.config.timeframes.includes(tf)) {
    state.config.timeframes = state.config.timeframes.filter(t => t !== tf);
  } else {
    state.config.timeframes.push(tf);
  }
  renderTimeframes();
}

// ─── Strategy Selection ──────────────────────────────────────────
function selectStrategy(name) {
  state.config.strategy = name;
  const strat = state.strategies.find(s => s.name === name);
  const descEl = document.getElementById('strategy-desc');
  if (descEl) {
    descEl.innerHTML = strat?.description
      ? `<p class="strategy-desc">${strat.description}</p>` : '';
  }

  if (!name || !strat) {
    state.strategySettings = null;
    renderRightColumn();
    return;
  }

  // Schema comes inline from GET /api/strategies — no separate fetch needed
  const schema = strat.schema || {};
  state.strategySettings = schema;
  state.config.settings = {};
  if (schema.properties) {
    Object.entries(schema.properties).forEach(([key, prop]) => {
      state.config.settings[key] = prop.default;
    });
  }
  renderRightColumn();
}


// ─── MTF Scanner Logic ──────────────────────────────────────────

async function toggleScanner() {
  const c = state.config;
  const errEl = document.getElementById('error-box');

  if (!state.scannerActive) {
    if (!c.symbol || c.timeframes.length === 0 || !c.strategy) {
      errEl.textContent = 'Fill in all fields: symbol, timeframes, and strategy.';
      errEl.style.display = 'block';
      return;
    }
    errEl.style.display = 'none';
    
    document.getElementById('loading-overlay').style.display = 'flex';
    document.getElementById('loading-title').textContent = 'Connecting...';
    document.getElementById('loading-sub').textContent = 'Initializing MT5 Live Feed...';
    
    // Start backend Engine
    try {
      const resp = await api('/api/mtf/start', {
        method: 'POST',
        body: JSON.stringify({
          symbol: c.symbol,
          timeframes: c.timeframes,
          strategy: c.strategy,
          settings: c.settings || {},
          market_type: state.marketType
        }),
      });
      
      state.scannerActive = true;
      const btn = document.getElementById('btn-run');
      btn.innerHTML = '<span class="run-icon">⏹</span> Stop MTF Scanner';
      btn.classList.add('active');
      btn.style.background = 'var(--loss-red)';
      btn.style.boxShadow = 'none';
      
      initScannerUI(resp.historical_candles, resp.historical_signals, resp.historical_indicators);
      connectWebSocket();
      
      document.getElementById('loading-overlay').style.display = 'none';
    } catch (err) {
      document.getElementById('loading-overlay').style.display = 'none';
      errEl.textContent = err.message;
      errEl.style.display = 'block';
    }
  } else {
    // Stop
    try { await api('/api/mtf/stop', { method: 'POST' }); } catch(err){}
    state.scannerActive = false;
    const btn = document.getElementById('btn-run');
    btn.innerHTML = '<span class="run-icon">▶</span> Run MTF Scanner';
    btn.classList.remove('active');
    btn.style.background = '';
    
    if (wsConnection) {
      wsConnection.close();
      wsConnection = null;
    }
    
    const pulse = document.querySelector('.live-pulse');
    if (pulse) pulse.style.display = 'none';
  }
}

function _toTs(isoStr) { return Math.floor(new Date(isoStr).getTime() / 1000); }

function initScannerUI(histCandles, histSignals, histIndicators) {
  document.getElementById('scanner-section').style.display = 'flex';
  document.getElementById('scanner-meta').innerHTML = `
    <span class="meta-tag">${state.config.symbol}</span>
    <span class="meta-tag">${state.config.strategy}</span>
  `;
  const pulse = document.querySelector('.live-pulse');
  if (pulse) pulse.style.display = 'inline-block';
  
  const container = document.getElementById('mtf-charts-container');
  container.innerHTML = '';
  document.getElementById('report-card').innerHTML = '<div class="report-empty">Waiting for live signals...</div>';
  
  // Clean old charts if any
  for(let tf in mtfCharts) {
      if(mtfCharts[tf].chartInst) mtfCharts[tf].chartInst.remove();
  }
  mtfCharts = {};
  
  const colors = getChartColors();
  
  // Create charts in order of timeframes initially
  state.config.timeframes.forEach(tf => {
    // Create DOM
    const wrap = document.createElement('div');
    wrap.className = 'mtf-chart-wrap';
    wrap.id = `chart-wrap-${tf}`;
    wrap.innerHTML = `
      <div class="mtf-chart-header">
         <span class="mtf-chart-title">${state.config.symbol} <span class="mtf-chart-tf">${tf}</span></span>
         <button class="expand-btn" onclick="openExpandedChart('${tf}')" title="Expand Chart">&#x26F6;</button>
      </div>
      <div class="mtf-chart-canvas" id="canvas-${tf}"></div>
    `;
    container.appendChild(wrap);
    
    // Create Chart
    const cdt = document.getElementById(`canvas-${tf}`);
    const chart = LightweightCharts.createChart(cdt, {
      width: cdt.clientWidth,
      height: 250,
      layout: { background: { type: 'solid', color: colors.bg }, textColor: colors.text, fontFamily: "'Inter', sans-serif", fontSize: 11 },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      rightPriceScale: { borderColor: colors.border },
      timeScale: { borderColor: colors.border, timeVisible: true, secondsVisible: false },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    });
    
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#22c55e', downColor: '#ef4444',
      borderUpColor: '#22c55e', borderDownColor: '#ef4444',
      wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    });
    
    // Add multiple line series for indicators
    const indicatorSeriesMap = {};
    if (histIndicators && histIndicators[tf]) {
      const lineColors = ['#3b82f6', '#f59e0b', '#8b5cf6', '#06b6d4'];
      let colorIdx = 0;
      
      for (const [indName, dataPoints] of Object.entries(histIndicators[tf])) {
         const line = chart.addLineSeries({
             color: lineColors[colorIdx % lineColors.length],
             lineWidth: 1,
             title: indName
         });
         
         const sortedPts = [...dataPoints]
             .map(p => ({ time: _toTs(p.time), value: p.value }))
             .sort((a,b) => a.time - b.time);
             
         line.setData(sortedPts);
         indicatorSeriesMap[indName] = line;
         colorIdx++;
      }
    }
    
    mtfCharts[tf] = { 
      wrapEl: wrap, 
      chartInst: chart, 
      candleSeries: candleSeries,
      indicatorSeriesMap: indicatorSeriesMap
    };
    
    // Set historical candles
    if (histCandles && histCandles[tf]) {
        const uniqueData = [];
        const seen = new Set();
        const sorted = histCandles[tf].map(c => ({
            time: _toTs(c.time),
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close
        })).sort((a,b) => a.time - b.time);
        
        for (const bar of sorted) {
            if (!seen.has(bar.time)) {
                seen.add(bar.time);
                uniqueData.push(bar);
            }
        }
        try {
            candleSeries.setData(uniqueData);
        } catch(e) { console.error("Error setting candle data", e); }
    }
  });
  
  // Render historical signals & markers
  if (histSignals && histSignals.length > 0) {
      const reversed = [...histSignals].reverse();
      
      // Group markers by timeframe
      const markersByTf = {};
      
      reversed.forEach(sig => {
          renderSignalItem(sig);
          
          if (!markersByTf[sig.timeframe]) markersByTf[sig.timeframe] = [];
          
          markersByTf[sig.timeframe].push({
              time: _toTs(sig.bar_time),
              position: sig.direction === 'BUY' ? 'belowBar' : 'aboveBar',
              color: sig.direction === 'BUY' ? '#22c55e' : '#ef4444',
              shape: sig.direction === 'BUY' ? 'arrowUp' : 'arrowDown',
              text: sig.direction
          });
      });
      
      // Apply markers to charts
      for (const tf in markersByTf) {
          if (mtfCharts[tf]) {
              const markers = markersByTf[tf].sort((a,b) => a.time - b.time);
              mtfCharts[tf].candleSeries.setMarkers(markers);
              mtfCharts[tf].markers = markers; // Store for future updates
          }
      }
      
      // Sort charts by the most recent signal (they are already newest-first in histSignals)
      const tfs_in_order = [...new Set(histSignals.map(s => s.timeframe))].reverse();
      const container = document.getElementById('mtf-charts-container');
      
      tfs_in_order.forEach(tf => {
          if (mtfCharts[tf]) {
             const wrap = mtfCharts[tf].wrapEl;
             if (wrap.parentNode === container) {
                 container.removeChild(wrap);
                 container.prepend(wrap);
             }
          }
      });
  }
  
  // Handle resize
  window.addEventListener('resize', () => {
     for(let tf in mtfCharts) {
         const cdt = document.getElementById(`canvas-${tf}`);
         if (cdt) {
             mtfCharts[tf].chartInst.applyOptions({ width: cdt.clientWidth });
         }
     }
  });
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/mtf/stream`;
    wsConnection = new WebSocket(wsUrl);
    
    wsConnection.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === 'bar_updates') {
            msg.data.forEach(update => {
                const tf = update.timeframe;
                if (mtfCharts[tf]) {
                    mtfCharts[tf].candleSeries.update({
                        time: _toTs(update.bar.time),
                        open: update.bar.open,
                        high: update.bar.high,
                        low: update.bar.low,
                        close: update.bar.close
                    });
                    
                    if (state.expandedTf === tf && state.expandedChart && state.expandedCandles) {
                        state.expandedCandles.update({
                            time: _toTs(update.bar.time),
                            open: update.bar.open,
                            high: update.bar.high,
                            low: update.bar.low,
                            close: update.bar.close
                        });
                    }
                }
            });
        }
        else if (msg.type === 'signal') {
            handleNewSignal(msg.data);
        }
    };
    
    wsConnection.onclose = () => {
        console.log("WS closed");
        if(state.scannerActive) {
            setTimeout(connectWebSocket, 2000); // reconnect
        }
    };
    
    wsConnection.onerror = (err) => {
        console.error("WS Error", err);
    };
}

function handleNewSignal(sig) {
    const tf = sig.timeframe;
    const isBuy = sig.direction === 'BUY';
    
    // 1. Move chart to top and glow
    if (mtfCharts[tf]) {
        const container = document.getElementById('mtf-charts-container');
        const wrap = mtfCharts[tf].wrapEl;
        if (wrap.parentNode === container) {
            // Remove then insert before first child
            container.removeChild(wrap);
            container.prepend(wrap);
            
            // Trigger animation reflow
            wrap.classList.remove('chart-glow-buy', 'chart-glow-sell');
            void wrap.offsetWidth; 
            wrap.classList.add(isBuy ? 'chart-glow-buy' : 'chart-glow-sell');
        }
        
        // Add Marker
        const marker = {
            time: _toTs(sig.bar_time),
            position: isBuy ? 'belowBar' : 'aboveBar',
            color: isBuy ? '#22c55e' : '#ef4444',
            shape: isBuy ? 'arrowUp' : 'arrowDown',
            text: sig.direction
        };
        
        if (!mtfCharts[tf].markers) mtfCharts[tf].markers = [];
        mtfCharts[tf].markers.push(marker);
        mtfCharts[tf].markers.sort((a, b) => a.time - b.time);
        mtfCharts[tf].candleSeries.setMarkers(mtfCharts[tf].markers);
        
        // Update Expanded Chart if active
        if (state.expandedTf === tf && state.expandedCandles) {
            state.expandedCandles.setMarkers(mtfCharts[tf].markers);
        }
    }
    
    renderSignalItem(sig);
}

function renderSignalItem(sig) {
    const tf = sig.timeframe;
    const isBuy = sig.direction === 'BUY';
    const rc = document.getElementById('report-card');
    const empty = rc.querySelector('.report-empty');
    if (empty) empty.remove();
    
    const item = document.createElement('div');
    item.className = `report-item ${isBuy ? 'buy' : 'sell'}`;
    
    const d = new Date(sig.time);
    const timeFmt = d.toLocaleTimeString([], { hour12: false });
    
    item.innerHTML = `
        <div class="report-item-header">
            <span>${sig.symbol} <span class="mtf-chart-tf">${tf}</span></span>
            <span class="${isBuy ? 'text-profit' : 'text-loss'}">${sig.direction}</span>
        </div>
        <div class="report-item-time">
            ${timeFmt} • @ ${sig.price}
        </div>
    `;
    rc.prepend(item);
}


// ─── Expanded Chart Modal ───────────────────────────────────────
function openExpandedChart(tf) {
    const modal = document.getElementById('chart-modal');
    const container = document.getElementById('modal-chart-container');
    const title = document.getElementById('modal-title');
    
    // Set Title
    title.innerHTML = `${state.config.symbol} <span class="mtf-chart-tf">${tf}</span>`;
    
    // Clear previous
    container.innerHTML = '';
    
    const colors = getChartColors();
    
    // Create new chart instance
    const chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: container.clientHeight,
        layout: { background: { type: 'solid', color: colors.bg }, textColor: colors.text, fontFamily: "'Inter', sans-serif", fontSize: 12 },
        grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
        rightPriceScale: { borderColor: colors.border },
        timeScale: { borderColor: colors.border, timeVisible: true, secondsVisible: false },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    });
    
    const candleSeries = chart.addCandlestickSeries({
        upColor: '#22c55e', downColor: '#ef4444',
        borderUpColor: '#22c55e', borderDownColor: '#ef4444',
        wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    });
    
    // Clone data from original chart
    const originalChartInfo = mtfCharts[tf];
    if (originalChartInfo) {
        const data = originalChartInfo.candleSeries.data();
        candleSeries.setData(data);
        
        // Clone markers
        if (originalChartInfo.markers) {
            candleSeries.setMarkers(originalChartInfo.markers);
        }
        
        // Clone indicators
        if (originalChartInfo.indicatorSeriesMap) {
            for (const [indName, indSeries] of Object.entries(originalChartInfo.indicatorSeriesMap)) {
                const line = chart.addLineSeries({
                    color: indSeries.options().color,
                    lineWidth: indSeries.options().lineWidth,
                    title: indName
                });
                line.setData(indSeries.data());
            }
        }
    }
    
    // Store in state so we can route updates
    state.expandedChart = chart;
    state.expandedCandles = candleSeries;
    state.expandedTf = tf;
    
    modal.classList.add('show');
    
    // Force a resize after rendering
    setTimeout(() => {
        chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
    }, 50);
}

function closeExpandedChart() {
    const modal = document.getElementById('chart-modal');
    modal.classList.remove('show');
    
    if (state.expandedChart) {
        state.expandedChart.remove();
        state.expandedChart = null;
        state.expandedCandles = null;
        state.expandedTf = null;
    }
}

// Bind modal close button
document.addEventListener('DOMContentLoaded', () => {
    const closeBtn = document.getElementById('close-modal-btn');
    if (closeBtn) closeBtn.addEventListener('click', closeExpandedChart);
});
