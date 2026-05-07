"""Terminal renderer for Sibux stream events."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any, TextIO

from sibux.event import (
    MESSAGE_REASONING_DELTA,
    MESSAGE_TEXT_DELTA,
    MESSAGE_TOOL_USE_DELTA,
    TOOL_CANCELLED,
    TOOL_EXECUTE_AFTER,
    TOOL_EXECUTE_BEFORE,
    TOOL_STREAM,
    BusEvent,
)


class TerminalRenderer:
    """Render Sibux bus events as categorized terminal output."""

    def __init__(self, stream: TextIO | None = None, *, color: bool | None = None) -> None:
        """Initialize the renderer.

        Args:
            stream: Output stream. Defaults to standard output.
            color: Whether to emit ANSI styling. Defaults to TTY detection.
        """
        self._stream = stream if stream is not None else sys.stdout
        self._color = self._stream.isatty() if color is None else color
        self._current_section: str | None = None
        self._at_line_start = True
        self._seen_tool_calls: set[str] = set()
        self._tool_inputs_started: set[str] = set()

    def handle(self, event: BusEvent) -> None:
        """Render a bus event if it has a terminal-facing representation."""
        if event.type == MESSAGE_TEXT_DELTA:
            self._render_message_delta(_payload_text(event, "text"))
        elif event.type == MESSAGE_REASONING_DELTA:
            self._render_reasoning_delta(_payload_text(event, "text"))
        elif event.type == MESSAGE_TOOL_USE_DELTA:
            self._render_tool_use_delta(event)
        elif event.type == TOOL_EXECUTE_BEFORE:
            self._render_tool_execute_before(event)
        elif event.type == TOOL_STREAM:
            self._render_tool_stream(event)
        elif event.type == TOOL_CANCELLED:
            self._render_tool_cancelled(event)
        elif event.type == TOOL_EXECUTE_AFTER:
            self._render_tool_execute_after(event)

    def finish_turn(self) -> None:
        """End the current rendered turn cleanly."""
        if not self._at_line_start:
            self._write("\n")
        self._current_section = None
        self._seen_tool_calls.clear()
        self._tool_inputs_started.clear()

    def _render_message_delta(self, text: str) -> None:
        if not text:
            return

        self._begin_section("message", self._style("assistant: ", "bold"))
        self._write(text)

    def _render_reasoning_delta(self, text: str) -> None:
        if not text:
            return

        self._begin_section("reasoning", self._style("think: ", "dim"))
        self._write(self._style(text, "dim"))

    def _render_tool_use_delta(self, event: BusEvent) -> None:
        tool_name = _payload_text(event, "tool_name") or "unknown"
        tool_key = _tool_key(event)
        input_delta = _payload_text(event, "input_delta")

        self._begin_tool_call(tool_key, tool_name)
        if input_delta:
            if tool_key not in self._tool_inputs_started:
                self._write(self._style(" input: ", "dim"))
                self._tool_inputs_started.add(tool_key)
            self._write(input_delta)
        self._seen_tool_calls.add(tool_key)

    def _render_tool_execute_before(self, event: BusEvent) -> None:
        tool_name = _payload_text(event, "tool_name") or "unknown"
        tool_key = _tool_key(event)

        if tool_key in self._seen_tool_calls:
            return

        self._begin_tool_call(tool_key, tool_name)
        self._seen_tool_calls.add(tool_key)

    def _render_tool_stream(self, event: BusEvent) -> None:
        data = event.payload.get("data")
        if data is None:
            return

        self._begin_section(
            f"tool_stream:{_tool_key(event)}",
            self._style("tool output: ", "dim"),
        )
        self._write(_format_value(data))

    def _render_tool_cancelled(self, event: BusEvent) -> None:
        tool_name = _payload_text(event, "tool_name") or "unknown"
        message = _payload_text(event, "message")
        suffix = f": {message}" if message else ""
        self._render_tool_status(tool_name, f"cancelled{suffix}", is_error=True)

    def _render_tool_execute_after(self, event: BusEvent) -> None:
        tool_name = _payload_text(event, "tool_name") or "unknown"
        has_error = event.payload.get("has_error") is True
        status = "error" if has_error else "done"
        self._render_tool_status(tool_name, status, is_error=has_error)

    def _render_tool_status(self, tool_name: str, status: str, *, is_error: bool) -> None:
        label_style = "red" if is_error else "green"
        self._begin_section(
            f"tool_status:{tool_name}:{status}",
            self._style("tool result: ", "dim") + self._style(f"{tool_name} {status}", label_style),
        )
        self._write("\n")
        self._current_section = None

    def _begin_tool_call(self, tool_key: str, tool_name: str) -> None:
        self._begin_section(
            f"tool:{tool_key}",
            self._style("tool: ", "dim") + self._style(tool_name, "bold"),
        )

    def _begin_section(self, section: str, label: str) -> None:
        if self._current_section == section:
            return

        if not self._at_line_start:
            self._write("\n")

        self._write(label)
        self._current_section = section

    def _write(self, text: str) -> None:
        # TODO: Sanitize untrusted model and tool output before writing terminal control sequences.
        self._stream.write(text)
        self._stream.flush()
        self._at_line_start = text.endswith("\n")

    def _style(self, text: str, style: str) -> str:
        if not self._color:
            return text

        codes = {
            "bold": "1",
            "dim": "2",
            "green": "32",
            "red": "31",
        }
        code = codes.get(style)
        if code is None:
            return text
        return f"\033[{code}m{text}\033[0m"


def _payload_text(event: BusEvent, key: str) -> str:
    value = event.payload.get(key)
    return value if isinstance(value, str) else ""


def _tool_key(event: BusEvent) -> str:
    tool_use_id = _payload_text(event, "tool_use_id")
    if tool_use_id:
        return tool_use_id

    tool_name = _payload_text(event, "tool_name")
    return tool_name if tool_name else "unknown"


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return value

    try:
        return json.dumps(_json_safe_value(value), separators=(",", ":"), ensure_ascii=True, default=str)
    except TypeError:
        return str(value)


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return value
