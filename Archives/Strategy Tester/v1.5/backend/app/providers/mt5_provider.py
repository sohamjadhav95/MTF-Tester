"""
MT5 Data Provider
=================
Concrete implementation of DataProvider for MetaTrader 5.
Merges the old mt5/connection.py and data/provider.py into one class.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.providers.base_provider import DataProvider


def _get_mt5():
    """
    Lazy import of MetaTrader5.
    Returns the module or raises ImportError with a helpful message.
    """
    try:
        import MetaTrader5 as mt5
        return mt5
    except ImportError as e:
        raise RuntimeError(
            f"Failed to import MetaTrader5: {e}. "
            "Ensure the MetaTrader5 package is installed: pip install MetaTrader5"
        )
    except Exception as e:
        raise RuntimeError(f"MetaTrader5 import error: {e}")


class MT5Provider(DataProvider):
    """MetaTrader 5 data provider — connection, symbols, and OHLCV data."""

    def __init__(self) -> None:
        self._connected = False
        self._account_info: dict | None = None

    # ── DataProvider interface ──────────────────────────────────
    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def account_info(self) -> dict | None:
        return self._account_info

    def connect(self, **kwargs) -> dict:
        """
        Initialize MT5 terminal and login.
        Expected kwargs: server (str), login (int), password (str).
        """
        server = kwargs.get("server", "")
        login = kwargs.get("login", 0)
        password = kwargs.get("password", "")

        try:
            mt5 = _get_mt5()
        except RuntimeError as e:
            return {"success": False, "error": str(e)}

        if not mt5.initialize():
            err = mt5.last_error()
            return {
                "success": False,
                "error": f"MT5 initialization failed: {err}. "
                         "Make sure MetaTrader 5 terminal is running.",
            }

        authorized = mt5.login(login=login, password=password, server=server)
        if not authorized:
            error = mt5.last_error()
            mt5.shutdown()
            return {"success": False, "error": f"MT5 login failed: {error}"}

        info = mt5.account_info()
        if info is None:
            mt5.shutdown()
            return {"success": False, "error": "Failed to retrieve account info after login."}

        self._connected = True
        self._account_info = {
            "login": info.login,
            "server": info.server,
            "name": info.name,
            "balance": info.balance,
            "currency": info.currency,
            "leverage": info.leverage,
            "company": info.company,
        }
        return {"success": True, "account": self._account_info}

    def disconnect(self) -> dict:
        """Shutdown MT5 connection."""
        if self._connected:
            try:
                mt5 = _get_mt5()
                mt5.shutdown()
            except Exception:
                pass
            self._connected = False
            self._account_info = None
        return {"success": True, "message": "Disconnected from MT5"}

    def get_symbols(self, group: str = "*") -> list[dict]:
        """Get available symbols from MT5."""
        if not self._connected:
            return []
        try:
            mt5 = _get_mt5()
        except RuntimeError:
            return []

        symbols = mt5.symbols_get(group=group)
        if symbols is None:
            return []

        result = []
        for s in symbols:
            result.append({
                "name": s.name,
                "description": s.description,
                "path": s.path,
                "spread": s.spread,
                "digits": s.digits,
                "point": s.point,
                "trade_contract_size": s.trade_contract_size,
                "currency_base": s.currency_base,
                "currency_profit": s.currency_profit,
            })
        return result

    def get_symbol_info(self, symbol: str) -> dict | None:
        """Get detailed info for a specific symbol."""
        if not self._connected:
            return None
        try:
            mt5 = _get_mt5()
        except RuntimeError:
            return None

        info = mt5.symbol_info(symbol)
        if info is None:
            return None

        return {
            "name": info.name,
            "description": info.description,
            "digits": info.digits,
            "point": info.point,
            "spread": info.spread,
            "trade_contract_size": info.trade_contract_size,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "currency_base": info.currency_base,
            "currency_profit": info.currency_profit,
            "currency_margin": info.currency_margin,
            "trade_tick_value": info.trade_tick_value,
            "trade_tick_size": info.trade_tick_size,
        }

    def get_timeframes(self) -> list[dict]:
        """Return supported MT5 timeframes."""
        return [
            {"value": "M1",  "label": "1 Minute"},
            {"value": "M5",  "label": "5 Minutes"},
            {"value": "M15", "label": "15 Minutes"},
            {"value": "M30", "label": "30 Minutes"},
            {"value": "H1",  "label": "1 Hour"},
            {"value": "H4",  "label": "4 Hours"},
            {"value": "D1",  "label": "Daily"},
            {"value": "W1",  "label": "Weekly"},
            {"value": "MN1", "label": "Monthly"},
        ]

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        date_from: datetime,
        date_to: datetime,
    ) -> pd.DataFrame:
        """Fetch OHLCV data from MT5."""
        mt5 = _get_mt5()

        tf = self._get_timeframe_const(timeframe)
        if tf is None:
            valid_tfs = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
            raise ValueError(
                f"Invalid timeframe '{timeframe}'. Valid options: {valid_tfs}"
            )

        selected = mt5.symbol_select(symbol, True)
        if not selected:
            raise ValueError(
                f"Symbol '{symbol}' not found or could not be selected in MT5"
            )

        rates = mt5.copy_rates_range(symbol, tf, date_from, date_to)

        if rates is None or len(rates) == 0:
            error = mt5.last_error()
            raise ValueError(
                f"No data returned for {symbol} {timeframe} "
                f"from {date_from} to {date_to}. MT5 error: {error}"
            )

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.rename(columns={"tick_volume": "volume"})
        df = df[["time", "open", "high", "low", "close", "volume", "spread"]]
        df = df.reset_index(drop=True)
        return df

    # ── Private helpers ─────────────────────────────────────────
    @staticmethod
    def _get_timeframe_const(timeframe_str: str):
        """Map string timeframe to MT5 constant (lazy import)."""
        mt5 = _get_mt5()
        mapping = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
            "W1": mt5.TIMEFRAME_W1,
            "MN1": mt5.TIMEFRAME_MN1,
        }
        return mapping.get(timeframe_str)
