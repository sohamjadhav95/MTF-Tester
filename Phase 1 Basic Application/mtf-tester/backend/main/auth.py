"""
Authentication Module
======================
Handles password hashing and session token lifecycle.

NOTE: Fernet encryption for MT5 credentials is DISABLED for testing.
      The encrypt/decrypt functions pass through plaintext.
      Re-enable by uncommenting the Fernet implementation below.
"""

import secrets
import base64
import bcrypt
import os
from typing import Optional
from main.config import BCRYPT_ROUNDS
from main.logger import get_logger

log = get_logger("auth")

# ── Fernet Setup (DISABLED for testing) ────────────────────────────────
# To re-enable, uncomment this block and update encrypt/decrypt below.
#
# from main.config import FERNET_KEY
# def _get_fernet():
#     from cryptography.fernet import Fernet
#     key = FERNET_KEY
#     if not key:
#         key = Fernet.generate_key().decode()
#         log.warning("FERNET_KEY not set — auto-generated for this session only.")
#         os.environ["FERNET_KEY"] = key
#     if isinstance(key, str):
#         key = key.encode()
#     return Fernet(key)

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

# ── MT5 Credential Encryption (DISABLED — passthrough for testing) ─────
def encrypt_mt5_password(plain: str) -> str:
    """Store MT5 password as-is (encryption disabled for testing)."""
    return plain

def decrypt_mt5_password(ciphertext: str) -> str:
    """Return MT5 password as-is (encryption disabled for testing)."""
    return ciphertext

