"""
QMIE — Symbol Universe
======================
Resolves the list of symbols to scan on each pass.

Strategy:
  * Always include the static `SCAN_SYMBOLS` env list.
  * Optionally union with top-N by 24h volume (≥ min quote volume).
  * Refreshes the auto list at most every `refresh_sec`.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from .exchange_clients import ExchangeClient

logger = logging.getLogger(__name__)


class SymbolUniverse:
    def __init__(
        self,
        client: ExchangeClient,
        *,
        static_symbols: list[str],
        auto_top_n: int = 0,
        min_quote_volume: float = 0.0,
        refresh_sec: int = 3600,
    ):
        self.client = client
        self.static = [s.upper().replace(".P", "") for s in static_symbols]
        self.auto_top_n = auto_top_n
        self.min_quote_volume = min_quote_volume
        self.refresh_sec = refresh_sec

        self._cached: list[str] = []
        self._last_refresh: float = 0.0

    async def get(self) -> list[str]:
        """Return the unique, ordered symbol set for this scan pass."""
        # Static-only path
        if self.auto_top_n <= 0:
            return list(dict.fromkeys(self.static))    # preserve order, dedup

        if (time.time() - self._last_refresh) > self.refresh_sec or not self._cached:
            try:
                top = await self.client.fetch_top_volume_symbols(
                    top_n=self.auto_top_n,
                    min_quote_volume=self.min_quote_volume,
                )
                self._cached = top
                self._last_refresh = time.time()
                logger.info("Universe refreshed: %d auto + %d static",
                            len(top), len(self.static))
            except Exception as e:
                logger.warning("Universe auto-refresh failed: %s "
                               "(falling back to last cache)", e)

        # Static first (priority), then auto, dedup preserving order
        merged = list(dict.fromkeys([*self.static, *self._cached]))
        return merged
