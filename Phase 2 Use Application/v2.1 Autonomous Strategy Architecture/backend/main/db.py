"""
Database Module
===============
SQLite persistence. All DB operations live here — nowhere else.
Schema is multi-user from day one.

SECURITY RULES:
- Never store plaintext passwords — bcrypt hash only
- Never store plaintext MT5 passwords — Fernet encrypted only
- Never store raw session tokens — SHA-256 hash only
- order_audit is append-only: no UPDATE or DELETE ever runs on it
- All operations use parameterized queries — no string formatting in SQL
"""

import sqlite3
import uuid
import json
import hashlib
import time
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

from main.config import DATABASE_PATH
from main.logger import get_logger

log = get_logger("db")

# ── Session Cache (in-memory, TTL-based) ───────────────────────────────
# Each entry: token_hash → (session_dict | None, expires_at_monotonic)
# Avoids a full SQLite round-trip on every authenticated request.
_SESSION_CACHE: dict = {}
_SESSION_CACHE_TTL = 60  # seconds — re-validate from DB after this long

# ── Connection ─────────────────────────────────────────────────────────
# check_same_thread=False is safe here because we use per-operation
# connections with explicit commit/close, not a shared persistent connection.

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DATABASE_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

# ── Schema Initialization ──────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,
    username     TEXT UNIQUE NOT NULL,
    email        TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_login   TEXT,
    is_active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash   TEXT NOT NULL UNIQUE,
    last_panel   TEXT DEFAULT 'dashboard',
    last_symbol  TEXT,
    last_tf      TEXT,
    last_market  TEXT DEFAULT 'forex',
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    ip_address   TEXT,
    user_agent   TEXT
);

CREATE TABLE IF NOT EXISTS mt5_credentials (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    server       TEXT NOT NULL,
    login        INTEGER NOT NULL,
    password_enc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_audit (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    action       TEXT NOT NULL,
    symbol       TEXT,
    direction    TEXT,
    volume       REAL,
    price        REAL,
    sl           REAL,
    tp           REAL,
    result_json  TEXT,
    ip_address   TEXT,
    session_id   TEXT
);

CREATE TABLE IF NOT EXISTS strategy_sessions (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    schema_json  TEXT,
    current_code TEXT,
    version      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_order_audit_user_id ON order_audit(user_id);
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

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

# ── Users ──────────────────────────────────────────────────────────────
def create_user(username: str, password_hash: str, email: Optional[str] = None) -> dict:
    user_id = _new_id()
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO users (id, username, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, username.strip().lower(), email, password_hash, _now_utc())
        )
        conn.commit()
        return {"id": user_id, "username": username}
    except sqlite3.IntegrityError as e:
        raise ValueError(f"Username or email already exists: {e}")
    finally:
        conn.close()

def get_user_by_username(username: str) -> Optional[dict]:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, username, email, password_hash, is_active, last_login FROM users WHERE username = ?",
            (username.strip().lower(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_user_by_id(user_id: str) -> Optional[dict]:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, username, email, is_active, last_login, created_at FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def update_last_login(user_id: str):
    conn = _get_conn()
    try:
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (_now_utc(), user_id))
        conn.commit()
    finally:
        conn.close()

# ── Sessions ───────────────────────────────────────────────────────────
def create_session(user_id: str, raw_token: str, ip_address: str = None,
                   user_agent: str = None) -> str:
    """Store hashed token, return the session ID."""
    from main.config import SESSION_EXPIRY_SECONDS
    from datetime import timedelta

    session_id = _new_id()
    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(seconds=SESSION_EXPIRY_SECONDS)).isoformat()

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO sessions
               (id, user_id, token_hash, created_at, expires_at, ip_address, user_agent)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, user_id, token_hash, now.isoformat(), expires, ip_address, user_agent)
        )
        conn.commit()
        return session_id
    finally:
        conn.close()

