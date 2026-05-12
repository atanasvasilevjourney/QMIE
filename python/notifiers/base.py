"""
QMIE Notifier base
==================
Async fan-out destinations for human-readable signals.
Notifiers are FIRE-AND-FORGET. The router awaits them with
asyncio.gather(..., return_exceptions=True) so a Discord 503
NEVER blocks an actual broker order. Notifier failures are logged
but never raised to the caller.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from models import TVSignal, BrokerResponse

logger = logging.getLogger(__name__)


class NotifierError(Exception):
    pass


class Notifier(ABC):
    name: str = "abstract"
    enabled: bool = True

    @abstractmethod
    async def send_signal(self, sig: TVSignal,
                          broker_resp: BrokerResponse | None = None) -> None: ...

    async def send_text(self, message: str) -> None:
        """Optional admin/heartbeat channel. Default: log only."""
        logger.info("[%s] %s", self.name, message)

    async def close(self) -> None:
        return None
