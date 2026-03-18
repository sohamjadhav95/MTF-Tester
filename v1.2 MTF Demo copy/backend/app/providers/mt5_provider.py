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

    def fetch_latest_bars(
        self,
        symbol: str,
        timeframe: str,
        num_bars: int = 200,
    ) -> pd.DataFrame:
        """Fetch the most recent N bars from MT5."""
        if not self._connected:
            raise ValueError("MT5 not connected")
            
        mt5 = _get_mt5()
        tf = self._get_timeframe_const(timeframe)
        if tf is None:
            raise ValueError(f"Invalid timeframe '{timeframe}'")

        # Select symbol
        if not mt5.symbol_select(symbol, True):
            raise ValueError(f"Symbol '{symbol}' not found in MT5")

        rates = mt5.copy_rates_from_pos(symbol, tf, 0, num_bars)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df["volume"] = df.get("tick_volume", 0)  # Use tick_volume as volume
        
        return df[["time", "open", "high", "low", "close", "volume"]]

    # ── Trading / Order Execution ─────────────────────────────────

    def send_order(
        self,
        symbol: str,
        order_type: str,   # "market" | "pending"
        direction: str,    # "buy" | "sell"
        volume: float,
        price: float | None = None,
        sl: float | None = None,
        tp: float | None = None,
        sl_enabled: bool = False,
        tp_enabled: bool = False,
        comment: str = "MTF-Tester",
    ) -> dict:
        """
        Place a market or pending order via MT5.
        Returns dict with success, ticket, or error.
        """
        if not self._connected:
            return {"success": False, "error": "MT5 not connected"}

        mt5 = _get_mt5()

        # Ensure symbol is selected
        if not mt5.symbol_select(symbol, True):
            return {"success": False, "error": f"Symbol '{symbol}' not available"}

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"success": False, "error": f"Cannot get tick for '{symbol}'"}

        # Determine order type constant and price
        dir_lower = direction.lower()
        type_lower = order_type.lower()

        if type_lower == "market":
            if dir_lower == "buy":
                mt5_type = mt5.ORDER_TYPE_BUY
                fill_price = tick.ask
            else:
                mt5_type = mt5.ORDER_TYPE_SELL
                fill_price = tick.bid
        elif type_lower == "pending":
            if price is None:
                return {"success": False, "error": "Price required for pending orders"}
            fill_price = price
            if dir_lower == "buy":
                # Buy Limit (below ask) or Buy Stop (above ask)
                mt5_type = mt5.ORDER_TYPE_BUY_LIMIT if price < tick.ask else mt5.ORDER_TYPE_BUY_STOP
            else:
                # Sell Limit (above bid) or Sell Stop (below bid)
                mt5_type = mt5.ORDER_TYPE_SELL_LIMIT if price > tick.bid else mt5.ORDER_TYPE_SELL_STOP
        else:
            return {"success": False, "error": f"Invalid order_type: '{order_type}'"}

        request = {
            "action": mt5.TRADE_ACTION_DEAL if type_lower == "market" else mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": volume,
            "type": mt5_type,
            "price": fill_price,
            "deviation": 20,
            "magic": 123456,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        if sl_enabled and sl is not None:
            request["sl"] = sl
        if tp_enabled and tp is not None:
            request["tp"] = tp

        result = mt5.order_send(request)
        if result is None:
            return {"success": False, "error": f"order_send returned None: {mt5.last_error()}"}

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                "success": False,
                "error": f"Order failed: {result.comment} (code {result.retcode})",
                "retcode": result.retcode,
            }

        return {
            "success": True,
            "ticket": result.order if type_lower == "pending" else result.deal,
            "volume": result.volume,
            "price": result.price,
            "comment": result.comment,
        }

    def get_positions(self, symbol: str | None = None) -> list[dict]:
        """Get all open positions, optionally filtered by symbol."""
        if not self._connected:
            return []

        mt5 = _get_mt5()
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()

        if positions is None:
            return []

        result = []
        for p in positions:
            result.append({
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "buy" if p.type == 0 else "sell",
                "volume": p.volume,
                "price_open": p.price_open,
                "price_current": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "swap": p.swap,
                "time": datetime.fromtimestamp(p.time).isoformat(),
                "comment": p.comment,
                "magic": p.magic,
            })
        return result

    def close_position(self, ticket: int) -> dict:
        """Close a specific position by ticket."""
        if not self._connected:
            return {"success": False, "error": "MT5 not connected"}

        mt5 = _get_mt5()
        positions = mt5.positions_get(ticket=ticket)
        if not positions or len(positions) == 0:
            return {"success": False, "error": f"Position {ticket} not found"}

        pos = positions[0]
        # Reverse the direction to close
        if pos.type == 0:  # BUY → close with SELL
            close_type = mt5.ORDER_TYPE_SELL
            price = mt5.symbol_info_tick(pos.symbol).bid
        else:  # SELL → close with BUY
            close_type = mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(pos.symbol).ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 123456,
            "comment": "MTF-Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None:
            return {"success": False, "error": f"Close failed: {mt5.last_error()}"}

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                "success": False,
                "error": f"Close failed: {result.comment} (code {result.retcode})",
            }

        return {"success": True, "ticket": ticket, "closed_profit": pos.profit}

    def close_all_positions(self, symbol: str | None = None) -> dict:
        """Close all open positions. Returns count of closed positions."""
        positions = self.get_positions(symbol=symbol)
        closed = 0
        errors = []
        for pos in positions:
            res = self.close_position(pos["ticket"])
            if res["success"]:
                closed += 1
            else:
                errors.append(f"Ticket {pos['ticket']}: {res['error']}")

        return {
            "success": len(errors) == 0,
            "closed_count": closed,
            "total": len(positions),
            "errors": errors,
        }

    def get_account_equity(self) -> dict | None:
        """Get current account balance, equity, margin info."""
        if not self._connected:
            return None

        mt5 = _get_mt5()
        info = mt5.account_info()
        if info is None:
            return None

        return {
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "margin_level": info.margin_level,
            "profit": info.profit,
            "currency": info.currency,
        }

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
