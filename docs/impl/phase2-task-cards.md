# Phase 2 可派工任务卡

> 本文档用于把 `Phase 2` 拆成可直接派给个人开发的任务卡。
>
> 它不是新的设计文档, 而是把已经收口的 `T0` 翻译成可执行的工作包。

## 1. 使用方式

派工时, 每个任务都应默认遵循以下规则:

- 不重新讨论 `T0` 已收口内容
- 如任务卡与旧文档表述冲突, 以 `phase2-t0-design-closure.md` 为准
- 如任务之间接口理解不一致, 以本文档“冻结接口”一节为准

统一参考文档:

- [implementation-plan.md](./implementation-plan.md)
- [phase2-detailed-plan.md](./phase2-detailed-plan.md)
- [phase2-t0-design-closure.md](./phase2-t0-design-closure.md)

## 2. 冻结接口

这些接口和行为应先冻结, 以便多人并行开发。

### 2.1 Session Config

`Config` 新增最小 session 配置:

```python
class SessionConfig(BaseModel):
    storage_dir: str = ".sibux/session/strands"
    resume: Literal["last", "new"] = "last"
```

约定:

- `storage_dir` 是项目内路径, 默认指向 `.sibux/session/strands`
- `resume` 只支持 `last` 和 `new`
- `Phase 2` 不新增 `persist_subagents`

### 2.2 Session State File

状态文件固定为:

```text
.sibux/session/state.json
```

最小结构:

```json
{
  "version": 1,
  "current_session_id": "sibux_xxx",
  "agent": "build",
  "updated_at": "2026-03-29T12:34:56Z"
}
```

恢复规则:

1. 仅当 `state.json` 中的 `agent` 等于当前启动的 primary agent 名称时, 才尝试恢复
2. 仅当对应 `session_id` 的 session 目录存在时, 才尝试恢复
3. 任一条件不满足时, 创建新 session
4. 如果恢复过程中读取失败或数据损坏, CLI 打印提示后创建新 session

### 2.3 Session Identity

身份生成规则固定为:

- `primary agent_id = agent_config.name`
- `subagent` 不要求稳定 `agent_id`
- `session_id = sibux_<uuid4hex>`

### 2.4 Session Service Interface

`src/sibux/session/service.py` 对外最小接口冻结为:

```python
@dataclass
class ActiveSession:
    session_id: str
    agent_name: str
    agent_id: str
    storage_dir: Path
    state_file: Path
    resumed: bool
    session_manager: FileSessionManager


class SessionService:
    def create_or_resume(self, *, agent_name: str) -> ActiveSession: ...
    def new_session(self, *, agent_name: str) -> ActiveSession: ...
    def current(self) -> ActiveSession | None: ...
```

说明:

- 具体实现可以有私有辅助方法
- 但对外至少要提供上述最小能力
- 若实现时确实需要补充字段, 只能追加, 不能改动已有字段语义

### 2.5 Agent Factory Interface

`src/sibux/agent/agent_factory.py` 的 `create()` 最小签名冻结为:

```python
def create(
    config: Config,
    agent_config: AgentConfig,
    *,
    session_manager: SessionManager | None = None,
    agent_id: str | None = None,
    context_manager: Any | None = None,
) -> strands.Agent:
    ...
```

行为约定:

- primary 路径允许显式传入 `session_manager` 和稳定 `agent_id`
- subagent 路径默认仍调用 `create(config, agent_config)` 的无状态形态
- 不改变现有 model 解析、tool 过滤、system prompt 构建逻辑

## 3. 可并行开始的任务

下面三个任务可以在冻结接口后立即并行开始。

### P1. Config Session Schema

#### 任务目标

把 session 配置模型正式接入 Sibux 配置系统, 但不实现 session 生命周期业务。

#### 必改文件

- `src/sibux/config/config.py`
- `src/sibux/config/defaults.py`
- `tests/sibux/config/test_config.py`

#### 可改文件

- `src/sibux/config/__init__.py`
- `tests/sibux/config/__init__.py`

#### 禁止改动范围

- `src/sibux/main.py`
- `src/sibux/agent/agent_factory.py`
- `src/sibux/tools/task.py`
- 任何 `session` service 实现文件

#### 具体要做什么

1. 在 `Config` 中新增 `session` 字段
2. 新增 `SessionConfig` 模型
3. 在默认配置中写入:
   - `storage_dir = ".sibux/session/strands"`
   - `resume = "last"`
4. 确保全局配置和项目配置可以覆盖 `session` 字段
5. 不添加 `persist_subagents`

#### 精确接口

实现后应允许以下代码成立:

```python
config = load_config()
assert config.session.storage_dir == ".sibux/session/strands"
assert config.session.resume in {"last", "new"}
```

#### 验收标准

- 无配置文件时, `config.session.storage_dir` 和 `config.session.resume` 有正确默认值
- 项目配置可覆盖 `session.resume`
- 项目配置可覆盖 `session.storage_dir`
- 旧配置文件不写 `session` 时不报错
- 不引入与 `Phase 2` 无关的新配置字段

