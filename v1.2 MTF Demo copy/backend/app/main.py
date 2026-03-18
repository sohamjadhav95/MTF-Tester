"""
Strategy Tester API — Main Application
=======================================
Thin entry point: creates the FastAPI app, registers routers,
and mounts the frontend static files.

Run with:
    cd backend
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Ensure backend/ is on sys.path for strategy imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import CORS_ORIGINS
from app.core.registry import auto_discover_strategies
from app.api.routes_strategies import router as strategies_router
from app.api.routes_backtest import router as backtest_router
from app.api.routes_crypto import router as crypto_router
from app.api.routes_mtf import router as mtf_router
from app.api.routes_trading import router as trading_router

# Path to the frontend directory
FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..",
    "frontend",
)

# ─── App Setup ──────────────────────────────────────────────────
app = FastAPI(
    title="Strategy Tester API",
    description="Trading Strategy Backtesting Engine",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ────────────────────────────────────────────────────
app.include_router(strategies_router)
app.include_router(backtest_router)
app.include_router(crypto_router)
app.include_router(mtf_router)
app.include_router(trading_router)


# ─── Startup ────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    registry = auto_discover_strategies()
    print(f"[startup] Loaded {len(registry)} strategies: {list(registry.keys())}")


# ─── Health ─────────────────────────────────────────────────────
@app.get("/api/health")
async def health_check():
    from app.api.routes_backtest import mt5_provider
    return {
        "app": "Strategy Tester API",
        "version": "2.0.0",
        "mt5_connected": mt5_provider.connected,
    }


# ─── Frontend Serving ──────────────────────────────────────────
@app.get("/")
async def serve_frontend():
    """Serve the frontend HTML page."""
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# Mount static files — MUST be last so it doesn't catch API routes
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")
