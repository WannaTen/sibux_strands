"""FastAPI application factory for Sibux."""

from __future__ import annotations

from fastapi import FastAPI

from ..config.config import Config
from ..event import GlobalBus
from ..session import SessionService
from .routes import _ServerRuntime, router


def create_app(
    config: Config,
    *,
    session_service: SessionService | None = None,
    global_bus: GlobalBus | None = None,
) -> FastAPI:
    """Create the Sibux FastAPI application.

    Args:
        config: Loaded Sibux configuration.
        session_service: Optional injected session service. When omitted, the
            default service is created from the configured session settings.
        global_bus: Optional injected global event bus used by SSE endpoints.

    Returns:
        Configured FastAPI application instance.
    """
    resolved_global_bus = global_bus or GlobalBus()
    app = FastAPI(title="Sibux Server")
    app.state.sibux_config = config
    app.state.sibux_session_service = session_service or SessionService(
        storage_dir=config.session.storage_dir,
        resume=config.session.resume,
        global_bus=resolved_global_bus,
    )
    app.state.sibux_global_bus = resolved_global_bus
    app.state.sibux_server_runtime = _ServerRuntime()
    app.include_router(router)
    return app
