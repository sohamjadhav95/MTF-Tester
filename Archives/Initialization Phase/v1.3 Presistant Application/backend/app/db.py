"""
Database Module — SQLite Persistence
=====================================
Stores MT5 login credentials and session state in a local SQLite database.
"""

import sqlite3
import os
import json
from typing import Optional, Dict, Any

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mtf_tester.db")

_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS credentials (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            server TEXT NOT NULL,
            login INTEGER NOT NULL,
            password TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            config_json TEXT NOT NULL
        )
    """)
    conn.commit()


# ─── Credentials ─────────────────────────────────────────────

def save_credentials(server: str, login: int, password: str):
    """Save MT5 credentials (upsert single row)."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO credentials (id, server, login, password) VALUES (1, ?, ?, ?)",
        (server, login, password),
    )
    conn.commit()


def load_credentials() -> Optional[Dict[str, Any]]:
    """Load saved MT5 credentials, or None if not saved."""
    conn = _get_conn()
    row = conn.execute("SELECT server, login, password FROM credentials WHERE id = 1").fetchone()
    if row is None:
        return None
    return {"server": row["server"], "login": row["login"], "password": row["password"]}


def clear_credentials():
    """Remove saved credentials."""
    conn = _get_conn()
    conn.execute("DELETE FROM credentials WHERE id = 1")
    conn.commit()


# ─── Session State ───────────────────────────────────────────

def save_session(config: Dict[str, Any]):
    """Save session configuration as JSON."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO session_state (id, config_json) VALUES (1, ?)",
        (json.dumps(config),),
    )
    conn.commit()


def load_session() -> Optional[Dict[str, Any]]:
    """Load saved session configuration, or None."""
    conn = _get_conn()
    row = conn.execute("SELECT config_json FROM session_state WHERE id = 1").fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["config_json"])
    except (json.JSONDecodeError, TypeError):
        return None
