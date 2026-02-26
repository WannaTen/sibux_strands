# 05. ToolRegistry / ToolExecutor / Runtime 设计

## 1. 职责

ToolRegistry 负责：
- 注册与管理 `ToolDefinition`
- 校验工具名与 schema
- 生成 `ToolSpec[]`（供 Model 输入）
- 解决工具名冲突与版本替换
- 记录工具对 `agent` / `runtime` 的依赖需求（不注入）

ToolRegistry 不负责：
- 工具执行
- 工具审批策略
- 工具输出的持久化

ToolExecutor 负责：
- 执行工具调用（ToolCall -> ToolResult）
- 支持顺序/并发执行策略
- 处理超时、取消、审批、错误映射
- 在执行时注入 `agent` / `runtime`（按工具声明）

ToolExecutor 不负责：
- 工具注册与 schema 校验
- 上层 agent loop 编排

Runtime 负责：
- 与外部执行环境交互（命令、文件、浏览器、网络等）
- 维护 runtime 状态与能力描述
- 为工具提供安全的执行边界

Runtime 不负责：
- 业务级工具语义（由 ToolDefinition 实现）
- context 管理与消息组装

## 2. 初始化

### 2.1 ToolRegistry

```text
ToolRegistryInit:
  allowNameDuplicates: boolean (optional)
  nameCollisionResolver: ToolNameResolver (optional)
```

### 2.2 ToolExecutor

```text
ToolExecutorInit:
  executionMode: sequential | concurrent
  maxParallel: integer (optional)
  timeoutMs: integer (optional)
  approvalPolicy: ApprovalPolicy (optional)
```

### 2.3 Runtime（参考 OpenHands，v0 仅本地）

```text
RuntimeInit:
  sandboxConfig: SandboxConfig
  plugins: PluginRequirement[] (optional)
  statusCallback: fn(status, msg) (optional)
```

## 3. 字段定义

```text
ToolRegistry fields:
  definitionsByName: map<toolName, ToolDefinition>
  allowNameDuplicates: boolean
  nameCollisionResolver: ToolNameResolver (optional)
```

```text
ToolExecutor fields:
  executionMode: sequential | concurrent
  maxParallel: integer
  timeoutMs: integer
  approvalPolicy: ApprovalPolicy (optional)
```

```text
Runtime fields:
  status: RuntimeStatus
  capabilities: RuntimeCapabilities
  sandboxConfig: SandboxConfig
  plugins: PluginRequirement[] (optional)
```

## 4. 方法定义

### 4.1 ToolRegistry

```text
registerDefinitions(defs: ToolDefinition[]) -> no return
getDefinition(name: text) -> ToolDefinition | null
listDefinitions() -> ToolDefinition[]
buildModelToolSpecs(order?: text[]) -> ToolSpec[]
unregisterDefinition(name: text) -> no return
```

语义说明：
- `buildModelToolSpecs` 只做 schema 提取与排序（不做过滤策略）
- 冲突处理由 `nameCollisionResolver` 或覆盖策略决定
- ToolRegistry 仅记录 `requiresRuntime/Agent`，不做注入

### 4.2 ToolExecutor

```text
executeToolCall(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult
executeToolCalls(calls: ToolCall[], ctx: ToolExecutionContext) -> ToolResult[]
```

`ToolExecutionContext`（示意）：

```text
ToolExecutionContext:
  sessionId: text
  runId: text
  agent: Agent (optional)
  runtime: Runtime (optional)
  callState: map (optional)
```

语义说明：
- `executeToolCalls` 在并发模式下必须保证每个 toolCallId 只执行一次
- 审批策略在执行前生效（approve/deny/modify）
- ToolExecutor 在执行前为工具注入 `agent/runtime`（按工具声明）
- 若工具声明 `requiresRuntime/Agent` 且缺失，对应调用应失败并返回标准化 tool error
- 超时/取消应返回标准化 tool error result

### 4.3 Runtime（参考 OpenHands，v0 仅本地）

```text
connect() -> no return
close() -> no return
status() -> RuntimeStatus
capabilities() -> RuntimeCapabilities
execute(action: RuntimeAction, signal?) -> RuntimeObservation
getInitData() -> map
getHints() -> map
```

`RuntimeAction`（示意）：

```text
RuntimeAction:
  kind: cmd_run | file_read | file_write | file_edit | browse | browse_interactive | ipython | mcp
  payload: object
```

`RuntimeObservation`（示意）：

```text
RuntimeObservation:
  kind: cmd_output | file_read | file_write | file_edit | browse_result | error
  payload: object
```

语义说明：
- v0 仅支持 `LocalRuntime`（本地环境），远程/容器化 runtime 暂缓
- `connect` 负责初始化本地 sandbox（可异步）
- `execute` 必须在 READY 状态下调用
- runtime 可暴露 `copyTo/copyFrom/listFiles` 等扩展方法

## 5. 数据结构

### ToolDefinition（参考 strands / agno / smolagents 思路）

```text
ToolDefinition:
  name: text
  description: text
  parameterSchema: json schema
  execute(input, ctx) -> ToolResult
  timeoutMs: integer (optional)
  requiresApproval: boolean
  requiresRuntime: boolean (optional)
  requiresAgent: boolean (optional)
```

### ToolSpec（供 Model）

```text
ToolSpec:
  name: text
  description: text (optional)
  parameterSchema: json schema
  strict: boolean (optional)
```

说明：
- `ToolSpec` 仅用于 Model 输入，不包含 `agent/runtime` 依赖信息
- `agent/runtime` 由 `ToolExecutionContext` 在执行时注入，不影响 model 侧参数选择
- 工具实现可按需读取 `ctx.agent/ctx.runtime`，不需要则忽略

## 6. 状态与不变量

- ToolRegistry 中 tool name 必须唯一（或由 resolver 显式映射）
- ToolExecutor 必须保证 toolCallId 幂等
- Runtime 必须提供明确的 READY/FAILED 状态

## 7. 数据流与依赖

上游依赖：
- Agent 传入 ToolDefinition
- Runtime 提供执行环境

下游依赖：
- Model 使用 ToolSpec
- SessionStore 持久化 tool_result message

输入输出边界：
- ToolRegistry：输入 ToolDefinition[]，输出 ToolSpec[]（`buildModelToolSpecs`）
- ToolExecutor：输入 ToolCall，输出 ToolResult
- Runtime：输入 RuntimeAction，输出 RuntimeObservation

## 8. v0 决策

- ToolRegistry 只做注册与 schema 提取
- ToolExecutor 支持顺序/并发两种策略
- Runtime 以 `execute(action)` 作为统一入口
- tool 执行结果必须写入 tool_result message
- runtime 仅实现 `LocalRuntime`，remote 暂缓
- runtime 只有在工具声明 `requiresRuntime` 时才需要初始化

## 9. 开放问题

- 是否需要 tool streaming 输出（partial tool results）
- 是否需要 registry 层的版本化/命名空间
- runtime capability 如何标准化（browser/network/git 等）
