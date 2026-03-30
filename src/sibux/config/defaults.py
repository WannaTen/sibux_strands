"""Built-in default configuration for Sibux.

Defines the three built-in agents and their permission rules.

Example full config with provider and model options:

    {
        "provider": {
            "anthropic": {"api_key": "sk-..."}
        },
        "model": {
            "opus":   {"model": "anthropic/claude-opus-4-5",   "max_tokens": 8192},
            "sonnet": {"model": "anthropic/claude-sonnet-4-5", "max_tokens": 8192}
        },
        "default_model": "sonnet",
        "agents": {
            "build": {"model": "opus", "temperature": 0.8}
        }
    }
"""

from typing import Any


def default_config_dict() -> dict[str, Any]:
    """Return the built-in default configuration as a plain dict.

    Returns:
        Dict matching the Config schema with sensible defaults for all three
        built-in agents (build, explore, general).
    """
    return {
        "default_agent": "build",
        "provider": {},
        "model": {},
        "instructions": [],
        "permission": [],
        "session": {
            "storage_dir": ".sibux/session/strands",
            "resume": "last",
        },
        "default_model": None,
        "agents": {
            "build": {
                "name": "build",
                "mode": "primary",
                "prompt": (
                    "You are an expert software engineering assistant. "
                    "You can read, write, and execute code to help users build software. "
                    "Be concise, precise, and prefer minimal changes that achieve the goal."
                ),
                "permission": [
                    {"permission": "*", "pattern": "*", "action": "allow"},
                ],
            },
            "explore": {
                "name": "explore",
                "mode": "subagent",
                "prompt": (
                    "You are a code exploration specialist. "
                    "Your role is to search and understand code — never modify files. "
                    "Use grep, glob, and read to gather information efficiently."
                ),
                "permission": [
                    {"permission": "*", "pattern": "*", "action": "deny"},
                    {"permission": "grep", "pattern": "*", "action": "allow"},
                    {"permission": "glob_tool", "pattern": "*", "action": "allow"},
                    {"permission": "read", "pattern": "*", "action": "allow"},
                    {"permission": "bash", "pattern": "*", "action": "allow"},
                ],
            },
            "general": {
                "name": "general",
                "mode": "subagent",
                "prompt": (
                    "You are a general-purpose coding assistant. "
                    "Complete the assigned task efficiently and report results clearly."
                ),
                "permission": [
                    {"permission": "*", "pattern": "*", "action": "allow"},
                    {"permission": "task", "pattern": "*", "action": "deny"},
                ],
            },
        },
    }
