"""Tests for the Sibux streaming message endpoints."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI, HTTPException, Request

import sibux.server.routes as route_module
import strands
from sibux.config.config import Config
from sibux.config.defaults import default_config_dict
from sibux.event import (
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
    SESSION_RESUMED,
    TOOL_CANCELLED,
    TOOL_EXECUTE_AFTER,
    TOOL_EXECUTE_BEFORE,
    TOOL_STREAM,
    BusEvent,
    GlobalBus,
)
from sibux.event.stream import StreamEventMapper, flatten_message_content
from sibux.server.app import create_app
from sibux.server.routes import abort_session, create_session, list_messages, send_message, stream_events
from sibux.server.schemas import SendMessageRequest
from sibux.session import SessionService
from strands.agent.agent_result import AgentResult
from strands.handlers import null_callback_handler
from strands.models.model import Model
from strands.telemetry.metrics import EventLoopMetrics
from tests.fixtures.mocked_model_provider import MockedModelProvider


@pytest.fixture(autouse=True)
def reset_global_bus() -> Iterator[None]:
    """Reset the singleton bus between streaming tests."""
    GlobalBus._instance = None
    yield
    GlobalBus._instance = None


class _ReceiveChannel:
    """Minimal ASGI receive channel controllable by tests."""

    def __init__(self) -> None:
        self._disconnected = False

    def disconnect(self) -> None:
        """Flip the channel into a disconnected state."""
        self._disconnected = True

    async def __call__(self) -> dict[str, object]:
        """Return the next ASGI receive event."""
        if self._disconnected:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": b"", "more_body": False}


class SlowTextModel(Model):
    """Simple model that streams slowly enough for abort tests."""

    def __init__(self, *, delay: float = 0.2) -> None:
        self._delay = delay

    def update_config(self, **model_config: Any) -> None:
        """Ignore config updates in tests."""

    def get_config(self) -> dict[str, object]:
        """Return a trivial config payload."""
        return {}

    async def structured_output(  # pragma: no cover - not used in these tests
        self,
        output_model: type[Any],
        prompt: list[dict[str, object]],
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, object], None]:
        if False:
            yield {}
        raise NotImplementedError

    async def stream(
        self,
        messages: list[dict[str, object]],
        tool_specs: list[dict[str, object]] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: Any | None = None,
        system_prompt_content: list[dict[str, object]] | None = None,
        invocation_state: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, object], None]:
        del messages, tool_specs, system_prompt, tool_choice, system_prompt_content, invocation_state, kwargs
        yield {"messageStart": {"role": "assistant"}}
        await asyncio.sleep(self._delay)
        yield {"contentBlockStart": {"start": {}}}
        await asyncio.sleep(self._delay)
        yield {"contentBlockDelta": {"delta": {"text": "still running"}}}
        await asyncio.sleep(self._delay)
        yield {"contentBlockStop": {}}
        await asyncio.sleep(self._delay)
        yield {"messageStop": {"stopReason": "end_turn"}}


def _build_config() -> Config:
    """Create a minimal config for server tests."""
    return Config.model_validate(default_config_dict())


def _build_app(tmp_path: Path) -> FastAPI:
    """Create an app wired to an isolated session root."""
    return create_app(
        _build_config(),
        session_service=SessionService(project_root=tmp_path, resume="new"),
        global_bus=GlobalBus(),
    )


def _build_request(
    app: FastAPI,
    *,
    path: str,
    method: str,
    receive: _ReceiveChannel | None = None,
) -> Request:
    """Create a minimal Request object for direct route invocation."""
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "app": app,
    }
    return Request(scope, receive or _ReceiveChannel())


def _patch_create(monkeypatch: pytest.MonkeyPatch, model_factory: Callable[[], Model]) -> None:
    """Patch the server agent factory to return a real test agent."""

    def fake_create(
        config: Config,
        agent_config: Any,
        *,
        session_manager: Any = None,
        agent_id: str | None = None,
        context_manager: Any | None = None,
        hooks: list[Any] | None = None,
    ) -> strands.Agent:
        del config, agent_config, context_manager, hooks
        assert session_manager is not None
        assert agent_id is not None
        return strands.Agent(
            model=model_factory(),
            session_manager=session_manager,
            agent_id=agent_id,
            callback_handler=null_callback_handler,
        )

    monkeypatch.setattr(route_module, "create", fake_create)


def _decode_frame(frame: str) -> dict[str, Any]:
    """Decode the JSON payload from an SSE frame."""
    data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
    return cast(dict[str, Any], json.loads(data_line.removeprefix("data: ")))


async def _open_streaming_response(response: object) -> AsyncGenerator[str, None]:
    """Consume the initial SSE comment frame and return the body iterator."""
    body = cast(AsyncGenerator[str, None], cast(Any, response).body_iterator)
    assert await anext(body) == ": connected\n\n"
    return body


async def _collect_until_result(body: AsyncGenerator[str, None]) -> list[str]:
    """Collect SSE frames until the final invocation result event arrives."""
    frames: list[str] = []
    while True:
        frame = await asyncio.wait_for(anext(body), timeout=2.0)
        frames.append(frame)
        if frame.startswith(f"event: {INVOCATION_RESULT}\n"):
            return frames


def _assistant_message(text: str) -> dict[str, object]:
    """Build a simple assistant message fixture."""
    return {
        "role": "assistant",
        "content": [{"text": text}],
    }


@pytest.mark.parametrize(
    ("stream_event", "expected_events"),
    [
        (
            {"data": "hello", "delta": {"text": "hello"}},
            [
                BusEvent(
                    type=MESSAGE_TEXT_DELTA,
                    session_id="sibux_stream",
                    timestamp="2026-04-16T12:00:00Z",
                    payload={"text": "hello"},
                )
            ],
        ),
        (
            {
                "type": "tool_use_stream",
                "delta": {"toolUse": {"input": '{"path":"README.md"}'}},
                "current_tool_use": {
                    "name": "read",
                    "toolUseId": "tool-1",
                    "input": {},
                },
            },
            [
                BusEvent(
                    type=MESSAGE_TOOL_USE_DELTA,
                    session_id="sibux_stream",
                    timestamp="2026-04-16T12:00:00Z",
                    payload={
                        "tool_name": "read",
                        "tool_use_id": "tool-1",
                        "input_delta": '{"path":"README.md"}',
                    },
                )
            ],
        ),
        (
            {"reasoningText": "thinking", "delta": {}, "reasoning": True},
            [
                BusEvent(
                    type=MESSAGE_REASONING_DELTA,
                    session_id="sibux_stream",
                    timestamp="2026-04-16T12:00:00Z",
                    payload={"text": "thinking"},
                )
            ],
        ),
        (
            {"event": {"messageStart": {"role": "assistant"}}},
            [
                BusEvent(
                    type=MESSAGE_EVENT,
                    session_id="sibux_stream",
                    timestamp="2026-04-16T12:00:00Z",
                    payload={"event": {"messageStart": {"role": "assistant"}}},
                )
            ],
        ),
        (
            {"message": {"role": "assistant", "content": [{"text": "hello"}]}},
            [
                BusEvent(
                    type=MESSAGE_ADDED,
                    session_id="sibux_stream",
                    timestamp="2026-04-16T12:00:00Z",
                    payload={"role": "assistant", "content_summary": "hello"},
                )
            ],
        ),
        (
            {
                "type": "tool_stream",
                "tool_stream_event": {
                    "tool_use": {"name": "bash", "toolUseId": "tool-2", "input": {}},
                    "data": {"stdout": "ok"},
                },
            },
            [
                BusEvent(
                    type=TOOL_STREAM,
                    session_id="sibux_stream",
                    timestamp="2026-04-16T12:00:00Z",
                    payload={
                        "tool_name": "bash",
                        "tool_use_id": "tool-2",
                        "data": {"stdout": "ok"},
                    },
                )
            ],
        ),
        (
            {
                "tool_cancel_event": {
                    "tool_use": {"name": "bash", "toolUseId": "tool-3", "input": {}},
                    "message": "cancelled",
                }
            },
            [
                BusEvent(
                    type=TOOL_CANCELLED,
                    session_id="sibux_stream",
                    timestamp="2026-04-16T12:00:00Z",
                    payload={
                        "tool_name": "bash",
                        "tool_use_id": "tool-3",
                        "message": "cancelled",
                    },
                )
            ],
        ),
        (
            {
                "result": AgentResult(
                    stop_reason="end_turn",
                    message={"role": "assistant", "content": [{"text": "done"}]},
                    metrics=EventLoopMetrics(),
                    state={},
                )
            },
            [
                BusEvent(
                    type=INVOCATION_RESULT,
                    session_id="sibux_stream",
                    timestamp="2026-04-16T12:00:00Z",
                    payload={
                        "stop_reason": "end_turn",
                        "message": {"role": "assistant", "content": [{"text": "done"}]},
                        "content_summary": "done",
                    },
                )
            ],
        ),
    ],
)
def test_stream_event_mapper_maps_single_event_shapes(
    stream_event: dict[str, Any],
    expected_events: list[BusEvent],
) -> None:
    mapper = StreamEventMapper("sibux_stream")

    assert mapper.map_event(stream_event, timestamp="2026-04-16T12:00:00Z") == expected_events


def test_stream_event_mapper_emits_lifecycle_and_content_events() -> None:
    mapper = StreamEventMapper("sibux_stream", model_id="anthropic/claude-sonnet-4-5")
    message = {
        "role": "user",
        "content": [
            {
                "toolResult": {
                    "toolUseId": "tool-1",
                    "status": "error",
                    "content": [{"text": "boom"}],
                }
            }
        ],
    }
    result = AgentResult(
        stop_reason="end_turn",
        message={"role": "assistant", "content": [{"text": "done"}]},
        metrics=EventLoopMetrics(),
        state={},
    )

    mapped_events: list[BusEvent] = []
    for stream_event in [
        {"start": True},
        {"start_event_loop": True},
        {"event": {"contentBlockStart": {"start": {"toolUse": {"name": "read", "toolUseId": "tool-1"}}}}},
        {"message": message},
        {"event": {"messageStop": {"stopReason": "end_turn"}}},
        {"event": {"metadata": {"usage": {"inputTokens": 1, "outputTokens": 2, "totalTokens": 3}}}},
        {"result": result},
    ]:
        mapped_events.extend(mapper.map_event(stream_event, timestamp="2026-04-16T12:00:00Z"))

    assert [event.type for event in mapped_events] == [
        INVOCATION_BEFORE,
        MODEL_CALL_BEFORE,
        MESSAGE_EVENT,
        TOOL_EXECUTE_BEFORE,
        TOOL_EXECUTE_AFTER,
        MESSAGE_ADDED,
        MESSAGE_EVENT,
        INVOCATION_AFTER,
        MESSAGE_EVENT,
        MODEL_CALL_AFTER,
        INVOCATION_RESULT,
    ]
    assert mapped_events[2].payload == {
        "event": {"contentBlockStart": {"start": {"toolUse": {"name": "read", "toolUseId": "tool-1"}}}}
    }
    assert mapped_events[3].payload == {"tool_name": "read", "tool_use_id": "tool-1"}
    assert mapped_events[4].payload == {"tool_name": "read", "tool_use_id": "tool-1", "has_error": True}
    assert mapped_events[7].payload == {"stop_reason": "end_turn"}
    assert mapped_events[9].payload == {
        "model_id": "anthropic/claude-sonnet-4-5",
        "usage": {"inputTokens": 1, "outputTokens": 2, "totalTokens": 3},
    }


def test_stream_event_mapper_only_emits_invocation_after_for_final_stop() -> None:
    mapper = StreamEventMapper("sibux_stream", model_id="anthropic/claude-sonnet-4-5")
    result = AgentResult(
        stop_reason="end_turn",
        message={"role": "assistant", "content": [{"text": "done"}]},
        metrics=EventLoopMetrics(),
        state={},
    )

    mapped_events: list[BusEvent] = []
    for stream_event in [
        {"start": True},
        {"start_event_loop": True},
        {"event": {"messageStop": {"stopReason": "tool_use"}}},
        {"event": {"metadata": {"usage": {"inputTokens": 1, "outputTokens": 2, "totalTokens": 3}}}},
        {"start_event_loop": True},
        {"event": {"messageStop": {"stopReason": "end_turn"}}},
        {"event": {"metadata": {"usage": {"inputTokens": 4, "outputTokens": 5, "totalTokens": 9}}}},
        {"result": result},
    ]:
        mapped_events.extend(mapper.map_event(stream_event, timestamp="2026-04-16T12:00:00Z"))

    assert [event.type for event in mapped_events].count(INVOCATION_AFTER) == 1
    assert [event.payload for event in mapped_events if event.type == INVOCATION_AFTER] == [{"stop_reason": "end_turn"}]
    assert [event.type for event in mapped_events].count(MODEL_CALL_BEFORE) == 2
    assert [event.type for event in mapped_events].count(MODEL_CALL_AFTER) == 2


def test_stream_event_mapper_falls_back_to_result_for_missing_stop_and_usage() -> None:
    mapper = StreamEventMapper("sibux_stream", model_id="anthropic/claude-sonnet-4-5")
    result = AgentResult(
        stop_reason="cancelled",
        message={"role": "assistant", "content": [{"text": "Cancelled by user"}]},
        metrics=EventLoopMetrics(),
        state={},
    )

    mapped_events: list[BusEvent] = []
    for stream_event in [
        {"start": True},
        {"start_event_loop": True},
        {"result": result},
    ]:
        mapped_events.extend(mapper.map_event(stream_event, timestamp="2026-04-16T12:00:00Z"))

    assert [event.type for event in mapped_events] == [
        INVOCATION_BEFORE,
        MODEL_CALL_BEFORE,
        INVOCATION_AFTER,
        MODEL_CALL_AFTER,
        INVOCATION_RESULT,
    ]
    assert mapped_events[2].payload == {"stop_reason": "cancelled"}
    assert mapped_events[3].payload == {"model_id": "anthropic/claude-sonnet-4-5", "usage": {}}


def test_flatten_message_content_summarizes_tool_blocks() -> None:
    message = {
        "role": "assistant",
        "content": [
            {"text": "first"},
            {"toolUse": {"name": "read", "toolUseId": "tool-1", "input": {"path": "README.md"}}},
            {"toolResult": {"status": "success", "toolUseId": "tool-1", "content": [{"text": "done"}]}},
        ],
    }

    assert flatten_message_content(cast(dict[str, Any], message)) == (
        'first\n[tool_use:read] {"path":"README.md"}\n[tool_result:success] done'
    )


class TestStreamingRoutes:
    @pytest.mark.asyncio
    async def test_message_stream_mirrors_bus_events_and_persists_history(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        app = _build_app(tmp_path)
        _patch_create(monkeypatch, lambda: MockedModelProvider([_assistant_message("hello back")]))

        session = create_session(_build_request(app, path="/session", method="POST"))
        session_id = session.session_id

        global_receive = _ReceiveChannel()
        global_response = await stream_events(_build_request(app, path="/event", method="GET", receive=global_receive))
        global_body = await _open_streaming_response(global_response)

        message_response = await send_message(
            _build_request(app, path=f"/session/{session_id}/message", method="POST"),
            session_id,
            SendMessageRequest(content="hello"),
        )
        message_body = await _open_streaming_response(message_response)

        message_frames = await _collect_until_result(message_body)
        global_frames = await _collect_until_result(global_body)

        assert message_frames == global_frames
        assert any(frame.startswith(f"event: {INVOCATION_BEFORE}\n") for frame in message_frames)
        assert any(frame.startswith(f"event: {MODEL_CALL_BEFORE}\n") for frame in message_frames)
        assert any(frame.startswith(f"event: {MESSAGE_TEXT_DELTA}\n") for frame in message_frames)
        assert any(frame.startswith(f"event: {MODEL_CALL_AFTER}\n") for frame in message_frames)
        assert message_frames[-1].startswith(f"event: {INVOCATION_RESULT}\n")

        history = list_messages(_build_request(app, path=f"/session/{session_id}/messages", method="GET"), session_id)
        assert [item.model_dump() for item in history] == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hello back"},
        ]

        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(message_body), timeout=1.0)

        global_receive.disconnect()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(global_body), timeout=1.0)

    @pytest.mark.asyncio
    async def test_message_endpoint_rejects_concurrent_invocations(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        app = _build_app(tmp_path)
        _patch_create(monkeypatch, lambda: MockedModelProvider([_assistant_message("done")]))

        session = create_session(_build_request(app, path="/session", method="POST"))
        session_id = session.session_id

        first_response = await send_message(
            _build_request(app, path=f"/session/{session_id}/message", method="POST"),
            session_id,
            SendMessageRequest(content="first"),
        )

        with pytest.raises(HTTPException) as excinfo:
            await send_message(
                _build_request(app, path=f"/session/{session_id}/message", method="POST"),
                session_id,
                SendMessageRequest(content="second"),
            )

        assert excinfo.value.status_code == 409

        first_body = await _open_streaming_response(first_response)
        frames = await _collect_until_result(first_body)
        assert frames[-1].startswith(f"event: {INVOCATION_RESULT}\n")

    @pytest.mark.asyncio
    async def test_abort_cancels_active_stream(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        app = _build_app(tmp_path)
        _patch_create(monkeypatch, lambda: SlowTextModel(delay=0.2))

        session = create_session(_build_request(app, path="/session", method="POST"))
        session_id = session.session_id

        message_response = await send_message(
            _build_request(app, path=f"/session/{session_id}/message", method="POST"),
            session_id,
            SendMessageRequest(content="stop"),
        )
        message_body = await _open_streaming_response(message_response)

        abort_response = abort_session(
            _build_request(app, path=f"/session/{session_id}/abort", method="POST"),
            session_id,
        )
        assert abort_response.aborted is True

        frames = await _collect_until_result(message_body)
        result_payload = _decode_frame(frames[-1])
        assert result_payload["type"] == INVOCATION_RESULT
        assert result_payload["payload"]["stop_reason"] == "cancelled"

    @pytest.mark.asyncio
    async def test_message_stream_survives_failing_subscribers(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        app = _build_app(tmp_path)
        _patch_create(monkeypatch, lambda: MockedModelProvider([_assistant_message("hello back")]))

        def broken_callback(event: BusEvent) -> None:
            del event
            raise RuntimeError("boom")

        app.state.sibux_global_bus.on_all(broken_callback)

        session = create_session(_build_request(app, path="/session", method="POST"))
        response = await send_message(
            _build_request(app, path=f"/session/{session.session_id}/message", method="POST"),
            session.session_id,
            SendMessageRequest(content="hello"),
        )

        frames = await _collect_until_result(await _open_streaming_response(response))

        assert frames[-1].startswith(f"event: {INVOCATION_RESULT}\n")

    @pytest.mark.asyncio
    async def test_messages_route_restores_session_from_storage_after_restart(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _patch_create(monkeypatch, lambda: MockedModelProvider([_assistant_message("hello back")]))

        first_app = _build_app(tmp_path)
        session = create_session(_build_request(first_app, path="/session", method="POST"))
        session_id = session.session_id

        first_response = await send_message(
            _build_request(first_app, path=f"/session/{session_id}/message", method="POST"),
            session_id,
            SendMessageRequest(content="hello"),
        )
        await _collect_until_result(await _open_streaming_response(first_response))

        second_app = _build_app(tmp_path)
        observed_events: list[BusEvent] = []
        second_app.state.sibux_global_bus.on_all(observed_events.append)

        history = list_messages(
            _build_request(second_app, path=f"/session/{session_id}/messages", method="GET"),
            session_id,
        )

        assert [item.model_dump() for item in history] == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hello back"},
        ]
        assert [event.type for event in observed_events] == [SESSION_RESUMED]
        assert observed_events[0].session_id == session_id

    @pytest.mark.asyncio
    async def test_message_route_restores_session_from_storage_after_restart(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _patch_create(monkeypatch, lambda: MockedModelProvider([_assistant_message("hello back")]))

        first_app = _build_app(tmp_path)
        session = create_session(_build_request(first_app, path="/session", method="POST"))
        session_id = session.session_id

        first_response = await send_message(
            _build_request(first_app, path=f"/session/{session_id}/message", method="POST"),
            session_id,
            SendMessageRequest(content="hello"),
        )
        await _collect_until_result(await _open_streaming_response(first_response))

        second_app = _build_app(tmp_path)
        observed_events: list[BusEvent] = []
        second_app.state.sibux_global_bus.on_all(observed_events.append)

        second_response = await send_message(
            _build_request(second_app, path=f"/session/{session_id}/message", method="POST"),
            session_id,
            SendMessageRequest(content="again"),
        )
        second_frames = await _collect_until_result(await _open_streaming_response(second_response))

        assert second_frames[-1].startswith(f"event: {INVOCATION_RESULT}\n")
        assert SESSION_RESUMED in [event.type for event in observed_events]

        history = list_messages(
            _build_request(second_app, path=f"/session/{session_id}/messages", method="GET"),
            session_id,
        )
        assert [item.model_dump() for item in history] == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hello back"},
            {"role": "user", "content": "again"},
            {"role": "assistant", "content": "hello back"},
        ]
