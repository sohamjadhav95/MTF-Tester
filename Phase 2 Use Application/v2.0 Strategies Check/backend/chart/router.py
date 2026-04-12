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
_scanner_counter = 0


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
    Upload a .py strategy file. Validates syntax, security, and BaseStrategy
    compliance. Saves to strategies/ directory. Clears registry cache so
    the new strategy is immediately available.
    Returns: {success, strategy_name, filename, schema}
    """
    from main.config import STRATEGIES_DIR
    from chart.registry import _registry

    # ── 1. File type check ────────────────────────────────────────
    if not file.filename.endswith(".py"):
        raise HTTPException(status_code=400, detail="Only .py files are accepted")

    content_bytes = await file.read()
    if len(content_bytes) > 500_000:  # 500KB max
        raise HTTPException(status_code=400, detail="File too large (max 500KB)")

    try:
        source = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    # ── 2. Syntax check ───────────────────────────────────────────
    try:
        compile(source, file.filename, "exec")
    except SyntaxError as e:
        raise HTTPException(status_code=400, detail=f"Syntax error in file: {e}")

    # ── 3. Security scan — block dangerous patterns ───────────────
    BLOCKED_PATTERNS = [
        "os.system", "os.popen", "subprocess", "eval(", "__import__(",
        "importlib.import_module", "open(", "socket.", "requests.",
        "urllib.request", "http.client", "ftplib", "smtplib",
        "shutil.rmtree", "shutil.move", "pathlib.Path",
        "sys.exit", "os.remove", "os.unlink", "os.rmdir",
    ]
    source_lower = source.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern.lower() in source_lower:
            raise HTTPException(
                status_code=400,
                detail=f"Strategy contains a blocked operation: '{pattern}'. "
                       f"Strategies may only use numpy, pandas, and standard math."
            )

    # ── 4. Load and validate class ────────────────────────────────
    try:
        import builtins as _builtins
        _safe_builtins = {k: getattr(_builtins, k) for k in [
            'True', 'False', 'None', 'int', 'float', 'str', 'bool', 'list',
            'dict', 'tuple', 'set', 'range', 'len', 'max', 'min', 'abs',
            'round', 'sum', 'sorted', 'enumerate', 'zip', 'map', 'filter',
            'isinstance', 'issubclass', 'type', 'super', 'property',
            'staticmethod', 'classmethod', 'print', 'hasattr', 'getattr',
            'setattr', 'ValueError', 'TypeError', 'KeyError', 'IndexError',
            'AttributeError', 'Exception', 'RuntimeError', 'StopIteration',
        ]}
        module = types.ModuleType(file.filename[:-3])
        # Restrict builtins BEFORE injecting anything else
        module.__dict__['__builtins__'] = _safe_builtins
        # Make strategy template available in module namespace
        import strategies._template as _tpl
        module.__dict__["BaseStrategy"] = _tpl.BaseStrategy
        module.__dict__["StrategyConfig"] = _tpl.StrategyConfig
        exec(compile(source, file.filename, "exec"), module.__dict__)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to execute module: {e}")

    from strategies._template import BaseStrategy

    found_cls = None
    for attr_name in dir(module):
        obj = getattr(module, attr_name, None)
        if (obj is not None
                and isinstance(obj, type)
                and issubclass(obj, BaseStrategy)
                and obj is not BaseStrategy
                and getattr(obj, "name", "")):
            found_cls = obj
            break

    if not found_cls:
        raise HTTPException(
            status_code=400,
            detail="No valid strategy class found. Your class must: "
                   "(1) extend BaseStrategy, (2) have a non-empty 'name' class variable, "
                   "(3) implement on_bar()."
        )

    strategy_name = found_cls.name

    # ── 5. Test instantiation ──────────────────────────────────────
    try:
        instance = found_cls(settings={})
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Strategy '{strategy_name}' failed to instantiate: {e}"
        )

    # Step 5b — smoke-test on_start with dummy data
    import pandas as pd, numpy as np
    dummy = pd.DataFrame({
        "time": pd.date_range("2024-01-01", periods=10, freq="1min"),
        "open": np.ones(10), "high": np.ones(10),
        "low": np.ones(10), "close": np.ones(10), "volume": np.ones(10)
    })
    try:
        instance.on_start(dummy)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Strategy on_start() failed with dummy data: {e}"
        )

    # Step 5c — smoke-test on_bar with dummy data
    try:
        result = instance.on_bar(len(dummy) - 1, dummy)
        # Validate return type
        if result is not None:
            if isinstance(result, tuple):
                if len(result) < 1 or str(result[0]).upper() not in ("BUY", "SELL", "HOLD"):
                    raise ValueError(f"on_bar() tuple first element must be BUY/SELL/HOLD, got: {result[0]}")
            elif isinstance(result, str):
                if result.upper() not in ("BUY", "SELL", "HOLD"):
                    raise ValueError(f"on_bar() must return BUY/SELL/HOLD, got: {result}")
            else:
                raise ValueError(f"on_bar() must return str or tuple, got: {type(result).__name__}")
    except ValueError:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Strategy on_bar() failed with dummy data: {e}"
        )

    # ── 6. Get config schema for UI ───────────────────────────────
    schema = {}
    if hasattr(found_cls, "config_model") and found_cls.config_model:
        try:
            schema = found_cls.config_model.model_json_schema()
        except Exception:
            schema = {}

    # ── Name collision check ──────────────────────────────────────
    from chart.registry import auto_discover_strategies
    registry = auto_discover_strategies()
    if strategy_name in registry:
        raise HTTPException(
            status_code=409,
            detail=f"A strategy named '{strategy_name}' already exists. "
                   f"Change the name class variable and re-upload."
        )

    # ── 7. Save to strategies directory ───────────────────────────
    # Sanitize filename
    safe_name = "".join(c for c in file.filename if c.isalnum() or c in "._-")
    if not safe_name.endswith(".py"):
        safe_name += ".py"
    dest = STRATEGIES_DIR / safe_name
    dest.write_bytes(content_bytes)

    # ── 8. Invalidate registry cache ──────────────────────────────
    _registry.clear()

    log.info(
        f"Strategy uploaded | name='{strategy_name}' | file={safe_name} "
        f"| user={getattr(request.state, 'user_id', 'unknown') if request else 'unknown'}"
    )

    return {
        "success":       True,
        "strategy_name": strategy_name,
        "filename":      safe_name,
        "description":   getattr(found_cls, "description", ""),
        "schema":        schema,
    }


@router.delete("/strategies/uploaded/{filename}")
async def delete_uploaded_strategy(filename: str, request: Request):
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

    log.info(f"Strategy deleted | file={filename} | user={getattr(request.state, 'user_id', 'unknown')}")
    return {"success": True, "message": f"Strategy '{filename}' deleted"}


@router.get("/strategies/uploaded/list")
async def list_uploaded_strategies(request: Request):
    """List only user-uploaded strategies (not built-ins)."""
    from main.config import STRATEGIES_DIR

    BUILTIN = {"_template.py", "ema_crossover.py", "supertrend.py", "reverse_ema_crossover.py", "VWAPStrategy.py"}
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

    # ── Resolve provider ──────────────────────────────────────────
    if req.provider == "binance":
        from data_collector.binance import BinanceProvider
        provider = BinanceProvider()
        if not provider.connected:
            connect_result = await asyncio.to_thread(provider.connect)
            if not connect_result["success"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Binance connection failed: {connect_result.get('error', 'unknown')}"
                )
        # Binance futures: 1 contract = 1 unit base asset
        default_point = 0.01
        default_digits = 2
        default_contract_size = 1.0
    else:  # mt5
        provider = get_mt5()
        if not provider.connected:
            raise HTTPException(status_code=400, detail="MT5 not connected")
        default_point = 0.00001
        default_digits = 5
        default_contract_size = 100000.0

    # ── Fetch primary OHLCV data ──────────────────────────────────
    try:
        date_from = datetime.fromisoformat(req.date_from)
        date_to = datetime.fromisoformat(req.date_to)
        data = await asyncio.to_thread(
            provider.fetch_ohlcv,
            symbol=req.symbol,
            timeframe=req.timeframe,
            date_from=date_from,
            date_to=date_to,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Data fetch failed: {e}")

    if data.empty:
        raise HTTPException(status_code=400, detail="No data returned for the specified range")

    # ── Get symbol info for contract specs ────────────────────────
    sym_info = await asyncio.to_thread(provider.get_symbol_info, req.symbol)
    point = sym_info.get("point", default_point) if sym_info else default_point
    digits = sym_info.get("digits", default_digits) if sym_info else default_digits
    contract_size = sym_info.get("trade_contract_size", default_contract_size) if sym_info else default_contract_size

    config = BacktestConfig(
        symbol=req.symbol,
        timeframe=req.timeframe,
        initial_balance=req.initial_balance,
        lot_size=req.lot_size,
        commission_per_lot=req.commission_per_lot,
        fixed_spread_points=req.fixed_spread_points,
        use_spread_from_data=req.use_spread_from_data,
        point=point,
        digits=digits,
        contract_size=contract_size,
    )

    # ── Get strategy ──────────────────────────────────────────────
    registry = auto_discover_strategies()
    if req.strategy_name not in registry:
        raise HTTPException(status_code=404, detail=f"Strategy '{req.strategy_name}' not found")

    strategy_cls = registry[req.strategy_name]
    strategy = strategy_cls(settings=req.settings)

    # ── Pre-fetch required HTF data ───────────────────────────────
    htf_data = {}
    required_tfs = getattr(strategy_cls, "required_timeframes", [])
    if required_tfs:
        for rtf in required_tfs:
            if rtf == req.timeframe:
                continue
            try:
                htf_df = await asyncio.to_thread(
                    provider.fetch_ohlcv,
                    symbol=req.symbol,
                    timeframe=rtf,
                    date_from=date_from,
                    date_to=date_to,
                )
                if not htf_df.empty:
                    htf_data[rtf] = htf_df
            except Exception as e:
                log.warning(f"Failed to fetch HTF data {rtf} for backtest: {e}")

    # Run backtest
    backtester = Backtester(config)
    try:
        result = await asyncio.to_thread(backtester.run, data, strategy, htf_data=htf_data if htf_data else None)
    except Exception as e:
        log.error(f"Backtest failed | symbol={req.symbol} | strategy={req.strategy_name} | error={e}")
        raise HTTPException(status_code=500, detail=f"Backtest engine error: {e}")

    log.info(
        f"Backtest complete | symbol={req.symbol} | tf={req.timeframe} | "
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
    mt5 = get_mt5()
    if req.provider == "mt5" and not mt5.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")

    provider = mt5 if req.provider == "mt5" else None

    global _scanner_counter
    _scanner_counter += 1
    scanner_id = f"scan-{_scanner_counter}"

    engine = MTFLiveEngine(
        symbol=req.symbol,
        timeframes=req.timeframes,
        strategy_name=req.strategy_name,
        settings=req.settings,
        provider=provider,
        broadcast_callback=None,  # No WS broadcast — signals go through SignalBus
        start_time=req.start_time,
    )

    # Fetch historical signals synchronously (no candles, no indicators)
    try:
        hist_signals = await asyncio.to_thread(
            engine.get_historical_context
        )
    except Exception as e:
        log.error(f"Historical fetch failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load historical data: {e}")

    # Store engine and metadata
    _active_scanners[scanner_id] = engine
    _scanner_meta[scanner_id] = {
        "name": req.settings.get("_name", f"{req.symbol} {req.strategy_name}"),
        "symbol": req.symbol,
        "timeframes": req.timeframes,
        "strategy_name": req.strategy_name,
        "provider": req.provider,
    }

    # Start live updates (polling or WS streams) in background
    asyncio.create_task(engine.start_live_only())

    # Historical signals are returned in the API response.
    # Frontend handles panel population + chart marker injection directly.
    # No need to publish to SignalBus (which would cause duplicates).

    log.info(f"Scanner started | id={scanner_id} | symbol={req.symbol} | tfs={req.timeframes}")

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
        _active_scanners[scanner_id].stop()
        del _active_scanners[scanner_id]
        _scanner_meta.pop(scanner_id, None)
        # Reset counter when no scanners active
        global _scanner_counter
        if not _active_scanners:
            _scanner_counter = 0
        log.info(f"Scanner stopped | id={scanner_id}")
        return {"success": True}

    return {"success": False, "detail": "Scanner not found"}


@router.get("/scanners")
async def list_scanners():
    """List active scanners with their status, config, and metadata."""
    scanners = []
    for sid, engine in _active_scanners.items():
        meta = _scanner_meta.get(sid, {})
        scanners.append({
            "scanner_id": sid,
            "name": meta.get("name", sid),
            "symbol": engine.symbol,
            "timeframes": engine.timeframes,
            "strategy_name": engine.strategy_name,
            "provider": meta.get("provider", "mt5"),
            "is_running": engine.is_running,
        })
    return {"scanners": scanners}
