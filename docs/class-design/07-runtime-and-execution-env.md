# 07. Runtime / ExecutionEnv 设计

## 1. 职责

Runtime 负责：
- 提供与执行环境交互的统一入口（命令、文件、浏览器、网络等）
- 维护执行环境的生命周期与状态（connect/ready/failed）
- 暴露能力与安全边界（capabilities / sandbox policy）
- 提供稳定的 `runtimeInitData` 与可变的 `runtimeHints`（供 ContextManager 使用）

Runtime 不负责：
- 工具语义与业务逻辑（由 ToolDefinition 实现）
- 上下文裁剪/压缩（ContextManager 负责）
- session 持久化（SessionStore 负责）

ExecutionEnv 负责：
- 描述“运行时环境快照与策略”（只读配置）
- 作为 Runtime 初始化的输入之一

## 2. 初始化

### 2.1 ExecutionEnv

```text
ExecutionEnv:
  os: text
  cwd: text
  workspaceRoot: text (optional)
  sandboxMode: text
  networkPolicy: allow | deny | restricted
  fsPolicy: {readOnlyRoots[], writableRoots[]}
  limits: {maxCpuMs?, maxMemoryMb?, maxDiskMb?} (optional)
```

说明：
- `ExecutionEnv` 由 Agent 基于 `AgentConfig.runtimePolicy` 与宿主环境生成
- `ExecutionEnv` 应在同一 session 中保持稳定

### 2.2 Runtime

```text
RuntimeInit:
  env: ExecutionEnv
  sandboxConfig: SandboxConfig (optional)
  statusCallback: fn(status, msg) (optional)
```

初始化流程：
- 校验 sandbox 与权限配置
- 进入 `connecting` 状态，准备本地执行资源

失败策略：
- 初始化失败进入 `failed`
- 未 `ready` 前禁止执行 `execute`

## 3. 字段定义

```text
Runtime fields:
  env: ExecutionEnv
  status: RuntimeStatus
  capabilities: RuntimeCapabilities
  sandboxConfig: SandboxConfig (optional)
```

## 4. 方法定义

```text
connect() -> no return
close() -> no return
status() -> RuntimeStatus
capabilities() -> RuntimeCapabilities
execute(action: RuntimeAction, signal?) -> RuntimeObservation
getInitData() -> map
getHints() -> map
```

`RuntimeStatus`（示意）：

```text
RuntimeStatus:
  state: idle | connecting | ready | failed | closed
  message: text (optional)
```

语义说明：
- `getInitData()` 返回稳定快照（如 `os/cwd/sandboxMode/workspaceRoot`）
- `getHints()` 返回可变信息（如 time/locale/timezone）
- `execute` 只能在 `ready` 状态调用

## 5. 状态与不变量

- `idle -> connecting -> ready` 为正常流转
- `failed/closed` 状态不可再次执行
- 同一 session 内 `getInitData()` 输出必须稳定（保证 prompt cache 幂等）

## 6. 数据流与依赖

上游依赖：
- Agent 生成 `ExecutionEnv`
- AgentDeps 注入 Runtime（可选）

下游依赖：
- ToolExecutor 在执行时使用 Runtime
- ContextManager 使用 `runtimeInitData/runtimeHints`
- SessionStore 持久化 `runtime_init` entry（可选）

输入输出边界：
- 输入：`RuntimeAction`
- 输出：`RuntimeObservation`

## 7. v0 决策

- 仅实现 `LocalRuntime`
- remote/container runtime 暂缓
- `RuntimeAction` 只覆盖基础命令/文件/浏览器/网络入口
- runtime 仅在工具声明 `requiresRuntime` 时要求可用

## 8. 开放问题

- `RuntimeAction/Observation` 是否需要进一步标准化（多媒体/IDE/GUI）
- 网络与浏览器能力的安全边界如何分级
- 长时任务与取消/中断的标准协议
