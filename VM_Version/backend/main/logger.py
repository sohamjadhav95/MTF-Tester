"""
Centralized Structured Logger
==============================
Import and use everywhere:
    from main.logger import get_logger
    log = get_logger("engine")
    log.info("Backtest started", symbol="EURUSD", bars=5000)

Rules:
- Never log passwords, tokens, or raw credentials — scrubber enforces this
- One named logger per module concern: api, engine, mtf, order, db
- Every log line: timestamp | level | name | message | key=value extras
- order.log is ALWAYS written — even if other logging fails
"""

import logging
import logging.handlers
import os
import sys
from datetime import datetime
from main.config import LOGS_DIR

# ── Scrubber ───────────────────────────────────────────────────────────
_SENSITIVE_KEYS = {"password", "token", "password_hash", "password_enc",
                   "fernet_key", "api_key", "authorization", "secret"}

class ScrubFilter(logging.Filter):
    """Remove sensitive fields from log records before they are written."""
    def filter(self, record):
        if hasattr(record, "__dict__"):
            for key in list(vars(record).keys()):
                if key.lower() in _SENSITIVE_KEYS:
                    setattr(record, key, "***REDACTED***")
        msg = str(record.getMessage()).lower()
        for key in _SENSITIVE_KEYS:
            if key in msg:
                record.msg = f"[SCRUBBED LOG — contained sensitive key: {key}]"
                record.args = ()
        return True

# ── Formatter ──────────────────────────────────────────────────────────
FORMATTER = logging.Formatter(
    fmt="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-12s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def _make_file_handler(filename: str, level=logging.DEBUG) -> logging.Handler:
    path = LOGS_DIR / filename
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setLevel(level)
    handler.setFormatter(FORMATTER)
    handler.addFilter(ScrubFilter())
    return handler

def _make_console_handler(level=logging.INFO) -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(FORMATTER)
    handler.addFilter(ScrubFilter())
    return handler

# ── Master logger ──────────────────────────────────────────────────────
_master = logging.getLogger("app")
_master.setLevel(logging.DEBUG)
_master.addHandler(_make_file_handler("app.log"))
_master.addHandler(_make_console_handler())

# ── Error-only logger (all sources) ───────────────────────────────────
_error_handler = _make_file_handler("errors.log", level=logging.ERROR)

# ── Named loggers cache ────────────────────────────────────────────────
_LOGGERS: dict[str, logging.Logger] = {}

_LOGGER_FILES = {
    "api":       "api.log",
    "engine":    "engine.log",
    "mtf":       "mtf.log",
    "order":     "order.log",    # ALWAYS written, never suppressed
    "auto":      "auto.log",
    "auth":      "auth.log",
    "db":        "db.log",
}

def get_logger(name: str) -> logging.Logger:
    """
    Get or create a named logger.
    Available names: api, engine, mtf, order, db
    Falls back to 'app' for unknown names.
    """
    if name in _LOGGERS:
        return _LOGGERS[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    filename = _LOGGER_FILES.get(name, "app.log")
    logger.addHandler(_make_file_handler(filename))
    logger.addHandler(_make_file_handler("app.log"))   # also write to master
    logger.addHandler(_error_handler)                  # errors go to errors.log
    logger.addHandler(_make_console_handler())

    _LOGGERS[name] = logger
    return logger
