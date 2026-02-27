"""This module implements the central event loop.

The event loop allows agents to:

1. Process conversation messages
2. Execute tools based on model requests
3. Handle errors and recovery strategies
4. Manage recursive execution cycles
"""
# Modified by Linyi in 2026.
# Licensed under the Apache License, Version 2.0.

import logging
import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from opentelemetry import trace as trace_api

from ..hooks import AfterModelCallEvent, BeforeModelCallEvent, MessageAddedEvent
from ..telemetry.metrics import Trace
from ..telemetry.tracer import Tracer, get_tracer
from ..tools._validator import validate_and_prepare_tools
from ..types._events import (
    EventLoopStopEvent,
    ForceStopEvent,
    ModelMessageEvent,
    ModelStopReason,
    StartEvent,
    StartEventLoopEvent,
    ToolInterruptEvent,
    ToolResultMessageEvent,
    TypedEvent,
)
from ..types.content import Message, Messages
from ..types.exceptions import (
    ContextWindowOverflowException,
    EventLoopException,
    MaxTokensReachedException,
)
from ..types.streaming import StopReason
from ..types.tools import ToolResult, ToolUse
from ._recover_message_on_max_tokens_reached import recover_message_on_max_tokens_reached
from ._retry import ModelRetryStrategy
from .streaming import stream_messages

if TYPE_CHECKING:
    from ..agent import Agent

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 6
INITIAL_DELAY = 4
MAX_DELAY = 240  # 4 minutes


def _has_tool_use_in_latest_message(messages: "Messages") -> bool:
    """Check if the latest message contains any ToolUse content blocks.

    Args:
        messages: List of messages in the conversation.

    Returns:
        True if the latest message contains at least one ToolUse content block, False otherwise.
    """
    if len(messages) > 0:
        latest_message = messages[-1]
        content_blocks = latest_message.get("content", [])

        for content_block in content_blocks:
            if "toolUse" in content_block:
                return True

    return False


async def event_loop_cycle(
    agent: "Agent",
    invocation_state: dict[str, Any],
) -> AsyncGenerator[TypedEvent, None]:
    """Execute the event loop as a while-loop over conversation turns.

    Each iteration handles one model call and optional tool execution. The loop continues
    until the model stops for a non-tool reason (e.g., end_turn) or a stop condition is met.

    Args:
        agent: The agent for which the loop is being executed.
        invocation_state: Additional arguments including:

            - request_state: State maintained across cycles
            - event_loop_cycle_id: Unique ID for this cycle
            - event_loop_cycle_span: Current tracing Span for this cycle

    Yields:
        Model and tool stream events. The last event is an EventLoopStopEvent.

    Raises:
        EventLoopException: If an error occurs during execution
        ContextWindowOverflowException: If the input is too large for the model
    """

    if "request_state" not in invocation_state:
        invocation_state["request_state"] = {}

    while True:
        # Initialize cycle state
        invocation_state["event_loop_cycle_id"] = uuid.uuid4()
        attributes = {"event_loop_cycle_id": str(invocation_state.get("event_loop_cycle_id"))}
        cycle_start_time, cycle_trace = agent.event_loop_metrics.start_cycle(attributes=attributes)
        invocation_state["event_loop_cycle_trace"] = cycle_trace

        yield StartEvent()
        yield StartEventLoopEvent()

        # Create tracer span for this event loop cycle
        tracer = get_tracer()
        cycle_span = tracer.start_event_loop_cycle_span(
            invocation_state=invocation_state,
            messages=agent.messages,
            parent_span=agent.trace_span,
            custom_trace_attributes=agent.trace_attributes,
        )
        invocation_state["event_loop_cycle_span"] = cycle_span

        with trace_api.use_span(cycle_span, end_on_exit=True):
            # Skipping model invocation if in interrupt state
            if agent._interrupt_state.activated:
                stop_reason: StopReason = "tool_use"
                message = agent._interrupt_state.context["tool_use_message"]
            # Skip model invocation if the latest message contains ToolUse
            elif _has_tool_use_in_latest_message(agent.messages):
                stop_reason = "tool_use"
                message = agent.messages[-1]
            else:
                model_events = _handle_model_execution(
                    agent, cycle_span, cycle_trace, invocation_state, tracer
                )
                async for model_event in model_events:
                    if not isinstance(model_event, ModelStopReason):
                        yield model_event

                stop_reason, message, *_ = model_event["stop"]
                yield ModelMessageEvent(message=message)

            try:
                if stop_reason == "max_tokens":
                    raise MaxTokensReachedException(
                        message=(
                            "Agent has reached an unrecoverable state due to max_tokens limit. "
                            "For more information see: "
                            "https://strandsagents.com/latest/user-guide/concepts/agents/agent-loop/"
                            "#maxtokensreachedexception"
                        )
                    )

                if stop_reason == "tool_use":
                    should_stop = False
                    tool_events = _handle_tool_execution(
                        stop_reason,
                        message,
                        agent=agent,
                        cycle_trace=cycle_trace,
                        cycle_span=cycle_span,
                        cycle_start_time=cycle_start_time,
                        invocation_state=invocation_state,
                        tracer=tracer,
                    )
                    async for tool_event in tool_events:
                        yield tool_event
                        if isinstance(tool_event, EventLoopStopEvent):
                            should_stop = True

                    if should_stop:
                        return

                    # Continue to next turn
                    continue

                # End the cycle for non-tool_use stops
                agent.event_loop_metrics.end_cycle(cycle_start_time, cycle_trace, attributes)
                tracer.end_event_loop_cycle_span(cycle_span, message)

            except EventLoopException:
                raise
            except (ContextWindowOverflowException, MaxTokensReachedException) as e:
                raise e
            except Exception as e:
                yield ForceStopEvent(reason=e)
                logger.exception("cycle failed")
                raise EventLoopException(e, invocation_state["request_state"]) from e

            yield EventLoopStopEvent(
                stop_reason, message, agent.event_loop_metrics, invocation_state["request_state"]
            )
            return


