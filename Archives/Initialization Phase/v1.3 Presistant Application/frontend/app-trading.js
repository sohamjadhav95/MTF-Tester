// ─── MTF Scanner — Trading Panel Module ────────────────────────

const tradingState = {
  orderType: 'market', direction: 'buy', symbol: '', volume: 0.01, price: null,
  slEnabled: false, tpEnabled: false, sl: null, tp: null,
  timeEnabled: false, executeTime: '', riskEnabled: false, riskThreshold: 5.0,
  positions: [], scheduledTimer: null,
};
let positionPollInterval = null;
let riskPollInterval = null;

function toggleTradingPanel() {
  const body = document.getElementById('trading-panel-body');
  const btn = document.getElementById('trading-toggle-btn');
  if (!body) return;
  if (body.style.display === 'none') { body.style.display = ''; if (btn) btn.textContent = '_'; }
  else { body.style.display = 'none'; if (btn) btn.textContent = '+'; }
}

function initTradingPanel() {
  tradingState.symbol = state.config.symbol || '';
  tradingState.volume = state.config.lotSize || 0.01;
  document.getElementById('trading-panel').style.display = '';
  renderOrderForm(); renderRiskMonitor(); renderPositionsTable([]);
  if (positionPollInterval) clearInterval(positionPollInterval);
  positionPollInterval = setInterval(pollPositions, 2000);
  if (riskPollInterval) clearInterval(riskPollInterval);
  riskPollInterval = setInterval(pollRiskStatus, 3000);
  pollPositions();
}

function destroyTradingPanel() {
  document.getElementById('trading-panel').style.display = 'none';
  if (positionPollInterval) { clearInterval(positionPollInterval); positionPollInterval = null; }
  if (riskPollInterval) { clearInterval(riskPollInterval); riskPollInterval = null; }
  if (tradingState.scheduledTimer) { clearTimeout(tradingState.scheduledTimer); tradingState.scheduledTimer = null; }
}

function renderOrderForm() {
  const el = document.getElementById('order-form-content');
  if (!el) return;
  el.innerHTML = `
    <div class="order-toggle-row">
      <button class="order-toggle-btn ${tradingState.orderType === 'market' ? 'active' : ''}" onclick="setOrderType('market')">Market</button>
      <button class="order-toggle-btn ${tradingState.orderType === 'pending' ? 'active' : ''}" onclick="setOrderType('pending')">Pending</button>
    </div>
    <div class="order-toggle-row direction-row">
      <button class="order-dir-btn buy-btn ${tradingState.direction === 'buy' ? 'active' : ''}" onclick="setDirection('buy')">BUY</button>
      <button class="order-dir-btn sell-btn ${tradingState.direction === 'sell' ? 'active' : ''}" onclick="setDirection('sell')">SELL</button>
    </div>
    <div class="order-field"><label>Asset</label><input type="text" value="${tradingState.symbol}" id="order-symbol" onchange="tradingState.symbol=this.value" placeholder="e.g. EURUSD" /></div>
    <div class="order-field"><label>Volume (Lots)</label><input type="number" value="${tradingState.volume}" min="0.01" step="0.01" onchange="tradingState.volume=parseFloat(this.value)" /></div>
    <div class="order-field" style="${tradingState.orderType === 'pending' ? '' : 'display:none'}"><label>Price</label><input type="number" step="0.00001" value="${tradingState.price || ''}" onchange="tradingState.price=parseFloat(this.value)" placeholder="Entry price" /></div>
    <div class="order-field-toggle"><div class="toggle-header"><label>Stop Loss</label><label class="switch-sm"><input type="checkbox" ${tradingState.slEnabled ? 'checked' : ''} onchange="tradingState.slEnabled=this.checked; renderOrderForm()" /><span class="slider-sm"></span></label></div>
      ${tradingState.slEnabled ? `<input type="number" step="0.00001" value="${tradingState.sl || ''}" onchange="tradingState.sl=parseFloat(this.value)" placeholder="SL Price" />` : ''}
    </div>
    <div class="order-field-toggle"><div class="toggle-header"><label>Take Profit</label><label class="switch-sm"><input type="checkbox" ${tradingState.tpEnabled ? 'checked' : ''} onchange="tradingState.tpEnabled=this.checked; renderOrderForm()" /><span class="slider-sm"></span></label></div>
      ${tradingState.tpEnabled ? `<input type="number" step="0.00001" value="${tradingState.tp || ''}" onchange="tradingState.tp=parseFloat(this.value)" placeholder="TP Price" />` : ''}
    </div>
    <button class="btn-place-order ${tradingState.direction === 'buy' ? 'buy' : 'sell'}" onclick="confirmPlaceOrder()">
      ${tradingState.direction === 'buy' ? '🟢' : '🔴'} Place ${tradingState.direction.toUpperCase()} Order
    </button>
    <div id="order-error" class="order-error" style="display:none"></div>
    <div id="order-success" class="order-success" style="display:none"></div>`;
}

