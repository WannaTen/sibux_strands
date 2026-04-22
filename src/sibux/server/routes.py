"""FastAPI route definitions for the Sibux HTTP server."""

from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

import strands
from strands.handlers import null_callback_handler
from strands.types.exceptions import SessionException

from ..agent.agent_factory import create
from ..config.config import Config
from ..event import Bus, GlobalBus
from ..event.stream import StreamEventMapper, flatten_message_content
from ..session import ActiveSession, SessionService
from .schemas import (
    AbortResponse,
    CreateSessionRequest,
    ProviderResponse,
    SendMessageRequest,
    SessionResponse,
)
from .schemas import (
    SessionMessage as SessionMessageResponse,
)
from .sse import encode_sse_event, get_or_create_sse_broker

router = APIRouter()


class _ServerRuntime:
    """In-memory runtime registry for session HTTP operations."""

    def __init__(self) -> None:
        """Initialize empty runtime state."""
        self.inflight_agents: dict[str, strands.Agent] = {}
        self.known_session_ids: OrderedDict[str, None] = OrderedDict()
        self.lock = threading.RLock()

    def remember_session(self, session_id: str) -> None:
        """Remember one session id without retaining full session objects."""
        with self.lock:
            self.known_session_ids[session_id] = None
            self.known_session_ids.move_to_end(session_id)
            if len(self.known_session_ids) > 1024:
                self.known_session_ids.popitem(last=False)

    def knows_session(self, session_id: str) -> bool:
        """Return whether the runtime recently saw this session id."""
        with self.lock:
            return session_id in self.known_session_ids


@router.post("/session", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    request: Request,
    payload: CreateSessionRequest | None = None,
) -> SessionResponse:
    """Create a brand-new session for a primary agent."""
    config = _get_config(request)
    session_service = _get_session_service(request)
    agent_name = _resolve_primary_agent_name(config, payload.agent_name if payload is not None else None)
    active_session = session_service.new_session(agent_name=agent_name)
    _get_runtime(request).remember_session(active_session.session_id)
    return SessionResponse(session_id=active_session.session_id, agent_name=active_session.agent_name)


@router.post("/session/{id}/message")
async def send_message(request: Request, id: str, payload: SendMessageRequest) -> StreamingResponse:
    """Stream session execution events to the HTTP client and Sibux bus."""
    config = _get_config(request)
    active_session = _get_or_restore_session(request, id)
    bus = Bus(id, global_bus=_get_global_bus(request))
    runtime = _get_runtime(request)
    mapper = StreamEventMapper(id, model_id=_resolve_agent_model_id(config, active_session.agent_name))

    with runtime.lock:
        if id in runtime.inflight_agents:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"session '{id}' already has an active invocation",
            )
        agent = _create_session_agent(config, active_session)
        runtime.inflight_agents[id] = agent

    async def event_stream() -> AsyncIterator[str]:
        try:
            yield ": connected\n\n"
            async for stream_event in agent.stream_async(payload.content):
                for bus_event in mapper.map_event(stream_event):
                    bus.publish(bus_event)
                    yield encode_sse_event(bus_event)
        finally:
            with runtime.lock:
                if runtime.inflight_agents.get(id) is agent:
                    runtime.inflight_agents.pop(id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/session/{id}/messages", response_model=list[SessionMessageResponse])
def list_messages(request: Request, id: str) -> list[SessionMessageResponse]:
    """Return persisted message history for one session."""
    active_session = _get_or_restore_session(request, id)

    try:
        stored_messages = active_session.session_manager.list_messages(id, active_session.agent_id)
    except SessionException:
        return []

    response: list[SessionMessageResponse] = []
    for stored_message in stored_messages:
        message = stored_message.to_message()
        response.append(
            SessionMessageResponse(
                role=message["role"],
                content=flatten_message_content(message),
            )
        )
    return response


@router.post("/session/{id}/abort", response_model=AbortResponse)
def abort_session(request: Request, id: str) -> AbortResponse:
    """Cancel the current invocation for a session when one is active."""
    runtime = _get_runtime(request)
    with runtime.lock:
        agent = runtime.inflight_agents.get(id)

    if agent is None:
        return AbortResponse(aborted=False)

    agent.cancel()
    return AbortResponse(aborted=True)


@router.get("/event")
async def stream_events(request: Request) -> StreamingResponse:
    """Stream global bus events over SSE."""
    broker = get_or_create_sse_broker(request.app)
    queue = broker.subscribe()

    async def event_stream() -> AsyncIterator[str]:
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                if not broker.is_subscribed(queue):
                    break

                try:
                    message = await asyncio.wait_for(queue.get(), timeout=0.25)
                except TimeoutError:
                    continue

                yield message
        finally:
            broker.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/provider", response_model=list[ProviderResponse])
def list_providers(request: Request) -> list[ProviderResponse]:
    """Return the configured provider/model pairs available to the server."""
    return _list_provider_models(_get_config(request))


def _get_config(request: Request) -> Config:
    """Return the application config stored on the FastAPI app state."""
    config = getattr(request.app.state, "sibux_config", None)
    if not isinstance(config, Config):
        raise RuntimeError("sibux_config is missing from application state")
    return config


def _get_session_service(request: Request) -> SessionService:
    """Return the session service stored on the FastAPI app state."""
    session_service = getattr(request.app.state, "sibux_session_service", None)
    if not isinstance(session_service, SessionService):
        raise RuntimeError("sibux_session_service is missing from application state")
    return session_service


def _get_global_bus(request: Request) -> GlobalBus:
    """Return the global bus stored on the FastAPI app state."""
    global_bus = getattr(request.app.state, "sibux_global_bus", None)
    if not isinstance(global_bus, GlobalBus):
        raise RuntimeError("sibux_global_bus is missing from application state")
    return global_bus


def _get_runtime(request: Request) -> _ServerRuntime:
    """Return the app-scoped server runtime registry."""
    runtime = getattr(request.app.state, "sibux_server_runtime", None)
    if isinstance(runtime, _ServerRuntime):
        return runtime

    raise RuntimeError("sibux_server_runtime is missing from application state")


def _get_or_restore_session(request: Request, session_id: str) -> ActiveSession:
    """Return one session, publishing a resume event when reloaded from storage."""
    session_service = _get_session_service(request)
    active_session = session_service.get_session(session_id=session_id)
    if active_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"session '{session_id}' was not found",
        )

    runtime = _get_runtime(request)
    if not runtime.knows_session(session_id):
        session_service.publish_session_event(active_session)
        runtime.remember_session(session_id)

    return active_session


