"""Factory for creating Strands Agent instances from Sibux AgentConfig."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import strands
from strands.handlers.callback_handler import null_callback_handler

from ..hooks.types import SystemPromptTransformProvider
from ..permission.permission import filter_tools
from ..tools import ALL_TOOLS, set_task_config
from .system_prompt import build_system_prompt

if TYPE_CHECKING:
    from strands.hooks import HookProvider
    from strands.session import SessionManager

    from ..config.config import AgentConfig, Config
    from ..hooks.types import SystemPromptTransform

logger = logging.getLogger(__name__)


def create(
    config: Config,
    agent_config: AgentConfig,
    *,
    session_manager: SessionManager | None = None,
    agent_id: str | None = None,
    context_manager: Any | None = None,
    hooks: list[HookProvider] | None = None,
) -> strands.Agent:
    """Build a Strands Agent from an AgentConfig.

    Resolves the model, filters tools by permission rules, constructs the
    system prompt, and wires the task tool's config reference.

    Args:
        config: Top-level application configuration.
        agent_config: Configuration for the specific agent to create.
        session_manager: Optional session manager for persistent primary-agent
            flows.
        agent_id: Optional stable agent identifier for session-backed agents.
        context_manager: Optional Strands context manager override.
        hooks: Optional Strands hook providers to register on the created
            agent. Sibux providers may also contribute system prompt
            transforms before agent construction.

    Returns:
        A configured Strands Agent ready to be called.

    Raises:
        ValueError: If a session manager is provided without a stable agent ID.
    """
    if session_manager is not None and agent_id is None:
        raise ValueError("agent_id is required when session_manager is provided")

    # Inject config into task tool before building the agent
    set_task_config(config)

    model = _resolve_model(config, agent_config)
    tools = filter_tools(ALL_TOOLS, agent_config.permission)
    system_prompt = build_system_prompt(agent_config, config)
    hook_list = list(hooks or [])
    system_prompt = _apply_system_prompt_transforms(system_prompt, hook_list)

    tool_names = [getattr(t, "__name__", str(t)) for t in tools]
    logger.debug(
        "agent=<%s>, agent_id=<%s>, has_session_manager=<%s>, has_hooks=<%s>, model=<%s>, tools=<%s> | creating agent",
        agent_config.name,
        agent_id,
        session_manager is not None,
        bool(hook_list),
        getattr(model, "model_id", model),
        tool_names,
    )

    agent_kwargs: dict[str, Any] = {
        "model": model,
        "tools": tools,
        "system_prompt": system_prompt,
        "callback_handler": null_callback_handler,
    }
    if session_manager is not None:
        agent_kwargs["session_manager"] = session_manager
    if agent_id is not None:
        agent_kwargs["agent_id"] = agent_id
    if context_manager is not None:
        agent_kwargs["context_manager"] = context_manager
    if hook_list:
        agent_kwargs["hooks"] = hook_list

    return strands.Agent(
        **agent_kwargs,
    )


def _apply_system_prompt_transforms(system_prompt: str, hooks: Sequence[HookProvider]) -> str:
    """Apply registered system prompt transforms in order.

    Args:
        system_prompt: The prompt built from Sibux configuration and
            environment context.
        hooks: Hook providers passed to the agent factory.

    Returns:
        The transformed system prompt.
    """
    transformed_prompt = system_prompt
    for transform in _iter_system_prompt_transforms(hooks):
        transformed_prompt = transform(transformed_prompt)
    return transformed_prompt


def _iter_system_prompt_transforms(hooks: Sequence[HookProvider]) -> list[SystemPromptTransform]:
    """Collect system prompt transforms exposed by hook providers."""
    transforms: list[SystemPromptTransform] = []
    for hook in hooks:
        if isinstance(hook, SystemPromptTransformProvider):
            transforms.extend(hook.get_system_prompt_transforms())
    return transforms


def _resolve_model(config: Config, agent_config: AgentConfig) -> Any:
    """Resolve the model to use for an agent.

    Priority:
      1. Agent-specific model (agent_config.model)
      2. Config default_model
      3. Strands SDK default (BedrockModel)

    The model reference is the name of a configured model alias in
    ``config.model``. The alias parameters are used as defaults, which the
    agent-level temperature/max_tokens can still override.

    Args:
        config: Top-level application configuration.
        agent_config: Agent-specific configuration.

    Returns:
        A Strands Model instance or None (falls back to Strands default).
    """
    ref = agent_config.model or config.default_model
    if ref is None:
        return None  # Strands defaults to BedrockModel

    model_cfg = config.model.get(ref)
    if model_cfg is None:
        logger.error("model=<%s> | model alias is not configured", ref)
        return None

    provider_id = model_cfg.provider
    model_id = model_cfg.model
    provider_cfg = config.provider.get(provider_id, None)

    # Determine final parameters: agent overrides named model config
    final_temperature = agent_config.temperature if agent_config.temperature is not None else model_cfg.temperature
    final_max_tokens = agent_config.max_tokens if agent_config.max_tokens is not None else model_cfg.max_tokens
    final_top_p = model_cfg.top_p
    final_top_k = model_cfg.top_k
    final_extra = model_cfg.extra

    # Get provider credentials
    api_key = provider_cfg.api_key if provider_cfg else None
    base_url = provider_cfg.base_url if provider_cfg else None

    if provider_id == "anthropic" or provider_id == "ant-moonshot":
        from strands.models.anthropic import AnthropicModel

        # max_tokens and model_id are top-level kwargs; temperature etc. go in params
        anthropic_kwargs: dict[str, Any] = {
            "model_id": model_id,
            "max_tokens": final_max_tokens if final_max_tokens is not None else 8096,
        }
        client_args: dict[str, Any] = {}
        if api_key:
            client_args["api_key"] = api_key
        if base_url:
            client_args["base_url"] = base_url
        if provider_cfg and provider_cfg.headers:
            client_args["default_headers"] = provider_cfg.headers
        if client_args:
            anthropic_kwargs["client_args"] = client_args
        params: dict[str, Any] = {}
        if final_temperature is not None:
            params["temperature"] = final_temperature
        if final_top_p is not None:
            params["top_p"] = final_top_p
        if final_top_k is not None:
            params["top_k"] = final_top_k
        if final_extra:
            params.update(final_extra)
        if params:
            anthropic_kwargs["params"] = params
        return AnthropicModel(**anthropic_kwargs)

    if provider_id in ("openai", "openai-compatible"):
        from strands.models.openai import OpenAIModel

        openai_client_args: dict[str, Any] = {}
        if api_key:
            openai_client_args["api_key"] = api_key
        if base_url:
            openai_client_args["base_url"] = base_url
        if provider_cfg and provider_cfg.headers:
            openai_client_args["default_headers"] = provider_cfg.headers
        openai_params: dict[str, Any] = {}
        if final_temperature is not None:
            openai_params["temperature"] = final_temperature
        if final_max_tokens is not None:
            openai_params["max_tokens"] = final_max_tokens
        if final_top_p is not None:
            openai_params["top_p"] = final_top_p
        if final_extra:
            openai_params.update(final_extra)
        openai_kwargs: dict[str, Any] = {"model_id": model_id}
        if openai_client_args:
            openai_kwargs["client_args"] = openai_client_args
        if openai_params:
            openai_kwargs["params"] = openai_params
        return OpenAIModel(**openai_kwargs)

    if provider_id == "bedrock":
        from strands.models.bedrock import BedrockModel

        bedrock_kwargs: dict[str, Any] = {"model_id": model_id}
        if final_temperature is not None:
            bedrock_kwargs["temperature"] = final_temperature
        if final_max_tokens is not None:
            bedrock_kwargs["max_tokens"] = final_max_tokens
        return BedrockModel(**bedrock_kwargs)

    if provider_id == "ollama":
        from strands.models.ollama import OllamaModel

        ollama_kwargs: dict[str, Any] = {"model_id": model_id}
        if base_url:
            ollama_kwargs["host"] = base_url
        return OllamaModel(**ollama_kwargs)

    if provider_id == "litellm":
        from strands.models.litellm import LiteLLMModel

        litellm_kwargs: dict[str, Any] = {"model_id": model_id}
        if api_key:
            litellm_kwargs["api_key"] = api_key
        if base_url:
            litellm_kwargs["base_url"] = base_url
        return LiteLLMModel(**litellm_kwargs)

    if provider_id == "moonshot":
        from strands.models.moonshot import MoonshotKimiModel

        moonshot_client_args: dict[str, Any] = {}
        if api_key:
            moonshot_client_args["api_key"] = api_key
        if base_url:
            moonshot_client_args["base_url"] = base_url
        moonshot_params: dict[str, Any] = {}
        if final_temperature is not None:
            moonshot_params["temperature"] = final_temperature
        if final_max_tokens is not None:
            moonshot_params["max_tokens"] = final_max_tokens
        if final_top_p is not None:
            moonshot_params["top_p"] = final_top_p
        if final_top_k is not None:
            moonshot_params["top_k"] = final_top_k
        if final_extra:
            moonshot_params.update(final_extra)
        moonshot_kwargs: dict[str, Any] = {"model_id": model_id}
        if moonshot_client_args:
            moonshot_kwargs["client_args"] = moonshot_client_args
        if moonshot_params:
            moonshot_kwargs["params"] = moonshot_params
        return MoonshotKimiModel(**moonshot_kwargs)

    logger.warning("provider_id=<%s> | unknown provider, falling back to Strands default", provider_id)
    return None
