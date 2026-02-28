# 06. AgentLoop / StateMachine 设计

## 1. 职责

AgentLoop 负责：
- 运行单次 `run` 的状态机编排
- 调用 ContextManager 生成本轮 model 输入
- 调用 Model 流式输出，并聚合为最终 assistant message
- 解析 tool calls，交给 ToolExecutor 执行并落库结果
- 处理 retry/overflow/hitl 等运行期策略
- 维护 run 级别幂等与边界条件（时间/轮次/工具次数）

AgentLoop 不负责：
- 工具定义与 schema 管理（ToolRegistry 负责）
- 消息裁剪/压缩策略本身（ContextManager 负责）
- 持久化存储实现细节（SessionStore 负责）
- 模型厂商差异抹平（Model 负责）

## 2. Agent vs AgentLoop

- Agent 是对外入口与生命周期容器：校验输入、合并配置、装配依赖、生成 run 级参数。
- AgentLoop 是执行引擎：只消费 deps 与本次 run 的参数，推进状态机。
- 因此 AgentLoop **不持有 AgentConfig**，它只接收 **Agent 预处理后的 RunInput**。
- 选择保留 AgentLoop 实体（但保持内部可替换）：
  - 测试与回放更容易（可注入 fake deps）
  - 运行策略可替换（HITL/自动化/调试回放）
  - 观测与故障隔离更清晰（loop 维度的事件与指标）
  - Agent 仍保持轻量 API 与生命周期职责，不被执行细节污染

## 3. 初始化

```text
AgentLoopInit:
  model: Model (required)
  contextManager: ContextManager (required)
  sessionStore: SessionStore (required)
  toolRegistry: ToolRegistry (required)
  toolExecutor: ToolExecutor (required)
  runtime: Runtime (optional)
  deltaAggregation: DeltaAggregation (optional)
  observer: ObserverHub (optional)
  idGenerator: IdGenerator (optional)
```

说明：
- `runtime` 仅在工具声明 `requiresRuntime` 时要求可用
- `messageAssemblerFactory` 允许替换默认聚合器实现
- 依赖在 init 后只读，不允许运行期替换

## 4. 字段定义

```text
AgentLoop fields:
  model: Model
  contextManager: ContextManager
  sessionStore: SessionStore
  toolRegistry: ToolRegistry
  toolExecutor: ToolExecutor
  runtime: Runtime (optional)
  deltaAggregation: DeltaAggregation
  observer: ObserverHub
  idGenerator: IdGenerator
```

## 5. 方法定义

```text
run(input: RunInput) -> RunResult
runStream(input: RunInput) -> AsyncStream<RunEvent>
abort(runId: text) -> no return
```

`RunInput`（示意）：

```text
RunInput:
  sessionId: text (optional)
  runId: text (optional)
  inputMessages: Message[]
  systemPromptOverride: text (optional)
  allowedTools: text[] (optional)
  toolOrder: text[] (optional)
  toolPolicy: ToolPolicy (optional)
  loopLimits: LoopLimits (optional)
  autoCreateSession: boolean (optional)
  runtimeInitData: map (optional)
  runtimeHints: map (optional)
  agentRef: Agent (optional)
```

`ToolPolicy`（示意）：

```text
ToolPolicy:
  enabled: boolean (optional)
  allowList: text[] (optional)
  maxParallel: integer (optional)
  maxCallsPerRun: integer (optional)
  requireApprovalByDefault: boolean (optional)
```

`LoopLimits`（示意）：

```text
LoopLimits:
  maxIterations: integer (optional)
  maxToolRounds: integer (optional)
  maxRunDurationMs: integer (optional)
```

`RunResult`（示意）：

```text
RunResult:
  sessionId: text
  runId: text
  status: completed | failed | aborted
  finalAssistantMessage: Message (optional)
  lastError: Error (optional)
  usage: UsageSummary (optional)
```

`RunEvent`（示意）：

```text
RunEvent:
  kind: model_delta | assistant_message | tool_result | status | error
  payload: object
```

语义说明：
- `run` 为非流式入口，内部可复用 `runStream` 聚合最终结果
- `runStream` 只透传统一 `MessageDelta` 与标准化事件，不暴露 provider 原始流
- `abort(runId)` 仅终止当前 run，不修改历史 session
- `runId` 未提供时由 `idGenerator` 生成；`sessionId` 未提供且 `autoCreateSession=true` 时自动创建

## 6. 关键流程（伪代码）

