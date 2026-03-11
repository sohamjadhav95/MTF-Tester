import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from app.core.registry import auto_discover_strategies
from app.providers.base_provider import DataProvider

class MTFLiveEngine:
    def __init__(self, symbol: str, timeframes: List[str], strategy_name: str, settings: Dict, provider: DataProvider):
        self.symbol = symbol
        self.timeframes = timeframes
        self.strategy_name = strategy_name
        self.settings = settings
        self.provider = provider
        
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
        
    def get_historical_context(self) -> Tuple[Dict[str, List[Dict]], List[Dict]]:
        historical_candles = {}
        historical_signals = []
        
        for tf in self.timeframes:
            try:
                df = self.provider.fetch_latest_bars(self.symbol, tf, 200)
            except Exception as e:
                print(f"Error fetching historical bars for {tf}: {e}")
                continue
                
            if df.empty:
                continue
                
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
            
            strategy = self.strategies[tf]
            start_idx = max(0, len(df) - 50)  # evaluate last 50 bars for recent signals
            for i in range(start_idx, len(df)):
                try:
                    raw_signal = strategy.on_bar(i, df)
                    signal_dir, sl, tp = self._parse_signal(raw_signal)
                    
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
                                "sl": sl,
                                "tp": tp
                            })
                except Exception:
                    continue
                    
        historical_signals.sort(key=lambda x: x["time"], reverse=True)
        return historical_candles, historical_signals

    def process_latest_data(self) -> Tuple[List[Dict], List[Dict]]:
        """
        Fetches the latest bars for each timeframe.
        Calls strategy.on_bar() on the newest bar.
        Returns (list_of_signals, list_of_bar_updates).
        """
        signals = []
        updates = []
        
        for tf in self.timeframes:
            try:
                df = self.provider.fetch_latest_bars(self.symbol, tf, 200)
            except Exception:
                continue
                
            if df.empty:
                continue
                
            # The current forming bar is the last one in the dataframe
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
            except Exception as e:
                print(f"Error in strategy {self.strategy_name} on {tf}: {e}")
                continue
                
            # Parse signal
            signal_dir, sl, tp = self._parse_signal(raw_signal)
            
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
                        "time": datetime.now().isoformat(),
                        "bar_time": current_time.isoformat(),
                        "sl": sl,
                        "tp": tp
                    })
                    
        return signals, updates
        
    def _parse_signal(self, raw) -> Tuple[str, Optional[float], Optional[float]]:
        if isinstance(raw, tuple):
            signal = str(raw[0]).upper() if raw else "HOLD"
            sl = float(raw[1]) if len(raw) > 1 and raw[1] is not None else None
            tp = float(raw[2]) if len(raw) > 2 and raw[2] is not None else None
            return signal, sl, tp
        signal = str(raw).upper() if raw else "HOLD"
        return signal, None, None
