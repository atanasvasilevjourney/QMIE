"""Pluggable OHLCV data sources. I/O only — no feature math."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class OhlcvFrame:
    """OHLCV indexed by bar **open** time (UTC)."""

    symbol: str
    timeframe: str
    df: pd.DataFrame
    source: str


class DataSource(ABC):
    @abstractmethod
    def load(
        self,
        symbol: str,
        timeframe: str,
        start: date,
        end: date,
    ) -> OhlcvFrame:
        ...