function setOrderType(type) { tradingState.orderType = type; renderOrderForm(); }
function setDirection(dir) { tradingState.direction = dir; renderOrderForm(); }

function confirmPlaceOrder() {
  const sym = tradingState.symbol, dir = tradingState.direction.toUpperCase(), vol = tradingState.volume;
  let details = `${tradingState.orderType.toUpperCase()} ${dir} ${vol} lots on ${sym}`;
  if (tradingState.slEnabled && tradingState.sl) details += ` | SL: ${tradingState.sl}`;
  if (tradingState.tpEnabled && tradingState.tp) details += ` | TP: ${tradingState.tp}`;
  showConfirmationDialog(details, executePlaceOrder);
}

function showConfirmationDialog(message, onConfirm) {
  const existing = document.getElementById('confirm-dialog-overlay');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.id = 'confirm-dialog-overlay'; overlay.className = 'confirm-overlay';
  overlay.innerHTML = `<div class="confirm-dialog"><div class="confirm-dialog-header"><span class="confirm-icon">⚠️</span><h3>Confirm Order</h3></div><p class="confirm-message">${message}</p><p class="confirm-warning">This will send a REAL order to your MT5 account.</p><div class="confirm-actions"><button class="btn-confirm-cancel" onclick="document.getElementById('confirm-dialog-overlay').remove()">Cancel</button><button class="btn-confirm-ok" id="btn-confirm-go">Confirm & Place</button></div></div>`;
  document.body.appendChild(overlay);
  document.getElementById('btn-confirm-go').onclick = () => { overlay.remove(); onConfirm(); };
}

function executePlaceOrder() { placeLiveOrder(); }

async function placeLiveOrder() {
  const errEl = document.getElementById('order-error'), sucEl = document.getElementById('order-success');
  errEl.style.display = 'none'; sucEl.style.display = 'none';
  const payload = { symbol: tradingState.symbol, order_type: tradingState.orderType, direction: tradingState.direction, volume: tradingState.volume, price: tradingState.orderType === 'pending' ? tradingState.price : null, sl: tradingState.slEnabled ? tradingState.sl : null, tp: tradingState.tpEnabled ? tradingState.tp : null, sl_enabled: tradingState.slEnabled, tp_enabled: tradingState.tpEnabled };
  try {
    const result = await api('/api/trading/order', { method: 'POST', body: JSON.stringify(payload) });
    sucEl.textContent = `✓ Order placed! Ticket: ${result.ticket} @ ${result.price}`;
    sucEl.style.display = 'block';
    setTimeout(() => { sucEl.style.display = 'none'; }, 5000);
    pollPositions();
  } catch (err) { errEl.textContent = err.message; errEl.style.display = 'block'; setTimeout(() => { errEl.style.display = 'none'; }, 8000); }
}

async function pollPositions() {
  if (!state.mt5Connected) return;
  try { const data = await api('/api/trading/positions'); tradingState.positions = data.positions || []; renderPositionsTable(tradingState.positions); } catch (_) { }
}

function renderPositionsTable(positions) {
  const wrap = document.getElementById('positions-table-wrap');
  if (!wrap) return;
  if (!positions || positions.length === 0) { wrap.innerHTML = '<div class="positions-empty">No open positions</div>'; return; }
  const totalPnL = positions.reduce((sum, p) => sum + p.profit, 0);
  const pnlClass = totalPnL >= 0 ? 'text-profit' : 'text-loss';
  wrap.innerHTML = `
    <div class="positions-summary"><span>${positions.length} position${positions.length > 1 ? 's' : ''}</span><span class="${pnlClass}">${totalPnL >= 0 ? '+' : ''}${totalPnL.toFixed(2)}</span></div>
    <div class="positions-scroll"><table class="pos-table"><thead><tr><th>Ticket</th><th>Symbol</th><th>Type</th><th>Vol</th><th>Open</th><th>Current</th><th>P&L</th><th></th></tr></thead>
    <tbody>${positions.map(p => {
      const plClass = p.profit >= 0 ? 'text-profit' : 'text-loss';
      const typeClass = p.type === 'buy' ? 'side-badge buy' : 'side-badge sell';
      return `<tr><td class="mono">${p.ticket}</td><td class="mono">${p.symbol}</td><td><span class="${typeClass}">${p.type.toUpperCase()}</span></td><td>${p.volume}</td><td class="mono">${p.price_open}</td><td class="mono">${p.price_current}</td><td class="${plClass} mono">${p.profit >= 0 ? '+' : ''}${p.profit.toFixed(2)}</td><td><button class="btn-close-pos" onclick="closeSinglePosition(${p.ticket})">✕</button></td></tr>`;
    }).join('')}</tbody></table></div>`;
}

