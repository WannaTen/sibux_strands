# Agent Framework Docs

本文档集用于指导从零实现一个 message-first 的通用 agent 框架。

核心定义：

`agent = model + context + environment`

- `model`: 统一输入、统一 `MessageDelta` 流输出，并最终生成 `Message`
- `context`: system prompt + session messages 的上下文管理层
- `environment`: runtime + tools 的执行环境层
- `agentLoop`: 编排循环，调用 environment 收集上下文、调用 model 产出 `MessageDelta`，组装并写入 `Message`

v0 约束：

- 不引入独立 EventBus/Event 实体
- 对外统一使用 `Message`
- 流式处理中间层统一使用 `MessageDelta`

## 阅读顺序

1. `01-architecture-overview.md`
2. `02-core-domain-model.md`
3. `03-agent-loop-and-state-machine.md`
4. `04-model-contract.md`
5. `05-context-management.md`
6. `06-environment-runtime-and-tools.md`
7. `07-session-and-persistence.md`
8. `08-hitl-and-control-flow.md`
9. `09-observability-and-ops.md`
10. `10-testing-and-acceptance.md`
11. `11-framework-dev-checklist.md`
12. `12-implementation-plan-v0.md`
13. `13-ascii-architecture-and-class-relationships.md`
14. `14-class-design-index.md`

## 文档目标

- 先冻结核心类型与状态机，再写实现代码
- 保证可回放、可观测、可中断、可扩展
- 支持通用场景快速落地，并按垂类做增量扩展
