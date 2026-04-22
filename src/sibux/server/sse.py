"""SSE helpers that bridge the synchronous GlobalBus into async response streams."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass

from fastapi import FastAPI

from ..event import BusEvent, Callback, GlobalBus

logger = logging.getLogger(__name__)

# TODO: Replace disconnect-on-backpressure with coordinated flow control once
# the global SSE endpoint grows a real slow-consumer strategy.
SSE_SUBSCRIBER_QUEUE_MAXSIZE = 4096


@dataclass(slots=True)
class _Subscriber:
    """Per-connection SSE subscriber state."""

    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[str]


class SSEBroker:
    """Bridge GlobalBus events into per-client async queues."""

    def __init__(self, global_bus: GlobalBus) -> None:
        """Initialize the broker.

        Args:
            global_bus: Process-wide event bus that publishes all session
                events.
        """
        self._global_bus = global_bus
        self._subscribers: dict[int, _Subscriber] = {}
        self._lock = threading.RLock()
        self._global_callback: Callback = self._handle_event
        self._attached = False

    @property
    def subscriber_count(self) -> int:
        """Return the number of active SSE subscribers."""
        with self._lock:
            return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue[str]:
        """Create and register a queue for one SSE client."""
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=SSE_SUBSCRIBER_QUEUE_MAXSIZE)
        subscriber = _Subscriber(loop=asyncio.get_running_loop(), queue=queue)

        with self._lock:
            if not self._attached:
                self._global_bus.on_all(self._global_callback)
                self._attached = True
            self._subscribers[id(queue)] = subscriber

        return queue

    def is_subscribed(self, queue: asyncio.Queue[str]) -> bool:
        """Return whether one queue is still attached to the broker."""
        with self._lock:
            return id(queue) in self._subscribers

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        """Remove an SSE subscriber queue."""
        self._remove_subscribers([id(queue)])

    def _handle_event(self, event: BusEvent) -> None:
        """Push one bus event to every connected SSE client."""
        message = encode_sse_event(event)

        with self._lock:
            subscribers = list(self._subscribers.items())

        stale_subscriber_ids: list[int] = []
        for subscriber_id, subscriber in subscribers:
            try:
                subscriber.loop.call_soon_threadsafe(self._enqueue_message, subscriber_id, message)
            except RuntimeError:
                stale_subscriber_ids.append(subscriber_id)

        if stale_subscriber_ids:
            self._remove_subscribers(stale_subscriber_ids)

    def _enqueue_message(self, subscriber_id: int, message: str) -> None:
        """Queue one message for a subscriber or drop the connection if it is too slow."""
        with self._lock:
            subscriber = self._subscribers.get(subscriber_id)
            if subscriber is None:
                return

            try:
                subscriber.queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning(
                    "subscriber_id=<%s>, queue_maxsize=<%s> | disconnecting slow SSE subscriber",
                    subscriber_id,
                    subscriber.queue.maxsize,
                )
                self._subscribers.pop(subscriber_id, None)
                if not self._subscribers:
                    self._detach_locked()

    def _remove_subscribers(self, subscriber_ids: list[int]) -> None:
        """Remove one or more subscribers from the broker."""
        with self._lock:
            for subscriber_id in subscriber_ids:
                self._subscribers.pop(subscriber_id, None)

            if not self._subscribers:
                self._detach_locked()

    def _detach_locked(self) -> None:
        """Detach the broker callback from the global bus when unused."""
        if not self._attached:
            return

        self._global_bus.off_all(self._global_callback)
        self._attached = False


def encode_sse_event(event: BusEvent) -> str:
    """Serialize one bus event into an SSE frame."""
    data = json.dumps(event.as_dict(), separators=(",", ":"))
    return f"event: {event.type}\ndata: {data}\n\n"


def get_or_create_sse_broker(app: FastAPI) -> SSEBroker:
    """Return the app-scoped SSE broker, creating it on first use."""
    broker = getattr(app.state, "sibux_sse_broker", None)
    if isinstance(broker, SSEBroker):
        return broker

    global_bus = getattr(app.state, "sibux_global_bus", None)
    if not isinstance(global_bus, GlobalBus):
        raise RuntimeError("sibux_global_bus is missing from application state")

    broker = SSEBroker(global_bus)
    app.state.sibux_sse_broker = broker
    return broker
