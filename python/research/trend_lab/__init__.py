"""Crypto trend lab — spot book vs 4h TEMA leverage vs Carver sizing.

Research only. Does not dispatch alerts, does not retune live ``W_*``,
does not send leverage to a venue.
"""
from .protocol import (
    SPLIT,
    WARMUP_BARS,
    ProtocolError,
    assert_no_lookahead,
    inner_validation_start,
    split_frame,
)

__all__ = [
    "SPLIT",
    "WARMUP_BARS",
    "ProtocolError",
    "assert_no_lookahead",
    "inner_validation_start",
    "split_frame",
]
