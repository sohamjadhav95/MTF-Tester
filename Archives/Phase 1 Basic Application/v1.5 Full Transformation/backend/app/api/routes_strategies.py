"""
Strategy API Routes
===================
GET /api/strategies — returns all strategies with JSON Schema from Pydantic.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.registry import auto_discover_strategies

router = APIRouter(prefix="/api", tags=["strategies"])


@router.get("/strategies")
async def list_strategies():
    """
    List all available strategies with their JSON Schema.

    Response:
        {
            "strategies": [
                {
                    "name": "EMA Crossover",
                    "description": "...",
                    "schema": { ... full JSON Schema ... }
                },
                ...
            ]
        }
    """
    registry = auto_discover_strategies()

    strategies = []
    for name, cls in registry.items():
        try:
            schema = cls.get_json_schema()
            strategies.append({
                "name": cls.name,
                "description": cls.description,
                "schema": schema,
            })
        except Exception as e:
            strategies.append({
                "name": name,
                "description": f"Error loading schema: {e}",
                "schema": {},
            })

    return {"strategies": strategies}
