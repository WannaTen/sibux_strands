# Phase 2 详细实施方案（草案）

> 对应 [implementation-plan.md](./implementation-plan.md) 中的 `Phase 2 -- 基础设施定型`
>
> 本文档基于当前共识重写: `Phase 2` 不再尝试自建一套独立于 Strands 的 runtime、message model、storage layer 或 event layer, 而是优先复用 Strands 已有能力, 在 Sibux 中补齐一层薄封装。
>
> 直接派工时, 请同时参考 [phase2-task-cards.md](./phase2-task-cards.md)。

## 1. 设计前提

### 1.1 我们对标 opencode 的是什么

`opencode` 在应用层做得很完整:

- 有明确的 session 生命周期
- 有稳定的会话恢复机制
- 有清晰的 agent 装配入口
- 有可扩展的工具接入点

但 `opencode` 之所以自己实现大量 runtime / message / storage / event 模块, 是因为它的底层执行内核本来就不是 Strands。

Sibux 的情况不同:

- Strands 已经提供了 `Agent` 执行循环
- Strands 已经提供了 `Message` / `ContentBlock` 模型
- Strands 已经提供了 `SessionManager` / `SessionRepository`
- Strands 已经提供了 hook 和 stream 事件
- Strands 已经提供了 `ToolRegistry`

因此, `Phase 2` 的目标不是“复制 opencode 的内部实现”, 而是“在 Strands 之上实现与 opencode 相当的应用层能力起点”。

### 1.2 Phase 2 的核心原则

1. **复用 Strands 现有内核**
   - 不重写 event loop
   - 不重写 message runtime model
   - 不重写 SDK 内部 tool registry

2. **Sibux 只做薄封装**
   - 负责 session 生命周期
   - 负责 primary agent 的持久化接入
   - 负责 CLI 启动/恢复逻辑
   - 负责 agent factory 的装配边界

3. **本阶段先求稳定, 不求完整**
   - 先使用 Strands `FileSessionManager`
   - 先不引入 SQLite
   - 先不自建 event schema / adapter / emitter
   - 先不做 message/part projection

## 2. Phase 2 目标

本阶段的目标收敛为四件事:

1. 让 Sibux 的 primary agent 拥有稳定的 session 持久化能力
2. 让 CLI 可以显式创建、恢复和切换当前 session
3. 让 agent factory 成为统一装配入口, 能接入 session manager、agent id 和后续扩展点
4. 保持整体设计与 Strands 对齐, 为 Phase 3/4 留出清晰扩展边界

## 3. 本阶段范围与非目标

### 3.1 本阶段范围

- Strands session integration
- primary agent persistence
- CLI session lifecycle
- thin agent factory / tool assembly seam
- 最小配置扩展

### 3.2 本阶段明确不做

- 不实现 SQLite repository
- 不实现自定义 `SessionRepository`
- 不实现 `sibux/session/models.py`、`projection.py`
- 不实现自定义事件 schema / adapter / emitter
- 不实现 Event Bus / SSE
- 不实现 Session Compaction
- 不实现 Retry & Error Handling v2
- 不实现 MCP / Skill / Plugin / Permission Ask

## 4. 当前代码现状

当前 `src/sibux/` 的 MVP 已可用, 但与“可持续 session”还有明显距离:

- [main.py](/Users/yilin/Code/projects/sibux_strands/src/sibux/main.py) 启动后直接创建 agent 并循环调用, 没有 session 生命周期管理
- [agent_factory.py](/Users/yilin/Code/projects/sibux_strands/src/sibux/agent/agent_factory.py) 只装配 model / tools / prompt, 还没有接入 `session_manager`、`agent_id`
- 目前没有稳定的 session 存储路径约定
- `task` 子 agent 和 primary agent 还没有明确的持久化边界

同时, Strands 已经具备可复用能力:

