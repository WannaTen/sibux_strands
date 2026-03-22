# Sibux 实现计划

> 基于 Strands SDK, 参照 opencode 架构设计, 构建通用编码 Agent

## 架构总览

```
CLI REPL (用户交互)
  │
  ▼
Config System (多层配置加载)
  │
  ▼
Agent Definition (配置即 Agent)
  │
  ├─ permission ruleset (工具权限)
  ├─ model binding (模型绑定)
  ├─ system prompt (行为指令)
  └─ parameters (运行参数)
  │
  ▼
Session Loop (主循环)
  │
  ├─ System Prompt Pipeline (分层构建)
  ├─ Tool Filtering (权限过滤)
  ├─ Strands Agent (LLM 调用 + 工具执行)
  └─ Finish Check (stop / tool-calls / length)
  │
  ▼
Core Tools
  ├─ bash, read, edit, write, glob, grep
  └─ task (subagent 委派)
```

## Strands SDK 可直接复用的能力

以下能力无需从零实现, 直接使用 Strands SDK:

| 能力 | Strands 模块 | 说明 |
|------|-------------|------|
| Model Providers | `strands.models.*` | Bedrock, Anthropic, OpenAI, Gemini, Ollama 等 |
| Tool 定义 | `@tool` 装饰器 | 工具定义、参数验证、docstring 自动提取 |
| MCP Client | `strands.tools.mcp` | 原生 MCP 协议支持 |
| Streaming | `strands.event_loop.streaming` | 流式响应处理 |
| Context Manager | `strands.context_manager.*` | SlidingWindow / Summarizing |
| Multi-agent | `strands.multiagent.*` | Graph / Swarm 模式 |
| Hooks | `strands.hooks.*` | 事件驱动的生命周期钩子 |
| Session 持久化 | `strands.session.*` | File / S3 session manager |

---

## Phase 1 -- MVP (可用的编码 Agent)

核心目标: 一个能在终端中交互式使用的编码 agent, 支持多模型、工具调用、subagent 委派。

### 1.1 Config System (配置系统)

**职责**: 多层配置加载与合并, 为所有模块提供统一配置入口。

**配置加载优先级** (低 -> 高):
1. 内置默认值
2. 全局配置 `~/.config/sibux/config.json`
3. 项目配置 `.sibux/config.json`

**合并策略**: 对象深度合并, 数组字段 (plugin, instructions) concat 合并。

**Config 结构**:

```python
@dataclass
class Config:
    # 模型配置
    provider: dict[str, ProviderConfig]  # provider_id -> {api_key, base_url, models}

    # Agent 配置
    agents: dict[str, AgentConfig]       # agent_name -> {model, prompt, permission, temperature}

    # 默认设置
    default_agent: str = "build"

    # 权限配置 (全局级别)
    permission: dict[str, str | dict[str, str]]  # permission_name -> action | {pattern: action}

    # 自定义指令 (追加到 system prompt)
    instructions: list[str] = []         # 文件路径, 内容追加到 system prompt

    # MCP 服务器 (Phase 2)
    mcp: dict[str, MCPServerConfig] = {}

    # 压缩配置 (Phase 2)
    compaction: CompactionConfig | None = None
```

**关键实现点**:
- 使用 Pydantic 做 schema 验证
- 支持 JSONC 格式 (带注释的 JSON)
- 配置变更时支持热重载 (Phase 2)

### 1.2 Agent Definitions (Agent 定义层)

**核心设计**: Agent 不是进程, 是配置集合。创建成本为零, 权限边界即能力边界。

**AgentConfig 结构**:

```python
@dataclass
class AgentConfig:
    name: str
    mode: Literal["primary", "subagent"]  # primary 面向用户, subagent 被 task 调用
    permission: list[PermissionRule]       # 权限规则集
    model: ModelRef | None = None          # 绑定模型, None 则继承默认
    prompt: str = ""                       # agent 特定 system prompt
    temperature: float | None = None
    max_steps: int = 100                   # 最大工具调用轮次
```

**内置 Agent**:

