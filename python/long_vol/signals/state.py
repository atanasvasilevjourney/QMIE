"""Per-symbol state machine for no-chase and pullback re-entry."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class SymbolState(Enum):
    IDLE = auto()
    SETUP = auto()
    TRIGGERED = auto()
    EXTENDED = auto()
    PULLBACK_WATCH = auto()


@dataclass
class Transition:
    prev: SymbolState
    new: SymbolState
    reason: str


def apply_no_chase(
    state: SymbolState,
    *,
    extended: bool,
    trigger: bool,
    compression: bool,
) -> Transition:
    """Table-driven core transitions (extended / trigger paths)."""
    if state == SymbolState.IDLE:
        if compression:
            return Transition(state, SymbolState.SETUP, "compression")
        return Transition(state, state, "idle")
    if state == SymbolState.SETUP:
        if trigger and extended:
            return Transition(state, SymbolState.EXTENDED, "no_chase")
        if trigger:
            return Transition(state, SymbolState.TRIGGERED, "breakout")
        if not compression:
            return Transition(state, SymbolState.IDLE, "compression_lost")
        return Transition(state, state, "setup")
    if state == SymbolState.TRIGGERED:
        return Transition(state, SymbolState.IDLE, "filled_reset")
    if state == SymbolState.EXTENDED:
        return Transition(state, SymbolState.PULLBACK_WATCH, "watch_pullback")
    if state == SymbolState.PULLBACK_WATCH:
        return Transition(state, state, "pullback_pending")
    return Transition(state, state, "noop")


def pullback_reentry_ready(
    *,
    low15: float,
    close15: float,
    vwap24: float,
    don_mid_1h: float,
    close_1h: float,
    prior_1h_high: float,
) -> bool:
    """Pullback path after EXTENDED (§1.3 no-chase rule)."""
    floor = max(vwap24, don_mid_1h)
    touched = low15 <= floor
    reclaimed = close15 > vwap24
    new_high = close_1h > prior_1h_high
    return touched and reclaimed and new_high