- `Agent` 自带执行循环与 hook 链路
- `FileSessionManager` 已能持久化消息与 agent 状态
- `RepositorySessionManager` 已实现恢复/同步流程

所以 Phase 2 的合理动作是“接入并约束这些能力”, 而不是平行重写。

## 5. 详细设计

### 5.1 Session Service

#### 目标

新增 `sibux/session/service.py`, 作为 Sibux 的会话入口层。

它不是新的 runtime, 而是负责:

- 创建新 session
- 恢复当前项目最近 session
- 决定 session 存储目录
- 维护当前 primary agent 对应的 `session_id`
- 为 CLI 提供稳定的 session API

#### 责任边界

`session/service.py` 负责:

- 生成或加载 `session_id`
- 构造 `FileSessionManager`
- 决定当前 primary agent 的 `agent_id`
- 提供 `create_or_resume()`、`new_session()`、`current()` 之类的高层接口

它不负责:

- 执行模型调用
- 自定义消息持久化格式
- 自定义 event schema

#### 为什么必须有这一层

即使使用 Strands 的 `FileSessionManager`, Sibux 仍然需要自己的 session 服务层, 因为:

- Strands 不知道“当前项目应该恢复哪个 session”
- Strands 默认存储目录是临时目录, 不适合产品行为
- CLI 需要一个稳定的 session 生命周期入口

### 5.2 Session Storage Policy

#### 目标

继续使用 Strands `FileSessionManager`, 但由 Sibux 显式管理存储路径和恢复策略。

#### 设计要求

- 不使用 `FileSessionManager` 的默认临时目录
- session 数据应写入稳定路径
- 同一项目需要有“当前活跃 session”的最小索引

#### 建议方案

会话数据:

```text
.sibux/
└── session/
    ├── state.json
    └── strands/
        └── session_<id>/...
```

其中:

- `.sibux/session/strands/` 存放 Strands file session 数据
- `.sibux/session/state.json` 记录:
  - 当前 project 的最近 `session_id`
  - 最近使用的 `agent`
  - 最近更新时间

#### 说明

这一步不是在发明新的 storage layer。
它只是给 Strands file session 加一个稳定的产品级落盘位置和恢复入口。

### 5.3 Primary Agent Persistence Policy

#### 目标

明确本阶段只有 primary agent 进入持久化路径。

#### 规则

- `primary` agent:
  - 挂 `FileSessionManager`
  - 使用稳定 `agent_id`
  - 会话可恢复

- `subagent`:
  - 默认无状态
  - 不进入主 session 持久化
  - 每次 task 调用临时创建

#### 原因

这样可以显著降低 Phase 2 的复杂度:

- 避免一个 session 下多个 agent 的生命周期冲突
- 避免 `task` 子调用污染主会话历史
- 避免过早定义 subagent persistence 语义

#### 后续扩展

Phase 3/4 如果需要保存 subagent 执行痕迹, 可以单独设计:

- 保存到主 session 的文本摘要
- 或引入显式 child session

但这不属于 Phase 2。

### 5.4 Agent Factory 重构

#### 目标

让 `sibux/agent/agent_factory.py` 从“简单创建器”演进为真正的装配层。

#### Phase 2 要补的能力

- 接收可选的 `session_manager`
- 接收可选的 `agent_id`
- 接收可选的 `context_manager`
- 统一接入 tool selection seam
- 保持当前 prompt / model / permission 逻辑

#### 设计原则

factory 依然只是装配器:

- 不自己执行 loop
- 不自己管理 session 生命周期
- 不自己做 storage

它的角色是:

- 把 config、session、tools、prompt、agent identity 组装成 Strands `Agent`

#### 最低验收

- primary agent 能通过 factory 接入 `FileSessionManager`
- subagent 可以继续走无状态路径
- `task` 工具继续可用
- factory 已预留后续扩展点, 但不提前引入复杂模块

### 5.5 Tool Assembly Seam

#### 目标

