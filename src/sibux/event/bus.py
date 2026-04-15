"""Thread-safe session and global event buses for Sibux.

The core bus intentionally keeps synchronous callbacks so event producers can
publish from sync code paths and worker threads without depending on an event
loop. Async consumers should bridge at the subscription edge, for example by
pushing events into an ``asyncio.Queue``.
"""

from __future__ import annotations

import threading

from .types import BusEvent, Callback


class _SubscriberRegistry:
    """Thread-safe subscriber registry shared by bus implementations."""

    def __init__(self) -> None:
        """Initialize an empty callback registry."""
        self._callbacks_by_type: dict[str, list[Callback]] = {}
        self._all_callbacks: list[Callback] = []
        self._lock = threading.RLock()

    def subscribe(self, event_type: str, callback: Callback) -> None:
        """Register a callback for one event type."""
        normalized_event_type = self._validate_event_type(event_type)
        if not callable(callback):
            raise TypeError("callback must be callable")

        with self._lock:
            callbacks = self._callbacks_by_type.setdefault(normalized_event_type, [])
            callbacks.append(callback)

    def subscribe_all(self, callback: Callback) -> None:
        """Register a callback for all event types."""
        if not callable(callback):
            raise TypeError("callback must be callable")

        with self._lock:
            self._all_callbacks.append(callback)

    def dispatch(self, event: BusEvent) -> None:
        """Dispatch an event to a snapshot of current subscribers."""
        with self._lock:
            type_callbacks = list(self._callbacks_by_type.get(event.type, []))
            all_callbacks = list(self._all_callbacks)

        for callback in type_callbacks:
            callback(event)

        for callback in all_callbacks:
            callback(event)

    def _validate_event_type(self, event_type: str) -> str:
        """Validate a subscriber event type."""
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event_type must be a non-empty, non-whitespace string")
        return event_type


class GlobalBus:
    """Process-wide singleton bus that aggregates all session events."""

    _instance: GlobalBus | None = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> GlobalBus:
        """Create or return the singleton instance."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize the singleton state once."""
        if getattr(self, "_initialized", False):
            return

        self._registry = _SubscriberRegistry()
        self._initialized = True

    def emit(self, event: BusEvent) -> None:
        """Broadcast an event to global subscribers."""
        self._registry.dispatch(event)

    def on(self, event_type: str, callback: Callback) -> None:
        """Subscribe to a single event type across all sessions."""
        self._registry.subscribe(event_type, callback)

    def on_all(self, callback: Callback) -> None:
        """Subscribe to all events across all sessions."""
        self._registry.subscribe_all(callback)


class Bus:
    """Per-session event bus that forwards all events to the global bus."""

    def __init__(self, session_id: str, *, global_bus: GlobalBus | None = None) -> None:
        """Initialize a per-session bus.

        Args:
            session_id: Stable session identifier served by this bus.
            global_bus: Optional global singleton override, primarily for tests.
        """
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty, non-whitespace string")

        self._session_id = session_id
        self._registry = _SubscriberRegistry()
        self._global_bus = global_bus if global_bus is not None else GlobalBus()

    @property
    def session_id(self) -> str:
        """Return the session identifier served by this bus."""
        return self._session_id

    def publish(self, event: BusEvent) -> None:
        """Broadcast an event to session subscribers and then the global bus.

        Args:
            event: Event to publish.

        Raises:
            ValueError: When the event does not belong to this session bus.
        """
        if event.session_id != self._session_id:
            raise ValueError(
                f"event.session_id=<{event.session_id}> does not match bus session_id=<{self._session_id}>"
            )

        self._registry.dispatch(event)
        self._global_bus.emit(event)

    def subscribe(self, event_type: str, callback: Callback) -> None:
        """Subscribe to one event type for this session."""
        self._registry.subscribe(event_type, callback)

    def subscribe_all(self, callback: Callback) -> None:
        """Subscribe to all events for this session."""
        self._registry.subscribe_all(callback)
