"""
MTF Live Engine
================
Self-contained multi-timeframe live scanner.
No module-level global state — engine is an instance per scanner session.
Supports both MT5 (REST polling) and Binance (WebSocket streaming).
"""

import asyncio
import json
import time
import threading
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime, timezone
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
        self.strategies = {}
        for tf in timeframes:
            self.strategies[tf] = self.strategy_cls(settings=settings)

        # Track last processed close time per timeframe to avoid duplicate signals
        self.last_signal_time = {tf: None for tf in timeframes}

        self._rolling_df: Dict[str, pd.DataFrame] = {}
        self._HISTORY_BARS = 300

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
        """Send payload via async broadcast callback."""
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

        # Fetch historical context
        try:
            hist_candles, hist_signals, hist_indicators = await asyncio.to_thread(
                self.get_historical_context
            )
            await self._push({
                "type": "historical",
                "data": {
                    "candles": hist_candles,
                    "signals": hist_signals,
                    "indicators": hist_indicators,
                }
            })
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
        while self._running:
            try:
                signals, updates = await asyncio.to_thread(self.process_latest_data)
                if updates:
                    await self._push({"type": "bar_updates", "data": updates})
                for sig in signals:
                    await self._push({"type": "signal", "data": sig})
                    log.info(f"Signal | {sig['direction']} {sig['symbol']} [{sig['timeframe']}] @ {sig['price']}")
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
                    signal_dir = self._parse_signal(raw_signal)

                    if signal_dir in ("BUY", "SELL"):
                        if self.last_signal_time[tf] != bar_time:
                            self.last_signal_time[tf] = bar_time
                            sig = {
                                "symbol": self.symbol,
                                "timeframe": tf,
                                "strategy": self.strategy_name,
                                "direction": signal_dir,
                                "price": bar["close"],
                                "time": datetime.now(timezone.utc).isoformat(),
                                "bar_time": bar_time_str,
                            }
                            log.info(f"Signal | {signal_dir} {self.symbol} [{tf}] @ {bar['close']}")
                except Exception:
                    pass

    # ── Historical Context ──────────────────────────────────────

    def get_historical_context(self) -> Tuple[Dict[str, List[Dict]], List[Dict], Dict[str, Dict[str, List[Dict]]]]:
        historical_candles = {}
        historical_signals = []
        historical_indicators = {}

        for tf in self.timeframes:
            try:
                if self.start_time_dt:
                    df = self.provider.fetch_ohlcv(
                        self.symbol, tf, self.start_time_dt, datetime.now(timezone.utc)
                    )
                else:
                    df = self.provider.fetch_latest_bars(self.symbol, tf, self._HISTORY_BARS)
            except Exception:
                continue

            if df.empty:
                continue

            self._rolling_df[tf] = df.copy()

            candles = []
            for _, row in df.iterrows():
                time_val = row["time"]
                time_str = time_val.isoformat() if hasattr(time_val, "isoformat") else str(time_val)
                candles.append({
                    "time": time_str,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"] if pd.notna(row["volume"]) else 0)
                })
            historical_candles[tf] = candles
            if candles:
                log.info(f"HIST [{tf}] first={candles[0]['time']} last={candles[-1]['time']} type={type(df.iloc[0]['time'])} bars={len(candles)}")

            # Indicator calculation
            strategy = self.strategies[tf]
            try:
                ind_raw = strategy.get_indicator_data(df)
            except (AttributeError, Exception):
                ind_raw = {}

            tf_indicators = {}
            for name, points in ind_raw.items():
                fmt_points = []
                for idx, val in enumerate(points):
                    if val is not None and not pd.isna(val):
                        t = df.iloc[idx]["time"]
                        fmt_points.append({
                            "time": t.isoformat() if hasattr(t, "isoformat") else str(t),
                            "value": val
                        })
                tf_indicators[name] = fmt_points
            historical_indicators[tf] = tf_indicators

            if self.start_time_dt:
                start_idx = 0
            else:
                start_idx = max(0, len(df) - 50)

            for i in range(start_idx, len(df)):
                try:
                    raw_signal = strategy.on_bar(i, df)
                    signal_dir = self._parse_signal(raw_signal)

                    if signal_dir in ("BUY", "SELL"):
                        bar_time = df.iloc[i]["time"]
                        if self.last_signal_time[tf] != bar_time:
                            self.last_signal_time[tf] = bar_time
                            historical_signals.append({
                                "symbol": self.symbol,
                                "timeframe": tf,
                                "strategy": self.strategy_name,
                                "direction": signal_dir,
                                "price": float(df.iloc[i]["close"]),
                                "time": bar_time.isoformat() if hasattr(bar_time, "isoformat") else str(bar_time),
                                "bar_time": bar_time.isoformat() if hasattr(bar_time, "isoformat") else str(bar_time),
                            })
                except Exception:
                    continue

        historical_signals.sort(key=lambda x: x["time"], reverse=True)

        return historical_candles, historical_signals, historical_indicators

    # ── REST Polling (MT5) ──────────────────────────────────────

    def process_latest_data(self) -> Tuple[List[Dict], List[Dict]]:
        signals = []
        updates = []

        for tf in self.timeframes:
            try:
                df_latest = self.provider.fetch_latest_bars(self.symbol, tf, 3)
            except Exception:
                continue

            if df_latest.empty:
                continue

            if tf not in self._rolling_df or self._rolling_df[tf].empty:
                self._rolling_df[tf] = df_latest.copy()
            else:
                df = self._rolling_df[tf]
                for _, row in df_latest.iterrows():
                    bar_time = row["time"]
                    last_time = df.iloc[-1]["time"]

                    new_row_df = pd.DataFrame([row.to_dict()])

                    if bar_time == last_time:
                        for col in ["open", "high", "low", "close", "volume"]:
                            df.at[df.index[-1], col] = row[col]
                    elif bar_time > last_time:
                        df = pd.concat([df, new_row_df], ignore_index=True)
                        if len(df) > self._HISTORY_BARS:
                            df = df.iloc[-self._HISTORY_BARS:].reset_index(drop=True)
                self._rolling_df[tf] = df

            df = self._rolling_df[tf]
            current_idx = len(df) - 1
            current_time = df.iloc[current_idx]["time"]

            bar_dict = {
                "time": current_time.isoformat() if hasattr(current_time, "isoformat") else str(current_time),
                "open": float(df.iloc[current_idx]["open"]),
                "high": float(df.iloc[current_idx]["high"]),
                "low": float(df.iloc[current_idx]["low"]),
                "close": float(df.iloc[current_idx]["close"]),
                "volume": int(df.iloc[current_idx]["volume"] if pd.notna(df.iloc[current_idx]["volume"]) else 0)
            }
            log.info(f"LIVE [{tf}] time={bar_dict['time']} type={type(current_time)}")
            updates.append({"symbol": self.symbol, "timeframe": tf, "bar": bar_dict})

            strategy = self.strategies[tf]
            try:
                raw_signal = strategy.on_bar(current_idx, df)
            except Exception:
                continue

            signal_dir = self._parse_signal(raw_signal)

            if signal_dir in ("BUY", "SELL"):
                if self.last_signal_time[tf] != current_time:
                    self.last_signal_time[tf] = current_time
                    signals.append({
                        "symbol": self.symbol,
                        "timeframe": tf,
                        "strategy": self.strategy_name,
                        "direction": signal_dir,
                        "price": float(df.iloc[current_idx]["close"]),
                        "time": datetime.now(timezone.utc).isoformat(),
                        "bar_time": current_time.isoformat() if hasattr(current_time, "isoformat") else str(current_time),
                    })

        return signals, updates

    @staticmethod
    def _parse_signal(raw) -> str:
        if isinstance(raw, tuple):
            return str(raw[0]).upper() if raw else "HOLD"
        return str(raw).upper() if raw else "HOLD"
