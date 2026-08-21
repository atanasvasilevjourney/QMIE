"""GET /guide returns the operator trading guide."""
from guide import trading_guide


def test_guide_never_orders():
    g = trading_guide()
    assert g["places_orders"] is False
    ids = [s["id"] for s in g["sections"]]
    assert ids == ["what", "tema", "breakout", "paper", "exit", "live"]
    assert "Paper" in g["sections"][3]["title"]
