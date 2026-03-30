"""Tests for the config loading and merging logic."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from sibux.config.config import _merge_into, find_project_root, load_config, validate_agent_name
from sibux.config.defaults import default_config_dict


class TestDefaultConfig:
    def test_default_has_three_agents(self) -> None:
        d = default_config_dict()
        assert set(d["agents"].keys()) == {"build", "explore", "general"}

    def test_default_has_session_config(self) -> None:
        d = default_config_dict()
        assert d["session"]["storage_dir"] == ".sibux/session/strands"
        assert d["session"]["resume"] == "last"

    def test_build_agent_is_primary(self) -> None:
        d = default_config_dict()
        assert d["agents"]["build"]["mode"] == "primary"

    def test_explore_agent_is_subagent(self) -> None:
        d = default_config_dict()
        assert d["agents"]["explore"]["mode"] == "subagent"

    def test_general_agent_is_subagent(self) -> None:
        d = default_config_dict()
        assert d["agents"]["general"]["mode"] == "subagent"


class TestMergeInto:
    def test_simple_override(self) -> None:
        base: dict[str, Any] = {"a": 1, "b": 2}
        _merge_into(base, {"b": 99})
        assert base == {"a": 1, "b": 99}

    def test_nested_dict_deep_merge(self) -> None:
        base: dict[str, Any] = {"provider": {"anthropic": {"api_key": "old"}}}
        _merge_into(base, {"provider": {"anthropic": {"base_url": "http://x"}}})
        assert base["provider"]["anthropic"]["api_key"] == "old"
        assert base["provider"]["anthropic"]["base_url"] == "http://x"

    def test_instructions_concatenated(self) -> None:
        base: dict[str, Any] = {"instructions": ["a.md"]}
        _merge_into(base, {"instructions": ["b.md", "a.md"]})
        # "a.md" is a duplicate and should not be repeated
        assert base["instructions"] == ["a.md", "b.md"]

    def test_agents_merged_by_key(self) -> None:
        base: dict[str, Any] = {"agents": {"build": {"mode": "primary", "prompt": "old"}}}
        _merge_into(base, {"agents": {"build": {"prompt": "new"}, "custom": {"mode": "subagent"}}})
        assert base["agents"]["build"]["prompt"] == "new"
        assert base["agents"]["build"]["mode"] == "primary"
        assert base["agents"]["custom"]["mode"] == "subagent"

    def test_model_dict_merged_by_key(self) -> None:
        base: dict[str, Any] = {"model": {"sonnet": {"model": "anthropic/claude-sonnet-4-5", "max_tokens": 8192}}}
        _merge_into(base, {"model": {"sonnet": {"max_tokens": 4096}, "haiku": {"model": "anthropic/claude-haiku-3-5"}}})
        assert base["model"]["sonnet"]["model"] == "anthropic/claude-sonnet-4-5"
        assert base["model"]["sonnet"]["max_tokens"] == 4096
        assert base["model"]["haiku"]["model"] == "anthropic/claude-haiku-3-5"


class TestHelpers:
    def test_find_project_root_returns_project_root_from_nested_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sibux_dir = tmp_path / ".sibux"
        sibux_dir.mkdir()
        (sibux_dir / "config.json").write_text(json.dumps({"default_agent": "explore"}))

        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        assert find_project_root() == tmp_path.resolve()
        assert find_project_root(nested) == tmp_path.resolve()

    def test_find_project_root_returns_start_when_no_project_config(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)

        assert find_project_root(nested) == nested.resolve()

    def test_validate_agent_name_rejects_path_separators(self) -> None:
        with pytest.raises(ValueError, match="agent_id=review/build \\| id cannot contain path separators"):
            validate_agent_name("review/build")

    def test_validate_agent_name_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError, match="agent name must be a non-empty, non-whitespace string"):
            validate_agent_name("")

    def test_validate_agent_name_rejects_whitespace_only_string(self) -> None:
        with pytest.raises(ValueError, match="agent name must be a non-empty, non-whitespace string"):
            validate_agent_name("   ")


class TestLoadConfig:
    def test_load_defaults_when_no_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        # Point global config dir to a non-existent path
        monkeypatch.setattr("sibux.config.config._GLOBAL_CONFIG_DIR", tmp_path / "nonexistent")
        config = load_config(str(tmp_path))
        assert config.default_agent == "build"
        assert "build" in config.agents
        assert "explore" in config.agents
        assert config.session.storage_dir == ".sibux/session/strands"
        assert config.session.resume == "last"

    def test_project_config_overrides_default_agent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sibux.config.config._GLOBAL_CONFIG_DIR", tmp_path / "nonexistent")

        sibux_dir = tmp_path / ".sibux"
        sibux_dir.mkdir()
        (sibux_dir / "config.json").write_text(json.dumps({"default_agent": "explore"}))

        config = load_config(str(tmp_path))
        assert config.default_agent == "explore"
        assert config.session.storage_dir == ".sibux/session/strands"
        assert config.session.resume == "last"

    def test_project_config_adds_custom_agent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sibux.config.config._GLOBAL_CONFIG_DIR", tmp_path / "nonexistent")

        sibux_dir = tmp_path / ".sibux"
        sibux_dir.mkdir()
        (sibux_dir / "config.json").write_text(
            json.dumps(
                {
                    "agents": {
                        "reviewer": {
                            "name": "reviewer",
                            "mode": "subagent",
                            "prompt": "Review code.",
                            "permission": [{"permission": "read", "action": "allow"}],
                        }
                    }
                }
            )
        )

        config = load_config(str(tmp_path))
        assert "reviewer" in config.agents
        assert "build" in config.agents  # defaults preserved

    def test_project_config_found_in_parent_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sibux.config.config._GLOBAL_CONFIG_DIR", tmp_path / "nonexistent")
        sibux_dir = tmp_path / ".sibux"
        sibux_dir.mkdir()
        (sibux_dir / "config.json").write_text(json.dumps({"default_agent": "explore"}))

        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        config = load_config(str(nested))
        assert config.default_agent == "explore"

    def test_global_config_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        global_dir = tmp_path / "global_config"
        global_dir.mkdir()
        (global_dir / "config.json").write_text(json.dumps({"default_agent": "general"}))
        monkeypatch.setattr("sibux.config.config._GLOBAL_CONFIG_DIR", global_dir)

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        monkeypatch.chdir(work_dir)

        config = load_config(str(work_dir))
        assert config.default_agent == "general"

    def test_project_config_overrides_session_resume(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sibux.config.config._GLOBAL_CONFIG_DIR", tmp_path / "nonexistent")

        sibux_dir = tmp_path / ".sibux"
        sibux_dir.mkdir()
        (sibux_dir / "config.json").write_text(json.dumps({"session": {"resume": "new"}}))

        config = load_config(str(tmp_path))
        assert config.session.resume == "new"
        assert config.session.storage_dir == ".sibux/session/strands"

    def test_project_config_overrides_session_storage_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sibux.config.config._GLOBAL_CONFIG_DIR", tmp_path / "nonexistent")

        sibux_dir = tmp_path / ".sibux"
        sibux_dir.mkdir()
        (sibux_dir / "config.json").write_text(json.dumps({"session": {"storage_dir": ".custom/session"}}))

        config = load_config(str(tmp_path))
        assert config.session.storage_dir == ".custom/session"
        assert config.session.resume == "last"

    def test_global_config_overrides_session_resume(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        global_dir = tmp_path / "global_config"
        global_dir.mkdir()
        (global_dir / "config.json").write_text(json.dumps({"session": {"resume": "new"}}))
        monkeypatch.setattr("sibux.config.config._GLOBAL_CONFIG_DIR", global_dir)

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        monkeypatch.chdir(work_dir)

        config = load_config(str(work_dir))
        assert config.session.resume == "new"
        assert config.session.storage_dir == ".sibux/session/strands"

    def test_invalid_agent_name_fails_config_validation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sibux.config.config._GLOBAL_CONFIG_DIR", tmp_path / "nonexistent")

        sibux_dir = tmp_path / ".sibux"
        sibux_dir.mkdir()
        (sibux_dir / "config.json").write_text(
            json.dumps(
                {
                    "agents": {
                        "review/build": {
                            "name": "review/build",
                            "mode": "subagent",
                            "prompt": "Review code.",
                        }
                    }
                }
            )
        )

        with pytest.raises(ValidationError, match="agent_id=review/build \\| id cannot contain path separators"):
            load_config(str(tmp_path))

    def test_empty_agent_name_fails_config_validation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sibux.config.config._GLOBAL_CONFIG_DIR", tmp_path / "nonexistent")

        sibux_dir = tmp_path / ".sibux"
        sibux_dir.mkdir()
        (sibux_dir / "config.json").write_text(
            json.dumps(
                {
                    "agents": {
                        "broken": {
                            "name": "",
                            "mode": "subagent",
                            "prompt": "Broken agent.",
                        }
                    }
                }
            )
        )

        with pytest.raises(ValidationError, match="agent name must be a non-empty, non-whitespace string"):
            load_config(str(tmp_path))

    def test_whitespace_agent_name_fails_config_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sibux.config.config._GLOBAL_CONFIG_DIR", tmp_path / "nonexistent")

        sibux_dir = tmp_path / ".sibux"
        sibux_dir.mkdir()
        (sibux_dir / "config.json").write_text(
            json.dumps(
                {
                    "agents": {
                        "broken": {
                            "name": "   ",
                            "mode": "subagent",
                            "prompt": "Broken agent.",
                        }
                    }
                }
            )
        )

        with pytest.raises(ValidationError, match="agent name must be a non-empty, non-whitespace string"):
            load_config(str(tmp_path))
