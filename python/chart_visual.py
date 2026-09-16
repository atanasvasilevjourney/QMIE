"""
PNG trade card for Discord alerts — closed candles + entry / SL / TP / R.
Uses matplotlib Agg only. Never an order ticket.
"""
from __future__ import annotations

import io
import logging
from typing import Any, Optional, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle

logger = logging.getLogger(__name__)


def expected_r(
    side: str | None,
    entry: float | None,
    stop_loss: float | None,
    take_profit: float | None,
) -> Optional[float]:
    if entry is None or stop_loss is None or take_profit is None:
        return None
    buy = (side or "BUY").upper() != "SELL"
    risk = (entry - stop_loss) if buy else (stop_loss - entry)
    reward = (take_profit - entry) if buy else (entry - take_profit)
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def _fmt_price(price: float) -> str:
    a = abs(price)
    if a >= 100:
        return f"{price:,.2f}"
    if a >= 1:
        return f"{price:,.4f}"
    if a >= 0.0001:
        return f"{price:.6f}"
    return f"{price:.8f}"


def render_trade_png(
    bars: Sequence[dict[str, Any]],
    *,
    symbol: str,
    timeframe: str,
    side: str,
    entry: float,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    grade: Optional[str] = None,
    score: Optional[float] = None,
    width: int = 960,
    height: int = 540,
) -> bytes:
    """Render dark-theme candle chart with risk/reward zones."""
    if not bars:
        raise ValueError("bars_required")
    n = len(bars)
    highs = [float(b["h"]) for b in bars]
    lows = [float(b["l"]) for b in bars]
    opens = [float(b["o"]) for b in bars]
    closes = [float(b["c"]) for b in bars]

    y_lo = min(lows + [entry])
    y_hi = max(highs + [entry])
    for p in (stop_loss, take_profit):
        if p is not None:
            y_lo = min(y_lo, float(p))
            y_hi = max(y_hi, float(p))
    pad = (y_hi - y_lo) * 0.08 or entry * 0.02 or 1.0
    y_min, y_max = y_lo - pad, y_hi + pad

    buy = (side or "BUY").upper() != "SELL"
    rr = expected_r(side, entry, stop_loss, take_profit)

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    x0, x1 = max(0, n - 35), n - 0.5
    if stop_loss is not None:
        if buy:
            ax.fill_between([x0, x1], entry, stop_loss, color="#e74c3c", alpha=0.18)
        else:
            ax.fill_between([x0, x1], stop_loss, entry, color="#e74c3c", alpha=0.18)
    if take_profit is not None:
        if buy:
            ax.fill_between([x0, x1], entry, take_profit, color="#2ecc71", alpha=0.15)
        else:
            ax.fill_between([x0, x1], take_profit, entry, color="#2ecc71", alpha=0.15)

    cw = 0.65
    for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes, strict=True)):
        up = c >= o
        color = "#2ecc71" if up else "#e74c3c"
        ax.plot([i, i], [l, h], color=color, linewidth=0.8, solid_capstyle="round")
        bottom = min(o, c)
        height_bar = max(abs(c - o), (y_max - y_min) * 0.002)
        ax.add_patch(
            Rectangle(
                (i - cw / 2, bottom),
                cw,
                height_bar,
                facecolor=color,
                edgecolor=color,
                linewidth=0,
            )
        )

    ax.axhline(entry, color="#00bcd4", linewidth=1.4, linestyle="-", label=f"Entry {_fmt_price(entry)}")
    if stop_loss is not None:
        ax.axhline(stop_loss, color="#e74c3c", linewidth=1.2, linestyle="--", label=f"SL {_fmt_price(stop_loss)}")
    if take_profit is not None:
        ax.axhline(take_profit, color="#2ecc71", linewidth=1.2, linestyle="--", label=f"TP {_fmt_price(take_profit)}")

    ax.scatter([n - 1], [entry], marker="^" if buy else "v", s=120, color="#00bcd4", zorder=5, edgecolors="white", linewidths=0.6)

    side_label = "LONG" if buy else "SHORT"
    grade_txt = f" · {grade}" if grade else ""
    score_txt = f" · {score:.0f}/100" if score is not None else ""
    rr_txt = f" · {rr:.2f}R" if rr is not None else ""
    ax.set_title(
        f"{symbol} · {timeframe.upper()} · {side_label}{grade_txt}{score_txt}{rr_txt}",
        color="#e6edf3",
        fontsize=13,
        fontweight="bold",
        loc="left",
        pad=12,
    )
    ax.set_ylabel("Price", color="#8b949e")
    ax.set_xlim(-0.8, n - 0.2)
    ax.set_ylim(y_min, y_max)
    ax.tick_params(colors="#8b949e", labelsize=8)
    ax.grid(True, color="#21262d", linewidth=0.6, alpha=0.9)
    for spine in ax.spines.values():
        spine.set_color("#30363d")
    ax.legend(loc="upper left", fontsize=8, facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3")

    fig.text(0.99, 0.02, "QMIE · signal only", ha="right", va="bottom", color="#484f58", fontsize=8)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return buf.getvalue()


async def fetch_bars_for_alert(
    client: Any,
    symbol: str,
    timeframe: str,
    *,
    limit: int = 90,
) -> list[dict[str, Any]]:
    import charts as charts_mod

    df = await client.fetch_klines(symbol, timeframe, limit=max(30, min(200, limit)))
    if df is None or getattr(df, "empty", True):
        return []
    return charts_mod.bars_payload(df)


async def build_alert_chart_png(
    client: Any,
    sig: Any,
    *,
    bar_limit: int = 90,
) -> Optional[bytes]:
    """Best-effort PNG for a TVSignal. Returns None if klines unavailable."""
    symbol = getattr(sig, "symbol", None) or ""
    tf = (getattr(sig, "timeframe", None) or "4h").lower()
    entry = getattr(sig, "signal_price", None) or getattr(sig, "price", None)
    if not symbol or entry is None:
        return None
    try:
        entry_f = float(entry)
    except (TypeError, ValueError):
        return None
    bars = await fetch_bars_for_alert(client, symbol, tf, limit=bar_limit)
    if len(bars) < 5:
        return None
    sl = getattr(sig, "stop_loss", None)
    tp = getattr(sig, "take_profit", None)
    side_obj = getattr(sig, "side", None)
    side = side_obj.value if hasattr(side_obj, "value") else str(side_obj or "BUY")
    grade = getattr(sig, "grade", None)
    grade_s = grade.value if hasattr(grade, "value") else (str(grade) if grade else None)
    score = getattr(sig, "score", None)
    try:
        return render_trade_png(
            bars,
            symbol=symbol,
            timeframe=tf,
            side=side,
            entry=entry_f,
            stop_loss=float(sl) if sl is not None else None,
            take_profit=float(tp) if tp is not None else None,
            grade=grade_s,
            score=float(score) if score is not None else None,
        )
    except Exception:
        logger.exception("render_trade_png failed for %s", symbol)
        return None
