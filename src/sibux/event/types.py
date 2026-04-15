"""Event type definitions for the Sibux event bus."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

SESSION_CREATED = "session.created"
SESSION_RESUMED = "session.resumed"
INVOCATION_BEFORE = "invocation.before"
INVOCATION_AFTER = "invocation.after"
MODEL_CALL_BEFORE = "model.call.before"
MODEL_CALL_AFTER = "model.call.after"
MESSAGE_ADDED = "message.added"
TOOL_EXECUTE_BEFORE = "tool.execute.before"
TOOL_EXECUTE_AFTER = "tool.execute.after"

MESSAGE_TEXT_DELTA = "message.text.delta"
MESSAGE_TOOL_USE_DELTA = "message.tool_use.delta"
MESSAGE_REASONING_DELTA = "message.reasoning.delta"
MESSAGE_EVENT = "message.event"
TOOL_STREAM = "tool.stream"
TOOL_CANCELLED = "tool.cancelled"
INVOCATION_RESULT = "invocation.result"

LIFECYCLE_EVENT_TYPES: tuple[str, ...] = (
    SESSION_CREATED,
    SESSION_RESUMED,
    INVOCATION_BEFORE,
    INVOCATION_AFTER,
    MODEL_CALL_BEFORE,
    MODEL_CALL_AFTER,
    MESSAGE_ADDED,
    TOOL_EXECUTE_BEFORE,
    TOOL_EXECUTE_AFTER,
)

STREAM_EVENT_TYPES: tuple[str, ...] = (
    MESSAGE_TEXT_DELTA,
    MESSAGE_TOOL_USE_DELTA,
    MESSAGE_REASONING_DELTA,
    MESSAGE_EVENT,
    TOOL_STREAM,
    TOOL_CANCELLED,
    INVOCATION_RESULT,
)

ALL_EVENT_TYPES: tuple[str, ...] = LIFECYCLE_EVENT_TYPES + STREAM_EVENT_TYPES


def _validate_non_empty_text(value: str, *, field_name: str) -> str:
    """Validate a non-empty string field."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty, non-whitespace string")
    return value


@dataclass(slots=True, frozen=True)
class BusEvent:
    """Event published to the Sibux event bus.

    Attributes:
        type: Dot-separated event type name.
        session_id: Session identifier that produced the event.
        timestamp: ISO 8601 UTC timestamp for the event.
        payload: Event-specific data payload.
    """

    type: str
    session_id: str
    timestamp: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        """Validate the event shape."""
        object.__setattr__(self, "type", _validate_non_empty_text(self.type, field_name="type"))
        object.__setattr__(self, "session_id", _validate_non_empty_text(self.session_id, field_name="session_id"))
        object.__setattr__(self, "timestamp", _validate_non_empty_text(self.timestamp, field_name="timestamp"))
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be a mapping")

        # Copy into a read-only proxy so published events cannot be mutated after creation.
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


Callback = Callable[[BusEvent], None]
