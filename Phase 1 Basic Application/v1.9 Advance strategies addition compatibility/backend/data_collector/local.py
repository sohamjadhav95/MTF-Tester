"""Local CSV data provider — Phase 3 stub."""
# Phase 3 stub — not yet implemented. Do not instantiate.
from data_collector.base import DataProvider


class LocalProvider(DataProvider):
    """Stub — Phase 3."""
    @property
    def connected(self): return False
    def connect(self, **kwargs): return {"success": False, "error": "Not implemented"}
    def disconnect(self): return {"success": True}
    def get_symbols(self, group="*"): return []
    def get_symbol_info(self, symbol): return None
    def get_timeframes(self): return []
    def fetch_ohlcv(self, *args, **kwargs):
        raise NotImplementedError("Local provider coming in Phase 3")
    def fetch_latest_bars(self, *args, **kwargs):
        raise NotImplementedError("Local provider coming in Phase 3")
