import sys
path = 'e:/Projects/Master Projects (Core)/MTF-Tester/v1.1 MTF Demo/frontend/app.js'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = lines[:518] # Keep up to line 518

new_code = """
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
      await api('/api/mtf/start', {
        method: 'POST',
        body: JSON.stringify({
          symbol: c.symbol,
          timeframes: c.timeframes,
          strategy: c.strategy,
          settings: c.settings || {}
        }),
      });
      
      state.scannerActive = true;
      const btn = document.getElementById('btn-run');
      btn.innerHTML = '<span class="run-icon">⏹</span> Stop MTF Scanner';
      btn.classList.add('active');
      btn.style.background = 'var(--loss-red)';
      btn.style.boxShadow = 'none';
      
      initScannerUI();
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

function initScannerUI() {
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
         <span class="mtf-chart-title">${state.config.symbol}</span>
         <span class="mtf-chart-tf">${tf}</span>
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
    
    mtfCharts[tf] = { wrapEl: wrap, chartInst: chart, candleSeries: candleSeries };
  });
  
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
    const wsUrl = `${protocol}//${window.location.host}/ws/stream`;
    wsConnection = new WebSocket(wsUrl);
    
    wsConnection.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === 'bar_updates') {
            msg.data.forEach(update => {
                const tf = update.timeframe;
                if (mtfCharts[tf]) {
                    mtfCharts[tf].candleSeries.update({
                        time: toTs(update.bar.time),
                        open: update.bar.open,
                        high: update.bar.high,
                        low: update.bar.low,
                        close: update.bar.close
                    });
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
    }
    
    // 2. Add to report card
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
"""

new_lines.append(new_code)

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Updated app.js successfully!")
