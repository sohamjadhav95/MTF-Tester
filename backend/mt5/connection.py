"""
MT5 Connection Module
Handles login/logout, symbol enumeration, and symbol info retrieval.
MetaTrader5 is imported lazily to avoid numpy compatibility issues at startup.
"""

from datetime import datetime


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


class MT5Connection:
    """Manages MetaTrader 5 terminal connection."""

    def __init__(self):
        self._connected = False
        self._account_info = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def account_info(self) -> dict | None:
        return self._account_info

    def connect(self, server: str, login: int, password: str) -> dict:
        """
        Initialize MT5 terminal and login.
        Returns dict with success status and account info or error message.
        """
        try:
            mt5 = _get_mt5()
        except RuntimeError as e:
            return {"success": False, "error": str(e)}

        # Initialize MT5 terminal
        if not mt5.initialize():
            err = mt5.last_error()
            return {
                "success": False,
                "error": f"MT5 initialization failed: {err}. Make sure MetaTrader 5 terminal is running.",
            }

        # Login to account
        authorized = mt5.login(login=login, password=password, server=server)
        if not authorized:
            error = mt5.last_error()
            mt5.shutdown()
            return {
                "success": False,
                "error": f"MT5 login failed: {error}",
            }

        # Get account info
        info = mt5.account_info()
        if info is None:
            mt5.shutdown()
            return {
                "success": False,
                "error": "Failed to retrieve account info after login.",
            }

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

        return {
            "success": True,
            "account": self._account_info,
        }

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
        """
        Get available symbols from MT5.
        Args:
            group: Filter pattern (e.g. "*USD*", "Forex*")
        Returns list of symbol dicts with name and description.
        """
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
            if s.visible:
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
        """
        Get detailed info for a specific symbol.
        Returns dict with symbol properties or None if not found.
        """
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
