# 09. Error Model 设计

## 1. 目标

- 统一框架内错误类型与语义
- 保证上层可感知、可恢复、可审计
- 屏蔽 provider/runtime 私有错误细节

## 2. 统一错误结构

```text
AgentError:
  code: text
  message: text
  retryable: boolean
  category: model | tool | runtime | session | context | loop | unknown
  cause: object (optional)   # 保留原始错误（仅调试/审计）
  meta: map (optional)
```

说明：
- `cause` 不参与业务逻辑分支，仅用于调试
- `message` 必须可读且面向用户或开发者

## 3. 错误码约定

### 3.1 Model

- `ModelTimeout`
- `ModelRateLimited`
- `ModelAuthError`
- `ModelContextOverflow`
- `ModelBadRequest`
- `ModelServerError`
- `ModelUnknownError`

### 3.2 Tool

- `ToolNotFound`
- `ToolTimeout`
- `ToolDenied`
- `ToolExecutionError`
- `ToolInvalidArgs`
- `ToolRequiresApproval`

### 3.3 Runtime

- `RuntimeNotReady`
- `RuntimeUnavailable`
- `RuntimePermissionDenied`
- `RuntimeSandboxViolation`
- `RuntimeExecutionError`

### 3.4 Session / Storage

- `SessionNotFound`
- `SessionWriteFailed`
- `SessionReadFailed`
- `SessionConcurrentWrite`
- `SessionMigrationFailed`

### 3.5 Context

- `ContextOverflow`
- `ContextCompactionFailed`
- `ContextInvalidInput`

### 3.6 Loop / Control

- `RunAborted`
- `RunTimeout`
- `RunMaxIterations`
- `RunMaxToolRounds`

## 4. 映射规则

- provider 错误必须映射为 `Model*` 错误码
- runtime 错误必须映射为 `Runtime*` 错误码
- tool 内部错误必须映射为 `Tool*` 错误码
- 未知错误使用 `Unknown` 后缀并标记 `retryable=false`

## 5. 错误传播

- Model 层返回 `MessageDelta.kind=error`，payload 使用 `AgentError`
- Tool 执行失败返回 `tool_result`，payload 携带 `AgentError`
- AgentLoop 捕获错误后记录 `lastError` 并结束 run

## 6. v0 决策

- `AgentError` 为唯一错误结构
- `retryable` 由映射层决定
- `cause` 默认不透传给模型或用户

## 7. 开放问题

- 是否引入错误的稳定 `errorId`
- `cause` 的持久化范围与脱敏策略
- `retryable` 是否需要细分为可幂等/不可幂等等级
