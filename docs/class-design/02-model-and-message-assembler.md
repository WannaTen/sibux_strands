# 02. Model / Message 设计

## 1. 职责

Model 负责：
- 接收上层（AgentLoop）组织好的统一输入（`messages[]`、tool specs、请求参数）
- 适配特定 provider 的输入格式并调用模型（接口与命名参考 strands `Model`）
- 将 provider 原始流输出映射为统一 `MessageDelta` 流
- 统一错误映射（provider error -> 框架错误码）
- 提供模型配置的读写入口（`update_config/get_config`）

Model 不负责：
- 组织 `messages[]`（上层负责）
- context 裁剪与 compaction
- session 持久化
- agent loop 编排与重试策略（策略由上层决定）
- tool 执行


## 2. 初始化

### 2.1 Model

初始化输入（示意）：

```text
ModelInit:
  client: ProviderClient
  config: ModelConfig (required)
  cacheConfig: CacheConfig (optional)
  errorMapper: ErrorMapper (optional)
```

初始化流程：
- 校验 config 结构（由实现定义）
- 绑定 provider client
- 合并默认 config

失败策略：
- 输入非法直接抛错
- 不在 init 做网络探活，避免阻塞启动

## 3. 字段定义

### 3.1 Model

```text
Model fields:
  config: ModelConfig
  client: ProviderClient
  cacheConfig: CacheConfig (optional)
  errorMapper: ErrorMapper (optional)
```


### 3.3 Message / MessageDelta（类级结构）

```text
Message:
  runId: text
  role: system | user | assistant | tool
  parts: MessagePart[]
  timestamp: text
  meta: map (optional)

MessagePart:
  kind: text | thinking | tool_call | tool_result | image | file_ref
  payload: object

MessageDelta:
  runId: text
  seq: integer
  kind: start | text | thinking | tool_call_start | tool_call_args | tool_call_end | usage | done | error
  payload: object
  timestamp: text
  providerRaw: object (optional)
```

payload 约定（最小集）：

- `start`: { modelId, requestId }
- `tool_call_start`: { toolCallId, toolName }
- `tool_call_args`: { toolCallId, argsTextDelta }
- `tool_call_end`: { toolCallId }
- `done`: { finishReason }
- `usage`: { inputTokens, outputTokens, totalTokens, cost? }

## 4. 方法定义

### 4.1 Model

```text
update_config(**modelConfig) -> no return
get_config() -> ModelConfig
stream(messages, toolSpecs, systemPrompt?, *, toolChoice?, systemPromptContent?, invocationState?, **params) -> AsyncStream<MessageDelta>
modelInfo() -> ModelInfo
```

`stream(...)` 输入：

```text
messages: Message[]
toolSpecs: ToolSpec[] (optional)
systemPrompt: text (optional)
requestMetadata: {sessionId, runId, traceId} (optional)
```

ModelConfig（provider-specific，示意）：

```text
ModelConfig:
  modelId: text
  temperature: decimal (optional)
  maxTokens: integer (optional)
  topP: decimal (optional)
  stopSequences: text[] (optional)
  toolChoice: ToolChoice (optional)
  cacheConfig: CacheConfig (optional)
  ... (允许 provider 自定义扩展字段)
```


CacheConfig（参考 strands）：

```text
CacheConfig:
  strategy: auto
```

ToolSpec（模型可见的工具 schema，示意）：

```text
ToolSpec:
  name: text
  description: text (optional)
  parameterSchema: json schema
  strict: boolean (optional)
```

说明：
- `ToolSpec` 由上层传入

ToolChoice（工具选择策略）：

```text
ToolChoice:
  auto | required | none | specific-tool
```

错误语义：
- provider error 必须映射为框架错误码
- 仅支持流式输出，stream 必须以 `done` 或 `error` 结束
说明：
- Model 内部使用 provider stream event，但对外统一输出 `MessageDelta`

## 5. 状态与不变量

### 5.1 Model
状态：
- `idle` -> `started` -> `done`
- `idle` -> `started` -> `error`

不变量：
- 每个 stream 必须以且仅以一个 `done` 或 `error` 终止
- `start` 必须是首个 delta
- `seq` 必须严格递增
- `tool_call_start` 必须与 `tool_call_end` 成对
- `tool_call_args` 必须可拼接为合法 JSON

## 6. 数据流与依赖

上游依赖：
- Model 依赖 provider client
- Model 依赖 provider client

下游依赖：
- AgentLoop 依赖 Model 请求
- SessionStore 依赖最终 `Message`

输入输出边界：
- Model 输入 `stream(...)` 参数，输出 `MessageDelta` 流

## 7. v0 决策

- `stream` 是唯一入口（仅流式输出）
- 上层负责组织 `messages[]`（包含 system prompt 或 runtime hints）
- `stream` 默认只组装一条 assistant message
- `MessageDelta` 采用最小集合（start/text/thinking/tool_call*/usage/done/error）
- provider 私有字段只放在 `providerRaw`，不上抛到上层逻辑
- tool call 只从最终 assistant message 解析

## 8. 开放问题

- `usage` 累计（建议固定为累计）
- 不支持单次 stream 输出多条 assistant message
- `thinking` 默认可见，Model 层不管
