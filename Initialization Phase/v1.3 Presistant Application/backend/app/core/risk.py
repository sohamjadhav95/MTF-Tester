"""
Risk Manager
============
Independent risk management layer, injectable into the backtesting engine.

Strategy emits SIGNAL + SL/TP.
Risk manager decides VOLUME based on balance, SL distance, and risk rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RiskManager:
    """
    Position-sizing and risk-limiting logic.

    The engine calls `calculate_position_size()` before opening a trade.
    If `fixed_lot_size` is set, it always returns that value.
    Otherwise it sizes the position so the SL distance risks at most
    `max_risk_per_trade_pct` percent of the current balance.

    Attributes:
        max_risk_per_trade_pct: Maximum % of balance to risk per trade.
        fixed_lot_size:         If set, overrides dynamic sizing.
        max_open_exposure:      (Future) Max aggregate lot exposure.
    """

    max_risk_per_trade_pct: float = 1.0       # 1 % of balance
    fixed_lot_size: Optional[float] = None    # override dynamic sizing
    max_open_exposure: Optional[float] = None  # reserved for future use

    def calculate_position_size(
        self,
        balance: float,
        sl_distance: float,
        contract_size: float = 100_000.0,
        point: float = 0.00001,
        volume_step: float = 0.01,
        volume_min: float = 0.01,
        volume_max: float = 100.0,
    ) -> float:
        """
        Calculate lot size for a trade.

        Args:
            balance:        Current account balance.
            sl_distance:    Distance from entry to SL in price units.
            contract_size:  E.g. 100 000 for standard forex lot.
            point:          Smallest price increment.
            volume_step:    Broker volume granularity.
            volume_min:     Broker minimum lot.
            volume_max:     Broker maximum lot.

        Returns:
            Lot size (float), clamped to [volume_min, volume_max],
            rounded to nearest volume_step.
        """
        # ── Fixed override ──────────────────────────────────────
        if self.fixed_lot_size is not None:
            return max(volume_min, min(self.fixed_lot_size, volume_max))

        # ── Dynamic sizing ──────────────────────────────────────
        if sl_distance <= 0 or balance <= 0:
            return volume_min

        risk_amount = balance * (self.max_risk_per_trade_pct / 100.0)
        raw_lots = risk_amount / (sl_distance * contract_size)

        # Round to nearest volume_step
        if volume_step > 0:
            raw_lots = round(raw_lots / volume_step) * volume_step

        # Clamp
        raw_lots = max(volume_min, min(raw_lots, volume_max))

        return round(raw_lots, 8)