| Agent | mode | 权限 | 用途 |
|-------|------|------|------|
| `build` | primary | 全部允许 | 默认编码 agent, 可读可写可执行 |
| `explore` | subagent | 只读 (grep/glob/read/bash) | 代码探索, 禁止修改 |
| `general` | subagent | 全部允许 (除 task) | 通用子任务执行 |

**Agent 与 Strands Agent 的关系**:

```python
def create_strands_agent(agent_config: AgentConfig, config: Config) -> strands.Agent:
    model = resolve_model(agent_config, config)
    tools = filter_tools_by_permission(all_tools, agent_config.permission)
    system_prompt = build_system_prompt(agent_config, config)

    return strands.Agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        # ... other params
    )
```

### 1.3 Core Tools (核心工具集)

所有工具用 Strands `@tool` 装饰器实现, 遵循 opencode 的工具接口设计。

| 工具 | 参数 | 说明 |
|------|------|------|
| `bash` | command, timeout?, description? | 执行 shell 命令 |
| `read` | file_path, offset?, limit? | 读取文件内容, 支持分页 |
| `edit` | file_path, old_string, new_string, replace_all? | 查找替换编辑 |
| `write` | file_path, content | 写入/创建文件 |
| `glob` | pattern, path? | 文件路径搜索 |
| `grep` | pattern, path?, include? | 内容搜索 (基于 ripgrep) |
| `task` | agent, prompt, description | 创建 subagent 执行子任务 |

**task 工具 (关键)**:

```python
@tool
def task(agent: str, prompt: str, description: str) -> str:
    """创建 subagent 执行子任务。

    Args:
        agent: subagent 名称 (如 "explore", "general")
        prompt: 子任务的详细指令
        description: 任务简要描述
    """
    agent_config = config.agents[agent]
    assert agent_config.mode != "primary"  # 防止 subagent 创建 primary agent

    sub_agent = create_strands_agent(agent_config, config)
    result = sub_agent(prompt)
    return result.message  # 返回最后一条 assistant 消息
```

**工具输出截断** (基础版):

```python
MAX_OUTPUT_LINES = 2000
MAX_OUTPUT_BYTES = 50 * 1024  # 50KB

def truncate_output(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= MAX_OUTPUT_LINES and len(text.encode()) <= MAX_OUTPUT_BYTES:
        return text
    # 截断并提示
    truncated = "\n".join(lines[:MAX_OUTPUT_LINES])
    return truncated + "\n[Output truncated]"
```

### 1.4 Permission System (基础权限)

**核心设计**: last-match-wins 规则求值。在工具列表传给 LLM 之前按权限过滤。

**数据结构**:

```python
@dataclass
class PermissionRule:
    permission: str   # 权限名 (工具名或通配符)
    pattern: str      # 资源模式, "*" 表示所有
    action: Literal["allow", "deny"]  # MVP 只支持 allow/deny
```

**求值逻辑**:

```python
def evaluate(permission: str, rules: list[PermissionRule]) -> str:
    """last-match-wins: 最后一条匹配的规则生效。"""
    result = "allow"  # 默认允许
    for rule in rules:
        if wildcard_match(permission, rule.permission):
            result = rule.action
    return result

def filter_tools(tools: list, rules: list[PermissionRule]) -> list:
    """过滤掉 action=deny 且 pattern='*' 的工具。"""
    return [t for t in tools if evaluate(t.name, rules) != "deny"]
```

**内置 Agent 权限示例**:

```python
# explore agent: 只读
EXPLORE_PERMISSION = [
    PermissionRule("*", "*", "deny"),      # 默认禁止
    PermissionRule("grep", "*", "allow"),
    PermissionRule("glob", "*", "allow"),
    PermissionRule("read", "*", "allow"),
    PermissionRule("bash", "*", "allow"),   # bash 允许但只能做只读操作 (靠 prompt 约束)
]

# build agent: 全部允许
BUILD_PERMISSION = [
    PermissionRule("*", "*", "allow"),
]

# general subagent: 允许大部分, 禁止创建 sub-subagent
GENERAL_PERMISSION = [
    PermissionRule("*", "*", "allow"),
    PermissionRule("task", "*", "deny"),    # 禁止嵌套 subagent
]
```

