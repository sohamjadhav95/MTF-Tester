# MTF Tester

**Production-grade algorithmic trading platform** for MetaTrader 5 (Forex) and Binance (Crypto). 

MTF Tester is a highly responsive, single-user desktop application designed around a core philosophy: **Candles + Signals**. It provides a robust environment to build, backtest, and live-trade multi-timeframe strategies with zero look-ahead bias.

## Core Features

- 📊 **Zero-Bias Backtesting:** True bar-by-bar historical backtesting ensuring accurate performance metrics.
- 🔍 **Live Multi-Timeframe Scanner:** Run multiple strategies simultaneously across different symbols and timeframes.
- ⚡ **Automated Trading:** True "hands-free" execution with position de-duplication, SL/TP management, and orphan recovery.
- 💰 **Manual Order Placement:** Quickly execute market orders with predefined SL/TP and visual confirmations.
- 🛡️ **Risk Management:** Configurable drawdown threshold with a global auto-close capability and an emergency kill-switch.
- 🤖 **AI Strategy Builder:** Built-in prompt generator to quickly scaffold new strategies using LLMs.

## Quick Start

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Install MetaTrader5 (Windows only):**
   ```bash
   pip install MetaTrader5
   ```
3. **Run the Application:**
   Just double-click `start.bat`. This will automatically pull the latest code, activate your virtual environment, and start the local server.
   
   *Alternatively, start manually:*
   ```bash
   cd backend
   python -m uvicorn main.app:app --host 0.0.0.0 --port 5000
   ```
4. **Open the Dashboard:**
   Navigate to `http://0.0.0.0:5000/` (or VM's public IP at port 5000) in your browser.

## Architecture & Tech Stack

MTF Tester uses a lightweight, dependency-free frontend backed by a robust Python engine.

- **Frontend:** Vanilla HTML/CSS/JS with a dark-themed, responsive trading UI (No frameworks used).
- **Backend:** Python 3.11+, FastAPI for API/WebSockets, SQLite for persistence.
- **Providers:** MetaTrader 5 API (Local Terminal), Binance Futures API.

```
mtf-tester/
├── backend/
│   ├── main/           # App core: config, auth, DB, middleware, models
│   ├── data_collector/ # MT5 + Binance data providers
│   ├── chart/          # Backtesting engine, MTF scanner, metrics
│   ├── order/          # Order placement, validation, risk management
│   └── strategies/     # Trading strategies (auto-discovered)
├── frontend/           # Vanilla JS dark-themed trading UI
├── database/           # SQLite persistence
└── logs/               # Rotating log files
```

## Documentation

- 📖 [**User Guide**](User_Guide.md): Comprehensive instructions on using the application, setting up scanners, and managing risk.
- 🛠️ [**Strategy Format Guide**](backend/strategies/STRATEGY_FORMAT.md): Detailed API reference and boilerplate for writing `.py` strategies.
- 🧪 [**Test Runbook**](backend/strategies/TEST_RUNBOOK.md): End-to-end verification guide for testing system stability.
