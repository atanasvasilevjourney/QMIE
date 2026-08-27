"""
QMIE combo screens — union of existing views, unique by symbol
==============================================================
Deep View-style master list: OR of result sets, then unique(symbol).

Sources (already on the desk):
  * TEMA A/A+ alerts (leverage book, prefer 4h over 1h)
  * Daily expansion (spot 1D coil-UP / coil-DOWN)
  * Daily color-flip (spot GREY→GREEN / GREY→RED)
  * Radar tight coils
  * Ranked book slots

Not a CAN SLIM filter DSL. Does not retune W_*. Does not place orders.
quantity is always 0.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from improve.checklist import atr_pct_of, flatten_signal, radar_color_for
from scanner.allocator import cluster_of

VIEWS = ("all", "leaders", "expansions", "coils", "breakouts", "book")
_TF_RANK = {"4h": 3, "1h": 2, "1d": 1}


def _s(v: Any) -> str:
    return str(v or "").strip()


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _is_exit(flat: dict[str, Any]) -> bool:
    ev = _s(flat.get("event")).lower()
    strat = _s(flat.get("strategy"))
    return (
        ev in ("exit", "close")
        or _s(flat.get("setup_type")) == "paper_exit"
        or strat == "QMIE-Paper"
    )


def _is_expansion(flat: dict[str, Any]) -> bool:
    if _is_exit(flat):
        return False
    strat = _s(flat.get("strategy"))
    reason = _s(flat.get("reason"))
    setup = _s(flat.get("setup_type")).lower()
    return (
        "DailyExpansion" in strat
        or setup == "expansion"
        or "coil_breakout" in reason
    )


def _is_breakout(flat: dict[str, Any]) -> bool:
    if _is_exit(flat) or _is_expansion(flat):
        return False
    strat = _s(flat.get("strategy"))
    reason = _s(flat.get("reason"))
    return (
        "DailyBreakout" in strat
        or _s(flat.get("setup_type")) == "breakout"
        or "trend_start" in reason
    )


def _is_tema_aa(flat: dict[str, Any]) -> bool:
    if _is_exit(flat) or _is_breakout(flat) or _is_expansion(flat):
        return False
    grade = _s(flat.get("grade"))
    if grade not in ("A", "A+"):
        return False
    side = _s(flat.get("side")).upper()
    return side in ("BUY", "SELL")


def _radar_by_symbol(radar: Optional[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not radar:
        return out
    for row in radar.get("rows") or []:
        sym = _s(row.get("symbol")).upper()
        if sym:
            out[sym] = row
    return out


def _display_rank(sources: set[str], tf: str) -> tuple[int, int]:
    """Higher is better when picking which row to keep for a symbol."""
    src = 0
    if "leaders" in sources:
        src += 40
    if "expansions" in sources:
        src += 25
    if "breakouts" in sources:
        src += 20
    if "book" in sources:
        src += 10
    if "coils" in sources:
        src += 5
    return (src, _TF_RANK.get(tf.lower(), 0))


def _blank_row(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "cluster": cluster_of(symbol),
        "sources": [],
        "side": None,
        "grade": None,
        "score": None,
        "timeframe": None,
        "signal_id": None,
        "signal_price": None,
        "stop_loss": None,
        "take_profit": None,
        "atr_pct": None,
        "adx": None,
        "radar_color": None,
        "coil_width_pct": None,
        "pct_since_flip": None,
        "is_tight_coil": False,
        "is_fresh_flip": False,
        "is_early_long": False,
        "is_early_short": False,
        "breakout": None,
        "is_expansion": False,
        "weight_pct": None,
        "book_rank": None,
        "quantity": 0,
        "places_orders": False,
    }


def _paint_radar(row: dict[str, Any], r: Optional[dict[str, Any]]) -> None:
    if not r:
        return
    if row["radar_color"] is None:
        row["radar_color"] = _s(r.get("color")).upper() or None
    if row["coil_width_pct"] is None:
        row["coil_width_pct"] = _f(r.get("coil_width_pct"))
    if row["pct_since_flip"] is None:
        row["pct_since_flip"] = _f(r.get("pct_since_flip"))
    if row["adx"] is None:
        row["adx"] = _f(r.get("adx"))
    if r.get("is_tight_coil"):
        row["is_tight_coil"] = True
    if r.get("is_fresh_flip"):
        row["is_fresh_flip"] = True
    if r.get("is_early_long"):
        row["is_early_long"] = True
    if r.get("is_early_short"):
        row["is_early_short"] = True
    if r.get("breakout") and not row["breakout"]:
        row["breakout"] = r.get("breakout")


def build_screens(
    *,
    signals: list[dict[str, Any]],
    radar: Optional[dict[str, Any]] = None,
    allocation: Optional[dict[str, Any]] = None,
    view: str = "all",
) -> dict[str, Any]:
    """OR of TEMA A/A+ ∪ daily expansion ∪ color-flip ∪ coils ∪ book, then unique(symbol)."""
    v = (view or "all").strip().lower()
    if v not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}")

    radar_idx = _radar_by_symbol(radar)
    by_sym: dict[str, dict[str, Any]] = {}

    def upsert(symbol: str, *, sources: list[str], tf: str = "", extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        sym = _s(symbol).upper()
        if not sym:
            raise ValueError("symbol required")
        incoming_src = set(sources)
        rank = _display_rank(incoming_src, tf)
        cur = by_sym.get(sym)
        if cur is None:
            row = _blank_row(sym)
            row["sources"] = sorted(incoming_src)
            row["_rank"] = rank
            by_sym[sym] = row
            if extra:
                for k, val in extra.items():
                    if val is not None and val != "":
                        row[k] = val
            if tf:
                row["timeframe"] = tf.lower()
            _paint_radar(row, radar_idx.get(sym))
            if row["radar_color"] is None:
                row["radar_color"] = radar_color_for(sym, radar)
            return row
        cur["sources"] = sorted(set(cur["sources"]) | incoming_src)
        if extra:
            for k in ("weight_pct", "book_rank", "cluster"):
                if extra.get(k) is not None and extra.get(k) != "":
                    cur[k] = extra[k]
            if rank >= (cur.get("_rank") or (0, 0)):
                for k, val in extra.items():
                    if k in ("weight_pct", "book_rank"):
                        continue
                    if val is not None and val != "":
                        cur[k] = val
                if tf:
                    cur["timeframe"] = tf.lower()
                cur["_rank"] = rank
        _paint_radar(cur, radar_idx.get(sym))
        return cur

    for raw in signals:
        flat = flatten_signal(raw)
        sym = _s(flat.get("symbol")).upper()
        if not sym:
            continue
        tf = _s(flat.get("timeframe")).lower()
        src: list[str] = []
        if _is_tema_aa(flat):
            src.append("leaders")
        if _is_expansion(flat):
            src.append("expansions")
        if _is_breakout(flat):
            src.append("breakouts")
        if not src:
            continue
        extra = {
            "side": _s(flat.get("side")).upper() or None,
            "grade": _s(flat.get("grade")) or None,
            "score": _f(flat.get("score")),
            "signal_id": _i(flat.get("id")),
            "signal_price": _f(flat.get("signal_price") or flat.get("price")),
            "stop_loss": _f(flat.get("stop_loss")),
            "take_profit": _f(flat.get("take_profit")),
            "atr_pct": atr_pct_of(flat),
            "adx": _f(flat.get("adx") or flat.get("adx_value")),
        }
        upsert(sym, sources=src, tf=tf, extra=extra)

    for slot in (allocation or {}).get("slots") or []:
        sym = _s(slot.get("symbol")).upper()
        if not sym:
            continue
        extra = {
            "side": _s(slot.get("side")).upper() or None,
            "grade": _s(slot.get("grade")) or None,
            "score": _f(slot.get("score")),
            "signal_price": _f(slot.get("price")),
            "stop_loss": _f(slot.get("stop_loss")),
            "take_profit": _f(slot.get("take_profit")),
            "weight_pct": _f(slot.get("weight_pct")),
            "book_rank": _i(slot.get("rank")),
        }
        if slot.get("cluster"):
            extra["cluster"] = _s(slot.get("cluster"))
        tf = _s((allocation or {}).get("timeframe")).lower()
        upsert(sym, sources=["book"], tf=tf, extra=extra)

    for coil in (radar or {}).get("tight_coils") or []:
        sym = _s(coil.get("symbol")).upper()
        if not sym:
            continue
        extra = {
            "signal_price": _f(coil.get("price")),
            "adx": _f(coil.get("adx")),
            "coil_width_pct": _f(coil.get("coil_width_pct")),
            "is_tight_coil": True,
            "is_early_long": bool(coil.get("is_early_long")),
            "is_early_short": bool(coil.get("is_early_short")),
        }
        upsert(sym, sources=["coils"], tf="1d", extra=extra)

    for br in (radar or {}).get("breakouts") or []:
        direction = _s(br.get("breakout")).upper()
        if direction not in ("UP", "DOWN"):
            continue
        sym = _s(br.get("symbol")).upper()
        if not sym:
            continue
        extra = {
            "side": "BUY" if direction == "UP" else "SELL",
            "signal_price": _f(br.get("price")),
            "adx": _f(br.get("adx")),
            "breakout": direction,
            "is_expansion": True,
            "stop_loss": _f(br.get("coil_low") if direction == "UP" else br.get("coil_high")),
        }
        upsert(sym, sources=["expansions"], tf="1d", extra=extra)

    for ex in (radar or {}).get("expansions") or []:
        sym = _s(ex.get("symbol")).upper()
        if not sym:
            continue
        extra = {
            "side": "BUY",
            "signal_price": _f(ex.get("price")),
            "adx": _f(ex.get("adx")),
            "breakout": "UP",
            "is_expansion": True,
            "stop_loss": _f(ex.get("coil_low")),
        }
        upsert(sym, sources=["expansions"], tf="1d", extra=extra)

    for ex in (radar or {}).get("expansion_shorts") or []:
        sym = _s(ex.get("symbol")).upper()
        if not sym:
            continue
        extra = {
            "side": "SELL",
            "signal_price": _f(ex.get("price")),
            "adx": _f(ex.get("adx")),
            "breakout": "DOWN",
            "is_expansion": True,
            "stop_loss": _f(ex.get("coil_high")),
        }
        upsert(sym, sources=["expansions"], tf="1d", extra=extra)

    rows = list(by_sym.values())
    for row in rows:
        row["sources"] = sorted(row["sources"])
        row["quantity"] = 0
        row["places_orders"] = False
        if "expansions" in row["sources"]:
            row["is_expansion"] = True
        if "coils" in row["sources"]:
            row["is_tight_coil"] = True
        if not row.get("cluster"):
            row["cluster"] = cluster_of(row["symbol"])
        row.pop("_rank", None)

    def matches(row: dict[str, Any]) -> bool:
        if v == "all":
            return True
        if v == "leaders":
            return "leaders" in row["sources"] and _s(row.get("timeframe")).lower() == "4h"
        return v in row["sources"]

    visible = [r for r in rows if matches(r)]
    counts = Counter(r["cluster"] for r in visible if r.get("cluster"))
    modal = counts.most_common(1)[0][0] if counts else None

    counts_src = Counter()
    for r in rows:
        for s in r["sources"]:
            counts_src[s] += 1

    visible.sort(
        key=lambda r: (
            -(r.get("score") or -1.0),
            r.get("coil_width_pct") if r.get("coil_width_pct") is not None else 999.0,
            r["symbol"],
        )
    )

    return {
        "places_orders": False,
        "quantity": 0,
        "view": v,
        "views": list(VIEWS),
        "count": len(visible),
        "union_count": len(rows),
        "modal_cluster": modal,
        "source_counts": dict(counts_src),
        "note": (
            "OR of leveraged TEMA A/A+ ∪ spot daily expansion ∪ color-flip ∪ coils ∪ book, unique(symbol). "
            "Leaders view is 4h A/A+ leverage. Expansions view is spot 1D coil-UP/DOWN. Never orders."
        ),
        "rows": visible,
    }
