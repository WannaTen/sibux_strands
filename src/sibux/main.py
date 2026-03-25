"""CLI entry point for Sibux coding agent.

Starts an interactive REPL session using the configured default agent.
"""

from __future__ import annotations

import logging
import sys

from .agent.agent_factory import create
from .config.config import load_config

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
    resolved_model = agent_config.model or config.default_model
    print(f"model: {resolved_model}")
    agent = create(config, agent_config)

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

        try:
            result = agent(user_input)
            print(f"\n[stop_reason: {result.stop_reason}]")
        except KeyboardInterrupt:
            print("\n[interrupted]")
        except Exception as exc:
            import traceback

            traceback.print_exc()
            print(f"Error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
