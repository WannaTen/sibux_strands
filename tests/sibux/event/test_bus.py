"""Tests for the Sibux event bus."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import FrozenInstanceError

import pytest

from sibux.event import (
    ALL_EVENT_TYPES,
    INVOCATION_AFTER,
    INVOCATION_BEFORE,
    INVOCATION_RESULT,
    LIFECYCLE_EVENT_TYPES,
    MESSAGE_ADDED,
    MESSAGE_EVENT,
    MESSAGE_REASONING_DELTA,
    MESSAGE_TEXT_DELTA,
    MESSAGE_TOOL_USE_DELTA,
    MODEL_CALL_AFTER,
    MODEL_CALL_BEFORE,
    SESSION_CREATED,
    SESSION_RESUMED,
    STREAM_EVENT_TYPES,
    TOOL_CANCELLED,
    TOOL_EXECUTE_AFTER,
    TOOL_EXECUTE_BEFORE,
    TOOL_STREAM,
    Bus,
    BusEvent,
    GlobalBus,
)


@pytest.fixture(autouse=True)
def reset_global_bus() -> Iterator[None]:
    """Reset the singleton bus between tests."""

    GlobalBus._instance = None
    yield
    GlobalBus._instance = None


def _event(event_type: str, *, session_id: str = "sibux_abc123", payload: dict[str, object] | None = None) -> BusEvent:
    """Build a standard event fixture."""

    return BusEvent(
        type=event_type,
        session_id=session_id,
        timestamp="2026-04-13T12:00:00Z",
        payload=payload if payload is not None else {},
    )


class TestBus:
    def test_publish_notifies_matching_event_type_subscribers(self) -> None:
        bus = Bus(session_id="sibux_abc123")
        matched_events: list[BusEvent] = []
        other_events: list[BusEvent] = []

        bus.subscribe(MESSAGE_TEXT_DELTA, matched_events.append)
        bus.subscribe(TOOL_STREAM, other_events.append)

        event = _event(MESSAGE_TEXT_DELTA, payload={"text": "Hello"})
        bus.publish(event)

        assert matched_events == [event]
        assert other_events == []

    def test_publish_forwards_events_to_global_bus(self) -> None:
        bus = Bus(session_id="sibux_abc123")
        global_events: list[BusEvent] = []

        GlobalBus().on(MESSAGE_TEXT_DELTA, global_events.append)

        event = _event(MESSAGE_TEXT_DELTA, payload={"text": "Hello"})
        bus.publish(event)

        assert global_events == [event]

    def test_subscribe_all_receives_all_events(self) -> None:
        bus = Bus(session_id="sibux_abc123")
        events: list[BusEvent] = []

        bus.subscribe_all(events.append)

        first = _event(MESSAGE_TEXT_DELTA, payload={"text": "Hello"})
        second = _event(TOOL_STREAM, payload={"data": "chunk"})
        bus.publish(first)
        bus.publish(second)

        assert events == [first, second]

    def test_publish_rejects_event_for_another_session(self) -> None:
        bus = Bus(session_id="sibux_abc123")

        with pytest.raises(
            ValueError,
            match=r"event.session_id=<sibux_other> does not match bus session_id=<sibux_abc123>",
        ):
            bus.publish(_event(MESSAGE_TEXT_DELTA, session_id="sibux_other"))


class TestGlobalBus:
    def test_global_bus_is_a_singleton(self) -> None:
        first = GlobalBus()
        second = GlobalBus()
        events: list[BusEvent] = []

        first.on_all(events.append)
        event = _event(SESSION_CREATED)
        second.emit(event)

        assert first is second
        assert events == [event]


class TestBusEvent:
    def test_bus_event_rejects_invalid_scalar_fields(self) -> None:
        with pytest.raises(ValueError, match="type must be a non-empty, non-whitespace string"):
            BusEvent(type="", session_id="sibux_abc123", timestamp="2026-04-13T12:00:00Z", payload={})

        with pytest.raises(ValueError, match="session_id must be a non-empty, non-whitespace string"):
            BusEvent(type=MESSAGE_TEXT_DELTA, session_id="   ", timestamp="2026-04-13T12:00:00Z", payload={})

        with pytest.raises(ValueError, match="timestamp must be a non-empty, non-whitespace string"):
            BusEvent(type=MESSAGE_TEXT_DELTA, session_id="sibux_abc123", timestamp="", payload={})

    def test_bus_event_rejects_non_mapping_payload(self) -> None:
        with pytest.raises(ValueError, match="payload must be a mapping"):
            BusEvent(
                type=MESSAGE_TEXT_DELTA,
                session_id="sibux_abc123",
                timestamp="2026-04-13T12:00:00Z",
                payload=["not", "a", "mapping"],
            )

    def test_bus_event_is_immutable(self) -> None:
        source_payload = {"text": "Hello"}
        event = _event(MESSAGE_TEXT_DELTA, payload=source_payload)

        with pytest.raises(FrozenInstanceError):
            event.type = TOOL_STREAM

        with pytest.raises(TypeError):
            event.payload["text"] = "Updated"

        source_payload["text"] = "Changed after creation"
        assert event.payload == {"text": "Hello"}


def test_event_type_constants_cover_phase_3_contract() -> None:
    lifecycle_types = {
        SESSION_CREATED,
        SESSION_RESUMED,
        INVOCATION_BEFORE,
        INVOCATION_AFTER,
        MODEL_CALL_BEFORE,
        MODEL_CALL_AFTER,
        MESSAGE_ADDED,
        TOOL_EXECUTE_BEFORE,
        TOOL_EXECUTE_AFTER,
    }
    stream_types = {
        MESSAGE_TEXT_DELTA,
        MESSAGE_TOOL_USE_DELTA,
        MESSAGE_REASONING_DELTA,
        MESSAGE_EVENT,
        TOOL_STREAM,
        TOOL_CANCELLED,
        INVOCATION_RESULT,
    }

    assert set(LIFECYCLE_EVENT_TYPES) == lifecycle_types
    assert set(STREAM_EVENT_TYPES) == stream_types
    assert set(ALL_EVENT_TYPES) == lifecycle_types | stream_types