#### 参考文档

- [implementation-plan.md](./implementation-plan.md)
- [phase2-detailed-plan.md](./phase2-detailed-plan.md)
- [phase2-t0-design-closure.md](./phase2-t0-design-closure.md)

#### 参考代码

- `src/sibux/config/config.py`
- `src/sibux/config/defaults.py`

#### 依赖与并行约束

- 只依赖 `T0`
- 可以与 `P2`、`P3` 同时开始
- 需要在提交前确认字段名与冻结接口一致

### P2. Session Service Core

#### 任务目标

实现 Sibux 的薄 session service, 统一封装 `FileSessionManager`、`state.json` 和恢复/新建策略。

#### 必改文件

- `src/sibux/session/__init__.py`
- `src/sibux/session/service.py`
- `tests/sibux/session/test_session_service.py`

#### 可改文件

- `tests/sibux/__init__.py`

#### 禁止改动范围

- `src/sibux/main.py`
- `src/sibux/agent/agent_factory.py`
- `src/sibux/tools/task.py`
- Strands `session` 实现

#### 具体要做什么

1. 新增 `ActiveSession` 数据结构
2. 新增 `SessionService`
3. 统一计算:
   - project session root
   - `.sibux/session/strands`
   - `.sibux/session/state.json`
4. 实现 `session_id = sibux_<uuid4hex>`
5. 实现 `agent_id = agent_name`
6. 实现 `create_or_resume(agent_name=...)`
7. 实现 `new_session(agent_name=...)`
8. 实现 `current()`
9. 统一读写最小 `state.json`
10. 恢复失败时返回新 session, 并把是否恢复成功写入 `resumed`

#### 精确接口

需要满足“冻结接口”一节中的 `ActiveSession` 和 `SessionService` 契约。

#### 验收标准

- 首次调用 `create_or_resume(agent_name="build")` 时创建新 session
- 第二次调用 `create_or_resume(agent_name="build")` 时恢复同一 session
- 若 `state.json` 里的 `agent` 是其他 primary agent, 则创建新 session
- 若 `state.json` 指向不存在的 session 目录, 则创建新 session
- `new_session(agent_name="build")` 总是生成新的 `session_id`
- `current()` 在未创建 session 时返回 `None`
- 所有 session 数据都落在项目内 `.sibux/session/` 下

#### 参考文档

- [implementation-plan.md](./implementation-plan.md)
- [phase2-detailed-plan.md](./phase2-detailed-plan.md)
- [phase2-t0-design-closure.md](./phase2-t0-design-closure.md)

#### 参考代码

- `src/strands/session/file_session_manager.py`
- `src/strands/session/repository_session_manager.py`
- `src/strands/session/session_manager.py`

#### 依赖与并行约束

- 只依赖 `T0`
- 可以与 `P1`、`P3` 同时开始
- 不等待 CLI 接入
- 如 `P1` 尚未合并, 可先按冻结接口中的字段名实现

### P3. Agent Factory Session Seam

#### 任务目标

让 primary agent 可以通过 factory 接入 `session_manager` 和稳定 `agent_id`, 同时保证 subagent 仍然无状态。

#### 必改文件

- `src/sibux/agent/agent_factory.py`
- `src/sibux/tools/task.py`
- `tests/sibux/agent/test_agent_factory.py`

#### 可改文件

- `tests/sibux/tools/test_tools.py`

#### 禁止改动范围

- `src/sibux/main.py`
- `src/sibux/config/config.py`
- `src/sibux/session/service.py`
- 工具权限模型

#### 具体要做什么

1. 扩展 `create()` 签名, 接收:
   - `session_manager`
   - `agent_id`
   - `context_manager`
2. 在创建 Strands `Agent` 时把这些参数正确透传
3. 保持现有:
   - model 解析逻辑
   - tool 过滤逻辑
   - system prompt 构建逻辑
4. 保证 `task()` 创建 subagent 时:
   - 不传 `session_manager`
   - 不依赖稳定 `agent_id`

#### 精确接口

需要满足“冻结接口”一节中的 `create()` 契约。

#### 验收标准

- `create(config, agent_config, session_manager=..., agent_id="build")` 可创建 primary agent
- 不传 `session_manager` 时, 现有无状态路径行为不变
- `task()` 仍能正常创建 subagent
- subagent 路径不会意外接入主 session
- 现有工具过滤测试继续通过

#### 参考文档

- [implementation-plan.md](./implementation-plan.md)
- [phase2-detailed-plan.md](./phase2-detailed-plan.md)
- [phase2-t0-design-closure.md](./phase2-t0-design-closure.md)

#### 参考代码

- `src/sibux/agent/agent_factory.py`
- `src/sibux/tools/task.py`
- `src/strands/agent/agent.py`

#### 依赖与并行约束

- 只依赖 `T0`
- 可以与 `P1`、`P2` 同时开始
- 与 `P2` 之间只通过冻结接口对齐, 不直接等待彼此实现

## 4. 需要等前序合并后再做的串行任务

