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
from matplotlib.ticker import FuncFormatter

from charts import TF_MS

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
    from price_fmt import crypto_decimals

    p = crypto_decimals(price)
    return f"{price:,.{p}f}"


def price_y_limits(
    highs: Sequence[float],
    lows: Sequence[float],
    entry: float,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    *,
    level_extend_frac: float = 0.55,
) -> tuple[float, float, float]:
    """
    Y-axis for alert charts: zoom on closed candles, soft-include SL/TP.

    Including full ATR stop/target in ylim squashes wicks into flat dashes.
    ``level_extend_frac`` caps how far beyond the candle range we pull SL/TP in.
    Returns (y_min, y_max, candle_span) after padding.
    """
    candle_lo = min(lows)
    candle_hi = max(highs)
    candle_span = candle_hi - candle_lo
    if candle_span <= 0:
        candle_span = max(abs(entry) * 0.02, entry * 1e-6, 1e-12)

    core_lo = min(candle_lo, entry)
    core_hi = max(candle_hi, entry)
    max_pull = candle_span * level_extend_frac

    y_lo, y_hi = core_lo, core_hi
    for p in (stop_loss, take_profit):
        if p is None:
            continue
        pf = float(p)
        if pf < y_lo:
            y_lo = max(pf, y_lo - max_pull)
        elif pf > y_hi:
            y_hi = min(pf, y_hi + max_pull)

    pad = (y_hi - y_lo) * 0.10 or candle_span * 0.10 or abs(entry) * 0.01 or 1.0
    return y_lo - pad, y_hi + pad, candle_span


def ltf_bar_to_htf_open_ms(ltf_bar_open_ms: int, htf: str) -> int:
    """Map a signal-timeframe bar open (ms) to its HTF candle open."""
    step = TF_MS.get(htf.lower())
    if not step:
        return int(ltf_bar_open_ms)
    t = int(ltf_bar_open_ms)
    return (t // step) * step


def _time_tolerance_ms(timeframe: str) -> int:
    step = TF_MS.get(timeframe.lower(), 86_400_000)
    return step * 2


def _draw_trade_panel(
    ax: Any,
    bars: Sequence[dict[str, Any]],
    *,
    panel_title: str,
    side: str,
    entry: float,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    entry_bar_index: Optional[int],
    show_legend: bool,
    anchor_rr_on_entry_bar: bool,
) -> None:
    n = len(bars)
    highs = [float(b["h"]) for b in bars]
    lows = [float(b["l"]) for b in bars]
    opens = [float(b["o"]) for b in bars]
    closes = [float(b["c"]) for b in bars]

    y_min, y_max, candle_span = price_y_limits(
        highs, lows, entry, stop_loss, take_profit
    )
    min_body = max(candle_span * 0.012, abs(entry) * 1e-8, 1e-12)
    buy = (side or "BUY").upper() != "SELL"

    e_idx = entry_bar_index if entry_bar_index is not None else n - 1
    e_idx = max(0, min(n - 1, int(e_idx)))

    if anchor_rr_on_entry_bar:
        x0 = float(e_idx) - 0.15
        x1 = float(n) - 0.5
    else:
        x0 = max(0.0, float(n - 35))
        x1 = float(n) - 0.5

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
        height_bar = max(abs(c - o), min_body)
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

    ax.axvline(e_idx, color="#00bcd4", alpha=0.45, linewidth=1.0, zorder=4)
    ax.scatter(
        [e_idx],
        [entry],
        marker="^" if buy else "v",
        s=100 if show_legend else 80,
        color="#00bcd4",
        zorder=5,
        edgecolors="white",
        linewidths=0.6,
    )

    ax.set_title(panel_title, color="#e6edf3", fontsize=11, fontweight="bold", loc="left", pad=8)
    ax.set_ylabel("Price", color="#8b949e", fontsize=8)
    ax.set_xlim(-0.8, n - 0.2)
    ax.set_ylim(y_min, y_max)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: _fmt_price(v)))
    ax.tick_params(colors="#8b949e", labelsize=7)
    ax.grid(True, color="#21262d", linewidth=0.6, alpha=0.9)
    for spine in ax.spines.values():
        spine.set_color("#30363d")
    if show_legend:
        ax.legend(loc="upper left", fontsize=7, facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3")


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
    entry_bar_index: Optional[int] = None,
    width: int = 960,
    height: int = 540,
    anchor_rr_on_entry_bar: bool = True,
) -> bytes:
    """Render dark-theme candle chart with risk/reward zones."""
    if not bars:
        raise ValueError("bars_required")
    buy = (side or "BUY").upper() != "SELL"
    rr = expected_r(side, entry, stop_loss, take_profit)
    side_label = "LONG" if buy else "SHORT"
    grade_txt = f" · {grade}" if grade else ""
    score_txt = f" · {score:.0f}/100" if score is not None else ""
    rr_txt = f" · {rr:.2f}R" if rr is not None else ""
    title = f"{symbol} · {timeframe.upper()} · {side_label}{grade_txt}{score_txt}{rr_txt}"

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")
    _draw_trade_panel(
        ax,
        bars,
        panel_title=title,
        side=side,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        entry_bar_index=entry_bar_index,
        show_legend=True,
        anchor_rr_on_entry_bar=anchor_rr_on_entry_bar,
    )
    fig.text(0.99, 0.02, "QMIE · signal only", ha="right", va="bottom", color="#484f58", fontsize=8)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return buf.getvalue()


