# Streaming Events Reference

This document explains which chunk and event shapes can appear while streaming
through the main `strands` execution path.

It is intended as a lookup reference for:

- model adapter authors
- callback handler authors
- application code that consumes `Agent.stream_async()`

## Scope

This reference focuses on the standard agent streaming path:

1. model adapters yield standardized `StreamEvent` chunks
2. `event_loop.streaming.process_stream()` converts chunks into typed events
3. `Agent.stream_async()` exposes callback-eligible events as plain dictionaries

Multi-agent wrappers such as Swarm and Graph add another layer on top. Those are
covered briefly at the end.

## Streaming Layers

There are three different layers that are easy to confuse:

### 1. Raw standardized model chunks

These are the `StreamEvent` dictionaries defined in
[`src/strands/types/streaming.py`](../src/strands/types/streaming.py).

Examples:

```python
{"messageStart": {"role": "assistant"}}
{"contentBlockStart": {"start": {}}}
{"contentBlockDelta": {"delta": {"text": "Hello"}}}
{"messageStop": {"stopReason": "end_turn"}}
```

### 2. `process_stream()` output

`process_stream()` yields both:

- a raw chunk wrapper: `{"event": <StreamEvent>}`
- higher-level delta events such as text/tool/reasoning/citation updates

This logic lives in
[`src/strands/event_loop/streaming.py`](../src/strands/event_loop/streaming.py).

### 3. `Agent.stream_async()` output

`Agent.stream_async()` yields the callback-eligible events as plain dictionaries
and finally appends:

```python
{"result": AgentResult(...)}
```

Internal stop events such as `ModelStopReason` and `EventLoopStopEvent` are used
inside the event loop but are not directly yielded by `Agent.stream_async()`.

## Layer 1: Standardized Raw Chunks

Top-level `StreamEvent` chunk types:

| Top-level key | Meaning | Notes |
| --- | --- | --- |
| `messageStart` | Start of an assistant message | Usually first chunk |
| `contentBlockStart` | Start of a content block | May include tool metadata |
| `contentBlockDelta` | Incremental content payload | Text, tool input, citations, reasoning |
| `contentBlockStop` | End of a content block | Finalizes the buffered block |
| `messageStop` | End of the assistant message | Carries `stopReason` |
| `metadata` | Usage and metrics | Commonly last chunk |
| `redactContent` | Guardrail-driven redaction instruction | Seen in Bedrock guardrail flows |
| `internalServerException` | Error chunk type declared by the schema | Declared, not commonly yielded in current adapters |
| `modelStreamErrorException` | Error chunk type declared by the schema | Declared, not commonly yielded in current adapters |
| `serviceUnavailableException` | Error chunk type declared by the schema | Declared, not commonly yielded in current adapters |
| `throttlingException` | Error chunk type declared by the schema | Declared, not commonly yielded in current adapters |
| `validationException` | Error chunk type declared by the schema | Declared, not commonly yielded in current adapters |

The schema is defined in
[`src/strands/types/streaming.py`](../src/strands/types/streaming.py).

### `contentBlockStart`

`contentBlockStart` has two common shapes:

Plain content block:

```python
{"contentBlockStart": {"start": {}}}
```

Tool-use content block:

```python
{
    "contentBlockStart": {
        "start": {
            "toolUse": {
                "name": "search",
                "toolUseId": "tooluse_123",
            }
        }
    }
}
```

Some providers also include `reasoningSignature` on tool start. Gemini does this
when the provider exposes a thought signature.

`contentBlockIndex` may be present depending on the provider. The event loop does
not require it for the main buffering logic.

### `contentBlockDelta`

`contentBlockDelta["delta"]` is where the useful payload lives. In the current
codebase it can contain the following subtypes.

#### Text delta

```python
{"contentBlockDelta": {"delta": {"text": "Hello"}}}
```

Used for normal assistant text.

#### Tool-use delta