下面的任务不建议并行起手, 因为它们依赖前面三个工作包都已经稳定。

### S1. CLI Session Lifecycle Integration

#### 前置依赖

- `P1` 已合并
- `P2` 已合并
- `P3` 已合并

#### 任务目标

把 CLI 从无状态 REPL 接成最小 session-aware REPL。

#### 必改文件

- `src/sibux/main.py`
- 对应 CLI 测试文件

#### 可改文件

- `src/sibux/session/__init__.py`
- `tests/sibux/session/test_session_service.py`

#### 禁止改动范围

- 不引入 HTTP / 服务化接口
- 不做 session list / fork / revert
- 不做 SSE / event bus

#### 具体要做什么

1. 启动时加载 config
2. 根据 `default_agent` 取到当前 primary agent
3. 调用 `SessionService.create_or_resume(agent_name=...)`
4. 通过 factory 创建 primary agent:
   - 注入 `session_manager`
   - 注入稳定 `agent_id`
5. 在 CLI 启动信息中显示当前 session 基本信息
6. 恢复失败时打印提示, 然后继续进入新 session

#### 验收标准

- 在同一项目下连续启动两次, 默认 agent 相同时会恢复同一 session
- 切换到另一个 primary agent 启动时不会错误复用旧 agent 的 session
- 没有 session 状态时仍能正常进入 REPL
- 现有 `exit` / `quit` / `/exit` 退出路径保持可用

#### 参考文档

- [implementation-plan.md](./implementation-plan.md)
- [phase2-detailed-plan.md](./phase2-detailed-plan.md)
- [phase2-t0-design-closure.md](./phase2-t0-design-closure.md)
- [phase2-task-cards.md](./phase2-task-cards.md)

### S2. CLI Session Commands

#### 前置依赖

- `S1` 已合并

#### 任务目标

补最小 session 命令集, 先只覆盖 `/new` 和 `/session`。

#### 必改文件

- `src/sibux/main.py`
- 对应 CLI 测试文件

#### 禁止改动范围

- 不做 `/sessions`
- 不做 fork / revert / share
- 不做标题、备注、标签系统

#### 具体要做什么

1. 实现 `/new`
2. `/new` 触发 `SessionService.new_session(agent_name=...)`
3. 用新 session 重新创建当前 primary agent
4. 实现 `/session`
5. `/session` 至少输出:
   - `session_id`
   - `agent_name`
   - `storage_dir`

#### 验收标准

- `/new` 后 `session_id` 变化
- `/new` 后后续对话写入新的 session
- `/session` 输出当前 session 基本信息
- 普通用户输入不被误判为命令

#### 参考文档

- [implementation-plan.md](./implementation-plan.md)
- [phase2-detailed-plan.md](./phase2-detailed-plan.md)
- [phase2-t0-design-closure.md](./phase2-t0-design-closure.md)
- [phase2-task-cards.md](./phase2-task-cards.md)

### S3. 集成验证与文档收尾

#### 前置依赖

- `S2` 已合并

#### 任务目标

把 `Phase 2` 最小闭环跑通, 并把仓库文档和目录说明补齐。

#### 必改文件

- 相关测试文件
- `AGENTS.md`
- 如有需要, 更新 `docs/impl/` 下的规划文档

#### 禁止改动范围

- 不新增 `Phase 3/4` 能力
- 不借机扩展成更复杂的 session 管理系统

#### 具体要做什么

1. 运行并补齐最小测试闭环
2. 验证 primary session 的 create / resume / new 三条路径
3. 验证 subagent 仍无状态
4. 若新增 `src/sibux/session/` 或相关测试目录, 更新 `AGENTS.md`
5. 确认规划文档与实际实现没有漂移

#### 验收标准

- `Phase 2` 的最小链路可用:
  - 启动
  - 恢复
  - 新建
  - 查看当前 session
- 文档、代码、目录结构描述一致
- 没有把 `Phase 3/4` 的内容混入当前实现

#### 参考文档

- [implementation-plan.md](./implementation-plan.md)
- [phase2-detailed-plan.md](./phase2-detailed-plan.md)
- [phase2-t0-design-closure.md](./phase2-t0-design-closure.md)
- [phase2-task-cards.md](./phase2-task-cards.md)

## 5. 推荐分工方式

如果你要分给不同的人, 建议按下面方式切:

- 一个人负责 `P1`
- 一个人负责 `P2`
- 一个人负责 `P3`
- 待三者合并后, 一个人负责 `S1`
- 然后同一人继续做 `S2` 和 `S3`

理由:

- `P1 / P2 / P3` 的写入范围基本可以拆开
- `S1 / S2 / S3` 都会集中碰 CLI 和集成行为, 串行更稳

## 6. 所有人都不要顺手做的事

以下内容虽然相关, 但全部不属于当前任务:

- SQLite 持久化
- 自定义 `SessionRepository`
- message / part projection
- 自定义事件 schema / adapter / emitter
- SSE
- 服务化 API
- subagent 持久化
- MCP / Skill / Plugin 能力扩展
- 更复杂的权限系统
