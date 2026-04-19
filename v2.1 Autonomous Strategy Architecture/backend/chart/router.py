"""
Chart + Backtest API Routes
============================
POST /api/chart/backtest           — Run backtest, return full result
GET  /api/chart/strategies         — List available strategies + their config schemas
GET  /api/chart/strategies/{name}  — Get single strategy config schema
POST /api/chart/strategies/upload  — Upload a .py strategy file
DELETE /api/chart/strategies/uploaded/{filename} — Delete uploaded strategy
GET  /api/chart/strategies/uploaded/list — List uploaded strategies
POST /api/chart/scanner/start      — Start headless MTF scanner → returns historical signals only
POST /api/chart/scanner/stop       — Stop a running scanner
GET  /api/chart/scanners           — List active scanners with status

No per-scanner WebSocket — signals go through /api/signals/ws,
chart data goes through /api/watchlist/ws.

All routes require auth.
"""

import asyncio
import json
from datetime import datetime
import shutil
import types
import importlib.util
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from main.models import BacktestRequest, MTFStartRequest
from main.logger import get_logger
from chart.registry import auto_discover_strategies
from chart.engine import Backtester
from chart.mtf_engine import MTFLiveEngine
from data_collector.router import get_mt5

log = get_logger("engine")
router = APIRouter()

# Active scanner engines — keyed by scanner_id
_active_scanners: dict[str, MTFLiveEngine] = {}
# Scanner metadata for listing (name, config, etc.)
_scanner_meta: dict[str, dict] = {}


@router.get("/strategies")
async def list_strategies():
    registry = auto_discover_strategies()
    result = []
    for name, cls in registry.items():
        schema = {}
        if hasattr(cls, "config_model") and cls.config_model:
            try:
                schema = cls.config_model.model_json_schema()
            except Exception:
                pass
        result.append({
            "name": name,
            "description": getattr(cls, "description", ""),
            "schema": schema,
        })
    return {"strategies": result}


@router.get("/strategies/{name}")
async def get_strategy(name: str):
    registry = auto_discover_strategies()
    if name not in registry:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")
    cls = registry[name]
    schema = {}
    if hasattr(cls, "config_model") and cls.config_model:
        schema = cls.config_model.model_json_schema()
    return {"name": name, "description": getattr(cls, "description", ""), "schema": schema}


