"""
QMIE — Webhook Security & Deduplication
========================================
Two enemies:
  1. Forged signals (anyone with the URL drains your account).
  2. Duplicate signals (TV retries, network glitches → double fills).

HMAC-SHA256 over the raw body verifies the source.
Idempotency key + TTL'd seen-set prevents replays.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
#                              HMAC verification
# ═══════════════════════════════════════════════════════════════════════════
def compute_signature(secret: str, body: bytes) -> str:
    """Hex-encoded HMAC-SHA256 of the raw request body."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, provided: Optional[str]) -> bool:
    """Constant-time compare. Returns False on missing or mismatched sig."""
    if not provided:
        return False
    expected = compute_signature(secret, body)
    return hmac.compare_digest(expected, provided.strip())


def verify_age(timestamp: Optional[float], max_age_sec: int) -> bool:
    """Reject stale signals — signed-then-stored replays."""
    if timestamp is None:
        return True  # we'll allow if absent; HMAC carries auth
    return abs(time.time() - timestamp) <= max_age_sec


# ═══════════════════════════════════════════════════════════════════════════
#                       Idempotency / dedup store
# ═══════════════════════════════════════════════════════════════════════════
class IdempotencyStore:
    """
    Pluggable: in-memory by default, Redis if a client is provided.
    """

    def __init__(self, ttl_sec: int = 300, redis=None):
        self.ttl = ttl_sec
        self._redis = redis
        self._mem: dict[str, float] = {}

    async def seen_or_mark(self, key: str) -> bool:
        """
        Atomic check-and-set. Returns True if the key was already seen
        (caller should drop the message), False if it's fresh.
        """
        if self._redis is not None:
            # SETNX with EX — atomic in Redis
            ok = await self._redis.set(f"qmie:idem:{key}", "1", ex=self.ttl, nx=True)
            return ok is None or ok is False  # nx=True returns None when key exists

        # In-memory fallback. Prune expired first.
        now = time.time()
        for k, ts in list(self._mem.items()):
            if now - ts > self.ttl:
                self._mem.pop(k, None)
        if key in self._mem:
            return True
        self._mem[key] = now
        return False