保留“应用层决定给 agent 哪些工具”的能力, 但不重复实现 Strands 的内部 `ToolRegistry`。

#### Phase 2 的最小做法

可以选择两种方式之一:

1. 暂时继续使用当前 `ALL_TOOLS + permission filter`
2. 新增一个很轻的 `catalog` / `selector` 模块, 专门返回某个 agent 应暴露的工具列表

#### 建议

如果改动足够小, 倾向于引入一个很薄的选择层, 但不要做成独立复杂框架。

这个层的职责仅限于:

- 汇总内置工具
- 按 agent permission 过滤
- 作为后续 MCP / Plugin / Skill 工具注入的挂点

### 5.6 CLI Session Lifecycle

#### 目标

让 CLI 从“无状态 REPL”变成“带最小 session 概念的 REPL”。

#### 启动行为

CLI 启动时:

1. 加载 config
2. 读取当前项目 session 状态
3. 根据配置决定:
   - 恢复当前 primary agent 对应的最近 session
   - 或创建新 session
4. 通过 session service 创建 primary agent
5. 在界面上显示当前 session 信息

#### 建议命令

本阶段只做最小集:

- `/new`
  - 创建新 session
  - 切换当前 primary agent 到新 session

- `/session`
  - 显示当前 session id、存储目录、agent 名称

- `/exit`
  - 退出 REPL

#### 本阶段不做

- 不做复杂 session 列表
- 不做 fork/revert/share
- 不做 HTTP 接口

### 5.7 配置扩展

#### 目标

在不引入复杂 schema 的前提下, 为 session 行为补充最小配置。

#### 建议字段

```json
{
  "session": {
    "storage_dir": ".sibux/session/strands",
    "resume": "last"
  }
}
```

#### 字段说明

- `storage_dir`
  - session 存储目录
  - 默认使用项目内稳定目录

- `resume`
  - `last` 或 `new`
  - 决定 CLI 启动时恢复还是新建

## 6. Phase 2 TODO 拆分

下面的 TODO 以“能直接落到代码仓库”的粒度来拆分。每项都标注了建议产出、前置依赖和并行性。

### T0. 设计收口

**目标**:

- 确认 session 存储路径
- 确认 CLI 默认恢复策略
- 确认 primary / subagent 的持久化边界

**建议产出**:

- 本文档定稿
- 配置字段命名定稿

**依赖**:

- 无

**并行性**:

- 必须最先完成
- 后续所有任务都依赖这一项的结论

### T1. Config 补充 session 字段

**目标**:

- 在 `config/config.py`、`config/defaults.py` 中补充 `session` 配置

**建议产出**:

- `session.storage_dir`
- `session.resume`

**涉及文件**:

- `src/sibux/config/config.py`
- `src/sibux/config/defaults.py`
- `tests/sibux/config/test_config.py`

**依赖**:

- 依赖 `T0`

**并行性**:

- 可以与 `T2`、`T3` 并行开发
- 不需要等 session service 全部写完

### T2. Session Service

**目标**:

- 新增 `sibux/session/service.py`
- 统一管理 session id、storage dir、state file、恢复逻辑

**建议产出**:

- `create_or_resume()`
- `new_session()`
- `current()`
- `.sibux/session/state.json` 读写逻辑
- `FileSessionManager` 构造逻辑

**涉及文件**:

- `src/sibux/session/__init__.py`
- `src/sibux/session/service.py`
- `tests/sibux/session/test_session_service.py`

**依赖**:

- 依赖 `T0`
- 与 `T1` 有轻耦合, 最终落盘前需要字段名一致

**并行性**:

- 可以与 `T1` 并行
- 可以先按约定字段写实现, 再和 `T1` 对齐

### T3. Agent Factory 注入 session_manager / agent_id

**目标**:

- 让 `agent_factory.create()` 能显式接收 `session_manager`、`agent_id`、`context_manager`

**建议产出**:

- primary agent 可挂载 `FileSessionManager`
- subagent 默认无状态
- factory 具备后续扩展点

