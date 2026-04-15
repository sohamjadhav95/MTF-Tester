// ─── MTF Scanner — Multi-Asset Scanner Module ──────────────────

function startFirstAsset() {
  const c = state.config;
  const errEl = document.getElementById('error-box');
  if (!c.symbol || c.timeframes.length === 0 || !c.strategy) {
    errEl.textContent = 'Fill in all fields: symbol, timeframes, and strategy.';
    errEl.style.display = 'block';
    return;
  }
  errEl.style.display = 'none';
  saveSession();
  launchAssetPanel(c.symbol, [...c.timeframes], c.strategy, { ...c.settings });
}

async function launchAssetPanel(symbol, timeframes, strategy, settings) {
  const assetId = generateAssetId();
  const loadingEl = document.getElementById('loading-overlay');
  loadingEl.style.display = 'flex';
  document.getElementById('loading-title').textContent = 'Starting ' + symbol + '...';
  document.getElementById('loading-sub').textContent = 'Initializing live data feed...';

  try {
    const payload = {
      asset_id: assetId, symbol, timeframes, strategy, settings: settings || {},
      market_type: state.marketType,
    };
    if (state.config.startTime) payload.start_time = new Date(state.config.startTime).toISOString();

    const resp = await api('/api/mtf/start', { method: 'POST', body: JSON.stringify(payload) });

    state.assets[assetId] = { symbol, timeframes, strategy, settings, charts: {}, minimized: false, markers: {} };

    // Show asset panels section, hide config
    document.getElementById('asset-panels-section').style.display = '';
    const cols = document.getElementById('config-cols');
    const toggle = document.getElementById('config-toggle-btn');
    if (cols && !cols.classList.contains('collapsed')) { cols.classList.add('collapsed'); if (toggle) toggle.textContent = '+'; }

    // Show report panel
    const mt5Sec = document.getElementById('mt5-section');
    if (mt5Sec) mt5Sec.style.display = 'none';
    const reportSec = document.getElementById('sidebar-report-section');
    if (reportSec) reportSec.style.display = 'flex';

    createAssetPanelDOM(assetId, resp.historical_candles, resp.historical_signals, resp.historical_indicators);
    if (!wsConnection || wsConnection.readyState !== WebSocket.OPEN) connectWebSocket();
    if (state.marketType !== 'crypto' && Object.keys(state.assets).length === 1) initTradingPanel();

    loadingEl.style.display = 'none';
  } catch (err) {
    loadingEl.style.display = 'none';
    document.getElementById('error-box').textContent = err.message;
    document.getElementById('error-box').style.display = 'block';
  }
}

