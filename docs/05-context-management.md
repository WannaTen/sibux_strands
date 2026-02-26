# 05. Context 管理

## 目标

在 token/cost 可控前提下，最大化有效上下文信息密度。

## Context Pipeline

1. 规范化（normalize）
2. 去重（dedupe）
3. 历史裁剪（truncate window）
4. 历史压缩（summarize/compact）
5. 组装输入（assemble model input）

## 输入构成

- `system prompt`
- `sessionEntries`（包含 messages + compaction summary 等）
- `inputMessages`（session 为空时可直接传入）
- `runtime init data`（固定不变：如 os/cwd/sandbox，保证 prompt cache 幂等）
- `runtime hints`（允许变动：如 time/locale，可能影响 cache 命中）
- `tool schemas`

输出：

- 统一的 `messages[]`（已包含 system prompt/runtime hints），直接供 Model 使用
- `toolSpecs[]`（与 messages 分离，供 Model 选择性使用）
- `entriesToAppend`（如 compaction summary，需由上层持久化）

## 裁剪与压缩策略

- 窗口优先：保留最近 N 轮
- 结构优先：保留 tool call/result 成对消息
- 压缩触发：
  - context 预计超阈值
  - 模型返回 context overflow

## 幂等性要求

- 同一 session 输入必须可重复得到一致结果（保证 prompt cache 稳定）
- 压缩结果必须作为显式消息写回 session（可回放）

## 最低可用策略（v0）

- 支持固定 token 预算窗口裁剪
- 支持单段 summary 压缩
- 支持 context overflow 后自动压缩重试
