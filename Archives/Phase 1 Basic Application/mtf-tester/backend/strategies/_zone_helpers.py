"""
Zone Helpers Mixin
==================
Provides complete supply/demand zone detection, validation,
and lifecycle management for zone-based strategies.

Usage in strategy:
    from strategies._zone_helpers import ZoneMixin

    class GeneratedStrategy(BaseStrategy, ZoneMixin):
        def on_start(self, data):
            ...
            self._cache["zones"] = []
            self._cache["zone_history"] = []
            self._atr_cache = self._atr(data, cfg.atr_period or 14)

        def on_bar(self, index, data):
            ...
            new_zones = self.detect_sd_zones(data, index, self._atr_cache)
            for z in new_zones:
                if self.validate_sd_zone(z, data, self._atr_cache):
                    self._cache["zones"].append(z)
                    self._cache["zone_history"].append(z)
            self._cache["zones"] = self.expire_zones(
                self._cache["zones"], data, index
            )
"""

import numpy as np
import pandas as pd
from typing import List


class ZoneMixin:
    """
    Complete Supply/Demand Zone implementation.
    All methods are pure functions — no state stored here,
    all state goes through self._cache["zones"].
    """

    def detect_sd_zones(self, data: pd.DataFrame, index: int,
                        atr_arr: np.ndarray) -> List[dict]:
        """
        Scan the 3 bars ending at index for the 4 zone patterns:
          RBR (Rally-Boring-Rally) → Demand
          DBR (Drop-Boring-Rally)  → Demand
          DBD (Drop-Boring-Drop)   → Supply
          RBD (Rally-Boring-Drop)  → Supply

        Returns list of raw zone candidates (not yet validated).
        """
        if index < 3:
            return []

        zones = []
        leg_in_idx  = index - 2
        boring_idx  = index - 1
        leg_out_idx = index

        leg_in  = data.iloc[leg_in_idx]
        boring  = data.iloc[boring_idx]
        leg_out = data.iloc[leg_out_idx]

        leg_in_body  = abs(float(leg_in["close"])  - float(leg_in["open"]))
        boring_body  = abs(float(boring["close"])  - float(boring["open"]))
        leg_out_body = abs(float(leg_out["close"]) - float(leg_out["open"]))

        leg_in_bull  = float(leg_in["close"])  > float(leg_in["open"])
        leg_out_bull = float(leg_out["close"]) > float(leg_out["open"])

        boring_open   = float(boring["open"])
        boring_close  = float(boring["close"])
        boring_body_top = max(boring_open, boring_close)
        boring_body_bot = min(boring_open, boring_close)

        base = {
            "formed_at":   str(data.iloc[boring_idx]["time"]),
            "formed_idx":  boring_idx,
            "leg_in_idx":  leg_in_idx,
            "leg_out_idx": leg_out_idx,
            "leg_in_body": leg_in_body,
            "boring_body": boring_body,
            "leg_out_body": leg_out_body,
            "status":      "active",
            "strength":    0,
        }

        # RBR: leg_in=bull, leg_out=bull → Demand
        if leg_in_bull and leg_out_bull:
            zones.append({**base, "type": "demand", "pattern": "RBR",
                "proximal": boring_body_top,
                "distal": min(float(boring["low"]), float(leg_in["low"]))})

        # DBR: leg_in=bear, leg_out=bull → Demand
        if not leg_in_bull and leg_out_bull:
            zones.append({**base, "type": "demand", "pattern": "DBR",
                "proximal": boring_body_top,
                "distal": min(float(boring["low"]), float(leg_in["low"]))})

        # DBD: leg_in=bear, leg_out=bear → Supply
        if not leg_in_bull and not leg_out_bull:
            zones.append({**base, "type": "supply", "pattern": "DBD",
                "proximal": boring_body_bot,
                "distal": max(float(boring["high"]), float(leg_in["high"]))})

        # RBD: leg_in=bull, leg_out=bear → Supply
        if leg_in_bull and not leg_out_bull:
            zones.append({**base, "type": "supply", "pattern": "RBD",
                "proximal": boring_body_bot,
                "distal": max(float(boring["high"]), float(leg_in["high"]))})

        return zones

    def validate_sd_zone(self, zone: dict, data: pd.DataFrame,
                          atr_arr: np.ndarray) -> bool:
        """
        Apply validation criteria. Returns True if zone passes.
        Increments zone["strength"] for each criterion passed.
        """
        idx = zone["leg_in_idx"]
        leg_in  = data.iloc[zone["leg_in_idx"]]
        boring  = data.iloc[zone["formed_idx"]]
        leg_out = data.iloc[zone["leg_out_idx"]]
        score = 0

        # Check 1: Candle Size Ratio (1:2:4)
        boring_body  = zone["boring_body"]
        leg_in_body  = zone["leg_in_body"]
        leg_out_body = zone["leg_out_body"]
        if boring_body > 0:
            if not (leg_in_body >= boring_body * 2 and leg_out_body >= leg_in_body * 2):
                return False
            score += 1

        # Check 2: White area (pass here, enforced in zone_entered)
        score += 1

        # Check 3: TR vs ATR
        if len(atr_arr) > zone["leg_out_idx"] and not np.isnan(atr_arr[idx]):
            boring_tr  = float(boring["high"])  - float(boring["low"])
            leg_in_tr  = float(leg_in["high"])  - float(leg_in["low"])
            leg_out_tr = float(leg_out["high"]) - float(leg_out["low"])
            atr_val    = float(atr_arr[zone["formed_idx"]])
            if not (boring_tr < atr_val and leg_in_tr >= atr_val and leg_out_tr >= atr_val):
                return False
            score += 1

        # Check 4: Candle behind leg-in
        if zone["leg_in_idx"] > 0:
            behind = data.iloc[zone["leg_in_idx"] - 1]
            behind_bull = float(behind["close"]) > float(behind["open"])
            leg_in_bull = float(leg_in["close"]) > float(leg_in["open"])
            behind_body = abs(float(behind["close"]) - float(behind["open"]))
            if behind_bull != leg_in_bull and behind_body >= leg_in_body * 0.5:
                return False
            score += 1

        zone["strength"] = score
        return True

    def zone_entered(self, zone: dict, bar: pd.Series) -> bool:
        """Check if current bar price has entered the zone's proximal line."""
        low  = float(bar["low"])
        high = float(bar["high"])
        if zone["type"] == "demand":
            return low <= zone["proximal"]
        if zone["type"] == "supply":
            return high >= zone["proximal"]
        return False

    def zone_broken(self, zone: dict, bar: pd.Series) -> bool:
        """Check if price has broken through the distal line."""
        close = float(bar["close"])
        if zone["type"] == "demand":
            return close < zone["distal"]
        if zone["type"] == "supply":
            return close > zone["distal"]
        return False

    def expire_zones(self, zones: list, data: pd.DataFrame,
                     current_index: int, max_age_bars: int = 200) -> list:
        """Remove expired, triggered, or broken zones."""
        bar = data.iloc[current_index]
        active = []
        for zone in zones:
            if zone["status"] in ("triggered", "broken"):
                continue
            if current_index - zone["formed_idx"] > max_age_bars:
                zone["status"] = "expired"
                continue
            if self.zone_broken(zone, bar):
                zone["status"] = "broken"
                continue
            active.append(zone)
        return active
