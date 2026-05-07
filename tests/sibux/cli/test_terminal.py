"""Tests for Sibux terminal event rendering."""

from __future__ import annotations

from io import StringIO
from typing import Any

from sibux.cli.terminal import TerminalRenderer
from sibux.event import (
    MESSAGE_REASONING_DELTA,
    MESSAGE_TEXT_DELTA,
    MESSAGE_TOOL_USE_DELTA,
    TOOL_EXECUTE_AFTER,
    TOOL_EXECUTE_BEFORE,
    TOOL_STREAM,
    BusEvent,
)


def _event(event_type: str, payload: dict[str, Any]) -> BusEvent:
    """Build a bus event for renderer tests."""
    return BusEvent(
        type=event_type,
        session_id="sibux_test",
        timestamp="2026-05-02T00:00:00Z",
        payload=payload,
    )


def test_terminal_renderer_groups_message_reasoning_and_tool_chunks() -> None:
    stream = StringIO()
    renderer = TerminalRenderer(stream, color=False)

    renderer.handle(_event(MESSAGE_TEXT_DELTA, {"text": "hello"}))
    renderer.handle(_event(MESSAGE_TEXT_DELTA, {"text": " world"}))
    renderer.handle(_event(MESSAGE_REASONING_DELTA, {"text": "checking"}))
    renderer.handle(
        _event(
            MESSAGE_TOOL_USE_DELTA,
            {
                "tool_name": "read",
                "tool_use_id": "toolu_1",
                "input_delta": '{"path":"README.md"}',
            },
        )
    )
    renderer.handle(
        _event(
            TOOL_STREAM,
            {
                "tool_name": "read",
                "tool_use_id": "toolu_1",
                "data": "line 1",
            },
        )
    )
    renderer.handle(
        _event(
            TOOL_EXECUTE_AFTER,
            {
                "tool_name": "read",
                "tool_use_id": "toolu_1",
                "has_error": False,
            },
        )
    )
    renderer.finish_turn()

    assert stream.getvalue() == (
        "assistant: hello world\n"
        "think: checking\n"
        'tool: read input: {"path":"README.md"}\n'
        "tool output: line 1\n"
        "tool result: read done\n"
    )


def test_terminal_renderer_does_not_duplicate_tool_start_from_before_and_delta() -> None:
    stream = StringIO()
    renderer = TerminalRenderer(stream, color=False)

    renderer.handle(
        _event(
            TOOL_EXECUTE_BEFORE,
            {
                "tool_name": "bash",
                "tool_use_id": "toolu_2",
            },
        )
    )
    renderer.handle(
        _event(
            MESSAGE_TOOL_USE_DELTA,
            {
                "tool_name": "bash",
                "tool_use_id": "toolu_2",
                "input_delta": '{"command":"pwd"}',
            },
        )
    )
    renderer.finish_turn()

    assert stream.getvalue() == 'tool: bash input: {"command":"pwd"}\n'


def test_terminal_renderer_formats_structured_tool_stream_mapping() -> None:
    stream = StringIO()
    renderer = TerminalRenderer(stream, color=False)

    renderer.handle(
        _event(
            TOOL_STREAM,
            {
                "tool_name": "bash",
                "tool_use_id": "toolu_3",
                "data": {"stdout": "ok", "exit_code": 0},
            },
        )
    )
    renderer.finish_turn()

    assert stream.getvalue() == 'tool output: {"stdout":"ok","exit_code":0}\n'


def test_terminal_renderer_formats_structured_tool_stream_sequence() -> None:
    stream = StringIO()
    renderer = TerminalRenderer(stream, color=False)

    renderer.handle(
        _event(
            TOOL_STREAM,
            {
                "tool_name": "read",
                "tool_use_id": "toolu_4",
                "data": [{"line": 1, "text": "hello"}, {"line": 2, "text": "world"}],
            },
        )
    )
    renderer.finish_turn()

    assert stream.getvalue() == 'tool output: [{"line":1,"text":"hello"},{"line":2,"text":"world"}]\n'