```text
initialize_run(sessionId, runId)
sessionEntries = sessionStore.loadSessionEntries(sessionId)
modelCallIndex = 0
state = preparing
inputMessages = input.inputMessages
toolOrder = input.toolOrder
toolPolicy = input.toolPolicy
loopLimits = input.loopLimits
agentRef = input.agentRef

while true:
  modelCallIndex += 1
  state = model_running

  if modelCallIndex > 1:
    inputMessages = []

  toolNames = resolveAllowedTools(toolPolicy, input.allowedTools)
  toolSpecs = toolRegistry.buildModelToolSpecs(order=toolOrder or toolNames)

  ctx = contextManager.buildContext({
    sessionEntries,
    inputMessages,
    systemPromptOverride,
    runtimeInitData,
    runtimeHints,
    toolSpecs
  })
  sessionStore.appendSessionEntries(sessionId, ctx.entriesToAppend)
  sessionEntries = sessionEntries + ctx.entriesToAppend
  contextMessages = ctx.modelMessages
  modelToolSpecs = ctx.modelToolSpecs

  assembler = messageAssemblerFactory.create(runId)
  deltaStream = model.stream(
    messages=contextMessages,
    toolSpecs=modelToolSpecs,
    requestMetadata={sessionId, runId, modelCallIndex}
  )

  for delta in deltaStream:
    dedupe_by(runId, modelCallIndex, delta.seq)
    assembler.consume(delta)
    emit RunEvent(model_delta)

  assistantMessage = assembler.buildFinalMessage()
  assistantEntry = messageEntry(assistantMessage)
  sessionStore.appendSessionEntries(sessionId, [assistantEntry])
  sessionEntries = sessionEntries + [assistantEntry]
  emit RunEvent(assistant_message)

  if overflowHint or model_token_overflow:
    ctxUpdate = contextManager.computeContextUpdates({
      sessionEntries,
      newMessages=[assistantMessage],
      overflowHint=true
    })
    sessionStore.appendSessionEntries(sessionId, ctxUpdate.entriesToAppend)
    sessionEntries = sessionEntries + ctxUpdate.entriesToAppend
    continue

  calls = extract_tool_calls(assistantMessage)
  if calls is empty:
    state = completed
    break

  state = tool_running
  results = toolExecutor.executeToolCalls(calls, {
    sessionId,
    runId,
    agent: agentRef,
    runtime
  })
  toolMessages = to_tool_result_messages(results)
  toolEntries = messageEntries(toolMessages)
  sessionStore.appendSessionEntries(sessionId, toolEntries)
  sessionEntries = sessionEntries + toolEntries
  emit RunEvent(tool_result)

finish_run()
```

说明：
- `toolSpecs` 只用于 Model，`agent/runtime` 由 ToolExecutor 注入
- `messageAssemblerFactory` 可被替换为内联聚合器（不强制暴露成公共类）
- 当 `ContextManager` 返回 `entriesToAppend` 必须持久化，保持可回放
- 若 model 在产出 assistant message 前抛出 `tokenOverflow`，`computeContextUpdates` 可在无 `newMessages` 情况下调用
- `resolveAllowedTools` 需对 `toolPolicy.allowList` 与 `input.allowedTools` 做交集，缺省则视为全量
- `loopLimits` 中的最大轮次与超时必须生效，达到上限后应终止 run 并标记失败或中止
- ToolExecutor 触发审批等待时，AgentLoop 进入 `awaiting_human` 并向上游发出状态事件

## 7. 状态机

状态：
- `idle`
- `preparing`
- `model_running`
- `tool_running`
- `awaiting_human`
- `completed`
- `failed`
- `aborted`

迁移触发：
- `run()`：`idle -> preparing`
- `buildContext` 完成：`preparing -> model_running`
- 无工具调用：`model_running -> completed`
- 有工具调用：`model_running -> tool_running`
- 工具需要审批：`tool_running -> awaiting_human`
- 审批通过：`awaiting_human -> tool_running`
- 审批拒绝：`awaiting_human -> model_running`
- 失败：`model_running/tool_running -> failed`
- 用户中止：任意运行态 -> `aborted`

## 8. 幂等与一致性

- `runId + modelCallIndex + delta.seq` 用于流式去重
- `toolCallId` 保证工具执行幂等
- session 写入失败必须中断 run，避免内存态与持久态分叉
- 在相同 `sessionEntries + runtimeInitData + systemPrompt` 下，`buildContext` 必须输出一致的 `modelMessages`

## 9. v0 决策

- 仅支持模型流式输出
- 模型与工具调用严格分段，不交叠执行
- 默认顺序执行工具；并发由 ToolExecutor 策略决定
- overflow 触发 `computeContextUpdates` 后重试模型调用

## 10. 开放问题

- `runStream` 的事件协议是否需要稳定化（RunEvent schema）
- tool call 是否允许 partial streaming 结果
- 是否需要 turnId（除了 runId）
