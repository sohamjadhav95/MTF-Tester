// ─── MTF Scanner — Core Module ─────────────────────────────────
const API = '';

// ─── App State ──────────────────────────────────────────────────
const state = {
  mt5Connected: false,
  accountInfo: null,
  symbols: [],
  timeframes: [],
  strategies: [],
  strategySettings: null,
  marketType: 'forex',
  config: {
    symbol: '', timeframes: ['M5', 'M15', 'H1'],
    strategy: '', settings: {},
    initialBalance: 10000, lotSize: 0.1,
    startTime: ''
  },
  assets: {},          // { assetId: { symbol, timeframes, strategy, settings, charts, minimized, markers } }
  rememberMe: false,
};

let wsConnection = null;
let _assetIdCounter = 0;

function generateAssetId() {
  return 'asset_' + (++_assetIdCounter) + '_' + Date.now();
}

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

// ─── Theme Toggle ───────────────────────────────────────────────
function toggleTheme() {
  const html = document.documentElement;
  const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  document.getElementById('theme-icon').textContent = next === 'dark' ? '☀️' : '🌙';
  localStorage.setItem('theme', next);
}

function applyThemeFromStorage() {
  const saved = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  const icon = document.getElementById('theme-icon');
  if (icon) icon.textContent = saved === 'dark' ? '☀️' : '🌙';
}

// ─── Chart Color Helper ─────────────────────────────────────────
function getChartColors() {
  const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
  return {
    bg: isDark ? '#0d1421' : '#ffffff',
    text: isDark ? '#94a3b8' : '#64748b',
    grid: isDark ? '#1e2d42' : '#e2e8f0',
    border: isDark ? '#1e2d42' : '#e2e8f0',
  };
}

// ─── Timestamp Utilities ────────────────────────────────────────
const IST_OFFSET_MS = 0;
const IST_OFFSET_S = 0;

function _toTs(isoStr) { return Math.floor(new Date(isoStr).getTime() / 1000); }

function fmtTimeIST(isoStr) {
  if (!isoStr) return '—';
  try {
    const ts = isoStr.includes('Z') || isoStr.includes('+') ? isoStr : isoStr + 'Z';
    const d = new Date(new Date(ts).getTime() + IST_OFFSET_MS);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} IST`;
  } catch { return isoStr; }
}

// ─── Persistence ────────────────────────────────────────────────
async function saveSession() {
  try {
    await api('/api/session/save', {
      method: 'POST',
      body: JSON.stringify({ config: state.config }),
    });
  } catch (e) { console.warn('Save session failed:', e); }
}

async function loadSession() {
  try {
    const data = await api('/api/session/load');
    if (data.saved && data.config) {
      Object.assign(state.config, data.config);
    }
  } catch (e) { console.warn('Load session failed:', e); }
}

async function trySavedLogin() {
  try {
    const data = await api('/api/credentials/load');
    if (data.saved) {
      state.rememberMe = true;
      // Auto-connect
      const result = await api('/api/mt5/connect', {
        method: 'POST',
        body: JSON.stringify({ server: data.server, login: data.login, password: data.password }),
      });
      state.mt5Connected = true;
      state.accountInfo = result.account;
      await loadConfigData();
      renderMT5Section();
      renderConfigCols();
    }
  } catch (e) { console.warn('Auto-login failed:', e); }
}

// ─── Toggle Config Panel ────────────────────────────────────────
function toggleConfig() {
  const cols = document.getElementById('config-cols');
  const btn = document.getElementById('config-toggle-btn');
  if (!cols) return;
  if (cols.classList.contains('collapsed')) {
    cols.classList.remove('collapsed');
    if (btn) btn.textContent = '_';
  } else {
    cols.classList.add('collapsed');
    if (btn) btn.textContent = '+';
  }
}

// ─── Initialization ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  applyThemeFromStorage();
  renderMT5Section();
  renderConfigCols();
  await loadSession();
  await trySavedLogin();
  renderConfigCols();
});
