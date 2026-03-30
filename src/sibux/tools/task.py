"""Task tool for delegating work to subagents."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from strands import tool

if TYPE_CHECKING:
    from ..config.config import Config

logger = logging.getLogger(__name__)

# Module-level config reference injected by agent_factory before agent creation.
_task_config: Config | None = None


def set_task_config(config: Config) -> None:
    """Inject the active Config into the task tool.

    Called by agent_factory.create() before building a Strands Agent so that
    the task tool can create subagents using the same configuration.

    Args:
        config: The loaded application config.
    """
    global _task_config
    _task_config = config


@tool
def task(agent: str, prompt: str, description: str) -> dict[str, Any]:
    """Delegate a sub-task to a specialised subagent.

    Use this tool to hand off focused, self-contained tasks to agents with
    narrower capabilities (e.g., "explore" for read-only code search, "general"
    for multi-step implementation work).

    Args:
        agent: Name of the subagent to use (e.g., "explore", "general"). Must
            have mode="subagent" in the configuration.
        prompt: Detailed instructions for the subagent.
        description: Short description of the task (used for logging).

    Returns:
        A dict with status and the subagent's final response text.
    """
    # Import here to avoid circular imports (agent_factory imports task)
    from ..agent.agent_factory import create as create_agent

    if _task_config is None:
        return {
            "status": "error",
            "content": [{"text": "task tool not initialised: config not set"}],
        }

    cfg = _task_config
    if agent not in cfg.agents:
        available = ", ".join(cfg.agents.keys())
        return {
            "status": "error",
            "content": [{"text": f"Unknown agent '{agent}'. Available subagents: {available}"}],
        }

    agent_config = cfg.agents[agent]
    if agent_config.mode != "subagent":
        return {
            "status": "error",
            "content": [
                {"text": f"Agent '{agent}' has mode='{agent_config.mode}'. Only subagents can be called via task."}
            ],
        }

    logger.debug("agent=<%s>, description=<%s> | delegating task to subagent", agent, description)

    try:
        # Subagents remain stateless in Phase 2 and must not inherit the
        # primary agent's session wiring.
        sub_agent = create_agent(config=cfg, agent_config=agent_config)
        result = sub_agent(prompt)
        response_text = result.message if hasattr(result, "message") else str(result)
        return {"status": "success", "content": [{"text": response_text}]}
    except Exception as exc:
        logger.warning("agent=<%s>, error=<%s> | subagent task failed", agent, exc)
        return {"status": "error", "content": [{"text": str(exc)}]}
