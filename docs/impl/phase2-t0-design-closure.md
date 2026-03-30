# Phase 2 T0 设计收口

> 本文档用于收口 `Phase 2` 的最小设计决策。
>
> 它不描述完整实现细节, 只回答当前必须先拍板的问题:
>
> - session 存在哪里
> - CLI 默认如何恢复 session
> - primary / subagent 的持久化边界是什么
> - `agent_id` / `session_id` 应如何生成和使用
> - Phase 2 明确不做哪些事情

## 1. 设计目标

T0 的目标不是设计完整架构, 而是为后续编码任务提供稳定边界, 让 `T1-T8` 可以并行推进而不反复返工。

本次收口后, `Phase 2` 应默认接受以下大方向:

- 优先复用 Strands
- 仅对 primary agent 接入持久化
- 继续使用 Strands `FileSessionManager`
- 暂不引入 SQLite
- 暂不引入自定义 event layer

## 2. 已收口决策

### D1. Session 持久化使用 Strands FileSessionManager

`Phase 2` 直接使用 Strands 的 `FileSessionManager` 作为底层持久化实现。

原因:

- 当前目标是尽快获得稳定 session 能力
- Strands 已经实现了 `SessionManager + RepositorySessionManager + FileSessionManager`
- 现阶段不需要自己实现 `SessionRepository`

结论:

- `Phase 2` 不新增 SQLite repository
- `Phase 2` 不新增 projection / part storage
- `Phase 2` 只做对 `FileSessionManager` 的产品级接入

### D2. Session 存储目录使用项目内稳定路径

不使用 Strands `FileSessionManager` 的默认临时目录。

推荐路径:

```text
.sibux/
└── session/
    ├── state.json
    └── strands/
        └── session_<id>/...
```

约定:

- `.sibux/session/strands/`
  - 存放 Strands file session 数据
- `.sibux/session/state.json`
  - 存放 Sibux 当前项目的最小会话索引

原因:

- 项目内落盘更符合 CLI 产品行为
- 路径可见、可清理、可迁移
- 避免临时目录被系统清理

### D3. CLI 默认恢复策略为 `resume=last`

`Phase 2` 默认采用“恢复最近 session”。

行为约定:

1. 启动时读取 `.sibux/session/state.json`
2. 若 `state.json` 中记录的 `agent` 与当前启动的 primary agent 相同, 且存在有效 `session_id` 且其 session 目录存在:
   - 恢复该 session
3. 否则:
   - 创建新 session
4. 如果恢复过程中发现 `state.json` 损坏、session 目录缺失或读取失败:
   - CLI 打印一条恢复失败提示
   - 然后自动创建新 session

配置项:

```json
{
  "session": {
    "resume": "last"
  }
}
```

后续支持:

- `resume = "new"` 时每次启动都创建新 session

原因:

- 对交互式 coding assistant 来说, 默认续接上下文更符合预期
- 也更接近 opencode 的使用体验

### D4. 仅 primary agent 进入持久化路径

`Phase 2` 明确划定持久化边界:

- `primary` agent:
  - 持久化
  - 恢复历史
  - 使用稳定 `agent_id`

- `subagent`:
  - 无状态
  - 不挂 `session_manager`
  - 不写入主 session

原因:

- 降低本阶段复杂度
- 避免在一个 session 内过早定义多 agent 持久化语义
- 避免 `task` 调用污染主会话

说明:

- `Phase 2` 仍允许 subagent 正常运行
- 只是其执行痕迹不进入持久化主路径

### D5. Primary agent 的 `agent_id` 采用稳定命名

`primary` agent 的 `agent_id` 采用稳定值:

```text
agent_id = agent_config.name
```

例如:

- `build`
- `plan`

原因:

- Strands 会话恢复依赖 `agent_id`
- 同一 primary agent 需要在同一 session 中被稳定识别
- 当前需求不需要更复杂的 agent instance 编号

约束:

- `primary` agent 在同一 session 中不应重复创建多个同名实例
- Session service 负责当前 primary agent 的唯一性

### D6. Subagent 不显式设置持久化 agent_id

`subagent` 在 `Phase 2` 不进入持久化路径, 因此:

- 不挂 `session_manager`
- 不要求稳定 `agent_id`

实现上可以有两种做法:

1. 不显式传 `agent_id`
2. 显式传一个临时 id, 但不挂 session manager

推荐:

- 优先使用更简单的做法
- 只要不进入持久化路径即可

