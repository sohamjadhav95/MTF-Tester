"""
connect_mt5.py
==============
Standalone helper to connect MetaTrader 5 using explicit credentials.
Includes structured logging to both console and a rotating log file.

Log file location: <project_root>/logs/mt5.log

Usage
-----
    from connect_mt5 import connect_mt5, disconnect_mt5

    connect_mt5()          # uses hardcoded credentials below
    disconnect_mt5()
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

# ── Logger setup ──────────────────────────────────────────────────────────────
_LOG_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "mt5.log")

os.makedirs(_LOG_DIR, exist_ok=True)

_fmt = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_file_handler = RotatingFileHandler(
    _LOG_FILE,
    maxBytes=2 * 1024 * 1024,   # 2 MB per file
    backupCount=5,               # keep last 5 rotated files
    encoding="utf-8",
)
_file_handler.setFormatter(_fmt)
_file_handler.setLevel(logging.DEBUG)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_fmt)
_console_handler.setLevel(logging.INFO)

log = logging.getLogger("MT5")
log.setLevel(logging.DEBUG)

if not log.handlers:               # avoid duplicate handlers on re-import
    log.addHandler(_file_handler)
    log.addHandler(_console_handler)

# ─────────────────────────────────────────────────────────────────────────────


def _get_mt5():
    """Lazy import of MetaTrader5 so the module is usable even when MT5
    is not installed (errors are raised only on actual connection attempt)."""
    try:
        import MetaTrader5 as mt5
        return mt5
    except ImportError as exc:
        raise RuntimeError(
            "MetaTrader5 package is not installed. "
            "Run: pip install MetaTrader5"
        ) from exc


def connect_mt5() -> dict:
    """
    Initialize the MT5 terminal and log in with the hardcoded credentials.

    Returns
    -------
    dict with keys:
        success (bool)  - True on successful login
        account (dict)  - account details (only present on success)
        error   (str)   - human-readable error message (only present on failure)
    """
    log.info("Attempting to connect to MT5 terminal...")

    # ── Step 1: Import MT5 library ────────────────────────────────────────────
    try:
        mt5 = _get_mt5()
        log.debug("MetaTrader5 library imported successfully.")
    except RuntimeError as exc:
        log.error("Failed to import MetaTrader5: %s", exc)
        return {"success": False, "error": str(exc)}

    # ── Step 2: Initialize terminal ───────────────────────────────────────────
    log.debug("Calling mt5.initialize()...")
    if not mt5.initialize():
        err = mt5.last_error()
        log.error("MT5 terminal initialization failed. Error: %s", err)
        return {
            "success": False,
            "error": (
                f"MT5 terminal initialization failed (error {err}). "
                "Make sure the MetaTrader 5 desktop application is running."
            ),
        }
    log.info("MT5 terminal initialized successfully.")

    # ── Step 3: Login ──────────────────────────────────────────────────────────
    LOGIN    = 415559990
    PASSWORD = "Soham@987"
    SERVER   = "Exness-MT5Trial14"

    log.debug("Logging in | login=%s | server=%s", LOGIN, SERVER)
    authorized = mt5.login(login=LOGIN, password=PASSWORD, server=SERVER)
    if not authorized:
        error = mt5.last_error()
        log.error(
            "MT5 login failed | login=%s | server=%s | error=%s",
            LOGIN, SERVER, error
        )
        mt5.shutdown()
        return {
            "success": False,
            "error": f"MT5 login failed (error {error}). Check your login ID, password, and server name.",
        }
    log.info("Login successful | login=%s | server=%s", LOGIN, SERVER)

    # ── Step 4: Read account info ──────────────────────────────────────────────
    log.debug("Fetching account info...")
    info = mt5.account_info()
    if info is None:
        log.error("Login succeeded but mt5.account_info() returned None.")
        mt5.shutdown()
        return {
            "success": False,
            "error": "Login succeeded but failed to retrieve account info.",
        }

    account = {
        "login":    info.login,
        "name":     info.name,
        "server":   info.server,
        "company":  info.company,
        "currency": info.currency,
        "balance":  info.balance,
        "equity":   info.equity,
        "leverage": info.leverage,
    }

    log.info(
        "Connected | name=%s | server=%s | balance=%.2f %s | equity=%.2f | leverage=1:%s",
        account["name"], account["server"],
        account["balance"], account["currency"],
        account["equity"], account["leverage"],
    )
    return {"success": True, "account": account}


def disconnect_mt5() -> None:
    """Cleanly shut down the MT5 connection."""
    try:
        mt5 = _get_mt5()
        mt5.shutdown()
        log.info("MT5 disconnected.")
    except RuntimeError:
        pass  # MT5 was never imported - nothing to shut down
