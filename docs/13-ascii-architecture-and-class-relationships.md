# 13. ASCII 架构线框图与类关系图

## 目的

本文件用于提供便于讨论和细化的“纯文本线框图”（非 mermaid 渲染）。

- 图 1：整体架构线框图（顶层组合）
- 图 2：核心类关系图（模块关系）
- 图 3：ASCII UML 类图（类属性/方法）

---

## 图 1：整体架构线框图（ASCII）

```text
+----------------------------------------------------------------------------------+
|                                     Agent                                        |
|                    config + run(task) + resume() + abort()                      |
+----------------------------------------------------------------------------------+
                    | owns
                    v
+----------------------------------------------------------------------------------+
|                                  AgentSession                                    |
|                 sessionId / runId / state / messages / metadata                 |
+----------------------------------------------------------------------------------+
        |                         |                          |
        | uses                    | owns                     | append-only
        v                         v                          v
+---------------------+   +-----------------------+   +-------------------------+
| ContextManager      |   | AgentLoop(EventLoop)  |   | SessionStore            |
| - system prompt     |   | - state machine       |   | - append(message)       |
| - history window    |   | - turn orchestration  |   | - load/replay()         |
| - compaction        |   +-----------+-----------+   +-------------------------+
+----------+----------+               |
           |                          | calls
           |                          v
           |                 +------------------------+
           |                 | Model           |
           |                 | provider -> MessageDelta|
           |                 +-----------+------------+
           |                             |
           |                             | stream
           |                             v
           |                 +------------------------+
           +---------------> | MessageAssembler       |
                             | consume(delta)         |
                             | buildFinalMessage()    |
                             +-----------+------------+
                                         |
                                         | extract tool_call from assistant message
                                         v
                             +------------------------+
                             | EnvironmentManager     |
                             | Runtime + ToolRegistry |
                             | + ToolExecutor         |
                             +-----------+------------+
                                         |
                                         | generate tool_result message
                                         v
                                 back to SessionStore
```

---

## 图 2：核心类关系图（ASCII）

### 关系符号

- `*--` 组合（强拥有）
- `o--` 聚合（弱拥有）
- `..>` 依赖（调用）
- `<|--` 继承/实现

```text
+--------------------+ 1   *-- 1 +----------------------+
| Agent              |------------| AgentSession         |
+--------------------+            +----------------------+
                                  | sessionId            |
                                  | runId                |
                                  | state                |
                                  | messages[]           |
                                  +----------------------+
                                  *-- AgentLoop
                                  *-- SessionStore
                                  o-- ContextManager
                                  o-- Model
                                  o-- MessageAssembler
                                  o-- EnvironmentManager
                                  o-- ObserverHub
```

```text
+--------------------+ *-- +----------------------+
| AgentLoop          |-----| StateMachine         |
+--------------------+     +----------------------+
| runUntilComplete() |     | transition(trigger)  |
| runTurn()          |     | currentState         |
+--------------------+     +----------------------+
..> ContextManager
..> Model
..> MessageAssembler
..> EnvironmentManager
..> SessionStore
```

```text
+----------------------+ <|-- +----------------------+
| Model         |      | OpenAIModel          |
+----------------------+      +----------------------+
| stream()             |      | mapRawToDelta()      |
| update_config()      |      +----------------------+
| get_config()         |
| supports()           |
+----------------------+
<|-- AnthropicModel
<|-- LocalModel
```

```text
+----------------------+ *-- +----------------------+
| EnvironmentManager   |-----| Runtime              |
+----------------------+     +----------------------+
| executeToolCall()    |     | execute(action)      |
+----------------------+     +----------------------+
*-- ToolRegistry
*-- ToolExecutor

ToolExecutor <|-- SequentialToolExecutor
ToolExecutor <|-- ConcurrentToolExecutor
Runtime     <|-- LocalRuntime
Runtime     <|-- RemoteRuntime
```

---

## 图 3：ASCII UML 类图（核心字段 + 方法）

```text
+--------------------------------------------------------------------------------+
| Agent                                                                          |
+--------------------------------------------------------------------------------+
| - config: AgentConfig                                                          |
| - sessionStore: SessionStore                                                   |
+--------------------------------------------------------------------------------+
| + run(task: UserMessage): RunResult                                            |
| + resume(sessionId: string): RunResult                                         |
| + abort(runId: string): void                                                   |
+--------------------------------------------------------------------------------+
                *--
                 |
                 v
+--------------------------------------------------------------------------------+
| AgentSession                                                                   |
+--------------------------------------------------------------------------------+
| - sessionId: string                                                            |
| - runId: string                                                                |
| - state: AgentState                                                            |
| - messages: Message[]                                                          |
+--------------------------------------------------------------------------------+
| + appendMessage(msg: Message): void                                            |
| + loadContext(): Message[]                                                     |
+--------------------------------------------------------------------------------+
      o-- ContextManager   o-- Model   o-- MessageAssembler   o-- EnvironmentManager
      *-- AgentLoop        *-- SessionStore

+----------------------------------+        +-------------------------------------+
| AgentLoop                        |        | Model                        |
+----------------------------------+        +-------------------------------------+
| - stateMachine: StateMachine     |        | + stream(...): DeltaStream           |
+----------------------------------+        | + supports(feature): bool            |
| + runTurn(session): TurnResult   |        +-------------------------------------+
| + handleToolCalls(msg): void     |                         ..> MessageDelta
+----------------------------------+
            ..> MessageAssembler
            ..> SessionStore
            ..> EnvironmentManager

+----------------------------------+
| MessageAssembler                 |
+----------------------------------+
| - buffer: MutableMessage         |
| - deltas: MessageDelta[]         |
+----------------------------------+
| + consume(delta): void           |
| + snapshot(): Message            |
| + buildFinalMessage(): Message   |
+----------------------------------+
```

---

## 当前关系结论（用于后续细化）

1. `AgentSession` 是运行期聚合根，负责持有会话状态与消息。
2. `AgentLoop` 只做编排，不绑定具体模型厂商与 runtime 实现。
3. `Model` 负责 provider -> `MessageDelta` 的差异抹平。
4. `MessageAssembler` 负责增量聚合与最终 message 提交边界。
5. `EnvironmentManager` 负责工具执行并生成统一 `tool_result` message。
