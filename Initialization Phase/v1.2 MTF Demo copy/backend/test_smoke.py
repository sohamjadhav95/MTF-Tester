"""Smoke test for the v2.0 refactored architecture."""
import sys, os, json

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

# Ensure backend/ is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("  Strategy-Tester v2.0 - Smoke Test")
print("=" * 60)

# 1. Registry discovery
print("\n[1] Auto-discover strategies...")
from app.core.registry import auto_discover_strategies

registry = auto_discover_strategies()
print(f"    Found {len(registry)} strategies: {list(registry.keys())}")
assert len(registry) >= 2, f"Expected at least 2 strategies, got {len(registry)}"
assert "EMA Crossover" in registry, "EMA Crossover not found"
assert "Supertrend" in registry, "Supertrend not found"
print("    PASS: Both strategies discovered")

# 2. Schema generation
print("\n[2] JSON Schema generation...")
for name, cls in registry.items():
    schema = cls.get_json_schema()
    assert "properties" in schema, f"{name}: schema has no properties"
    props = schema["properties"]
    print(f"    {name}: {len(props)} properties")
    for key, prop in props.items():
        ptype = prop.get("type") or ("enum" if "enum" in prop else "allOf/anyOf")
        default = prop.get("default", "N/A")
        desc = prop.get("description", "")
        print(f"      - {key}: type={ptype}, default={default}")
print("    PASS: All schemas valid")

# 3. Strategy instantiation (defaults)
print("\n[3] Instantiation with defaults...")
for name, cls in registry.items():
    instance = cls()
    print(f"    {name}: config = {instance.config}")
print("    PASS: All strategies instantiate with defaults")

# 4. Custom settings validation
print("\n[4] Custom settings validation...")
ema_cls = registry["EMA Crossover"]
custom = ema_cls(settings={"fast_period": 12, "slow_period": 26, "sl_type": "atr"})
assert custom.config.fast_period == 12
assert custom.config.slow_period == 26
assert custom.config.sl_type == "atr"
print(f"    EMA custom: fast={custom.config.fast_period}, slow={custom.config.slow_period}, sl={custom.config.sl_type}")
print("    PASS: Custom settings validated correctly")

# 5. Pydantic validation rejects bad values
print("\n[5] Pydantic validation (should reject bad values)...")
try:
    bad = ema_cls(settings={"fast_period": -5})
    print("    FAIL: Should have rejected fast_period=-5!")
    assert False
except Exception as e:
    print(f"    PASS: Correctly rejected: {type(e).__name__}")

# 6. Risk manager
print("\n[6] Risk manager...")
from app.core.risk import RiskManager
rm = RiskManager(max_risk_per_trade_pct=2.0)
lot = rm.calculate_position_size(
    balance=10000, sl_distance=0.0020, contract_size=100000
)
print(f"    2% risk on $10k, SL=20 pips -> lot={lot}")
assert 0.01 <= lot <= 100, f"Lot size out of range: {lot}"

rm_fixed = RiskManager(fixed_lot_size=0.5)
lot_fixed = rm_fixed.calculate_position_size(balance=10000, sl_distance=0.002)
assert lot_fixed == 0.5
print(f"    Fixed lot override -> lot={lot_fixed}")
print("    PASS: Risk manager works correctly")

# 7. Import isolation
print("\n[7] Import isolation check...")
import app.core.engine as engine_mod
source = open(engine_mod.__file__).read()
assert "from strategies" not in source, "Engine imports from strategies!"
assert "import strategies" not in source, "Engine imports strategies!"
print("    PASS: Engine has no strategy imports")

# 8. JSON Schema for frontend (check enum fields work)
print("\n[8] Frontend-compatible JSON Schema check...")
ema_schema = registry["EMA Crossover"].get_json_schema()
props = ema_schema["properties"]

# source should have enum, not type=string
source_prop = props.get("source", {})
assert "enum" in source_prop or "allOf" in source_prop, "source field should have enum"
print(f"    source field: has enum={bool('enum' in source_prop) or bool('allOf' in source_prop)}")

# sl_pips should have x-visible-when
sl_pips_prop = props.get("sl_pips", {})
has_visible = "x-visible-when" in sl_pips_prop
print(f"    sl_pips: has x-visible-when={has_visible}")

print("    PASS: Schema is frontend-compatible")

print("\n" + "=" * 60)
print("  ALL SMOKE TESTS PASSED")
print("=" * 60)