### 1.5 System Prompt Pipeline (提示词构建)

**分层构建** (按顺序拼接):

```
1. Provider Prompt     -- 按模型选择基础 prompt 模板
2. Environment Info    -- 工作目录、平台、日期、模型名
3. Instructions        -- AGENTS.md + 用户自定义 instructions
4. Agent Prompt        -- agent 特定 prompt (如 explore 的只读约束)
5. Tool Descriptions   -- 可用工具列表 (已按权限过滤)
```

**实现**:

```python
def build_system_prompt(agent_config: AgentConfig, config: Config) -> str:
    parts = []

    # 1. 环境信息
    parts.append(build_environment_prompt())

    # 2. 项目 instructions (AGENTS.md 等)
    for instruction_path in config.instructions:
        content = load_instruction(instruction_path)
        if content:
            parts.append(content)

    # 3. Agent 特定 prompt
    if agent_config.prompt:
        parts.append(agent_config.prompt)

    return "\n\n".join(parts)

def build_environment_prompt() -> str:
    return f"""## Environment
- Working directory: {os.getcwd()}
- Platform: {platform.system()}
- Date: {datetime.now().strftime('%Y-%m-%d')}
- Shell: {os.environ.get('SHELL', '/bin/sh')}
"""
```

### 1.6 Session Loop (主循环)

**核心逻辑**: 封装 Strands Agent 调用, 实现 opencode 风格的 while 循环。

```python
def session_loop(session: Session, user_input: str):
    agent_config = resolve_agent(session)
    strands_agent = create_strands_agent(agent_config, config)

    # Strands Agent 内部已有 event_loop 处理 tool-calls 循环
    # 我们在外层处理 session 级别逻辑
    result = strands_agent(user_input)

    # 记录到 session 历史
    session.add_message("user", user_input)
    session.add_message("assistant", result.message)

    return result
```

注: Strands 的 `Agent.__call__` 内部已经实现了 tool-calls 循环 (event_loop), 我们不需要重新实现 LLM -> tool -> LLM 的循环, 只需在外层做 session 管理和 agent 配置注入。

### 1.7 CLI 交互入口

**简单 REPL**:

```python
def main():
    config = load_config()
    session = Session()

    print("Sibux Agent (type 'exit' to quit)")

    while True:
        user_input = input("> ")
        if user_input.strip() in ("exit", "quit"):
            break

        result = session_loop(session, user_input)
        # Strands 的 streaming callback 会实时输出
```

### MVP 文件结构

```
src/sibux/
├── __init__.py
├── main.py                  # CLI 入口 + REPL
├── config/
│   ├── __init__.py
│   ├── config.py            # Config 数据模型 + 加载逻辑
│   └── defaults.py          # 内置默认配置
├── agent/
│   ├── __init__.py
│   ├── agent_config.py      # AgentConfig 数据模型
│   ├── agent_factory.py     # 根据 AgentConfig 创建 Strands Agent
│   ├── system_prompt.py     # System Prompt 分层构建
│   └── builtin_agents.py    # 内置 agent 定义 (build/explore/general)
├── tools/
│   ├── __init__.py
│   ├── bash.py              # Shell 执行
│   ├── read.py              # 文件读取
│   ├── edit.py              # 文件编辑
│   ├── write.py             # 文件写入
│   ├── glob_tool.py         # 路径搜索
│   ├── grep.py              # 内容搜索
│   ├── task.py              # Subagent 委派
│   └── truncation.py        # 输出截断
├── permission/
│   ├── __init__.py
│   └── permission.py        # 权限规则求值 + 工具过滤
└── session/
    ├── __init__.py
    └── session.py           # Session 状态 + 主循环
```

---

## Phase 2 -- 基础设施定型

目标: 在不改变 Phase 1 使用方式的前提下, 把运行时、持久化和事件模型定型, 为后续生产化和能力扩展提供稳定底座。

### 2.1 Runtime Kernel Completion (运行时内核补全)

**目标**: 从“直接创建 Agent 并调用”的 MVP 结构, 演进到可承载长会话、持久化、服务化的运行时内核。

