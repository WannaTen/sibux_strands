"""This package provides the core Agent interface and supporting components for building AI agents with the SDK.

It includes:

- Agent: The main interface for interacting with AI models and tools
- ContextManager: Classes for managing conversation history and context windows
- Retry Strategies: Configurable retry behavior for model calls
"""

from ..event_loop._retry import ModelRetryStrategy
from .agent import Agent
from .agent_result import AgentResult
from .base import AgentBase
from ..context_manager import (
    ContextManager,
    NullContextManager,
    SlidingWindowContextManager,
    SummarizingContextManager,
)

__all__ = [
    "Agent",
    "AgentBase",
    "AgentResult",
    "ContextManager",
    "NullContextManager",
    "SlidingWindowContextManager",
    "SummarizingContextManager",
    "ModelRetryStrategy",
]
