import pandas as pd
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime
from app.core.registry import auto_discover_strategies
from app.providers.base_provider import DataProvider
import threading
import json
import time

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
    def __init__(
        self, 
        symbol: str, 
        timeframes: List[str], 
        strategy_name: str, 
        settings: Dict, 
        provider: DataProvider,
        broadcast_callback: Optional[Callable] = None,
        start_time: Optional[str] = None
    ):
        self.symbol = symbol
        self.timeframes = timeframes
        self.strategy_name = strategy_name
        self.settings = settings
        self.provider = provider
        self.broadcast_callback = broadcast_callback
        
        self.strategy_registry = auto_discover_strategies()
        if strategy_name not in self.strategy_registry:
            raise ValueError(f"Strategy {strategy_name} not found.")
            
        self.strategy_cls = self.strategy_registry[strategy_name]
        
        # Instantiate a strategy instance for each timeframe
        self.strategies = {}
        for tf in timeframes:
            self.strategies[tf] = self.strategy_cls(settings=settings)
            
        # Keep track of the last processed close time per timeframe to avoid duplicate signals
        self.last_signal_time = {tf: None for tf in timeframes}
        
        self._rolling_df: Dict[str, pd.DataFrame] = {}
        self._HISTORY_BARS = 300
        
        self._ws_running = True
        self._ws_threads = []
        
        # Detect Binance vs MT5 (Binance has a _session in its provider)
        self.is_binance = hasattr(self.provider, "_session")
        
        self.start_time_dt = None
        if start_time:
            from dateutil.parser import parse
            try:
                self.start_time_dt = parse(start_time).replace(tzinfo=None)
            except Exception:
                pass
        
    def _push(self, payload: dict):
        if self.broadcast_callback:
            self.broadcast_callback(payload)
            
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
            except Exception as e:
                import traceback
                traceback.print_exc()
                
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
        
        # Always push live bar to browser
        self._push({"type": "bar_updates", "data": [{"symbol": self.symbol, "timeframe": tf, "bar": bar}]})
        
        is_closed = k.get("x", False)
        
        # Update rolling DF
        if tf in self._rolling_df:
            df = self._rolling_df[tf]
            if not df.empty:
                last_time = df.iloc[-1]["time"]
                
                new_row_dict = {
                    "time": bar_time,
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                    "volume": bar["volume"]
                }
                new_row_df = pd.DataFrame([new_row_dict])
                
                if last_time == bar_time:
                    # Update in-place
                    for col in ["open", "high", "low", "close", "volume"]:
                        df.at[df.index[-1], col] = bar[col]
                else:
                    # Append new row
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
                                "time": datetime.utcnow().isoformat(),
                                "bar_time": bar_time_str,
                            }
                            self._push({"type": "signal", "data": sig})
                except Exception as e:
                    import traceback
                    traceback.print_exc()

    def get_historical_context(self) -> Tuple[Dict[str, List[Dict]], List[Dict], Dict[str, Dict[str, List[Dict]]]]:
        historical_candles = {}
        historical_signals = []
        historical_indicators = {}
        
        for tf in self.timeframes:
            try:
                if self.start_time_dt:
                    df = self.provider.fetch_ohlcv(
                        self.symbol, 
                        tf, 
                        self.start_time_dt, 
                        datetime.utcnow()
                    )
                else:
                    df = self.provider.fetch_latest_bars(self.symbol, tf, self._HISTORY_BARS)
            except Exception as e:
                continue
                
            if df.empty:
                continue
                
            self._rolling_df[tf] = df.copy()
            
            candles = []
            for _, row in df.iterrows():
                candles.append({
                    "time": row["time"].isoformat(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"] if pd.notna(row["volume"]) else 0)
                })
            historical_candles[tf] = candles
            
            # Indicator calculation
            strategy = self.strategies[tf]
            try:
                ind_raw = strategy.get_indicator_data(df)
            except AttributeError:
                ind_raw = {}
                
            tf_indicators = {}
            for name, points in ind_raw.items():
                fmt_points = []
                for idx, val in enumerate(points):
                    if val is not None and not pd.isna(val):
                        fmt_points.append({
                            "time": df.iloc[idx]["time"].isoformat(),
                            "value": val
                        })
                tf_indicators[name] = fmt_points
            historical_indicators[tf] = tf_indicators
            
            if self.start_time_dt:
                start_idx = 0
            else:
                start_idx = max(0, len(df) - 50)  # evaluate last 50 bars for recent signals
                
            for i in range(start_idx, len(df)):
                try:
                    raw_signal = strategy.on_bar(i, df)
                    signal_dir = self._parse_signal(raw_signal)
                    
                    if signal_dir in ("BUY", "SELL"):
                        bar_time = df.iloc[i]["time"]
                        # Prevent duplicate signals on same bar
                        if self.last_signal_time[tf] != bar_time:
                            self.last_signal_time[tf] = bar_time
                            historical_signals.append({
                                "symbol": self.symbol,
                                "timeframe": tf,
                                "strategy": self.strategy_name,
                                "direction": signal_dir,
                                "price": float(df.iloc[i]["close"]),
                                "time": bar_time.isoformat(),
                                "bar_time": bar_time.isoformat(),
                            })
                except Exception:
                    continue
                    
        historical_signals.sort(key=lambda x: x["time"], reverse=True)
        
        # Now start websocket streams if Binance
        if self.is_binance:
            self._start_binance_streams()
            
        return historical_candles, historical_signals, historical_indicators

    def process_latest_data(self) -> Tuple[List[Dict], List[Dict]]:
        """
        Fetches the latest data via REST polling (used primarily for MT5, 
        or Binance fallback if websocket is not available).
        """
        signals = []
        updates = []
        
        for tf in self.timeframes:
            try:
                # Fetch ONLY 3 bars per poll
                df_latest = self.provider.fetch_latest_bars(self.symbol, tf, 3)
            except Exception:
                continue
                
            if df_latest.empty:
                continue
                
            # Update rolling DF
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
            
            # Keep bar update for frontend chart drawing
            bar_dict = {
                "time": current_time.isoformat(),
                "open": float(df.iloc[current_idx]["open"]),
                "high": float(df.iloc[current_idx]["high"]),
                "low": float(df.iloc[current_idx]["low"]),
                "close": float(df.iloc[current_idx]["close"]),
                "volume": int(df.iloc[current_idx]["volume"] if pd.notna(df.iloc[current_idx]["volume"]) else 0)
            }
            updates.append({"symbol": self.symbol, "timeframe": tf, "bar": bar_dict})

            # Evaluate Strategy
            strategy = self.strategies[tf]
            try:
                raw_signal = strategy.on_bar(current_idx, df)
            except Exception:
                continue
                
            # Parse signal
            signal_dir = self._parse_signal(raw_signal)
            
            if signal_dir in ("BUY", "SELL"):
                # Ensure we only broadcast one signal per bar to avoid spam
                if self.last_signal_time[tf] != current_time:
                    self.last_signal_time[tf] = current_time
                    signals.append({
                        "symbol": self.symbol,
                        "timeframe": tf,
                        "strategy": self.strategy_name,
                        "direction": signal_dir,
                        "price": float(df.iloc[current_idx]["close"]),
                        "time": datetime.utcnow().isoformat(),
                        "bar_time": current_time.isoformat(),
                    })
                    
        return signals, updates

    def stop(self):
        self._ws_running = False
        
    @staticmethod
    def _parse_signal(raw) -> str:
        if isinstance(raw, tuple):
            return str(raw[0]).upper() if raw else "HOLD"
        return str(raw).upper() if raw else "HOLD"
