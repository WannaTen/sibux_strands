"""Configuration loading and merging for Sibux.

Loads config from (in order of increasing precedence):
  1. Built-in defaults
  2. Global config at ~/.config/sibux/config.json
  3. Project config at .sibux/config.json (found by walking up from cwd)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..permission.permission import PermissionRule

logger = logging.getLogger(__name__)

_GLOBAL_CONFIG_DIR = Path.home() / ".config" / "sibux"
_PROJECT_CONFIG_NAME = "config.json"
_PROJECT_CONFIG_DIR = ".sibux"


class ProviderConfig(BaseModel):
    """Configuration for a model provider (credentials only).

    Attributes:
        api_key: API key for the provider.
        base_url: Optional custom base URL (e.g., for proxies or local servers).
        headers: Additional HTTP headers to send with every request (e.g., User-Agent).
    """

    api_key: str | None = None
    base_url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)


class ModelConfig(BaseModel):
    """Configuration for a named model.

    Defines a reusable model reference with its parameters. Agents and
    default_model can reference this by name instead of repeating the
    provider/model string and parameters everywhere.

    Attributes:
        model: Model reference in "provider/model_id" format (required).
        temperature: Sampling temperature.
        max_tokens: Maximum output tokens.
        top_p: Nucleus sampling parameter.
        top_k: Top-k sampling parameter.
        extra: Additional provider-specific parameters.
    """

    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    """Configuration for a named agent.

    Attributes:
        name: Unique identifier for the agent.
        mode: "primary" agents are user-facing; "subagent" agents are called via
            the task tool. The task tool refuses to call primary agents.
        permission: Ordered list of permission rules. Evaluated with
            last-match-wins semantics.
        model: Model reference in "provider/model" format (e.g., "anthropic/claude-opus-4-5").
            Falls back to the default model when None.
        prompt: Agent-specific system prompt fragment appended after base prompt.
        temperature: Sampling temperature override.
        max_tokens: Maximum output tokens override.
    """

    name: str
    mode: str = "primary"
    permission: list[PermissionRule] = Field(default_factory=list)
    model: str | None = None
    prompt: str = ""
    temperature: float | None = None
    max_tokens: int | None = None


class Config(BaseModel):
    """Top-level application configuration.

    Attributes:
        provider: Provider credentials keyed by provider_id (e.g., "anthropic").
        model: Named model configurations keyed by a short alias (e.g., "sonnet").
            Each entry combines a "provider/model_id" string with optional params.
        agents: Named agent configurations.
        default_agent: Name of the agent used when none is specified.
        default_model: Name of a key in ``model``, or a direct "provider/model_id"
            string. Used when an agent has no model set.
        instructions: List of file paths whose contents are appended to the
            system prompt as project-level instructions.
        permission: Global permission rules applied before agent-level rules.
    """

    provider: dict[str, ProviderConfig] = Field(default_factory=dict)
    model: dict[str, ModelConfig] = Field(default_factory=dict)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    default_agent: str = "build"
    default_model: str | None = None
    instructions: list[str] = Field(default_factory=list)
    permission: list[PermissionRule] = Field(default_factory=list)


def load_config(cwd: str | None = None) -> Config:
    """Load and merge configuration from all config file locations.

    Args:
        cwd: Working directory to start searching for project config. Defaults
            to the process current working directory.

    Returns:
        Merged Config object.
    """
    from .defaults import default_config_dict

    merged: dict[str, Any] = default_config_dict()

    global_path = _GLOBAL_CONFIG_DIR / _PROJECT_CONFIG_NAME
    if global_path.exists():
        logger.debug("path=<%s> | loading global config", global_path)
        _merge_into(merged, _load_json(global_path))

    project_path = _find_project_config(cwd or os.getcwd())
    if project_path:
        logger.debug("path=<%s> | loading project config", project_path)
        _merge_into(merged, _load_json(project_path))

    return Config.model_validate(merged)


def _find_project_config(start: str) -> Path | None:
    """Walk up the directory tree looking for a .sibux/config.json file.

    Args:
        start: Directory to start searching from.

    Returns:
        Path to the config file, or None if not found.
    """
    current = Path(start).resolve()
    while True:
        candidate = current / _PROJECT_CONFIG_DIR / _PROJECT_CONFIG_NAME
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file, returning an empty dict on failure.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed dict, or empty dict if the file cannot be read or parsed.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return dict(data)
    except Exception as exc:
        logger.warning("path=<%s>, error=<%s> | failed to load config file", path, exc)
        return {}


def _merge_into(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Deep-merge override into base in place.

    - Dicts are merged recursively.
    - "agents", "model", and "instructions" are merged specially: dicts by key
      (override wins per entry), lists by concatenation with deduplication.
    - All other values in override replace those in base.

    Args:
        base: The dict to merge into (modified in place).
        override: The dict whose values take precedence.
    """
    for key, value in override.items():
        if key in ("agents", "model") and isinstance(value, dict) and isinstance(base.get(key), dict):
            # Merge keyed configs; override wins per-entry
            for entry_name, entry_cfg in value.items():
                if entry_name in base[key] and isinstance(entry_cfg, dict):
                    base[key][entry_name].update(entry_cfg)
                else:
                    base[key][entry_name] = entry_cfg
        elif key == "instructions" and isinstance(value, list) and isinstance(base.get("instructions"), list):
            # Concatenate, preserving order and avoiding duplicates
            existing = set(base["instructions"])
            base["instructions"] = base["instructions"] + [v for v in value if v not in existing]
        elif isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge_into(base[key], value)
        else:
            base[key] = value