def validate_session(raw_token: str) -> Optional[dict]:
    """
    Validate a raw token. Returns user_id + session info if valid, None if expired/invalid.
    Called on every authenticated request — uses an in-memory TTL cache to avoid
    a SQLite round-trip on every request (was causing 2s page load delays).
    """
    token_hash = _hash_token(raw_token)
    now_mono = time.monotonic()

    # Cache hit — return cached result if still fresh
    cached = _SESSION_CACHE.get(token_hash)
    if cached is not None:
        session, cache_expires = cached
        if now_mono < cache_expires:
            return session  # None means "known invalid" — also cached

    # Cache miss or stale — hit SQLite
    now = _now_utc()
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT s.id, s.user_id, s.expires_at, s.last_panel, s.last_symbol,
                      s.last_tf, s.last_market, u.username, u.is_active
               FROM sessions s
               JOIN users u ON s.user_id = u.id
               WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = 1""",
            (token_hash, now)
        ).fetchone()
        session = dict(row) if row else None
    finally:
        conn.close()

    # Store in cache (including None so we don't hammer DB for bad tokens)
    _SESSION_CACHE[token_hash] = (session, now_mono + _SESSION_CACHE_TTL)
    return session

def update_session_state(session_id: str, last_panel: str = None,
                         last_symbol: str = None, last_tf: str = None,
                         last_market: str = None):
    """Update the user's last-active state for resume-on-login."""
    fields, values = [], []
    if last_panel:
        fields.append("last_panel = ?"); values.append(last_panel)
    if last_symbol:
        fields.append("last_symbol = ?"); values.append(last_symbol)
    if last_tf:
        fields.append("last_tf = ?"); values.append(last_tf)
    if last_market:
        fields.append("last_market = ?"); values.append(last_market)
    if not fields:
        return
    values.append(session_id)
    conn = _get_conn()
    try:
        conn.execute(f"UPDATE sessions SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()

def delete_session(session_id: str):
    conn = _get_conn()
    try:
        # Get token_hash first so we can evict the cache entry
        row = conn.execute(
            "SELECT token_hash FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row:
            _SESSION_CACHE.pop(row["token_hash"], None)

        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()

def cleanup_expired_sessions():
    """Remove expired sessions. Call periodically."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now_utc(),))
        conn.commit()
    finally:
        conn.close()

# ── MT5 Credentials ────────────────────────────────────────────────────
def save_mt5_credentials(user_id: str, server: str, login: int, password_enc: str):
    """Save encrypted MT5 credentials for a user (upsert)."""
    conn = _get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM mt5_credentials WHERE user_id = ?", (user_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE mt5_credentials SET server=?, login=?, password_enc=? WHERE user_id=?",
                (server, login, password_enc, user_id)
            )
        else:
            conn.execute(
                "INSERT INTO mt5_credentials (id, user_id, server, login, password_enc) VALUES (?,?,?,?,?)",
                (_new_id(), user_id, server, login, password_enc)
            )
        conn.commit()
    finally:
        conn.close()

def load_mt5_credentials(user_id: str) -> Optional[dict]:
    """Load encrypted MT5 credentials."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT server, login, password_enc FROM mt5_credentials WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def delete_mt5_credentials(user_id: str):
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM mt5_credentials WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()

# ── Order Audit ────────────────────────────────────────────────────────
def write_order_audit(user_id: str, action: str, symbol: str = None,
                      direction: str = None, volume: float = None,
                      price: float = None, sl: float = None, tp: float = None,
                      result: dict = None, ip_address: str = None,
                      session_id: str = None):
    """
    Append-only order audit log.
    NEVER update or delete from this table.
    Called for every order attempt — success or failure.
    """
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO order_audit
               (id, user_id, timestamp, action, symbol, direction, volume, price,
                sl, tp, result_json, ip_address, session_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_new_id(), user_id, _now_utc(), action, symbol, direction, volume,
             price, sl, tp, json.dumps(result) if result else None, ip_address, session_id)
        )
        conn.commit()
    except Exception as e:
        # Order audit must NEVER fail silently — log to stderr directly
        import sys
        print(f"[CRITICAL] Order audit write failed: {e}", file=sys.stderr)
    finally:
        conn.close()


def get_order_history(user_id: str, limit: int = 100) -> list[dict]:
    """Read order audit log for a user. Uses the standard _get_conn() pattern."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM order_audit WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
