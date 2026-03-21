"""System prompt construction for Sibux agents.

Builds a layered system prompt from:
  1. Environment information (cwd, platform, date, shell)
  2. Project instructions (AGENTS.md, CLAUDE.md, config.instructions paths)
  3. Agent-specific prompt fragment
"""

from __future__ import annotations

import logging
import os
import platform
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config.config import AgentConfig, Config

logger = logging.getLogger(__name__)

_INSTRUCTION_FILENAMES = ["AGENTS.md", "CLAUDE.md", "OPENCODE.md"]

# ComMent: system prompt 这里需要的结构是： agentconfig.prompt + instruction + environment
def build_system_prompt(agent_config: AgentConfig, config: Config) -> str:
    """Build the full system prompt for an agent invocation.

    Args:
        agent_config: Configuration of the agent being invoked.
        config: Application-level configuration.

    Returns:
        Concatenated system prompt string.
    """
    parts: list[str] = []

    # ComMent: agent prompt first
    if agent_config.prompt:
        parts.append(agent_config.prompt)

    # ComMent: instructions second
    instructions = _load_instructions(config)
    if instructions:
        parts.append(instructions)

    # ComMent: environment last
    env_section = _build_environment_section()
    if env_section:
        parts.append(env_section)

    return "\n\n".join(parts)


def _build_environment_section() -> str:
    """Build the environment context section of the system prompt.

    Returns:
        A markdown-formatted string with cwd, platform, date and shell.
    """
    cwd = os.getcwd()
    shell = os.environ.get("SHELL", "/bin/sh")
    today = datetime.now().strftime("%Y-%m-%d")
    system = platform.system()

    return f"## Environment\n- Working directory: {cwd}\n- Platform: {system}\n- Date: {today}\n- Shell: {shell}"

# ComMent: 这里是不是只需要有一个文件来指定所有的 instructions？
def _load_instructions(config: Config) -> str:
    """Load project instructions from well-known files and config paths.

    Scans the current directory for AGENTS.md / CLAUDE.md / OPENCODE.md and
    then loads any additional paths listed in config.instructions.

    Args:
        config: Application configuration.

    Returns:
        Concatenated instruction content, or empty string if none found.
    """
    sections: list[str] = []
    cwd = Path(os.getcwd())

    for filename in _INSTRUCTION_FILENAMES:
        candidate = cwd / filename
        if candidate.exists():
            content = _read_file(candidate)
            if content:
                logger.debug("path=<%s> | loaded instruction file", candidate)
                sections.append(content)

    for path_str in config.instructions:
        path = Path(path_str)
        if not path.is_absolute():
            path = cwd / path
        content = _read_file(path)
        if content:
            logger.debug("path=<%s> | loaded instruction file from config", path)
            sections.append(content)

    return "\n\n".join(sections)


def _read_file(path: Path) -> str:
    """Read a text file, returning empty string on failure.

    Args:
        path: Path to the file.

    Returns:
        File contents or empty string.
    """
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("path=<%s>, error=<%s> | failed to read instruction file", path, exc)
        return ""