**涉及文件**:

- `src/sibux/agent/agent_factory.py`
- `tests/sibux/agent/test_agent_factory.py`

**依赖**:

- 依赖 `T0`

**并行性**:

- 可以和 `T1`、`T2` 并行
- 但在 `T4` CLI 接入前需要完成

### T4. Primary / Subagent 持久化策略落地

**目标**:

- 把“primary 持久化、subagent 无状态”明确写进代码路径

**建议产出**:

- primary agent 创建时挂 session manager
- `task` 创建 subagent 时显式不挂 session manager
- subagent 使用稳定但局部的 `agent_id` 策略, 或直接沿用无状态默认

**涉及文件**:

- `src/sibux/agent/agent_factory.py`
- `src/sibux/tools/task.py`
- `tests/sibux/tools/test_tools.py`
- 可能新增 `tests/sibux/session/test_subagent_persistence.py`

**依赖**:

- 依赖 `T2`
- 依赖 `T3`

**并行性**:

- 不能早于 `T2`、`T3`
- 但可以与 `T5` 的 CLI 改造后半段并行

### T5. CLI Session Lifecycle 改造

**目标**:

- 让 CLI 在启动时恢复或新建 session
- 用 session service 创建 primary agent

**建议产出**:

- 启动显示当前 session id
- 启动时按配置恢复或新建
- 当前 agent 不再由 `main.py` 直接裸创建

**涉及文件**:

- `src/sibux/main.py`
- `src/sibux/session/service.py`
- 可能新增 `tests/sibux/test_main.py`

**依赖**:

- 依赖 `T1`
- 依赖 `T2`
- 依赖 `T3`

**并行性**:

- 不适合提前做
- 是第一批明显依赖前序任务完成的任务

### T6. CLI 最小会话命令

**目标**:

- 增加 `/new`
- 增加 `/session`

**建议产出**:

- `/new` 创建新 session 并切换当前 primary agent
- `/session` 输出当前 session 信息

**涉及文件**:

- `src/sibux/main.py`
- `src/sibux/session/service.py`
- 可能新增 `tests/sibux/test_main.py`

**依赖**:

- 依赖 `T5`

**并行性**:

- 不建议与 `T5` 分开太久
- 但可以在 `T5` 主流程稳定后单独实现

### T7. Tool Assembly Seam 收口

**目标**:

- 决定是否保留当前 `ALL_TOOLS + filter`
- 或引入极薄的 tool selector

**建议产出**:

- 一个明确的工具选择入口
- 不影响现有工具实现

**涉及文件**:

- `src/sibux/tools/__init__.py`
- 可选新增 `src/sibux/tools/catalog.py`
- `src/sibux/agent/agent_factory.py`

**依赖**:

- 依赖 `T0`

**并行性**:

- 可以与 `T2`、`T3` 并行
- 如果范围受控, 也可以延后到 `T5` 之后再做

### T8. 测试与回归验证

**目标**:

- 为本阶段关键路径补单元测试和集成测试

**建议产出**:

- config 测试
- session service 测试
- factory 注入测试
- primary session 恢复测试
- subagent 不污染主 session 的测试

**涉及文件**:

- `tests/sibux/config/test_config.py`
- `tests/sibux/agent/test_agent_factory.py`
- 新增 `tests/sibux/session/`
- 可能新增 `tests/sibux/test_main.py`

**依赖**:

- 单元测试可跟随各任务并行补
- 集成验证依赖 `T5`、`T6`

**并行性**:

- 单元测试应与对应实现并行
- 最终回归验证必须在核心功能完成后进行

## 7. 任务依赖关系

### 7.1 串行主路径

建议主路径按下面顺序推进:

1. `T0` 设计收口
2. `T1` Config session 字段
3. `T2` Session Service
4. `T3` Agent Factory 注入
5. `T4` Primary / Subagent 持久化策略
6. `T5` CLI Session Lifecycle
7. `T6` CLI 最小会话命令
8. `T8` 最终集成验证

