# Phase 3 可派工任务卡

> 本文档用于把 `Phase 3` 拆成可直接派给个人开发的任务卡。
>
> 它不是新的设计文档, 而是把 `implementation-plan.md` Phase 3 部分翻译成可执行的工作包。

## 1. 使用方式

派工时, 每个任务都应默认遵循以下规则:

- 不重新讨论 Phase 3 已收口内容
- 如任务卡与旧文档表述冲突, 以 `implementation-plan.md` Phase 3 章节为准
- 如任务之间接口理解不一致, 以本文档"冻结接口"一节为准

统一参考文档:

- [implementation-plan.md](./implementation-plan.md)
- [STREAMING_EVENTS.md](../STREAMING_EVENTS.md)

## 2. 核心设计决策

### 2.1 Hook 与 Bus 的职责分离

- **Hook** = 修改执行链路的同步拦截器 (cancel tool, retry, transform prompt)
- **Bus** = 只读事件广播通道, 事件来源是 `Agent.stream_async()`
- Hook 不输出给 Bus, Bus 不依赖 Hook

```
Hook (SibuxHookProvider)
  └─ 修改执行链路 (cancel/retry/transform)

Agent.stream_async()
  └─ yield event ──→ Bus.publish(event) ──→ GlobalBus
                                               │
                                    ┌──────────┼──────────┐
                                    ▼          ▼          ▼
                               SSE /event   HTTP /msg   Future Plugin
```

### 2.2 stream_async 是唯一事件源

`Agent.stream_async()` 已经 yield 出所有执行事件 (生命周期 + 内容增量 + 工具执行 + 最终结果)。
不需要通过 Hook 桥接 (ObserverBridge), 直接在消费 stream_async 的地方 publish 到 Bus 即可。

## 3. 冻结接口

这些接口和行为应先冻结, 以便多人并行开发。

### 3.1 Hook Registration in Agent Factory

`agent_factory.create()` 新增 `hooks` 参数, 透传给 Strands `Agent(hooks=...)`:

```python
def create(
    config: Config,
    agent_config: AgentConfig,
    *,
    session_manager: SessionManager | None = None,
    agent_id: str | None = None,
    context_manager: Any | None = None,
    hooks: list[HookProvider] | None = None,       # Phase 3 新增
) -> strands.Agent:
    ...
```

约定:

- `hooks` 是 Strands `HookProvider` 实例列表
- `None` 或空列表时行为与现有完全一致
- 不改变现有 model 解析、tool 过滤、system prompt 构建逻辑
- subagent 路径不注入 hooks (除非调用方显式传入)

### 3.2 SibuxHookProvider Protocol

Sibux 层的 hook 注册统一通过实现 Strands `HookProvider` 协议:

```python
from strands.hooks.registry import HookProvider, HookRegistry

class SibuxHookProvider(HookProvider):
    """Sibux hooks that intercept and modify agent execution."""

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeToolCallEvent, self.on_before_tool_call)
        registry.add_callback(AfterToolCallEvent, self.on_after_tool_call)
        registry.add_callback(BeforeInvocationEvent, self.on_before_invocation)
        registry.add_callback(AfterInvocationEvent, self.on_after_invocation)
```

约定:

- `tool.execute.before` / `tool.execute.after` 直接桥接 Strands `BeforeToolCallEvent` / `AfterToolCallEvent`
- `chat.message` 通过 `BeforeInvocationEvent` 拦截 (可修改 `event.messages`)
- `chat.system.transform` 在 agent_factory 层实现 (构建 system prompt 后、传给 Agent 前)
- Hook 可修改执行链路 (cancel tool, retry, transform messages)
- Hook 不跨 session / 跨进程
- **Hook 不输出给 Bus** -- Bus 的事件来自 stream_async, 不来自 Hook

### 3.3 Bus Interface

`src/sibux/event/bus.py` 的最小接口冻结为:

```python
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

@dataclass(slots=True, frozen=True)
class BusEvent:
    """Base event published to Bus."""
    type: str               # 如 "message.text.delta", "tool.execute.before"
    session_id: str
    timestamp: str          # ISO 8601 UTC
    payload: Mapping[str, Any]  # 运行时为 MappingProxyType, 不可变

Callback = Callable[[BusEvent], None]

class Bus:
    """Per-session event bus. Read-only broadcast, does not modify execution."""

    def publish(self, event: BusEvent) -> None: ...
    def subscribe(self, event_type: str, callback: Callback) -> None: ...
    def subscribe_all(self, callback: Callback) -> None: ...

class GlobalBus:
    """Process-level singleton. Aggregates all session Bus events."""

    def emit(self, event: BusEvent) -> None: ...
    def on(self, event_type: str, callback: Callback) -> None: ...
    def on_all(self, callback: Callback) -> None: ...
```

