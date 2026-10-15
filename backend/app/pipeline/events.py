"""In-process pub/sub so the SSE endpoint can push new articles to open browsers."""

import asyncio
import json


class Broadcaster:
    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: str, payload: dict) -> None:
        """Thread-safe: ingestion runs in a worker thread."""
        if self._loop is None:
            return
        message = f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"
        self._loop.call_soon_threadsafe(self._fanout, message)

    def _fanout(self, message: str) -> None:
        for q in list(self._subscribers):
            if q.full():  # slow client; drop oldest rather than block ingestion
                q.get_nowait()
            q.put_nowait(message)


broadcaster = Broadcaster()
