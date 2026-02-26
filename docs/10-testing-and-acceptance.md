# 10. 测试策略与验收标准

## 测试分层

- Unit
  - type/schema 校验
  - 状态机转换
  - adapter delta normalize（provider -> `MessageDelta`）
  - message assembler
- Integration
  - loop + session + model mock
  - tool 执行与 hitl
- Replay
  - golden trace 回放一致性
- E2E
  - CLI/SDK 最小用户路径

## Golden Traces（必须先准备）

至少准备 10 条：

1. 无工具调用
2. 单工具成功
3. 多工具串行
4. 多工具并行
5. 工具失败后继续
6. 高风险工具审批通过
7. 高风险工具审批拒绝
8. context overflow 后压缩重试成功
9. 用户中止
10. session 恢复继续运行

## 验收标准（v0）

- 能稳定完成完整 loop（模型->工具->模型）
- 所有 message 与关键元数据可落库并可回放
- replay 与原始轨迹在结构上等价
- 关键指标可观测
- HITL 审批链路可用

## CI 最低门槛

- lint/typecheck/test 必须通过
- golden traces 回放测试必须通过
- 覆盖率底线（建议）：core >= 80%