约定:

- `Bus` 是 per-session 实例, 生命周期跟随 session
- `GlobalBus` 是进程级单例, 聚合所有 session 的事件
- `Bus.publish()` 内部自动调用 `GlobalBus.emit()` 转发
- 事件是只读广播, 不能通过 Bus 修改执行链路
- `BusEvent.type` 使用 dot-separated 命名
- `BusEvent` 是不可变的 (`frozen=True`), `payload` 运行时为 `MappingProxyType`
- JSON 序列化时使用 `dataclasses.asdict(event)` 或手动 `dict(event.payload)`
- 线程安全 (Bus 和 GlobalBus 可能被多个线程调用)

### 3.4 核心事件类型

Bus 上的事件类型定义冻结为:

**生命周期事件** (从 stream_async 生命周期事件转换):

| 事件类型 | stream_async 来源 | payload 关键字段 |
|---------|-------------------|-----------------|
| `session.created` | SessionService 创建新 session | `agent_name` |
| `session.resumed` | SessionService 恢复已有 session | `agent_name` |
| `invocation.before` | `{"start": True}` | - |
| `invocation.after` | `{"result": AgentResult}` 前的 stop 信号 | `stop_reason` |
| `model.call.before` | model 调用开始 | `model_id` |
| `model.call.after` | model 调用完成 | `model_id`, `usage` |
| `message.added` | `{"message": <Message>}` | `role`, `content_summary` |
| `tool.execute.before` | `contentBlockStart` with `toolUse` | `tool_name`, `tool_use_id` |
| `tool.execute.after` | tool result `{"message": <Message>}` | `tool_name`, `tool_use_id`, `has_error` |

**内容流事件** (从 stream_async 增量事件转换):

| 事件类型 | stream_async 来源 | payload 关键字段 |
|---------|-------------------|-----------------|
| `message.text.delta` | `{"data": ..., "delta": {"text": ...}}` | `text` |
| `message.tool_use.delta` | `{"type": "tool_use_stream", ...}` | `tool_name`, `tool_use_id`, `input_delta` |
| `message.reasoning.delta` | `{"reasoningText": ..., "reasoning": True}` | `text` |
| `message.event` | `{"event": <raw StreamEvent>}` | `event` |
| `tool.stream` | `{"type": "tool_stream", ...}` | `tool_name`, `tool_use_id`, `data` |
| `tool.cancelled` | `{"tool_cancel_event": ...}` | `tool_name`, `tool_use_id` |
| `invocation.result` | `{"result": AgentResult(...)}` | `stop_reason`, `message_id` |

### 3.5 HTTP Route Contracts

`src/sibux/server/app.py` 路由冻结为:

```
POST   /session                 创建 session       → 201 {session_id, agent_name}
POST   /session/{id}/message    发送消息 (流式)     → SSE stream / 200
GET    /session/{id}/messages   获取历史消息        → 200 [{role, content}]
POST   /session/{id}/abort      取消当前 LLM 调用   → 200 {aborted: bool}
GET    /event                   SSE 全局事件流      → SSE stream
GET    /provider                列出可用模型        → 200 [{provider, models}]
```

约定:

- 使用 FastAPI
- SSE 路由 `/event` 订阅 `GlobalBus`
- `/session/{id}/message` 消费 `Agent.stream_async()`, 同时将事件 publish 到 Bus

## 4. 可并行开始的任务

下面三个任务可以在冻结接口后立即并行开始。

### P1. Hook System Core

#### 任务目标

实现 Sibux 的 Hook System, 让 Sibux 层能通过 Strands `HookProvider` 机制拦截和修改 agent 执行链路。

#### 必改文件

- `src/sibux/hooks/__init__.py` (新建)
- `src/sibux/hooks/provider.py` (新建)
- `src/sibux/agent/agent_factory.py`
- `tests/sibux/hooks/test_hook_provider.py` (新建)

#### 可改文件

- `src/sibux/hooks/types.py` (新建, 如需自定义 hook 类型)
- `tests/sibux/agent/test_agent_factory.py`

#### 禁止改动范围

- `src/sibux/main.py`
- `src/sibux/event/` (Bus 是 P2 的职责)
- `src/sibux/server/` (HTTP 是 P3 的职责)
- Strands SDK 源码

