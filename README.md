# Strategy Tester — Professional Backtesting Application

A high-performance trading strategy backtester built with **Python (FastAPI)** and **MetaTrader 5**. Includes a bar-by-bar execution engine, modular strategy system, and a modern dark-themed web interface.

> [!NOTE]
> **Zero Dependencies:** The frontend is pure HTML/JS served by Python. No Node.js or npm required.

---

## 🚀 Key Features

### Backend (Python)
- **MT5 Integration**: Connects directly to MetaTrader 5 terminal for historical data.
- **Bar-by-Bar Engine**: Simulates realistic trading (no look-ahead bias) with spread accounting.
- **Modular Strategies**: Write strategies as simple Python classes. Auto-discovered by the app.
- **Analytics**: Calculates 25+ metrics (Sharpe, Profit Factor, Drawdown, etc.).

### Frontend (Web UI)
- **Modern Interface**: Professional dark trading theme.
- **Interactive Charts**: Equity curve and balance lines using Lightweight Charts.
- **Asset Config**: Symbol search, timeframe selection (M1–MN1), and date range pickers.
- **Dynamic Settings**: Strategy settings (inputs) are automatically generated in the UI based on your Python code.
- **Detailed Logs**: Sortable trade log with P&L, entry/exit times, and spread costs.

---

## 🛠️ Installation

### Prerequisites
1. **Python 3.10+**
2. **MetaTrader 5 Terminal** (installed and logged in)

### Setup
1. Clone or download the repository.
2. Install Python dependencies:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

---

## ▶️ How to Run

**Option 1: One-Click (Recommended)**
Double-click the `start_app.bat` file in the project root.
- Starts the server.
- Automatically opens **http://localhost:8000** in your browser.

**Option 2: Manual Terminal**
```bash
cd backend
py -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
Then visit **http://localhost:8000**.

---

## 📂 Project Structure

```
Strategy-Tester/
├── start_app.bat                   ← Launcher script
├── backend/
│   ├── main.py                     ← FastAPI app & Static File Server
│   ├── config.py                   ← Application config
│   ├── requirements.txt            ← Python dependencies
│   ├── mt5/                        ← MetaTrader 5 connection module
│   ├── data/                       ← Data fetching & processing
│   ├── engine/                     ← Core backtesting engine
│   ├── strategies/                 ← STRATEGY FOLDER (Put .py files here)
│   │   ├── base.py                 ← Base strategy class
│   │   ├── loader.py               ← Strategy auto-loader
│   │   └── ema_crossover.py        ← Example strategy
│   └── analytics/                  ← Performance metrics calculation
└── frontend/                       ← Pure HTML/JS Frontend
    ├── index.html                  ← Main UI
    ├── styles.css                  ← Styling (Dark Theme)
    └── app.js                      ← Frontend Logic (Vanilla JS)
```

---

## 📈 Creating Custom Strategies

1. Create a **new Python file** in `backend/strategies/` (e.g., `my_strategy.py`).
2. Create a class that inherits from `BaseStrategy`.
3. Implement the `on_bar` method.
4. Define your settings in `settings_schema` (optional).

**Example:**
```python
from .base import BaseStrategy
from engine.models import Signal

class MyStrategy(BaseStrategy):
    name = "Simple MA Cross"
    description = "Moving Average Crossover Strategy"
    
    # Settings appear automatically in the UI
    settings_schema = {
        "fast_period": {"type": "int", "default": 10, "min": 1, "max": 100},
        "slow_period": {"type": "int", "default": 20, "min": 1, "max": 200},
    }

    def on_bar(self, bar, context):
        # Access indicators or logic here
        # Return Signal.BUY, Signal.SELL, or Signal.NONE
        pass
```

The application will **automatically detect** your new strategy properly on the next reload.

---

## 📊 Analytics & Metrics

The dashboard provides comprehensive performance analysis:
- **Net P&L** ($ and pips)
- **Win Rate** & Profit Factor
- **Max Drawdown** (% and $)
- **Sharpe & Sortino Ratios**
- **Trade Durations** & Spread Costs
- **Equity & Balance Curve**
