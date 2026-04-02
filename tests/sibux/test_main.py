"""Tests for the Sibux CLI entry point."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sibux.config.config import Config
from sibux.config.defaults import default_config_dict
from sibux.main import main


def _build_config() -> Config:
    """Create a baseline config for CLI tests."""
    config_dict = default_config_dict()
    config_dict["default_model"] = "anthropic/claude-sonnet-4-5"
    return Config.model_validate(config_dict)


def _active_session(
    *,
    session_id: str = "sibux_test_session",
    resumed: bool = False,
    restore_error: str | None = None,
) -> SimpleNamespace:
    """Build a lightweight active-session stub for CLI tests."""
    return SimpleNamespace(
        session_id=session_id,
        agent_name="build",
        agent_id="build",
        storage_dir=Path("/tmp/test-project/.sibux/session/strands"),
        state_file=Path("/tmp/test-project/.sibux/session/state.json"),
        resumed=resumed,
        session_manager=object(),
        restore_error=restore_error,
    )


class _FakeResult:
    """Simple fake Strands result object for CLI tests."""

    def __init__(self, *, stop_reason: str = "end_turn") -> None:
        self.stop_reason = stop_reason


class _FakeAgent:
    """Minimal callable agent stub that records prompts."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> _FakeResult:
        self.calls.append(prompt)
        return _FakeResult()


class TestMain:
    def test_main_creates_primary_agent_with_session_seam(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = _build_config()
        active_session = _active_session(session_id="sibux_123", resumed=True)
        monkeypatch.setattr("sibux.main.sys.argv", ["sibux"])
        monkeypatch.setattr("builtins.input", lambda _: "exit")

        with (
            patch("sibux.main.load_config", return_value=config) as load_config_mock,
            patch("sibux.main.SessionService") as session_service_cls,
            patch("sibux.main.create", return_value=object()) as create_mock,
        ):
            session_service = session_service_cls.return_value
            session_service.create_or_resume.return_value = active_session

            main()

        stdout = capsys.readouterr().out
        load_config_mock.assert_called_once_with()
        session_service_cls.assert_called_once_with(
            storage_dir=config.session.storage_dir,
            resume=config.session.resume,
        )
        session_service.create_or_resume.assert_called_once_with(agent_name="build")
        create_mock.assert_called_once_with(
            config,
            config.agents["build"],
            session_manager=active_session.session_manager,
            agent_id=active_session.agent_id,
        )
        assert "model: anthropic/claude-sonnet-4-5" in stdout
        assert "session: sibux_123 (resumed)" in stdout
        assert "storage: /tmp/test-project/.sibux/session/strands" in stdout

    def test_main_prints_restore_failure_notice(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = _build_config()
        active_session = _active_session(
            session_id="sibux_new",
            resumed=False,
            restore_error="failed to load previous session state: invalid json",
        )
        monkeypatch.setattr("sibux.main.sys.argv", ["sibux"])
        monkeypatch.setattr("builtins.input", lambda _: "exit")

        with (
            patch("sibux.main.load_config", return_value=config),
            patch("sibux.main.SessionService") as session_service_cls,
            patch("sibux.main.create", return_value=object()),
        ):
            session_service_cls.return_value.create_or_resume.return_value = active_session
            main()

        stdout = capsys.readouterr().out
        assert "session restore failed: failed to load previous session state: invalid json" in stdout
        assert "session: sibux_new (new)" in stdout

    def test_main_rejects_non_primary_default_agent(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = _build_config()
        config.default_agent = "explore"
        monkeypatch.setattr("sibux.main.sys.argv", ["sibux"])

        with patch("sibux.main.load_config", return_value=config):
            with pytest.raises(SystemExit) as exc_info:
                main()

        stderr = capsys.readouterr().err
        assert exc_info.value.code == 1
        assert "Error: default agent 'explore' must have mode='primary'" in stderr

    def test_main_new_command_recreates_primary_agent_with_new_session(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = _build_config()
        first_session = _active_session(session_id="sibux_old", resumed=True)
        second_session = _active_session(session_id="sibux_new", resumed=False)
        first_agent = _FakeAgent()
        second_agent = _FakeAgent()
        inputs = iter(["/new", "continue work", "exit"])
        monkeypatch.setattr("sibux.main.sys.argv", ["sibux"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        with (
            patch("sibux.main.load_config", return_value=config),
            patch("sibux.main.SessionService") as session_service_cls,
            patch("sibux.main.create", side_effect=[first_agent, second_agent]) as create_mock,
        ):
            session_service = session_service_cls.return_value
            session_service.create_or_resume.return_value = first_session
            session_service.new_session.return_value = second_session

            main()

        stdout = capsys.readouterr().out
        session_service.new_session.assert_called_once_with(agent_name="build")
        assert create_mock.call_count == 2
        assert create_mock.call_args_list[0].kwargs["session_manager"] is first_session.session_manager
        assert create_mock.call_args_list[0].kwargs["agent_id"] == first_session.agent_id
        assert create_mock.call_args_list[1].kwargs["session_manager"] is second_session.session_manager
        assert create_mock.call_args_list[1].kwargs["agent_id"] == second_session.agent_id
        assert first_agent.calls == []
        assert second_agent.calls == ["continue work"]
        assert "session: sibux_new (new)" in stdout
        assert "\n[stop_reason: end_turn]" in stdout

    def test_main_session_command_prints_current_session_details(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = _build_config()
        active_session = _active_session(session_id="sibux_456", resumed=True)
        agent = _FakeAgent()
        inputs = iter(["/session", "exit"])
        monkeypatch.setattr("sibux.main.sys.argv", ["sibux"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        with (
            patch("sibux.main.load_config", return_value=config),
            patch("sibux.main.SessionService") as session_service_cls,
            patch("sibux.main.create", return_value=agent),
        ):
            session_service = session_service_cls.return_value
            session_service.create_or_resume.return_value = active_session

            main()

        stdout = capsys.readouterr().out
        assert "session_id: sibux_456" in stdout
        assert "agent_name: build" in stdout
        assert "storage_dir: /tmp/test-project/.sibux/session/strands" in stdout
        assert agent.calls == []

    def test_main_only_exact_session_command_is_treated_as_command(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = _build_config()
        active_session = _active_session(session_id="sibux_789", resumed=True)
        agent = _FakeAgent()
        inputs = iter(["/session now", "exit"])
        monkeypatch.setattr("sibux.main.sys.argv", ["sibux"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        with (
            patch("sibux.main.load_config", return_value=config),
            patch("sibux.main.SessionService") as session_service_cls,
            patch("sibux.main.create", return_value=agent),
        ):
            session_service_cls.return_value.create_or_resume.return_value = active_session
            main()

        stdout = capsys.readouterr().out
        assert agent.calls == ["/session now"]
        assert "session_id:" not in stdout
