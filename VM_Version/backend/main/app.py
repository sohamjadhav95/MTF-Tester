"""
FastAPI Application Entry Point
================================
Creates app, registers middleware (order matters), mounts all routers,
serves frontend static files.

Run: cd backend && uvicorn main.app:app --host 0.0.0.0 --port 5000
"""

import sys
import os
from pathlib import Path

# Ensure backend/ is on path for cross-module imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from main.config import FRONTEND_DIR, HOST, PORT, DEBUG
from main.db import init_db
from main.middleware import RequestLoggerMiddleware
from main.logger import get_logger

log = get_logger("api")

# ── Router Imports ─────────────────────────────────────────────────────
# ── Router Imports ─────────────────────────────────────────────────────
from data_collector.router import router as data_router
from chart.router import router as chart_router
from order.router import router as order_router
from watchlist.router import router as watchlist_router
from signals.router import router as signals_router

# ── App ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from chart.registry import auto_discover_strategies
    strategies = auto_discover_strategies()
    log.info(f"Startup complete. Loaded {len(strategies)} strategies: {list(strategies.keys())}")

    # NEW: attach the auto-executor to the signal bus
    from order.auto_executor import AutoExecutor
    from order.router import _risk_guard
    AutoExecutor.get(risk_guard=_risk_guard).attach_to_bus()

    # Reconcile orphan positions
    from reconcile import startup_reconcile
    await startup_reconcile()

    yield

# ── App ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="MTF Tester API",
    description="Production-grade algorithmic trading platform",
    version="2.2.0",
    docs_url="/api/docs" if DEBUG else None,
    redoc_url=None,
    lifespan=lifespan,
)

# ── Middleware (applied in reverse order — last added = first executed) ─
app.add_middleware(RequestLoggerMiddleware)

# ── Routers ────────────────────────────────────────────────────────────
# ── Routers ────────────────────────────────────────────────────────────
app.include_router(data_router,       prefix="/api/data",       tags=["data"])
app.include_router(chart_router,      prefix="/api/chart",      tags=["chart"])
app.include_router(order_router,      prefix="/api/order",      tags=["order"])
app.include_router(watchlist_router,  prefix="/api/watchlist",  tags=["watchlist"])
app.include_router(signals_router,    prefix="/api/signals",    tags=["signals"])

# ── Health ─────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.2.0"}

# ── Frontend Serving ───────────────────────────────────────────────────
@app.get("/")
async def serve_app():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

# Mount static files LAST — must not shadow API routes
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