#### 具体要做什么

1. 创建 `src/sibux/hooks/` 包
2. 实现 `SibuxHookProvider`:
   - 注册 `BeforeToolCallEvent` 回调, 桥接 `tool.execute.before` 语义
   - 注册 `AfterToolCallEvent` 回调, 桥接 `tool.execute.after` 语义
   - 注册 `BeforeInvocationEvent` 回调, 实现 `chat.message` 拦截 (可修改 `event.messages`)
   - 注册 `AfterInvocationEvent` 回调
3. 实现 `chat.system.transform` 管线:
   - 在 `agent_factory.create()` 中, `build_system_prompt()` 之后、传给 `Agent()` 之前, 运行 transform 函数链
   - transform 函数签名: `(prompt: str) -> str`
   - 通过 `SibuxHookProvider` 或独立 transform list 注册
4. 扩展 `agent_factory.create()`:
   - 新增 `hooks` 参数, 透传给 `strands.Agent(hooks=...)`
   - 默认不注入任何 hook (保持现有行为)
5. 编写测试:
   - `SibuxHookProvider` 注册到 agent 后, `BeforeToolCallEvent` 回调被触发
   - `chat.system.transform` 可修改 system prompt
   - 不传 hooks 时行为与现有一致

#### 精确接口

实现后应允许以下代码成立:

```python
from sibux.hooks import SibuxHookProvider

provider = SibuxHookProvider()
agent = create(config, agent_config, hooks=[provider])
# agent 执行时 provider 的回调会被触发
```

#### 验收标准

- `SibuxHookProvider` 实现 Strands `HookProvider` 协议
- `tool.execute.before/after` 回调在工具执行前后被触发
- `chat.message` 回调可通过 `BeforeInvocationEvent.messages` 修改用户消息
- `chat.system.transform` 可追加或改写 system prompt
- 不传 hooks 时, 现有 agent 行为完全不变
- Hook 不跨 session、不跨进程
- subagent 路径默认不注入 hooks
- **Hook 不输出给 Bus** (Hook 只负责修改, 不负责广播)

#### 参考文档

- [implementation-plan.md](./implementation-plan.md) Phase 3.4
- Strands `HookProvider` 协议: `src/strands/hooks/registry.py`
- Strands hook events: `src/strands/hooks/events.py`

#### 参考代码

- `src/sibux/agent/agent_factory.py`
- `src/strands/hooks/registry.py`
- `src/strands/hooks/events.py`

#### 依赖与并行约束

- 只依赖 Phase 2 已合并代码
- 可以与 `P2`、`P3` 同时开始
- 不依赖 Event Bus (Hook 和 Bus 是独立关注点)

### P2. Event Bus Core

#### 任务目标

实现 Sibux 的 Event Bus 系统, 提供只读事件广播通道, 为后续 SSE 端点和外部消费者提供统一事件源。

#### 必改文件

- `src/sibux/event/__init__.py` (新建)
- `src/sibux/event/bus.py` (新建)
- `src/sibux/event/types.py` (新建)
- `tests/sibux/event/test_bus.py` (新建)

#### 可改文件

- `tests/sibux/event/__init__.py` (新建)

#### 禁止改动范围

- `src/sibux/main.py`
- `src/sibux/hooks/` (Hook 是 P1 的职责)
- `src/sibux/server/` (HTTP 是 P3 的职责)
- `src/sibux/agent/agent_factory.py`
- Strands SDK 源码

#### 具体要做什么

1. 创建 `src/sibux/event/` 包
2. 在 `types.py` 中定义事件类型:
   - `BusEvent` 基础数据类 (type, session_id, timestamp, payload)
   - 冻结接口中列出的所有核心事件类型常量 (生命周期 + 内容流)
3. 实现 `Bus` 类:
   - `publish(event: BusEvent)` -- 广播事件给该 session 的订阅者, 同时转发到 GlobalBus
   - `subscribe(event_type: str, callback)` -- 按事件类型订阅
   - `subscribe_all(callback)` -- 订阅所有事件
4. 实现 `GlobalBus` 类:
   - 进程级单例
   - `emit(event: BusEvent)` -- 广播给全局订阅者
   - `on(event_type: str, callback)` / `on_all(callback)` -- 订阅
5. 编写测试:
   - `Bus.publish()` 触发对应类型的订阅者
   - `Bus.publish()` 自动转发到 GlobalBus
   - `subscribe_all()` 收到所有事件
   - GlobalBus 单例行为正确