**交付物**:
- `SessionRuntime` / `TurnContext` / `InvocationContext` 等内部运行时对象
- 统一的消息模型, 明确 user / assistant / tool / reasoning / file 等 part 边界
- token 统计与上下文窗口预算接口
- 动态 tool registry, 不再依赖静态 `ALL_TOOLS` 列表
- 配置模型扩展骨架, 为 storage / event / service / mcp 等后续配置预留字段

**非目标**:
- 不在此阶段引入 MCP、Skill、Plugin 等新能力
- 不在此阶段实现交互式权限确认

### 2.2 Storage Layer (SQLite 持久化)

**目标**: 为 session、message、message part 等核心运行时状态提供可靠持久化, 支撑会话恢复、历史查看和服务接口。

**首批数据表**:
- `project` -- 项目元数据
- `session` -- 会话元数据, 支持 parent_id 树状关系
- `message` -- 消息记录, 包含角色、时序、token 统计、stop reason
- `part` -- 消息组成单元, 支持 text / tool / reasoning / file 等类型

**交付物**:
- SQLite repository 抽象
- session 创建、读取、追加消息、恢复最近会话
- 基础 migration 机制, 保证后续 Phase 可继续扩表

**非目标**:
- 本阶段不落地 permission decision 持久化逻辑
- 本阶段不要求暴露 HTTP API

### 2.3 Unified Event Semantics (统一事件语义)

**目标**: 先定义“系统里到底发生了什么”, 再分别实现 hook、bus、SSE 等传播方式。

**需要定型的内容**:
- 事件命名与层级, 例如 `session.*`, `chat.*`, `model.*`, `tool.*`, `storage.*`
- 事件 payload 结构, 明确 session_id、turn_id、message_id、tool_call_id、timestamp 等字段
- streaming delta 语义, 明确增量文本、工具状态、结束事件
- interrupt / abort / error 语义, 保证 CLI 和 HTTP 使用同一套约定

**交付物**:
- 事件类型定义与 schema
- 事件生命周期文档
- 核心发射点清单, 说明哪些模块负责发什么事件

**非目标**:
- 本阶段只定语义和边界, 不要求把 bus / hook / SSE 全部实现完

**Phase 2 依赖关系**:
- `Storage Layer` 依赖 `运行时内核补全`, 因为要先有稳定的 session/message 模型
- `统一事件语义` 依赖 `运行时内核补全`, 因为事件必须绑定到真实运行时对象

---

## Phase 3 -- 生产可用

目标: 让 Sibux 在 CLI 和服务端场景下都具备稳定运行能力, 支持长会话、错误恢复、事件流和外部接口。

### 3.1 Output Truncation v2 (完整版输出截断)

**目标**: 工具输出不再只是简单截断, 而是具备可追溯、可恢复的上下文控制能力。

**交付物**:
- 超出阈值的工具输出写入临时文件或受控缓存目录
- 截断返回值附带文件路径和摘要信息
- 临时文件自动清理策略, 默认 7 天过期
- 不同 agent / tool 的差异化截断配额

### 3.2 Retry & Error Handling

**目标**: 对可恢复错误做统一重试, 对不可恢复错误做清晰分类和暴露。

**交付物**:
- 可重试错误分类: `429`, `529`, provider overloaded 等
- 统一退避策略: 优先使用 `retry-after`, 否则指数退避 `2s * 2^(attempt-1)`, 最大 30s
- 明确不可重试错误: context overflow、auth error、invalid request 等
- CLI 与 HTTP 共用的错误表示结构

### 3.3 Session Compaction (上下文压缩)

**目标**: 让长会话在有限上下文窗口内可持续运行。

**两阶段策略**:
1. `Prune`: 清空较旧工具调用的冗长输出, 保留调用结构和关键结论
2. `Compact`: 使用 compaction agent 生成历史摘要, 替换旧消息

**触发条件**:
- `total_tokens >= model.context_limit - reserved`
- 默认保留最近 20K tokens 的安全余量

**实现路径**:
- 优先复用 Strands 的 `SummarizingContextManager`
- 在其上扩展 prune + compact 双阶段策略

