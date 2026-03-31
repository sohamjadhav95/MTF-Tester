// ─── MTF Scanner — Config & Connection Module ──────────────────

// ─── Market Type ────────────────────────────────────────────────
async function setMarketType(type) {
  state.marketType = type;
  const isCrypto = type === 'crypto';
  document.getElementById('btn-forex').classList.toggle('active', !isCrypto);
  document.getElementById('btn-crypto').classList.toggle('active', isCrypto);
  document.documentElement.setAttribute('data-market', isCrypto ? 'crypto' : 'forex');
  state.config.symbol = '';
  state.config.timeframes = isCrypto ? ['H1'] : ['M5', 'H1'];
  renderMT5Section();
  if (isCrypto) {
    document.getElementById('config-col-left').innerHTML = '<div class="config-disabled"><div class="disabled-icon">⏳</div><p>Loading Binance Futures symbols...</p></div>';
    try {
      const [symRes, tfRes, stratRes] = await Promise.all([
        api('/api/crypto/symbols'), api('/api/crypto/timeframes'), api('/api/strategies'),
      ]);
      state.symbols = symRes.symbols || [];
      state.timeframes = tfRes.timeframes || [];
      state.strategies = stratRes.strategies || [];
      state.config.lotSize = 0.01;
    } catch (err) { console.error('Failed to load crypto data:', err); }
    renderConfigCols();
  } else {
    if (state.mt5Connected) { await loadConfigData(); }
    else { state.symbols = []; state.timeframes = []; }
    renderConfigCols();
  }
}

