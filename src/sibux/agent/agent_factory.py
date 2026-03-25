"""Factory for creating Strands Agent instances from Sibux AgentConfig."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import strands
from strands.handlers.callback_handler import PrintingCallbackHandler

from ..permission.permission import filter_tools
from ..tools import ALL_TOOLS, set_task_config
from .system_prompt import build_system_prompt

if TYPE_CHECKING:
    from ..config.config import AgentConfig, Config

logger = logging.getLogger(__name__)


def create(config: Config, agent_config: AgentConfig) -> strands.Agent:
    """Build a Strands Agent from an AgentConfig.

    Resolves the model, filters tools by permission rules, constructs the
    system prompt, and wires the task tool's config reference.

    Args:
        config: Top-level application configuration.
        agent_config: Configuration for the specific agent to create.

    Returns:
        A configured Strands Agent ready to be called.
    """
    # Inject config into task tool before building the agent
    set_task_config(config)

    model = _resolve_model(config, agent_config)
    tools = filter_tools(ALL_TOOLS, agent_config.permission)
    system_prompt = build_system_prompt(agent_config, config)

    tool_names = [getattr(t, "__name__", str(t)) for t in tools]
    logger.debug(
        "agent=<%s>, model=<%s>, tools=<%s> | creating agent",
        agent_config.name,
        getattr(model, "model_id", model),
        tool_names,
    )

    return strands.Agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        callback_handler=PrintingCallbackHandler(),
    )


def _resolve_model(config: Config, agent_config: AgentConfig) -> Any:
    """Resolve the model to use for an agent.

    Priority:
      1. Agent-specific model (agent_config.model)
      2. Config default_model
      3. Strands SDK default (BedrockModel)

    The model reference is either a name in config.model (e.g., "sonnet") or a
    direct "provider/model_id" string (e.g., "anthropic/claude-sonnet-4-5").
    When it is a named model, its parameters are used as defaults, which the
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

    # Resolve named model alias from config.model dict
    model_cfg = config.model.get(ref)
    if model_cfg is not None:
        model_str = model_cfg.model
        model_options = model_cfg
    else:
        model_str = ref
        model_options = None

    # Parse "provider/model_id" format
    if "/" not in model_str:
        logger.error("model=<%s> | invalid model format, expected 'provider/model'", model_str)
        return None

    provider_id, model_id = model_str.split("/", 1)
    provider_id = provider_id.lower()
    provider_cfg = config.provider.get(provider_id, None)

    # Determine final parameters: agent overrides named model config
    final_temperature = (
        agent_config.temperature
        if agent_config.temperature is not None
        else (model_options.temperature if model_options else None)
    )
    final_max_tokens = (
        agent_config.max_tokens
        if agent_config.max_tokens is not None
        else (model_options.max_tokens if model_options else None)
    )
    final_top_p = model_options.top_p if model_options else None
    final_top_k = model_options.top_k if model_options else None
    final_extra = model_options.extra if model_options else {}

    # Get provider credentials
    api_key = provider_cfg.api_key if provider_cfg else None
    base_url = provider_cfg.base_url if provider_cfg else None

    if provider_id == "anthropic":
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

    logger.warning("provider_id=<%s> | unknown provider, falling back to Strands default", provider_id)
    return None
