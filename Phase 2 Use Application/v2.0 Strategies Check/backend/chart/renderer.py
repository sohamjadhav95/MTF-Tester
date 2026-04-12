"""
Chart Renderer
===============
Converts indicator data from strategies into IndicatorPlot schema
for the frontend chart overlay.
"""

from main.models import IndicatorPlot

# Default color palette for auto-assigning indicator colors
_COLORS = [
    "#2196F3", "#FF9800", "#4CAF50", "#E91E63",
    "#9C27B0", "#00BCD4", "#FFEB3B", "#795548",
    "#607D8B", "#F44336",
]


def format_indicator_plots(indicator_data: dict, bar_data: list) -> list:
    """
    Convert raw indicator data dict to list of IndicatorPlot dicts
    for the frontend chart renderer.

    Args:
        indicator_data: dict from strategy.get_indicator_data()
            Keys are indicator names, values are lists of floats (same length as bars)
        bar_data: list of bar dicts with 'time' field

    Returns:
        List of IndicatorPlot-compatible dicts
    """
    plots = []
    color_idx = 0

    for name, values in indicator_data.items():
        if not values:
            continue

        # Build time-value pairs, filtering out None/NaN
        time_values = []
        for i, val in enumerate(values):
            if val is not None and i < len(bar_data):
                time_values.append({
                    "time": bar_data[i]["time"],
                    "value": val,
                })

        if not time_values:
            continue

        color = _COLORS[color_idx % len(_COLORS)]
        color_idx += 1

        # Determine pane: indicators with "separate" patterns go to separate pane
        pane = "price"
        separate_keywords = ["rsi", "macd", "volume", "histogram", "oscillator", "stoch"]
        if any(kw in name.lower() for kw in separate_keywords):
            pane = "separate"

        plots.append({
            "id": name.lower().replace(" ", "_").replace("(", "").replace(")", ""),
            "label": name,
            "pane": pane,
            "type": "line",
            "color": color,
            "values": time_values,
            "line_style": "solid",
            "line_width": 1,
            "opacity": 1.0,
        })

    return plots
