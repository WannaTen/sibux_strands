"""Tests for the Sibux SSE event endpoint."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request

import sibux.server.sse as sse_module
from sibux.config.config import Config
from sibux.config.defaults import default_config_dict
from sibux.event import MESSAGE_TEXT_DELTA, BusEvent, GlobalBus
from sibux.server.app import create_app
from sibux.server.routes import stream_events
from sibux.server.sse import encode_sse_event, get_or_create_sse_broker
from sibux.session import SessionService


@pytest.fixture(autouse=True)
def reset_global_bus() -> Iterator[None]:
    """Reset the singleton bus between SSE tests."""
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


def _build_config() -> Config:
    """Create a minimal config for server tests."""
    return Config.model_validate(default_config_dict())


def _build_app(tmp_path: Path) -> tuple[FastAPI, GlobalBus]:
    """Create an app wired to an isolated GlobalBus instance."""
    config = _build_config()
    global_bus = GlobalBus()
    app = create_app(
        config,
        session_service=SessionService(project_root=tmp_path),
        global_bus=global_bus,
    )
    return app, global_bus


def _build_request(app: FastAPI, receive: _ReceiveChannel) -> Request:
    """Create a minimal Request object for the SSE route."""
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/event",
        "raw_path": b"/event",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "app": app,
    }
    return Request(scope, receive)


def _event() -> BusEvent:
    """Build a representative SSE bus event."""
    return BusEvent(
        type=MESSAGE_TEXT_DELTA,
        session_id="sibux_stream",
        timestamp="2026-04-15T12:00:00Z",
        payload={"text": "hello"},
    )


async def _open_sse_stream(app: FastAPI, receive: _ReceiveChannel) -> tuple[AsyncGenerator[str, None], object]:
    """Open the SSE stream and consume the initial comment frame."""
    response = await stream_events(_build_request(app, receive))
    body = cast(AsyncGenerator[str, None], response.body_iterator)
    assert await anext(body) == ": connected\n\n"
    return body, response


class TestSSE:
    def test_encode_sse_event_serializes_nested_frozen_payload(self) -> None:
        event = BusEvent(
            type=MESSAGE_TEXT_DELTA,
            session_id="sibux_stream",
            timestamp="2026-04-15T12:00:00Z",
            payload={"nested": {"items": [{"text": "hello"}]}},
        )

        assert encode_sse_event(event) == (
            "event: message.text.delta\n"
            'data: {"type":"message.text.delta","session_id":"sibux_stream",'
            '"timestamp":"2026-04-15T12:00:00Z","payload":{"nested":{"items":[{"text":"hello"}]}}}\n\n'
        )

    def test_encode_sse_event_base64_encodes_bytes_payloads(self) -> None:
        event = BusEvent(
            type=MESSAGE_TEXT_DELTA,
            session_id="sibux_stream",
            timestamp="2026-04-15T12:00:00Z",
            payload={"event": {"reasoningContent": {"redactedContent": b"hello"}}},
        )

        assert encode_sse_event(event) == (
            "event: message.text.delta\n"
            'data: {"type":"message.text.delta","session_id":"sibux_stream","timestamp":"2026-04-15T12:00:00Z",'
            '"payload":{"event":{"reasoningContent":{"redactedContent":{"__bytes_encoded__":true,"data":"aGVsbG8="}}}}}\n\n'
        )

    @pytest.mark.asyncio
    async def test_event_endpoint_returns_sse_content_type(self, tmp_path: Path) -> None:
        app, _ = _build_app(tmp_path)
        receive = _ReceiveChannel()

        body, response = await _open_sse_stream(app, receive)

        assert response.headers["content-type"].startswith("text/event-stream")
        assert get_or_create_sse_broker(app).subscriber_count == 1

        receive.disconnect()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(body), timeout=1.0)

        assert get_or_create_sse_broker(app).subscriber_count == 0

    @pytest.mark.asyncio
    async def test_event_endpoint_broadcasts_to_multiple_clients(self, tmp_path: Path) -> None:
        app, global_bus = _build_app(tmp_path)
        first_receive = _ReceiveChannel()
        second_receive = _ReceiveChannel()
        event = _event()

        first_body, _ = await _open_sse_stream(app, first_receive)
        second_body, _ = await _open_sse_stream(app, second_receive)

        assert get_or_create_sse_broker(app).subscriber_count == 2

        global_bus.emit(event)
        expected_frame = (
            "event: message.text.delta\n"
            'data: {"type":"message.text.delta","session_id":"sibux_stream",'
            '"timestamp":"2026-04-15T12:00:00Z","payload":{"text":"hello"}}\n\n'
        )

        assert await asyncio.wait_for(anext(first_body), timeout=1.0) == expected_frame
        assert await asyncio.wait_for(anext(second_body), timeout=1.0) == expected_frame

        first_receive.disconnect()
        second_receive.disconnect()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(first_body), timeout=1.0)
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(second_body), timeout=1.0)

        assert get_or_create_sse_broker(app).subscriber_count == 0

    @pytest.mark.asyncio
    async def test_event_endpoint_cleans_up_subscribers_on_disconnect(self, tmp_path: Path) -> None:
        app, global_bus = _build_app(tmp_path)
        receive = _ReceiveChannel()

        body, _ = await _open_sse_stream(app, receive)
        assert get_or_create_sse_broker(app).subscriber_count == 1

        receive.disconnect()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(body), timeout=1.0)

        assert get_or_create_sse_broker(app).subscriber_count == 0

        global_bus.emit(_event())
        assert get_or_create_sse_broker(app).subscriber_count == 0

    @pytest.mark.asyncio
    async def test_event_endpoint_disconnects_slow_subscribers_when_queue_fills(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(sse_module, "SSE_SUBSCRIBER_QUEUE_MAXSIZE", 1)
        app, global_bus = _build_app(tmp_path)
        receive = _ReceiveChannel()

        body, _ = await _open_sse_stream(app, receive)
        broker = get_or_create_sse_broker(app)

        global_bus.emit(_event())
        global_bus.emit(_event())
        await asyncio.sleep(0)

        assert broker.subscriber_count == 0
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(body), timeout=1.0)
