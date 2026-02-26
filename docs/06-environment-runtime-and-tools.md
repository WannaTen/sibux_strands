# 06. Environment（Runtime + Tools）

## Runtime 抽象（v0 仅本地）

Runtime 负责与外部执行环境交互，典型能力：

- 文件读写
- 命令执行
- 进程控制
- 网络访问（可选）
- 浏览器操作（可选）

接口建议：

```text
runtime.connect() -> no return
runtime.close() -> no return
runtime.status() -> RuntimeStatus
runtime.capabilities() -> RuntimeCapabilities
runtime.execute(action, signal) -> RuntimeObservation
runtime.getInitData() -> map
runtime.getHints() -> map
```

v0 约束：

- 仅实现 `LocalRuntime`（本地环境）
- remote/container runtime 暂缓实现
- runtime 仅在工具声明 `requiresRuntime` 时需要初始化
- v0 允许显式注入 runtime，但默认不自动创建

## Tool 体系

### ToolDefinition

- `name`
- `description`
- `parameterSchema`
- `execute(input, ctx)`
- `requiresApproval`
- `timeoutMs`
- `requiresRuntime`（optional）
- `requiresAgent`（optional）

### ToolSpec（供 Model）

- `name`
- `description`
- `parameterSchema`
- `strict`（optional）

说明：`ToolSpec` 由 `ToolDefinition` 派生，仅用于 Model 输入，不包含 `agent/runtime` 依赖信息

### ToolRegistry

- 注册、查找、校验 schema
- 解决工具名冲突
- `buildModelToolSpecs(order?)`：按顺序提取 schema
- 记录工具 `requiresAgent/Runtime` 需求（不注入）

### ToolExecutor

- `sequential`
- `concurrent`
- 支持超时、取消、重试
- `executeToolCall(call, ctx)` / `executeToolCalls(calls, ctx)`
- 执行时按工具声明注入 `agent/runtime`

`ToolExecutionContext`（示意）：

- `agent`（optional）
- `runtime`（optional）
- `runId/sessionId/traceId`（optional）

说明：工具实现可按需读取 `ctx.agent/ctx.runtime`，不需要则忽略

## HITL/HITP 接入点

- 执行前审批：高风险工具
- 执行中暂停：长时命令
- 执行后确认：结果回写前（可选）

## 数据写入约束

- 每次工具执行都必须落两类 message：
  - assistant message 中的 `tool_call` part（由模型输出）
  - tool message 中的 `tool_result` part（由工具执行结果生成）
- 审批决策与执行元数据可作为 message meta 或 session 附加 entry 落库
