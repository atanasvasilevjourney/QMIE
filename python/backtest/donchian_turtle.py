"""
Donchian turtle portfolio backtest — USDT-M daily bars, top-N universe.

Manual measurement only. Does not dispatch ``QMIE-DonchianTurtle`` alerts yet.

Usage:
    cd python
    python -m backtest.donchian_turtle --start 2024-01-01 --split 2025-01-01
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from backtest.data_loader import load_tf_ohlcv
from scanner.donchian_turtle import TurtleParams, donchian_turtle_frame, min_warmup_bars

logger = logging.getLogger(__name__)

DEFAULT_TOP_UNIVERSE = 100
DEFAULT_MAX_POSITIONS = 20
DEFAULT_REBALANCE_DAYS = 1
INITIAL_EQUITY = 100_000.0

# Static fallback when ``fapi`` ticker REST is geo-blocked (451/403).
_FALLBACK_SYMBOLS: list[str] = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "AVAXUSDT", "LINKUSDT", "DOTUSDT", "MATICUSDT", "LTCUSDT", "TRXUSDT", "BCHUSDT",
    "ATOMUSDT", "UNIUSDT", "ETCUSDT", "XLMUSDT", "FILUSDT", "APTUSDT", "ARBUSDT",
    "OPUSDT", "NEARUSDT", "INJUSDT", "SUIUSDT", "SEIUSDT", "TIAUSDT", "WLDUSDT",
    "FETUSDT", "RNDRUSDT", "IMXUSDT", "STXUSDT", "AAVEUSDT", "MKRUSDT", "GRTUSDT",
    "ALGOUSDT", "VETUSDT", "ICPUSDT", "THETAUSDT", "FTMUSDT", "SANDUSDT", "MANAUSDT",
    "AXSUSDT", "EGLDUSDT", "FLOWUSDT", "XTZUSDT", "EOSUSDT", "KAVAUSDT", "RUNEUSDT",
    "SNXUSDT", "CRVUSDT", "LDOUSDT", "DYDXUSDT", "GMXUSDT", "COMPUSDT", "1INCHUSDT",
    "ZECUSDT", "DASHUSDT", "IOTAUSDT", "NEOUSDT", "QTUMUSDT", "ZILUSDT", "ENJUSDT",
    "CHZUSDT", "GALAUSDT", "APEUSDT", "LRCUSDT", "KSMUSDT", "BLURUSDT", "JTOUSDT",
    "PYTHUSDT", "JUPUSDT", "WIFUSDT", "PEPEUSDT", "BONKUSDT", "FLOKIUSDT", "ORDIUSDT",
    "1000SHIBUSDT", "1000FLOKIUSDT", "1000PEPEUSDT", "1000BONKUSDT", "ENAUSDT",
    "NOTUSDT", "TONUSDT", "TAOUSDT", "ONDOUSDT", "PENDLEUSDT", "STRKUSDT", "ZKUSDT",
    "LISTAUSDT", "BBUSDT", "IOUSDT", "ZROUSDT", "RENDERUSDT", "POLUSDT", "EIGENUSDT",
    "HMSTRUSDT", "CATIUSDT", "SCRUSDT", "GOATUSDT", "MOODENGUSDT", "COWUSDT",
    "CETUSUSDT", "ACTUSDT", "PNUTUSDT", "BANUSDT", "AKTUSDT", "MEUSDT", "MOVEUSDT",
    "VIRTUALUSDT", "PENGUUSDT", "USUALUSDT", "FARTCOINUSDT", "TRUMPUSDT", "MELANIAUSDT",
]


def resolve_universe(
    top_n: int = DEFAULT_TOP_UNIVERSE,
    *,
    min_quote_volume: float = 5_000_000.0,
) -> tuple[list[str], str]:
    """Return up to ``top_n`` USDT-M perpetual symbols sorted by 24h quote volume."""
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code in (403, 451):
            raise RuntimeError(f"HTTP {resp.status_code}")
        resp.raise_for_status()
        rows = resp.json()
        scored: list[tuple[str, float]] = []
        for row in rows:
            sym = str(row.get("symbol") or "")
            if not sym.endswith("USDT"):
                continue
            if sym.endswith("USDC") or "BUSD" in sym:
                continue
            qv = float(row.get("quoteVolume") or 0.0)
            if qv < min_quote_volume:
                continue
            scored.append((sym, qv))
        scored.sort(key=lambda x: -x[1])
        syms = [s for s, _ in scored[:top_n]]
        if syms:
            return syms, "binance_24hr"
    except Exception as e:
        logger.warning("Universe REST failed (%s); using static fallback", e)
    base = list(dict.fromkeys(_FALLBACK_SYMBOLS))
    return base[:top_n], "static_fallback"


@dataclass
class TurtleBacktestResult:
    params: TurtleParams
    universe: list[str]
    universe_source: str
    start: date
    end: date
    split: date | None
    equity_curve: pd.DataFrame
    daily_returns: pd.Series
    metrics: dict[str, Any] = field(default_factory=dict)
    is_metrics: dict[str, Any] = field(default_factory=dict)
    oos_metrics: dict[str, Any] = field(default_factory=dict)


def _metrics_for_returns(r: pd.Series) -> dict[str, Any]:
    r = r.dropna()
    if r.empty:
        return {"days": 0, "total_return_pct": 0.0, "max_drawdown_pct": 0.0, "sharpe": 0.0}
    eq = (1.0 + r).cumprod()
    total = (float(eq.iloc[-1]) - 1.0) * 100.0
    dd = float((eq / eq.cummax() - 1.0).min() * 100.0)
    sharpe = 0.0
    if r.std() > 0:
        sharpe = float(r.mean() / r.std() * math.sqrt(365.0))
    return {
        "days": int(len(r)),
        "total_return_pct": round(total, 3),
        "max_drawdown_pct": round(dd, 3),
        "sharpe": round(sharpe, 3),
        "ann_vol_pct": round(float(r.std() * math.sqrt(365.0) * 100.0), 3),
    }


def _bar_row(frame: pd.DataFrame, ts: pd.Timestamp) -> pd.Series | None:
    if frame.empty:
        return None
    idx = frame.index
    if getattr(idx, "tz", None) is not None:
        hits = idx.normalize() == ts.normalize()
    else:
        hits = idx.normalize() == ts.normalize()
    if not hits.any():
        return None
    return frame.loc[hits].iloc[-1]


def run_turtle_portfolio(
    symbols: list[str],
    start: date,
    end: date,
    *,
    params: TurtleParams | None = None,
    max_positions: int = DEFAULT_MAX_POSITIONS,
    rebalance_days: int = DEFAULT_REBALANCE_DAYS,
    initial_equity: float = INITIAL_EQUITY,
    cache_dir: Path | None = None,
    data_pad_days: int = 120,
) -> TurtleBacktestResult:
    """
    Equal-weight portfolio among up to ``max_positions`` names.

    Signals use the **prior** session close (no same-bar lookahead). Daily
    returns are close-to-close on held weights.
    """
    p = params or TurtleParams()
    warmup = min_warmup_bars(p)
    load_start = start - timedelta(days=data_pad_days + p.entry_channel * 2)

    panels: dict[str, pd.DataFrame] = {}
    signals: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        kw = {}
        if cache_dir is not None:
            kw["cache_dir"] = cache_dir
        try:
            ohlcv, _src = load_tf_ohlcv(sym, "1d", load_start, end, **kw)
        except Exception as e:
            logger.debug("Skip %s load: %s", sym, e)
            continue
        if len(ohlcv) < warmup:
            continue
        panels[sym] = ohlcv
        signals[sym] = donchian_turtle_frame(ohlcv, p)

    if not panels:
        empty = pd.DataFrame(columns=["equity", "daily_return", "names"])
        return TurtleBacktestResult(
            params=p,
            universe=symbols,
            universe_source="",
            start=start,
            end=end,
            split=None,
            equity_curve=empty,
            daily_returns=pd.Series(dtype=float),
        )

    # Calendar = union of BTC (or first loaded) index clipped to [start, end]
    ref = panels["BTCUSDT"] if "BTCUSDT" in panels else next(iter(panels.values()))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
    cal = ref.index[(ref.index >= start_ts) & (ref.index <= end_ts)]
    if len(cal) < 2:
        empty = pd.DataFrame(columns=["equity", "daily_return", "names"])
        return TurtleBacktestResult(
            params=p,
            universe=list(panels.keys()),
            universe_source="",
            start=start,
            end=end,
            split=None,
            equity_curve=empty,
            daily_returns=pd.Series(dtype=float),
        )

    holdings: dict[str, float] = {}
    equity = float(initial_equity)
    eq_rows: list[dict[str, Any]] = []
    last_rebalance_i = -rebalance_days

    for i, ts in enumerate(cal):
        ts = pd.Timestamp(ts)
        signal_ts = pd.Timestamp(cal[i - 1]) if i > 0 else None

        if signal_ts is not None:
            for sym in list(holdings.keys()):
                sig = signals.get(sym)
                if sig is None:
                    continue
                row = _bar_row(sig, signal_ts)
                if row is not None and bool(row.get("exit_long", False)):
                    holdings.pop(sym, None)

            if i - last_rebalance_i >= max(1, rebalance_days):
                cands: list[tuple[str, float]] = []
                for sym, sig in signals.items():
                    if sym in holdings:
                        continue
                    row = _bar_row(sig, signal_ts)
                    if row is None or not bool(row.get("entry_long", False)):
                        continue
                    cands.append((sym, float(row.get("strength") or 0.0)))
                cands.sort(key=lambda x: -x[1])
                for sym, _ in cands:
                    if len(holdings) >= max_positions:
                        break
                    holdings[sym] = 1.0
                last_rebalance_i = i

        if holdings:
            w = 1.0 / len(holdings)
            holdings = {s: w for s in holdings}

        day_ret = 0.0
        if holdings and i > 0:
            prev_ts = pd.Timestamp(cal[i - 1])
            parts: list[float] = []
            for sym, w in holdings.items():
                ohlcv = panels.get(sym)
                if ohlcv is None:
                    continue
                r0 = _bar_row(ohlcv, prev_ts)
                r1 = _bar_row(ohlcv, ts)
                if r0 is None or r1 is None:
                    continue
                c0 = float(r0["close"])
                c1 = float(r1["close"])
                if c0 <= 0:
                    continue
                parts.append(w * (c1 / c0 - 1.0))
            day_ret = sum(parts) if parts else 0.0

        equity *= 1.0 + day_ret
        eq_rows.append(
            {
                "date": ts.date().isoformat(),
                "equity": equity,
                "daily_return": day_ret,
                "names": len(holdings),
            }
        )

    eq_df = pd.DataFrame(eq_rows)
    eq_df.index = pd.to_datetime(eq_df["date"])
    daily = pd.Series(eq_df["daily_return"].values, index=eq_df.index, name="ret")
    full_metrics = _metrics_for_returns(daily)
    return TurtleBacktestResult(
        params=p,
        universe=sorted(panels.keys()),
        universe_source="loaded",
        start=start,
        end=end,
        split=None,
        equity_curve=eq_df,
        daily_returns=daily,
        metrics=full_metrics,
    )


def apply_split_metrics(result: TurtleBacktestResult, split: date) -> TurtleBacktestResult:
    r = result.daily_returns
    if r.empty:
        return result
    split_ts = pd.Timestamp(split, tz="UTC") if r.index.tz else pd.Timestamp(split)
    is_r = r[r.index < split_ts]
    oos_r = r[r.index >= split_ts]
    result.split = split
    result.is_metrics = _metrics_for_returns(is_r)
    result.oos_metrics = _metrics_for_returns(oos_r)
    return result


def benchmark_btc_returns(
    start: date,
    end: date,
    cache_dir: Path | None = None,
) -> pd.Series:
    kw = {}
    if cache_dir is not None:
        kw["cache_dir"] = cache_dir
    df, _ = load_tf_ohlcv("BTCUSDT", "1d", start, end, **kw)
    if df.empty:
        return pd.Series(dtype=float)
    return df["close"].pct_change().dropna()


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Donchian turtle portfolio backtest (daily USDT-M)")
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default=str(date.today() - timedelta(days=1)))
    p.add_argument("--split", default="2025-01-01", help="IS/OOS split date")
    p.add_argument("--top-universe", type=int, default=DEFAULT_TOP_UNIVERSE)
    p.add_argument("--max-positions", type=int, default=DEFAULT_MAX_POSITIONS)
    p.add_argument("--rebalance-days", type=int, default=DEFAULT_REBALANCE_DAYS)
    p.add_argument("--no-vwap", action="store_true")
    p.add_argument("--out", default=str(Path(__file__).parent / "results" / "donchian_turtle"))
    return p.parse_args(argv)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    split = date.fromisoformat(args.split) if args.split else None
    universe, src = resolve_universe(args.top_universe)
    params = TurtleParams(use_vwap_filter=not args.no_vwap)
    logger.info("Universe %d symbols (%s)", len(universe), src)
    result = run_turtle_portfolio(
        universe,
        start,
        end,
        params=params,
        max_positions=args.max_positions,
        rebalance_days=args.rebalance_days,
    )
    result.universe_source = src
    if split:
        apply_split_metrics(result, split)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    result.equity_curve.to_parquet(out_dir / "equity_curve.parquet")
    summary = {
        "strategy": "QMIE-DonchianTurtle",
        "universe_source": src,
        "symbols_loaded": len(result.universe),
        "params": asdict(params),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "split": split.isoformat() if split else None,
        "metrics": result.metrics,
        "is_metrics": result.is_metrics,
        "oos_metrics": result.oos_metrics,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
