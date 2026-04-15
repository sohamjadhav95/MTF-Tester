"""
Auth API Routes
================
POST /api/auth/register    — Create new user
POST /api/auth/login       — Login, get session token
POST /api/auth/logout      — Invalidate session
GET  /api/auth/me          — Get current user info + session state
PUT  /api/auth/session     — Update session state (last panel, symbol, tf)
POST /api/auth/mt5/save    — Save encrypted MT5 credentials
GET  /api/auth/mt5/load    — Check if saved credentials exist (no password returned)
DELETE /api/auth/mt5       — Delete saved credentials
"""

from fastapi import APIRouter, Request, HTTPException, Header
from typing import Optional

from main.auth import hash_password, verify_password, generate_token
from main.auth import encrypt_mt5_password, decrypt_mt5_password
from main.db import (
    create_user, get_user_by_username, get_user_by_id,
    update_last_login, create_session, validate_session,
    delete_session, update_session_state,
    save_mt5_credentials, load_mt5_credentials, delete_mt5_credentials,
)
from main.models import RegisterRequest, LoginRequest, SessionStateUpdate, MT5ConnectRequest
from main.logger import get_logger

log = get_logger("auth")
router = APIRouter()


@router.post("/register")
async def register(req: RegisterRequest, request: Request):
    log.info(f"Register attempt | username={req.username}")
    password_hash = hash_password(req.password)
    try:
        user = create_user(req.username, password_hash, req.email)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    log.info(f"User registered | username={req.username} | id={user['id']}")
    return {"message": "Account created successfully"}


@router.post("/login")
async def login(req: LoginRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")
    log.info(f"Login attempt | username={req.username} | ip={ip}")

    user = get_user_by_username(req.username)
    if not user or not verify_password(req.password, user["password_hash"]):
        log.warning(f"Login failed | username={req.username} | ip={ip}")
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account is disabled")

    raw_token = generate_token()
    session_id = create_session(user["id"], raw_token, ip_address=ip, user_agent=ua)
    update_last_login(user["id"])

    log.info(f"Login success | username={user['username']} | session={session_id}")

    has_mt5_creds = load_mt5_credentials(user["id"]) is not None

    return {
        "token": raw_token,
        "session_id": session_id,
        "username": user["username"],
        "has_mt5_credentials": has_mt5_creds,
    }


@router.post("/logout")
async def logout(request: Request):
    session_id = getattr(request.state, "session_id", None)
    if session_id:
        delete_session(session_id)
        log.info(f"Logout | session={session_id}")
    return {"message": "Logged out"}


@router.get("/me")
async def get_me(request: Request):
    user = get_user_by_id(request.state.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    session = validate_session(request.state.raw_token)
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user.get("email"),
        "last_login": user.get("last_login"),
        "session": {
            "last_panel": session.get("last_panel", "dashboard") if session else "dashboard",
            "last_symbol": session.get("last_symbol") if session else None,
            "last_tf": session.get("last_tf") if session else None,
            "last_market": session.get("last_market", "forex") if session else "forex",
        }
    }


@router.put("/session")
async def update_session(req: SessionStateUpdate, request: Request):
    update_session_state(
        request.state.session_id,
        last_panel=req.last_panel,
        last_symbol=req.last_symbol,
        last_tf=req.last_tf,
        last_market=req.last_market,
    )
    return {"message": "Session updated"}


@router.post("/mt5/save")
async def save_mt5_creds(req: MT5ConnectRequest, request: Request):
    enc_password = encrypt_mt5_password(req.password)
    save_mt5_credentials(request.state.user_id, req.server, req.login, enc_password)
    log.info(f"MT5 credentials saved | user={request.state.user_id}")
    return {"message": "Credentials saved"}


@router.get("/mt5/load")
async def check_mt5_creds(request: Request):
    creds = load_mt5_credentials(request.state.user_id)
    if not creds:
        return {"has_credentials": False}
    return {
        "has_credentials": True,
        "server": creds["server"],
        "login": creds["login"],
    }


@router.delete("/mt5")
async def delete_mt5_creds(request: Request):
    delete_mt5_credentials(request.state.user_id)
    log.info(f"MT5 credentials deleted | user={request.state.user_id}")
    return {"message": "Credentials deleted"}
