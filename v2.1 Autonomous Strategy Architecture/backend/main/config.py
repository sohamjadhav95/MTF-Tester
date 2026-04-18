"""
Application Configuration
=========================
Single source of truth for all constants and environment variables.
Load this module first. Never hardcode values anywhere else.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.parent   # project root
BACKEND_DIR = BASE_DIR / "backend"
DATABASE_DIR = BASE_DIR / "database"
LOGS_DIR = BASE_DIR / "logs"
FRONTEND_DIR = BASE_DIR / "frontend"
STRATEGIES_DIR = BACKEND_DIR / "strategies"

DATABASE_PATH = DATABASE_DIR / "mtf_tester.db"

# Ensure directories exist
DATABASE_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# ── Server ─────────────────────────────────────────────────────────────
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", 8000))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Config vars removed inline

# ── Trading Safety ─────────────────────────────────────────────────────
MAX_LOT_SIZE = float(os.getenv("MAX_LOT_SIZE", 10.0))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", 20))
DEFAULT_RISK_THRESHOLD_PCT = float(os.getenv("DEFAULT_RISK_THRESHOLD_PCT", 5.0))

# ── LLM (Phase 2) ──────────────────────────────────────────────────────
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-opus-4-6-20251101")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", 4000))

# ── MT5 Connection ─────────────────────────────────────────────────────
MT5_SERVER = os.getenv("MT5_SERVER", "")
MT5_LOGIN = os.getenv("MT5_LOGIN", "")
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")


# ── Backtesting Defaults ───────────────────────────────────────────────
DEFAULT_INITIAL_BALANCE = 10000.0
DEFAULT_LOT_SIZE = 0.1
DEFAULT_COMMISSION_PER_LOT = 0.0

TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1", "MN1": "TIMEFRAME_MN1",
}

TIMEFRAME_LABELS = {
    "M1": "1 Min", "M5": "5 Min", "M15": "15 Min", "M30": "30 Min",
    "H1": "1 Hour", "H4": "4 Hours", "D1": "Daily", "W1": "Weekly", "MN1": "Monthly",
}

BARS_PER_YEAR = {
    "M1": 525600, "M5": 105120, "M15": 35040, "M30": 17520,
    "H1": 8760, "H4": 2190, "D1": 252, "W1": 52, "MN1": 12,
}
