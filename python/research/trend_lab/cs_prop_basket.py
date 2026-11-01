"""Cross-sectional prop basket — multi-horizon votes, ranked equal weights.

Research only. Mentor-style: N decorrelated assets, 3 lookbacks, conviction
votes, ~1/N cap, target gross exposure (e.g. 68%). Long-only daily rebalance.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .carver import normalised_price
from .data import load_etf, load_symbol
from .metrics import kpis_from_net
from .protocol import SPLIT

ANN_CS = 252

# Decorrelated mix: crypto, metal, equity beta, sectors, bonds, EM, vol, fx, real assets
UNIVERSE_20: tuple[str, ...] = (
    "BTC",
    "GLD",
    "QQQ",
    "SMH",
    "XLE",
    "TLT",
    "EEM",
    "HYG",
    "USO",
    "DBA",
    "UUP",
    "EWJ",
    "EWZ",
    "XLU",
    "BOTZ",
    "SLV",
    "VNQ",
    "IEF",
    "FXE",
    "CPER",
)

UNIVERSE_10: tuple[str, ...] = (
    "BTC",
    "GLD",
    "QQQ",
    "SMH",
    "TLT",
    "EEM",
    "USO",
    "HYG",
    "XLU",
    "DBA",
)


@dataclass(frozen=True)
class CsBasketParams:
    horizons: tuple[int, ...] = (14, 40, 80)
    min_votes: int = 2  # of len(horizons); 2-of-3 long
    top_n: int = 10
    gross_target: float = 0.68
    per_name_cap: float | None = None  # default 1 / n_symbols in panel
    cost_bps: float = 2.0
    exec_lag: int = 1
    ann_days: int = ANN_CS


def _align_btc_to_index(btc: pd.Series, session: pd.DatetimeIndex) -> pd.Series:
    btc = btc.sort_index()
    out = btc.reindex(session)
    for i, ts in enumerate(session):
        if pd.notna(out.iloc[i]):
            continue
        loc = btc.index.searchsorted(ts, side="right") - 1
        if loc >= 0:
            out.iloc[i] = btc.iloc[loc]
    return out.ffill()


def load_cs_panel(
    symbols: tuple[str, ...] | list[str],
    *,
    start: date | None = None,
    end: date | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Daily close panel; BTC from Vision aligned to ETF session dates."""
    start = start or SPLIT.is_start
    end = end or SPLIT.oos_end
    t0 = pd.Timestamp(start, tz="UTC")
    t1 = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    sources: dict[str, str] = {}
    frames: dict[str, pd.Series] = {}
    session: pd.DatetimeIndex | None = None

    for sym in symbols:
        s = sym.upper()
        if s == "BTC":
            df, src = load_symbol("BTCUSDT", "1d", start=start, end=end)
            sources[s] = src
            ser = df["close"].copy()
            ser.index = pd.DatetimeIndex(ser.index).tz_convert("UTC").normalize()
            frames[s] = ser.rename(s)
            continue
        try:
            ser, src = load_etf(s)
            sources[s] = src
            ser = ser.loc[t0:t1].rename(s)
            frames[s] = ser
            session = ser.index if session is None else session.union(ser.index)
        except Exception as exc:
            sources[s] = f"skip:{exc}"

    if session is None or not session.size:
        return pd.DataFrame(), sources

    session = session.sort_values()
    if "BTC" in frames:
        frames["BTC"] = _align_btc_to_index(frames["BTC"], session)

    panel = pd.DataFrame({k: v.reindex(session).ffill() for k, v in frames.items()})
    panel = panel.sort_index().loc[t0:]
    panel = panel.ffill()
    panel = panel.loc[:, panel.notna().any(axis=0)]
    panel = panel.dropna(how="any", axis=0)
    return panel, sources


def relative_strength_panel(panel: pd.DataFrame, *, ann_days: int = ANN_CS) -> pd.DataFrame:
    """R = PN_i - mean(PN) for each asset."""
    pn = pd.DataFrame({
        c: normalised_price(panel[c], ann_days=ann_days).reindex(panel.index).ffill()
        for c in panel.columns
    })
    bench = pn.mean(axis=1)
    return pn.sub(bench, axis=0)


def cs_vote_matrix(panel: pd.DataFrame, p: CsBasketParams) -> pd.DataFrame:
    """Votes per asset per day (0..len(horizons))."""
    r = relative_strength_panel(panel, ann_days=p.ann_days)
    out = pd.DataFrame(index=panel.index, columns=panel.columns, dtype=float)
    for c in panel.columns:
        ri = r[c]
        v = pd.Series(0.0, index=panel.index)
        for h in p.horizons:
            v = v + (ri - ri.shift(h) > 0).astype(float)
        out[c] = v
    return out


def cs_conviction_weights(panel: pd.DataFrame, p: CsBasketParams) -> pd.DataFrame:
    """Daily weights: top names by votes (>= min_votes), equal split, gross scaled."""
    votes = cs_vote_matrix(panel, p)
    r = relative_strength_panel(panel, ann_days=p.ann_days)
    idx = panel.index
    n_sym = panel.shape[1]
    cap = p.per_name_cap if p.per_name_cap is not None else (1.0 / max(n_sym, 1))
    rows: list[pd.Series] = []

    for ts in idx:
        v_row = votes.loc[ts]
        eligible = v_row[v_row >= p.min_votes].index.tolist()
        if not eligible:
            rows.append(pd.Series(0.0, index=panel.columns))
            continue
        r_row = r.loc[ts, eligible].sort_values(ascending=False)
        ranked = r_row.index.tolist()[: p.top_n]
        w = pd.Series(0.0, index=panel.columns)
        if ranked:
            each = min(cap, p.gross_target / len(ranked))
            for c in ranked:
                w[c] = each
            gross = w.sum()
            if gross > p.gross_target and gross > 0:
                w = w * (p.gross_target / gross)
        rows.append(w)

    return pd.DataFrame(rows, index=idx)


def basket_net_returns(panel: pd.DataFrame, weights: pd.DataFrame, p: CsBasketParams) -> pd.Series:
    rets = panel.pct_change(fill_method=None).fillna(0.0)
    held = weights.shift(p.exec_lag).fillna(0.0)
    gross = (held * rets).sum(axis=1)
    turnover = held.diff().abs().fillna(held.abs()).sum(axis=1)
    return (gross - turnover * (p.cost_bps / 1e4)).rename("net")


def avg_pairwise_corr(panel: pd.DataFrame, *, lookback: int = 60) -> float:
    rets = panel.pct_change(fill_method=None).fillna(0.0)
    if len(rets) < lookback + 2:
        return float("nan")
    c = rets.iloc[-lookback:].corr().values
    n = c.shape[0]
    if n < 2:
        return float("nan")
    mask = ~np.eye(n, dtype=bool)
    return float(np.nanmean(c[mask]))


def evaluate_cs_basket(
    panel: pd.DataFrame,
    p: CsBasketParams,
    *,
    is_end: pd.Timestamp,
) -> dict[str, object]:
    w = cs_conviction_weights(panel, p)
    net = basket_net_returns(panel, w, p)
    is_end = pd.Timestamp(is_end, tz="UTC") if is_end.tzinfo is None else is_end
    cut = is_end + pd.Timedelta(days=1)
    return {
        "params": p,
        "weights": w,
        "net": net,
        "is": kpis_from_net(net.loc[:is_end], ann=p.ann_days),
        "oos": kpis_from_net(net.loc[cut:], ann=p.ann_days),
        "avg_gross": float(w.sum(axis=1).mean()),
        "avg_names": float((w > 0).sum(axis=1).mean()),
    }