#### 精确接口

实现后应允许以下代码成立:

```python
from sibux.event import Bus, GlobalBus, BusEvent

bus = Bus(session_id="sibux_abc123")
events = []
bus.subscribe_all(lambda e: events.append(e))

bus.publish(BusEvent(
    type="message.text.delta",
    session_id="sibux_abc123",
    timestamp="2026-04-13T12:00:00Z",
    payload={"text": "Hello"},
))
assert len(events) == 1
assert events[0].type == "message.text.delta"
```

#### 验收标准

- `Bus` 是 per-session 实例
- `GlobalBus` 是进程级单例
- `publish()` 同时通知 session 订阅者和 GlobalBus
- `subscribe()` 按 event_type 过滤
- `subscribe_all()` 不过滤
- Bus 只做广播, 不修改事件内容
- 线程安全 (Bus 和 GlobalBus 可能被多个线程调用)
- 事件类型常量覆盖生命周期事件和内容流事件

#### 参考文档

- [implementation-plan.md](./implementation-plan.md) Phase 3.5
- [STREAMING_EVENTS.md](../STREAMING_EVENTS.md)

#### 参考代码

- 无直接参考代码, 这是全新模块

#### 依赖与并行约束

- 只依赖 Phase 2 已合并代码
- 可以与 `P1`、`P3` 同时开始
- **不依赖 Hook System** (Bus 事件来自 stream_async, 不来自 Hook)

### P3. HTTP Server Skeleton

#### 任务目标

搭建 FastAPI 应用骨架和路由定义, 不依赖 Event Bus 和 Hook System, 先把 HTTP 层的基本结构建出来。

#### 必改文件

- `src/sibux/server/__init__.py` (新建)
- `src/sibux/server/app.py` (新建)
- `src/sibux/server/routes.py` (新建)
- `tests/sibux/server/test_routes.py` (新建)

#### 可改文件

- `pyproject.toml` (如需添加 fastapi / sse-starlette 依赖)
- `src/sibux/server/schemas.py` (新建, 请求/响应 schema)

#### 禁止改动范围

- `src/sibux/main.py` (CLI 接入是串行任务)
- `src/sibux/hooks/` (Hook 是 P1 的职责)
- `src/sibux/event/` (Bus 是 P2 的职责)
- `src/sibux/agent/agent_factory.py`
- Strands SDK 源码

#### 具体要做什么

1. 创建 `src/sibux/server/` 包
2. 在 `app.py` 中初始化 FastAPI app
3. 在 `routes.py` 中定义路由骨架:
   - `POST /session` -- 创建 session (调用 SessionService)
   - `POST /session/{id}/message` -- 发送消息 (暂时返回 501, 流式响应在 S2 实现)
   - `GET /session/{id}/messages` -- 获取历史消息 (暂时返回空列表)
   - `POST /session/{id}/abort` -- 取消调用 (暂时返回 `{aborted: false}`)
   - `GET /event` -- SSE 事件流 (暂时返回 501, SSE 在 S1 实现)
   - `GET /provider` -- 列出可用模型 (从 config 读取)
4. 定义请求/响应 schema (Pydantic models)
5. 编写测试:
   - `POST /session` 可创建 session 并返回 session_id
   - `GET /provider` 返回配置中的模型列表
   - 未实现的端点返回正确的 501 状态码

#### 精确接口

实现后应允许以下代码成立:

```python
from sibux.server.app import create_app

app = create_app(config)
# FastAPI TestClient 可正常访问路由
```

#### 验收标准

- FastAPI app 可正常启动
- `POST /session` 通过 SessionService 创建 session 并返回 201
- `GET /provider` 返回配置中的模型列表
- 未实现的端点 (message, event) 返回 501 而不是 500
- 不依赖 Event Bus 或 Hook System
- 路由签名与冻结接口一致

#### 参考文档

- [implementation-plan.md](./implementation-plan.md) Phase 3.6

#### 参考代码

- `src/sibux/session/service.py` (SessionService)
- `src/sibux/config/config.py` (Config 结构)

#### 依赖与并行约束

- 只依赖 Phase 2 已合并代码
- 可以与 `P1`、`P2` 同时开始
- 可能需要在 `pyproject.toml` 中添加 fastapi 依赖

## 5. 需要等前序合并后再做的串行任务

下面的任务不建议并行起手, 因为它们依赖前面的工作包。

### S1. SSE Endpoint Wiring

#### 前置依赖

