# Sibux Project Instructions

## Project Overview

This is the Sibux coding agent built on the [Strands Agents](https://strandsagents.com/) SDK.
The agent lives under `src/sibux/` and is configured via `.sibux/config.json`.

## Directory Structure

```
src/sibux/
├── agent/
│   ├── agent_factory.py    # Creates Strands Agent from AgentConfig
│   └── system_prompt.py    # Builds layered system prompt
├── config/
│   ├── config.py           # Pydantic config models + load_config()
│   └── defaults.py         # Built-in agent definitions
├── session/
│   ├── __init__.py         # Session lifecycle exports
│   └── service.py          # Project-local session create/resume logic
├── permission/
│   └── permission.py       # Last-match-wins rule evaluation + tool filtering
├── tools/
│   ├── bash.py             # Shell command execution
│   ├── read.py             # File reading with offset/limit
│   ├── edit.py             # Find-and-replace editing
│   ├── write.py            # File writing
│   ├── glob_tool.py        # Path pattern matching
│   ├── grep.py             # Content search
│   ├── task.py             # Subagent delegation
│   └── truncation.py       # Output size limiting
└── main.py                 # CLI REPL entry point
```

## Development

```bash
./scripts/setup-dev.sh             # Install dev deps + Git hooks
pre-commit run --all-files         # Run hooks manually
uv run sibux                      # Run the agent
uv run pytest tests/sibux/        # Run unit tests
uv run ruff format src/sibux/     # Format
uv run ruff check src/sibux/      # Lint
uv run mypy src/sibux/            # Type check
```

## Key Design Decisions

- **Config format**: Models are `"provider/model_id"` strings (e.g., `"anthropic/claude-sonnet-4-5"`).
- **Permission system**: Last-match-wins; default is allow-all if no rules set.
- **System prompt order**: agent prompt → project instructions → environment context.
- **Tool filtering**: Applied at agent construction time from permission rules.
- **Subagents**: `mode: "subagent"` agents can only be called via the `task` tool.

## Coding Guidelines

Follow patterns from the root `AGENTS.md`. Additional sibux-specific rules:

- Keep tool implementations simple and self-contained in their own files.
- Config loading must remain pure (no side effects beyond reading files).
- Agent factory must not import provider SDKs at module level (lazy imports only).
- Tests live in `tests/sibux/` mirroring the `src/sibux/` structure.
