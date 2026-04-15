"""Sibux hook provider implementation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from strands.hooks import (
    AfterInvocationEvent,
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeToolCallEvent,
    HookCallback,
    HookProvider,
    HookRegistry,
)

from .types import SystemPromptTransform


class SibuxHookProvider(HookProvider):
    """Register Sibux hook callbacks against the Strands hook registry.

    The default implementation exposes four lifecycle callbacks and an
    optional system prompt transform pipeline. Callers can subclass this
    provider and override the lifecycle methods, or inject callbacks through
    the constructor for lightweight one-off hooks.
    """

    def __init__(
        self,
        *,
        before_tool_call: HookCallback[BeforeToolCallEvent] | None = None,
        after_tool_call: HookCallback[AfterToolCallEvent] | None = None,
        before_invocation: HookCallback[BeforeInvocationEvent] | None = None,
        after_invocation: HookCallback[AfterInvocationEvent] | None = None,
        system_prompt_transforms: Sequence[SystemPromptTransform] | None = None,
    ) -> None:
        """Initialize a Sibux hook provider.

        Args:
            before_tool_call: Optional callback for tool pre-execution.
            after_tool_call: Optional callback for tool post-execution.
            before_invocation: Optional callback for invocation pre-processing.
            after_invocation: Optional callback for invocation cleanup.
            system_prompt_transforms: Optional transforms applied to the built
                system prompt before the agent is created.
        """
        self._before_tool_call = before_tool_call
        self._after_tool_call = after_tool_call
        self._before_invocation = before_invocation
        self._after_invocation = after_invocation
        self._system_prompt_transforms = list(system_prompt_transforms or [])

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Register the Sibux lifecycle callbacks with Strands.

        Args:
            registry: Hook registry supplied by the Strands agent.
            **kwargs: Additional future-compatible registration parameters.
        """
        del kwargs
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call or self.on_before_tool_call)
        registry.add_callback(AfterToolCallEvent, self._after_tool_call or self.on_after_tool_call)
        registry.add_callback(BeforeInvocationEvent, self._before_invocation or self.on_before_invocation)
        registry.add_callback(AfterInvocationEvent, self._after_invocation or self.on_after_invocation)

    def get_system_prompt_transforms(self) -> list[SystemPromptTransform]:
        """Return the registered system prompt transforms."""
        return list(self._system_prompt_transforms)

    def add_system_prompt_transform(self, transform: SystemPromptTransform) -> None:
        """Append a system prompt transform to this provider.

        Args:
            transform: Callable that accepts the current prompt string and
                returns the replacement prompt string.
        """
        self._system_prompt_transforms.append(transform)

    def on_before_tool_call(self, event: BeforeToolCallEvent) -> None:
        """Handle the tool pre-execution hook."""
        del event

    def on_after_tool_call(self, event: AfterToolCallEvent) -> None:
        """Handle the tool post-execution hook."""
        del event

    def on_before_invocation(self, event: BeforeInvocationEvent) -> None:
        """Handle the invocation pre-processing hook."""
        del event

    def on_after_invocation(self, event: AfterInvocationEvent) -> None:
        """Handle the invocation post-processing hook."""
        del event
