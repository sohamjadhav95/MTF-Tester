from chart.mtf_engine import MTFLiveEngine
from strategies._template import Signal, HOLD

def test_signal_parsing():
    engine = MTFLiveEngine("scan-test", "EURUSD", "ema_crossover", {}, None)
    
    # 1. HOLD variations
    assert engine._parse_signal(None) == ("HOLD", None, None)
    assert engine._parse_signal("HOLD") == ("HOLD", None, None)
    assert engine._parse_signal(("HOLD",)) == ("HOLD", None, None)
    assert engine._parse_signal(HOLD) == ("HOLD", None, None)
    
    # 2. BUY/SELL string
    assert engine._parse_signal("BUY") == ("BUY", None, None)
    assert engine._parse_signal("sell ") == ("SELL", None, None)
    
    # 3. Tuple 3
    assert engine._parse_signal(("BUY", 1.1, 1.2)) == ("BUY", 1.1, 1.2)
    assert engine._parse_signal(("SELL", None, 1.1)) == ("SELL", None, 1.1)
    
    # 4. Signal object
    sig = Signal(direction="BUY", sl=1.05, tp=1.20)
    assert engine._parse_signal(sig) == ("BUY", 1.05, 1.20)

    # 5. Invalid should raise ValueError
    try:
        engine._parse_signal(("BUY", 1.1))
        assert False, "Should raise ValueError for invalid tuple length"
    except ValueError:
        pass
        
    try:
        engine._parse_signal({"direction": "BUY"})
        assert False, "Should raise ValueError for dict"
    except ValueError:
        pass

if __name__ == "__main__":
    test_signal_parsing()
    print("test_signal_parsing passed!")
