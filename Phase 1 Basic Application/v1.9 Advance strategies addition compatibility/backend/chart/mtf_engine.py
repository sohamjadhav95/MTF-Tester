"""
MTF Live Engine — Headless Signal Generator
=============================================
Self-contained multi-timeframe live scanner.
No module-level global state — engine is an instance per scanner session.
Supports both MT5 (REST polling) and Binance (WebSocket streaming).

After decoupling: this engine is a HEADLESS signal generator.
It crunches data and publishes signals to the SignalBus.
It does NOT send chart/candle/indicator data to any frontend.
"""

import asyncio
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any, Callable
import pandas as pd
from main.logger import get_logger

log = get_logger("mtf")

try:
    import websocket
except ImportError:
    websocket = None

BINANCE_TF_MAP = {
    "M1": "1m", "M3": "3m", "M5": "5m", "M15": "15m", "M30": "30m",
    "H1": "1h", "H2": "2h", "H4": "4h", "H6": "6h", "H8": "8h",
    "H12": "12h", "D1": "1d", "W1": "1w",
}


class MTFLiveEngine:
    """
    Multi-timeframe live scanner engine.
    Self-contained — no global state. One instance per active scan.

    After decoupling: publishes signals to SignalBus instead of broadcasting
    chart data. The engine is a headless signal generator.
    """

    def __init__(
        self,
        symbol: str,
        timeframes: List[str],
        strategy_name: str,
        settings: Dict,
        provider,
        broadcast_callback: Optional[Callable] = None,
        start_time: Optional[str] = None,
    ):
        self.symbol = symbol
        self.timeframes = timeframes
        self.strategy_name = strategy_name
        self.settings = settings
        self.provider = provider
        self.broadcast_callback = broadcast_callback

        # Load strategy registry
        from chart.registry import auto_discover_strategies
        self.strategy_registry = auto_discover_strategies()
        if strategy_name not in self.strategy_registry:
            raise ValueError(f"Strategy {strategy_name} not found.")

        self.strategy_cls = self.strategy_registry[strategy_name]

        # Instantiate a strategy instance for each timeframe
        # Strip internal/meta keys (underscore-prefixed like _name) before
        # passing to strategy constructors — those are metadata, not config.
        strategy_settings = {k: v for k, v in settings.items() if not k.startswith("_")}
        self.strategies = {}
        for tf in timeframes:
            self.strategies[tf] = self.strategy_cls(settings=strategy_settings)

        self.active_data_tfs = list(set(timeframes + getattr(self.strategy_cls, "required_timeframes", [])))

        # Track last processed close time per timeframe to avoid duplicate signals
        self.last_signal_time = {tf: None for tf in timeframes}

        self._started_tfs: set = set()

        self._rolling_df: Dict[str, pd.DataFrame] = {}
        self.active_trades: Dict[str, List[Dict]] = {tf: [] for tf in timeframes}
        self._HISTORY_BARS = 3000

        self._running = False
        self._ws_running = True
        self._ws_threads = []
        self._poll_task = None

        # Detect Binance vs MT5
        self.is_binance = hasattr(self.provider, "_session")

        self.start_time_dt = None
        if start_time:
            from dateutil.parser import parse
            try:
                self.start_time_dt = parse(start_time).replace(tzinfo=None)
            except Exception:
                pass

    @property
    def is_running(self) -> bool:
        return self._running

    async def _push(self, payload: dict):
        """Send payload via async broadcast callback (status messages only)."""
        if self.broadcast_callback:
            try:
                if asyncio.iscoroutinefunction(self.broadcast_callback):
                    await self.broadcast_callback(payload)
                else:
                    self.broadcast_callback(payload)
            except Exception:
                pass

    async def start(self):
        """Start the scanner — fetch historical data, then begin live updates."""
        self._running = True
        log.info(f"MTF scanner started | symbol={self.symbol} | tfs={self.timeframes} | strategy={self.strategy_name}")

        # Fetch historical context (signals only — no candles/indicators sent)
        try:
            hist_signals = await asyncio.to_thread(
                self.get_historical_context
            )
            # Publish historical signals to SignalBus
            from signals.bus import SignalBus
            bus = SignalBus.get()
            for sig in hist_signals:
                await bus.publish(sig)
        except Exception as e:
            log.error(f"Historical fetch failed: {e}")
            await self._push({"type": "error", "data": str(e)})

        # Start live updates
        if self.is_binance:
            self._start_binance_streams()
        else:
            # MT5: poll every 5 seconds
            self._poll_task = asyncio.create_task(self._mt5_poll_loop())

    async def start_live_only(self):
        """Start ONLY the live polling/streaming loop (historical data already provided via REST)."""
        self._running = True
        log.info(f"MTF live polling started | symbol={self.symbol} | tfs={self.timeframes}")

        if self.is_binance:
            self._start_binance_streams()
        else:
            self._poll_task = asyncio.create_task(self._mt5_poll_loop())

    def stop(self):
        """Stop all running tasks and WS connections."""
        self._running = False
        self._ws_running = False
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None
        log.info(f"MTF scanner stopped | symbol={self.symbol}")

    async def _mt5_poll_loop(self):
        """Poll MT5 for new bars every 5 seconds."""
        from signals.bus import SignalBus
        bus = SignalBus.get()

        while self._running:
            try:
                signals, _updates = await asyncio.to_thread(self.process_latest_data)
                for sig in signals:
                    msg_type = sig.get("type", "signal")
                    if msg_type == "signal":
                        await bus.publish(sig)
                        log.info(f"Signal | {sig['direction']} {sig['symbol']} [{sig['timeframe']}] @ {sig['price']}")
                    elif msg_type == "trade_update":
                        await bus.publish_trade_update(sig)
                        log.info(f"Trade Update | {sig['status']} {sig['symbol']} [{sig['timeframe']}]")
            except Exception as e:
                log.error(f"Poll error: {e}")
            await asyncio.sleep(5)

    # ── Binance WebSocket Streaming ─────────────────────────────

    def _start_binance_streams(self):
        if not websocket or not self.is_binance:
            return
        for tf in self.timeframes:
            t = threading.Thread(target=self._binance_ws_loop, args=(tf,), daemon=True)
            self._ws_threads.append(t)
            t.start()

    def _binance_ws_loop(self, tf: str):
        symbol_lower = self.symbol.lower()
        interval = BINANCE_TF_MAP.get(tf, "1h")
        url = f"wss://fstream.binance.com/ws/{symbol_lower}@kline_{interval}"

        def on_message(ws, raw_msg):
            try:
                self._on_kline_message(tf, raw_msg)
            except Exception:
                pass

        def on_error(ws, error):
            pass

        def on_close(ws, close_status_code, close_msg):
            if self._ws_running:
                time.sleep(3)
                self._run_ws(url, on_message, on_error, on_close)

        self._run_ws(url, on_message, on_error, on_close)

    def _run_ws(self, url, on_message, on_error, on_close):
        ws_app = websocket.WebSocketApp(
            url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        if self._ws_running:
            ws_app.run_forever()

    def _on_kline_message(self, tf: str, raw_msg: str):
        msg = json.loads(raw_msg)
        if "k" not in msg:
            return

        k = msg["k"]
        bar_time = datetime.utcfromtimestamp(int(k["t"]) / 1000)
        bar_time_str = bar_time.isoformat()

        bar = {
            "time": bar_time_str,
            "open": float(k["o"]),
            "high": float(k["h"]),
            "low": float(k["l"]),
            "close": float(k["c"]),
            "volume": float(k["v"])
        }

        is_closed = k.get("x", False)

        # Update rolling DF
        if tf in self._rolling_df:
            df = self._rolling_df[tf]
            if not df.empty:
                last_time = df.iloc[-1]["time"]
                new_row_dict = {
                    "time": bar_time, "open": bar["open"], "high": bar["high"],
                    "low": bar["low"], "close": bar["close"], "volume": bar["volume"]
                }
                new_row_df = pd.DataFrame([new_row_dict])

                if last_time == bar_time:
                    for col in ["open", "high", "low", "close", "volume"]:
                        df.at[df.index[-1], col] = bar[col]
                else:
                    df = pd.concat([df, new_row_df], ignore_index=True)
                    if len(df) > self._HISTORY_BARS:
                        df = df.iloc[-self._HISTORY_BARS:].reset_index(drop=True)
                    self._rolling_df[tf] = df

            # Evaluate strategy on bar close
            if is_closed:
                strategy = self.strategies[tf]
                try:
                    current_idx = len(df) - 1
                    raw_signal = strategy.on_bar(current_idx, df)
                    signal_dir, sl, tp = self._parse_signal(raw_signal)

                    if signal_dir in ("BUY", "SELL"):
                        if self.last_signal_time[tf] != bar_time:
                            self.last_signal_time[tf] = bar_time
                            sig = {
                                "id": str(uuid.uuid4()),
                                "type": "signal",
                                "symbol": self.symbol,
                                "timeframe": tf,
                                "strategy": self.strategy_name,
                                "direction": signal_dir,
                                "price": bar["close"],
                                "sl": sl,
                                "tp": tp,
                                "time": bar_time_str,
                                "bar_time": bar_time_str,
                                "status": "RUNNING",
                            }
                            # Publish to SignalBus from sync context
                            try:
                                loop = asyncio.get_event_loop()
                                if loop.is_running():
                                    asyncio.run_coroutine_threadsafe(
                                        self._publish_signal(sig), loop
                                    )
                                else:
                                    asyncio.run(self._publish_signal(sig))
                            except Exception:
                                pass
                            log.info(f"Signal | {signal_dir} {self.symbol} [{tf}] @ {bar['close']}")
                except Exception:
                    pass

    async def _publish_signal(self, sig: dict):
        """Helper to publish signal to SignalBus."""
        from signals.bus import SignalBus
        await SignalBus.get().publish(sig)

    # ── Historical Context ──────────────────────────────────────

    def get_historical_context(self) -> List[Dict]:
        """
        Fetch historical data, run strategy over it, return signals only.

        After decoupling: returns ONLY historical_signals (list of dicts).
        No candles, no indicators — charts handle their own data independently.

        The engine still maintains rolling DataFrames internally for strategy
        evaluation and still calls on_start/on_bar/get_indicator_data for strategy
        logic — indicators are used for strategy computation, just not sent to frontend.
        """
        historical_signals = []

        # 1. Fetch raw data for all dependencies (primary + required HTF)
        for tf in self.active_data_tfs:
            try:
                if self.start_time_dt:
                    df = self.provider.fetch_ohlcv(
                        self.symbol, tf, self.start_time_dt, datetime.now(timezone.utc)
                    )
                else:
                    df = self.provider.fetch_latest_bars(self.symbol, tf, self._HISTORY_BARS)
            except Exception:
                continue

            if not df.empty:
                self._rolling_df[tf] = df.copy()

        # 2. Process strategy logic for requested timeframes
        for tf in self.timeframes:
            if tf not in self._rolling_df:
                continue
            
            df = self._rolling_df[tf]
            strategy = self.strategies[tf]
            
            # Prepare optional HTF data dict
            htf_data = {}
            for rtf in getattr(self.strategy_cls, "required_timeframes", []):
                if rtf in self._rolling_df and rtf != tf:
                    htf_data[rtf] = self._rolling_df[rtf]

            # Call on_start with full historical data and injected HTF frame
            if hasattr(strategy, "on_start"):
                import inspect
                try:
                    sig = inspect.signature(strategy.on_start)
                    kwargs = {}
                    if "htf_data" in sig.parameters:
                        kwargs["htf_data"] = htf_data if htf_data else None
                    strategy.on_start(df, **kwargs)
                except Exception as e:
                    log.warning(f"on_start failed [{tf}]: {e}")

            # Calculate indicators for strategy logic (not sent to frontend)
            try:
                strategy.get_indicator_data(df)
            except (AttributeError, Exception):
                pass

            if self.start_time_dt:
                start_idx = 0
            else:
                start_idx = max(0, len(df) - 50)

            for i in range(start_idx, len(df)):
                bar = df.iloc[i]
                bar_time = bar["time"]
                formatted_time = bar_time.isoformat() if hasattr(bar_time, "isoformat") else str(bar_time)
                if not formatted_time.endswith("Z") and "+" not in formatted_time:
                    formatted_time += "Z"

                # Check active trades for TP/SL hits
                for t in self.active_trades[tf][:]:
                    hit_status = None
                    if t["direction"] == "BUY":
                        if t["sl"] is not None and bar["low"] <= t["sl"]:
                            hit_status = "SL HIT"
                        elif t["tp"] is not None and bar["high"] >= t["tp"]:
                            hit_status = "TP HIT"
                    elif t["direction"] == "SELL":
                        if t["sl"] is not None and bar["high"] >= t["sl"]:
                            hit_status = "SL HIT"
                        elif t["tp"] is not None and bar["low"] <= t["tp"]:
                            hit_status = "TP HIT"

                    if hit_status:
                        t["status"] = hit_status
                        t["close_time"] = formatted_time
                        self.active_trades[tf].remove(t)

                try:
                    raw_signal = strategy.on_bar(i, df)
                    signal_dir, sl, tp = self._parse_signal(raw_signal)

                    if signal_dir in ("BUY", "SELL"):
                        if self.last_signal_time[tf] != bar_time:
                            self.last_signal_time[tf] = bar_time
                            trade_obj = {
                                "id": str(uuid.uuid4()),
                                "type": "signal",
                                "symbol": self.symbol,
                                "timeframe": tf,
                                "strategy": self.strategy_name,
                                "direction": signal_dir,
                                "price": float(bar["close"]),
                                "sl": sl,
                                "tp": tp,
                                "time": formatted_time,
                                "bar_time": formatted_time,
                                "status": "RUNNING"
                            }
                            self.active_trades[tf].append(trade_obj)
                            historical_signals.append(trade_obj)
                except Exception:
                    continue

        historical_signals.sort(key=lambda x: x["time"], reverse=True)

        return historical_signals

    # ── REST Polling (MT5) ──────────────────────────────────────

    def process_latest_data(self) -> Tuple[List[Dict], List[Dict]]:
        """
        Process latest data from the provider.
        Returns (signals, updates) where:
          - signals: list of signal/trade_update dicts to publish to SignalBus
          - updates: list of bar update dicts (kept for internal use, not sent to frontend)
        """
        signals = []
        updates = []

        # 1. Pre-fetch all required live data
        latest_dfs = {}
        for tf in self.active_data_tfs:
            try:
                df_latest = self.provider.fetch_latest_bars(self.symbol, tf, self._HISTORY_BARS)
                if not df_latest.empty:
                    latest_dfs[tf] = df_latest
            except Exception:
                continue

        # 2. Process charting & logic timeframes
        for tf in self.timeframes:
            if tf not in latest_dfs:
                continue

            df_latest = latest_dfs[tf]
            old_df = self._rolling_df.get(tf)
            self._rolling_df[tf] = df_latest.copy()
            df = self._rolling_df[tf]
            strategy = self.strategies[tf]

            # Prepare optional HTF data dict from the pre-fetched batch
            htf_data = {}
            for rtf in getattr(self.strategy_cls, "required_timeframes", []):
                if rtf in latest_dfs:
                    self._rolling_df[rtf] = latest_dfs[rtf].copy()
                if rtf in self._rolling_df and rtf != tf:
                    htf_data[rtf] = self._rolling_df[rtf]

            # Determine indexes to process
            if old_df is None or old_df.empty:
                idxs_to_process = [len(df) - 1]
                re_run_start = True
            else:
                old_last_time = old_df.iloc[-1]["time"]
                curr_last_time = df.iloc[-1]["time"]
                
                if curr_last_time == old_last_time:
                    idxs_to_process = [len(df) - 1]
                    re_run_start = False
                else:
                    idxs_to_process = df.index[df["time"] >= old_last_time].tolist()
                    re_run_start = True

            # Recalibrate strategy cache, dynamically passing HTF if required
            if re_run_start and hasattr(strategy, "on_start"):
                import inspect
                try:
                    sig = inspect.signature(strategy.on_start)
                    kwargs = {}
                    if "htf_data" in sig.parameters:
                        kwargs["htf_data"] = htf_data if htf_data else None
                    strategy.on_start(df, **kwargs)
                except Exception as e:
                    log.warning(f"on_start recalibration failed [{tf}]: {e}")

            # Get fresh indicators for strategy logic (not sent to frontend)
            try:
                ind_raw = strategy.get_indicator_data(df)
            except Exception:
                ind_raw = {}

            # Process updates linearly
            for idx in idxs_to_process:
                row = df.iloc[idx]
                b_time = row["time"]
                formatted_time = b_time.isoformat() if hasattr(b_time, "isoformat") else str(b_time)
                if not formatted_time.endswith("Z") and "+" not in formatted_time:
                    formatted_time += "Z"

                # Evaluate Running Trades actively for TP/SL hits
                for t in self.active_trades[tf][:]:
                    hit_status = None
                    if t["direction"] == "BUY":
                        if t["sl"] is not None and row["low"] <= t["sl"]:
                            hit_status = "SL HIT"
                        elif t["tp"] is not None and row["high"] >= t["tp"]:
                            hit_status = "TP HIT"
                    elif t["direction"] == "SELL":
                        if t["sl"] is not None and row["high"] >= t["sl"]:
                            hit_status = "SL HIT"
                        elif t["tp"] is not None and row["low"] <= t["tp"]:
                            hit_status = "TP HIT"

                    if hit_status:
                        t["status"] = hit_status
                        t["close_time"] = formatted_time
                        self.active_trades[tf].remove(t)
                        # Emit trade update
                        signals.append({
                            "type": "trade_update",
                            "id": t["id"],
                            "status": hit_status,
                            "close_time": formatted_time,
                            "symbol": self.symbol,
                            "timeframe": tf
                        })

                # Evaluate strategy on EACH recovered bar (no skipped signals)
                try:
                    raw_signal = strategy.on_bar(idx, df)
                    signal_dir, sl, tp = self._parse_signal(raw_signal)

                    if signal_dir in ("BUY", "SELL"):
                        if self.last_signal_time.get(tf) != b_time:
                            self.last_signal_time[tf] = b_time
                            trade_obj = {
                                "id": str(uuid.uuid4()),
                                "type": "signal",
                                "symbol": self.symbol,
                                "timeframe": tf,
                                "strategy": self.strategy_name,
                                "direction": signal_dir,
                                "price": float(row["close"]),
                                "sl": sl,
                                "tp": tp,
                                "time": formatted_time,
                                "bar_time": formatted_time,
                                "status": "RUNNING"
                            }
                            self.active_trades[tf].append(trade_obj)
                            signals.append(trade_obj)
                except Exception:
                    pass

        return signals, updates

    @staticmethod
    def _parse_signal(raw):
        """Parse signal — returns (direction, sl, tp)."""
        if isinstance(raw, tuple) and len(raw) >= 1:
            direction = str(raw[0]).upper() if raw[0] else "HOLD"
            sl = float(raw[1]) if len(raw) > 1 and raw[1] is not None else None
            tp = float(raw[2]) if len(raw) > 2 and raw[2] is not None else None
            return direction, sl, tp
        return str(raw).upper() if raw else "HOLD", None, None