async def _handle_model_execution(
    agent: "Agent",
    cycle_span: Any,
    cycle_trace: Trace,
    invocation_state: dict[str, Any],
    tracer: Tracer,
) -> AsyncGenerator[TypedEvent, None]:
    """Handle model execution with retry logic for throttling exceptions.

    Executes the model inference with automatic retry handling for throttling exceptions.
    Manages tracing, hooks, and metrics collection throughout the process.

    Args:
        agent: The agent executing the model.
        cycle_span: Span object for tracing the cycle.
        cycle_trace: Trace object for the current event loop cycle.
        invocation_state: State maintained across cycles.
        tracer: Tracer instance for span management.

    Yields:
        Model stream events and throttle events during retries.

    Raises:
        ModelThrottledException: If max retry attempts are exceeded.
        Exception: Any other model execution errors.
    """
    # Create a trace for the stream_messages call
    stream_trace = Trace("stream_messages", parent_id=cycle_trace.id)
    cycle_trace.add_child(stream_trace)

    # Retry loop - actual retry logic is handled by retry_strategy hook
    # Hooks control when to stop retrying via the event.retry flag
    while True:
        model_id = agent.model.config.get("model_id") if hasattr(agent.model, "config") else None
        model_invoke_span = tracer.start_model_invoke_span(
            messages=agent.messages,
            parent_span=cycle_span,
            model_id=model_id,
            custom_trace_attributes=agent.trace_attributes,
        )
        with trace_api.use_span(model_invoke_span, end_on_exit=True):
            await agent.hooks.invoke_callbacks_async(
                BeforeModelCallEvent(
                    agent=agent,
                    invocation_state=invocation_state,
                )
            )

            tool_specs = agent.tool_registry.get_all_tool_specs()
            try:
                async for event in stream_messages(
                    agent.model,
                    agent.system_prompt,
                    agent.messages,
                    tool_specs,
                    system_prompt_content=agent._system_prompt_content,
                    invocation_state=invocation_state,
                ):
                    yield event

                stop_reason, message, usage, metrics = event["stop"]
                invocation_state.setdefault("request_state", {})

                after_model_call_event = AfterModelCallEvent(
                    agent=agent,
                    invocation_state=invocation_state,
                    stop_response=AfterModelCallEvent.ModelStopResponse(
                        stop_reason=stop_reason,
                        message=message,
                    ),
                )

                await agent.hooks.invoke_callbacks_async(after_model_call_event)

                # Check if hooks want to retry the model call
                if after_model_call_event.retry:
                    logger.debug(
                        "stop_reason=<%s>, retry_requested=<True> | hook requested model retry",
                        stop_reason,
                    )
                    continue  # Retry the model call

                if stop_reason == "max_tokens":
                    message = recover_message_on_max_tokens_reached(message)

                # Set attributes before span auto-closes
                tracer.end_model_invoke_span(model_invoke_span, message, usage, metrics, stop_reason)
                break  # Success! Break out of retry loop

            except Exception as e:
                # Exception is automatically recorded by use_span with end_on_exit=True
                after_model_call_event = AfterModelCallEvent(
                    agent=agent,
                    invocation_state=invocation_state,
                    exception=e,
                )
                await agent.hooks.invoke_callbacks_async(after_model_call_event)

                # Emit backwards-compatible events if retry strategy supports it
                # (prior to making the retry strategy configurable, this is what we emitted)

                if (
                    isinstance(agent._retry_strategy, ModelRetryStrategy)
                    and agent._retry_strategy._backwards_compatible_event_to_yield
                ):
                    yield agent._retry_strategy._backwards_compatible_event_to_yield

                # Check if hooks want to retry the model call
                if after_model_call_event.retry:
                    logger.debug(
                        "exception=<%s>, retry_requested=<True> | hook requested model retry",
                        type(e).__name__,
                    )

                    continue  # Retry the model call

                # No retry requested, raise the exception
                yield ForceStopEvent(reason=e)
                raise e

    try:
        # Add message in trace and mark the end of the stream messages trace
        stream_trace.add_message(message)
        stream_trace.end()

        # Add the response message to the conversation
        agent.messages.append(message)
        await agent.hooks.invoke_callbacks_async(MessageAddedEvent(agent=agent, message=message))

        # Update metrics
        agent.event_loop_metrics.update_usage(usage)
        agent.event_loop_metrics.update_metrics(metrics)

    except Exception as e:
        yield ForceStopEvent(reason=e)
        logger.exception("cycle failed")
        raise EventLoopException(e, invocation_state["request_state"]) from e


