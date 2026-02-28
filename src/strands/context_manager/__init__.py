"""This package provides classes for managing conversation history during agent execution.

It includes:

- ContextManager: Abstract base class defining the context management interface
- NullContextManager: A no-op implementation that does not modify conversation history
- SlidingWindowContextManager: An implementation that maintains a sliding window of messages to control context
  size while preserving conversation coherence
- SummarizingContextManager: An implementation that summarizes older context instead
  of simply trimming it

Context managers help control memory usage and context length while maintaining relevant conversation state, which
is critical for effective agent interactions.
"""

from .context_manager import ContextManager
from .null_context_manager import NullContextManager
from .sliding_window_context_manager import SlidingWindowContextManager
from .summarizing_context_manager import SummarizingContextManager

__all__ = [
    "ContextManager",
    "NullContextManager",
    "SlidingWindowContextManager",
    "SummarizingContextManager",
]
