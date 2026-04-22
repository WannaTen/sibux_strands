# Streaming Events 参考

这份文档说明了在 `strands` 主执行路径中，流式过程中可能出现哪些
chunk 和 event 形态。

它主要给以下场景做查阅参考：

- model adapter 作者
- callback handler 作者
- 消费 `Agent.stream_async()` 的应用代码
- 使用 `Agent.invoke_async()` 或 `Agent()` 的应用代码

## 范围

这份参考文档聚焦于标准 agent 流式路径：

1. model adapter 产出标准化的 `StreamEvent` chunks
2. `event_loop.streaming.process_stream()` 将 chunks 转成 typed events
3. `Agent.stream_async()` 将可回调事件以普通字典形式暴露给外部

Swarm、Graph 等 multi-agent wrapper 会在这条路径之上再包一层。文档
末尾会简要说明。

主 agent loop 并不存在另一条独立的“非流式模型执行路径”。标准路径始终
会经过 `model.stream(...)`、`process_stream()` 和 `event_loop_cycle()`。
对外的非流式 API，也就是 `Agent.invoke_async()` 和 `Agent()`，只是把这同
一条事件流消费完，然后返回最终的 `AgentResult`。

## 流式层次

这里有三层输出，很容易混淆：

### 1. 标准化的原始模型 chunks

它们就是定义在
[`src/strands/types/streaming.py`](../src/strands/types/streaming.py)
里的 `StreamEvent` 字典。

示例：

```python
{"messageStart": {"role": "assistant"}}
{"contentBlockStart": {"start": {}}}
{"contentBlockDelta": {"delta": {"text": "Hello"}}}
{"messageStop": {"stopReason": "end_turn"}}
```

### 2. `process_stream()` 的输出

`process_stream()` 会产出两类东西：

- 原始 chunk 包装事件：`{"event": <StreamEvent>}`
- 更高层的增量事件，例如 text/tool/reasoning/citation 更新

这部分逻辑在
[`src/strands/event_loop/streaming.py`](../src/strands/event_loop/streaming.py)
里。

### 3. `Agent.stream_async()` 的输出

`Agent.stream_async()` 会把可回调事件以普通字典形式往外 `yield`，最后再补
上一条：

```python
{"result": AgentResult(...)}
```

像 `ModelStopReason`、`EventLoopStopEvent` 这样的内部 stop 事件会在 event
loop 内部使用，但不会直接由 `Agent.stream_async()` 对外暴露。

## 第 1 层：标准化原始 chunks

`StreamEvent` 顶层 chunk 类型如下：

| 顶层 key | 含义 | 说明 |
| --- | --- | --- |
| `messageStart` | assistant message 开始 | 通常是第一条 chunk |
| `contentBlockStart` | content block 开始 | 可能带 tool 元数据 |
| `contentBlockDelta` | 增量内容载荷 | 可能是文本、tool 输入、citation、reasoning |
| `contentBlockStop` | content block 结束 | 会触发内部缓冲块收口 |
| `messageStop` | assistant message 结束 | 携带 `stopReason` |
| `metadata` | usage 和 metrics | 通常是最后一个 chunk |
| `redactContent` | guardrail 触发的脱敏指令 | 常见于 Bedrock guardrail 流程 |
| `internalServerException` | schema 声明的错误 chunk 类型 | 当前 adapter 中不常见 |
| `modelStreamErrorException` | schema 声明的错误 chunk 类型 | 当前 adapter 中不常见 |
| `serviceUnavailableException` | schema 声明的错误 chunk 类型 | 当前 adapter 中不常见 |
| `throttlingException` | schema 声明的错误 chunk 类型 | 当前 adapter 中不常见 |
| `validationException` | schema 声明的错误 chunk 类型 | 当前 adapter 中不常见 |

schema 定义见
[`src/strands/types/streaming.py`](../src/strands/types/streaming.py)。

### `contentBlockStart`

`contentBlockStart` 常见有两种形态。

普通内容块：

```python
{"contentBlockStart": {"start": {}}}
```

tool-use 内容块：

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

部分 provider 还会在 tool start 上附带 `reasoningSignature`。Gemini 在暴露
thought signature 时会这样做。

不同 provider 可能会带上 `contentBlockIndex`。主 event loop 的缓冲逻辑
并不依赖它。

### `contentBlockDelta`

`contentBlockDelta["delta"]` 是真正有业务信息的部分。基于当前代码，它可
以包含以下子类型。

#### 文本增量

```python
{"contentBlockDelta": {"delta": {"text": "Hello"}}}
```

用于普通 assistant 文本输出。

#### Tool-use 增量

