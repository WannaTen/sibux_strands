# 03. ContextManager 设计

## 1. 职责

ContextManager 负责：
- 接收 session entries（包含 messages 与 compaction summary 等 entry）
- 接收上游 user 输入（可能是 message list，session 为空时可直接接入）
- 按策略执行 normalize / dedupe / truncate / compact
- 组装 system prompt 与 runtime 初始数据（如 cwd/os/sandbox/time）
- 输出本轮调用的 `modelMessages[]` 与统计信息
- 在 agent loop 中间判断是否触发处理策略，并返回需要写入 session 的更新

补充说明（工作流视角）：

- 每轮请求开始：接收 `sessionEntries` + `inputMessages` + `systemPrompt` + `toolSpecs` + `runtimeInitData`，生成本轮起始 `modelMessages[]`
- 运行中间：根据 overflowHint / tokenOverflow 等信号决定是否更新上下文
- 每次对 message list 的变动都产出 `entriesToAppend`，由上层持久化，保证同一 session 内幂等与可回放
- session 为空时，允许仅用 `inputMessages` 直接生成上下文

ContextManager 不负责：
- 生成模型请求参数（temperature/maxTokens 等）
- 持久化 session（但需返回可持久化的更新）
- 工具执行与工具选择
- 上层的 loop 编排与重试策略

## 2. 初始化

初始化输入（示意）：

```text
ContextManagerInit:
  config: ContextConfig
  tokenizer: Tokenizer
  compactor: Compactor (optional)
  runtimeHintProvider: RuntimeHintProvider (optional)
```

初始化流程：
- 校验 config
- 绑定 tokenizer/compactor/runtimeHintProvider

失败策略：
- 入参非法直接抛错
- compactor 缺失时禁用压缩能力

## 3. 字段定义

```text
ContextManager fields:
  config: ContextConfig
  tokenizer: Tokenizer
  compactor: Compactor (optional)
  runtimeHintProvider: RuntimeHintProvider (optional)
```

`ContextConfig` 取自 `AgentConfig.context`：

```text
ContextConfig:
  maxInputTokens: integer
  maxHistoryMessages: integer
  enableCompaction: boolean
```

## 4. 方法定义

```text
buildContext(input: ContextBuildInput) -> ContextBuildResult
computeContextUpdates(input: ContextUpdateRequest) -> ContextUpdateResult
estimateTokens(messages: Message[]) -> integer
```

`ContextBuildInput`（示意）：

```text
ContextBuildInput:
  systemPrompt: text (optional)
  sessionEntries: SessionEntry[]
  inputMessages: Message[] (optional)
  runtimeInitData: map (optional)
  runtimeHints: map (optional)
  toolSpecs: ToolSpec[] (optional)
  overflowHint: boolean (optional)
```

`ContextBuildResult`（示意）：

```text
ContextBuildResult:
  modelMessages: Message[]
  modelToolSpecs: ToolSpec[] (optional)
  compacted: boolean
  compactionSummaryEntry: SessionEntry (optional)
  entriesToAppend: SessionEntry[] (optional)
  stats: {inputTokens, messageCount, droppedMessagesCount}

ContextUpdateRequest:
  sessionEntries: SessionEntry[]
  newMessages: Message[] (optional)
  overflowHint: boolean (optional)

ContextUpdateResult:
  updatedMessages: Message[] (optional)
  compacted: boolean
  entriesToAppend: SessionEntry[] (optional)
  stats: {inputTokens, messageCount, droppedMessagesCount}
```

语义说明：
- `buildContext` 只做上下文裁剪与组装，不直接写 session
- 当发生 compaction 或需要记录变更时，返回 `entriesToAppend`，由上层负责持久化
- `inputMessages` 允许直接传入（session 为空时的启动场景）
- `systemPrompt` 若提供则视为 override；否则从 `AgentConfig.prompt.system` 取值
- `runtimeInitData` 应在同一 session 内保持稳定，用于保证 prompt cache 的幂等性
- `runtimeHints` 允许变动（如 time、locale），可能影响是否命中 prompt cache
- `modelToolSpecs` 仅透传上层顺序，不做过滤/排序；若某些模型需要“工具 schema 内联到 prompt”，由 Model 层处理
- `computeContextUpdates` 建议在 overflowHint=true 或模型返回 tokenOverflow 时调用
- `computeContextUpdates` 只做“追加 + 压缩”，不重排历史顺序

## 5. 状态与不变量

- ContextManager 应保持无状态或可重入
- 同一 session 输入必须得到确定性输出（`sessionEntries + runtimeInitData + systemPrompt` 相同，则 `modelMessages[]` 一致）
- compaction 输出必须可回放（summary 作为显式 entry 落库）

## 6. 数据流与依赖

上游依赖：
- AgentLoop 提供 session entries 与 system prompt
- Runtime 提供 runtime 初始数据与 runtime hints（可选）
- ToolRegistry 提供 tool specs（可选）

下游依赖：
- Model 使用 `modelMessages[]` 与 `modelToolSpecs[]`
- SessionStore 写入 entriesToAppend（由上层触发）

输入输出边界：
- 输入：ContextBuildInput / ContextUpdateRequest
- 输出：ContextBuildResult / ContextUpdateResult

## 7. v0 决策

- 仅支持窗口裁剪 + 单段 summary 压缩
- 仅在超阈值或 overflowHint 时触发 compaction
- 不引入多级摘要或向量检索
- 不在 ContextManager 内部写 session

## 8. 开放问题

- `runtimeHints` 的规范字段集合是否固定
- compaction 是否需要可插拔的多策略（摘要/删除/结构保留）
- `toolSpecs` 是否需要在 ContextManager 进行过滤或排序