- `P2` 已合并 (Bus 和事件类型)
- `P3` 已合并 (HTTP Server 骨架)

#### 任务目标

把 GlobalBus 接入 HTTP Server 的 SSE 端点, 让外部客户端可以实时订阅系统事件。

#### 必改文件

- `src/sibux/server/routes.py`
- `src/sibux/server/app.py`
- `tests/sibux/server/test_sse.py` (新建)

#### 可改文件

- `pyproject.toml` (如需 sse-starlette)
- `src/sibux/server/sse.py` (新建, SSE 辅助)

#### 禁止改动范围

- `src/sibux/event/bus.py` (Bus 接口已冻结)
- `src/sibux/hooks/` (Hook 实现已完成)
- Strands SDK 源码

#### 具体要做什么

1. 将 `GET /event` 从 501 stub 升级为真实 SSE 端点:
   - 订阅 `GlobalBus.on_all()`
   - 每个 `BusEvent` 序列化为 SSE `data:` 行 (JSON)
   - 客户端断开时清理订阅
2. SSE 消息格式:
   ```
   event: message.text.delta
   data: {"type":"message.text.delta","session_id":"sibux_xxx","timestamp":"...","payload":{...}}

   ```
3. 在 `create_app()` 中注入 GlobalBus 实例
4. 编写测试:
   - SSE 端点可建立连接
   - Bus 发布事件后, SSE 客户端收到对应消息
   - 客户端断开后不再收到事件

#### 验收标准

- `GET /event` 返回 `text/event-stream` Content-Type
- GlobalBus 上发布的事件能通过 SSE 推送到客户端
- 多个 SSE 客户端可同时订阅
- 客户端断开后资源正确清理

#### 参考文档

- [implementation-plan.md](./implementation-plan.md) Phase 3.6
- [STREAMING_EVENTS.md](../STREAMING_EVENTS.md)

### S2. Streaming Message Endpoint

#### 前置依赖

- `S1` 已合并 (SSE 基础设施)

#### 任务目标

实现 `POST /session/{id}/message` 的流式响应, 消费 `Agent.stream_async()`, 同时将事件 publish 到 Bus, 让 HTTP 客户端和 SSE 订阅者都能收到事件。

#### 必改文件

- `src/sibux/server/routes.py`
- `tests/sibux/server/test_streaming.py` (新建)

#### 可改文件

- `src/sibux/server/app.py`
- `src/sibux/server/schemas.py`
- `src/sibux/event/stream.py` (新建, stream_async → Bus 转换逻辑)

#### 禁止改动范围

- `src/sibux/event/bus.py` (Bus 接口已冻结)
- `src/sibux/hooks/`
- `src/sibux/main.py`
- Strands SDK 源码

#### 具体要做什么

1. 实现 stream_async → Bus 转换:
   - 消费 `Agent.stream_async()` 的每个 yield 事件
   - 将 stream_async 事件转换为对应的 `BusEvent` 并 publish 到 Bus
   - 转换映射:
     - `{"data": ..., "delta": {"text": ...}}` → `BusEvent(type="message.text.delta")`
     - `{"type": "tool_use_stream", ...}` → `BusEvent(type="message.tool_use.delta")`
     - `{"reasoningText": ..., "reasoning": True}` → `BusEvent(type="message.reasoning.delta")`
     - `{"event": <StreamEvent>}` → `BusEvent(type="message.event")`
     - `{"message": <Message>}` → `BusEvent(type="message.added")`
     - `{"type": "tool_stream", ...}` → `BusEvent(type="tool.stream")`
     - `{"tool_cancel_event": ...}` → `BusEvent(type="tool.cancelled")`
     - `{"result": AgentResult}` → `BusEvent(type="invocation.result")`
2. 将 `POST /session/{id}/message` 从 501 stub 升级为流式响应:
   - 根据 session_id 找到对应 session
   - 调用 `Agent.stream_async()` 驱动 agent
   - 每个事件同时: (a) publish 到 Bus, (b) 作为 SSE 发给 HTTP 客户端
   - 最终返回 `{"result": ...}` 事件
3. 实现 `POST /session/{id}/abort`:
   - 取消当前正在执行的 LLM 调用
   - 返回 `{aborted: true/false}`
4. 实现 `GET /session/{id}/messages`:
   - 从 session storage 读取历史消息
   - 返回消息列表
5. 需要管理并发 session 状态:
   - 跟踪哪些 session 正在执行
   - abort 时能找到并中断正确的 session

#### 验收标准

