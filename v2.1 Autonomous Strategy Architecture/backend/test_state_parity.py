import pandas as pd
from strategies._template import BaseStrategy

class StatefulTestStrategy(BaseStrategy):
    name = "test-stateful"
    
    def on_start(self, data):
        self._cache = {"times": data["time"].values}
    
    def on_bar(self, i, data):
        self.state.setdefault("count", 0)
        self.state["count"] += 1
        return "HOLD"