```python
{"contentBlockDelta": {"delta": {"toolUse": {"input": "{\"city\": \"Paris\"}"}}}}
```

tool 输入会以字符串片段的形式流出，并在 `contentBlockStop` 时累计并解析
成 JSON。

#### Citation 增量

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

这类事件通常用于带 citation 的 Bedrock 响应。

#### Reasoning 文本增量

```python
{"contentBlockDelta": {"delta": {"reasoningContent": {"text": "I should call a tool"}}}}
```

#### Reasoning signature 增量

```python
{"contentBlockDelta": {"delta": {"reasoningContent": {"signature": "abc-"}}}}
```

它会追加到 reasoning signature 缓冲区，并在最终收口时和 reasoning 文本一
起落盘到 message。

#### Reasoning redacted-content 增量

```python
{"contentBlockDelta": {"delta": {"reasoningContent": {"redactedContent": b"..."}}}}
```

当 provider 返回的是加密或脱敏后的 reasoning bytes，而不是明文 reasoning
文本时，会走这一路径。

### `messageStop`

主路径里常见的 `stopReason` 如下：

| `stopReason` | 含义 |
| --- | --- |
| `end_turn` | assistant 正常结束输出 |
| `tool_use` | assistant 希望执行工具 |
| `max_tokens` | 模型撞到了输出 token 上限 |
| `guardrail_intervened` | guardrail 中止或替换了输出 |

不同 provider 可能会把自己的 provider-specific stop reason 归一到这个集
合里。

`interrupt` 是后续 event-loop 层面的停止原因，但它不是 model adapter
正常产出的原始 `messageStop` 值。

## 第 2 层：`process_stream()` 事件

`process_stream()` 实现在
[`src/strands/event_loop/streaming.py`](../src/strands/event_loop/streaming.py)。

对于每一个原始 model chunk，它都会先产出：

```python
{"event": <raw StreamEvent>}
```

然后，如果是 `contentBlockDelta`，它还可能再产出一条更高层的增量事件。

### 原始 chunk 包装事件

```python
{"event": {"contentBlockDelta": {"delta": {"text": "Hello"}}}}
```

这个形态保留了完全原始的标准化 chunk，适合那些需要最低层视角的消费方。

### 文本流事件

```python
{"data": "Hello", "delta": {"text": "Hello"}}
```

当 `delta` 里包含 `text` 时产出。

### Tool-use 流事件

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

当 `delta` 里包含 `toolUse` 时产出。`current_tool_use` 表示到当前为止累计
出来的 tool 状态。

### Citation 流事件

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

当 `delta` 里包含 `citation` 时产出。

### Reasoning 文本流事件

```python
{
    "reasoningText": "I should call a tool",
    "delta": {"reasoningContent": {"text": "I should call a tool"}},
    "reasoning": True,
}
```

### Reasoning signature 流事件

```python
{
    "reasoning_signature": "abc-",
    "delta": {"reasoningContent": {"signature": "abc-"}},
    "reasoning": True,
}
```

### Reasoning redacted-content 流事件

```python
{
    "reasoningRedactedContent": b"...",
    "delta": {"reasoningContent": {"redactedContent": b"..."}},
    "reasoning": True,
}
```

### 最终 stop 事件

原始流结束时，`process_stream()` 会产出一条内部 stop 事件：

```python
{"stop": (stop_reason, message, usage, metrics)}
```

这条事件会被 event loop 消费，不会直接暴露给 `Agent.stream_async()` 的消费
方。

### 最终缓冲后的 message 形态

`contentBlockStop` 是内部缓冲增量被收口并写回 assistant message content
blocks 的时机。

因此，最终落到 message 里的 content block 可能长这样：

- `{"text": "..."}`
- `{"toolUse": {"toolUseId": "...", "name": "...", "input": {...}}}`
- `{"citationsContent": {"citations": [...], "content": [{"text": "..."}]}}`
- `{"reasoningContent": {"reasoningText": {"text": "...", "signature": "..."}}}`
- `{"reasoningContent": {"redactedContent": b"..."}}`

## 第 3 层：`Agent.stream_async()` 输出

`Agent.stream_async()` 位于
[`src/strands/agent/agent.py`](../src/strands/agent/agent.py)。

它只会对外产出 callback-eligible 的事件，并且会把这些事件序列化成普通字
典。在正常 agent 路径下，调用方会看到以下形态。

### Event loop 生命周期事件

```python
{"init_event_loop": True, ...invocation_state}
{"start": True}
{"start_event_loop": True}
```

### Model 流式事件

它们包含所有 callback-eligible 的 `process_stream()` 输出：

