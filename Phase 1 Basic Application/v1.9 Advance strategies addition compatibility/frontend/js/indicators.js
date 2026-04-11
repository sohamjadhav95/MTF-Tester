/**
 * INDICATORS.JS — Chart Indicator UI & Renderer
 * ================================================
 * NO computation — all indicator math is server-side.
 * This module handles:
 *   1. Indicator catalog metadata (for the picker modal)
 *   2. Rendering server-provided data onto LightweightCharts
 *   3. Indicator modal UI (add indicators)
 *   4. Settings panel UI (edit indicator params)
 *   5. Chip bar UI (show active indicators)
 *   6. API calls to backend for add/remove/update
 */

// ── Per-chart indicator rendering state ────────────────────────────
// watchId → { indicators: { indId → { type, settings, series[], paneChart?, paneContainer? } } }
const _indicatorState = {};

// Track which watchId the indicator modal is opened for (null = global mode)
let _indicatorModalWatchId = null;
let _isGlobalIndicatorMode = false;

// ── Catalog (loaded from server, cached) ──────────────────────────
let _indicatorCatalog = [];
let _catalogLoaded = false;

async function loadIndicatorCatalog() {
    if (_catalogLoaded) return _indicatorCatalog;
    try {
        const data = await api('/api/watchlist/indicators/catalog');
        _indicatorCatalog = data.indicators || [];
        _catalogLoaded = true;
    } catch (e) {
        console.error('Failed to load indicator catalog:', e);
        _indicatorCatalog = [];
    }
    return _indicatorCatalog;
}

function getCatalogEntry(type) {
    return _indicatorCatalog.find(c => c.id === type) || null;
}


// ═══ INDICATOR STATE MANAGEMENT ════════════════════════════════════

function initIndicatorState(watchId) {
    _indicatorState[watchId] = { indicators: {} };
}

function destroyIndicatorState(watchId) {
    const state = _indicatorState[watchId];
    if (!state) return;

    for (const indId of Object.keys(state.indicators)) {
        _removeIndicatorSeries(watchId, indId);
    }
    delete _indicatorState[watchId];
}


// ═══ RENDERING — Server Data → LightweightCharts Series ═══════════

/**
 * Render a full indicator from server-provided data.
 * Called on indicator_added, indicator_updated, and indicator_sync.
 */
function renderIndicator(watchId, indId, type, settings, data) {
    const inst = _chartInstances[watchId];
    if (!inst) return;

    // Remove existing series if updating
    _removeIndicatorSeries(watchId, indId);

    const state = _indicatorState[watchId];
    if (!state) return;

    const catalog = getCatalogEntry(type);
    const pane = data?.pane || catalog?.pane || 'overlay';

    const indState = {
        type,
        settings: { ...settings },
        series: [],
        paneChart: null,
        paneContainer: null,
        pane,
    };

    if (pane === 'overlay') {
        _renderOverlay(inst, indState, data, settings);
    } else {
        _renderSeparatePane(watchId, inst, indState, data, settings, type);
    }

    state.indicators[indId] = indState;
    renderIndicatorChips(watchId);
}

/**
 * Render an overlay indicator (SMA, EMA, BB, VWAP) on the main chart.
 */
function _renderOverlay(inst, indState, data, settings) {
    const chart = inst.chart;
    const seriesData = data?.series || {};

    if (indState.type === 'bb') {
        // Bollinger Bands — 3 lines
        const colors = {
            middle: settings.color || '#9C27B0',
            upper: (settings.color || '#9C27B0') + '99',
            lower: (settings.color || '#9C27B0') + '99',
        };
        for (const [key, color] of [['middle', colors.middle], ['upper', colors.upper], ['lower', colors.lower]]) {
            const lineData = seriesData[key];
            if (lineData && lineData.length > 0) {
                const series = chart.addLineSeries({
                    color: color,
                    lineWidth: key === 'middle' ? (settings.lineWidth || 1) : 1,
                    lineStyle: key === 'middle' ? 0 : 2, // 0=solid, 2=dashed
                    priceLineVisible: false,
                    lastValueVisible: false,
                    crosshairMarkerVisible: false,
                });
                series.setData(_convertTimeValues(lineData));
                indState.series.push(series);
            }
        }
    } else {
        // Single line (SMA, EMA, VWAP)
        const lineData = seriesData.main;
        if (lineData && lineData.length > 0) {
            const series = chart.addLineSeries({
                color: settings.color || '#2196F3',
                lineWidth: settings.lineWidth || 2,
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: false,
            });
            series.setData(_convertTimeValues(lineData));
            indState.series.push(series);
        }
    }
}

/**
 * Render a separate-pane indicator (RSI, MACD, Volume) below the main chart.
 */