async function closeSinglePosition(ticket) { try { await api(`/api/trading/close/${ticket}`, { method: 'POST' }); pollPositions(); } catch (err) { alert('Close failed: ' + err.message); } }
async function closeAllPositions() { if (tradingState.positions.length === 0) return; showConfirmationDialog(`Close ALL ${tradingState.positions.length} open position(s)?`, async () => { try { await api('/api/trading/close-all', { method: 'POST' }); pollPositions(); } catch (err) { alert('Close all failed: ' + err.message); } }); }

function renderRiskMonitor() {
  const el = document.getElementById('risk-monitor-content');
  if (!el) return;
  el.innerHTML = `
    <div class="risk-toggle-row"><label>Enable Risk Threshold</label><label class="switch-sm"><input type="checkbox" ${tradingState.riskEnabled ? 'checked' : ''} onchange="toggleRiskThreshold(this.checked)" id="risk-enabled-chk" /><span class="slider-sm"></span></label></div>
    <div class="order-field"><label>Max Drawdown (%)</label><input type="number" value="${tradingState.riskThreshold}" min="0.5" max="100" step="0.5" onchange="tradingState.riskThreshold=parseFloat(this.value)" /></div>
    <div class="risk-bar-container"><div class="risk-bar-bg"><div class="risk-bar-fill" id="risk-bar-fill" style="width:0%"></div><div class="risk-bar-threshold" id="risk-bar-threshold" style="left:${tradingState.riskThreshold}%"></div></div>
      <div class="risk-bar-labels"><span id="risk-drawdown-label">0.00%</span><span id="risk-status-label" class="risk-status-safe">SAFE</span></div></div>
    <div class="risk-account-info" id="risk-account-info"></div>`;
}

async function toggleRiskThreshold(enabled) { tradingState.riskEnabled = enabled; try { await api('/api/trading/risk-threshold', { method: 'POST', body: JSON.stringify({ enabled, threshold_pct: tradingState.riskThreshold }) }); } catch (e) { } }

async function pollRiskStatus() { if (!state.mt5Connected) return; try { const data = await api('/api/trading/risk-status'); updateRiskDisplay(data); } catch (_) { } }

function updateRiskDisplay(data) {
  const fillEl = document.getElementById('risk-bar-fill'), drawdownLabel = document.getElementById('risk-drawdown-label'), statusLabel = document.getElementById('risk-status-label'), acctInfo = document.getElementById('risk-account-info');
  if (!fillEl || !drawdownLabel || !statusLabel) return;
  const dd = data.drawdown_pct || 0, threshold = data.threshold_pct || tradingState.riskThreshold;
  fillEl.style.width = Math.min(dd, 100) + '%';
  drawdownLabel.textContent = dd.toFixed(2) + '%';
  if (data.breached) { fillEl.style.background = 'var(--loss-red)'; statusLabel.textContent = 'BREACHED'; statusLabel.className = 'risk-status-danger'; }
  else if (dd >= threshold * 0.8) { fillEl.style.background = 'var(--warning-amber)'; statusLabel.textContent = 'WARNING'; statusLabel.className = 'risk-status-warning'; }
  else { fillEl.style.background = 'var(--profit-green)'; statusLabel.textContent = 'SAFE'; statusLabel.className = 'risk-status-safe'; }
  const thresholdEl = document.getElementById('risk-bar-threshold');
  if (thresholdEl) thresholdEl.style.left = Math.min(threshold, 100) + '%';
  if (acctInfo) {
    const bal = data.current_balance != null ? data.current_balance.toFixed(2) : '—';
    const eq = data.current_equity != null ? data.current_equity.toFixed(2) : '—';
    acctInfo.innerHTML = `<div class="risk-info-row"><span>Balance</span><span class="mono">${bal}</span></div><div class="risk-info-row"><span>Equity</span><span class="mono">${eq}</span></div>`;
  }
}

function handleRiskAlert(data) {
  const overlay = document.createElement('div');
  overlay.className = 'risk-alert-overlay';
  overlay.innerHTML = `<div class="risk-alert-box"><div class="risk-alert-icon">🚨</div><h3>RISK THRESHOLD BREACHED</h3><p>${data.message}</p><div class="risk-alert-details"><span>Drawdown: <strong>${data.drawdown_pct}%</strong></span><span>Positions Closed: <strong>${data.positions_closed}</strong></span></div><button class="btn-primary" onclick="this.closest('.risk-alert-overlay').remove()">Acknowledge</button></div>`;
  document.body.appendChild(overlay);
  tradingState.riskEnabled = false;
  const chk = document.getElementById('risk-enabled-chk');
  if (chk) chk.checked = false;
  pollPositions();
}