```python
{"contentBlockDelta": {"delta": {"toolUse": {"input": "{\"city\": \"Paris\"}"}}}}
```

The input is streamed as a string fragment and accumulated until
`contentBlockStop`, where it is parsed as JSON.

#### Citation delta

```python
{
    "contentBlockDelta": {
        "delta": {
            "citation": {
                "title": "Spec",
                "location": {"documentPage": {"documentIndex": 0, "start": 3, "end": 4}},
                "sourceContent": [{"text": "quoted source text"}],
            }
        }
    }
}
```

This is used for citation-aware Bedrock responses.

#### Reasoning text delta

```python
{"contentBlockDelta": {"delta": {"reasoningContent": {"text": "I should call a tool"}}}}
```

#### Reasoning signature delta

```python
{"contentBlockDelta": {"delta": {"reasoningContent": {"signature": "abc-"}}}}
```

This appends to the reasoning signature buffer and is finalized together with
the reasoning text block.

#### Reasoning redacted-content delta

```python
{"contentBlockDelta": {"delta": {"reasoningContent": {"redactedContent": b"..."}}}}
```

This is used when a provider returns encrypted or redacted reasoning bytes
instead of plain reasoning text.

### `messageStop`

Common `stopReason` values in the main path:

| `stopReason` | Meaning |
| --- | --- |
| `end_turn` | Normal assistant completion |
| `tool_use` | The assistant wants tools to run |
| `max_tokens` | The model hit the output token limit |
| `guardrail_intervened` | Guardrail stopped or replaced output |

Provider adapters may normalize provider-specific stop reasons into this set.

`interrupt` exists later at the event-loop layer, but it is not a normal raw
`messageStop` value emitted by model adapters.

## Layer 2: `process_stream()` Events

`process_stream()` is implemented in
[`src/strands/event_loop/streaming.py`](../src/strands/event_loop/streaming.py).

For every raw model chunk, it first yields:

```python
{"event": <raw StreamEvent>}
```

Then, for `contentBlockDelta`, it may yield one additional high-level event.

### Raw chunk wrapper

```python
{"event": {"contentBlockDelta": {"delta": {"text": "Hello"}}}}
```

This preserves the exact standardized chunk for consumers that want the lowest
level view.

### Text stream event

```python
{"data": "Hello", "delta": {"text": "Hello"}}
```

Produced when `delta` contains `text`.

### Tool-use stream event

```python
{
    "type": "tool_use_stream",
    "delta": {"toolUse": {"input": "{\"city\": "}},
    "current_tool_use": {
        "toolUseId": "tooluse_123",
        "name": "weather",
        "input": "{\"city\": ",
    },
}
```

Produced when `delta` contains `toolUse`. `current_tool_use` is the accumulated
state so far.

### Citation stream event

```python
{
    "citation": {
        "title": "Spec",
        "location": {"documentPage": {"documentIndex": 0, "start": 3, "end": 4}},
    },
    "delta": {
        "citation": {
            "title": "Spec",
            "location": {"documentPage": {"documentIndex": 0, "start": 3, "end": 4}},
        }
    },
}
```

Produced when `delta` contains `citation`.

### Reasoning text stream event

```python
{
    "reasoningText": "I should call a tool",
    "delta": {"reasoningContent": {"text": "I should call a tool"}},
    "reasoning": True,
}
```

### Reasoning signature stream event

```python
{
    "reasoning_signature": "abc-",
    "delta": {"reasoningContent": {"signature": "abc-"}},
    "reasoning": True,
}
```

### Reasoning redacted-content stream event

```python
{
    "reasoningRedactedContent": b"...",
    "delta": {"reasoningContent": {"redactedContent": b"..."}},
    "reasoning": True,
}
```

### Final stop event

At the end of the raw stream, `process_stream()` yields one internal stop event:

```python
{"stop": (stop_reason, message, usage, metrics)}
```

This event is consumed by the event loop. It is not directly exposed by
`Agent.stream_async()`.

