"""GET /guide returns the operator trading guide."""
from guide import trading_guide


def test_guide_never_orders():
    g = trading_guide()
    assert g["places_orders"] is False
    ids = [s["id"] for s in g["sections"]]
    assert ids == [
        "what",
        "tema",
        "expansion",
        "tema_buy",
        "breakout",
        "screens",
        "paper",
        "exit",
        "charts",
        "kovaview",
        "live",
    ]
    assert "Paper" in g["sections"][6]["title"]
    kv = next(s for s in g["sections"] if s["id"] == "kovaview")
    assert "docs/kovaview-equity-map.md" in kv["body"]
    assert any("KAMA" in r for r in kv["rules"])
    exp = next(s for s in g["sections"] if s["id"] == "expansion")
    assert "spot" in exp["title"].lower()
    assert any("spot" in r.lower() for r in (exp.get("rules") or []))
    buy = next(s for s in g["sections"] if s["id"] == "tema_buy")
    assert "leverage" in buy["title"].lower() or "leveraged" in buy["title"].lower()
