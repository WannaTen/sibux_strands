"""FastAPI route definitions for the Sibux HTTP server."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from ..config.config import Config
from ..session import SessionService
from .schemas import (
    AbortResponse,
    CreateSessionRequest,
    ProviderResponse,
    SendMessageRequest,
    SessionMessage,
    SessionResponse,
)

router = APIRouter()


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
    return SessionResponse(session_id=active_session.session_id, agent_name=active_session.agent_name)


@router.post("/session/{id}/message")
def send_message(id: str, payload: SendMessageRequest) -> None:  # noqa: ARG001
    """Reserve the streaming message route until Phase 3 wiring lands."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="streaming session message endpoint is not implemented",
    )


@router.get("/session/{id}/messages", response_model=list[SessionMessage])
def list_messages(id: str) -> list[SessionMessage]:  # noqa: ARG001
    """Return session message history once storage wiring is implemented."""
    return []


@router.post("/session/{id}/abort", response_model=AbortResponse)
def abort_session(id: str) -> AbortResponse:  # noqa: ARG001
    """Return a placeholder abort response until runtime tracking is implemented."""
    return AbortResponse(aborted=False)


@router.get("/event")
def stream_events() -> None:
    """Reserve the global SSE event route until Event Bus wiring lands."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="global event stream endpoint is not implemented",
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