- `{"event": <raw StreamEvent>}`
- `{"data": "...", "delta": ...}`
- `{"type": "tool_use_stream", "delta": ..., "current_tool_use": ...}`
- `{"citation": ..., "delta": ...}`
- `{"reasoningText": ..., "delta": ..., "reasoning": True}`
- `{"reasoning_signature": ..., "delta": ..., "reasoning": True}`
- `{"reasoningRedactedContent": ..., "delta": ..., "reasoning": True}`

对于带 `delta` 的 model-stream 事件，`ModelStreamEvent.prepare()` 会把
`invocation_state` 合并进最终对外字典里。因此，调用方实际看到的 key 可
能会比这里展示的基础形态更多。

### Message 事件

下面两类事件最终都会序列化成同一个外层字典形态：

```python
{"message": <Message>}
```

这里的 message 可能是：

- model 生成出来的 assistant message
- 为 tool results 合成的 user message

如果要区分这两者，需要继续看 `message["role"]` 以及内部 content blocks。

### Tool execution 事件

工具流式事件：

```python
{
    "type": "tool_stream",
    "tool_stream_event": {
        "tool_use": {"toolUseId": "...", "name": "...", "input": {...}},
        "data": <tool-yielded payload>,
    },
}
```

工具取消事件：

```python
{
    "tool_cancel_event": {
        "tool_use": {"toolUseId": "...", "name": "...", "input": {...}},
        "message": "tool cancelled by user",
    }
}
```

工具中断事件：

```python
{
    "tool_interrupt_event": {
        "tool_use": {"toolUseId": "...", "name": "...", "input": {...}},
        "interrupts": [...],
    }
}
```

### 重试与强制停止事件

```python
{"event_loop_throttled_delay": 4, ...invocation_state}
{"force_stop": True, "force_stop_reason": "..."}
```

### 最终结果事件

`Agent.stream_async()` 对外最后一条事件是：

```python
{"result": AgentResult(...)}
```

它是整个 agent invocation 的公共最终结果对象。

## 面向消费方的暴露矩阵

同一轮 agent 执行，根据调用 API 的不同，对外暴露面并不一样。

| 接口面 | 调用方实际拿到什么 | 说明 |
| --- | --- | --- |
| `event_loop_cycle()` | 内部 `TypedEvent` 对象，包括内部 stop 事件 | 最底层 loop API |
| `Agent.stream_async()` | callback-eligible 的普通字典事件，最后再跟一个 `{"result": AgentResult(...)}` | 主要的流式应用接入面 |
| `Agent.invoke_async()` | 只有最终 `AgentResult` | 内部会消费 `stream_async()` |
| `Agent()` | 只有最终 `AgentResult` | `invoke_async()` 的同步封装 |
| `callback_handler` | 与 `Agent.stream_async()` 相同的 callback-eligible 事件字典，外加最终的 `result=` 回调 | 对流式和非流式调用都成立 |

### `event_loop_cycle()` 会发、但 `Agent.stream_async()` 不会直接发的事件

下面这些事件虽然存在于 loop 中，但普通 `Agent.stream_async()` 消费方不会
直接看到：

- `ModelStopReason`
- `ToolResultEvent`
- `EventLoopStopEvent`

`Agent.stream_async()` 会利用这些内部事件组装最终公共结果，然后对外发出：

```python
{"result": AgentResult(...)}
```

### 面向上层应用的流式 vs 非流式区别

对应用接入方来说，最实用的差异就是：

- `Agent.stream_async()` 是唯一一个会向调用方增量产出事件的公共 API
- `Agent.invoke_async()` 和 `Agent()` 不会把中间事件直接 `yield` 给调用方
- 非流式调用依然会驱动同一套 callback 管线，所以如果配置了
  `callback_handler`，它仍然能收到正常的 callback-eligible 事件流

因此，上层应用如果要消费增量事件，应当把 `Agent.stream_async()` 当作公共
事件流；如果只关心最终结果，则用 `Agent()` 或 `Agent.invoke_async()`。

### 事件可见性矩阵

下表总结了主要 surface 上各类事件的可见性。

| 事件类别 | `event_loop_cycle()` | `Agent.stream_async()` | `Agent.invoke_async()` / `Agent()` |
| --- | --- | --- | --- |
| `InitEventLoopEvent` | 否 | 是 | 否 |
| `StartEvent` / `StartEventLoopEvent` | 是 | 是 | 否 |
| 原始 chunk 包装事件 `{"event": <StreamEvent>}` | 是 | 是 | 否 |
| Text / tool-use / citation / reasoning 增量事件 | 是 | 是 | 否 |
| `EventLoopThrottleEvent` | 是 | 是 | 否 |
| `ModelMessageEvent` | 是 | 是 | 否 |
| `ToolStreamEvent` | 是 | 是 | 否 |
| `ToolCancelEvent` | 是 | 是 | 否 |
| `ToolInterruptEvent` | 是 | 是 | 否 |
| `ToolResultMessageEvent` | 是 | 是 | 否 |
| `ForceStopEvent` | 是 | 是 | 否 |
| `ModelStopReason` | 是 | 否 | 否 |
| `ToolResultEvent` | 是 | 否 | 否 |
| `EventLoopStopEvent` | 是 | 否 | 否 |
| 最终 `{"result": AgentResult(...)}` | 否 | 是 | 否，直接作为 `AgentResult` 返回 |

