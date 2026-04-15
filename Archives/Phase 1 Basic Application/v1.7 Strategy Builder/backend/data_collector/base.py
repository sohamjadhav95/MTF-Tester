"""
Data Provider Interface
=======================
Abstract base for all data providers (MT5, CSV, Crypto, etc.).
Engine depends on this interface, NOT on any specific provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import pandas as pd


class DataProvider(ABC):
    """
    Abstract data provider contract.

    Implement this to add a new data source
    (e.g. CSV files, crypto exchange, database).
    """

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Whether the provider is currently connected."""
        ...

    @abstractmethod
    def connect(self, **kwargs: Any) -> dict:
        """Establish connection. Returns {success: bool, ...}."""
        ...

    @abstractmethod
    def disconnect(self) -> dict:
        """Terminate connection. Returns {success: bool, ...}."""
        ...

    @abstractmethod
    def get_symbols(self, group: str = "*") -> list[dict]:
        """Return available trading symbols."""
        ...

    @abstractmethod
    def get_symbol_info(self, symbol: str) -> dict | None:
        """Return detailed info for a specific symbol."""
        ...

    @abstractmethod
    def get_timeframes(self) -> list[dict]:
        """Return supported timeframes."""
        ...

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        date_from: datetime,
        date_to: datetime,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data.

        Returns:
            DataFrame with columns: time, open, high, low, close, volume, spread
        """
        ...

    @abstractmethod
    def fetch_latest_bars(
        self,
        symbol: str,
        timeframe: str,
        num_bars: int = 200,
    ) -> pd.DataFrame:
        """
        Fetch the most recent N bars for a live scanner/engine.
        
        Returns:
            DataFrame with minimum columns: time, open, high, low, close, volume
        """
        ...
