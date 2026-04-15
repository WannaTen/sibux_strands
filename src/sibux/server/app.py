"""FastAPI application factory for Sibux."""

from __future__ import annotations

from fastapi import FastAPI

from ..config.config import Config
from ..session import SessionService
from .routes import router


def create_app(config: Config, *, session_service: SessionService | None = None) -> FastAPI:
    """Create the Sibux FastAPI application.

    Args:
        config: Loaded Sibux configuration.
        session_service: Optional injected session service. When omitted, the
            default service is created from the configured session settings.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(title="Sibux Server")
    app.state.sibux_config = config
    app.state.sibux_session_service = session_service or SessionService(
        storage_dir=config.session.storage_dir,
        resume=config.session.resume,
    )
    app.include_router(router)
    return app
