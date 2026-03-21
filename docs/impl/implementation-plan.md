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

## Phase 2 -- 增强体验

在 MVP 可用后, 按优先级逐步添加:

### 2.1 Session Compaction (上下文压缩)

**问题**: 长 session 积累大量历史, 超出 LLM 上下文窗口。

**两阶段策略**:
1. **Prune**: 清空旧工具调用的输出内容, 保留调用结构 (保护最近 40K tokens)
2. **Compact**: 用 LLM (compaction agent) 生成摘要, 替换旧消息

**触发条件**: `total_tokens >= model.context_limit - reserved (20K)`

**实现路径**: Strands 已有 `SummarizingContextManager`, 可扩展实现 prune + compact 两阶段。

### 2.2 Skill System (技能系统)

**概念**: Skill 是 markdown 文件, 包含特定任务的专业指令。Agent 通过 `skill` 工具按需加载。

**文件格式**:
```markdown
---
name: skill-name
description: 一句话描述
---
# 具体指令内容...
```

**扫描位置**: `~/.config/sibux/skills/` + `.sibux/skills/`

**实现**: 新增 `skill` 工具 + skill 列表注入 system prompt。

### 2.3 Hook System (钩子系统)

**关键 Hook 点**:
- `chat.message` -- 用户消息创建后, LLM 调用前
- `tool.execute.before` / `tool.execute.after` -- 工具执行前后
- `chat.system.transform` -- 修改 system prompt
- `session.compacting` -- 压缩前注入上下文

**设计**: `(input, output) => None`, output 是可变对象, hook 可直接修改。

**实现路径**: Strands 已有 `hooks.registry`, 可扩展 hook 事件类型。

### 2.4 MCP Integration (MCP 工具服务器)

**配置**:
```json
{
  "mcp": {
    "github": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  }
}
```

**实现路径**: Strands 原生支持 `MCPClient`, 只需从 config 读取 MCP 配置并初始化。MCP 工具与内置工具等价, 经过相同的权限检查和 hook 触发。

### 2.5 Output Truncation (完整版)

- 超出 50KB 的工具输出存储到临时文件
- 截断内容附带文件路径提示
- 定期清理 (7 天过期)
- `task` 权限的 agent 获得更大截断限制

### 2.6 Retry & Error Handling

- 可重试错误: rate limit (429), overloaded (529)
- 退避策略: 优先用 `retry-after` 响应头, 否则指数退避 `2s * 2^(attempt-1)`, 最大 30s
- 不可重试: context overflow, auth error

---

## Phase 3 -- 生产级功能

### 3.1 Storage Layer (SQLite 持久化)

**数据表**:
- `project` -- 项目元数据
- `session` -- 会话 (关联 project, 支持 parent_id 树状结构)
- `message` -- 消息 (user/assistant, token 统计, cost)
- `part` -- 消息组成单元 (text/tool/reasoning/file)
- `permission` -- 持久化 "always allow" 决策

**实现**: 使用 SQLite + SQLAlchemy 或 Peewee。

### 3.2 Event Bus (事件总线)

**两层设计**:
- `Bus` -- per-session 事件 (message delta, tool execution, error)
- `GlobalBus` -- 跨 session 事件 (session created/destroyed)

**用途**: 解耦模块间通信, 支持 SSE 实时推送。

### 3.3 HTTP Server + SSE

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

### 3.4 Plan Agent (计划模式)

**5 阶段工作流**:
1. Initial Understanding -- 并行启动 explore subagent 探索代码库
2. Design -- general subagent 设计方案
3. Review -- 向用户确认关键决策
4. Final Plan -- 写入计划文件 (唯一允许编辑的文件)
5. Exit -- 通知用户计划完成

**权限约束**: plan agent 只能写 `.sibux/plans/*.md`, 其余文件只读。

### 3.5 Permission Ask Mode (交互式权限)

- 新增 `ask` action: 暂停执行, 等待用户确认
- 用户可选: `once` (本次通过), `always` (持久化), `reject` (拒绝)
- `always` 决策存储到 SQLite, 跨 session 生效
- 默认规则: `.env` 文件读取需要确认

### 3.6 Plugin System (插件系统)

**Plugin 接口**:
```python
class Plugin(Protocol):
    async def init(self, ctx: PluginContext) -> Hooks: ...
```

**加载**: 从配置中指定 Python 包或本地路径, 动态 import。

**能力**: 注册工具、修改 system prompt、拦截工具调用、监听所有事件。

### 3.7 Git Snapshot

- 每轮 LLM 调用前 `git stash` 创建 snapshot
- 支持 `revert` 回滚到任意 snapshot
- session 列表显示代码变更统计 (additions/deletions/files)

### 3.8 Agent Generation (LLM 生成 Agent)

- 用户描述需求, LLM 生成 agent 配置 (identifier + prompt + permission)
- 写入配置文件, 立即可用
- 系统和用户定义的 agent 完全等价

### 3.9 @agent 语法

- 用户输入 `@explore 找所有 API 路由`
- 解析 `@agent` -> 注入 synthetic 消息引导 LLM 调用 task 工具
- 保持工具调用统一性

### 3.10 Structured Output

- 支持 `format: { type: "json_schema", schema: {...} }` 约束输出
- 注入 `StructuredOutput` 工具, 要求 LLM 通过该工具返回结构化结果
- 失败自动重试

---

## 实现优先级总结

```
Phase 1 (MVP)          Phase 2 (增强)           Phase 3 (生产级)
─────────────          ────────────             ──────────────
Config System          Session Compaction       SQLite Storage
Agent Definitions      Skill System             Event Bus
Core Tools (7个)       Hook System              HTTP Server + SSE
Permission (基础)      MCP Integration          Plan Agent
System Prompt          Output Truncation        Permission Ask
Session Loop           Retry & Error            Plugin System
CLI REPL                                        Git Snapshot
                                                Agent Generation
                                                @agent 语法
                                                Structured Output
```

**预估工作量**:
- Phase 1: ~15 个核心文件, 约 2000-3000 行代码
- Phase 2: ~10 个文件, 约 1500-2000 行
- Phase 3: ~20 个文件, 约 3000-5000 行