### 重要的形态冲突

两种不同的事件类，最终会序列化成同一个外层字典形态：

```python
{"message": <Message>}
```

具体来说：

- `ModelMessageEvent` 包的是 model 产出的 assistant message
- `ToolResultMessageEvent` 包的是包含 `toolResult` blocks 的 synthetic user message

如果消费方需要区分它们，应该继续检查：

- `message["role"]`
- content block 类型，尤其是是否存在 `toolResult`

### Tool-use 回环细节

当一轮 tool-use 完成并继续进入下一轮 model 调用时，当前实现还会额外再发
一次 `{"start": True}`。

因此，消费方不要假设 `start` 在一次顶层 invocation 里只会出现一次。

## 存在于内部、但不会被 `Agent.stream_async()` 直接产出的事件

这些事件在事件系统中存在，但被标记为 `is_callback_event = False`，因此会
被内部消费掉：

- `ModelStopReason`
- `ToolResultEvent`
- `EventLoopStopEvent`

它们负责驱动 event loop 和最终 `AgentResult` 的生成，但不会直接暴露给正
常的 `Agent.stream_async()` 消费方。

## 常见事件序列

### 纯文本回答

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

### Tool-use 回合

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

### Reasoning 加最终答案

```python
{"event": {"contentBlockDelta": {"delta": {"reasoningContent": {"text": "I should think"}}}}}
{"reasoningText": "I should think", "delta": {"reasoningContent": {"text": "I should think"}}, "reasoning": True}
{"event": {"contentBlockDelta": {"delta": {"reasoningContent": {"signature": "abc-"}}}}}
{"reasoning_signature": "abc-", "delta": {"reasoningContent": {"signature": "abc-"}}, "reasoning": True}
{"event": {"contentBlockStop": {}}}
{"event": {"contentBlockDelta": {"delta": {"text": "Final answer"}}}}
{"data": "Final answer", "delta": {"text": "Final answer"}}
```

### Bedrock citation 流程

```python
{"event": {"contentBlockDelta": {"delta": {"text": "The document says ..."}}}}
{"data": "The document says ...", "delta": {"text": "The document says ..."}}
{"event": {"contentBlockDelta": {"delta": {"citation": {...}}}}}
{"citation": {...}, "delta": {"citation": {...}}}
{"event": {"contentBlockStop": {}}}
```

### Guardrail 脱敏

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

当出现这种情况时，event loop 会重写缓冲中的 assistant 内容，并且还可能对
agent history 中最新一条 user message 做脱敏。

## Structured Output 是另一条路径

某些 model adapter 还支持 structured-output helper，它们会产出：

```python
{"output": parsed_model}
```

这不属于上面描述的标准 `StreamEvent` chunk 合约。它属于显式请求解析后
Pydantic 输出时使用的 structured-output 路径。

## Multi-Agent 包装层

Swarm 和 Graph 会在普通 agent 事件外面再包一层 wrapper event，例如：

- `{"type": "multiagent_result", "result": ...}`
- `{"type": "multiagent_node_start", "node_id": "...", "node_type": "..."}`
- `{"type": "multiagent_node_stop", "node_id": "...", "node_result": ...}`
- `{"type": "multiagent_node_stream", "node_id": "...", "event": <nested agent event>}`
- `{"type": "multiagent_handoff", "from_node_ids": [...], "to_node_ids": [...]}`

它们是对前面这套普通 agent/event-loop 流的包装层，而不是替代品。

## 主要源码文件

如果后续要验证或更新本文档描述的行为，优先看这些文件：

- [`src/strands/types/streaming.py`](../src/strands/types/streaming.py)
- [`src/strands/types/_events.py`](../src/strands/types/_events.py)
- [`src/strands/event_loop/streaming.py`](../src/strands/event_loop/streaming.py)
- [`src/strands/event_loop/event_loop.py`](../src/strands/event_loop/event_loop.py)
- [`src/strands/agent/agent.py`](../src/strands/agent/agent.py)
- [`src/strands/models/`](../src/strands/models/) 下的各个 model adapter
