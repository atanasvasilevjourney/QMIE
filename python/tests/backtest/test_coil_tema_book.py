"""Two-clip coil-UP + TEMA add book — flatten order, no network."""
from __future__ import annotations

import pandas as pd

from backtest.coil_tema_book import (
    CoilUp,
    TemaBuy,
    iter_coil_ups,
    simulate_book,
    summarize,
)
from scanner.radar import RadarConfig
from tests.test_radar import _coil_then_expansion


def _h4_from_daily(df_1d: pd.DataFrame) -> pd.DataFrame:
    """Six flat 4h bars per daily bar (high/low copied)."""
    rows = []
    for ts, row in df_1d.iterrows():
        for h in range(0, 24, 4):
            t = pd.Timestamp(ts) + pd.Timedelta(hours=h)
            rows.append({
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"] / 6.0,
                "t": t,
            })
    out = pd.DataFrame(rows).set_index("t")
    out.index.name = None
    return out


def test_replay_fixture_emits_one_coil_up():
    df, coil_n = _coil_then_expansion()
    ups = iter_coil_ups(df, "SOLUSDT", cfg=RadarConfig(min_bars=60))
    assert len(ups) == 1
    assert ups[0].price == 107.0
    assert ups[0].coil_low == 98.0
    assert ups[0].bar_time == df.index[coil_n]


def test_coil_low_flattens_before_tema():
    df, coil_n = _coil_then_expansion()
    coil = iter_coil_ups(df, "SOLUSDT", cfg=RadarConfig(min_bars=60))[0]
    dump = df.copy()
    i = coil_n + 1
    dump.iloc[i, dump.columns.get_loc("low")] = 90.0
    dump.iloc[i, dump.columns.get_loc("close")] = 92.0
    dump.iloc[i, dump.columns.get_loc("high")] = 100.0
    h4 = _h4_from_daily(dump)
    # TEMA prints later — coil-low on the next closed 1D must kill clip 1 first.
    tema = [TemaBuy(
        symbol="SOLUSDT",
        bar_time=pd.Timestamp(dump.index[coil_n + 3]) + pd.Timedelta(hours=4),
        price=120.0,
        stop_loss=110.0,
        take_profit=140.0,
        grade="A",
        score=84.0,
        atr_pct=1.2,
        adx=28.0,
    )]
    trade = simulate_book(coil, dump, h4, tema)
    assert trade.exit_reason == "coil_low"
    assert trade.added is False
    assert trade.exit_price == 98.0
    assert trade.clip1_pnl < 0
    assert trade.clip2_pnl == 0


def test_tema_tp_takes_whole_book():
    df, coil_n = _coil_then_expansion()
    coil = iter_coil_ups(df, "SOLUSDT", cfg=RadarConfig(min_bars=60))[0]
    h4 = _h4_from_daily(df)
    add_ts = pd.Timestamp(df.index[coil_n]) + pd.Timedelta(days=1, hours=4)
    tema = [TemaBuy(
        symbol="SOLUSDT",
        bar_time=add_ts,
        price=112.0,
        stop_loss=80.0,
        take_profit=117.0,
        grade="A+",
        score=91.0,
        atr_pct=1.1,
        adx=30.0,
    )]
    trade = simulate_book(coil, df, h4, tema)
    assert trade.added is True
    assert trade.exit_reason == "tema_tp"
    assert trade.exit_price == 117.0
    assert trade.clip1_pnl > 0
    assert trade.clip2_pnl > 0
    assert trade.pnl_usdt == round(trade.clip1_pnl + trade.clip2_pnl, 4)


def test_tema_same_bar_sl_and_tp_is_sl():
    df, coil_n = _coil_then_expansion()
    coil = iter_coil_ups(df, "SOLUSDT", cfg=RadarConfig(min_bars=60))[0]
    h4 = _h4_from_daily(df)
    add_ts = pd.Timestamp(df.index[coil_n]) + pd.Timedelta(days=1)
    # Next 4h bar after add is +4h same day; make that bar span both SL and TP.
    nxt = add_ts + pd.Timedelta(hours=4)
    h4.loc[nxt, "low"] = 100.0
    h4.loc[nxt, "high"] = 140.0
    tema = [TemaBuy(
        symbol="SOLUSDT",
        bar_time=add_ts,
        price=112.0,
        stop_loss=105.0,
        take_profit=130.0,
        grade="A",
        score=82.0,
        atr_pct=1.0,
        adx=26.0,
    )]
    trade = simulate_book(coil, df, h4, tema)
    assert trade.exit_reason == "tema_sl"
    assert trade.exit_price == 105.0


def test_green_to_grey_only_without_add():
    df, coil_n = _coil_then_expansion()
    coil = iter_coil_ups(df, "SOLUSDT", cfg=RadarConfig(min_bars=60))[0]
    h4 = _h4_from_daily(df)
    colors = pd.Series(["GREY"] * len(df), index=df.index)
    colors.iloc[coil_n + 1] = "GREEN"
    colors.iloc[coil_n + 2] = "GREY"
    trade = simulate_book(coil, df, h4, tema_buys=[], colors=colors)
    assert trade.added is False
    assert trade.exit_reason == "green_to_grey"
    assert trade.clip2_pnl == 0.0


def test_summarize_counts_adds():
    df, _coil_n = _coil_then_expansion()
    coil = iter_coil_ups(df, "SOLUSDT", cfg=RadarConfig(min_bars=60))[0]
    h4 = _h4_from_daily(df)
    a = simulate_book(coil, df, h4, [])
    s = summarize([a])
    assert s["n_books"] == 1
    assert s["n_with_tema_add"] == 0
    assert "Not frozen" in s["note"]
