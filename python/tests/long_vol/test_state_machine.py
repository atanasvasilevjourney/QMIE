from __future__ import annotations

import pandas as pd
import pytest

from long_vol.config import EntryConfig, ExitConfig
from long_vol.signals.long_vol_breakout import SymbolRuntime, evaluate_bar
from long_vol.signals.state import SymbolState, Transition, apply_no_chase, pullback_reentry_ready


@pytest.mark.parametrize(
    "prev,extended,trigger,compression,exp,reason",
    [
        (SymbolState.IDLE, False, False, True, SymbolState.SETUP, "compression"),
        (SymbolState.SETUP, True, True, True, SymbolState.EXTENDED, "no_chase"),
        (SymbolState.SETUP, False, True, True, SymbolState.TRIGGERED, "breakout"),
        (SymbolState.SETUP, False, False, False, SymbolState.IDLE, "compression_lost"),
    ],
)
def test_apply_no_chase_table(prev, extended, trigger, compression, exp, reason):
    tr = apply_no_chase(prev, extended=extended, trigger=trigger, compression=compression)
    assert tr.new == exp
    assert tr.reason == reason


def test_pullback_reentry_conditions():
    assert pullback_reentry_ready(
        low15=99.0,
        close15=101.0,
        vwap24=100.0,
        don_mid_1h=98.0,
        close_1h=102.0,
        prior_1h_high=101.5,
    )


def test_cooldown_blocks_entry():
    ts = pd.Timestamp("2024-01-01 12:00:00", tz="UTC")
    rt = SymbolRuntime(cooldown_until=ts + pd.Timedelta(hours=1))
    row = pd.Series({"compression_ok": True, "close_1h": 200, "don_up_1h": 100})
    ent, ex, rt2, meta = evaluate_bar(
        "ETHUSDT",
        ts,
        row,
        runtime=rt,
        btc_ok=True,
        ent=EntryConfig(),
        ex=ExitConfig(),
    )
    assert ent is None
    assert meta.get("cooldown") is True