function createAssetPanelDOM(assetId, histCandles, histSignals, histIndicators) {
  const asset = state.assets[assetId];
  const container = document.getElementById('asset-panels-container');
  const panel = document.createElement('div');
  panel.className = 'asset-panel';
  panel.id = `panel-${assetId}`;
  panel.innerHTML = `
    <div class="asset-panel-header">
      <div class="asset-panel-info">
        <span class="asset-panel-symbol">${asset.symbol}</span>
        <span class="asset-panel-strategy">${asset.strategy}</span>
        ${asset.timeframes.map(tf => `<span class="asset-panel-tf">${tf}</span>`).join('')}
      </div>
      <div class="asset-panel-controls">
        <button class="asset-ctrl-btn" onclick="toggleAssetPanel('${assetId}')" title="Minimize/Maximize" id="toggle-${assetId}">_</button>
        <button class="asset-ctrl-btn asset-ctrl-close" onclick="removeAssetPanel('${assetId}')" title="Stop & Remove">✕</button>
      </div>
    </div>
    <div class="asset-panel-body" id="body-${assetId}">
      <div class="mtf-charts-container" id="charts-${assetId}"></div>
    </div>`;
  container.appendChild(panel);

  const colors = getChartColors();
  const chartsContainer = document.getElementById(`charts-${assetId}`);

  asset.timeframes.forEach(tf => {
    const wrap = document.createElement('div');
    wrap.className = 'mtf-chart-wrap';
    wrap.id = `chart-wrap-${assetId}-${tf}`;
    wrap.innerHTML = `
      <div class="mtf-chart-header">
        <span class="mtf-chart-title">${asset.symbol} <span class="mtf-chart-tf">${tf}</span></span>
        <button class="expand-btn" onclick="openExpandedChart('${assetId}','${tf}')" title="Expand">⛶</button>
      </div>
      <div class="mtf-chart-canvas" id="canvas-${assetId}-${tf}"></div>`;
    chartsContainer.appendChild(wrap);

    const cdt = document.getElementById(`canvas-${assetId}-${tf}`);
    const chart = LightweightCharts.createChart(cdt, {
      width: cdt.clientWidth, height: 400,
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

    const indicatorSeriesMap = {};
    if (histIndicators && histIndicators[tf]) {
      const lineColors = ['#3b82f6', '#f59e0b', '#8b5cf6', '#06b6d4'];
      let colorIdx = 0;
      for (const [indName, dataPoints] of Object.entries(histIndicators[tf])) {
        const line = chart.addLineSeries({ color: lineColors[colorIdx % lineColors.length], lineWidth: 1, title: indName });
        const sortedPts = [...dataPoints].map(p => ({ time: _toTs(p.time), value: p.value })).sort((a, b) => a.time - b.time);
        line.setData(sortedPts);
        indicatorSeriesMap[indName] = line;
        colorIdx++;
      }
    }

    asset.charts[tf] = { wrapEl: wrap, chartInst: chart, candleSeries, indicatorSeriesMap };

    if (histCandles && histCandles[tf]) {
      const uniqueData = []; const seen = new Set();
      const sorted = histCandles[tf].map(c => ({ time: _toTs(c.time), open: c.open, high: c.high, low: c.low, close: c.close })).sort((a, b) => a.time - b.time);
      for (const bar of sorted) { if (!seen.has(bar.time)) { seen.add(bar.time); uniqueData.push(bar); } }
      try { candleSeries.setData(uniqueData); } catch (e) { console.error("Error setting candle data", e); }
    }
  });

  // Render historical signals & markers
  if (histSignals && histSignals.length > 0) {
    const reversed = [...histSignals].reverse();
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
    for (const tf in markersByTf) {
      if (asset.charts[tf]) {
        const markers = markersByTf[tf].sort((a, b) => a.time - b.time);
        asset.charts[tf].candleSeries.setMarkers(markers);
        if (!asset.markers) asset.markers = {};
        asset.markers[tf] = markers;
      }
    }
  }

  // Resize handler
  const resizeObs = new ResizeObserver(() => {
    for (const tf in asset.charts) {
      const cdt = document.getElementById(`canvas-${assetId}-${tf}`);
      if (cdt && asset.charts[tf].chartInst) asset.charts[tf].chartInst.applyOptions({ width: cdt.clientWidth });
    }
  });
  resizeObs.observe(chartsContainer);
}

function toggleAssetPanel(assetId) {
  const asset = state.assets[assetId];
  if (!asset) return;
  const body = document.getElementById(`body-${assetId}`);
  const btn = document.getElementById(`toggle-${assetId}`);
  if (!body) return;
  asset.minimized = !asset.minimized;
  body.style.display = asset.minimized ? 'none' : '';
  if (btn) btn.textContent = asset.minimized ? '+' : '_';
  const panel = document.getElementById(`panel-${assetId}`);
  if (panel) panel.classList.toggle('minimized', asset.minimized);
}

async function removeAssetPanel(assetId) {
  try { await api('/api/mtf/stop', { method: 'POST', body: JSON.stringify({ asset_id: assetId }) }); } catch (e) { }
  const asset = state.assets[assetId];
  if (asset) {
    for (const tf in asset.charts) { if (asset.charts[tf].chartInst) asset.charts[tf].chartInst.remove(); }
  }
  delete state.assets[assetId];
  const panel = document.getElementById(`panel-${assetId}`);
  if (panel) panel.remove();
  if (Object.keys(state.assets).length === 0) {
    document.getElementById('asset-panels-section').style.display = 'none';
    const mt5Sec = document.getElementById('mt5-section');
    if (mt5Sec) mt5Sec.style.display = '';
    const reportSec = document.getElementById('sidebar-report-section');
    if (reportSec) reportSec.style.display = 'none';
    if (wsConnection) { wsConnection.close(); wsConnection = null; }
    destroyTradingPanel();
  }
}

async function stopAllScanners() {
  try { await api('/api/mtf/stop-all', { method: 'POST' }); } catch (e) { }
  for (const assetId in state.assets) {
    const asset = state.assets[assetId];
    for (const tf in asset.charts) { if (asset.charts[tf].chartInst) asset.charts[tf].chartInst.remove(); }
    const panel = document.getElementById(`panel-${assetId}`);
    if (panel) panel.remove();
  }
  state.assets = {};
  document.getElementById('asset-panels-section').style.display = 'none';
  const mt5Sec = document.getElementById('mt5-section');
  if (mt5Sec) mt5Sec.style.display = '';
  const reportSec = document.getElementById('sidebar-report-section');
  if (reportSec) reportSec.style.display = 'none';
  if (wsConnection) { wsConnection.close(); wsConnection = null; }
  destroyTradingPanel();
}

// ─── Add Asset Dialog ───────────────────────────────────────────
function showAddAssetDialog() {
  const modal = document.getElementById('add-asset-dialog');
  const body = document.getElementById('add-asset-body');
  body.innerHTML = `
    <div style="padding: 24px; display:flex; flex-direction:column; gap:16px;">
      <div class="form-group"><label>Symbol</label>
        <input type="text" id="add-symbol-search" placeholder="Search symbols..." oninput="filterAddSymbols()" />
        <div class="symbol-list" id="add-symbol-list" style="max-height:140px"></div>
      </div>
      <div class="form-group"><label>Timeframes</label>
        <div class="timeframe-grid" id="add-tf-grid"></div>
      </div>
      <div class="form-group"><label>Strategy</label>
        <select id="add-strategy-select">
          ${state.strategies.map(s => `<option value="${s.name}" ${state.config.strategy === s.name ? 'selected' : ''}>${s.name}</option>`).join('')}
        </select>
      </div>
      <button class="btn btn-run" onclick="confirmAddAsset()" style="width:100%"><span class="run-icon">▶</span> Start Asset</button>
    </div>`;
  modal.classList.add('show');
  window._addAssetSymbol = '';
  window._addAssetTfs = [...state.config.timeframes];
  filterAddSymbols();
  renderAddTimeframes();
}

function hideAddAssetDialog() { document.getElementById('add-asset-dialog').classList.remove('show'); }

function filterAddSymbols() {
  const q = (document.getElementById('add-symbol-search')?.value || '').toLowerCase();
  const filtered = state.symbols.filter(s => s.name.toLowerCase().includes(q));
  const list = document.getElementById('add-symbol-list');
  if (!list) return;
  list.innerHTML = filtered.slice(0, 30).map(s => `
    <button class="symbol-item ${window._addAssetSymbol === s.name ? 'active' : ''}" onclick="window._addAssetSymbol='${s.name}'; document.getElementById('add-symbol-search').value='${s.name}'; filterAddSymbols();">
      <span class="symbol-name">${s.name}</span><span class="symbol-spread">${s.spread} pts</span>
    </button>`).join('');
}

function renderAddTimeframes() {
  const grid = document.getElementById('add-tf-grid');
  if (!grid) return;
  grid.innerHTML = state.timeframes.map(tf => `<button class="tf-btn ${window._addAssetTfs.includes(tf.value) ? 'active' : ''}" onclick="toggleAddTf('${tf.value}')">${tf.value}</button>`).join('');
}

function toggleAddTf(tf) {
  if (window._addAssetTfs.includes(tf)) window._addAssetTfs = window._addAssetTfs.filter(t => t !== tf);
  else window._addAssetTfs.push(tf);
  renderAddTimeframes();
}

function confirmAddAsset() {
  const sym = window._addAssetSymbol;
  const tfs = window._addAssetTfs;
  const strat = document.getElementById('add-strategy-select')?.value;
  if (!sym || tfs.length === 0 || !strat) { alert('Fill in all fields.'); return; }
  hideAddAssetDialog();
  launchAssetPanel(sym, tfs, strat, { ...state.config.settings });
}

// ─── WebSocket ──────────────────────────────────────────────────
function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/api/mtf/stream`;
  wsConnection = new WebSocket(wsUrl);
  wsConnection.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    const assetId = msg.asset_id;
    const asset = assetId ? state.assets[assetId] : null;
    if (msg.type === 'bar_updates' && asset) {
      (msg.data || []).forEach(update => {
        const tf = update.timeframe;
        if (asset.charts[tf]) {
          asset.charts[tf].candleSeries.update({ time: _toTs(update.bar.time), open: update.bar.open, high: update.bar.high, low: update.bar.low, close: update.bar.close });
          if (state.expandedAssetId === assetId && state.expandedTf === tf && state.expandedCandles) {
            state.expandedCandles.update({ time: _toTs(update.bar.time), open: update.bar.open, high: update.bar.high, low: update.bar.low, close: update.bar.close });
          }
        }
      });
    } else if (msg.type === 'signal' && asset) {
      handleNewSignal(assetId, msg.data);
    } else if (msg.type === 'risk_alert') {
      handleRiskAlert(msg.data);
    }
  };
  wsConnection.onclose = () => { if (Object.keys(state.assets).length > 0) setTimeout(connectWebSocket, 2000); };
  wsConnection.onerror = (err) => console.error("WS Error", err);
}

function handleNewSignal(assetId, sig) {
  const asset = state.assets[assetId];
  if (!asset) return;
  const tf = sig.timeframe;
  const isBuy = sig.direction === 'BUY';
  if (asset.charts[tf]) {
    const wrap = asset.charts[tf].wrapEl;
    wrap.classList.remove('chart-glow-buy', 'chart-glow-sell');
    void wrap.offsetWidth;
    wrap.classList.add(isBuy ? 'chart-glow-buy' : 'chart-glow-sell');
    const marker = { time: _toTs(sig.bar_time), position: isBuy ? 'belowBar' : 'aboveBar', color: isBuy ? '#22c55e' : '#ef4444', shape: isBuy ? 'arrowUp' : 'arrowDown', text: sig.direction };
    if (!asset.markers) asset.markers = {};
    if (!asset.markers[tf]) asset.markers[tf] = [];
    asset.markers[tf].push(marker);
    asset.markers[tf].sort((a, b) => a.time - b.time);
    asset.charts[tf].candleSeries.setMarkers(asset.markers[tf]);
    if (state.expandedAssetId === assetId && state.expandedTf === tf && state.expandedCandles) {
      state.expandedCandles.setMarkers(asset.markers[tf]);
    }
  }
  renderSignalItem(sig);
}

function renderSignalItem(sig) {
  const isBuy = sig.direction === 'BUY';
  const rc = document.getElementById('report-card');
  const empty = rc.querySelector('.report-empty');
  if (empty) empty.remove();
  const item = document.createElement('div');
  item.className = `report-item ${isBuy ? 'buy' : 'sell'}`;
  const d = new Date(new Date(sig.time).getTime() + IST_OFFSET_MS);
  const pad = n => String(n).padStart(2, '0');
  const timeFmt = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} IST`;
  item.innerHTML = `<div class="report-item-header"><span>${sig.symbol} <span class="mtf-chart-tf">${sig.timeframe}</span></span><span class="${isBuy ? 'text-profit' : 'text-loss'}">${sig.direction}</span></div><div class="report-item-time">${timeFmt} • @ ${sig.price}</div>`;
  rc.prepend(item);
}

// ─── Expanded Chart Modal ───────────────────────────────────────
function openExpandedChart(assetId, tf) {
  const asset = state.assets[assetId];
  if (!asset) return;
  const modal = document.getElementById('chart-modal');
  const container = document.getElementById('modal-chart-container');
  const title = document.getElementById('modal-title');
  title.innerHTML = `${asset.symbol} <span class="mtf-chart-tf">${tf}</span>`;
  container.innerHTML = '';
  const colors = getChartColors();
  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth, height: container.clientHeight,
    layout: { background: { type: 'solid', color: colors.bg }, textColor: colors.text, fontFamily: "'Inter', sans-serif", fontSize: 12 },
    grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
    rightPriceScale: { borderColor: colors.border },
    timeScale: { borderColor: colors.border, timeVisible: true, secondsVisible: false },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });
  const candleSeries = chart.addCandlestickSeries({ upColor: '#22c55e', downColor: '#ef4444', borderUpColor: '#22c55e', borderDownColor: '#ef4444', wickUpColor: '#22c55e', wickDownColor: '#ef4444' });
  const orig = asset.charts[tf];
  if (orig) {
    candleSeries.setData(orig.candleSeries.data());
    if (asset.markers && asset.markers[tf]) candleSeries.setMarkers(asset.markers[tf]);
    if (orig.indicatorSeriesMap) {
      for (const [indName, indSeries] of Object.entries(orig.indicatorSeriesMap)) {
        const line = chart.addLineSeries({ color: indSeries.options().color, lineWidth: indSeries.options().lineWidth, title: indName });
        line.setData(indSeries.data());
      }
    }
  }
  state.expandedChart = chart; state.expandedCandles = candleSeries; state.expandedTf = tf; state.expandedAssetId = assetId;
  modal.classList.add('show');
  setTimeout(() => chart.applyOptions({ width: container.clientWidth, height: container.clientHeight }), 50);
}

function closeExpandedChart() {
  document.getElementById('chart-modal').classList.remove('show');
  if (state.expandedChart) { state.expandedChart.remove(); state.expandedChart = null; state.expandedCandles = null; state.expandedTf = null; state.expandedAssetId = null; }
}

document.addEventListener('DOMContentLoaded', () => {
  const closeBtn = document.getElementById('close-modal-btn');
  if (closeBtn) closeBtn.addEventListener('click', closeExpandedChart);
});
