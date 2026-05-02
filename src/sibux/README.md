# Sibux

A general-purpose coding agent built on the [Strands Agents](https://strandsagents.com/) SDK.

## Quick Start

```bash
# Install
uv sync

# Set API key
export ANTHROPIC_API_KEY=sk-...

# Create project config
mkdir .sibux && cat > .sibux/config.json << 'EOF'
{
  "default_model": "sonnet",
  "model": {
    "sonnet": {
      "provider": "anthropic",
      "model": "claude-sonnet-4-5"
    }
  }
}
EOF

# Run
uv run sibux
```

## Development Setup

For a fresh clone of this repository, run the bootstrap script from the repository root:

```bash
./scripts/setup-dev.sh
```

The script:

- Syncs the development dependencies with `uv`
- Installs the `pre-commit` and `commit-msg` Git hooks
- Sets repository-local Git settings needed for development

After it completes, `git commit` automatically runs the configured checks for this repository, including `ruff format --check`, `ruff check`, `mypy ./src`, `pytest`, and commit message validation.

Common examples:

```bash
# Basic setup
./scripts/setup-dev.sh

# Run the hooks once after setup
./scripts/setup-dev.sh --verify

# Configure repository-local Git identity at the same time
./scripts/setup-dev.sh --git-user-name "Jane Doe" --git-user-email "jane@example.com"
```

The script requires `git` and `uv` to be available on your machine.

## Configuration

Config is loaded and merged in order (later sources win):

1. Built-in defaults
2. `~/.config/sibux/config.json` (global)
3. `.sibux/config.json` (project, found by walking up from cwd)

### Minimal config

```json
{
  "default_model": "sonnet",
  "model": {
    "sonnet": {
      "provider": "anthropic",
      "model": "claude-sonnet-4-5"
    }
  }
}
```

### Full config reference

```json
{
  "default_model": "sonnet",
  "default_agent": "build",
  "provider": {
    "anthropic": {
      "api_key": "sk-..."
    },
    "openai": {
      "api_key": "sk-...",
      "base_url": "https://api.openai.com/v1"
    }
  },
  "model": {
    "sonnet": {
      "provider": "anthropic",
      "model": "claude-sonnet-4-5",
      "max_tokens": 32000
    },
    "opus": {
      "provider": "anthropic",
      "model": "claude-opus-4-5",
      "max_tokens": 32000
    },
    "gpt4o": {
      "provider": "openai",
      "model": "gpt-4o"
    }
  },
  "agents": {
    "build": {
      "model": "opus",
      "temperature": 0.8
    }
  }
}
```

### Model format

Models are named aliases under `model`. Each alias has a `provider` and a `model`; the `model` value is passed directly to the downstream provider as `model_id`.

| Provider | Example |
|----------|---------|
| `anthropic` | `{"provider": "anthropic", "model": "claude-sonnet-4-5"}` |
| `openai` | `{"provider": "openai", "model": "gpt-4o"}` |
| `openai-compatible` | `{"provider": "openai-compatible", "model": "my-model"}` |
| `bedrock` | `{"provider": "bedrock", "model": "anthropic.claude-3-5-sonnet-20241022-v2:0"}` |
| `ollama` | `{"provider": "ollama", "model": "llama3.2"}` |
| `litellm` | `{"provider": "litellm", "model": "openai/gpt-4o"}` |

## Built-in Agents

Three agents are included by default.

**build** (default) — Full access to all tools. Designed for software engineering tasks.

**explore** — Read-only subagent. Can use `read`, `grep`, `glob`, and `bash` but cannot write files. Used via the `task` tool.

**general** — Full-access subagent without the `task` tool (prevents recursive delegation). Used for standalone subtasks.

### Switching agents

Change the active agent via `default_agent` in config:

```json
{
  "default_agent": "explore"
}
```

### Custom agents

Add custom agents under `agents`. The `model`, `temperature`, and `max_tokens` fields override defaults.

```json
{
  "agents": {
    "reviewer": {
      "name": "reviewer",
      "mode": "primary",
      "model": "haiku",
      "prompt": "You are a code reviewer. Be concise and direct.",
      "permission": [
        {"permission": "*", "pattern": "*", "action": "deny"},
        {"permission": "read", "pattern": "*", "action": "allow"},
        {"permission": "grep", "pattern": "*", "action": "allow"},
        {"permission": "glob_tool", "pattern": "*", "action": "allow"}
      ]
    }
  },
  "model": {
    "haiku": {
      "provider": "anthropic",
      "model": "claude-haiku-3-5"
    }
  },
  "default_agent": "reviewer"
}
```

`mode` is either `"primary"` (user-facing) or `"subagent"` (called via `task` tool only).

## Project Instructions

Place an `AGENTS.md` file anywhere in your project. Sibux will find and include it in the system prompt as project-specific instructions.

## Tools

| Tool | Description |
|------|-------------|
| `bash` | Execute shell commands (30s timeout) |
| `read` | Read file contents with optional offset/limit |
| `edit` | Find-and-replace editing |
| `write` | Write file contents (creates parent directories) |
| `glob` | File path pattern matching |
| `grep` | Content search across files |
| `task` | Delegate subtasks to a subagent |

## Permissions

Permission rules control which tools an agent can use. Rules are evaluated with last-match-wins semantics.

```json
"permission": [
  {"permission": "*",    "pattern": "*", "action": "deny"},
  {"permission": "read", "pattern": "*", "action": "allow"}
]
```

`permission` is a tool name or `"*"` (all tools). `pattern` is a glob matched against the tool name. `action` is `"allow"` or `"deny"`.
