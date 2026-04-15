"""
Live Scanner Engine — Single M1 Stream
========================================
Fetches M1 bars (3000 max), calls strategy.on_start() once,
then polls for new M1 bars and calls strategy.on_bar() per new bar.

No multi-TF orchestration. Strategy owns all timeframe logic internally.
Publishes signals to SignalBus. Does not broadcast chart data.
"""

import asyncio
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable, Tuple
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

HISTORY_BARS = 3000
LIVE_POLL_BARS = 20


class LiveScanEngine:
    """
    Single-symbol live scanner.
    Always operates on M1 data. Strategy handles all TF logic internally.
    One instance per active scan session.
    """

    def __init__(
        self,
        symbol: str,
        strategy_name: str,
        settings: Dict,
        provider,
        broadcast_callback: Optional[Callable] = None,
    ):
        self.symbol = symbol
        self.strategy_name = strategy_name
        self.settings = settings
        self.provider = provider
        self.broadcast_callback = broadcast_callback

        from chart.registry import auto_discover_strategies
        registry = auto_discover_strategies()
        if strategy_name not in registry:
            raise ValueError(f"Strategy '{strategy_name}' not found.")

        strategy_cls = registry[strategy_name]
        clean_settings = {k: v for k, v in settings.items() if not k.startswith("_")}
        self.strategy = strategy_cls(settings=clean_settings)

        self._rolling_df: Optional[pd.DataFrame] = None
        self._active_trades: List[Dict] = []
        self._last_signal_time = None
        self._last_signal_htf_idx: int = -1   # Bug 4: HTF-bar dedup

        self._running = False
        self._ws_running = True
        self._ws_thread: Optional[threading.Thread] = None
        self._poll_task = None

        self.is_binance = hasattr(provider, "_session")

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self):
        """Fetch history, call on_start, then start live updates."""
        self._running = True
        log.info(f"Scanner started | symbol={self.symbol} | strategy={self.strategy_name}")

        try:
            hist_signals = await asyncio.to_thread(self._load_history_and_scan)
            from signals.bus import SignalBus
            bus = SignalBus.get()
            for sig in hist_signals:
                await bus.publish(sig)
        except Exception as e:
            log.error(f"History load failed: {e}")
            if self.broadcast_callback:
                try:
                    await self.broadcast_callback({"type": "error", "data": str(e)})
                except Exception:
                    pass

        if self.is_binance:
            self._start_binance_ws()
        else:
            self._poll_task = asyncio.create_task(self._mt5_poll_loop())

    async def start_live_only(self):
        """Start live polling/streaming only (history already loaded)."""
        self._running = True
        log.info(f"Scanner live polling started | symbol={self.symbol}")
        if self.is_binance:
            self._start_binance_ws()
        else:
            self._poll_task = asyncio.create_task(self._mt5_poll_loop())

    def stop(self):
        self._running = False
        self._ws_running = False
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None
        log.info(f"Scanner stopped | symbol={self.symbol}")

    # ── History Load ────────────────────────────────────────────

    def _load_history_and_scan(self) -> List[Dict]:
        """
        Fetch 3000 M1 bars, call strategy.on_start(), scan for historical signals.
        Returns list of signal dicts (newest first).
        """
        df = self.provider.fetch_latest_bars(self.symbol, "M1", HISTORY_BARS)
        if df.empty:
            log.warning(f"No M1 data returned for {self.symbol}")
            return []

        self._rolling_df = df.copy()
        log.info(f"History loaded | {self.symbol}/M1 | bars={len(df)}")

        # Prime strategy cache
        try:
            self.strategy.on_start(df)
        except Exception as e:
            log.warning(f"on_start failed: {e}")

        # Scan last ~2880 bars (~2 days of M1) for recent signals
        start_idx = max(0, len(df) - 2880)
        signals = []

        for i in range(start_idx, len(df)):
            bar = df.iloc[i]
            bar_time = bar["time"]
            t_str = self._fmt_time(bar_time)

            # Check active trades for TP/SL hits
            self._check_active_trade_hits(bar, t_str)

            try:
                raw = self.strategy.on_bar(i, df)
                direction, sl, tp = self._parse_signal(raw)
                if direction in ("BUY", "SELL") and self._last_signal_time != bar_time:
                    # Bug 4: HTF-bar dedup — only emit once per HTF bar
                    current_htf_idx = -1
                    cache = getattr(self.strategy, "_cache", {})
                    m1_to_htf = cache.get("m1_to_htf", [])
                    if i < len(m1_to_htf):
                        current_htf_idx = m1_to_htf[i]
                    if current_htf_idx > -1 and current_htf_idx == self._last_signal_htf_idx:
                        continue  # Same HTF bar already signaled — skip duplicate

                    self._last_signal_time = bar_time
                    self._last_signal_htf_idx = current_htf_idx
                    trade = {
                        "id": str(uuid.uuid4()),
                        "type": "signal",
                        "symbol": self.symbol,
                        "timeframe": "M1",
                        "strategy": self.strategy_name,
                        "direction": direction,
                        "price": float(bar["close"]),
                        "sl": sl,
                        "tp": tp,
                        "time": t_str,
                        "bar_time": t_str,
                        "status": "RUNNING",
                    }
                    self._active_trades.append(trade)
                    signals.append(trade)
            except Exception:
                continue

        signals.sort(key=lambda x: x["time"], reverse=True)
        return signals

    # ── MT5 Polling ─────────────────────────────────────────────

    async def _mt5_poll_loop(self):
        from signals.bus import SignalBus
        bus = SignalBus.get()

        while self._running:
            try:
                new_signals = await asyncio.to_thread(self._process_new_bars)
                for sig in new_signals:
                    if sig.get("type") == "signal":
                        await bus.publish(sig)
                        log.info(f"Signal | {sig['direction']} {sig['symbol']} [M1] @ {sig['price']}")
                    elif sig.get("type") == "trade_update":
                        await bus.publish_trade_update(sig)
                        log.info(f"Trade Update | {sig['status']} {sig['symbol']} [M1]")
            except Exception as e:
                log.error(f"Poll error: {e}")
            await asyncio.sleep(5)

    def _process_new_bars(self) -> List[Dict]:
        """Fetch latest M1 tail, merge into rolling_df, call on_bar on new bars."""
        if self._rolling_df is None:
            return []

        try:
            df_new = self.provider.fetch_latest_bars(self.symbol, "M1", LIVE_POLL_BARS)
        except Exception:
            return []

        if df_new.empty:
            return []

        old_df = self._rolling_df
        old_last_time = old_df.iloc[-1]["time"]

        # Merge new tail into rolling_df
        existing_times = set(old_df["time"].astype(str))
        new_rows = []
        for _, row in df_new.iterrows():
            t_str = str(row["time"])
            if t_str in existing_times:
                mask = old_df["time"].astype(str) == t_str
                if mask.any():
                    idx = old_df.index[mask][0]
                    for col in ["open", "high", "low", "close", "volume", "spread"]:
                        if col in row.index:
                            old_df.at[idx, col] = row[col]
            else:
                new_rows.append(row)

        if new_rows:
            merged = pd.concat([old_df, pd.DataFrame(new_rows)], ignore_index=True)
            if len(merged) > HISTORY_BARS:
                merged = merged.iloc[-HISTORY_BARS:].reset_index(drop=True)
            self._rolling_df = merged
        else:
            self._rolling_df = old_df

        df = self._rolling_df
        curr_last_time = df.iloc[-1]["time"]

        # Determine which bars are new (haven't been processed)
        has_new_bars = curr_last_time != old_last_time

        # Recalibrate strategy cache when new bars arrived
        if has_new_bars:
            try:
                self.strategy.on_start(df)
            except Exception as e:
                log.warning(f"on_start recalibration failed: {e}")

        # Find bar indices to process
        new_bar_mask = df["time"] > old_last_time
        new_indices = df.index[new_bar_mask].tolist()
        if not new_indices:
            # Always process the last bar (live/forming bar update)
            new_indices = [len(df) - 1]

        signals = []
        for idx in new_indices:
            row = df.iloc[idx]
            b_time = row["time"]
            t_str = self._fmt_time(b_time)

            # Check active trades
            for s in self._check_active_trade_hits(row, t_str):
                signals.append(s)

            try:
                raw = self.strategy.on_bar(idx, df)
                direction, sl, tp = self._parse_signal(raw)
                if direction in ("BUY", "SELL") and self._last_signal_time != b_time:
                    # Bug 4: HTF-bar dedup
                    current_htf_idx = -1
                    cache = getattr(self.strategy, "_cache", {})
                    m1_to_htf = cache.get("m1_to_htf", [])
                    if idx < len(m1_to_htf):
                        current_htf_idx = m1_to_htf[idx]
                    if current_htf_idx > -1 and current_htf_idx == self._last_signal_htf_idx:
                        continue  # Same HTF bar already signaled — skip duplicate

                    self._last_signal_time = b_time
                    self._last_signal_htf_idx = current_htf_idx
                    trade = {
                        "id": str(uuid.uuid4()),
                        "type": "signal",
                        "symbol": self.symbol,
                        "timeframe": "M1",
                        "strategy": self.strategy_name,
                        "direction": direction,
                        "price": float(row["close"]),
                        "sl": sl,
                        "tp": tp,
                        "time": t_str,
                        "bar_time": t_str,
                        "status": "RUNNING",
                    }
                    self._active_trades.append(trade)
                    signals.append(trade)
            except Exception:
                pass

        return signals

    # ── Binance WebSocket ────────────────────────────────────────

    def _start_binance_ws(self):
        if not websocket:
            return
        self._ws_thread = threading.Thread(target=self._binance_ws_loop, daemon=True)
        self._ws_thread.start()

    def _binance_ws_loop(self):
        """Bug 8: Iterative reconnect — no recursion, no stack overflow risk."""
        symbol_lower = self.symbol.lower()
        url = f"wss://fstream.binance.com/ws/{symbol_lower}@kline_1m"

        def on_message(ws, raw_msg):
            try:
                msg = json.loads(raw_msg)
                if "k" not in msg:
                    return
                k = msg["k"]
                if not k.get("x", False):
                    return  # Only process completed M1 bars
                bar_time = datetime.utcfromtimestamp(int(k["t"]) / 1000)
                new_row = {
                    "time": bar_time,
                    "open": float(k["o"]), "high": float(k["h"]),
                    "low": float(k["l"]), "close": float(k["c"]),
                    "volume": float(k["v"]), "spread": 0,
                }
                self._on_new_m1_bar(new_row)
            except Exception:
                pass

        while self._ws_running:
            try:
                ws_app = websocket.WebSocketApp(url, on_message=on_message)
                ws_app.run_forever()
            except Exception:
                pass
            if self._ws_running:
                time.sleep(3)  # Wait before reconnecting

    def _on_new_m1_bar(self, bar_dict: dict):
        """Handle a new completed M1 bar from Binance WS."""
        if self._rolling_df is None:
            return

        new_row_df = pd.DataFrame([bar_dict])
        df = pd.concat([self._rolling_df, new_row_df], ignore_index=True)
        if len(df) > HISTORY_BARS:
            df = df.iloc[-HISTORY_BARS:].reset_index(drop=True)
        self._rolling_df = df

        try:
            self.strategy.on_start(df)
        except Exception:
            pass

        idx = len(df) - 1
        bar = df.iloc[idx]
        t_str = self._fmt_time(bar["time"])

        # Bug 5: capture trade updates and publish them via SignalBus
        trade_updates = self._check_active_trade_hits(bar, t_str)
        if trade_updates:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    for upd in trade_updates:
                        asyncio.run_coroutine_threadsafe(
                            self._publish_trade_update(upd), loop
                        )
            except Exception:
                pass

        try:
            raw = self.strategy.on_bar(idx, df)
            direction, sl, tp = self._parse_signal(raw)
            if direction in ("BUY", "SELL") and self._last_signal_time != bar["time"]:
                # Bug 4: HTF-bar dedup (Binance WS path)
                current_htf_idx = -1
                cache = getattr(self.strategy, "_cache", {})
                m1_to_htf = cache.get("m1_to_htf", [])
                if idx < len(m1_to_htf):
                    current_htf_idx = m1_to_htf[idx]
                if current_htf_idx > -1 and current_htf_idx == self._last_signal_htf_idx:
                    return  # Same HTF bar already signaled

                self._last_signal_time = bar["time"]
                self._last_signal_htf_idx = current_htf_idx
                sig = {
                    "id": str(uuid.uuid4()),
                    "type": "signal",
                    "symbol": self.symbol,
                    "timeframe": "M1",
                    "strategy": self.strategy_name,
                    "direction": direction,
                    "price": float(bar["close"]),
                    "sl": sl, "tp": tp,
                    "time": t_str, "bar_time": t_str,
                    "status": "RUNNING",
                }
                self._active_trades.append(sig)
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.run_coroutine_threadsafe(self._publish(sig), loop)
                except Exception:
                    pass
                log.info(f"Signal | {direction} {self.symbol} [M1] @ {bar['close']}")
        except Exception:
            pass

    async def _publish(self, sig: dict):
        from signals.bus import SignalBus
        await SignalBus.get().publish(sig)

    async def _publish_trade_update(self, upd: dict):
        """Bug 5: Publish trade status update (TP/SL hit) to SignalBus."""
        from signals.bus import SignalBus
        await SignalBus.get().publish_trade_update(upd)

    # ── Helpers ─────────────────────────────────────────────────

    def _check_active_trade_hits(self, bar, t_str: str) -> List[Dict]:
        """Check if bar hits SL or TP of any active trade. Returns trade_update dicts."""
        updates = []
        for t in self._active_trades[:]:
            hit = None
            if t["direction"] == "BUY":
                if t["sl"] is not None and float(bar["low"]) <= t["sl"]:
                    hit = "SL HIT"
                elif t["tp"] is not None and float(bar["high"]) >= t["tp"]:
                    hit = "TP HIT"
            elif t["direction"] == "SELL":
                if t["sl"] is not None and float(bar["high"]) >= t["sl"]:
                    hit = "SL HIT"
                elif t["tp"] is not None and float(bar["low"]) <= t["tp"]:
                    hit = "TP HIT"
            if hit:
                t["status"] = hit
                t["close_time"] = t_str
                self._active_trades.remove(t)
                updates.append({
                    "type": "trade_update",
                    "id": t["id"],
                    "status": hit,
                    "close_time": t_str,
                    "symbol": self.symbol,
                    "timeframe": "M1",
                })
        return updates

    @staticmethod
    def _fmt_time(t) -> str:
        s = t.isoformat() if hasattr(t, "isoformat") else str(t)
        if not s.endswith("Z") and "+" not in s:
            s += "Z"
        return s

    @staticmethod
    def _parse_signal(raw) -> Tuple:
        if isinstance(raw, tuple) and len(raw) >= 1:
            direction = str(raw[0]).upper() if raw[0] else "HOLD"
            sl = float(raw[1]) if len(raw) > 1 and raw[1] is not None else None
            tp = float(raw[2]) if len(raw) > 2 and raw[2] is not None else None
            return direction, sl, tp
        return str(raw).upper() if raw else "HOLD", None, None


# ── Backward-compat alias (router.py imports MTFLiveEngine) ──────
MTFLiveEngine = LiveScanEngine
