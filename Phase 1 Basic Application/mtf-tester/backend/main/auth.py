"""
Authentication Module
======================
Handles password hashing and session token lifecycle.

SECURITY RULES:
- bcrypt with cost factor from config (default 12)
- Session tokens: 32 random bytes, base64url encoded
- Only SHA-256 hash of token is stored in DB
- MT5 passwords: Fernet symmetric encryption
- Fernet key loaded from env, auto-generated if missing (warns loudly)
"""

import secrets
import base64
import bcrypt
import os
from typing import Optional
from main.config import BCRYPT_ROUNDS, FERNET_KEY
from main.logger import get_logger

log = get_logger("auth")

# ── Fernet Setup ───────────────────────────────────────────────────────
def _get_fernet():
    """Get or generate Fernet encryption instance."""
    from cryptography.fernet import Fernet
    key = FERNET_KEY
    if not key:
        # Auto-generate for dev — in production this MUST be set in .env
        key = Fernet.generate_key().decode()
        log.warning(
            "FERNET_KEY not set in .env — auto-generated for this session only. "
            "MT5 credentials encrypted with this session key will be unreadable after restart. "
            "Set FERNET_KEY in .env for production."
        )
        os.environ["FERNET_KEY"] = key
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)

# ── Password Hashing ───────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt. Never store plain."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time comparison via bcrypt. Returns True if match."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

# ── Session Tokens ─────────────────────────────────────────────────────
def generate_token() -> str:
    """Generate a cryptographically random 32-byte base64url token."""
    return secrets.token_urlsafe(32)

# ── MT5 Credential Encryption ──────────────────────────────────────────
def encrypt_mt5_password(plain: str) -> str:
    """Encrypt MT5 password with Fernet. Returns base64 ciphertext."""
    f = _get_fernet()
    return f.encrypt(plain.encode("utf-8")).decode("utf-8")

def decrypt_mt5_password(ciphertext: str) -> str:
    """Decrypt MT5 password. Raises if key is wrong or token invalid."""
    f = _get_fernet()
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
