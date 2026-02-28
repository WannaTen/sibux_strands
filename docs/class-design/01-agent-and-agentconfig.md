# 01. Agent / AgentConfig / AgentDeps 设计

## 1. 文档目标

这篇只冻结三件事：

- `AgentConfig` 是什么（策略参数）
- `AgentDeps` 是什么（运行时能力）
- `Agent` 初始化和 tools 来源如何定义

## 2. 参考框架后的收敛结论

参考 `strands / pi-mono / pydantic-ai / smolagents / agno / camel` 后，Agent 初始化参数里最常见的核心维度是：

- identity：`name / id / description`
- prompt：`system prompt / instructions`
- model：`model + model settings`
- tools：`tools 列表 + tool 调用策略`
- session/memory：`session id / history / memory policy`
- loop control：`max steps / timeout / retry`
- streaming：`stream 开关与增量策略`
- observability：`hooks / callbacks / tracing`

## 3. 核心定义（单一来源）

### 3.1 AgentConfig

`AgentConfig` = 可持久化的策略参数集合，用于描述“Agent 应该如何运行”。

### 3.2 AgentDeps

`AgentDeps` = 运行时依赖实例集合，用于描述“Agent 运行所需的服务/基础设施”。
（例如 model/session/context/runtime/tool execution 等；**不包含工具定义列表**）

### 3.3 Agent

`Agent` = `Agent.create(...)` 的唯一输入对象。

```text
Agent:
  config: AgentConfig (optional)
  deps: AgentDeps (required)
  tools: ToolDefinition[] (optional)
```

说明：

- `config` 未传时使用默认 `AgentConfig`
- `tools` 是 **Agent 自身能力清单**（工具定义列表），用于“创建时注册工具”
- `ToolRegistry` 是工具**容器/索引**，由 Agent 内部创建或由 deps 注入，但不代表“工具列表本身”

## 4. 边界规则（避免混淆）

- `AgentConfig` 可序列化、可持久化、可版本化
- `AgentDeps` 不序列化，仅运行期注入
- `AgentConfig` 不允许持有可执行对象实例
- `AgentDeps` 不允许存放策略参数
- `tools`（ToolDefinition 列表）属于 **Agent 本体能力**，不放在 `AgentDeps`
- `ToolRegistry` 只是工具容器，可由 Agent 内部创建或由 deps 注入
- `ToolRegistry` 不注入 `agent/runtime`，执行时由 `ToolExecutor` 注入
- `Agent` 读取策略只从 `AgentConfig`，调用能力只从 `AgentDeps`

## 5. AgentConfig（v0 结构）

```text
AgentConfig:
  identity:
    name: text
    description: text (optional)

  prompt:
    system: text or template
    variables: key-value map (optional)
    appendTimeHint: boolean
    appendRuntimeHint: boolean

  model:
    provider: text
    model: text
    temperature: decimal (optional)
    maxTokens: integer (optional)
    timeoutMs: integer (optional)
    toolChoice: auto | required | none | specific-tool (optional)

    retry:
      maxAttempts: integer
      backoffMs: integer
      (optional)

  context:
    maxInputTokens: integer
    maxHistoryMessages: integer
    enableCompaction: boolean

  toolsPolicy:
    enabled: boolean
    allowList: tool-name list (optional)
    maxParallel: integer
    maxCallsPerRun: integer (optional)
    requireApprovalByDefault: boolean

  loop:
    maxIterations: integer
    maxToolRounds: integer
    maxRunDurationMs: integer

  runtimePolicy:
    profile: text
    sandboxMode: text (optional)
    workingDirectory: text (optional)

  session:
    autoCreate: boolean
    persistDelta: boolean

  observability:
    enableTrace: boolean
    enableMetrics: boolean
    logLevel: debug | info | warn | error
```

说明：

- system prompt 定义源统一在 `config.prompt.system`
- 最终 system prompt 在每轮由 `ContextManager` 组装（可拼接时间/runtime hints）

## 6. AgentDeps（v0 结构）

