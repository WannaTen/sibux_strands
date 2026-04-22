"""Helpers for translating Strands stream events into Sibux bus events."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, cast

from strands.agent.agent_result import AgentResult
from strands.types.content import Message

from .types import (
    INVOCATION_AFTER,
    INVOCATION_BEFORE,
    INVOCATION_RESULT,
    MESSAGE_ADDED,
    MESSAGE_EVENT,
    MESSAGE_REASONING_DELTA,
    MESSAGE_TEXT_DELTA,
    MESSAGE_TOOL_USE_DELTA,
    MODEL_CALL_AFTER,
    MODEL_CALL_BEFORE,
    TOOL_CANCELLED,
    TOOL_EXECUTE_AFTER,
    TOOL_EXECUTE_BEFORE,
    TOOL_STREAM,
    BusEvent,
)


@dataclass(slots=True)
class StreamEventMapper:
    """Stateful mapper from ``Agent.stream_async()`` events to ``BusEvent`` values."""

    session_id: str
    model_id: str | None = None
    _pending_invocation_start: bool = field(default=False, init=False)
    _pending_invocation_after: bool = field(default=False, init=False)
    _pending_model_call_after: bool = field(default=False, init=False)
    _tool_names_by_id: dict[str, str | None] = field(default_factory=dict, init=False)

    def map_event(self, event: Mapping[str, Any], *, timestamp: str | None = None) -> list[BusEvent]:
        """Map one stream event into zero or more bus events."""
        mapped_events: list[BusEvent] = []

        if event.get("start") is True:
            if not self._pending_invocation_start:
                mapped_events.append(_bus_event(INVOCATION_BEFORE, self.session_id, {}, timestamp=timestamp))
                self._pending_invocation_start = True
            return mapped_events

        if event.get("start_event_loop") is True:
            mapped_events.append(
                _bus_event(
                    MODEL_CALL_BEFORE,
                    self.session_id,
                    {"model_id": self.model_id},
                    timestamp=timestamp,
                )
            )
            self._pending_invocation_start = False
            self._pending_invocation_after = True
            self._pending_model_call_after = True
            return mapped_events

        delta = _mapping(event.get("delta"))
        if isinstance(event.get("data"), str) and isinstance(delta.get("text"), str):
            mapped_events.append(
                _bus_event(
                    MESSAGE_TEXT_DELTA,
                    self.session_id,
                    {"text": event["data"]},
                    timestamp=timestamp,
                )
            )
            return mapped_events

        if event.get("type") == "tool_use_stream":
            current_tool_use = _mapping(event.get("current_tool_use"))
            tool_use_delta = _mapping(delta.get("toolUse"))
            mapped_events.append(
                _bus_event(
                    MESSAGE_TOOL_USE_DELTA,
                    self.session_id,
                    {
                        "tool_name": current_tool_use.get("name"),
                        "tool_use_id": current_tool_use.get("toolUseId"),
                        "input_delta": tool_use_delta.get("input"),
                    },
                    timestamp=timestamp,
                )
            )
            return mapped_events

        if event.get("reasoning") is True and isinstance(event.get("reasoningText"), str):
            mapped_events.append(
                _bus_event(
                    MESSAGE_REASONING_DELTA,
                    self.session_id,
                    {"text": event["reasoningText"]},
                    timestamp=timestamp,
                )
            )
            return mapped_events

        if "event" in event:
            raw_event = _mapping(event.get("event"))
            mapped_events.append(
                _bus_event(
                    MESSAGE_EVENT,
                    self.session_id,
                    {"event": raw_event},
                    timestamp=timestamp,
                )
            )
            mapped_events.extend(self._map_raw_event(raw_event, timestamp=timestamp))
            return mapped_events

        if "message" in event and isinstance(event["message"], Mapping):
            message = cast(Message, event["message"])
            mapped_events.extend(self._map_message_event(message, timestamp=timestamp))
            mapped_events.append(
                _bus_event(
                    MESSAGE_ADDED,
                    self.session_id,
                    {
                        "role": message.get("role"),
                        "content_summary": flatten_message_content(message),
                    },
                    timestamp=timestamp,
                )
            )
            return mapped_events

        if event.get("type") == "tool_stream":
            tool_stream_event = _mapping(event.get("tool_stream_event"))
            tool_use = _mapping(tool_stream_event.get("tool_use"))
            mapped_events.append(
                _bus_event(
                    TOOL_STREAM,
                    self.session_id,
                    {
                        "tool_name": tool_use.get("name"),
                        "tool_use_id": tool_use.get("toolUseId"),
                        "data": tool_stream_event.get("data"),
                    },
                    timestamp=timestamp,
                )
            )
            return mapped_events

        if "tool_cancel_event" in event:
            tool_cancel_event = _mapping(event.get("tool_cancel_event"))
            tool_use = _mapping(tool_cancel_event.get("tool_use"))
            mapped_events.append(
                _bus_event(
                    TOOL_CANCELLED,
                    self.session_id,
                    {
                        "tool_name": tool_use.get("name"),
                        "tool_use_id": tool_use.get("toolUseId"),
                        "message": tool_cancel_event.get("message"),
                    },
                    timestamp=timestamp,
                )
            )
            return mapped_events

        result = event.get("result")
        if isinstance(result, AgentResult):
            if self._pending_invocation_after:
                mapped_events.append(
                    _bus_event(
                        INVOCATION_AFTER,
                        self.session_id,
                        {"stop_reason": result.stop_reason},
                        timestamp=timestamp,
                    )
                )
                self._pending_invocation_after = False

            if self._pending_model_call_after:
                mapped_events.append(
                    _bus_event(
                        MODEL_CALL_AFTER,
                        self.session_id,
                        {
                            "model_id": self.model_id,
                            "usage": {},
                        },
                        timestamp=timestamp,
                    )
                )
                self._pending_model_call_after = False

            mapped_events.append(
                _bus_event(
                    INVOCATION_RESULT,
                    self.session_id,
                    {
                        "stop_reason": result.stop_reason,
                        "message": result.message,
                        "content_summary": flatten_message_content(result.message),
                    },
                    timestamp=timestamp,
                )
            )

        return mapped_events

    def _map_raw_event(self, raw_event: Mapping[str, Any], *, timestamp: str | None = None) -> list[BusEvent]:
        mapped_events: list[BusEvent] = []

        if "contentBlockStart" in raw_event:
            content_block_start = _mapping(raw_event.get("contentBlockStart"))
            start = _mapping(content_block_start.get("start"))
            tool_use = _mapping(start.get("toolUse"))
            tool_use_id = tool_use.get("toolUseId")
            if isinstance(tool_use_id, str) and tool_use_id:
                tool_name = tool_use.get("name")
                normalized_tool_name = tool_name if isinstance(tool_name, str) else None
                self._tool_names_by_id[tool_use_id] = normalized_tool_name
                mapped_events.append(
                    _bus_event(
                        TOOL_EXECUTE_BEFORE,
                        self.session_id,
                        {
                            "tool_name": tool_name,
                            "tool_use_id": tool_use_id,
                        },
                        timestamp=timestamp,
                    )
                )

        if "messageStop" in raw_event:
            message_stop = _mapping(raw_event.get("messageStop"))
            stop_reason = message_stop.get("stopReason")
            if isinstance(stop_reason, str):
                if stop_reason != "tool_use":
                    mapped_events.append(
                        _bus_event(
                            INVOCATION_AFTER,
                            self.session_id,
                            {"stop_reason": stop_reason},
                            timestamp=timestamp,
                        )
                    )
                    self._pending_invocation_after = False

        if "metadata" in raw_event:
            metadata = _mapping(raw_event.get("metadata"))
            usage = _mapping(metadata.get("usage"))
            mapped_events.append(
                _bus_event(
                    MODEL_CALL_AFTER,
                    self.session_id,
                    {
                        "model_id": self.model_id,
                        "usage": dict(usage),
                    },
                    timestamp=timestamp,
                )
            )
            self._pending_model_call_after = False

        return mapped_events

    def _map_message_event(self, message: Message, *, timestamp: str | None = None) -> list[BusEvent]:
        mapped_events: list[BusEvent] = []

        for block in message.get("content", []):
            tool_result = _mapping(block.get("toolResult"))
            tool_use_id = tool_result.get("toolUseId")
            if not isinstance(tool_use_id, str) or not tool_use_id:
                continue

            mapped_events.append(
                _bus_event(
                    TOOL_EXECUTE_AFTER,
                    self.session_id,
                    {
                        "tool_name": self._tool_names_by_id.get(tool_use_id),
                        "tool_use_id": tool_use_id,
                        "has_error": tool_result.get("status") == "error",
                    },
                    timestamp=timestamp,
                )
            )

        return mapped_events


def flatten_message_content(message: Message) -> str:
    """Flatten a Strands ``Message`` into a readable single string."""
    return flatten_content_blocks(message.get("content", []))


def flatten_content_blocks(content: Sequence[Mapping[str, Any]]) -> str:
    """Flatten content blocks into a readable summary string."""
    parts: list[str] = []

    for block in content:
        text = block.get("text")
        if isinstance(text, str) and text:
            parts.append(text)

        reasoning_content = _mapping(block.get("reasoningContent"))
        reasoning_text = _mapping(reasoning_content.get("reasoningText")).get("text")
        if isinstance(reasoning_text, str) and reasoning_text:
            parts.append(reasoning_text)

        citations_content = _mapping(block.get("citationsContent"))
        citation_entries = citations_content.get("content")
        if isinstance(citation_entries, list):
            for entry in citation_entries:
                citation_text = _mapping(entry).get("text")
                if isinstance(citation_text, str) and citation_text:
                    parts.append(citation_text)

        tool_use = _mapping(block.get("toolUse"))
        if tool_use:
            tool_name = tool_use.get("name")
            tool_input = _serialize_tool_input(tool_use.get("input"))
            if isinstance(tool_name, str) and tool_name:
                parts.append(f"[tool_use:{tool_name}] {tool_input}".strip())

        tool_result = _mapping(block.get("toolResult"))
        if tool_result:
            nested_content = tool_result.get("content")
            nested_text = (
                flatten_content_blocks(cast(Sequence[Mapping[str, Any]], nested_content))
                if isinstance(nested_content, list)
                else ""
            )
            status = tool_result.get("status")
            if isinstance(status, str) and status and nested_text:
                parts.append(f"[tool_result:{status}] {nested_text}")
            elif isinstance(status, str) and status:
                parts.append(f"[tool_result:{status}]")
            elif nested_text:
                parts.append(nested_text)

    return "\n".join(part for part in parts if part)


def utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _bus_event(
    event_type: str,
    session_id: str,
    payload: Mapping[str, Any],
    *,
    timestamp: str | None,
) -> BusEvent:
    return BusEvent(
        type=event_type,
        session_id=session_id,
        timestamp=timestamp or utc_now_iso(),
        payload=payload,
    )


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    return {}


def _serialize_tool_input(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value

    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True, default=str)
    except TypeError:
        return str(value)
