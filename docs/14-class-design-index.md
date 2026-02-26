# 14. 类设计细化索引

## 为什么单独拆一组文档

前 01-13 文档用于冻结框架级协议和架构。  
从这一步开始，我们进入“类级别设计冻结”，每个类会反复迭代字段、方法、边界和不变量。

如果继续写在总览文档中，会出现两个问题：

- 框架总览与实现细节混在一起，阅读成本变高
- 后续变更 diff 粒度太粗，不利于评审和回滚

因此采用：

- `docs/class-design/` 下每个类单独一篇
- 统一模板，保证讨论结构一致

## 文档约定

- 每篇文档只负责一个类（或强耦合的一小组类）
- 每篇必须包含：职责、初始化、字段、方法、状态与不变量、开放问题
- 决策结论优先，背景说明次之
- v0 先最小可用，避免一次性设计过重

## 当前条目

1. `docs/class-design/00-template.md`
2. `docs/class-design/01-agent-and-agentconfig.md`
3. `docs/class-design/02-model-and-message-assembler.md`
4. `docs/class-design/03-context-manager.md`
5. `docs/class-design/04-session-store-and-entry.md`
6. `docs/class-design/05-tool-registry-and-executor.md`
7. `docs/class-design/06-agent-loop-and-state-machine.md`
8. `docs/class-design/07-runtime-and-execution-env.md`
9. `docs/class-design/08-message-schema-and-delta-contract.md`
10. `docs/class-design/09-error-model.md`
11. `docs/class-design/10-hitl-and-control-flow.md`