// ─── MT5 Section ────────────────────────────────────────────────
function renderMT5Section() {
  const el = document.getElementById('mt5-section');
  if (state.marketType === 'crypto') {
    el.innerHTML = `<div class="sidebar-content-scroll">
      <div class="connection-status"><span class="status-dot connected"></span><span class="status-text">Binance Futures</span></div>
      <div class="account-details">
        <div class="detail-row"><span class="detail-label">Source</span><span class="detail-value">Binance FAPI</span></div>
        <div class="detail-row"><span class="detail-label">Market</span><span class="detail-value">USDT Perpetuals</span></div>
        <div class="detail-row"><span class="detail-label">Auth</span><span class="detail-value text-profit">Public API ✓</span></div>
      </div>
      <button class="btn-disconnect" onclick="setMarketType('forex')" style="margin-top:12px">← Switch to Forex</button>
    </div>`;
    return;
  }
  if (state.mt5Connected && state.accountInfo) {
    const a = state.accountInfo;
    el.innerHTML = `<div class="sidebar-content-scroll">
      <div class="connection-status"><span class="status-dot connected"></span><span class="status-text">MT5 Connected</span></div>
      <div class="account-details">
        <div class="detail-row"><span class="detail-label">Account</span><span class="detail-value">${a.login}</span></div>
        <div class="detail-row"><span class="detail-label">Name</span><span class="detail-value">${a.name}</span></div>
        <div class="detail-row"><span class="detail-label">Server</span><span class="detail-value">${a.server}</span></div>
        <div class="detail-row"><span class="detail-label">Balance</span><span class="detail-value text-profit">${a.currency} ${a.balance?.toLocaleString()}</span></div>
      </div>
      <button class="btn-disconnect" onclick="disconnectMT5()">Disconnect</button>
    </div>`;
  } else {
    el.innerHTML = `<div class="sidebar-content-scroll">
      <div class="connection-status"><span class="status-dot disconnected"></span><span class="status-text">MT5 Disconnected</span></div>
      <div id="mt5-error"></div>
      <form onsubmit="connectMT5(event)">
        <div class="form-group"><label>Server</label><input type="text" id="mt5-server" placeholder="e.g. Exness-MT5Real" required /></div>
        <div class="form-group"><label>Login</label><input type="text" id="mt5-login" placeholder="Account number" required /></div>
        <div class="form-group"><label>Password</label><input type="password" id="mt5-password" placeholder="Password" required /></div>
        <div class="remember-me-row">
          <label class="remember-label"><input type="checkbox" id="remember-me-chk" ${state.rememberMe ? 'checked' : ''} onchange="state.rememberMe=this.checked" /> Remember Me</label>
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
  const btn = e.target.querySelector('button[type="submit"]');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Connecting...';
  try {
    const data = await api('/api/mt5/connect', {
      method: 'POST',
      body: JSON.stringify({ server, login: parseInt(login), password }),
    });
    state.mt5Connected = true;
    state.accountInfo = data.account;
    // Save credentials if Remember Me is checked
    if (state.rememberMe) {
      await api('/api/credentials/save', { method: 'POST', body: JSON.stringify({ server, login: parseInt(login), password }) });
    }
    renderMT5Section();
    await loadConfigData();
    renderConfigCols();
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
  renderMT5Section();
  renderConfigCols();
}

// ─── Load Config Data ───────────────────────────────────────────
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

// ─── Config Panel ───────────────────────────────────────────────
function renderConfigCols() {
  const leftEl = document.getElementById('config-col-left');
  const rightEl = document.getElementById('config-col-right');
  const isCrypto = state.marketType === 'crypto';
  if (!state.mt5Connected && !isCrypto) {
    leftEl.innerHTML = `<div class="config-disabled"><div class="disabled-icon">🔌</div><p>Connect to MT5 to configure</p></div>`;
    rightEl.innerHTML = '';
    return;
  }
  leftEl.innerHTML = `
    <div class="config-section"><h3 class="config-section-title">Asset Symbol</h3>
      <div class="form-group"><input type="text" id="symbol-search" placeholder="Search symbols..." oninput="filterSymbols()" /></div>
      <div class="symbol-list" id="symbol-list"></div>
    </div>
    <div class="config-section"><h3 class="config-section-title">Timeframes (Multi-Select)</h3>
      <div class="timeframe-grid" id="tf-grid"></div>
    </div>
    <div class="config-section"><h3 class="config-section-title">Strategy</h3>
      <div class="form-group"><select id="strategy-select" onchange="selectStrategy(this.value)">
        <option value="">Select a strategy...</option>
        ${state.strategies.map(s => `<option value="${s.name}" ${state.config.strategy === s.name ? 'selected' : ''}>${s.name}</option>`).join('')}
      </select></div>
      <div id="strategy-desc"></div>
    </div>
    <div class="config-section" style="padding-top:8px">
      <button class="btn btn-run" id="btn-start-scanner" onclick="startFirstAsset()" ${!state.mt5Connected && !isCrypto ? 'disabled' : ''}>
        <span class="run-icon">▶</span> Start Scanner
      </button>
    </div>`;
  filterSymbols();
  renderTimeframes();
  if (state.config.strategy) selectStrategy(state.config.strategy);
  renderRightColumn();
}

function renderRightColumn() {
  const rightEl = document.getElementById('config-col-right');
  if (!state.strategySettings || Object.keys(state.strategySettings).length === 0) {
    rightEl.innerHTML = `<div class="config-placeholder"><span class="config-placeholder-icon">⚙️</span><p>Select a strategy to configure its settings</p></div>`;
    return;
  }
  rightEl.innerHTML = `
    <div class="config-section"><h3 class="config-section-title">Strategy Settings</h3><div class="settings-grid" id="strategy-settings"></div></div>
    <div class="config-section"><h3 class="config-section-title">Backtest Settings</h3>
      <div class="settings-grid">
        <div class="setting-item"><label class="setting-label">Start Date & Time (Optional)</label>
          <input type="datetime-local" value="${state.config.startTime}" step="1" onchange="state.config.startTime=this.value" />
          <span class="setting-range">Limits historical fetch.</span></div>
        <div class="setting-item"><label class="setting-label">Initial Balance</label>
          <input type="number" value="${state.config.initialBalance}" min="100" step="100" onchange="state.config.initialBalance=parseFloat(this.value)" /></div>
        <div class="setting-item"><label class="setting-label">Lot Size</label>
          <input type="number" value="${state.config.lotSize}" min="0.01" max="100" step="0.01" onchange="state.config.lotSize=parseFloat(this.value)" /></div>
      </div>
    </div>`;
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
    const visibleWhen = prop['x-visible-when'] || null;
    if (prop.enum) {
      inputHTML = `<select onchange="updateSetting('${key}', this.value)">${prop.enum.map(o => `<option value="${o}" ${val === o ? 'selected' : ''}>${String(o).replace(/_/g, ' ')}</option>`).join('')}</select>`;
    } else if (prop.type === 'integer' || prop.type === 'number') {
      const step = prop.step || (prop.type === 'number' ? 0.1 : 1);
      const min = prop.minimum ?? prop.exclusiveMinimum ?? '';
      const max = prop.maximum ?? prop.exclusiveMaximum ?? '';
      const parser = prop.type === 'integer' ? 'parseInt(this.value)' : 'parseFloat(this.value)';
      inputHTML = `<input type="number" value="${val}" min="${min}" max="${max}" step="${step}" onchange="updateSetting('${key}', ${parser})" />${min !== '' && max !== '' ? `<span class="setting-range">${min} — ${max}</span>` : ''}`;
    } else if (prop.type === 'boolean') {
      inputHTML = `<label style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" ${val ? 'checked' : ''} onchange="updateSetting('${key}', this.checked)" /><span style="font-size:0.8rem;color:var(--text-muted)">${val ? 'Enabled' : 'Disabled'}</span></label>`;
    } else if (prop.type === 'string') {
      inputHTML = `<input type="text" value="${val || ''}" onchange="updateSetting('${key}', this.value)" />`;
    }
    return `<div class="setting-item" data-setting-key="${key}" data-visible-when='${visibleWhen ? JSON.stringify(visibleWhen) : ""}'><label class="setting-label">${desc}</label>${inputHTML}</div>`;
  }).join('');
  refreshSettingVisibility();
}