```text
AgentDeps:
  model: Model (required)
  sessionStore: SessionStore (required)
  contextManager: ContextManager (required)
  toolExecutor: ToolExecutor (required)
  runtime: Runtime (optional)

  toolRegistry: ToolRegistry (optional)
  deltaAggregation: DeltaAggregation (optional)
  observer: ObserverHub (optional)
  idGenerator: IdGenerator (optional)
```

默认注入（optional）：

- `runtime` -> `LocalRuntime`（仅当有工具声明需要 runtime）
- `toolRegistry` -> `DefaultToolRegistry`
- `deltaAggregation` -> `DefaultDeltaAggregation`
- `observer` -> `NoopObserver`
- `idGenerator` -> `UuidGenerator`

## 7. Tools 定义放哪里（明确规则）

工具定义与来源分三层：

1. 定义层：`ToolDefinition`
- 放在类型层（领域模型，包含 `execute` 与依赖声明）

2. 模型层：`ToolSpec`
- 由 `ToolRegistry` 从 `ToolDefinition` 提取 schema 生成，仅供 Model 输入

3. 注入层：`Agent.tools` / `AgentInit.tools`
- 在 `Agent.create()` 时注册到 **Agent 的 `ToolRegistry`**
- 这是“当前 agent 初始可用工具”

4. 运行层：`run(..., allowedTools)`
- 只做子集过滤，不新增工具

补充：
- `agent/runtime` 只在工具执行时由 `ToolExecutor` 作为上下文注入

优先级：

- 可用工具全集 = Agent 内部 `toolRegistry`（含 init 注册工具）
- 每次 run 的实际工具 = 可用工具全集 与 `allowedTools` 的交集（如果传了）

## 8. Agent 类设计（v0）

### 8.1 类成员

```text
Agent fields:
  config: AgentConfig
  state: AgentState

  toolRegistry: ToolRegistry (agent-owned)

  model: Model
  sessionStore
  contextManager
  runtime? (optional)
  toolExecutor

  messageAssemblerFactory
  observer
  idGenerator
```

### 8.2 对外方法

```text
Agent:
  create(init) -> Agent

  run(inputMessage, options{sessionId optional, runId optional, allowedTools optional, systemPromptOverride optional}) -> RunResult
  runStream(inputMessage, options{sessionId optional, runId optional, allowedTools optional, systemPromptOverride optional}) -> Stream<MessageDelta or Message>
  resume(sessionId) -> RunResult
  abort(runId) -> no return

  getState() -> AgentState
  getConfig() -> AgentConfig
  setConfig(config) -> no return

  getTools() -> ToolSummary[]
  registerTools(tools) -> no return

  close() -> no return
```

## 9. 初始化流程

```text
create(init):
  1) validateRequiredDeps(init.deps)
  2) fillOptionalDepsWithDefaults(init.deps)
  3) normalizeConfigWithDefaults(init.config) -> effectiveConfig
  4) validateConfig(effectiveConfig)
  5) resolve tool requirements (agent/runtime)
  6) init runtime if required by any tool (or error if missing)
  7) create or get toolRegistry
  8) register(init.tools) into toolRegistry
  9) build Agent(config=effectiveConfig, deps=effectiveDeps)
  10) set state = idle
```

初始化约束：

- 创建阶段不加载 session
- session 在 `run/resume` 阶段加载
- deps 在创建后只读，不允许运行时替换
- `run()` 未显式传 `runId` 时，使用 `idGenerator` 生成

## 10. v0 决策冻结

- 保留 `AgentConfig`（配置）与 `AgentDeps`（依赖）
- 初始化统一为 `Agent.create({ config, deps, tools })`
- 不引入 `turnId/messageId` 到 Agent 对外 API
- `runId` 在 run 开始时生成并贯穿全程
- system prompt 统一在 `config.prompt.system` 定义
- tools 必须有明确来源与优先级（init 注册 + run 过滤）

## 11. 开放问题

- `setConfig` 对“当前 run”是否立即生效
- `runStream` 是否在结束时追加最终 `Message`
- `session.persistDelta` 默认值取舍（性能 vs 调试）
- `systemPromptOverride` 与 `config.prompt.system` 的优先级是否允许覆盖