### D7. Session ID 使用 opaque id

`session_id` 使用不含路径分隔符的 opaque id。

推荐格式:

```text
sibux_<uuid4hex>
```

例如:

```text
sibux_3f7b4d6c8a1e4c28b8b1d7f1d58d9e8a
```

原因:

- 满足 Strands `_identifier.validate()` 的要求
- 不把时间、目录等语义直接编码进 id
- 简单稳定, 无额外约束

说明:

- `FileSessionManager` 自己会再包一层 `session_<id>/`
- 因此我们不需要在 id 中再加 `session_` 前缀

### D8. Session state 文件只记录最小索引

`.sibux/session/state.json` 只记录最小状态, 不做复杂索引库。

建议结构:

```json
{
  "version": 1,
  "current_session_id": "sibux_xxx",
  "agent": "build",
  "updated_at": "2026-03-29T12:34:56Z"
}
```

Phase 2 不要求:

- session 列表缓存
- fork 树
- share 状态
- revert 元数据

原因:

- 当前只需要支持“恢复最近 session”
- 不需要提前做完整 state store

### D9. Tool Assembly 先保持最小实现

`Phase 2` 不强制引入新的 `catalog.py`。

当前建议:

- 默认继续使用 `ALL_TOOLS + permission filter`
- 若实现过程中发现 factory 已明显变重, 再抽一个很薄的 selector

结论:

- `catalog` 不是 `Phase 2` 的前置必需项
- 可以作为实现过程中的局部重构决定

### D10. Phase 2 不自建事件模型

`Phase 2` 不新增:

- `sibux/events/schema.py`
- `sibux/events/adapter.py`
- `sibux/events/emitter.py`

原因:

- 当前阶段目标只是接入 session 持久化
- Strands 现有 hook / stream 事件已足够支撑 Phase 2
- 自定义事件层应在后续真正做服务化时再设计

## 3. 对代码结构的直接影响

基于上面的收口, `Phase 2` 的代码新增应尽量收敛为:

```text
src/sibux/
├── session/
│   ├── __init__.py
│   └── service.py
├── agent/
│   └── agent_factory.py       # 增加 session_manager / agent_id 注入
├── config/
│   ├── config.py              # 增加 session 字段
│   └── defaults.py            # 增加 session 默认值
└── main.py                    # 接入 session lifecycle
```

不应在 `Phase 2` 新增:

```text
src/sibux/
├── events/
├── storage/
├── runtime/
└── session/
    ├── repository.py
    ├── sqlite_repository.py
    ├── models.py
    └── projection.py
```

## 4. 对 T1-T8 的约束

### T1 Config

必须遵循:

- 引入 `session.storage_dir`
- 引入 `session.resume`

### T2 Session Service

必须遵循:

- 统一读写 `.sibux/session/state.json`
- 统一构造 `FileSessionManager`
- 统一决定 `session_id`

### T3 Agent Factory

必须遵循:

- 允许注入 `session_manager`
- 允许注入 `agent_id`
- subagent 路径默认不接持久化

### T4 Primary/Subagent 持久化策略

必须遵循:

- primary 持久化
- subagent 无状态

### T5/T6 CLI

必须遵循:

- 启动恢复逻辑基于 `state.json`
- `/new` 会切换到全新 session
- `/session` 输出当前 session 基本信息

## 5. 本阶段明确不解决的问题

这些问题不是未考虑, 而是明确延后:

- session 列表管理
- session fork 树
- child session
- SQLite 持久化
- part 级独立存储
- 自定义事件总线
- SSE
- subagent 执行痕迹持久化
- richer permission state

## 6. 已确认补充规则

在本轮讨论后, 额外确认以下实现规则:

1. `state.json` 固定放在 `.sibux/session/state.json`, 不再放在 `.sibux/` 根下
2. `session_id` 继续使用 `sibux_<uuid4hex>`, 本阶段不再压缩格式
3. `resume="last"` 只恢复“当前 primary agent 对应的最近 session”
4. 恢复失败时, CLI 需要打印提示, 然后自动创建新 session
5. `session.persist_subagents` 不进入 `Phase 2` 配置面

## 7. 当前建议

如果没有新的反对意见, 建议把本文件作为 `T0` 定稿依据, 然后按下面顺序进入实现:

1. `T1` Config
2. `T2` Session Service
3. `T3` Agent Factory
4. `T4` 持久化边界
5. `T5/T6` CLI 生命周期与命令
