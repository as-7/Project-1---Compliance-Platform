"""In-memory async rate limiter for LLM calls.

Token-bucket per provider. Cheap, single-process, good enough for the demo.
For multi-replica deployments swap the storage for Redis (the limits library
already supports this).
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class _Bucket:
    capacity: int
    tokens: float
    last_refill: float
    refill_per_sec: float
    lock: asyncio.Lock


class RateLimiter:
    def __init__(self, *, rpm_per_provider: int):
        self._rpm = rpm_per_provider
        self._refill = rpm_per_provider / 60.0
        self._buckets: dict[str, _Bucket] = {}
        self._dict_lock = asyncio.Lock()

    async def _bucket(self, provider: str) -> _Bucket:
        async with self._dict_lock:
            b = self._buckets.get(provider)
            if b is None:
                b = _Bucket(
                    capacity=self._rpm,
                    tokens=float(self._rpm),
                    last_refill=time.monotonic(),
                    refill_per_sec=self._refill,
                    lock=asyncio.Lock(),
                )
                self._buckets[provider] = b
            return b

    async def acquire(self, provider: str, *, weight: int = 1) -> None:
        bucket = await self._bucket(provider)
        async with bucket.lock:
            while True:
                now = time.monotonic()
                elapsed = now - bucket.last_refill
                bucket.tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.refill_per_sec)
                bucket.last_refill = now
                if bucket.tokens >= weight:
                    bucket.tokens -= weight
                    return
                deficit = weight - bucket.tokens
                wait_s = max(deficit / bucket.refill_per_sec, 0.05)
                await asyncio.sleep(wait_s)


_calls_seen: dict[str, int] = defaultdict(int)


def record_call(provider: str) -> None:
    _calls_seen[provider] += 1


def call_counts() -> dict[str, int]:
    return dict(_calls_seen)