def render_dual_htf_landscape_png(
    ltf_bars: Sequence[dict[str, Any]],
    htf_bars: Sequence[dict[str, Any]],
    *,
    symbol: str,
    ltf: str,
    htf: str,
    side: str,
    entry: float,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    grade: Optional[str] = None,
    score: Optional[float] = None,
    ltf_entry_index: Optional[int] = None,
    htf_entry_index: Optional[int] = None,
    width: int = 1280,
    height: int = 520,
) -> bytes:
    """Landscape card: HTF context (left) + signal TF entry (right)."""
    if not ltf_bars or not htf_bars:
        raise ValueError("bars_required")
    buy = (side or "BUY").upper() != "SELL"
    rr = expected_r(side, entry, stop_loss, take_profit)
    side_label = "LONG" if buy else "SHORT"
    grade_txt = f" · {grade}" if grade else ""
    score_txt = f" · {score:.0f}/100" if score is not None else ""
    rr_txt = f" · {rr:.2f}R" if rr is not None else ""
    ltf_title = f"{symbol} · {ltf.upper()} · {side_label}{grade_txt}{score_txt}{rr_txt}"
    htf_title = f"{symbol} · {htf.upper()} · HTF context"

    fig, (ax_htf, ax_ltf) = plt.subplots(
        1,
        2,
        figsize=(width / 100, height / 100),
        dpi=100,
        gridspec_kw={"width_ratios": [1.0, 1.12], "wspace": 0.22},
    )
    fig.patch.set_facecolor("#0d1117")
    for ax in (ax_htf, ax_ltf):
        ax.set_facecolor("#0d1117")

    _draw_trade_panel(
        ax_htf,
        htf_bars,
        panel_title=htf_title,
        side=side,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        entry_bar_index=htf_entry_index,
        show_legend=False,
        anchor_rr_on_entry_bar=True,
    )
    _draw_trade_panel(
        ax_ltf,
        ltf_bars,
        panel_title=ltf_title,
        side=side,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        entry_bar_index=ltf_entry_index,
        show_legend=True,
        anchor_rr_on_entry_bar=True,
    )
    fig.text(0.99, 0.02, "QMIE · signal only", ha="right", va="bottom", color="#484f58", fontsize=8)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.12)
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


