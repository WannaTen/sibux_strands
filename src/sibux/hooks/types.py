"""Types for Sibux hook integrations."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable

SystemPromptTransform = Callable[[str], str]
"""Callable that transforms the fully built system prompt."""


@runtime_checkable
class SystemPromptTransformProvider(Protocol):
    """Protocol for hook providers that expose system prompt transforms."""

    def get_system_prompt_transforms(self) -> Sequence[SystemPromptTransform]:
        """Return prompt transforms to apply before agent construction."""
        ...
