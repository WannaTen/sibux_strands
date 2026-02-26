# 12. 实施计划（v0）

## Milestone 0：协议冻结（1-2 天）

产出：

- `types` 文档与 schema
- 状态机文档
- `Message` / `MessageDelta` 类型清单

验收：

- 评审通过，后续实现不再改核心协议

## Milestone 1：Session 与 Context（2-4 天）

产出：

- append-only session store
- context pipeline（normalize/dedupe/truncate）

验收：

- 可以从 session 重建上下文
- 基础 replay 可用

## Milestone 2：Model + Loop（3-5 天）

产出：

- 单 provider model 实现
- 统一 `MessageDelta` 流
- `MessageAssembler`
- loop v0（无 HITL）

验收：

- 无工具与单工具流程可跑通

## Milestone 3：Tools + Runtime + HITL（3-6 天）

产出：

- tool registry/executor
- runtime 抽象
- 审批流程（approve/deny/modify）

验收：

- 多工具与审批流程可跑通

## Milestone 4：Observability + Replay + Hardening（3-5 天）

产出：

- 指标、trace、结构化日志
- golden trace replay
- retry/timeout/overflow recovery

验收：

- 10 条 golden traces 全通过
- 基本 SLO 指标可采集

## Milestone 5：SDK/CLI 最小可用（2-3 天）

产出：

- 最小 SDK API
- 最小 CLI 示例

验收：

- 文档示例可一键运行