async def _handle_tool_execution(
    stop_reason: StopReason,
    message: Message,
    agent: "Agent",
    cycle_trace: Trace,
    cycle_span: Any,
    cycle_start_time: float,
    invocation_state: dict[str, Any],
    tracer: Tracer,
) -> AsyncGenerator[TypedEvent, None]:
    """Handle the execution of tools requested by the model during an event loop cycle.

    Args:
        stop_reason: The reason the model stopped generating.
        message: The message from the model that may contain tool use requests.
        agent: Agent for which tools are being executed.
        cycle_trace: Trace object for the current event loop cycle.
        cycle_span: Span object for tracing the cycle.
        cycle_start_time: Start time of the current cycle.
        invocation_state: Additional keyword arguments, including request state.
        tracer: Tracer instance for span management.

    Yields:
        Tool stream events. If the loop should stop, the last event is an EventLoopStopEvent.
    """
    tool_uses: list[ToolUse] = []
    tool_results: list[ToolResult] = []
    invalid_tool_use_ids: list[str] = []

    validate_and_prepare_tools(message, tool_uses, tool_results, invalid_tool_use_ids)
    tool_uses = [tool_use for tool_use in tool_uses if tool_use.get("toolUseId") not in invalid_tool_use_ids]

    if agent._interrupt_state.activated:
        tool_results.extend(agent._interrupt_state.context["tool_results"])
        tool_use_ids = {tool_result["toolUseId"] for tool_result in tool_results}
        tool_uses = [tool_use for tool_use in tool_uses if tool_use["toolUseId"] not in tool_use_ids]

    interrupts: list[Any] = []
    tool_events = agent.tool_executor._execute(
        agent, tool_uses, tool_results, cycle_trace, cycle_span, invocation_state
    )
    async for tool_event in tool_events:
        if isinstance(tool_event, ToolInterruptEvent):
            interrupts.extend(tool_event["tool_interrupt_event"]["interrupts"])
        yield tool_event

    invocation_state["event_loop_parent_cycle_id"] = invocation_state["event_loop_cycle_id"]

    if interrupts:
        agent._interrupt_state.context = {"tool_use_message": message, "tool_results": tool_results}
        agent._interrupt_state.activate()

        agent.event_loop_metrics.end_cycle(cycle_start_time, cycle_trace)
        yield EventLoopStopEvent(
            "interrupt",
            message,
            agent.event_loop_metrics,
            invocation_state["request_state"],
            interrupts,
        )
        if cycle_span:
            tracer.end_event_loop_cycle_span(span=cycle_span, message=message)
        return

    agent._interrupt_state.deactivate()

    tool_result_message: Message = {
        "role": "user",
        "content": [{"toolResult": result} for result in tool_results],
    }

    agent.messages.append(tool_result_message)
    await agent.hooks.invoke_callbacks_async(MessageAddedEvent(agent=agent, message=tool_result_message))

    yield ToolResultMessageEvent(message=tool_result_message)

    if cycle_span:
        tracer.end_event_loop_cycle_span(span=cycle_span, message=message, tool_result_message=tool_result_message)

    if invocation_state["request_state"].get("stop_event_loop", False):
        agent.event_loop_metrics.end_cycle(cycle_start_time, cycle_trace)
        yield EventLoopStopEvent(
            stop_reason,
            message,
            agent.event_loop_metrics,
            invocation_state["request_state"],
        )