### Final buffered message shape

`contentBlockStop` is the point where buffered deltas are finalized into content
blocks inside the reconstructed assistant message.

Finalized content blocks can therefore look like:

- `{"text": "..."}`
- `{"toolUse": {"toolUseId": "...", "name": "...", "input": {...}}}`
- `{"citationsContent": {"citations": [...], "content": [{"text": "..."}]}}`
- `{"reasoningContent": {"reasoningText": {"text": "...", "signature": "..."}}}`
- `{"reasoningContent": {"redactedContent": b"..."}}`

## Layer 3: `Agent.stream_async()` Output

`Agent.stream_async()` lives in
[`src/strands/agent/agent.py`](../src/strands/agent/agent.py).

It yields plain dictionaries for callback-eligible events only. In practice,
the consumer can observe the following shapes in the normal agent path.

### Event-loop lifecycle events

```python
{"init_event_loop": True, ...invocation_state}
{"start": True}
{"start_event_loop": True}
```

### Model streaming events

These include all callback-eligible `process_stream()` outputs:

- `{"event": <raw StreamEvent>}`
- `{"data": "...", "delta": ...}`
- `{"type": "tool_use_stream", "delta": ..., "current_tool_use": ...}`
- `{"citation": ..., "delta": ...}`
- `{"reasoningText": ..., "delta": ..., "reasoning": True}`
- `{"reasoning_signature": ..., "delta": ..., "reasoning": True}`
- `{"reasoningRedactedContent": ..., "delta": ..., "reasoning": True}`

For model-stream events that contain a `delta`, `ModelStreamEvent.prepare()`
merges `invocation_state` into the yielded dictionary. This means callers may
see extra keys beyond the base shapes shown here.

### Message events

Both of the following serialize to the same outer shape:

```python
{"message": <Message>}
```

The message may be:

- the assistant message produced by the model
- the synthetic user message that wraps tool results

To distinguish them, inspect `message["role"]` and its content blocks.

### Tool execution events

Tool streaming:

```python
{
    "type": "tool_stream",
    "tool_stream_event": {
        "tool_use": {"toolUseId": "...", "name": "...", "input": {...}},
        "data": <tool-yielded payload>,
    },
}
```

Tool cancellation:

```python
{
    "tool_cancel_event": {
        "tool_use": {"toolUseId": "...", "name": "...", "input": {...}},
        "message": "tool cancelled by user",
    }
}
```

Tool interrupt:

```python
{
    "tool_interrupt_event": {
        "tool_use": {"toolUseId": "...", "name": "...", "input": {...}},
        "interrupts": [...],
    }
}
```

### Retry and forced-stop events

```python
{"event_loop_throttled_delay": 4, ...invocation_state}
{"force_stop": True, "force_stop_reason": "..."}
```

### Final result event

The last outward-facing event from `Agent.stream_async()` is:

```python
{"result": AgentResult(...)}
```

This is the public final result object for the whole agent invocation.

## Events Used Internally but Not Directly Yielded by `Agent.stream_async()`

These exist in the event system but are marked `is_callback_event = False`, so
they are consumed internally:

- `ModelStopReason`
- `ToolResultEvent`
- `EventLoopStopEvent`

They drive the event loop and final `AgentResult`, but they are not directly
yielded to normal `Agent.stream_async()` consumers.

## Typical Sequences

### Plain text answer

```python
{"event": {"messageStart": {"role": "assistant"}}}
{"event": {"contentBlockStart": {"start": {}}}}
{"event": {"contentBlockDelta": {"delta": {"text": "Hello"}}}}
{"data": "Hello", "delta": {"text": "Hello"}}
{"event": {"contentBlockStop": {}}}
{"event": {"messageStop": {"stopReason": "end_turn"}}}
{"event": {"metadata": {...}}}
{"message": {"role": "assistant", "content": [{"text": "Hello"}]}}
{"result": AgentResult(...)}
```

### Tool-use turn

