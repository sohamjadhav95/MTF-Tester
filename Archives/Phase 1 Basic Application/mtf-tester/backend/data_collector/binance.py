"""
Binance Futures Data Provider
==============================
Uses the public Binance FAPI v1 REST API — no API key required for
historical klines data.

Endpoints used:
  GET https://fapi.binance.com/fapi/v1/exchangeInfo  — symbol catalogue
  GET https://fapi.binance.com/fapi/v1/klines         — OHLCV history (paginated)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
import requests

from .base import DataProvider

FAPI_BASE = "https://fapi.binance.com"
_TIMEFRAME_MAP = {
    "M1":  "1m",
    "M3":  "3m",
    "M5":  "5m",
    "M15": "15m",
    "M30": "30m",
    "H1":  "1h",
    "H2":  "2h",
    "H4":  "4h",
    "H6":  "6h",
    "H8":  "8h",
    "H12": "12h",
    "D1":  "1d",
    "W1":  "1w",
    "MN1": "1M",
}
_MAX_BARS_PER_REQUEST = 1500


class BinanceProvider(DataProvider):
    """
    Binance USDT-Margined Futures data provider.
    No authentication needed — uses public endpoints only.
    """

    # ── Shared (module-level) exchange info cache ───────────────
    _exchange_info_cache: Optional[dict] = None

    def __init__(self) -> None:
        self._connected = False
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    # ── DataProvider interface ──────────────────────────────────
    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, **kwargs: Any) -> dict:
        """Binance is always accessible — just validate connectivity."""
        try:
            resp = self._session.get(f"{FAPI_BASE}/fapi/v1/ping", timeout=5)
            resp.raise_for_status()
            self._connected = True
            self._load_exchange_info()
            return {"success": True, "message": "Connected to Binance Futures"}
        except Exception as e:
            return {"success": False, "error": f"Binance connectivity check failed: {e}"}

    def disconnect(self) -> dict:
        self._connected = False
        return {"success": True, "message": "Disconnected from Binance Futures"}

    def _load_exchange_info(self) -> None:
        """Cache exchange info (symbols, contract sizes, tick sizes)."""
        if BinanceProvider._exchange_info_cache is not None:
            return
        try:
            resp = self._session.get(
                f"{FAPI_BASE}/fapi/v1/exchangeInfo", timeout=15
            )
            resp.raise_for_status()
            BinanceProvider._exchange_info_cache = resp.json()
        except Exception:
            BinanceProvider._exchange_info_cache = {"symbols": []}

    def _get_info_cache(self) -> dict:
        if BinanceProvider._exchange_info_cache is None:
            self._load_exchange_info()
        return BinanceProvider._exchange_info_cache or {"symbols": []}

    def get_symbols(self, group: str = "*") -> list[dict]:
        """Return all USDT-perpetual futures symbols from Binance."""
        cache = self._get_info_cache()
        out = []
        for s in cache.get("symbols", []):
            if s.get("contractType") != "PERPETUAL":
                continue
            if s.get("quoteAsset") != "USDT":
                continue
            if s.get("status") != "TRADING":
                continue

            # Extract tick size / lot step
            tick_size = 0.01
            lot_step = 0.001
            for f in s.get("filters", []):
                if f["filterType"] == "PRICE_FILTER":
                    tick_size = float(f.get("tickSize", 0.01))
                if f["filterType"] == "LOT_SIZE":
                    lot_step = float(f.get("stepSize", 0.001))

            digits = max(0, len(f"{tick_size:.10f}".rstrip("0").split(".")[-1]))
            out.append({
                "name": s["symbol"],
                "description": f"{s.get('baseAsset', '')}/USDT Perpetual",
                "path": "Crypto/Futures",
                "spread": 0,
                "digits": digits,
                "point": tick_size,
                "trade_contract_size": lot_step,
                "currency_base": s.get("baseAsset", ""),
                "currency_profit": "USDT",
            })
        return out

    def get_symbol_info(self, symbol: str) -> dict | None:
        """Return contract metadata for a specific symbol."""
        cache = self._get_info_cache()
        for s in cache.get("symbols", []):
            if s["symbol"] != symbol:
                continue
            tick_size = 0.01
            min_qty = 0.001
            step_size = 0.001
            for f in s.get("filters", []):
                if f["filterType"] == "PRICE_FILTER":
                    tick_size = float(f.get("tickSize", 0.01))
                if f["filterType"] == "LOT_SIZE":
                    min_qty = float(f.get("minQty", 0.001))
                    step_size = float(f.get("stepSize", 0.001))

            digits = max(0, len(f"{tick_size:.10f}".rstrip("0").split(".")[-1]))
            return {
                "name": symbol,
                "description": s.get("baseAsset", "") + "/USDT Perpetual",
                "digits": digits,
                "point": tick_size,
                "spread": 0,
                "trade_contract_size": 1.0,  # Binance futures: contract = 1 unit base
                "volume_min": min_qty,
                "volume_max": 1000.0,
                "volume_step": step_size,
                "currency_base": s.get("baseAsset", ""),
                "currency_profit": "USDT",
                "currency_margin": "USDT",
                "trade_tick_value": tick_size,
                "trade_tick_size": tick_size,
            }
        return None

    def get_timeframes(self) -> list[dict]:
        return [
            {"value": "M1",  "label": "1 Minute"},
            {"value": "M3",  "label": "3 Minutes"},
            {"value": "M5",  "label": "5 Minutes"},
            {"value": "M15", "label": "15 Minutes"},
            {"value": "M30", "label": "30 Minutes"},
            {"value": "H1",  "label": "1 Hour"},
            {"value": "H2",  "label": "2 Hours"},
            {"value": "H4",  "label": "4 Hours"},
            {"value": "H6",  "label": "6 Hours"},
            {"value": "H8",  "label": "8 Hours"},
            {"value": "H12", "label": "12 Hours"},
            {"value": "D1",  "label": "Daily"},
            {"value": "W1",  "label": "Weekly"},
        ]

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        date_from: datetime,
        date_to: datetime,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV klines from Binance Futures (paginated, up to _MAX_BARS_PER_REQUEST per call).
        Returns standard DataFrame: time, open, high, low, close, volume, spread
        """
        interval = _TIMEFRAME_MAP.get(timeframe)
        if interval is None:
            raise ValueError(
                f"Invalid timeframe '{timeframe}'. "
                f"Supported: {list(_TIMEFRAME_MAP.keys())}"
            )

        # Convert to millisecond timestamps
        start_ms = int(date_from.replace(tzinfo=timezone.utc).timestamp() * 1000)
        end_ms   = int(date_to.replace(tzinfo=timezone.utc).timestamp() * 1000)

        all_rows: list[list] = []
        cursor = start_ms

        while cursor < end_ms:
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": _MAX_BARS_PER_REQUEST,
            }
            try:
                resp = self._session.get(
                    f"{FAPI_BASE}/fapi/v1/klines", params=params, timeout=30
                )
                resp.raise_for_status()
                rows = resp.json()
            except requests.HTTPError as e:
                raise ValueError(f"Binance API error for {symbol}: {e}") from e
            except Exception as e:
                raise ValueError(f"Network error fetching {symbol}: {e}") from e

            if not rows:
                break

            all_rows.extend(rows)

            # Move cursor to just after the last returned bar
            last_open_time = int(rows[-1][0])
            if last_open_time <= cursor:
                break
            cursor = last_open_time + 1

        if not all_rows:
            raise ValueError(
                f"No data returned from Binance for {symbol} {timeframe} "
                f"between {date_from} and {date_to}."
            )

        # Kline columns: [open_time, open, high, low, close, volume, close_time, ...]
        df = pd.DataFrame(all_rows, columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "num_trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ])

        df["time"]   = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_localize(None)
        df["open"]   = df["open"].astype(float)
        df["high"]   = df["high"].astype(float)
        df["low"]    = df["low"].astype(float)
        df["close"]  = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        df["spread"] = 0  # Binance futures: no spread (taker fee separated)

        df = df[["time", "open", "high", "low", "close", "volume", "spread"]]
        df = df.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
        return df

    def fetch_latest_bars(
        self,
        symbol: str,
        timeframe: str,
        num_bars: int = 200,
    ) -> pd.DataFrame:
        """Fetch the most recent N bars from Binance."""
        interval = _TIMEFRAME_MAP.get(timeframe)
        if interval is None:
            raise ValueError(f"Invalid timeframe {timeframe}")
            
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(num_bars, _MAX_BARS_PER_REQUEST),
        }
        
        try:
            resp = self._session.get(
                f"{FAPI_BASE}/fapi/v1/klines", params=params, timeout=10
            )
            resp.raise_for_status()
            rows = resp.json()
        except requests.HTTPError as e:
            raise ValueError(f"Binance API error for {symbol}: {e}") from e
        except Exception as e:
            raise ValueError(f"Network error fetching latest {symbol}: {e}") from e

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "num_trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ])

        df["time"]   = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_localize(None)
        df["open"]   = df["open"].astype(float)
        df["high"]   = df["high"].astype(float)
        df["low"]    = df["low"].astype(float)
        df["close"]  = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        
        return df[["time", "open", "high", "low", "close", "volume"]]
