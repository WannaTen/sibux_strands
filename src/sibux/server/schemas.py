"""HTTP request and response schemas for the Sibux server."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    """Request payload for creating a new session.

    Attributes:
        agent_name: Optional primary-agent name. Falls back to the configured
            default agent when omitted.
    """

    agent_name: str | None = None


class SessionResponse(BaseModel):
    """Response payload describing a created session.

    Attributes:
        session_id: Stable identifier for the new session.
        agent_name: Primary agent bound to the session.
    """

    session_id: str
    agent_name: str


class SendMessageRequest(BaseModel):
    """Request payload for sending a user message to a session.

    Attributes:
        content: User message text. Streaming execution is implemented in a
            later phase, so this schema exists to freeze the route contract.
    """

    content: str = Field(min_length=1)


class SessionMessage(BaseModel):
    """Serialized session message returned by the history endpoint.

    Attributes:
        role: Message role, for example ``"user"`` or ``"assistant"``.
        content: Flattened message text content.
    """

    role: str
    content: str


class AbortResponse(BaseModel):
    """Response payload for abort requests.

    Attributes:
        aborted: Whether an in-flight invocation was cancelled.
    """

    aborted: bool


class ProviderResponse(BaseModel):
    """Grouped provider and model identifiers exposed by the HTTP API.

    Attributes:
        provider: Provider identifier such as ``"anthropic"``.
        models: Sorted unique model ids configured for the provider.
    """

    provider: str
    models: list[str]
