"""
Two-clip book: 1D coil-UP ($100) then 4h TEMA A/A+ BUY add ($100).

Manual-entry measurement only. Does not place orders. Does not retune W_*.
Not the frozen 4h A/A+ OOS (`docs/backtest-baseline.md`).

Flatten the whole book on the first of:
  1. closed 1D low <= coil_low (thesis dead)
  2. after the add: 4h TEMA TP (take) or SL (same-bar SL+TP → SL)
  3. GREEN→GREY on closed 1D only if the TEMA add never printed
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from scanner.indicators import adx
from scanner.radar import RadarConfig, _row_at, classify_rgg_series
from scanner.signal_engine import compute_signal

from .data_loader import load_klines, load_tf_ohlcv, resample_ohlcv

logger = logging.getLogger(__name__)

CLIP1_USDT = 100.0
CLIP2_USDT = 100.0
MAX_WAIT_DAYS = 20
TEMA_WINDOW = 400
TEMA_WARMUP = 220
LIVE_MIN_ATR_PCT = 0.10
LIVE_MAX_ATR_PCT = 8.0

_DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


@dataclass
class CoilUp:
    symbol: str
    bar_time: pd.Timestamp
    price: float
    coil_low: float
    coil_high: Optional[float]
    color: str


@dataclass
class TemaBuy:
    symbol: str
    bar_time: pd.Timestamp
    price: float
    stop_loss: float
    take_profit: float
    grade: str
    score: float
    atr_pct: float
    adx: float


@dataclass
class BookTrade:
    symbol: str
    coil_time: str
    clip1_entry: float
    clip1_qty: float
    coil_low: float
    coil_color: str
    added: bool
    tema_time: Optional[str]
    clip2_entry: Optional[float]
    clip2_qty: float
    tema_grade: Optional[str]
    tema_score: Optional[float]
    tema_sl: Optional[float]
    tema_tp: Optional[float]
    exit_time: Optional[str]
    exit_price: Optional[float]
    exit_reason: str
    clip1_pnl: float
    clip2_pnl: float
    pnl_usdt: float
    open_at_end: bool


def _qty(notional: float, price: float) -> float:
    if price <= 0 or notional <= 0:
        return 0.0
    return notional / price


def _iso(ts: Optional[pd.Timestamp]) -> Optional[str]:
    if ts is None or pd.isna(ts):
        return None
    return pd.Timestamp(ts).isoformat()


def iter_coil_ups(
    df_1d: pd.DataFrame,
    symbol: str,
    *,
    cfg: Optional[RadarConfig] = None,
) -> list[CoilUp]:
    """Closed-1D coil-UP rows (follow-through already stripped in `_row_at`)."""
    cfg = cfg or RadarConfig()
    cfg.validate()
    if df_1d is None or len(df_1d) < cfg.min_bars:
        return []
    plus_di, minus_di, adx_s = adx(df_1d, cfg.adx_length)
    colors = classify_rgg_series(
        plus_di, minus_di, adx_s,
        enter_adx=cfg.enter_adx,
        exit_adx=cfg.exit_adx,
    )
    warmup = max(cfg.min_bars - 1, cfg.coil_lookback + 1, cfg.adx_length * 2 + 5)
    out: list[CoilUp] = []
    for i in range(warmup, len(df_1d)):
        row = _row_at(df_1d, symbol, i, plus_di, minus_di, adx_s, colors, cfg)
        if row is None or row.breakout != "UP" or row.coil_low is None:
            continue
        out.append(CoilUp(
            symbol=symbol.upper(),
            bar_time=pd.Timestamp(df_1d.index[i]),
            price=float(row.price),
            coil_low=float(row.coil_low),
            coil_high=None if row.coil_high is None else float(row.coil_high),
            color=str(row.color),
        ))
    return out


def collect_tema_buys(
    df_4h: pd.DataFrame,
    symbol: str,
    *,
    min_atr_pct: float = LIVE_MIN_ATR_PCT,
    max_atr_pct: float = LIVE_MAX_ATR_PCT,
    after: Optional[pd.Timestamp] = None,
) -> list[TemaBuy]:
    """Closed-4h A/A+ BUY alerts using live-like ATR gates (not frozen ADX≥20)."""
    if df_4h is None or len(df_4h) < TEMA_WARMUP:
        return []
    df_htf = resample_ohlcv(df_4h, "1D")
    out: list[TemaBuy] = []
    n = len(df_4h)
    start_i = TEMA_WARMUP
    if after is not None:
        start_i = max(start_i, int(df_4h.index.searchsorted(pd.Timestamp(after))))
    for i in range(start_i, n):
        bar_ts = df_4h.index[i]
        slice_base = df_4h.iloc[max(0, i - TEMA_WINDOW + 1): i + 1]
        slice_htf = df_htf.loc[:bar_ts].iloc[-TEMA_WINDOW:]
        slice_daily = df_htf.loc[:bar_ts]
        sig = compute_signal(
            slice_base,
            symbol=symbol,
            timeframe="4h",
            htf_df=slice_htf if len(slice_htf) >= 10 else None,
            daily_df=slice_daily if len(slice_daily) >= 199 else None,
        )
        if sig is None or sig.side != "BUY" or sig.grade not in ("A", "A+"):
            continue
        if not (min_atr_pct <= sig.atr_pct <= max_atr_pct):
            continue
        out.append(TemaBuy(
            symbol=symbol.upper(),
            bar_time=pd.Timestamp(sig.timestamp),
            price=float(sig.price),
            stop_loss=float(sig.stop_loss),
            take_profit=float(sig.take_profit),
            grade=str(sig.grade),
            score=float(sig.score),
            atr_pct=float(sig.atr_pct),
            adx=float(sig.adx_value),
        ))
    return out


def _daily_colors(df_1d: pd.DataFrame, cfg: RadarConfig) -> pd.Series:
    plus_di, minus_di, adx_s = adx(df_1d, cfg.adx_length)
    return classify_rgg_series(
        plus_di, minus_di, adx_s,
        enter_adx=cfg.enter_adx,
        exit_adx=cfg.exit_adx,
    )


def simulate_book(
    coil: CoilUp,
    df_1d: pd.DataFrame,
    df_4h: pd.DataFrame,
    tema_buys: list[TemaBuy],
    *,
    clip1_usdt: float = CLIP1_USDT,
    clip2_usdt: float = CLIP2_USDT,
    max_wait_days: int = MAX_WAIT_DAYS,
    cfg: Optional[RadarConfig] = None,
    colors: Optional[pd.Series] = None,
) -> BookTrade:
    """Walk closed bars after coil-UP. Fill = alert close (same as paper)."""
    cfg = cfg or RadarConfig()
    qty1 = _qty(clip1_usdt, coil.price)
    colors = colors if colors is not None else _daily_colors(df_1d, cfg)

    coil_end = coil.bar_time + pd.Timedelta(days=1)
    wait_until = coil.bar_time + pd.Timedelta(days=max_wait_days)

    daily_after = df_1d[df_1d.index > coil.bar_time]
    h4_after = df_4h[df_4h.index >= coil_end]
    tema_by_ts = {
        pd.Timestamp(t.bar_time): t
        for t in tema_buys
        if t.symbol == coil.symbol and coil_end <= pd.Timestamp(t.bar_time) < wait_until
    }

    events: list[tuple[pd.Timestamp, int, str, Any]] = []
    for ts, row in h4_after.iterrows():
        events.append((pd.Timestamp(ts), 0, "4h", row))
    for ts, row in daily_after.iterrows():
        close_ts = pd.Timestamp(ts) + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
        events.append((close_ts, 1, "1d", (pd.Timestamp(ts), row)))
    events.sort(key=lambda x: (x[0], x[1]))

    added = False
    tema: Optional[TemaBuy] = None
    qty2 = 0.0
    add_bar_time: Optional[pd.Timestamp] = None
    prev_color = str(colors.loc[coil.bar_time]) if coil.bar_time in colors.index else coil.color

    def _finish(
        reason: str,
        when: pd.Timestamp,
        price: float,
        *,
        still_open: bool = False,
    ) -> BookTrade:
        p1 = coil.price
        p2 = tema.price if tema is not None else None
        c1 = qty1 * (price - p1)
        c2 = (qty2 * (price - p2)) if p2 is not None else 0.0
        return BookTrade(
            symbol=coil.symbol,
            coil_time=_iso(coil.bar_time) or "",
            clip1_entry=p1,
            clip1_qty=qty1,
            coil_low=coil.coil_low,
            coil_color=coil.color,
            added=added,
            tema_time=_iso(tema.bar_time) if tema is not None else None,
            clip2_entry=p2,
            clip2_qty=qty2,
            tema_grade=tema.grade if tema is not None else None,
            tema_score=tema.score if tema is not None else None,
            tema_sl=tema.stop_loss if tema is not None else None,
            tema_tp=tema.take_profit if tema is not None else None,
            exit_time=None if still_open else _iso(when),
            exit_price=None if still_open else float(price),
            exit_reason=reason,
            clip1_pnl=round(c1, 4),
            clip2_pnl=round(c2, 4),
            pnl_usdt=round(c1 + c2, 4),
            open_at_end=still_open,
        )

    for when, _prio, kind, payload in events:
        if kind == "4h":
            bar = payload
            ts = when
            if (
                not added
                and ts in tema_by_ts
                and ts < wait_until
            ):
                tema = tema_by_ts[ts]
                added = True
                qty2 = _qty(clip2_usdt, tema.price)
                add_bar_time = ts
                continue
            if added and add_bar_time is not None and ts > add_bar_time and tema is not None:
                low = float(bar["low"])
                high = float(bar["high"])
                sl_hit = low <= tema.stop_loss
                tp_hit = high >= tema.take_profit
                if sl_hit and tp_hit:
                    return _finish("tema_sl", ts, tema.stop_loss)
                if sl_hit:
                    return _finish("tema_sl", ts, tema.stop_loss)
                if tp_hit:
                    return _finish("tema_tp", ts, tema.take_profit)
            continue

        day_ts, row = payload
        low = float(row["low"])
        close = float(row["close"])
        if low <= coil.coil_low:
            return _finish("coil_low", when, coil.coil_low)
        color = str(colors.loc[day_ts]) if day_ts in colors.index else prev_color
        if (not added) and prev_color == "GREEN" and color == "GREY":
            return _finish("green_to_grey", when, close)
        prev_color = color

    last_px = float(df_4h["close"].iloc[-1]) if len(df_4h) else coil.price
    last_ts = pd.Timestamp(df_4h.index[-1]) if len(df_4h) else coil.bar_time
    return _finish("open", last_ts, last_px, still_open=True)


def run_symbols(
    symbols: list[str],
    *,
    start: date,
    end: date,
    trade_start: date,
    clip1_usdt: float = CLIP1_USDT,
    clip2_usdt: float = CLIP2_USDT,
    max_wait_days: int = MAX_WAIT_DAYS,
) -> list[BookTrade]:
    cfg = RadarConfig()
    trades: list[BookTrade] = []
    trade_start_ts = pd.Timestamp(trade_start, tz="UTC")
    for symbol in symbols:
        logger.info("coil-TEMA book %s %s→%s", symbol, start, end)
        df_4h = load_klines(symbol, "4h", start, end)
        if len(df_4h) < TEMA_WARMUP:
            logger.warning("%s 4h too short (%d)", symbol, len(df_4h))
            continue
        df_1d, src = load_tf_ohlcv(symbol, "1d", start, end)
        logger.info("%s 1d source=%s bars=%d", symbol, src, len(df_1d))
        coils = [
            c for c in iter_coil_ups(df_1d, symbol, cfg=cfg)
            if c.bar_time >= trade_start_ts
        ]
        tema = collect_tema_buys(
            df_4h, symbol,
            after=trade_start_ts - pd.Timedelta(days=1),
        )
        logger.info("%s coil-UPs=%d 4h A/A+ BUY=%d", symbol, len(coils), len(tema))
        occupied_until: Optional[pd.Timestamp] = None
        for coil in coils:
            if occupied_until is not None and coil.bar_time <= occupied_until:
                continue
            trade = simulate_book(
                coil, df_1d, df_4h, tema,
                clip1_usdt=clip1_usdt,
                clip2_usdt=clip2_usdt,
                max_wait_days=max_wait_days,
                cfg=cfg,
            )
            trades.append(trade)
            if trade.exit_time:
                occupied_until = pd.Timestamp(trade.exit_time)
            else:
                occupied_until = pd.Timestamp(df_1d.index[-1])
    return trades


def trades_to_frame(trades: list[BookTrade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    return pd.DataFrame([asdict(t) for t in trades])


def summarize(trades: list[BookTrade]) -> dict[str, Any]:
    closed = [t for t in trades if not t.open_at_end]
    pnls = [t.pnl_usdt for t in closed]
    wins = [t for t in closed if t.pnl_usdt > 0]
    added = [t for t in trades if t.added]
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    return {
        "n_books": len(trades),
        "n_closed": len(closed),
        "n_open": sum(1 for t in trades if t.open_at_end),
        "n_with_tema_add": len(added),
        "win_closed": len(wins),
        "win_pct_closed": round(100.0 * len(wins) / len(closed), 1) if closed else None,
        "sum_pnl_usdt": round(sum(pnls), 4) if pnls else 0.0,
        "avg_pnl_usdt": round(sum(pnls) / len(pnls), 4) if pnls else None,
        "exit_reasons": reasons,
        "clip1_usdt": CLIP1_USDT,
        "clip2_usdt": CLIP2_USDT,
        "note": (
            "Not frozen 4h A/A+ OOS. Coil-UP is unranked. "
            "$100+$100 notional, fill=alert close, one book per symbol at a time."
        ),
    }


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Coil-UP + 4h TEMA A/A+ two-clip book")
    p.add_argument("--symbols", nargs="+", default=_DEFAULT_SYMBOLS)
    p.add_argument("--warmup-start", default="2025-07-01")
    p.add_argument("--start", default="2026-01-01", help="Count coil-UPs on/after this date")
    p.add_argument("--end", default=str(date.today() - timedelta(days=1)))
    p.add_argument("--out", default=str(Path(__file__).parent / "results"))
    return p.parse_args(argv)


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    warmup = date.fromisoformat(args.warmup_start)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    trades = run_symbols(
        [s.upper() for s in args.symbols],
        start=warmup,
        end=end,
        trade_start=start,
    )
    df = trades_to_frame(trades)
    summary = summarize(trades)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S")
    if not df.empty:
        df.to_csv(out_dir / f"coil_tema_book_{stamp}.csv", index=False)
        df.to_csv(out_dir / "coil_tema_book_latest.csv", index=False)
    print(f"Window coil-UPs {start} → {end} (warmup from {warmup})")
    print(f"Books {summary['n_books']}  closed {summary['n_closed']}  "
          f"open {summary['n_open']}  with TEMA add {summary['n_with_tema_add']}")
    print(f"Closed win {summary['win_closed']}/{summary['n_closed']} "
          f"({summary['win_pct_closed']}%)  "
          f"sum PnL ${summary['sum_pnl_usdt']}  avg ${summary['avg_pnl_usdt']}")
    print(f"Exits {summary['exit_reasons']}")
    print(summary["note"])
    if not df.empty:
        cols = [
            "symbol", "coil_time", "clip1_entry", "coil_low", "added",
            "tema_time", "tema_grade", "clip2_entry", "tema_tp",
            "exit_reason", "exit_price", "clip1_pnl", "clip2_pnl", "pnl_usdt",
        ]
        print(df[cols].to_string(index=False))


if __name__ == "__main__":
    main()
