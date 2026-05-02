"""
Database Module
===============
SQLite persistence. Schema is single-user.

SECURITY RULES:
- order_audit is append-only: no UPDATE or DELETE ever runs on it
- All operations use parameterized queries — no string formatting in SQL
"""

import sqlite3
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path

from main.config import DATABASE_PATH
from main.logger import get_logger

log = get_logger("db")

# ── Connection ─────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DATABASE_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

# ── Schema Initialization ──────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS order_audit (
    id           TEXT PRIMARY KEY,
    timestamp    TEXT NOT NULL,
    action       TEXT NOT NULL,
    symbol       TEXT,
    direction    TEXT,
    volume       REAL,
    price        REAL,
    sl           REAL,
    tp           REAL,
    result_json  TEXT
);
"""

def init_db():
    """Create all tables and indexes. Safe to call multiple times."""
    conn = _get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        log.info("Database initialized successfully")
    except Exception as e:
        log.error(f"Database initialization failed: {e}")
        raise
    finally:
        conn.close()

# ── Helpers ────────────────────────────────────────────────────────────
def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def _new_id() -> str:
    return str(uuid.uuid4())

# ── Order Audit ────────────────────────────────────────────────────────
def write_order_audit(action: str, symbol: str = None,
                      direction: str = None, volume: float = None,
                      price: float = None, sl: float = None, tp: float = None,
                      result: dict = None):
    """
    Append-only order audit log.
    NEVER update or delete from this table.
    Called for every order attempt — success or failure.
    """
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO order_audit
               (id, timestamp, action, symbol, direction, volume, price,
                sl, tp, result_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (_new_id(), _now_utc(), action, symbol, direction, volume,
             price, sl, tp, json.dumps(result) if result else None)
        )
        conn.commit()
    except Exception as e:
        # Order audit must NEVER fail silently — log to stderr directly
        import sys
        print(f"[CRITICAL] Order audit write failed: {e}", file=sys.stderr)
    finally:
        conn.close()


def get_order_history(limit: int = 100) -> list[dict]:
    """Read order audit log. Uses the standard _get_conn() pattern."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM order_audit ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