function refreshSettingVisibility() {
  document.querySelectorAll('[data-setting-key]').forEach(item => {
    const raw = item.getAttribute('data-visible-when');
    if (!raw) return;
    let cond; try { cond = JSON.parse(raw); } catch { return; }
    const shouldShow = Object.entries(cond).every(([key, allowedVals]) => allowedVals.includes(state.config.settings[key]));
    item.classList.toggle('setting-item--hidden', !shouldShow);
  });
}

function updateSetting(key, value) {
  state.config.settings[key] = value;
  refreshSettingVisibility();
}

// ─── Symbols / Timeframes ───────────────────────────────────────
function filterSymbols() {
  const q = (document.getElementById('symbol-search')?.value || '').toLowerCase();
  const filtered = state.symbols.filter(s => s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q));
  const list = document.getElementById('symbol-list');
  if (!list) return;
  list.innerHTML = filtered.slice(0, 50).map(s => `
    <button class="symbol-item ${state.config.symbol === s.name ? 'active' : ''}" onclick="selectSymbol('${s.name}')">
      <span class="symbol-name">${s.name}</span><span class="symbol-spread">${s.spread} pts</span>
    </button>`).join('');
  if (filtered.length === 0) list.innerHTML = '<div style="padding:14px;text-align:center;color:var(--text-muted)">No symbols found</div>';
}

function selectSymbol(name) { state.config.symbol = name; document.getElementById('symbol-search').value = name; filterSymbols(); }

function renderTimeframes() {
  const grid = document.getElementById('tf-grid');
  if (!grid) return;
  grid.innerHTML = state.timeframes.map(tf => `<button class="tf-btn ${state.config.timeframes.includes(tf.value) ? 'active' : ''}" onclick="selectTimeframe('${tf.value}')">${tf.value}</button>`).join('');
}

function selectTimeframe(tf) {
  if (state.config.timeframes.includes(tf)) state.config.timeframes = state.config.timeframes.filter(t => t !== tf);
  else state.config.timeframes.push(tf);
  renderTimeframes();
}

function selectStrategy(name) {
  state.config.strategy = name;
  const strat = state.strategies.find(s => s.name === name);
  const descEl = document.getElementById('strategy-desc');
  if (descEl) descEl.innerHTML = strat?.description ? `<p class="strategy-desc">${strat.description}</p>` : '';
  if (!name || !strat) { state.strategySettings = null; renderRightColumn(); return; }
  const schema = strat.schema || {};
  state.strategySettings = schema;
  state.config.settings = {};
  if (schema.properties) Object.entries(schema.properties).forEach(([key, prop]) => { state.config.settings[key] = prop.default; });
  renderRightColumn();
}