@router.post("/strategies/upload")
async def upload_strategy(file: UploadFile = File(...), request: Request = None):
    """
    Upload a .py strategy file. Validates syntax and BaseStrategy compliance,
    then saves to the strategies/ directory. No sandbox — single-user local app.
    Returns: {success, strategy_name, filename, schema}
    """
    from main.config import STRATEGIES_DIR
    from chart.registry import _registry, auto_discover_strategies
    from strategies._template import BaseStrategy

    # 1. Basic file checks
    if not file.filename.endswith(".py"):
        raise HTTPException(status_code=400, detail="Only .py files are accepted")
    if file.filename.startswith("_"):
        raise HTTPException(status_code=400, detail="Filename cannot start with underscore")

    content_bytes = await file.read()
    if len(content_bytes) > 500_000:
        raise HTTPException(status_code=400, detail="File too large (max 500KB)")
    try:
        source = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    # 2. Syntax check (compile without executing)
    try:
        compile(source, file.filename, "exec")
    except SyntaxError as e:
        raise HTTPException(status_code=400, detail=f"Syntax error: {e}")

    # 3. Write the file first, THEN import it through the normal registry path.
    #    This gives imports, package relativity, and everything else Python users expect.
    safe_name = "".join(c for c in file.filename if c.isalnum() or c in "._-")
    if not safe_name.endswith(".py"):
        safe_name += ".py"
    dest = STRATEGIES_DIR / safe_name

    # Refuse to overwrite protected / built-in strategies
    PROTECTED = {
        "_template.py", "ema_crossover.py", "supertrend.py",
        "reverse_ema_crossover.py", "VWAPStrategy.py",
    }
    if safe_name in PROTECTED:
        raise HTTPException(status_code=403, detail=f"Cannot overwrite built-in strategy '{safe_name}'")

    # Write to a temp name so we can roll back cleanly if it fails to load
    tmp_path = STRATEGIES_DIR / f".uploading_{safe_name}"
    tmp_path.write_bytes(content_bytes)

    # 4. Try to import it and find the strategy class
    import importlib, importlib.util
    module_name = f"strategies._upload_check_{file.filename[:-3]}"
    spec = importlib.util.spec_from_file_location(module_name, tmp_path)
    if spec is None or spec.loader is None:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Could not prepare module loader")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Module failed to load: {e}")

    found_cls = None
    for attr in dir(module):
        obj = getattr(module, attr, None)
        if (isinstance(obj, type) and issubclass(obj, BaseStrategy)
                and obj is not BaseStrategy and getattr(obj, "name", "")):
            found_cls = obj
            break

    if found_cls is None:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="No valid strategy class found. Need a subclass of BaseStrategy with a non-empty `name`."
        )

    strategy_name = found_cls.name

    # 5. Smoke-test instantiation + on_start/on_bar with dummy M1 data
    import pandas as pd, numpy as np
    dummy = pd.DataFrame({
        "time":   pd.date_range("2024-01-01", periods=500, freq="1min"),
        "open":   np.full(500, 1.0), "high": np.full(500, 1.01),
        "low":    np.full(500, 0.99), "close": np.full(500, 1.0),
        "volume": np.ones(500), "spread": 0,
    })
    try:
        instance = found_cls(settings={})
        instance.on_start(dummy)
        
        def engine_parse(raw):
            from strategies._template import Signal
            if raw is None: return
            if isinstance(raw, Signal): return
            if isinstance(raw, str):
                if raw.upper().strip() not in ("BUY", "SELL", "HOLD"): raise ValueError("String must be BUY/SELL/HOLD")
                return
            if isinstance(raw, tuple):
                if len(raw) == 1: return engine_parse(raw[0])
                if len(raw) == 3:
                    d = str(raw[0]).upper().strip()
                    if d not in ("BUY", "SELL", "HOLD"): raise ValueError("Tuple must start with BUY/SELL/HOLD")
                    if raw[1] is not None: float(raw[1])
                    if raw[2] is not None: float(raw[2])
                    return
                raise ValueError(f"Tuple length {len(raw)} must be 1 or 3")
            raise ValueError(f"Unsupported type {type(raw).__name__}")

        for i in range(len(dummy)):
            try:
                result = instance.on_bar(i, dummy)
            except Exception as e:
                raise ValueError(f"on_bar raised on bar {i}: {type(e).__name__}: {e}")
            try:
                engine_parse(result)
            except Exception as e:
                raise ValueError(f"on_bar returned unparseable value on bar {i}: {e}")
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Strategy smoke-test failed: {e}")

    # 6. Name collision against already-registered strategies
    if strategy_name in auto_discover_strategies():
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=409,
            detail=f"Strategy named '{strategy_name}' already exists. Change the `name` attribute."
        )

    # 7. Commit — rename temp file to final name and clear the registry cache
    if dest.exists():
        dest.unlink()
    tmp_path.rename(dest)
    _registry.clear()

    schema = found_cls.config_model.model_json_schema() if getattr(found_cls, "config_model", None) else {}

    log.info(f"Strategy uploaded | name='{strategy_name}' | file={safe_name}")
    return {
        "success":       True,
        "strategy_name": strategy_name,
        "filename":      safe_name,
        "description":   getattr(found_cls, "description", ""),
        "schema":        schema,
    }


