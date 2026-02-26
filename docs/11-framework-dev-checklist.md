# 11. 在开始开发框架前，你要先准备什么

## A. 必备输入（没有这些先不要开工）

1. 架构契约
- 核心类型定义（`Message`/`MessageDelta`/State/Tool）
- 状态机定义
- 错误码与重试策略

2. 验收基线
- Golden traces 样本
- 每个里程碑的 Done Criteria

3. 运行边界
- runtime 能力清单（文件/命令/网络/浏览器）
- 安全策略（哪些工具需要审批）

4. 模型策略
- 默认模型与 fallback
- token/cost 预算
- timeout/retry 参数

5. 工程约束
- 代码目录结构
- 统一命令（lint/test/typecheck）
- 日志与 trace 规范

## B. 代码仓库脚手架（建议）

```text
src/
  agent/
  loop/
  model/
  context/
  env/
  session/
  observability/
  hitl/
  types/

examples/
  minimal/
  chat-assistant/
  tool-automation/
  code-agent-optional/

tests/
  unit/
  integration/
  replay/

golden/
  traces/

docs/
```

## C. 开发任务拆分方式

- 任务必须小步可验收
- 每个任务只改 1~3 个模块
- 每个任务都附测试与验收命令

示例拆分：

1. 先做 `types + schema`
2. 再做 `session append-only`
3. 再做 `model (provider -> MessageDelta)`
4. 再做 `message assembler + agent loop v0`
5. 再做 `tool executor + hitl`
6. 最后做 `observability + replay`

## D. 常见失败原因

- 先写功能后写协议，导致反复重构
- 没有 golden traces，回归无法判断
- session 非 append-only，重放困难
- 模型输出未抹平，导致上层充满 provider 分支判断
- 没有统一错误码，线上排障成本高
