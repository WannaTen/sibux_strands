# 10. HITL / Control Flow 设计

## 1. 职责

HITL 组件负责：
- 在工具执行前/中/后提供人工审批与控制流
- 统一审批请求与决策结构
- 与 AgentLoop/ToolExecutor 形成清晰的等待与恢复协议

HITL 不负责：
- 工具执行实现（ToolExecutor 负责）
- 上下文裁剪（ContextManager 负责）
- 持久化实现细节（SessionStore 负责）

## 2. 关键概念

- `ApprovalGate`：审批入口，生成审批请求并等待决策
- `ApprovalPolicy`：判断是否需要审批
- `ApprovalDecision`：人类或策略引擎给出的决策
- `ControlSignal`：运行态控制指令（pause/resume/abort）

## 3. 数据结构

```text
ApprovalRequest:
  sessionId: text
  runId: text
  toolCallId: text
  toolName: text
  arguments: object
  riskLevel: low | medium | high (optional)
  reason: text (optional)
```

```text
ApprovalDecision:
  toolCallId: text
  action: approve | deny | modify_args | pause | resume | abort_run
  modifiedArgs: object (optional)
  note: text (optional)
  reviewerId: text (optional)
```

```text
ControlSignal:
  runId: text
  action: pause_run | resume_run | abort_run
  payload: object (optional)
```

## 4. 接口建议

```text
ApprovalGate:
  requestApproval(req: ApprovalRequest) -> ApprovalDecision

ApprovalPolicy:
  shouldApprove(tool: ToolDefinition, ctx: ApprovalContext) -> ApprovalRequirement

ApprovalRequirement:
  decision: auto_approve | auto_deny | require_human
  riskLevel: low | medium | high (optional)
  reason: text (optional)
```

`ApprovalContext`（示意）：

```text
ApprovalContext:
  sessionId: text
  runId: text
  toolCallId: text
  toolName: text
  arguments: object
  runtime: Runtime (optional)
```

## 5. 与 AgentLoop 的交互

- ToolExecutor 在执行前根据 `ApprovalPolicy` 判断是否需要审批
- 若 `require_human`，进入 `awaiting_human` 并阻塞执行
- AgentLoop 发出状态事件，等待 `ApprovalDecision`
- `approve/modify_args` 恢复工具执行
- `deny` 生成标准化 `tool_result`（isError=true）
- `abort_run` 直接终止 run

## 6. 持久化建议

建议写入 session entry 或 message meta：

- `approval_required`
- `approval_decision`
- `tool_paused`
- `tool_resumed`
- `run_aborted_by_human`

要求：
- `modify_args` 必须记录修改前后参数
- 审批记录必须可回放

## 7. v0 决策

- 只支持 `before_tool_execute` 审批
- 不引入独立事件总线
- `deny` 必须生成 `tool_result` message

## 8. 开放问题

- `ApprovalGate` 是否需要异步/回调模式
- `during_tool_execute` 的暂停/恢复与超时策略
- `before_result_commit` 的默认启用策略