def slice_bars_for_signal(
    bars: list[dict[str, Any]],
    *,
    bar_time_ms: Optional[int],
    limit: int,
    timeframe: str = "4h",
) -> tuple[list[dict[str, Any]], int]:
    """Window bars ending on the signal candle; return (bars, entry_bar_index)."""
    if not bars:
        return [], 0
    lim = max(10, min(200, limit))
    tol = _time_tolerance_ms(timeframe)
    if bar_time_ms is None:
        window = bars[-lim:]
        return window, len(window) - 1
    target = int(bar_time_ms)
    idx = next((i for i, b in enumerate(bars) if int(b["t"]) == target), None)
    if idx is None:
        idx = min(
            range(len(bars)),
            key=lambda i: abs(int(bars[i]["t"]) - target),
        )
        if abs(int(bars[idx]["t"]) - target) > tol:
            window = bars[-lim:]
            return window, len(window) - 1
    start = max(0, idx - lim + 1)
    window = bars[start : idx + 1]
    return window, len(window) - 1


async def build_alert_chart_png(
    client: Any,
    sig: Any,
    *,
    bar_limit: int = 90,
    htf_map: Optional[dict[str, str]] = None,
    include_htf: bool = True,
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
    bars_raw = await fetch_bars_for_alert(client, symbol, tf, limit=bar_limit + 30)
    bar_ms = getattr(sig, "bar_time", None)
    if bar_ms is not None:
        try:
            bar_ms = int(bar_ms)
        except (TypeError, ValueError):
            bar_ms = None
    bars, entry_i = slice_bars_for_signal(
        bars_raw, bar_time_ms=bar_ms, limit=bar_limit, timeframe=tf
    )
    if len(bars) < 5:
        return None
    sl = getattr(sig, "stop_loss", None)
    tp = getattr(sig, "take_profit", None)
    side_obj = getattr(sig, "side", None)
    side = side_obj.value if hasattr(side_obj, "value") else str(side_obj or "BUY")
    grade = getattr(sig, "grade", None)
    grade_s = grade.value if hasattr(grade, "value") else (str(grade) if grade else None)
    score = getattr(sig, "score", None)
    sl_f = float(sl) if sl is not None else None
    tp_f = float(tp) if tp is not None else None
    score_f = float(score) if score is not None else None

    htf_tf: Optional[str] = None
    if include_htf and htf_map:
        htf_tf = htf_map.get(tf)
    if htf_tf and htf_tf.lower() != tf:
        try:
            htf_limit = min(120, max(40, bar_limit // 2))
            htf_raw = await fetch_bars_for_alert(client, symbol, htf_tf, limit=htf_limit + 20)
            htf_ms = ltf_bar_to_htf_open_ms(bar_ms, htf_tf) if bar_ms is not None else None
            htf_bars, htf_i = slice_bars_for_signal(
                htf_raw,
                bar_time_ms=htf_ms,
                limit=htf_limit,
                timeframe=htf_tf,
            )
            if len(htf_bars) >= 5:
                return render_dual_htf_landscape_png(
                    bars,
                    htf_bars,
                    symbol=symbol,
                    ltf=tf,
                    htf=htf_tf,
                    side=side,
                    entry=entry_f,
                    stop_loss=sl_f,
                    take_profit=tp_f,
                    grade=grade_s,
                    score=score_f,
                    ltf_entry_index=entry_i,
                    htf_entry_index=htf_i,
                )
        except Exception:
            logger.exception("HTF alert chart panel skipped for %s", symbol)

    try:
        return render_trade_png(
            bars,
            symbol=symbol,
            timeframe=tf,
            entry=entry_f,
            side=side,
            stop_loss=sl_f,
            take_profit=tp_f,
            grade=grade_s,
            score=score_f,
            entry_bar_index=entry_i,
            anchor_rr_on_entry_bar=True,
        )
    except Exception:
        logger.exception("render_trade_png failed for %s", symbol)
        return None