function _renderSeparatePane(watchId, inst, indState, data, settings, type) {
    const cell = document.getElementById(`watch-cell-${watchId}`);
    if (!cell) return;

    // Create pane container
    const paneId = `ind-pane-${watchId}-${Date.now()}`;
    const paneContainer = document.createElement('div');
    paneContainer.className = 'chart-indicator-pane';
    paneContainer.id = paneId;

    const paneLabel = document.createElement('div');
    paneLabel.className = 'chart-pane-label';
    paneLabel.textContent = type.toUpperCase();
    paneContainer.appendChild(paneLabel);

    const paneCanvas = document.createElement('div');
    paneCanvas.className = 'chart-pane-canvas';
    paneContainer.appendChild(paneCanvas);

    cell.appendChild(paneContainer);

    // Create separate chart
    const colors = _getChartColors();
    const paneChart = LightweightCharts.createChart(paneCanvas, {
        width: paneCanvas.clientWidth || cell.clientWidth,
        height: 100,
        layout: {
            background: { type: 'solid', color: colors.bg },
            textColor: colors.text,
            fontFamily: "'Inter', 'Segoe UI', sans-serif",
            fontSize: 10,
        },
        grid: {
            vertLines: { color: colors.grid },
            horzLines: { color: colors.grid },
        },
        rightPriceScale: {
            borderColor: colors.border,
            scaleMargins: { top: 0.1, bottom: 0.1 },
        },
        timeScale: {
            visible: false,  // hidden — synced with main chart
        },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    });

    indState.paneChart = paneChart;
    indState.paneContainer = paneContainer;

    const seriesData = data?.series || {};

    if (type === 'macd') {
        // MACD histogram
        const histData = seriesData.histogram;
        if (histData && histData.length > 0) {
            const histSeries = paneChart.addHistogramSeries({
                priceLineVisible: false,
                lastValueVisible: false,
            });
            histSeries.setData(_convertTimeValues(histData));
            indState.series.push(histSeries);
        }

        // MACD line
        const macdData = seriesData.macd;
        if (macdData && macdData.length > 0) {
            const macdSeries = paneChart.addLineSeries({
                color: settings.macdColor || '#2196F3',
                lineWidth: settings.lineWidth || 2,
                priceLineVisible: false,
                lastValueVisible: false,
            });
            macdSeries.setData(_convertTimeValues(macdData));
            indState.series.push(macdSeries);
        }

        // Signal line
        const sigData = seriesData.signal;
        if (sigData && sigData.length > 0) {
            const sigSeries = paneChart.addLineSeries({
                color: settings.signalColor || '#FF9800',
                lineWidth: settings.lineWidth || 2,
                priceLineVisible: false,
                lastValueVisible: false,
            });
            sigSeries.setData(_convertTimeValues(sigData));
            indState.series.push(sigSeries);
        }
    } else if (type === 'volume') {
        // Volume histogram bars
        const volData = seriesData.bars;
        if (volData && volData.length > 0) {
            const volSeries = paneChart.addHistogramSeries({
                priceLineVisible: false,
                lastValueVisible: false,
            });
            volSeries.setData(_convertTimeValues(volData));
            indState.series.push(volSeries);
        }

        // Volume MA line
        const maData = seriesData.ma;
        if (maData && maData.length > 0) {
            const maSeries = paneChart.addLineSeries({
                color: settings.maColor || '#FF9800',
                lineWidth: 1,
                priceLineVisible: false,
                lastValueVisible: false,
            });
            maSeries.setData(_convertTimeValues(maData));
            indState.series.push(maSeries);
        }
    } else if (type === 'rsi') {
        // RSI line
        const rsiData = seriesData.main;
        if (rsiData && rsiData.length > 0) {
            const rsiSeries = paneChart.addLineSeries({
                color: settings.color || '#E040FB',
                lineWidth: settings.lineWidth || 2,
                priceLineVisible: false,
                lastValueVisible: false,
            });
            rsiSeries.setData(_convertTimeValues(rsiData));
            indState.series.push(rsiSeries);

            // Overbought/Oversold levels
            const ob = settings.overbought || 70;
            const os = settings.oversold || 30;
            rsiSeries.createPriceLine({ price: ob, color: '#ef4444aa', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' });
            rsiSeries.createPriceLine({ price: os, color: '#22c55eaa', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' });
            rsiSeries.createPriceLine({ price: 50, color: '#64748b66', lineWidth: 1, lineStyle: 1, axisLabelVisible: false, title: '' });
        }

        // Scale range
        if (data?.scaleRange) {
            paneChart.priceScale('right').applyOptions({
                autoScale: false,
                scaleMargins: { top: 0.05, bottom: 0.05 },
            });
        }
    }

    // ── Sync time scales ──────────────────────────────────────
    _syncTimeScales(inst.chart, paneChart);

    // Resize existing charts to make room
    _resizeChartWithPanes(watchId);
}

/**
 * Sync the time scale of a separate pane with the main chart.
 */
function _syncTimeScales(mainChart, paneChart) {
    const mainTs = mainChart.timeScale();
    const paneTs = paneChart.timeScale();

    let syncing = false;

    mainTs.subscribeVisibleLogicalRangeChange((range) => {
        if (syncing) return;
        syncing = true;
        if (range) paneTs.setVisibleLogicalRange(range);
        syncing = false;
    });

    paneTs.subscribeVisibleLogicalRangeChange((range) => {
        if (syncing) return;
        syncing = true;
        if (range) mainTs.setVisibleLogicalRange(range);
        syncing = false;
    });
}

/**
 * Resize main chart and panes within a chart cell.
 */
function _resizeChartWithPanes(watchId) {
    const cell = document.getElementById(`watch-cell-${watchId}`);
    if (!cell) return;

    const inst = _chartInstances[watchId];
    if (!inst) return;

    const state = _indicatorState[watchId];
    const paneCount = state ? Object.values(state.indicators).filter(i => i.pane === 'separate').length : 0;

    const header = cell.querySelector('.chart-cell-header');
    const chipBar = cell.querySelector('.indicator-chips-bar');
    const body = cell.querySelector('.chart-cell-body');

    const headerH = header ? header.offsetHeight : 0;
    const chipH = chipBar ? chipBar.offsetHeight : 0;
    const cellH = cell.clientHeight;

    const paneHeight = 100; // fixed height per separate pane
    const totalPaneH = paneCount * paneHeight;
    const mainH = Math.max(100, cellH - headerH - chipH - totalPaneH);

    if (body) body.style.height = `${mainH}px`;

    try {
        inst.chart.applyOptions({
            width: body ? body.clientWidth : cell.clientWidth,
            height: mainH,
        });
    } catch (e) {}

    // Resize separate pane charts
    if (state) {
        for (const ind of Object.values(state.indicators)) {
            if (ind.paneChart && ind.paneContainer) {
                const canvas = ind.paneContainer.querySelector('.chart-pane-canvas');
                if (canvas) {
                    try {
                        ind.paneChart.applyOptions({
                            width: canvas.clientWidth || cell.clientWidth,
                            height: paneHeight - 20, // minus label
                        });
                    } catch (e) {}
                }
            }
        }
    }
}

/**
 * Remove indicator series from chart.
 */
function _removeIndicatorSeries(watchId, indId) {
    const state = _indicatorState[watchId];
    if (!state || !state.indicators[indId]) return;

    const ind = state.indicators[indId];
    const inst = _chartInstances[watchId];

    // Remove overlay series from main chart
    if (ind.pane === 'overlay' && inst) {
        for (const series of ind.series) {
            try { inst.chart.removeSeries(series); } catch (e) {}
        }
    }

    // Remove separate pane
    if (ind.paneChart) {
        try { ind.paneChart.remove(); } catch (e) {}
    }
    if (ind.paneContainer) {
        try { ind.paneContainer.remove(); } catch (e) {}
    }

    delete state.indicators[indId];
    _resizeChartWithPanes(watchId);
}


/**
 * Convert server time values to LightweightCharts format.
 * Reuses _toChartTs from dashboard.js.
 */
function _convertTimeValues(dataPoints) {
    if (!dataPoints || !Array.isArray(dataPoints)) return [];
    const result = [];
    const seen = new Set();

    for (const dp of dataPoints) {
        const ts = _toChartTs(dp.time);
        if (ts && !seen.has(ts)) {
            seen.add(ts);
            const point = { time: ts, value: dp.value };
            if (dp.color) point.color = dp.color;
            result.push(point);
        }
    }

    return result.sort((a, b) => a.time - b.time);
}


// ═══ LIVE UPDATE HANDLING ══════════════════════════════════════════

/**
 * Handle indicator data from bar_updates WS message.
 * Updates all active indicator series with new data.
 */
function handleIndicatorUpdates(watchId, indicators) {
    if (!indicators || typeof indicators !== 'object') return;

    const state = _indicatorState[watchId];
    if (!state) return;

    for (const [indId, indData] of Object.entries(indicators)) {
        const ind = state.indicators[indId];
        if (!ind) continue;

        const seriesData = indData.data?.series || {};

        if (ind.pane === 'overlay') {
            _updateOverlaySeries(ind, seriesData);
        } else {
            _updatePaneSeries(ind, seriesData);
        }
    }
}

function _updateOverlaySeries(ind, seriesData) {
    if (ind.type === 'bb') {
        const keys = ['middle', 'upper', 'lower'];
        for (let i = 0; i < keys.length && i < ind.series.length; i++) {
            const newData = seriesData[keys[i]];
            if (newData && newData.length > 0) {
                try { ind.series[i].setData(_convertTimeValues(newData)); } catch (e) {}
            }
        }
    } else {
        const newData = seriesData.main;
        if (newData && newData.length > 0 && ind.series[0]) {
            try { ind.series[0].setData(_convertTimeValues(newData)); } catch (e) {}
        }
    }
}

function _updatePaneSeries(ind, seriesData) {
    if (ind.type === 'macd') {
        const keys = ['histogram', 'macd', 'signal'];
        for (let i = 0; i < keys.length && i < ind.series.length; i++) {
            const newData = seriesData[keys[i]];
            if (newData && newData.length > 0) {
                try { ind.series[i].setData(_convertTimeValues(newData)); } catch (e) {}
            }
        }
    } else if (ind.type === 'volume') {
        if (seriesData.bars && seriesData.bars.length > 0 && ind.series[0]) {
            try { ind.series[0].setData(_convertTimeValues(seriesData.bars)); } catch (e) {}
        }
        if (seriesData.ma && seriesData.ma.length > 0 && ind.series[1]) {
            try { ind.series[1].setData(_convertTimeValues(seriesData.ma)); } catch (e) {}
        }
    } else if (ind.type === 'rsi') {
        if (seriesData.main && seriesData.main.length > 0 && ind.series[0]) {
            try { ind.series[0].setData(_convertTimeValues(seriesData.main)); } catch (e) {}
        }
    }
}


// ═══ INDICATOR SYNC (WS reconnect) ════════════════════════════════

function handleIndicatorSync(watchId, syncData) {
    const allData = syncData.indicators || {};
    for (const [indId, indInfo] of Object.entries(allData)) {
        renderIndicator(watchId, indId, indInfo.type, indInfo.settings, indInfo.data);
    }
}


// ═══ API CALLS ═════════════════════════════════════════════════════

async function apiAddIndicator(watchId, type, settings = {}) {
    try {
        const result = await api(`/api/watchlist/${watchId}/indicators`, 'POST', { type, settings });
        renderIndicator(watchId, result.indicator_id, result.type, result.settings, result.data);
        showToast(`${type.toUpperCase()} added`, 'success');
        return result;
    } catch (err) {
        showToast(`Failed to add indicator: ${err.message}`, 'error');
        return null;
    }
}

async function apiRemoveIndicator(watchId, indId) {
    try {
        await api(`/api/watchlist/${watchId}/indicators/${indId}`, 'DELETE');
        _removeIndicatorSeries(watchId, indId);
        renderIndicatorChips(watchId);
        showToast('Indicator removed', 'info');
    } catch (err) {
        showToast(`Failed to remove indicator: ${err.message}`, 'error');
    }
}

async function apiUpdateIndicator(watchId, indId, newSettings) {
    try {
        const result = await api(`/api/watchlist/${watchId}/indicators/${indId}`, 'PUT', { settings: newSettings });
        renderIndicator(watchId, result.indicator_id, result.type, result.settings, result.data);
        showToast('Indicator updated', 'success');
        return result;
    } catch (err) {
        showToast(`Failed to update indicator: ${err.message}`, 'error');
        return null;
    }
}


// ═══ INDICATOR MODAL UI ════════════════════════════════════════════

async function openIndicatorModal(watchId) {
    _indicatorModalWatchId = watchId;
    const catalog = await loadIndicatorCatalog();

    const modal = document.getElementById('indicator-modal');
    const list = document.getElementById('indicator-list');
    const search = document.getElementById('indicator-search');
    const tabs = document.querySelectorAll('.indicator-cat-tab');

    if (!modal || !list) return;

    // Reset search
    if (search) search.value = '';

    // Set active tab to "all"
    tabs.forEach(t => t.classList.remove('active'));
    const allTab = document.querySelector('.indicator-cat-tab[data-cat="all"]');
    if (allTab) allTab.classList.add('active');

    _renderIndicatorList(catalog);
    modal.classList.add('open');

    if (search) search.focus();
}

function closeIndicatorModal() {
    const modal = document.getElementById('indicator-modal');
    if (modal) modal.classList.remove('open');
    _indicatorModalWatchId = null;
}

function _renderIndicatorList(catalog, filter = '', category = 'all') {
    const list = document.getElementById('indicator-list');
    if (!list) return;

    const q = filter.toLowerCase().trim();
    const filtered = catalog.filter(ind => {
        const matchesSearch = !q ||
            ind.name.toLowerCase().includes(q) ||
            ind.fullName.toLowerCase().includes(q);
        const matchesCat = category === 'all' || ind.category === category;
        return matchesSearch && matchesCat;
    });

    if (filtered.length === 0) {
        list.innerHTML = '<div class="indicator-list-empty">No indicators match your search</div>';
        return;
    }

    list.innerHTML = filtered.map(ind => `
        <div class="indicator-list-item" onclick="handleIndicatorAdd('${ind.id}')">
            <div class="indicator-list-icon">${ind.icon}</div>
            <div class="indicator-list-info">
                <span class="indicator-list-name">${ind.name}</span>
                <span class="indicator-list-fullname">${ind.fullName}</span>
            </div>
            <span class="indicator-list-category badge badge-muted">${ind.category}</span>
            <button class="btn btn-primary btn-xs indicator-list-add">+ Add</button>
        </div>
    `).join('');
}

function handleIndicatorSearch() {
    const search = document.getElementById('indicator-search');
    const activeTab = document.querySelector('.indicator-cat-tab.active');
    const cat = activeTab ? activeTab.dataset.cat : 'all';
    _renderIndicatorList(_indicatorCatalog, search ? search.value : '', cat);
}

function handleIndicatorCategoryTab(tabEl) {
    document.querySelectorAll('.indicator-cat-tab').forEach(t => t.classList.remove('active'));
    tabEl.classList.add('active');

    const search = document.getElementById('indicator-search');
    _renderIndicatorList(_indicatorCatalog, search ? search.value : '', tabEl.dataset.cat);
}

async function handleIndicatorAdd(type) {
    if (_isGlobalIndicatorMode) {
        // Global mode: add indicator to ALL existing charts
        await addGlobalIndicator(type);
    } else if (_indicatorModalWatchId) {
        await apiAddIndicator(_indicatorModalWatchId, type);
    }
    // Don't close modal — allow adding multiple indicators like TradingView
}


// ═══ GLOBAL INDICATOR MANAGEMENT ═══════════════════════════════════

/**
 * Open indicator modal in global mode — adds indicators to ALL charts.
 */
async function openGlobalIndicatorModal() {
    _isGlobalIndicatorMode = true;
    _indicatorModalWatchId = null;
    const catalog = await loadIndicatorCatalog();

    const modal = document.getElementById('indicator-modal');
    const list = document.getElementById('indicator-list');
    const search = document.getElementById('indicator-search');
    const tabs = document.querySelectorAll('.indicator-cat-tab');

    if (!modal || !list) return;

    if (search) search.value = '';
    tabs.forEach(t => t.classList.remove('active'));
    const allTab = document.querySelector('.indicator-cat-tab[data-cat="all"]');
    if (allTab) allTab.classList.add('active');

    _renderIndicatorList(catalog);
    modal.classList.add('open');
    if (search) search.focus();
}

/**
 * Add an indicator globally to ALL existing charts.
 * Stores in _globalIndicators so new charts get it too.
 */
async function addGlobalIndicator(type) {
    const catalog = getCatalogEntry(type);
    const settings = catalog ? { ...catalog.defaultSettings } : {};

    // Track globally
    const globalId = `global-${type}-${Date.now()}`;
    _globalIndicators[globalId] = { type, settings };

    // Add to every existing chart
    const watchIds = Object.keys(_watchCharts);
    let successCount = 0;
    for (const wid of watchIds) {
        try {
            const result = await api(`/api/watchlist/${wid}/indicators`, 'POST', { type, settings });
            renderIndicator(wid, result.indicator_id, result.type, result.settings, result.data);

            // Store mapping: globalId → per-chart indId
            if (!_globalIndicators[globalId].chartMap) _globalIndicators[globalId].chartMap = {};
            _globalIndicators[globalId].chartMap[wid] = result.indicator_id;
            successCount++;
        } catch (e) {
            console.warn(`Failed to add ${type} to chart ${wid}:`, e);
        }
    }

    if (successCount > 0) {
        showToast(`${type.toUpperCase()} added to ${successCount} chart${successCount > 1 ? 's' : ''}`, 'success');
    }

    renderGlobalIndicatorChips();
}

/**
 * Apply all global indicators to a newly added chart.
 */
async function applyGlobalIndicatorsToChart(watchId) {
    for (const [globalId, gInd] of Object.entries(_globalIndicators)) {
        try {
            const result = await api(`/api/watchlist/${watchId}/indicators`, 'POST', {
                type: gInd.type,
                settings: gInd.settings,
            });
            renderIndicator(watchId, result.indicator_id, result.type, result.settings, result.data);

            if (!gInd.chartMap) gInd.chartMap = {};
            gInd.chartMap[watchId] = result.indicator_id;
        } catch (e) {
            console.warn(`Failed to apply global ${gInd.type} to new chart ${watchId}:`, e);
        }
    }
}

/**
 * Remove a global indicator from ALL charts.
 */
async function removeGlobalIndicator(globalId) {
    const gInd = _globalIndicators[globalId];
    if (!gInd) return;

    const chartMap = gInd.chartMap || {};
    for (const [wid, indId] of Object.entries(chartMap)) {
        try {
            await api(`/api/watchlist/${wid}/indicators/${indId}`, 'DELETE');
            _removeIndicatorSeries(wid, indId);
            renderIndicatorChips(wid);
        } catch (e) {}
    }

    delete _globalIndicators[globalId];
    renderGlobalIndicatorChips();
    showToast('Indicator removed from all charts', 'info');
}

/**
 * Open settings for a global indicator. Apply to all charts.
 */
function openGlobalIndicatorSettings(globalId) {
    const gInd = _globalIndicators[globalId];
    if (!gInd) return;

    const catalog = getCatalogEntry(gInd.type);
    if (!catalog) return;

    const panel = document.getElementById('indicator-settings-panel');
    if (!panel) return;

    // Mark as global edit
    panel.dataset.watchId = '';
    panel.dataset.indId = '';
    panel.dataset.globalId = globalId;

    const title = panel.querySelector('.ind-settings-title');
    if (title) title.textContent = `${catalog.fullName} Settings (All Charts)`;

    const body = panel.querySelector('.ind-settings-body');
    if (!body) return;

    body.innerHTML = catalog.settingsSchema.map(field => {
        const val = gInd.settings[field.key] ?? '';
        if (field.type === 'number') {
            return `<div class="ind-settings-row">
                <label class="ind-settings-label">${field.label}</label>
                <input type="number" class="ind-settings-input form-input"
                    data-key="${field.key}" value="${val}"
                    min="${field.min || ''}" max="${field.max || ''}" step="${field.step || 1}">
            </div>`;
        } else if (field.type === 'color') {
            return `<div class="ind-settings-row">
                <label class="ind-settings-label">${field.label}</label>
                <div class="ind-color-wrap">
                    <input type="color" class="ind-settings-color" data-key="${field.key}" value="${val}">
                    <span class="ind-color-hex">${val}</span>
                </div>
            </div>`;
        } else if (field.type === 'select') {
            const opts = (field.options || []).map(o =>
                `<option value="${o}" ${o === val ? 'selected' : ''}>${o}</option>`
            ).join('');
            return `<div class="ind-settings-row">
                <label class="ind-settings-label">${field.label}</label>
                <select class="ind-settings-input form-input form-select" data-key="${field.key}">${opts}</select>
            </div>`;
        }
        return '';
    }).join('');

    body.querySelectorAll('.ind-settings-color').forEach(inp => {
        inp.addEventListener('input', () => {
            const hex = inp.closest('.ind-color-wrap').querySelector('.ind-color-hex');
            if (hex) hex.textContent = inp.value;
        });
    });

    panel.classList.add('open');
}

/**
 * Render the global indicator chips bar in the Charts panel.
 */
function renderGlobalIndicatorChips() {
    const bar = document.getElementById('global-indicator-bar');
    if (!bar) return;

    const entries = Object.entries(_globalIndicators);
    if (entries.length === 0) {
        bar.style.display = 'none';
        bar.innerHTML = '';
        return;
    }

    bar.style.display = 'flex';
    bar.innerHTML = entries.map(([globalId, gInd]) => {
        const catalog = getCatalogEntry(gInd.type);
        const label = _getIndicatorLabel({ type: gInd.type, settings: gInd.settings });
        const color = gInd.settings.color || gInd.settings.macdColor || catalog?.defaultSettings?.color || '#2196F3';

        return `<div class="indicator-chip" data-globalid="${globalId}">
            <span class="indicator-chip-dot" style="background:${color};"></span>
            <span class="indicator-chip-label">${label}</span>
            <button class="indicator-chip-gear" onclick="event.stopPropagation(); openGlobalIndicatorSettings('${globalId}')" title="Settings">⚙</button>
            <button class="indicator-chip-remove" onclick="event.stopPropagation(); removeGlobalIndicator('${globalId}')" title="Remove">×</button>
        </div>`;
    }).join('');
}


// ═══ INDICATOR CHIPS BAR ═══════════════════════════════════════════

function renderIndicatorChips(watchId) {
    const chipBar = document.getElementById(`indicator-chips-${watchId}`);
    if (!chipBar) return;

    const state = _indicatorState[watchId];
    if (!state || Object.keys(state.indicators).length === 0) {
        chipBar.style.display = 'none';
        chipBar.innerHTML = '';
        _resizeChartWithPanes(watchId);
        return;
    }

    chipBar.style.display = 'flex';
    chipBar.innerHTML = Object.entries(state.indicators).map(([indId, ind]) => {
        const catalog = getCatalogEntry(ind.type);
        const label = _getIndicatorLabel(ind);
        const color = ind.settings.color || ind.settings.macdColor || catalog?.defaultSettings?.color || '#2196F3';

        return `<div class="indicator-chip" data-indid="${indId}">
            <span class="indicator-chip-dot" style="background:${color};"></span>
            <span class="indicator-chip-label">${label}</span>
            <button class="indicator-chip-gear" onclick="event.stopPropagation(); openIndicatorSettings('${watchId}', '${indId}')" title="Settings">⚙</button>
            <button class="indicator-chip-remove" onclick="event.stopPropagation(); apiRemoveIndicator('${watchId}', '${indId}')" title="Remove">×</button>
        </div>`;
    }).join('');

    _resizeChartWithPanes(watchId);
}

function _getIndicatorLabel(ind) {
    const type = ind.type.toUpperCase();
    const s = ind.settings;
    switch (ind.type) {
        case 'sma': return `SMA(${s.period || 20})`;
        case 'ema': return `EMA(${s.period || 20})`;
        case 'bb':  return `BB(${s.period || 20}, ${s.stdDev || 2})`;
        case 'vwap': return 'VWAP';
        case 'rsi': return `RSI(${s.period || 14})`;
        case 'macd': return `MACD(${s.fastPeriod || 12},${s.slowPeriod || 26},${s.signalPeriod || 9})`;
        case 'volume': return `Vol(${s.maPeriod || 20})`;
        default: return type;
    }
}


// ═══ INDICATOR SETTINGS PANEL ══════════════════════════════════════

function openIndicatorSettings(watchId, indId) {
    const state = _indicatorState[watchId];
    if (!state || !state.indicators[indId]) return;

    const ind = state.indicators[indId];
    const catalog = getCatalogEntry(ind.type);
    if (!catalog) return;

    const panel = document.getElementById('indicator-settings-panel');
    if (!panel) return;

    panel.dataset.watchId = watchId;
    panel.dataset.indId = indId;

    const title = panel.querySelector('.ind-settings-title');
    if (title) title.textContent = `${catalog.fullName} Settings`;

    const body = panel.querySelector('.ind-settings-body');
    if (!body) return;

    // Build settings form from schema
    body.innerHTML = catalog.settingsSchema.map(field => {
        const val = ind.settings[field.key] ?? '';
        if (field.type === 'number') {
            return `<div class="ind-settings-row">
                <label class="ind-settings-label">${field.label}</label>
                <input type="number" class="ind-settings-input form-input"
                    data-key="${field.key}" value="${val}"
                    min="${field.min || ''}" max="${field.max || ''}" step="${field.step || 1}">
            </div>`;
        } else if (field.type === 'color') {
            return `<div class="ind-settings-row">
                <label class="ind-settings-label">${field.label}</label>
                <div class="ind-color-wrap">
                    <input type="color" class="ind-settings-color" data-key="${field.key}" value="${val}">
                    <span class="ind-color-hex">${val}</span>
                </div>
            </div>`;
        } else if (field.type === 'select') {
            const opts = (field.options || []).map(o =>
                `<option value="${o}" ${o === val ? 'selected' : ''}>${o}</option>`
            ).join('');
            return `<div class="ind-settings-row">
                <label class="ind-settings-label">${field.label}</label>
                <select class="ind-settings-input form-input form-select" data-key="${field.key}">${opts}</select>
            </div>`;
        }
        return '';
    }).join('');

    // Color input live hex display
    body.querySelectorAll('.ind-settings-color').forEach(inp => {
        inp.addEventListener('input', () => {
            const hex = inp.closest('.ind-color-wrap').querySelector('.ind-color-hex');
            if (hex) hex.textContent = inp.value;
        });
    });

    // Position panel near the chip
    panel.classList.add('open');
}

function closeIndicatorSettings() {
    const panel = document.getElementById('indicator-settings-panel');
    if (panel) panel.classList.remove('open');
}

async function applyIndicatorSettings() {
    const panel = document.getElementById('indicator-settings-panel');
    if (!panel) return;

    const globalId = panel.dataset.globalId;

    // Global mode: apply to all charts
    if (globalId && _globalIndicators[globalId]) {
        const inputs = panel.querySelectorAll('[data-key]');
        const newSettings = {};
        inputs.forEach(inp => {
            const key = inp.dataset.key;
            if (inp.type === 'number') {
                newSettings[key] = inp.step && inp.step !== '1' ? parseFloat(inp.value) : parseInt(inp.value);
            } else {
                newSettings[key] = inp.value;
            }
        });

        _globalIndicators[globalId].settings = { ...newSettings };

        const chartMap = _globalIndicators[globalId].chartMap || {};
        for (const [wid, indId] of Object.entries(chartMap)) {
            try {
                const result = await api(`/api/watchlist/${wid}/indicators/${indId}`, 'PUT', { settings: newSettings });
                renderIndicator(wid, result.indicator_id, result.type, result.settings, result.data);
            } catch (e) {}
        }

        renderGlobalIndicatorChips();
        closeIndicatorSettings();
        showToast('Indicator updated on all charts', 'success');
        return;
    }

    // Per-chart mode (fallback)
    const watchId = panel.dataset.watchId;
    const indId = panel.dataset.indId;
    if (!watchId || !indId) return;

    const inputs = panel.querySelectorAll('[data-key]');
    const newSettings = {};
    inputs.forEach(inp => {
        const key = inp.dataset.key;
        if (inp.type === 'number') {
            newSettings[key] = inp.step && inp.step !== '1' ? parseFloat(inp.value) : parseInt(inp.value);
        } else {
            newSettings[key] = inp.value;
        }
    });

    await apiUpdateIndicator(watchId, indId, newSettings);
    closeIndicatorSettings();
}

async function removeFromSettings() {
    const panel = document.getElementById('indicator-settings-panel');
    if (!panel) return;

    const globalId = panel.dataset.globalId;

    // Global mode
    if (globalId && _globalIndicators[globalId]) {
        closeIndicatorSettings();
        await removeGlobalIndicator(globalId);
        return;
    }

    // Per-chart mode (fallback)
    const watchId = panel.dataset.watchId;
    const indId = panel.dataset.indId;
    if (!watchId || !indId) return;

    closeIndicatorSettings();
    await apiRemoveIndicator(watchId, indId);
}


// ═══ RESIZE ALL INDICATOR PANES ════════════════════════════════════

function resizeAllIndicatorPanes() {
    for (const watchId of Object.keys(_indicatorState)) {
        _resizeChartWithPanes(watchId);
    }
}


// ═══ EXPANDED CHART INDICATOR SUPPORT ══════════════════════════════════

/**
 * State for indicators rendered on the expanded chart modal.
 * Stores overlay series and separate-pane charts for cleanup + live updates.
 */
let _expandedIndicators = {
    overlaySeries: {},   // indId → [series, ...]
    paneCharts: {},      // indId → { chart, series[], container }
    watchId: null,
};

/**
 * Render all active indicators for a watchId onto the expanded chart.
 * Called from openExpandedWatch() after candle data is cloned.
 *
 * @param {string} watchId - The watch ID whose indicators to render
 * @param {object} expandedChart - The LightweightCharts chart instance in the modal
 * @param {object} expandedCandleSeries - The candle series on the expanded chart
 */
function renderIndicatorsOnExpandedChart(watchId, expandedChart, expandedCandleSeries) {
    // Clean up any previous expanded indicators
    cleanupExpandedIndicators();

    _expandedIndicators.watchId = watchId;

    const state = _indicatorState[watchId];
    if (!state) return;

    const modalBody = document.getElementById('chart-modal-container');

    for (const [indId, ind] of Object.entries(state.indicators)) {
        if (ind.pane === 'overlay') {
            // Clone overlay series data onto the expanded chart
            _renderExpandedOverlay(expandedChart, indId, ind);
        } else {
            // Create separate pane in the modal for pane indicators
            _renderExpandedPane(modalBody, expandedChart, indId, ind);
        }
    }
}

/**
 * Render an overlay indicator onto the expanded chart.
 */
function _renderExpandedOverlay(chart, indId, ind) {
    const seriesList = [];

    if (ind.type === 'bb') {
        // Clone each BB line
        for (let i = 0; i < ind.series.length; i++) {
            const srcSeries = ind.series[i];
            try {
                const data = srcSeries.data();
                const lineOpts = {
                    color: i === 0 ? (ind.settings.color || '#9C27B0') : (ind.settings.color || '#9C27B0') + '99',
                    lineWidth: i === 0 ? (ind.settings.lineWidth || 1) : 1,
                    lineStyle: i === 0 ? 0 : 2,
                    priceLineVisible: false,
                    lastValueVisible: false,
                    crosshairMarkerVisible: false,
                };
                const series = chart.addLineSeries(lineOpts);
                series.setData(data);
                seriesList.push(series);
            } catch (e) {}
        }
    } else {
        // Single line (SMA, EMA, VWAP)
        if (ind.series[0]) {
            try {
                const data = ind.series[0].data();
                const series = chart.addLineSeries({
                    color: ind.settings.color || '#2196F3',
                    lineWidth: ind.settings.lineWidth || 2,
                    priceLineVisible: false,
                    lastValueVisible: false,
                    crosshairMarkerVisible: false,
                });
                series.setData(data);
                seriesList.push(series);
            } catch (e) {}
        }
    }

    _expandedIndicators.overlaySeries[indId] = seriesList;
}

/**
 * Render a separate-pane indicator in the expanded chart modal.
 */
function _renderExpandedPane(modalBody, mainChart, indId, ind) {
    if (!modalBody) return;

    // Get the modal content wrapper (parent of modalBody)
    const modalContent = modalBody.closest('.chart-modal-content');
    if (!modalContent) return;

    const paneContainer = document.createElement('div');
    paneContainer.className = 'chart-indicator-pane expanded-indicator-pane';
    paneContainer.id = `expanded-ind-pane-${indId}`;

    const paneLabel = document.createElement('div');
    paneLabel.className = 'chart-pane-label';
    paneLabel.textContent = ind.type.toUpperCase();
    paneContainer.appendChild(paneLabel);

    const paneCanvas = document.createElement('div');
    paneCanvas.className = 'chart-pane-canvas';
    paneCanvas.style.height = '100px';
    paneContainer.appendChild(paneCanvas);

    // Insert pane after the modal body
    modalContent.appendChild(paneContainer);

    const colors = _getChartColors();
    const paneChart = LightweightCharts.createChart(paneCanvas, {
        width: paneCanvas.clientWidth || modalBody.clientWidth,
        height: 80,
        layout: {
            background: { type: 'solid', color: colors.bg },
            textColor: colors.text,
            fontFamily: "'Inter', 'Segoe UI', sans-serif",
            fontSize: 10,
        },
        grid: {
            vertLines: { color: colors.grid },
            horzLines: { color: colors.grid },
        },
        rightPriceScale: {
            borderColor: colors.border,
            scaleMargins: { top: 0.1, bottom: 0.1 },
        },
        timeScale: { visible: false },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    });

    const seriesList = [];

    // Clone data from the original pane indicator series
    if (ind.type === 'macd') {
        for (let i = 0; i < ind.series.length; i++) {
            try {
                const srcData = ind.series[i].data();
                let series;
                if (i === 0) {
                    // Histogram
                    series = paneChart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
                } else {
                    // MACD line or Signal line
                    const color = i === 1 ? (ind.settings.macdColor || '#2196F3') : (ind.settings.signalColor || '#FF9800');
                    series = paneChart.addLineSeries({
                        color, lineWidth: ind.settings.lineWidth || 2,
                        priceLineVisible: false, lastValueVisible: false,
                    });
                }
                series.setData(srcData);
                seriesList.push(series);
            } catch (e) {}
        }
    } else if (ind.type === 'volume') {
        for (let i = 0; i < ind.series.length; i++) {
            try {
                const srcData = ind.series[i].data();
                let series;
                if (i === 0) {
                    series = paneChart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
                } else {
                    series = paneChart.addLineSeries({
                        color: ind.settings.maColor || '#FF9800', lineWidth: 1,
                        priceLineVisible: false, lastValueVisible: false,
                    });
                }
                series.setData(srcData);
                seriesList.push(series);
            } catch (e) {}
        }
    } else if (ind.type === 'rsi') {
        if (ind.series[0]) {
            try {
                const srcData = ind.series[0].data();
                const rsiSeries = paneChart.addLineSeries({
                    color: ind.settings.color || '#E040FB',
                    lineWidth: ind.settings.lineWidth || 2,
                    priceLineVisible: false, lastValueVisible: false,
                });
                rsiSeries.setData(srcData);
                seriesList.push(rsiSeries);

                // Overbought/Oversold levels
                const ob = ind.settings.overbought || 70;
                const os = ind.settings.oversold || 30;
                rsiSeries.createPriceLine({ price: ob, color: '#ef4444aa', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' });
                rsiSeries.createPriceLine({ price: os, color: '#22c55eaa', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' });
                rsiSeries.createPriceLine({ price: 50, color: '#64748b66', lineWidth: 1, lineStyle: 1, axisLabelVisible: false, title: '' });
            } catch (e) {}
        }
    }

    // Sync time scales
    _syncTimeScales(mainChart, paneChart);

    _expandedIndicators.paneCharts[indId] = { chart: paneChart, series: seriesList, container: paneContainer };

    // Resize main chart body to accommodate pane
    _resizeExpandedChartWithPanes();
}

/**
 * Resize the expanded chart body to make room for indicator panes.
 */
function _resizeExpandedChartWithPanes() {
    const modalBody = document.getElementById('chart-modal-container');
    const modalContent = modalBody?.closest('.chart-modal-content');
    if (!modalBody || !modalContent) return;

    const panes = modalContent.querySelectorAll('.expanded-indicator-pane');
    const paneCount = panes.length;

    if (paneCount === 0) return;

    const header = modalContent.querySelector('.chart-modal-header');
    const headerH = header ? header.offsetHeight : 0;
    const totalH = modalContent.clientHeight;
    const paneH = 100;
    const totalPaneH = paneCount * paneH;
    const mainH = Math.max(200, totalH - headerH - totalPaneH);

    modalBody.style.height = `${mainH}px`;
    modalBody.style.flex = 'none';

    if (_expandedState.chart) {
        try {
            _expandedState.chart.applyOptions({
                width: modalBody.clientWidth,
                height: mainH,
            });
        } catch (e) {}
    }

    // Resize pane charts
    panes.forEach(pane => {
        const canvas = pane.querySelector('.chart-pane-canvas');
        if (canvas) {
            const indId = pane.id.replace('expanded-ind-pane-', '');
            const paneState = _expandedIndicators.paneCharts[indId];
            if (paneState?.chart) {
                try {
                    paneState.chart.applyOptions({
                        width: canvas.clientWidth || modalBody.clientWidth,
                        height: 80,
                    });
                } catch (e) {}
            }
        }
    });
}

/**
 * Clean up all expanded chart indicator series and pane charts.
 * Called from closeExpandedChart().
 */
function cleanupExpandedIndicators() {
    // Remove overlay series (chart will be destroyed anyway, but clean state)
    _expandedIndicators.overlaySeries = {};

    // Destroy pane charts and containers
    for (const [indId, pane] of Object.entries(_expandedIndicators.paneCharts)) {
        if (pane.chart) {
            try { pane.chart.remove(); } catch (e) {}
        }
        if (pane.container) {
            try { pane.container.remove(); } catch (e) {}
        }
    }
    _expandedIndicators.paneCharts = {};
    _expandedIndicators.watchId = null;
}

/**
 * Update expanded chart indicators with live data.
 * Called from handleIndicatorUpdates when the expanded chart is open for this watchId.
 */
function updateExpandedIndicators(watchId, indicators) {
    if (_expandedIndicators.watchId !== watchId) return;

    const state = _indicatorState[watchId];
    if (!state) return;

    for (const [indId, indData] of Object.entries(indicators)) {
        const ind = state.indicators[indId];
        if (!ind) continue;

        const seriesData = indData.data?.series || {};

        if (ind.pane === 'overlay') {
            // Update expanded overlay series
            const expSeries = _expandedIndicators.overlaySeries[indId];
            if (!expSeries) continue;

            if (ind.type === 'bb') {
                const keys = ['middle', 'upper', 'lower'];
                for (let i = 0; i < keys.length && i < expSeries.length; i++) {
                    const newData = seriesData[keys[i]];
                    if (newData && newData.length > 0) {
                        try { expSeries[i].setData(_convertTimeValues(newData)); } catch (e) {}
                    }
                }
            } else {
                const newData = seriesData.main;
                if (newData && newData.length > 0 && expSeries[0]) {
                    try { expSeries[0].setData(_convertTimeValues(newData)); } catch (e) {}
                }
            }
        } else {
            // Update expanded pane series
            const expPane = _expandedIndicators.paneCharts[indId];
            if (!expPane) continue;

            if (ind.type === 'macd') {
                const keys = ['histogram', 'macd', 'signal'];
                for (let i = 0; i < keys.length && i < expPane.series.length; i++) {
                    const newData = seriesData[keys[i]];
                    if (newData && newData.length > 0) {
                        try { expPane.series[i].setData(_convertTimeValues(newData)); } catch (e) {}
                    }
                }
            } else if (ind.type === 'volume') {
                if (seriesData.bars && seriesData.bars.length > 0 && expPane.series[0]) {
                    try { expPane.series[0].setData(_convertTimeValues(seriesData.bars)); } catch (e) {}
                }
                if (seriesData.ma && seriesData.ma.length > 0 && expPane.series[1]) {
                    try { expPane.series[1].setData(_convertTimeValues(seriesData.ma)); } catch (e) {}
                }
            } else if (ind.type === 'rsi') {
                if (seriesData.main && seriesData.main.length > 0 && expPane.series[0]) {
                    try { expPane.series[0].setData(_convertTimeValues(seriesData.main)); } catch (e) {}
                }
            }
        }
    }
}