- `POST /session/{id}/message` 返回 SSE 流式响应
- 流中包含 text delta、tool_use 等增量事件
- 流结束时包含 result 事件
- **同一事件同时推送到 HTTP 响应流和 Bus** (SSE `/event` 订阅者也能收到)
- `POST /session/{id}/abort` 可中断正在执行的调用
- `GET /session/{id}/messages` 返回该 session 的历史消息

#### 参考文档

- [implementation-plan.md](./implementation-plan.md) Phase 3.6
- [STREAMING_EVENTS.md](../STREAMING_EVENTS.md)

#### 参考代码

- `src/strands/agent/agent.py` (`stream_async()`)
- `src/sibux/session/service.py`

### S3. Integration Validation & CLI Bus Wiring

#### 前置依赖

- `S2` 已合并

#### 任务目标

把 Phase 3 全链路跑通, 在 CLI 中接入 Bus, 并做最终的集成验证。

#### 必改文件

- `src/sibux/main.py`
- 相关测试文件

#### 可改文件

- `src/sibux/session/service.py` (发布 session 事件)
- `AGENTS.md`
- `docs/impl/` 下的规划文档

#### 禁止改动范围

- 不新增 Phase 4 能力
- 不借机扩展复杂权限系统
- 不引入 MCP / Skill / Plugin

#### 具体要做什么

1. CLI Bus 接入:
   - 在 `main.py` 中创建 Bus 实例
   - 在消费 `agent()` 结果的地方, 改用 `agent.stream_async()` 并将事件 publish 到 Bus
   - 确保 agent 执行时事件正确发布到 Bus
2. Session 事件发布:
   - 在 `SessionService` 创建/恢复 session 时, 发布 `session.created` / `session.resumed` 事件到 Bus
3. 添加 `sibux serve` 入口 (可选):
   - 启动 HTTP Server (FastAPI + uvicorn)
   - 从 config 读取 host/port
4. 集成测试:
   - CLI 模式: 启动 → agent 执行 → Bus 收到事件
   - HTTP 模式: 创建 session → 发送消息 → SSE 收到事件
   - 验证 Hook System + Bus + SSE 全链路
5. 文档收尾:
   - 更新 `AGENTS.md` 中的目录结构
   - 确认规划文档与实际实现无漂移

#### 验收标准

- CLI 模式下, Bus 能收到 agent 执行事件 (通过 stream_async)
- HTTP 模式下, SSE 端点能实时推送事件
- Hook System 和 Bus 互不干扰 (Hook 修改执行, Bus 只读广播, 两者独立)
- Phase 3 全链路可用:
  - Hook: 拦截/修改执行
  - Bus: 广播事件 (来自 stream_async)
  - SSE: 外部消费
  - HTTP: 服务化接口
- 没有把 Phase 4 的内容混入当前实现

#### 参考文档

- [implementation-plan.md](./implementation-plan.md) Phase 3 全部
- [STREAMING_EVENTS.md](../STREAMING_EVENTS.md)

## 6. 推荐分工方式

如果你要分给不同的人, 建议按下面方式切:

- 一个人负责 `P1` (Hook System)
- 一个人负责 `P2` (Event Bus)
- 一个人负责 `P3` (HTTP Server)
- 待 P2 + P3 合并后, 一个人负责 `S1` (SSE Wiring)
- 然后依次做 `S2` (Streaming) → `S3` (Integration)

理由:

- `P1 / P2 / P3` 的写入范围完全不重叠, 可安全并行
- `S1` 需要 Bus (P2) 和 HTTP (P3) 都稳定, 但不需要 Hook (P1)
- `S2 / S3` 集中在 HTTP + Bus 层, 串行更稳

依赖关系图:

```
P1 (Hook System)  ──────────────────────────┐
                                             │
P2 (Event Bus)    ─┐                         │
                   ├─→ S1 (SSE) → S2 (Streaming) → S3 (Integration)
P3 (HTTP Skeleton) ┘
```

注意: P1 (Hook) 与 S1/S2 没有依赖关系, 但 S3 集成验证时需要 P1 已就绪。

## 7. 所有人都不要顺手做的事

以下内容虽然相关, 但全部不属于当前任务:

- Output Truncation v2 (完整版输出截断)
- Retry & Error Handling (统一重试)
- Session Compaction (上下文压缩)
- Permission System (完整权限系统)
- MCP Integration
- Skill System
- Plan Agent
- Plugin System
- Agent Generation
- Git Snapshot
- 交互式权限确认 (ask 模式)
- subagent 持久化
