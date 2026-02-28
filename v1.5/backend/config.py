"""
Application configuration settings.
"""

# Default backtest settings
DEFAULT_INITIAL_BALANCE = 10000.0
DEFAULT_LOT_SIZE = 0.1
DEFAULT_COMMISSION_PER_LOT = 0.0  # In account currency, per side

# MT5 Timeframe mapping
TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
    "W1": "TIMEFRAME_W1",
    "MN1": "TIMEFRAME_MN1",
}

# Timeframe display names
TIMEFRAME_LABELS = {
    "M1": "1 Minute",
    "M5": "5 Minutes",
    "M15": "15 Minutes",
    "M30": "30 Minutes",
    "H1": "1 Hour",
    "H4": "4 Hours",
    "D1": "Daily",
    "W1": "Weekly",
    "MN1": "Monthly",
}

# Bars per year approximation for Sharpe ratio annualization
BARS_PER_YEAR = {
    "M1": 525600,
    "M5": 105120,
    "M15": 35040,
    "M30": 17520,
    "H1": 8760,
    "H4": 2190,
    "D1": 252,
    "W1": 52,
    "MN1": 12,
}

# CORS settings
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]