### 3.4 Event Bus + Hook System

**目标**: 在 Phase 2 统一事件语义的基础上, 落地内部事件传播和可拦截扩展点。

**Event Bus 交付物**:
- `Bus` -- per-session 事件流
- `GlobalBus` -- 进程级全局事件流
- 订阅 / 发布接口
- 支持 message delta、tool execution、abort、error、compaction 等核心事件

**Hook System 交付物**:
- `chat.message` -- 用户消息创建后, 模型调用前
- `chat.system.transform` -- system prompt 构建后, 最终下发前
- `tool.execute.before` / `tool.execute.after` -- 工具执行前后
- `session.compacting` -- 压缩前, 允许注入额外上下文

**设计约束**:
- hook 与 event bus 使用同一套事件语义
- hook 负责“修改执行过程”, event bus 负责“广播执行事实”

### 3.5 HTTP Server + SSE

**目标**: 在已有运行时和事件系统之上提供服务化接口, 让 Sibux 不再局限于本地 REPL。

**技术栈**: FastAPI + SSE

**核心路由**:
```
POST   /session                 创建 session
POST   /session/:id/message     发送消息 (流式响应)
GET    /session/:id/messages    获取历史
POST   /session/:id/abort       取消 LLM 调用
GET    /event                   SSE 实时事件流
GET    /provider                列出可用模型
```

**交付物**:
- session API 与 storage 打通
- streaming 响应与 SSE 事件打通
- abort 语义与运行时 interrupt 对齐

**Phase 3 依赖关系**:
- `Output Truncation v2` 依赖 `运行时内核补全`, 因为要接入统一工具输出路径
- `Retry & Error Handling` 依赖 `统一事件语义`, 因为错误和重试状态需要统一表示
- `Session Compaction` 依赖 `运行时内核补全` 和 `Storage Layer`
- `Event Bus + Hook System` 依赖 `统一事件语义`
- `HTTP Server + SSE` 依赖 `Storage Layer` 与 `Event Bus + Hook System`

---

## Phase 4 -- 能力扩展

目标: 在稳定底座和生产能力之上, 增加权限、安全边界、工作流、生态扩展和自动化能力。

### 4.1 Permission System (完整权限系统)

**目标**: 从 MVP 的“工具级预过滤”升级为运行时权限系统。

**交付物**:
- `allow` / `deny` / `ask` 三种 action
- path-level 规则匹配, 如 `.env`、证书、密钥目录等
- 运行时权限检查, 不再只在工具列表构建前过滤
- 用户确认模式: `once` / `always` / `reject`
- `always` 决策持久化到 SQLite

**说明**:
- Phase 4 中所有扩大能力边界的特性, 都应建立在完整权限系统之上

### 4.2 MCP Integration (MCP 工具服务器)

**目标**: 把外部 MCP 工具纳入统一工具体系。

**交付物**:
- 从 config 读取 MCP server 定义并初始化
- stdio / 本地命令启动模式
- MCP 工具参与同一套权限检查、事件发射和错误处理

### 4.3 Skill System (技能系统)

**目标**: 提供可复用的任务级专业指令封装。

**文件格式**:
```markdown
---
name: skill-name
description: 一句话描述
---
# 具体指令内容...
```

**扫描位置**:
- `~/.config/sibux/skills/`
- `.sibux/skills/`

**交付物**:
- skill 扫描与索引
- `skill` 工具
- skill 列表注入 system prompt

### 4.4 Plan Agent (计划模式)

**目标**: 提供“先分析、后设计、再确认”的高价值工作流。

**5 阶段工作流**:
1. `Initial Understanding` -- 并行启动 explore subagent 探索代码库
2. `Design` -- general subagent 设计方案
3. `Review` -- 向用户确认关键决策
4. `Final Plan` -- 写入计划文件
5. `Exit` -- 通知用户计划完成

**权限约束**:
- plan agent 只能写 `.sibux/plans/*.md`
- 其余文件默认只读

### 4.5 @agent 语法

**目标**: 提供显式 agent 入口语法, 但不引入新的执行模型。

