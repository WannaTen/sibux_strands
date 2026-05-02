"""CLI entry point for Sibux coding agent.

Starts an interactive REPL session using the configured default agent.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import TYPE_CHECKING

import strands
from strands.agent.agent_result import AgentResult

from .agent.agent_factory import create
from .config.config import load_config
from .event import Bus, GlobalBus
from .event.stream import StreamEventMapper
from .session import ActiveSession, SessionService

if TYPE_CHECKING:
    from .config.config import AgentConfig, Config

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the Sibux interactive REPL.

    Loads configuration, creates the default agent, and starts an input loop.
    Type 'exit', 'quit', or '/exit' to stop.
    """
    log_level = logging.DEBUG if "--debug" in sys.argv else logging.WARNING
    logging.basicConfig(level=log_level, format="%(levelname)s %(name)s: %(message)s")

    config = load_config()

    agent_name = config.default_agent
    if agent_name not in config.agents:
        print(f"Error: default agent '{agent_name}' not found in config", file=sys.stderr)
        sys.exit(1)

    agent_config = config.agents[agent_name]
    if agent_config.mode != "primary":
        print(f"Error: default agent '{agent_name}' must have mode='primary'", file=sys.stderr)
        sys.exit(1)

    global_bus = GlobalBus()
    session_service = SessionService(
        storage_dir=config.session.storage_dir,
        resume=config.session.resume,
        global_bus=global_bus,
    )
    active_session = session_service.create_or_resume(agent_name=agent_name)

    if active_session.restore_error:
        print(f"session restore failed: {active_session.restore_error}")

    resolved_model = _resolve_configured_model_id(config, agent_config)
    print(f"model: {resolved_model}")
    _print_session_banner(active_session)

    bus = _create_session_bus(active_session, global_bus)
    agent = _create_primary_agent(config, agent_config, active_session)

    print(f"Sibux [{agent_name}]  (type 'exit' to quit)\n")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input in ("exit", "quit", "/exit"):
            break
        if user_input == "/new":
            active_session = session_service.new_session(agent_name=agent_name)
            _print_session_banner(active_session)
            bus = _create_session_bus(active_session, global_bus)
            agent = _create_primary_agent(config, agent_config, active_session)
            continue
        if user_input == "/session":
            _print_session_details(active_session)
            continue

        try:
            result = asyncio.run(_stream_agent_prompt(agent, bus, user_input))
            print(f"\n[stop_reason: {result.stop_reason}]")
        except KeyboardInterrupt:
            print("\n[interrupted]")
        except Exception as exc:
            import traceback

            traceback.print_exc()
            print(f"Error: {exc}", file=sys.stderr)


def _create_primary_agent(config: Config, agent_config: AgentConfig, active_session: ActiveSession) -> strands.Agent:
    """Create the session-backed primary Strands agent."""
    return create(
        config,
        agent_config,
        session_manager=active_session.session_manager,
        agent_id=active_session.agent_id,
    )


def _resolve_configured_model_id(config: Config, agent_config: AgentConfig) -> str | None:
    """Resolve the configured downstream model id for display."""
    model_ref = agent_config.model or config.default_model
    if model_ref is None:
        return None

    model_config = config.model.get(model_ref)
    if model_config is None:
        return None

    return model_config.model


def _create_session_bus(active_session: ActiveSession, global_bus: GlobalBus) -> Bus:
    """Create the per-session bus used by the current CLI session."""
    return Bus(active_session.session_id, global_bus=global_bus)


async def _stream_agent_prompt(agent: strands.Agent, bus: Bus, prompt: str) -> AgentResult:
    """Run one prompt through ``stream_async()`` and publish mapped bus events."""
    result: AgentResult | None = None
    model_config = getattr(getattr(agent, "model", None), "config", None)
    model_id = model_config.get("model_id") if isinstance(model_config, dict) else None
    mapper = StreamEventMapper(bus.session_id, model_id=model_id)

    async for stream_event in agent.stream_async(prompt):
        for bus_event in mapper.map_event(stream_event):
            bus.publish(bus_event)

        stream_result = stream_event.get("result")
        if isinstance(stream_result, AgentResult):
            result = stream_result

    if result is None:
        raise RuntimeError("agent stream completed without a result event")

    return result


def _print_session_banner(active_session: ActiveSession) -> None:
    """Print a compact startup or session-switch summary."""
    print(f"session: {active_session.session_id} ({'resumed' if active_session.resumed else 'new'})")
    print(f"storage: {active_session.storage_dir}")


def _print_session_details(active_session: ActiveSession) -> None:
    """Print the current session details for the `/session` command."""
    print(f"session_id: {active_session.session_id}")
    print(f"agent_name: {active_session.agent_name}")
    print(f"storage_dir: {active_session.storage_dir}")


if __name__ == "__main__":
    main()
