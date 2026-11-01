"""Deterministic data fingerprint for run manifests."""
from __future__ import annotations

import hashlib
from datetime import date

import pandas as pd


def frame_fingerprint(df: pd.DataFrame) -> str:
    """Hash OHLCV content + index range (UTC)."""
    if df.empty:
        return hashlib.sha256(b"empty").hexdigest()[:16]
    cols = ["open", "high", "low", "close", "volume"]
    sub = df[cols].astype("float64")
    idx = pd.DatetimeIndex(df.index).tz_convert("UTC")
    meta = f"{idx[0].value}:{idx[-1].value}:{len(df)}".encode()
    arr = sub.to_numpy().tobytes()
    return hashlib.sha256(meta + arr).hexdigest()[:16]


def panel_fingerprint(frames: dict[str, pd.DataFrame]) -> str:
    parts = []
    for sym in sorted(frames):
        parts.append(f"{sym}:{frame_fingerprint(frames[sym])}")
    blob = "|".join(parts).encode()
    return hashlib.sha256(blob).hexdigest()[:16]
