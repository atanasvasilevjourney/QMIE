"""
Entry/exit intent evaluation on a **closed** 15m bar.

Returns intents to fill at next bar open (except stop handled in engine).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

from long_vol.config import EntryConfig, ExitConfig
from long_vol.signals.state import SymbolState, Transition, apply_no_chase, pullback_reentry_ready


@dataclass(frozen=True)
class EntryIntent:
    symbol: str
    bar_ts: pd.Timestamp
    entry_price: float  # next open (placeholder until engine)
    stop: float
    reason: str


@dataclass(frozen=True)
class ExitIntent:
    symbol: str
    bar_ts: pd.Timestamp
    reason: str


@dataclass
class SymbolRuntime:
    state: SymbolState = SymbolState.IDLE
    cooldown_until: Optional[pd.Timestamp] = None
    vwap_below_streak: int = 0
    entry_bar: Optional[pd.Timestamp] = None
    entry_price: Optional[float] = None
    stop: Optional[float] = None
    initial_risk: Optional[float] = None


def _gate_row(row: pd.Series, btc_ok: bool, *, ent: EntryConfig) -> dict[str, bool]:
    return {
        "compression_ok": bool(row.get("compression_ok")),
        "don_break": bool(row.get("close_1h", 0) > row.get("don_up_1h", float("inf"))),
        "dist_atr": ent.dist_atr_min <= float(row.get("dist_atr", -1)) <= ent.dist_atr_max,
        "rvol": float(row.get("rvol", 0)) >= ent.rvol_min,
        "adx_band": ent.adx_min <= float(row.get("adx", 0)) <= ent.adx_max,
        "adx_slope": float(row.get("adx_slope", 0)) > 0,
        "rsi": float(row.get("rsi_1h", 100)) < ent.rsi_max,
        "btc_ok": btc_ok,
    }


def evaluate_bar(
    symbol: str,
    ts: pd.Timestamp,
    row: pd.Series,
    *,
    runtime: SymbolRuntime,
    btc_ok: bool,
    ent: EntryConfig,
    ex: ExitConfig,
    liquidity_ok: bool = True,
    in_position: bool = False,
) -> tuple[Optional[EntryIntent], Optional[ExitIntent], SymbolRuntime, dict[str, Any]]:
    """Evaluate one closed 15m bar. Updates runtime state."""
    rt = runtime
    meta: dict[str, Any] = {"gates": {}, "transition": None}

    if rt.cooldown_until is not None and ts < rt.cooldown_until:
        meta["cooldown"] = True
        return None, None, rt, meta

    extended = (
        float(row.get("rsi_1h", 0)) > ent.no_chase_rsi
        or float(row.get("dist_atr", 0)) > ent.no_chase_dist_atr
    )
    trigger = bool(row.get("close_1h", 0) > row.get("don_up_1h", float("inf")))
    compression = bool(row.get("compression_ok"))

    tr = apply_no_chase(rt.state, extended=extended, trigger=trigger, compression=compression)
    if rt.state == SymbolState.PULLBACK_WATCH and pullback_reentry_ready(
        low15=float(row["low"]) if "low" in row else float("nan"),
        close15=float(row["close"]) if "close" in row else float("nan"),
        vwap24=float(row.get("vwap24", float("nan"))),
        don_mid_1h=float(row.get("don_mid_1h", float("nan"))),
        close_1h=float(row.get("close_1h", float("nan"))),
        prior_1h_high=float(row.get("don_up_1h", float("nan"))),
    ):
        tr = Transition(rt.state, SymbolState.SETUP, "pullback_reentry")
    rt.state = tr.new
    meta["transition"] = tr.reason

    exit_int: Optional[ExitIntent] = None
    if in_position:
        if float(row.get("close_1h", 1e9)) < float(row.get("exit_don_dn", -1e9)):
            exit_int = ExitIntent(symbol, ts, "don_trail")
        elif float(row.get("close", 0)) < float(row.get("vwap24", 0)):
            rt.vwap_below_streak += 1
        else:
            rt.vwap_below_streak = 0
        if rt.vwap_below_streak >= ex.vwap_exit_bars:
            exit_int = ExitIntent(symbol, ts, "vwap")
        if rt.entry_bar is not None:
            bars_held = (ts - rt.entry_bar) / pd.Timedelta(minutes=15)
            if bars_held >= ex.time_stop_bars and rt.initial_risk:
                # time stop checked in engine with +1R — flag here
                meta["time_stop_check"] = True

    entry_int: Optional[EntryIntent] = None
    if not in_position and rt.state == SymbolState.TRIGGERED:
        gates = _gate_row(row, btc_ok, ent=ent)
        gates["liquidity"] = liquidity_ok
        meta["gates"] = gates
        if all(gates.values()):
            atr15 = float(row.get("atr15", 0))
            close = float(row.get("close", row.get("tp", 0)))
            don_mid = float(row.get("don_mid_1h", 0))
            stop = max(don_mid, close - ex.stop_atr_mult * atr15)
            entry_int = EntryIntent(symbol, ts, close, stop, "long_vol_breakout")
            rt.state = SymbolState.IDLE

    return entry_int, exit_int, rt, meta
