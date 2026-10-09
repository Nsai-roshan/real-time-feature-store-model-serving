from __future__ import annotations

import time

from starlette.datastructures import MutableHeaders


class ServerTimingMiddleware:
    """Measure server processing through response serialization."""

    def __init__(self, app, histogram) -> None:
        self.app = app
        self.histogram = histogram

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()

        async def send_with_timing(message) -> None:
            if message["type"] == "http.response.start":
                elapsed = time.perf_counter() - started
                self.histogram.observe(elapsed)
                headers = MutableHeaders(scope=message)
                headers.append("server-timing", f"app;dur={elapsed * 1000:.3f}")
            await send(message)

        await self.app(scope, receive, send_with_timing)
