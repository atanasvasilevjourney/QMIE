"""
Event study: compression + Donchian trigger instances and forward returns.

Evaluated on closed 15m bars; forward returns from the **next bar open**.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from long_vol.config import EntryConfig, LongVolConfig
from long_vol.features.long_vol_features import btc_ok_series, compute_long_vol_features
from long_vol.data.validate import validate_ohlcv


HORIZON_BARS = {"1h": 4, "4h": 16, "12h": 48, "24h": 96}


@dataclass
class EventStudyResult:
    events: pd.DataFrame
    attribution: pd.DataFrame
    symbols: list[str]


def _raw_trigger_mask(feat: pd.DataFrame, *, require_compression: bool = True) -> pd.Series:
    comp = feat["compression_ok"].fillna(False).astype(bool)
    brk = (feat["close_1h"] > feat["don_up_1h"]).fillna(False).astype(bool)
    if require_compression:
        return comp & brk
    return brk


def _gate_columns(row: pd.Series, btc_ok: bool, ent: EntryConfig) -> dict[str, bool]:
    return {
        "gate_compression": bool(row.get("compression_ok")),
        "gate_don_break": bool(row.get("close_1h", 0) > row.get("don_up_1h", np.inf)),
        "gate_dist_atr": ent.dist_atr_min <= float(row.get("dist_atr", -1)) <= ent.dist_atr_max,
        "gate_rvol": float(row.get("rvol", 0)) >= ent.rvol_min,
        "gate_adx": ent.adx_min <= float(row.get("adx", 0)) <= ent.adx_max,
        "gate_adx_slope": float(row.get("adx_slope", 0)) > 0,
        "gate_rsi": float(row.get("rsi_1h", 100)) < ent.rsi_max,
        "gate_btc": btc_ok,
    }


def forward_returns_from_next_open(
    df15: pd.DataFrame,
    event_times: pd.DatetimeIndex,
    *,
    fee_bps: float = 5.5,
) -> pd.DataFrame:
    """Percent returns net of round-trip taker fee (entry + exit)."""
    opens = df15["open"]
    idx = df15.index
    pos = idx.get_indexer(event_times)
    rows = []
    fee = 2.0 * fee_bps / 10_000.0
    for i, ts in zip(pos, event_times):
        if i < 0 or i + 1 >= len(idx):
            continue
        entry_i = i + 1
        entry_px = float(opens.iloc[entry_i])
        if entry_px <= 0:
            continue
        rec = {"timestamp": ts, "entry_open": entry_px}
        for name, bars in HORIZON_BARS.items():
            exit_i = entry_i + bars
            if exit_i >= len(idx):
                rec[f"ret_{name}_pct"] = np.nan
                rec[f"r_{name}"] = np.nan
                continue
            exit_px = float(opens.iloc[exit_i])
            gross = (exit_px - entry_px) / entry_px
            net = gross - fee
            rec[f"ret_{name}_pct"] = net * 100.0
            rec[f"r_{name}"] = net
        rows.append(rec)
    return pd.DataFrame(rows)


def run_event_study(
    panels: dict[str, pd.DataFrame],
    cfg: LongVolConfig,
    *,
    btc15: pd.DataFrame | None = None,
    require_compression: bool = True,
) -> EventStudyResult:
    """Run trigger scan + attribution on multiple symbols."""
    ent = cfg.entry
    if btc15 is None and cfg.data.btc_symbol in panels:
        btc15 = panels[cfg.data.btc_symbol]
    btc_ok = btc_ok_series(btc15, cfg.features.vwap_bars) if btc15 is not None else None

    all_events: list[pd.DataFrame] = []
    for sym, df15 in panels.items():
        rep = validate_ohlcv(df15, timeframe=cfg.data.base_tf)
        lv = compute_long_vol_features(
            df15, cfg=cfg.features, blocked=rep.blocked_mask,
        )
        feat = lv.df15
        mask = _raw_trigger_mask(feat, require_compression=require_compression)
        if not mask.any():
            continue
        hits = feat.loc[mask].copy()
        hits["symbol"] = sym
        if btc_ok is not None:
            hits["btc_ok"] = btc_ok.reindex(hits.index).fillna(False).astype(bool)
        else:
            hits["btc_ok"] = True

        gate_rows = []
        for ts, row in hits.iterrows():
            g = _gate_columns(row, bool(row["btc_ok"]), ent)
            g["all_gates"] = all(g.values())
            g["timestamp"] = ts
            gate_rows.append(g)
        gates = pd.DataFrame(gate_rows).set_index("timestamp")
        merged = hits.join(gates)
        merged.index.name = "timestamp"
        fwd = forward_returns_from_next_open(
            df15, pd.DatetimeIndex(merged.index),
            fee_bps=cfg.costs.taker_fee * 10_000,
        )
        merged = merged.reset_index()
        if not fwd.empty:
            merged = merged.merge(fwd, on="timestamp", how="left")
        all_events.append(merged)

    if not all_events:
        empty = pd.DataFrame()
        return EventStudyResult(events=empty, attribution=empty, symbols=list(panels))

    events = pd.concat(all_events, ignore_index=True)
    attr = _attribution_table(events)
    return EventStudyResult(events=events, attribution=attr, symbols=list(panels))


def _attribution_table(events: pd.DataFrame) -> pd.DataFrame:
    """Count how many raw triggers each gate would block."""
    if events.empty:
        return pd.DataFrame()
    gate_cols = [c for c in events.columns if c.startswith("gate_") and c != "gate_all"]
    base = len(events)
    rows = [{"gate": "raw_triggers", "pass_count": base, "block_count": 0}]
    for col in gate_cols:
        if col not in events.columns:
            continue
        passed = int(events[col].sum())
        rows.append({"gate": col.replace("gate_", ""), "pass_count": passed, "block_count": base - passed})
    if "all_gates" in events.columns:
        passed = int(events["all_gates"].sum())
        rows.append({"gate": "all_gates", "pass_count": passed, "block_count": base - passed})
    return pd.DataFrame(rows)


def bucket_summary(
    events: pd.DataFrame,
    col: str,
    ret_col: str = "ret_24h_pct",
    bins: Iterable[float] | None = None,
) -> pd.DataFrame:
    if events.empty or col not in events.columns:
        return pd.DataFrame()
    s = events.dropna(subset=[col, ret_col])
    if s.empty:
        return pd.DataFrame()
    if bins is None:
        qs = s[col].quantile([0.25, 0.5, 0.75]).tolist()
        bins = [-np.inf] + qs + [np.inf]
    s = s.copy()
    s["bucket"] = pd.cut(s[col], bins=bins, duplicates="drop")
    g = s.groupby("bucket", observed=True)[ret_col]
    out = g.agg(["mean", "median", "count"]).reset_index()
    out["hit_rate"] = s.groupby("bucket", observed=True)[ret_col].apply(lambda x: (x > 0).mean()).values
    return out
