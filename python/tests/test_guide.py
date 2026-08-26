"""GET /guide returns the operator trading guide."""
from guide import trading_guide


def test_guide_never_orders():
    g = trading_guide()
    assert g["places_orders"] is False
    ids = [s["id"] for s in g["sections"]]
    assert ids == [
        "what",
        "tema",
        "breakout",
        "screens",
        "paper",
        "exit",
        "charts",
        "kovaview",
        "live",
    ]
    assert "Paper" in g["sections"][4]["title"]
    kv = next(s for s in g["sections"] if s["id"] == "kovaview")
    assert "docs/kovaview-equity-map.md" in kv["body"]
    assert any("KAMA" in r for r in kv["rules"])