@router.delete("/strategies/uploaded/{filename}")
async def delete_uploaded_strategy(filename: str):
    """Delete an uploaded strategy. Cannot delete built-in strategies."""
    from main.config import STRATEGIES_DIR
    from chart.registry import _registry

    # Protect built-in strategies
    PROTECTED = {
        "_template.py", "ema_crossover.py",
        "supertrend.py", "reverse_ema_crossover.py",
        "VWAPStrategy.py",
    }
    if filename in PROTECTED:
        raise HTTPException(status_code=403, detail="Cannot delete built-in strategies")

    # Only allow .py files
    if not filename.endswith(".py"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = STRATEGIES_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Strategy file not found")

    path.unlink()
    _registry.clear()

    log.info(f"Strategy deleted | file={filename}")
    return {"success": True, "message": f"Strategy '{filename}' deleted"}


@router.get("/strategies/uploaded/list")
async def list_uploaded_strategies(request: Request):
    """List only user-uploaded strategies (not built-ins)."""
    from main.config import STRATEGIES_DIR

    BUILTIN = {
        "_template.py", "ema_crossover.py", "supertrend.py",
        "reverse_ema_crossover.py", "VWAPStrategy.py",
    }
    uploaded = []

    for path in STRATEGIES_DIR.glob("*.py"):
        if path.name not in BUILTIN:
            uploaded.append({
                "filename": path.name,
                "size_kb":  round(path.stat().st_size / 1024, 1),
            })

    # Enrich with strategy name from registry if loaded
    from chart.registry import auto_discover_strategies
    registry = auto_discover_strategies()
    name_by_file = {
        cls.__module__.split(".")[-1] + ".py": cls.name
        for cls in registry.values()
    }

    for item in uploaded:
        item["strategy_name"] = name_by_file.get(item["filename"], item["filename"][:-3])

    return {"uploaded": uploaded}


@router.post("/backtest")
async def run_backtest(req: BacktestRequest, request: Request):
    from main.models import BacktestConfig
    from datetime import datetime

    # Parse the date range (accept both "YYYY-MM-DD" and ISO-with-time)
    try:
        date_from = datetime.fromisoformat(req.date_from.replace("Z", "+00:00"))
        date_to   = datetime.fromisoformat(req.date_to.replace("Z", "+00:00"))
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format: {e}. Use 'YYYY-MM-DD' or ISO-8601."
        )
    if date_to <= date_from:
        raise HTTPException(status_code=400, detail="date_to must be after date_from")

    # Sanity cap: 1 year of M1 = ~525k bars. Cap at 90 days by default to
    # keep backtests responsive; bump this if you need longer windows.
    from datetime import timedelta
    MAX_DAYS = 90
    if (date_to - date_from) > timedelta(days=MAX_DAYS):
        raise HTTPException(
            status_code=400,
            detail=f"Date range exceeds {MAX_DAYS} days. M1 backtests over longer "
                   f"windows are slow; shorten the range or raise MAX_DAYS in code."
        )

    # Resolve provider
    if req.provider == "binance":
        from data_collector.binance import BinanceProvider
        provider = BinanceProvider()
        if not provider.connected:
            connect_result = await asyncio.to_thread(provider.connect)
            if not connect_result["success"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Binance connection failed: {connect_result.get('error')}"
                )
        default_point = 0.01; default_digits = 2; default_contract_size = 1.0
    else:
        provider = get_mt5()
        if not provider.connected:
            raise HTTPException(status_code=400, detail="MT5 not connected")
        default_point = 0.00001; default_digits = 5; default_contract_size = 100000.0

    # Fetch M1 OHLCV for the requested date range + warmup buffer
    from datetime import timedelta
    fetch_date_from = date_from
    if req.warmup_bars > 0:
        buffer_days = (req.warmup_bars / 1440.0) * 1.5 + 4
        fetch_date_from = date_from - timedelta(days=buffer_days)

    try:
        data = await asyncio.to_thread(
            provider.fetch_ohlcv,
            symbol=req.symbol,
            timeframe="M1",
            date_from=fetch_date_from,
            date_to=date_to,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Data fetch failed: {e}")

    # Exact align warmup bars
    live_idx = data.index[data["time"] >= date_from]
    actual_warmup_bars = 0
    if len(live_idx) > 0:
        start_idx = live_idx[0]
        keep_idx = max(0, start_idx - req.warmup_bars)
        data = data.iloc[keep_idx:].reset_index(drop=True)
        actual_warmup_bars = start_idx - keep_idx

    if data.empty:
        raise HTTPException(
            status_code=400,
            detail=f"No data returned for {req.symbol} between {req.date_from} and {req.date_to}"
        )

    # Contract specs
    sym_info = await asyncio.to_thread(provider.get_symbol_info, req.symbol)
    point = sym_info.get("point", default_point) if sym_info else default_point
    digits = sym_info.get("digits", default_digits) if sym_info else default_digits
    contract_size = sym_info.get("trade_contract_size", default_contract_size) if sym_info else default_contract_size

    config = BacktestConfig(
        symbol=req.symbol,
        timeframe="M1",
        initial_balance=req.initial_balance,
        lot_size=req.lot_size,
        commission_per_lot=req.commission_per_lot,
        fixed_spread_points=req.fixed_spread_points,
        use_spread_from_data=req.use_spread_from_data,
        point=point, digits=digits, contract_size=contract_size,
        warmup_bars=actual_warmup_bars,
    )

    registry = auto_discover_strategies()
    if req.strategy_name not in registry:
        raise HTTPException(status_code=404, detail=f"Strategy '{req.strategy_name}' not found")

    strategy = registry[req.strategy_name](settings=req.settings)

    backtester = Backtester(config)
    try:
        result = await asyncio.to_thread(backtester.run, data, strategy)
    except Exception as e:
        log.error(f"Backtest failed | symbol={req.symbol} | strategy={req.strategy_name} | error={e}")
        raise HTTPException(status_code=500, detail=f"Backtest engine error: {e}")

    log.info(
        f"Backtest complete | {req.symbol} | M1 bars={len(data)} | "
        f"strategy={req.strategy_name} | trades={len(result.trades)} | "
        f"pnl={result.metrics.get('net_pnl', 0):.2f}"
    )
    return result


# ═══ REST-based Scanner Start/Stop (headless — signals only) ═══════════

@router.post("/scanner/start")
async def start_scanner(req: MTFStartRequest, request: Request):
    """
    Start a new headless MTF scanner. Returns historical signals only.
    Live signals are published to the SignalBus and delivered via /api/signals/ws.
    No candles, no indicators — charts are independent.
    """
    # ── Resolve provider — Bug 2: properly instantiate Binance ──────
    mt5 = get_mt5()

    if req.provider == "mt5":
        if not mt5.connected:
            raise HTTPException(status_code=400, detail="MT5 not connected")
        provider = mt5
    elif req.provider == "binance":
        from data_collector.binance import BinanceProvider
        provider = BinanceProvider()
        if not provider.connected:
            connect_result = await asyncio.to_thread(provider.connect)
            if not connect_result.get("success"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Binance connection failed: {connect_result.get('error', 'unknown')}"
                )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {req.provider}")

    import uuid
    scanner_id = f"scan-{uuid.uuid4().hex[:8]}"

    engine = MTFLiveEngine(
        scanner_id=scanner_id,
        symbol=req.symbol,
        strategy_name=req.strategy_name,
        settings=req.settings,
        provider=provider,
        broadcast_callback=None,  # No WS broadcast — signals go through SignalBus
        display_name=req.name or f"{req.symbol} {req.strategy_name}",
    )

    # Fetch historical signals synchronously (no candles, no indicators)
    try:
        hist_signals = await asyncio.to_thread(
            engine._load_history_and_scan
        )
    except Exception as e:
        log.error(f"Historical fetch failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load historical data: {e}")

    # Store engine and metadata
    _active_scanners[scanner_id] = engine
    _scanner_meta[scanner_id] = {
        "name": req.name or req.settings.get("_name", f"{req.symbol} {req.strategy_name}"),
        "symbol": req.symbol,
        "timeframe": "M1",             # Always M1
        "strategy_name": req.strategy_name,
        "provider": req.provider,
    }

    # Start live updates (polling or WS streams) in background
    asyncio.create_task(engine.start_live_only())

    # Historical signals are returned in the API response.
    # Frontend handles panel population + chart marker injection directly.
    # No need to publish to SignalBus (which would cause duplicates).

    log.info(f"Scanner started | id={scanner_id} | symbol={req.symbol} | tf=M1")

    return {
        "success": True,
        "scanner_id": scanner_id,
        "historical_signals": hist_signals,
    }


@router.post("/scanner/stop")
async def stop_scanner(request: Request):
    """Stop a running scanner by scanner_id."""
    body = await request.json()
    scanner_id = body.get("scanner_id", "")

    if scanner_id in _active_scanners:
        # Disable auto-trade for this scanner before stopping
        from order.auto_executor import AutoExecutor
        AutoExecutor.get().remove(scanner_id)

        _active_scanners[scanner_id].stop()
        del _active_scanners[scanner_id]
        _scanner_meta.pop(scanner_id, None)
        _scanner_meta.pop(scanner_id, None)
        log.info(f"Scanner stopped | id={scanner_id}")
        return {"success": True}

    return {"success": False, "detail": "Scanner not found"}


@router.get("/scanners")
async def list_scanners():
    """List active scanners with their status, config, and metadata."""
    from order.auto_executor import AutoExecutor
    auto_configs = AutoExecutor.get().get_all_configs()

    scanners = []
    for sid, engine in _active_scanners.items():
        meta = _scanner_meta.get(sid, {})
        auto = auto_configs.get(sid, {"enabled": False})
        scanners.append({
            "scanner_id": sid,
            "name": meta.get("name", sid),
            "symbol": engine.symbol,
            "timeframe": "M1",
            "strategy_name": engine.strategy_name,
            "provider": meta.get("provider", "mt5"),
            "is_running": engine.is_running,
            "auto": auto,
        })
    return {"scanners": scanners}
