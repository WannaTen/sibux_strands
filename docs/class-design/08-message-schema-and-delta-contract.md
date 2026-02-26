# 08. Message Schema / Delta Contract 设计

## 1. 目标

- 冻结跨模块通用的 `Message` 与 `MessageDelta` 结构
- 明确流式输出到最终 message 的拼装规则
- 为工具调用与结果消息提供统一约束

## 2. 适用范围

- Model 输出统一 `MessageDelta`
- AgentLoop/Assembler 聚合为最终 `Message`
- SessionStore 以 `message` entry 作为事实来源

## 3. 数据结构

### 3.1 Message

```text
Message:
  runId: text
  role: system | user | assistant | tool
  parts: MessagePart[]
  timestamp: text
  meta: map (optional)
```

### 3.2 MessagePart

```text
MessagePart:
  kind: text | thinking | tool_call | tool_result | image | file_ref
  payload: object
```

常见 payload（示意）：

```text
text: { text }
thinking: { text }
tool_call: { toolCallId, toolName, arguments, rawArgsText? }
tool_result: { toolCallId, isError, content }
image: { mimeType, data? | url? }
file_ref: { path, mimeType?, size? }
```

角色约束（建议）：

- `system`：只包含 `text/thinking`
- `user`：`text/image/file_ref`
- `assistant`：`text/thinking/tool_call`
- `tool`：只包含 `tool_result`

说明：
- `parts` 顺序不可重排
- `tool_call` 允许多个；`tool_result` 应单条对应一个 `toolCallId`
- `meta` 用于携带 usage、trace、审批记录等非核心字段

### 3.3 ToolCall / ToolResult（便于约定）

```text
ToolCall:
  toolCallId: text
  toolName: text
  arguments: object

ToolResult:
  toolCallId: text
  isError: boolean
  content: MessagePart[] | object | text
```

## 4. MessageDelta 合约

```text
MessageDelta:
  runId: text
  seq: integer
  kind: start | text | thinking | tool_call_start | tool_call_args | tool_call_end | usage | done | error
  payload: object
  timestamp: text
  providerRaw: object (optional)
```

payload 最小集合（示意）：

```text
start: { modelId, requestId }
text: { textDelta }
thinking: { textDelta }
tool_call_start: { toolCallId, toolName }
tool_call_args: { toolCallId, argsTextDelta }
tool_call_end: { toolCallId }
usage: { inputTokens, outputTokens, totalTokens, cost? }
done: { finishReason }
error: { errorCode, message?, retryable? }
```

## 5. 聚合规则（Delta -> Message）

- `start` 必须是首个 delta
- `done` 或 `error` 必须且只能出现一次作为终止
- `seq` 在单次 stream 内严格递增
- `text/thinking` 按序拼接为单个 part
- `tool_call_args` 以 `toolCallId` 聚合为完整 JSON 字符串
- `tool_call_end` 触发 JSON 解析，失败则保留 `rawArgsText` 并标记解析失败（放入 `meta`）
- `usage` 汇总到 `Message.meta` 或独立统计结构
- `error` 终止时不产出最终 assistant message（由上层决定是否重试）

## 6. 约束与不变量

- `toolCallId` 在同一 `runId` 内必须唯一
- 每个 `toolCallId` 最终只能有一个 terminal `tool_result`
- `tool_result` 必须可追溯到已出现的 `tool_call`
- `MessageDelta.providerRaw` 仅用于调试，不参与业务逻辑

## 7. v0 决策

- 仅支持流式输出；`MessageDelta` 为唯一模型输出协议
- `MessagePart.kind` 先冻结最小集合，新增需版本化
- `tool_result` 必须落库为 `message` entry

## 8. 开放问题

- 是否引入 `messageId/turnId`
- 多模态 payload 的标准化范围
- `tool_result` 是否允许大对象分片传输
