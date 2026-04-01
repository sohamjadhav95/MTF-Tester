import numpy as np
import pandas as pd
from typing import Literal
from pydantic import Field
from strategies._template import BaseStrategy, StrategyConfig

class VWAPStrategyConfig(StrategyConfig):
    """Configuration parameters for the VWAP Strategy."""
    
    atr_period: int = Field(14, ge=2, le=100, description="ATR Period (for Stop Loss)")
    sl_type: Literal["ATR", "Candle Extremes"] = Field("ATR", description="Stop Loss Calculation Method")
    sl_multiplier: float = Field(1.5, ge=0.1, le=10.0, description="ATR Multiplier (if ATR SL is selected)")
    rr_ratio: float = Field(2.0, ge=0.1, le=20.0, description="Risk/Reward Ratio (for Take Profit)")


class VWAPStrategy(BaseStrategy):
    name = "VWAP Cross with Dynamic SL"
    description = "Buys when price closes above daily VWAP, sells when it closes below. SL based on ATR or candle extremes."
    config_model = VWAPStrategyConfig

    def on_start(self, data: pd.DataFrame):
        """
        Pre-compute Daily VWAP and ATR, storing them in self._cache.
        data contains the full dataset (all bars).
        """
        cfg = self.config
        
        # 1. Calculate Daily Reset VWAP
        typical_price = (data["high"] + data["low"] + data["close"]) / 3.0
        pv = typical_price * data["volume"]
        
        # Group by date to reset cumulative sums daily
        dates = pd.to_datetime(data["time"]).dt.date
        cum_pv = pv.groupby(dates).cumsum()
        cum_vol = data["volume"].groupby(dates).cumsum()
        vwap = (cum_pv / cum_vol).values
        
        # 2. Calculate ATR
        high = data["high"].values
        low = data["low"].values
        close = data["close"].values
        
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0] # Handle the first element safely
        
        tr1 = high - low
        tr2 = np.abs(high - prev_close)
        tr3 = np.abs(low - prev_close)
        
        # Maximum of the three TR components
        tr = np.maximum(tr1, np.maximum(tr2, tr3))
        
        # Simple moving average of True Range
        atr = pd.Series(tr).rolling(window=cfg.atr_period).mean().values
        
        self._cache = {
            "vwap": vwap,
            "atr": atr
        }

    def on_bar(self, index: int, data: pd.DataFrame):
        """
        Evaluate VWAP crossovers and determine entry, SL, and TP on every bar.
        """
        cfg = self.config
        cache = getattr(self, "_cache", None)
        
        if cache is None or index < 1:
            return "HOLD"
            
        vwap_val = cache["vwap"][index]
        prev_vwap = cache["vwap"][index - 1]
        atr_val = cache["atr"][index]
        
        # Ensure we have valid calculated data before triggering signals
        if np.isnan(vwap_val) or np.isnan(prev_vwap) or np.isnan(atr_val):
            return "HOLD"
            
        bar = data.iloc[index]
        prev_bar = data.iloc[index - 1]
        
        close_price = float(bar["close"])
        prev_close = float(prev_bar["close"])
        high_price = float(bar["high"])
        low_price = float(bar["low"])
        
        # Check for Crossovers
        cross_up = prev_close <= prev_vwap and close_price > vwap_val
        cross_down = prev_close >= prev_vwap and close_price < vwap_val
        
        if cross_up:
            # Determine Stop Loss (Absolute Price)
            if cfg.sl_type == "ATR":
                sl = close_price - (atr_val * cfg.sl_multiplier)
            else:
                sl = low_price
                
            # Determine Take Profit based on Risk/Reward Ratio (Absolute Price)
            risk = close_price - sl
            if risk <= 0:  # Safety catch to avoid division/logic errors
                return "HOLD"
            tp = close_price + (risk * cfg.rr_ratio)
            
            return ("BUY", sl, tp)
            
        if cross_down:
            # Determine Stop Loss (Absolute Price)
            if cfg.sl_type == "ATR":
                sl = close_price + (atr_val * cfg.sl_multiplier)
            else:
                sl = high_price
                
            # Determine Take Profit based on Risk/Reward Ratio (Absolute Price)
            risk = sl - close_price
            if risk <= 0:  # Safety catch to avoid division/logic errors
                return "HOLD"
            tp = close_price - (risk * cfg.rr_ratio)
            
            return ("SELL", sl, tp)
            
        return "HOLD"

    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        """
        Return indicators for chart overlay.
        VWAP overlays on price. ATR drops into a lower pane due to the 'oscillator' keyword.
        """
        cache = getattr(self, "_cache", None)
        if not cache:
            return {}
            
        def to_list(arr):
            return [None if np.isnan(v) else round(float(v), 6) for v in arr]
            
        return {
            "VWAP": to_list(cache["vwap"]),
            "ATR oscillator": to_list(cache["atr"]) 
        }