"""
FastAPI Application Entry Point
================================
Creates app, registers middleware (order matters), mounts all routers,
serves frontend static files.

Run: cd backend && uvicorn main.app:app --host 127.0.0.1 --port 8000
"""

import sys
import os
from pathlib import Path

# Ensure backend/ is on path for cross-module imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from main.config import CORS_ORIGINS, FRONTEND_DIR, HOST, PORT, DEBUG
from main.db import init_db, cleanup_expired_sessions
from main.middleware import (
    AuthMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    RequestLoggerMiddleware,
)
from main.logger import get_logger

log = get_logger("api")

# ── Router Imports ─────────────────────────────────────────────────────
from main.api_auth import router as auth_router
from data_collector.router import router as data_router
from chart.router import router as chart_router
from order.router import router as order_router
from strategy_builder.router import router as strategy_router

# ── App ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="MTF Tester API",
    description="Production-grade algorithmic trading platform",
    version="2.0.0",
    docs_url="/api/docs" if DEBUG else None,
    redoc_url=None,
)

# ── Middleware (applied in reverse order — last added = first executed) ─
app.add_middleware(RequestLoggerMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── Routers ────────────────────────────────────────────────────────────
app.include_router(auth_router,     prefix="/api/auth",     tags=["auth"])
app.include_router(data_router,     prefix="/api/data",     tags=["data"])
app.include_router(chart_router,    prefix="/api/chart",    tags=["chart"])
app.include_router(order_router,    prefix="/api/order",    tags=["order"])
app.include_router(strategy_router, prefix="/api/strategy", tags=["strategy"])

# ── Health ─────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}

# ── Startup ────────────────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    init_db()
    cleanup_expired_sessions()

    from chart.registry import auto_discover_strategies
    strategies = auto_discover_strategies()
    log.info(f"Startup complete. Loaded {len(strategies)} strategies: {list(strategies.keys())}")

# ── Frontend Serving ───────────────────────────────────────────────────
@app.get("/")
async def serve_app():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

@app.get("/auth")
async def serve_auth():
    return FileResponse(str(FRONTEND_DIR / "auth.html"))

# Mount static files LAST — must not shadow API routes
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