def _create_session_agent(config: Config, active_session: ActiveSession) -> strands.Agent:
    """Build a fresh session-backed agent for one HTTP invocation."""
    agent_config = config.agents.get(active_session.agent_name)
    if agent_config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"agent '{active_session.agent_name}' is not configured",
        )

    agent = create(
        config,
        agent_config,
        session_manager=active_session.session_manager,
        agent_id=active_session.agent_id,
    )
    agent.callback_handler = null_callback_handler
    return agent


def _resolve_primary_agent_name(config: Config, requested_agent_name: str | None) -> str:
    """Validate the requested agent name against configured primary agents."""
    agent_name = requested_agent_name or config.default_agent
    agent_config = config.agents.get(agent_name)

    if agent_config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"agent '{agent_name}' is not configured",
        )
    if agent_config.mode != "primary":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"agent '{agent_name}' must have mode='primary'",
        )

    return agent_name


def _resolve_agent_model_id(config: Config, agent_name: str) -> str | None:
    """Resolve the configured model reference for one agent."""
    agent_config = config.agents.get(agent_name)
    if agent_config is None:
        return None

    model_ref = agent_config.model or config.default_model
    if model_ref is None:
        return None

    return _resolve_model_reference(config, model_ref) or model_ref


def _list_provider_models(config: Config) -> list[ProviderResponse]:
    """Collect unique provider/model ids from the current config."""
    grouped_models: dict[str, set[str]] = {}

    for model_ref in _iter_model_references(config):
        resolved_ref = _resolve_model_reference(config, model_ref)
        if resolved_ref is None:
            continue

        provider_id, model_id = resolved_ref.split("/", 1)
        grouped_models.setdefault(provider_id, set()).add(model_id)

    return [
        ProviderResponse(provider=provider_id, models=sorted(grouped_models[provider_id]))
        for provider_id in sorted(grouped_models)
    ]


def _iter_model_references(config: Config) -> list[str]:
    """Return model references declared across config defaults and agents."""
    model_refs = [model_config.model for model_config in config.model.values()]

    if config.default_model is not None:
        model_refs.append(config.default_model)

    model_refs.extend(agent_config.model for agent_config in config.agents.values() if agent_config.model is not None)
    return model_refs


def _resolve_model_reference(config: Config, model_ref: str) -> str | None:
    """Resolve a named model alias to a concrete ``provider/model_id`` string."""
    if "/" in model_ref:
        return model_ref

    model_config = config.model.get(model_ref)
    if model_config is None:
        return None

    return model_config.model
