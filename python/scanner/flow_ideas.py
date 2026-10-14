"""Rule-based flow trade ideas. Suggestions only — never orders."""
from __future__ import annotations

from typing import Any


def _f(row: dict[str, Any], key: str) -> float | None:
    v = row.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _idea(
    *,
    bias: str,
    setup: str,
    thesis: str,
    invalidation: str,
    confidence: str,
    entry: float | None,
    stop: float | None,
    target: float | None,
) -> dict[str, Any]:
    return {
        "bias": bias,
        "setup": setup,
        "thesis": thesis,
        "invalidation": invalidation,
        "confidence": confidence,
        "entry": entry,
        "stop": stop,
        "target": target,
        "places_orders": False,
    }


def flow_ideas(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Return up to three ideas. The first is the primary suggestion."""
    close = _f(row, "close")
    oi = _f(row, "oi_change_pct")
    cvd = _f(row, "cvd_slope")
    px = _f(row, "price_change_pct")
    funding = _f(row, "funding_rate")
    poc = _f(row, "poc")
    vah = _f(row, "vah")
    val = _f(row, "val")
    sym = str(row.get("symbol") or "symbol")

    ideas: list[dict[str, Any]] = []

    stretched = funding is not None and abs(funding) >= 0.0008
    oi_up = oi is not None and oi >= 1.5
    oi_down = oi is not None and oi <= -1.5
    buy_flow = cvd is not None and cvd > 0
    sell_flow = cvd is not None and cvd < 0
    price_up = px is not None and px > 0
    price_down = px is not None and px < 0

    if stretched and oi_up and price_up and (funding or 0) > 0:
        ideas.append(_idea(
            bias="WAIT",
            setup="Crowded long",
            thesis=(
                f"{sym} is paying positive funding with rising open interest into a higher price. "
                "Positioning looks stretched — wait for a flush or CVD fade before adding."
            ),
            invalidation="Funding cools and CVD stays positive through the next closed bar.",
            confidence="medium",
            entry=close,
            stop=vah,
            target=poc or val,
        ))

    if price_up and oi_up and buy_flow and close is not None:
        ideas.append(_idea(
            bias="LONG",
            setup="OI build + aggressive buy",
            thesis=(
                f"{sym} closed higher with open interest up and positive CVD slope. "
                "New participation is buying, not just short covering."
            ),
            invalidation="Next closed bar loses the value-area low, or CVD slope flips negative.",
            confidence="high" if not stretched else "medium",
            entry=close,
            stop=val or (close * 0.985 if close else None),
            target=vah or (close * 1.02 if close else None),
        ))

    if price_down and oi_up and sell_flow and close is not None:
        ideas.append(_idea(
            bias="SHORT",
            setup="OI build + aggressive sell",
            thesis=(
                f"{sym} closed lower with open interest up and negative CVD slope. "
                "New shorts (or trapped longs) are pressing the offer."
            ),
            invalidation="Next closed bar reclaims value-area high, or CVD slope flips positive.",
            confidence="high" if not stretched else "medium",
            entry=close,
            stop=vah or (close * 1.015 if close else None),
            target=val or (close * 0.98 if close else None),
        ))

    if price_up and oi_down and buy_flow:
        ideas.append(_idea(
            bias="LONG",
            setup="Short cover",
            thesis=(
                f"{sym} rose while open interest fell and CVD stayed positive. "
                "The move looks like covering more than fresh long build — trail tighter."
            ),
            invalidation="CVD slope turns negative on the next closed bar.",
            confidence="low",
            entry=close,
            stop=poc or val,
            target=vah,
        ))

    if close is not None and val is not None and close < val and buy_flow:
        ideas.append(_idea(
            bias="LONG",
            setup="Below value, buyers returning",
            thesis=(
                f"{sym} is under the volume-profile value area while CVD slope is positive. "
                "A reclaim of VAL is the trigger; until then size stays small."
            ),
            invalidation=f"Acceptance below {val:.6g} with CVD still negative.",
            confidence="medium",
            entry=val,
            stop=close * 0.99,
            target=poc or vah,
        ))

    # Venues without OI history (OKX snapshot-only) still get a location + CVD idea.
    if oi is None and close is not None and poc is not None and price_up and buy_flow and close >= poc:
        ideas.append(_idea(
            bias="LONG",
            setup="Aggressive buy above POC",
            thesis=(
                f"{sym} is at or above the volume-profile POC with a positive CVD slope. "
                "Open-interest change is unavailable on this data source, so this is flow-and-location only."
            ),
            invalidation="Close back under POC, or CVD slope flips negative.",
            confidence="medium",
            entry=close,
            stop=poc,
            target=vah or (close * 1.015),
        ))

    if oi is None and close is not None and poc is not None and price_down and sell_flow and close <= poc:
        ideas.append(_idea(
            bias="SHORT",
            setup="Aggressive sell below POC",
            thesis=(
                f"{sym} is at or under the volume-profile POC with a negative CVD slope. "
                "Open-interest change is unavailable on this data source, so this is flow-and-location only."
            ),
            invalidation="Close back above POC, or CVD slope flips positive.",
            confidence="medium",
            entry=close,
            stop=poc,
            target=val or (close * 0.985),
        ))

    if close is not None and vah is not None and close > vah and sell_flow:
        ideas.append(_idea(
            bias="SHORT",
            setup="Above value, sellers returning",
            thesis=(
                f"{sym} is above the volume-profile value area while CVD slope is negative. "
                "Failed acceptance above VAH favors a rotation back toward POC."
            ),
            invalidation=f"Hold above {vah:.6g} with CVD turning positive.",
            confidence="medium",
            entry=vah,
            stop=close * 1.01,
            target=poc or val,
        ))

    if not ideas:
        ideas.append(_idea(
            bias="WAIT",
            setup="No aligned flow",
            thesis=(
                f"{sym} does not show OI, CVD, and location lining up. "
                "Keep it on the screener until the next closed bar."
            ),
            invalidation="A later bar where OI Δ and CVD slope share a direction with price.",
            confidence="low",
            entry=close,
            stop=val,
            target=vah or poc,
        ))

    # Primary first; cap at three so the review panel stays scannable.
    ranked = sorted(
        ideas,
        key=lambda idea: {"high": 0, "medium": 1, "low": 2}.get(str(idea["confidence"]), 3),
    )
    # Prefer a directional idea over WAIT when both exist at the same confidence.
    ranked.sort(key=lambda idea: (idea["bias"] == "WAIT", {"high": 0, "medium": 1, "low": 2}[idea["confidence"]]))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idea in ranked:
        if idea["setup"] in seen:
            continue
        seen.add(idea["setup"])
        out.append(idea)
        if len(out) == 3:
            break
    return out
