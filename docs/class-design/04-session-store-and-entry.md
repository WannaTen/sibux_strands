# 04. SessionStore / SessionEntry 设计

## 1. 职责

SessionStore 负责：
- 持久化 session entries（append-only）
- 提供按顺序加载与回放能力
- 支持分支（branch）与版本迁移
- 提供幂等与并发控制（避免重复写入）
- 作为“唯一持久化边界”，所有需要落盘的内容都以 entry 形式写入

SessionStore 不负责：
- context 裁剪、压缩或消息组织
- model 调用与 tool 执行
- agent loop 的编排与重试策略
- 构建 messages 视图（由上层从 entries 派生）

## 2. 初始化

初始化输入（示意）：

```text
SessionStoreInit:
  backend: StorageBackend
  entrySerializer: EntrySerializer
  schemaVersion: text
```

初始化流程：
- 校验 storage/backend 可用性
- 载入当前版本与迁移策略

失败策略：
- 无法访问存储时直接报错
- 迁移失败时拒绝写入并返回错误

## 3. 字段定义

```text
SessionStore fields:
  backend: StorageBackend
  entrySerializer: EntrySerializer
  schemaVersion: text
```

## 4. 方法定义

```text
createSession(sessionId?) -> SessionHandle
loadSessionEntries(sessionId, opts?) -> SessionEntry[]
appendSessionEntries(sessionId, sessionEntries, expectedTailEntryId?) -> AppendResult
branchFromEntry(sessionId, fromEntryId, newSessionId?) -> SessionHandle
migrateSession(sessionId) -> MigrationResult
close() -> no return
```

参数与返回值（示意）：

```text
AppendResult:
  sessionId: text
  lastAppendedEntryId: text
  appendedCount: integer

SessionHandle:
  sessionId: text
  schemaVersion: text
```

语义说明：
- `appendSessionEntries` 必须原子追加，失败不得部分写入
- `expectedTailEntryId` 用于乐观并发控制，不匹配则失败
- 重复 entryId 应幂等（忽略或返回已存在）

## 5. SessionEntry 定义

基础结构：

```text
SessionEntry:
  id: text
  parentId: text (optional)
  type: text
  timestamp: text
  runId: text (optional)
  payload: object
  meta: map (optional)
```

最小 entry 类型集合（v0）：

- `session_header`（必选，版本/时间/cwd/parentSession 等）
- `message`
- `message_delta_batch`（可选，调试/精细回放）
- `model_change`
- `thinking_level_change`
- `runtime_init`（system prompt/runtimeInitData 的稳定快照）
- `system_prompt_override`（若支持 override，则显式记录）
- `compaction_summary`
- `branch_summary`
- `redaction`
- `custom`

约定：
- `message` 是事实来源（source of truth）
- `compaction_summary` 应包含 `firstKeptEntryId`
- `branch_summary` 应包含 `sourceSessionId/sourceEntryId`
- 不允许覆盖写历史 entry；修复/删除使用 `redaction` 追加记录

## 6. 状态与不变量

- append-only，不允许修改或删除历史 entry
- 同一 session 的 entry 顺序不可逆
- `id` 全局唯一或在 session 内唯一
- `parentId` 用于回放分支路径
- 任何 compaction 必须显式写入 entry（可回放）

## 7. 数据流与依赖

上游依赖：
- AgentLoop / ContextManager 产生 `entriesToAppend`

下游依赖：
- ContextManager 与 Session 回放读取 entries
- Observability 读取 session entry 进行审计

输入输出边界：
- 输入：SessionEntry[]
- 输出：SessionEntry[] / AppendResult

## 8. v0 决策

- 单文件 JSONL append-only
- `message` 作为主事实来源
- `message_delta_batch` 默认关闭
- 支持 `parentId` 分支回放
- 每个 session 文件带 `version` 字段

## 9. 开放问题

- entryId 是否需要全局唯一还是 session 内唯一
- 并发写入的冲突解决策略（拒绝/重试/合并）
- branch 结构是否需要独立索引以提升回放性能
