"""Event type definitions for the Sibux event bus."""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterable, Mapping, Sequence
from copy import deepcopy
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


class FrozenList(tuple[Any, ...]):
    """Immutable list-like wrapper used inside frozen bus payloads."""

    def __new__(cls, items: Iterable[Any]) -> FrozenList:
        """Create an immutable tuple-backed sequence."""
        return super().__new__(cls, tuple(items))

    def __eq__(self, other: object) -> bool:
        """Preserve list-style equality semantics for payload comparisons."""
        if isinstance(other, Sequence) and not isinstance(other, (str, bytes, bytearray)):
            return tuple(self) == tuple(other)
        return super().__eq__(other)


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

        # Recursively freeze payload data so subscribers cannot mutate shared event state.
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""
        return {
            "type": self.type,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "payload": _json_safe_value(_thaw_value(self.payload)),
        }


Callback = Callable[[BusEvent], None]


def _freeze_mapping(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    """Recursively freeze a payload mapping."""
    return MappingProxyType({key: _freeze_value(value) for key, value in mapping.items()})


def _freeze_value(value: Any) -> Any:
    """Recursively freeze nested payload values."""
    try:
        if isinstance(value, Mapping):
            return _freeze_mapping(value)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return FrozenList(_freeze_value(item) for item in value)
    except Exception:  # noqa: BLE001
        return _copy_if_possible(value)
    return _copy_if_possible(value)


def _thaw_value(value: Any) -> Any:
    """Convert frozen payload values back into plain Python containers."""
    try:
        if isinstance(value, Mapping):
            return {key: _thaw_value(item) for key, item in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [_thaw_value(item) for item in value]
    except Exception:  # noqa: BLE001
        return _copy_if_possible(value)
    return _copy_if_possible(value)


def _json_safe_value(value: Any) -> Any:
    """Convert thawed payload values into JSON-safe structures."""
    try:
        if isinstance(value, Mapping):
            return {key: _json_safe_value(item) for key, item in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [_json_safe_value(item) for item in value]
        if isinstance(value, (bytes, bytearray)):
            return {
                "__bytes_encoded__": True,
                "data": base64.b64encode(bytes(value)).decode("utf-8"),
            }
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
    except Exception:  # noqa: BLE001
        return str(value)
    return str(value)


def _copy_if_possible(value: Any) -> Any:
    """Return a deep copy when possible, otherwise preserve the original value."""
    try:
        return deepcopy(value)
    except Exception:  # noqa: BLE001
        return value
