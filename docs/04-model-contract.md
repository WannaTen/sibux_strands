# 04. Model 契约

## 目标

屏蔽厂商差异，在模型层把 provider 原始流序列化为统一 `MessageDelta`，上层只处理统一协议。

## 统一输入

- `messages[]`（由上层组织好的统一 messages；可包含 system prompt）
- `toolSpecs[]`
- `modelParams`（调用期参数，如 temperature、max_tokens、tool_choice 等）
- `requestMetadata`（sessionId, runId, traceId）
- `systemPrompt` / `systemPromptContent`（可选，用于模型特性如缓存）
- `invocationState`（可选，上层透传上下文）

模型配置（provider-specific）：

- 通过 `update_config/get_config` 读写，允许扩展字段

## 统一输出（`MessageDelta` 流）

- `start`
- `text`
- `thinking`
- `tool_call_start`
- `tool_call_args`
- `tool_call_end`
- `usage`
- `done`
- `error`

## 接口建议（语言无关）

```text
Model.update_config(**modelConfig) -> no return
Model.get_config() -> ModelConfig
Model.stream(messages, toolSpecs, systemPrompt?, *, toolChoice?, systemPromptContent?, invocationState?, **params)
  -> AsyncStream<MessageDelta>
Model.modelInfo() -> ModelInfo
```

说明：

- v0 仅支持流式输出，`stream` 为唯一模型调用入口

## `MessageDelta` 最小结构

```text
MessageDelta {
  runId: string
  seq: number
  kind: "start" | "text" | "thinking" | "tool_call_start" |
        "tool_call_args" | "tool_call_end" | "usage" | "done" | "error"
  payload: object
  timestamp: string
  providerRaw?: object
}
```

## 关键策略（参考 strands / pi-mono 思路）

- 流式差异抹平发生在 `Model` 内部，不上抛 provider 私有结构
- 框架核心消费统一 `MessageDelta`，在 AgentLoop 内聚合最终 `Message`
- 上层业务（loop/context/session/hitl）只依赖 `Message` 与 `MessageDelta`
- `providerRaw` 只用于调试与审计，不参与业务逻辑分支

## 流边界约束

- 每次 `stream` 必须先产生一个 `start`
- 每个流必须以且仅以一个 `done` 或 `error` 终止
- `seq` 在当前 stream 内严格递增
- `tool_call_args` 允许多次增量，需可拼接成合法参数
- 单次 `stream` 默认只组装一条 assistant message

## 错误约定

- `ModelTimeout`
- `ModelRateLimited`
- `ModelContextOverflow`
- `ModelAuthError`
- `ModelUnknownError`

错误统一映射到框架错误码，禁止直接向上泄露 provider 私有异常类型。
