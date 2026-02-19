# Trading Strategy Tester — Walkthrough

## What Was Built

A full-featured trading strategy backtesting application with:

- **Python backend** (FastAPI) — MT5 data connection, bar-by-bar backtesting engine, modular strategy system, 25+ performance metrics
- **React frontend** (Vite) — Dark trading-themed UI with symbol search, dynamic strategy settings, equity chart, and sortable trade log

---

## Project Structure

```
Strategy-Tester/
├── backend/
│   ├── main.py                    ← FastAPI app (all REST endpoints)
│   ├── config.py                  ← Timeframe maps, defaults, CORS
│   ├── requirements.txt
│   ├── mt5/connection.py          ← MT5 login/logout, symbols, info
│   ├── data/provider.py           ← Fetch OHLCV from MT5
│   ├── engine/
│   │   ├── backtester.py          ← Bar-by-bar engine (core)
│   │   └── models.py              ← Trade, Position, BacktestResult
│   ├── strategies/                ← DROP YOUR STRATEGIES HERE
│   │   ├── base.py                ← BaseStrategy abstract class
│   │   ├── loader.py              ← Auto-discovers strategy files
│   │   └── ema_crossover.py       ← Example template
│   └── analytics/metrics.py       ← 25+ performance metrics
└── frontend/
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.jsx / App.css      ← Main layout
        ├── index.css              ← Design system tokens
        ├── api/client.js          ← Backend API wrapper
        └── components/
            ├── MT5Login.jsx       ← MT5 connection form
            ├── AssetConfig.jsx    ← Symbol/timeframe/strategy config
            ├── ResultsDashboard.jsx ← Metrics cards
            ├── EquityChart.jsx    ← Lightweight Charts equity curve
            └── TradeLog.jsx       ← Sortable trade table
```

---

## How to Run

### 1. Backend
```bash
cd backend
pip install -r requirements.txt
py -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Frontend
```bash
cd frontend
npm install
npm run dev
```

> [!IMPORTANT]
> **Node.js** must be installed for the frontend. Install from [nodejs.org](https://nodejs.org). After installing, run `npm install` then `npm run dev`.

Open **http://localhost:5173** in your browser.

---

## How to Create a Strategy

1. Create a new [.py](file:///e:/Projects/Master%20Projects%20%28Core%29/Strategy-Tester/backend/main.py) file in `backend/strategies/`
2. Extend `BaseStrategy` and implement `on_bar()`
3. The app auto-discovers it — no registration needed

See [ema_crossover.py](file:///e:/Projects/Master%20Projects%20(Core)/Strategy-Tester/backend/strategies/ema_crossover.py) as a reference.

---

## Verification Results

| Check | Result |
|-------|--------|
| Backend starts | ✅ Uvicorn on port 8000 |
| Strategy loader | ✅ Found 1 strategy: "EMA Crossover" |
| `GET /` | ✅ Returns API info |
| `GET /api/strategies` | ✅ Returns EMA Crossover with full settings schema |
| `GET /api/timeframes` | ✅ Returns all 9 timeframes |
| EMA Crossover settings | ✅ fast_period, slow_period, source, trade_direction |

MT5 data endpoints require a live MT5 terminal connection to test (user must enter their credentials).
