"""Tests for non-streaming Sibux FastAPI routes."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from sibux.config.config import Config
from sibux.config.defaults import default_config_dict
from sibux.server.app import create_app
from sibux.session import SessionService


def _build_config() -> Config:
    """Create a config with multiple configured provider/model references."""
    config_dict = default_config_dict()
    config_dict["default_agent"] = "build"
    config_dict["default_model"] = "sonnet"
    config_dict["model"] = {
        "sonnet": {"model": "anthropic/claude-sonnet-4-5"},
        "haiku": {"model": "anthropic/claude-haiku-3-5"},
        "gpt5": {"model": "openai/gpt-5.1"},
    }
    config_dict["agents"]["build"]["model"] = "gpt5"
    config_dict["agents"]["review"] = {
        "name": "review",
        "mode": "primary",
        "model": "anthropic/claude-haiku-3-5",
        "prompt": "Review code.",
        "permission": [{"permission": "*", "pattern": "*", "action": "allow"}],
    }
    return Config.model_validate(config_dict)


class TestRoutes:
    def test_post_session_creates_new_session(self, tmp_path: Path) -> None:
        config = _build_config()
        session_service = SessionService(project_root=tmp_path, resume="new")
        client = TestClient(create_app(config, session_service=session_service))

        response = client.post("/session")

        assert response.status_code == 201
        assert response.json()["agent_name"] == "build"
        assert response.json()["session_id"].startswith("sibux_")
        assert session_service.current() is not None
        assert session_service.current().session_id == response.json()["session_id"]

    def test_post_session_accepts_explicit_primary_agent(self, tmp_path: Path) -> None:
        config = _build_config()
        session_service = SessionService(project_root=tmp_path, resume="new")
        client = TestClient(create_app(config, session_service=session_service))

        response = client.post("/session", json={"agent_name": "review"})

        assert response.status_code == 201
        assert response.json() == {
            "session_id": response.json()["session_id"],
            "agent_name": "review",
        }

    def test_get_provider_returns_grouped_models_from_config(self, tmp_path: Path) -> None:
        config = _build_config()
        client = TestClient(create_app(config, session_service=SessionService(project_root=tmp_path)))

        response = client.get("/provider")

        assert response.status_code == 200
        assert response.json() == [
            {"provider": "anthropic", "models": ["claude-haiku-3-5", "claude-sonnet-4-5"]},
            {"provider": "openai", "models": ["gpt-5.1"]},
        ]

    def test_message_endpoint_rejects_unknown_session(self, tmp_path: Path) -> None:
        config = _build_config()
        client = TestClient(create_app(config, session_service=SessionService(project_root=tmp_path)))

        message_response = client.post("/session/sibux_test/message", json={"content": "hello"})

        assert message_response.status_code == 404

    def test_messages_endpoint_rejects_unknown_session(self, tmp_path: Path) -> None:
        config = _build_config()
        client = TestClient(create_app(config, session_service=SessionService(project_root=tmp_path)))

        messages_response = client.get("/session/sibux_test/messages")

        assert messages_response.status_code == 404

    def test_abort_endpoint_returns_false_without_active_invocation(self, tmp_path: Path) -> None:
        config = _build_config()
        client = TestClient(create_app(config, session_service=SessionService(project_root=tmp_path)))

        abort_response = client.post("/session/sibux_test/abort")

        assert abort_response.status_code == 200
        assert abort_response.json() == {"aborted": False}
