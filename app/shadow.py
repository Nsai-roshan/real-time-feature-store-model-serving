from __future__ import annotations

import asyncio
from contextlib import suppress

SHADOW_SUMMARY_KEY = "shadow:candidate-v2:summary"


class ShadowRecorder:
    """Aggregate shadow outcomes off the response path and flush them in batches."""

    def __init__(self, client, flush_interval_seconds: float = 0.1) -> None:
        self.client = client
        self.flush_interval_seconds = flush_interval_seconds
        self._pending_count = 0
        self._pending_delta = 0.0

    def record(self, absolute_delta: float) -> None:
        self._pending_count += 1
        self._pending_delta += absolute_delta

    async def flush(self) -> None:
        count = self._pending_count
        if count == 0:
            return
        delta = self._pending_delta
        self._pending_count = 0
        self._pending_delta = 0.0
        try:
            async with self.client.pipeline(transaction=False) as pipe:
                pipe.hincrby(SHADOW_SUMMARY_KEY, "sample_count", count)
                pipe.hincrbyfloat(SHADOW_SUMMARY_KEY, "absolute_delta_sum", delta)
                await pipe.execute()
        except Exception:
            self._pending_count += count
            self._pending_delta += delta
            raise

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.flush_interval_seconds)
            await self.flush()
        await self.flush()
