# 07. Session 与持久化

## 目标

- 可回放
- 可分支
- 可迁移
- 可审计

## 存储模型建议

优先 append-only 日志模型：

- `session_header`
- `entry[]`（message/message_delta_batch/model_change/compaction/custom）

## SessionEntry 最小集合

- `message`（必选）
- `message_delta_batch`（可选，调试或精细回放）
- `model_change`
- `thinking_level_change`
- `runtime_init`
- `system_prompt_override`
- `compaction_summary`
- `branch_summary`
- `redaction`
- `custom`

## 关键字段

- `id`
- `parentId`（支持树状分支）
- `timestamp`
- `type`
- `payload`

说明：
- `session_header` 用于记录版本/时间/cwd/parentSession 等元数据
- `runtime_init` / `system_prompt_override` 用于保证 prompt cache 幂等与回放一致性
- `redaction` 用于修复/删除历史内容，避免覆盖写

## 数据关系

- 默认沿 `parentId` 回溯得到当前分支上下文
- compaction entry 指向 `firstKeptEntryId`
- replay 时按 entry 顺序还原 `messages + state`

## 迁移策略

- 每个 session 文件包含 `version`
- 加载时自动执行 `vN -> vN+1` 迁移
- 迁移应幂等，并保留原始备份（至少在开发环境）

## 最低可用（v0）

- 单文件 JSONL append-only
- 以 `message` 作为主事实来源（source of truth）
- `message_delta_batch` 默认为关闭，仅在调试模式开启
- 支持基于 `parentId` 的分支回放
- 支持压缩摘要 entry
