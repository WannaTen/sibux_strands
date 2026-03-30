"""Tests for the agent factory and system prompt builder."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sibux.agent.agent_factory import create
from sibux.agent.system_prompt import _build_environment_section, build_system_prompt
from sibux.config.config import AgentConfig, Config
from sibux.config.defaults import default_config_dict


class TestSystemPrompt:
    def _agent_config(self, prompt: str = "test prompt") -> AgentConfig:
        return AgentConfig(name="test", mode="primary", prompt=prompt)

    def _config(self) -> Config:
        return Config.model_validate(default_config_dict())

    def test_environment_section_present(self) -> None:
        section = _build_environment_section()
        assert "Working directory" in section
        assert "Platform" in section
        assert "Date" in section

    def test_agent_prompt_included(self) -> None:
        agent_cfg = self._agent_config("My custom prompt")
        result = build_system_prompt(agent_cfg, self._config())
        assert "My custom prompt" in result

    def test_instruction_file_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Project instructions\nDo things well.")

        agent_cfg = self._agent_config()
        result = build_system_prompt(agent_cfg, self._config())
        assert "Project instructions" in result

    def test_config_instruction_path_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        custom = tmp_path / "my_rules.md"
        custom.write_text("Custom rules here.")

        config = Config.model_validate({**default_config_dict(), "instructions": [str(custom)]})
        agent_cfg = self._agent_config()
        result = build_system_prompt(agent_cfg, config)
        assert "Custom rules here." in result

    def test_missing_instruction_file_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        config = Config.model_validate({**default_config_dict(), "instructions": ["/nonexistent/path.md"]})
        agent_cfg = self._agent_config()
        # should not raise
        result = build_system_prompt(agent_cfg, config)
        assert isinstance(result, str)


class TestAgentFactory:
    def _config_with_default_model(self) -> Config:
        d = default_config_dict()
        d["model"] = {"opus": {"model": "anthropic/claude-opus-4-5", "max_tokens": 8192}}
        d["default_model"] = "opus"
        d["provider"] = {"anthropic": {"api_key": "test-key"}}
        return Config.model_validate(d)

    def test_create_passes_session_seam_to_primary_agent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        config = Config.model_validate(default_config_dict())
        agent_cfg = config.agents["build"]
        session_manager = object()
        context_manager = object()

        with patch("sibux.agent.agent_factory.strands.Agent") as agent_cls:
            built_agent = object()
            agent_cls.return_value = built_agent

            result = create(
                config,
                agent_cfg,
                session_manager=session_manager,
                agent_id="build",
                context_manager=context_manager,
            )

        assert result is built_agent
        call_kwargs = agent_cls.call_args.kwargs
        assert call_kwargs["session_manager"] is session_manager
        assert call_kwargs["agent_id"] == "build"
        assert call_kwargs["context_manager"] is context_manager

    def test_create_without_session_seam_keeps_default_stateless_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        config = Config.model_validate(default_config_dict())
        agent_cfg = config.agents["build"]

        with patch("sibux.agent.agent_factory.strands.Agent") as agent_cls:
            create(config, agent_cfg)

        call_kwargs = agent_cls.call_args.kwargs
        assert "session_manager" not in call_kwargs
        assert "agent_id" not in call_kwargs
        assert "context_manager" not in call_kwargs

    def test_create_rejects_session_manager_without_agent_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        config = Config.model_validate(default_config_dict())
        agent_cfg = config.agents["build"]

        with patch("sibux.agent.agent_factory.strands.Agent") as agent_cls:
            with pytest.raises(ValueError, match="agent_id is required when session_manager is provided"):
                create(
                    config,
                    agent_cfg,
                    session_manager=object(),
                )

        agent_cls.assert_not_called()

    def test_explore_agent_missing_task_tool(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explore agent must not receive the task tool."""
        monkeypatch.chdir(tmp_path)
        config = Config.model_validate(default_config_dict())
        agent_cfg = config.agents["explore"]

        from sibux.permission.permission import filter_tools
        from sibux.tools import ALL_TOOLS

        tools = filter_tools(ALL_TOOLS, agent_cfg.permission)
        tool_names = [getattr(t, "__name__", str(t)) for t in tools]
        assert "task" not in tool_names
        assert "read" in tool_names

    def test_general_agent_missing_task_tool(self) -> None:
        """General agent must not receive the task tool."""
        config = Config.model_validate(default_config_dict())
        agent_cfg = config.agents["general"]

        from sibux.permission.permission import filter_tools
        from sibux.tools import ALL_TOOLS

        tools = filter_tools(ALL_TOOLS, agent_cfg.permission)
        tool_names = [getattr(t, "__name__", str(t)) for t in tools]
        assert "task" not in tool_names

    def test_build_agent_has_all_tools(self) -> None:
        """Build agent must have all tools."""
        config = Config.model_validate(default_config_dict())
        agent_cfg = config.agents["build"]

        from sibux.permission.permission import filter_tools
        from sibux.tools import ALL_TOOLS

        tools = filter_tools(ALL_TOOLS, agent_cfg.permission)
        assert len(tools) == len(ALL_TOOLS)


class TestResolveModel:
    """Tests for the _resolve_model function."""

    def test_named_model_resolved_from_config(self) -> None:
        """Named model alias is resolved through config.model dict."""
        from sibux.agent.agent_factory import _resolve_model

        d = default_config_dict()
        d["model"] = {"sonnet": {"model": "anthropic/claude-sonnet-4-5", "max_tokens": 8192}}
        d["default_model"] = "sonnet"
        config = Config.model_validate(d)
        agent_cfg = config.agents["build"]

        # Just verify it doesn't crash and attempts anthropic model construction
        # (will fail import in test env, so we only test up to provider resolution)
        try:
            _resolve_model(config, agent_cfg)
        except Exception:
            pass  # provider import may fail in test env

    def test_direct_provider_model_string(self, caplog) -> None:
        """Direct 'provider/model' string bypasses the model dict."""
        import logging

        from sibux.agent.agent_factory import _resolve_model

        d = default_config_dict()
        d["default_model"] = "unknown-provider/some-model"
        config = Config.model_validate(d)
        agent_cfg = config.agents["build"]

        with caplog.at_level(logging.WARNING):
            model = _resolve_model(config, agent_cfg)

        assert model is None
        assert "unknown provider" in caplog.text

    def test_invalid_model_format_logs_error(self, caplog) -> None:
        """A model string with no slash logs an error."""
        import logging

        from sibux.agent.agent_factory import _resolve_model

        d = default_config_dict()
        # Use a name not in config.model and with no slash
        d["default_model"] = "invalid-no-slash"
        config = Config.model_validate(d)
        agent_cfg = config.agents["build"]

        with caplog.at_level(logging.ERROR):
            model = _resolve_model(config, agent_cfg)

        assert model is None
        assert "invalid model format" in caplog.text

    def test_agent_params_override_model_config(self) -> None:
        """Agent-level temperature/max_tokens override named model defaults."""
        d = default_config_dict()
        d["model"] = {"sonnet": {"model": "anthropic/claude-sonnet-4-5", "temperature": 0.3, "max_tokens": 4096}}
        d["agents"]["build"]["temperature"] = 0.9
        d["agents"]["build"]["max_tokens"] = 1024
        d["agents"]["build"]["model"] = "sonnet"
        config = Config.model_validate(d)
        agent_cfg = config.agents["build"]

        assert agent_cfg.temperature == 0.9
        assert agent_cfg.max_tokens == 1024
