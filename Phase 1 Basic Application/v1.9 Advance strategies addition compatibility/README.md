# MTF Tester

**Production-grade algorithmic trading platform** for MetaTrader 5 (Forex) and Binance (Crypto).

## Features

- 🔐 **Multi-user authentication** — bcrypt password hashing, session tokens
- 📊 **Bar-by-bar backtesting** — zero look-ahead bias, SL/TP support, comprehensive metrics
- 🔍 **Multi-timeframe scanner** — live signal scanning across multiple timeframes simultaneously
- 💰 **Manual order placement** — market/pending orders with SL/TP, confirmation dialogs
- 🛡️ **Risk management** — configurable drawdown threshold with auto-close capability
- 📝 **Full audit trail** — every order attempt logged to append-only audit table
- 🤖 **Strategy Builder** — AI-powered strategy creation (Phase 2)

## Quick Start

1. Install dependencies: `pip install -r requirements.txt`
2. Install MetaTrader5 (Windows): `pip install MetaTrader5`
3. Start: `cd backend && python -m uvicorn main.app:app --host 127.0.0.1 --port 8000`
4. Open `http://127.0.0.1:8000/auth` to create an account

Or just double-click `start.bat`

## Architecture

```
mtf-tester/
├── backend/
│   ├── main/           # App core: config, auth, DB, middleware, models
│   ├── data_collector/  # MT5 + Binance data providers
│   ├── chart/          # Backtesting engine, MTF scanner, metrics
│   ├── order/          # Order placement, validation, risk management
│   ├── strategies/     # Trading strategies (auto-discovered)
│   └── strategy_builder/ # Phase 2 stub
├── frontend/           # Vanilla JS dark-themed trading UI
├── database/           # SQLite persistence
└── logs/              # Rotating log files
```

## Security

- Passwords: bcrypt (cost factor 12)
- MT5 credentials: stored per-session (encryption disabled for testing)
- Session tokens: 32-byte random, SHA-256 hashed in DB
- All API routes: Bearer token authentication
- Order audit: append-only (no UPDATE/DELETE)
- Sensitive data: scrubbed from all log output

## Included Strategies

| Strategy | Description |
|----------|-------------|
| EMA Crossover | BUY when fast EMA crosses above slow EMA |
| Supertrend | Classic TradingView Supertrend indicator |
| Reverse EMA Crossover | Counter-trend version of EMA Crossover |

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, SQLite
- **Frontend**: Vanilla HTML/CSS/JS (no framework)
- **Providers**: MetaTrader5 API, Binance Futures