### 7.2 可并行任务

以下任务可以并行推进:

- `T1` Config 字段
- `T2` Session Service
- `T3` Agent Factory 注入
- `T7` Tool Assembly Seam

前提是:

- `T0` 已经把字段命名、目录约定、subagent 策略定下来

### 7.3 需要等待前序完成的任务

以下任务应等待前序落稳后再做:

- `T4` 必须等待 `T2`、`T3`
- `T5` 必须等待 `T1`、`T2`、`T3`
- `T6` 必须等待 `T5`
- `T8` 的集成验证必须等待 `T5`、`T6`

## 8. 推荐开发分组

如果多人并行, 建议按下面分组:

### 组 A: 配置与会话

- `T1`
- `T2`

### 组 B: Agent 装配

- `T3`
- `T7`

### 组 C: CLI 接入

- `T5`
- `T6`

### 组 D: 测试

- 跟随 `T1`、`T2`、`T3` 同步补单测
- 在 `T5`、`T6` 完成后补最终集成验证

## 9. 建议里程碑

### Milestone 1

- `T0`
- `T1`
- `T2`
- `T3`

完成后应达到:

- session 配置已定
- session service 已可创建 / 恢复
- agent factory 已能注入 `session_manager`

### Milestone 2

- `T4`
- `T5`
- `T6`

完成后应达到:

- primary agent 可恢复
- subagent 保持无状态
- CLI 已具备最小 session 生命周期

### Milestone 3

- `T7`
- `T8`

完成后应达到:

- tool 选择入口清晰
- 测试覆盖本阶段关键路径

## 10. 验收标准

Phase 2 完成时, 至少应满足:

- primary agent 会话可以稳定落盘
- 不再使用默认临时目录保存 session
- CLI 重启后可恢复最近 session
- `task` 子 agent 不会破坏主 session
- agent factory 已支持 session 注入
- 用户仍然能以与 Phase 1 基本相同的方式使用 REPL

## 11. 推荐测试范围

### 单元测试

- session service 的 `create / resume / new`
- config 中 session 字段的默认值与覆盖逻辑
- factory 在有 / 无 `session_manager` 时的装配行为
- primary / subagent 的持久化策略分流

### 集成测试

- CLI 首次启动创建 session
- CLI 二次启动恢复最近 session
- primary agent 的消息历史可恢复
- `task` 工具调用 subagent 时不污染主 session 结构

## 12. 风险与边界

### 9.1 已接受的边界

- Phase 2 只做 file-backed persistence
- 这不是最终 storage 方案
- 这也不是最终事件语义方案

### 9.2 明确延后到后续阶段的内容

- SQLite storage
- message/part projection
- event bus / SSE
- compaction
- retry/backoff 增强
- permission ask mode

### 12.3 这样做的好处

- 改动面显著变小
- 完全贴合 Strands 现有能力边界
- 先把“会话可持续”这件事做对
- 不会在后续 Phase 为了兼容 Strands 而推翻 Phase 2

## 13. 对后续阶段的承诺

Phase 2 完成后, 需要为后续阶段提供下面这些基础:

- `Phase 3`
  - 可以基于现有 session 生命周期继续扩到 compaction 和服务化
  - 可以在现有 primary session 之上挂更多运行状态

- `Phase 4`
  - 可以在 factory/tool seam 上接入 MCP、Skill、Plugin
- 可以在 session service 上继续扩展 richer storage

## 14. 当前结论

本阶段不再追求“基础设施全部定型”, 而是聚焦于:

- **复用 Strands**
- **补齐 Sibux 的 session 产品行为**
- **为后续扩展预留清晰装配边界**

如果后续决定重新引入 SQLite 或独立 event 层, 应作为新的阶段能力来设计, 而不是回到 Phase 2 里提前铺大摊子。
