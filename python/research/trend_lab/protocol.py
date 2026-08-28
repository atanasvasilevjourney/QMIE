"""Walk-forward protocol. Chronological IS → OOS. No lookahead.

The operator asked for "2018–2023 OOS, 2023→now IS". Training on the
later window and testing on the earlier one is not a valid out-of-sample
test (it uses future market structure to score the past). This lab
therefore:

* **IS (fit):** 2019-09-01 → 2022-12-31  (first USDT-M history is ~2019)
* **OOS (never tune):** 2023-01-01 → today
* A reverse-split table may be printed as a *leakage diagnostic only*.

Warmup bars seed indicators; P&L starts after warmup. OOS indicators
are seeded with the last ``WARMUP_BARS`` of IS (strictly past data).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

WARMUP_BARS = 220  # TEMA-TEMPLATE_adjusted6: longest EMA 199 + margin
ANN_DAYS = 365     # crypto 24/7


@dataclass(frozen=True)
class Split:
    is_start: date
    is_end: date
    oos_start: date
    oos_end: date
    requested_note: str


SPLIT = Split(
    is_start=date(2019, 9, 1),
    is_end=date(2022, 12, 31),
    oos_start=date(2023, 1, 1),
    oos_end=date.today(),
    requested_note=(
        "Requested '2018-2023 OOS / 2023-now IS' trains on the future. "
        "This lab uses chronological IS 2019-09→2022 / OOS 2023→now. "
        "USDT-M Vision klines start ~2019-09, not 2018."
    ),
)


class ProtocolError(ValueError):
    pass


def split_frame(df: pd.DataFrame, *, warmup: int = WARMUP_BARS) -> dict[str, pd.DataFrame]:
    """Return IS / IS-eval / OOS-seeded frames. Index must be UTC datetime."""
    if df.empty:
        raise ProtocolError("empty frame")
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        raise ProtocolError("index must be timezone-aware UTC")
    is_end = pd.Timestamp(SPLIT.is_end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
    oos_start = pd.Timestamp(SPLIT.oos_start, tz="UTC")
    is_df = df.loc[:is_end]
    oos_df = df.loc[oos_start:]
    if len(is_df) <= warmup:
        raise ProtocolError(f"IS too short for warmup={warmup}: {len(is_df)} bars")
    is_eval = is_df.iloc[warmup:]
    # OOS indicators: prefix with last warmup of IS (past only)
    seed = is_df.iloc[-warmup:]
    oos_seeded = pd.concat([seed, oos_df])
    oos_seeded = oos_seeded[~oos_seeded.index.duplicated(keep="last")].sort_index()
    return {
        "full": df,
        "is": is_df,
        "is_eval": is_eval,
        "oos": oos_df,
        "oos_seeded": oos_seeded,
    }


def inner_validation_start(index: pd.DatetimeIndex, frac: float = 0.20) -> pd.Timestamp:
    """Last ``frac`` of IS is inner validation. Never the true OOS holdout."""
    if frac <= 0 or frac >= 1:
        raise ProtocolError("inner validation frac must be in (0, 1)")
    if len(index) < 20:
        raise ProtocolError(f"IS too short for inner validation: {len(index)}")
    cut = int(len(index) * (1.0 - frac))
    return pd.Timestamp(index[cut])


def assert_no_lookahead(signal: pd.Series, held: pd.Series) -> None:
    """held[t] must equal signal[t-1] (exec_lag=1)."""
    expected = signal.shift(1)
    aligned = pd.concat([held, expected], axis=1).dropna()
    if aligned.empty:
        raise ProtocolError("no overlapping held/signal to check")
    if not (aligned.iloc[:, 0] == aligned.iloc[:, 1]).all():
        raise ProtocolError("lookahead: held is not signal.shift(1)")