```python
{"event": {"messageStart": {"role": "assistant"}}}
{"event": {"contentBlockStart": {"start": {"toolUse": {"name": "weather", "toolUseId": "tooluse_123"}}}}}
{"event": {"contentBlockDelta": {"delta": {"toolUse": {"input": "{\"city\": \"Paris\"}"}}}}}
{
    "type": "tool_use_stream",
    "delta": {"toolUse": {"input": "{\"city\": \"Paris\"}"}},
    "current_tool_use": {
        "toolUseId": "tooluse_123",
        "name": "weather",
        "input": "{\"city\": \"Paris\"}",
    },
}
{"event": {"contentBlockStop": {}}}
{"event": {"messageStop": {"stopReason": "tool_use"}}}
{"message": {"role": "assistant", "content": [{"toolUse": {...}}]}}
{"type": "tool_stream", "tool_stream_event": {...}}
{"message": {"role": "user", "content": [{"toolResult": {...}}]}}
```

### Reasoning plus final answer

```python
{"event": {"contentBlockDelta": {"delta": {"reasoningContent": {"text": "I should think"}}}}}
{"reasoningText": "I should think", "delta": {"reasoningContent": {"text": "I should think"}}, "reasoning": True}
{"event": {"contentBlockDelta": {"delta": {"reasoningContent": {"signature": "abc-"}}}}}
{"reasoning_signature": "abc-", "delta": {"reasoningContent": {"signature": "abc-"}}, "reasoning": True}
{"event": {"contentBlockStop": {}}}
{"event": {"contentBlockDelta": {"delta": {"text": "Final answer"}}}}
{"data": "Final answer", "delta": {"text": "Final answer"}}
```

### Bedrock citation flow

```python
{"event": {"contentBlockDelta": {"delta": {"text": "The document says ..."}}}}
{"data": "The document says ...", "delta": {"text": "The document says ..."}}
{"event": {"contentBlockDelta": {"delta": {"citation": {...}}}}}
{"citation": {...}, "delta": {"citation": {...}}}
{"event": {"contentBlockStop": {}}}
```

### Guardrail redaction

```python
{"event": {"messageStop": {"stopReason": "guardrail_intervened"}}}
{
    "event": {
        "redactContent": {
            "redactUserContentMessage": "REDACTED",
            "redactAssistantContentMessage": "REDACTED.",
        }
    }
}
```

When this happens, the event loop rewrites the buffered assistant content and
may also redact the latest user message in the agent history.

## Structured Output Is a Separate Path

Some model adapters also support structured-output helpers that yield:

```python
{"output": parsed_model}
```

This is not part of the standard `StreamEvent` chunk contract described above.
It belongs to the structured-output path used by methods that explicitly request
parsed Pydantic output.

## Multi-Agent Wrappers

Swarm and Graph add wrapper event types around normal agent events, including:

- `{"type": "multiagent_result", "result": ...}`
- `{"type": "multiagent_node_start", "node_id": "...", "node_type": "..."}`
- `{"type": "multiagent_node_stop", "node_id": "...", "node_result": ...}`
- `{"type": "multiagent_node_stream", "node_id": "...", "event": <nested agent event>}`
- `{"type": "multiagent_handoff", "from_node_ids": [...], "to_node_ids": [...]}`

These are wrappers around the normal agent/event-loop stream described earlier,
not replacements for it.

## Primary Source Files

Use these files when verifying or updating the behavior documented here:

- [`src/strands/types/streaming.py`](../src/strands/types/streaming.py)
- [`src/strands/types/_events.py`](../src/strands/types/_events.py)
- [`src/strands/event_loop/streaming.py`](../src/strands/event_loop/streaming.py)
- [`src/strands/event_loop/event_loop.py`](../src/strands/event_loop/event_loop.py)
- [`src/strands/agent/agent.py`](../src/strands/agent/agent.py)
- model adapters under [`src/strands/models/`](../src/strands/models/)