**行为**:
- 用户输入 `@explore 找所有 API 路由`
- 解析 `@agent` 为 synthetic 消息
- 最终仍然通过统一的 `task` 工具路径执行

### 4.6 Structured Output

**目标**: 提供稳定的结构化结果约束, 支撑后续自动化能力。

**交付物**:
- `format: { type: "json_schema", schema: {...} }` 输出约束
- `StructuredOutput` 工具
- 结构化结果校验与失败重试

### 4.7 Plugin System (插件系统)

**目标**: 允许外部扩展在不修改核心代码的情况下接入 Sibux。

**Plugin 接口**:
```python
class Plugin(Protocol):
    async def init(self, ctx: PluginContext) -> Hooks: ...
```

**能力**:
- 注册工具
- 修改 system prompt
- 拦截工具调用
- 监听所有事件

### 4.8 Agent Generation (LLM 生成 Agent)

**目标**: 让用户通过自然语言生成新的 agent 配置。

**交付物**:
- 生成 agent 配置: identifier + prompt + permission + model
- 写入配置文件并立即生效
- 与系统内置 agent 使用同一套配置模型

### 4.9 Git Snapshot

**目标**: 为每轮关键执行保留可回滚代码快照。

**交付物**:
- 每轮 LLM 调用前创建 git snapshot
- 支持回滚到任意 snapshot
- session 列表显示代码变更统计

**说明**:
- 该能力价值较高, 但实现复杂度也高
- 可在 Phase 4 内作为并行支线推进, 不阻塞其他扩展能力

**Phase 4 依赖关系**:
- `Permission System` 是本阶段其他高能力特性的安全前置
- `MCP Integration` 依赖 `Permission System`、`Event Bus + Hook System`
- `Skill System` 依赖 `运行时内核补全` 与 `chat.system.transform` hook
- `Plan Agent` 依赖 `Permission System` 与 `@agent` / `task` 路径稳定
- `@agent` 语法依赖 `task` 工具与 agent registry 稳定
- `Structured Output` 依赖 `Retry & Error Handling`
- `Plugin System` 依赖 `Event Bus + Hook System`
- `Agent Generation` 依赖 `Structured Output`
- `Git Snapshot` 依赖 `Storage Layer` 与 `Permission System`

---

## 阶段依赖关系总览

- `Phase 2 / 运行时内核补全` 是后续所有阶段的共同前置
- `Phase 2 / Storage Layer` 是 `Session Compaction`、`HTTP Server + SSE`、`Permission System`、`Git Snapshot` 的前置
- `Phase 2 / 统一事件语义` 是 `Event Bus + Hook System`、`HTTP Server + SSE`、`Plugin System` 的前置
- `Phase 3 / Event Bus + Hook System` 是 `HTTP Server + SSE`、`MCP Integration`、`Plugin System` 的前置
- `Phase 3 / Retry & Error Handling` 是 `Structured Output`、`MCP Integration` 等复杂执行路径的前置
- `Phase 4 / Permission System` 必须先于 `MCP Integration`、`Plan Agent`、`Plugin System`、`Git Snapshot`
- `Phase 4 / Structured Output` 必须先于 `Agent Generation`

---

## 实现优先级总结

```
Phase 1 (MVP)          Phase 2 (基础设施)        Phase 3 (生产可用)        Phase 4 (能力扩展)
─────────────          ────────────────          ────────────────          ────────────────
Config System          Runtime Kernel            Output Truncation v2      Permission System
Agent Definitions      SQLite Storage            Retry & Error Handling     MCP Integration
Core Tools (7个)       Event Semantics           Session Compaction         Skill System
Permission (基础)                               Event Bus + Hook System    Plan Agent
System Prompt                                   HTTP Server + SSE          @agent 语法
Session Loop                                                              Structured Output
CLI REPL                                                                  Plugin System
                                                                          Agent Generation
                                                                          Git Snapshot
```

**预估工作量**:
- Phase 1: ~15 个核心文件, 约 2000-3000 行代码
- Phase 2: ~8-12 个文件, 约 1200-2200 行
- Phase 3: ~12-18 个文件, 约 2000-3500 行
- Phase 4: ~15-25 个文件, 约 2500-4500 行
