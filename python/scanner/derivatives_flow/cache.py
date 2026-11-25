"""TTL cache for derivatives flow snapshots."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .collector import build_derivatives_flow_snapshot

logger = logging.getLogger(__name__)


@dataclass
class DerivativesFlowCache:
    ttl_sec: int = 300
    liq_sample_sec: int = 20
    coinalyze_key: str = ""
    default_assets: tuple[str, ...] = ("BTC", "ETH", "SOL")

    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _entries: dict[str, tuple[float, dict[str, Any]]] = field(default_factory=dict)
    _refresh_task: asyncio.Task | None = None

    async def get(self, asset: str, *, force: bool = False) -> dict[str, Any]:
        asset = asset.upper()
        now = time.time()
        async with self._lock:
            hit = self._entries.get(asset)
            if hit and not force and now - hit[0] < self.ttl_sec:
                payload = dict(hit[1])
                payload["cached"] = True
                payload["cache_age_sec"] = round(now - hit[0], 1)
                return payload
        try:
            snap = await build_derivatives_flow_snapshot(
                asset,
                liq_sample_sec=self.liq_sample_sec,
                coinalyze_key=self.coinalyze_key,
            )
        except Exception as e:
            logger.warning("derivatives flow fetch failed for %s: %s", asset, e)
            async with self._lock:
                if hit := self._entries.get(asset):
                    stale = dict(hit[1])
                    stale["stale"] = True
                    stale["fetch_error"] = str(e)[:200]
                    return stale
            raise
        snap["cached"] = False
        snap["cache_age_sec"] = 0
        async with self._lock:
            self._entries[asset] = (time.time(), snap)
        return snap

    async def refresh_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(max(30, self.ttl_sec))
                for a in self.default_assets:
                    try:
                        await self.get(a, force=True)
                    except Exception as e:
                        logger.warning("background flow refresh %s: %s", a, e)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("flow refresh loop: %s", e)

    def start_background(self) -> None:
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self.refresh_loop())