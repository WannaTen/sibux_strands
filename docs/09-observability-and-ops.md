# 09. 可观测性与运维

## 观测三件套

- Logs
- Metrics
- Traces

## 关键日志

- run lifecycle（start/finish/fail）
- model request/response 摘要
- model delta stream 摘要（可采样）
- tool execution 摘要
- hitl decision
- compaction/retry 触发

## 核心指标（v0）

- `run_duration_ms`
- `turn_count`
- `model_latency_ms`
- `tool_latency_ms`
- `tool_error_rate`
- `retry_count`
- `context_compaction_count`
- `token_input/output`
- `cost_total`

## Trace Span 建议

- `run`
- `turn`
- `model_request`
- `model_stream`
- `tool_execution`
- `context_build`
- `context_update`
- `session_commit`

## SLO 建议（初版）

- P95 单次 turn 延迟 < 8s（不含长工具）
- 失败可归因率 > 95%
- replay 一致性通过率 100%

## 故障排查最小 Runbook

1. 看 run 状态与 `last_error_code`
2. 看对应 `model_request` / `model_stream` / `tool_execution` span
3. 检查 session commit 是否连续
4. 检查是否发生 context overflow / compaction / retry
