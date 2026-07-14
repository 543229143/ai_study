# Pi Agent 精读计划

> 前置基础：已理解 Function Calling 核心循环（LLM 返回 JSON → 执行 → 结果回填 → 再调 LLM）
> 时间安排：每天 1 小时（30 分钟读代码 + 30 分钟动手改/写验证）
> 仓库：https://github.com/earendil-works/pi

---

## 第一周：理解 LLM 抽象层（packages/ai）

---

### Day 1 — pi-ai 类型系统

**架构图：pi-ai 类型体系**

```
┌────────────────────────────────────────────────────────────┐
│                   pi-ai 类型系统 (types.ts)                  │
│                                                            │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────┐  │
│  │   Message    │   │  Model<TApi> │   │ProviderId     │  │
│  │              │   │              │   │               │  │
│  │ UserMessage  │   │  name        │   │ "anthropic"   │  │
│  │ AssistantMsg │   │  api         │   │ "openai"      │  │
│  │ ToolResultMsg│   │  contextWin  │   │ "google"      │  │
│  │              │   │  cost/thinking│  │ "deepseek"    │  │
│  └──────┬───────┘   └──────┬───────┘   │ 30+ 厂商      │  │
│         │                  │           └───────────────┘  │
│         ▼                  ▼                              │
│  ┌──────────────────────────────────────────────────┐     │
│  │        AssistantMessageEvent (流式事件协议)        │     │
│  │                                                   │     │
│  │  start  →  text delta  →  toolcall delta  →  done │     │
│  │  (会话开始) (逐 token)   (逐 token 工具参数)  (结束) │     │
│  └──────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────┘
```

**读** `packages/ai/src/types.ts`：
- `Message` 类型：UserMessage / AssistantMessage / ToolResultMessage
- `Model<TApi>` 接口：成本、上下文窗口、thinking 等级
- `AssistantMessageEvent`：流式事件协议（start / text delta / toolcall delta / done / error）

**对照** `mini_agent.py` 里的 messages list，理解 pi-ai 的 Message 就是在做同样的事，只是加了 TypeScript 类型。

**动手**：在 `mini_agent.py` 基础上加一个 `Message` dataclass，把 messages 从裸 dict 改成类型化结构

**Day 1 精读收获 — 7 个核心概念**：

1. **Content Blocks** — content 从字符串变为 `(TextContent | ThinkingContent | ToolCall)[]` 数组，tool_call 不再是旁挂字段，而是 content 数组中的一项。这样模型可以交替输出思考、调工具、回答，顺序不丢失。

2. **三消息分离** — 三个独立类型各司其职：UserMessage（只记录输入）、AssistantMessage（运行产物，附带 `usage`/`stopReason`/`model`）、ToolResultMessage（工具结果，`isError` 显式标明成败）。不混用一个通用 Message 来背所有字段。

3. **StopReason** — 5 种终止状态替代"有 tool_calls 就继续"的隐式判断：`"stop"`（正常结束）、`"length"`（输出截断）、`"toolUse"`（调工具）、`"error"`（API 报错）、`"aborted"`（用户中断）。每种对应不同的处理策略。

4. **AssistantMessageEvent 流协议** — 产生端（API 模块）和消费端（Agent Loop）之间的事件格式合同。顺序：`start` → (text/thinking/toolcall 的 start/delta/end) → `done`/`error`。每个事件带 `contentIndex`（指向 content 数组的哪个元素）和 `partial`（截至当前的完整 AssistantMessage 快照），监听者拿到就渲染，不需自己拼状态。

5. **Context 接口** — `systemPrompt + messages + tools` 打包成一个对象，让 `stream(model, context, options)` 三参数走天下。不依赖外部状态，每次调用传新 Context 即可。

6. **Model<TApi> 元信息** — model 从字符串变成完整配置对象（含 `api` 路由、`provider` 厂商、`cost` 成本、`contextWindow` 窗口、`compat` 兼容设置）。`stream()` 根据 `model.api` 路由到对应的 API 模块（openai-responses / anthropic-messages / google-gen-ai 等 28+）。

7. **ProviderId / KnownApi 路由** — api（协议格式）和 provider（认证配置）两个维度正交解耦。同一个 DeepSeek 模型可能 `api: "openai-completions"` + `provider: "deepseek"`。切换厂商只换 Model 对象，stream() 自动匹配。

---

### Day 2 — pi-ai Provider 抽象

**架构图：pi-ai 内部调用流程**

```
User Code (agent-loop.ts)
      │
      │ stream(model, messages, tools...)
      ▼
┌──────────────────────────────────────────────┐
│           stream() 路由                        │
│  根据 model.api 选择 API 实现                   │
│                                              │
│  api/providers 映射:                          │
│  "anthropic-messages"    → anthropic-msgs.ts │
│  "openai-responses"      → openai-responses  │
│  "google-generative-ai"  → google-gen-ai     │
│  "bedrock-converse-stream"→ bedrock-converse │
│  "mistral-conversations" → mistral-conv      │
│  "azure-openai-responses"→ azure-openai      │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│      Provider 特有实现 (e.g. anthropic-msgs)   │
│                                              │
│  1. transformMessages():                     │
│     pi-ai Message → Anthropic API 格式       │
│                                              │
│  2. API 调用 (SDK / HTTP)                    │
│                                              │
│  3. stream 解析:                              │
│     Anthropic stream events                  │
│     → pi-ai AssistantMessageEvent 格式       │
│     (text delta / toolcall delta / done)     │
│                                              │
│  4. error 处理 + retry 逻辑                  │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│      返回 EventStream<AssistantMessageEvent>  │
│                                              │
│  agent-loop.ts 消费事件流:                     │
│  · text delta → 拼接最终文本                  │
│  · toolcall delta → 拼接工具调用参数          │
│  · done → 结束本轮                            │
└──────────────────────────────────────────────┘
```

**读**：
- `packages/ai/src/api/anthropic-messages.ts` 的 `stream()` 函数
- `packages/ai/src/api/openai-responses.ts` 的 `stream()` 函数

**关键理解**：pi-ai 把"不同厂商的 API 差异"封装在 API 层，上层代码不需要关心调的是谁。这就是 `mini_agent.py` 里 `client.chat.completions.create` 这一行的抽象化。

**动手**：在 `mini_agent.py` 里加一个 `LLMProvider` 抽象类，让代码可以切换 OpenAI / Anthropic 两家

---

### Day 3 — pi-ai 流式事件协议

**架构图：AssistantMessageEvent 流式协议**

```
  LLM API Stream                pi-ai EventStream
  ──────────────                ──────────────────
  [chunk 1]                     AssistantMessageEvent {
    type: "message_start"         type: "start"
    message: {...}                messageId, model
  }
                                AssistantMessageEvent {
  [chunk 2]                       type: "text_delta"
    type: "content_block_delta"   delta: "北京今日天"
    delta: {text: "北京今日天"}
                                }
                                AssistantMessageEvent {
  [chunk 3]                       type: "text_delta"
    type: "content_block_delta"   delta: "气晴，22-28°"
    delta: {text: "气晴，22-28°"}
                                }
                                AssistantMessageEvent {
  [chunk 4]                       type: "toolcall_delta"
    type: "content_block_delta"   id: "call_xxx"
    delta: {partial_json:         name: "query_weather"
            '{"city":"北京"}'}     arguments: {city: "北京"}
                                }
                                AssistantMessageEvent {
  [chunk 5]                       type: "done"
    type: "message_stop"          finishReason: "tool_use"
    stop_reason: "tool_use"       usage: {...}
  }

  agent-loop.ts 侧:
  · text delta → 拼成最终文本
  · toolcall delta → 拼成最终工具调用参数
  · start → 初始化
  · done → 本轮 LLM 调用结束，判断下一步
```

**读** `packages/ai/src/types.ts` 中的 `AssistantMessageEvent`：
- start → 会话开始
- text delta → 逐 token 文本
- toolcall delta → 逐 token 工具调用
- done → 结束
- error → 错误

**理解**：现在的 `mini_agent.py` 是一次性拿到完整 response，流式协议让你可以边收边显示。

**动手**：把 `mini_agent.py` 改成流式输出，用 `stream=True` 参数，边收边打印

---

## 第二周：Agent 核心循环（packages/agent）— 最重要

---

### Day 4 — Agent 类型系统

**架构图：Agent 核心类型体系**

```
┌────────────────────────────────────────────────────────────┐
│              pi-agent-core 类型体系 (types.ts)               │
│                                                            │
│  ┌─────────────────────────┐                               │
│  │    AgentTool<T,D>       │                               │
│  │                         │                               │
│  │  name: string           │   例:                          │
│  │  description: string    │   name: "query_weather"       │
│  │  parameters: TypeBox    │   description: "查询天气"      │
│  │  execute(): ToolResult  │   parameters: {city: string}  │
│  │  prepareArguments()     │   execute: → 调 API           │
│  │  executionMode: seq/par │                               │
│  └───────────┬─────────────┘                               │
│              │                                             │
│  ┌───────────┴─────────────────────────────────────────┐   │
│  │              AgentLoopConfig                         │   │
│  │                                                     │   │
│  │  model → 当前模型                                    │   │
│  │  convertToLlm → AgentMessage[] → Message[]           │   │
│  │  transformContext → 上下文转换                        │   │
│  │  getApiKey → API 密钥获取                            │   │
│  │  shouldStopAfterTurn → 终止条件检查                    │   │
│  │  prepareNextTurn → 下一轮准备                         │   │
│  │  beforeToolCall / afterToolCall → 工具钩子             │   │
│  │  toolExecution → "sequential" | "parallel"            │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  AgentEvent (事件类型，供 UI/Extension 订阅)           │   │
│  │                                                     │   │
│  │  agent_start / agent_end                            │   │
│  │  turn_start / turn_end                              │   │
│  │  message_start / message_update / message_end        │   │
│  │  tool_execution_start / _update / _end               │   │
│  └─────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────┘
```

**读** `packages/agent/src/types.ts`：
- `AgentTool<TParameters, TDetails>` — 对应你 tools JSON 的类型化版本，含 `name`、`description`、`parameters`、`execute()`
- `AgentLoopConfig` — 整个 loop 的配置对象：model、转换函数、tool 执行模式（sequential / parallel）、生命周期钩子（beforeToolCall / afterToolCall）
- `AgentEvent` — 事件类型：agent_start/end、turn_start/end、message_start/update/end、tool_execution_start/update/end

**理解**：pi-agent-core 把"裸 JSON tools"变成了带类型的 Tool 定义 + 生命周期钩子。

**动手**：把 `mini_agent.py` 的 tools 从 JSON dict 改成一个 Python 类 `AgentTool`，每个工具一个实例

---

### Day 5 — Agent Loop（核心！）

**核心思想：Agent Loop 的本质就是 6 行**

剥去事件、转换、错误处理，Agent Loop 的真身：

```ts
while (true) {
  const assistant = await callLLM(context.messages);   // 调大模型
  context.messages.push(assistant);                     // 记录回复
  const toolCalls = extractToolCalls(assistant);        // 提取工具调用
  if (toolCalls.length === 0) break;                    // 没有工具调用 → 结束
  const toolResults = await executeToolCalls(toolCalls); // 执行工具
  context.messages.push(...toolResults);                 // 结果回灌
}
```

**层层加码后，748 行多出来的内容**：
- 消息转换（AgentMessage ≠ LLM Message）
- 上下文裁剪（Compaction）
- 工具校验（参数/权限/危险操作拦截）
- 工具执行发事件（UI 展示进度、审计留痕）
- **工具失败也必须回灌上下文**（让模型知道报错，自主决定重试还是换策略）
- 运行中可能有用户插话（Steering 队列）
- 结束后可能追加任务（FollowUp 队列）

**为什么工具结果必须回灌给模型？**

反例：金融客服查贷款审批状态，工具返回 `{status: "rejected", reason: "信用评分不足"}`。

如果直接把原始结果返回用户，模型就失去了思考这些的机会：
- 要不要用温和的方式解释？
- 要不要调风控记录查具体原因？
- 要不要提醒用户补材料？
- 是不是涉及合规不能直说？

正确链路：**工具结果 → toolResult message → 回到上下文 → LLM 继续推理 → 用户可读回答**

**两层循环设计**

Pi 的 Agent Loop 不是简单一层 `while(true)`：

```
外层循环（FollowUp 消息）
  │  处理 "Agent 本来要结束了，外部又追加了新任务"
  │  例：用户连发两条消息，第一条 assistant 已结束
  │      第二条作为 followUp 重开循环
  ▼
内层循环（工具调用 + Steering 打断）
  │  处理 "模型调了工具，执行完结果回灌，继续推理"
  │  也处理 "用户中途插话 → 停掉当前工具，标记 Skipped"
  ▼
真正停止 → emit agent_end
```

为什么不能混？"中途插话（打断）"和"结束后追加任务"是两种完全不同的控制流。混在一起，你的 Agent 就会在"用户突然改主意"和"任务搞定后继续追加需求"两个场景里频繁逻辑混乱。

**currentContext.messages vs newMessages**

| 变量 | 作用 |
|------|------|
| `currentContext.messages` | 当前 run 的**完整上下文**，模型每次推理都要看 |
| `newMessages` | 本次运行**增量**的消息，用于触发事件、更新状态、返回结果 |

类比：`currentContext.messages` ≈ 当前事务的完整业务上下文，`newMessages` ≈ 本次请求的变更日志。两个职责，不要混一起。

**架构图：agentLoop() 详细执行流程**

```
┌──────────────────────────────────────────────────────────────────┐
│                    agentLoop() / agentLoopContinue()              │
│                                                                   │
│  输入: prompts (AgentMessage[])                                   │
│        context (已有消息上下文)                                    │
│        config (AgentLoopConfig)                                   │
│        signal (AbortSignal)                                       │
│        streamFn (LLM 流式调用函数)                                 │
│                                                                   │
│  输出: EventStream<AgentEvent, AgentMessage[]>                    │
└──────────────────────────────┬───────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│              runLoop() — 核心 while 循环                          │
│                                                                   │
│  ┌──────────┐                                                     │
│  │ 1. 检查  │  steering 队列 → 有则注入 steering messages        │
│  │  前置条件 │  follow-up 队列 → 有则注入 follow-up messages      │
│  └────┬─────┘                                                     │
│       ▼                                                           │
│  ┌──────────┐                                                     │
│  │ 2. 调用  │  streamAssistantResponse()                          │
│  │  LLM     │  · AgentMessage[] → Message[] (convertToLlm)       │
│  │          │  · 调 streamFn → 获得事件流                         │
│  │          │  · 拼接 text + toolcall → 构造 AssistantMessage    │
│  └────┬─────┘                                                     │
│       ▼                                                           │
│  ┌──────────┐                                                     │
│  │ 3. 判断  │  stop_reason                                        │
│  │  下一步  │                                                     │
│  │          │  end_turn  ──────────────→  返回最终消息 ✅          │
│  │          │  tool_use  ───┐                                     │
│  └──────────┘               │                                     │
│                            ▼                                      │
│  ┌──────────────────────────────────────────────────────────┐     │
│  │  4. executeToolCalls()                                    │     │
│  │                                                           │     │
│  │  sequential 模式:                                         │     │
│  │  for each tool:                                           │     │
│  │    prepareArguments → beforeToolCall hook                 │     │
│  │    → execute → afterToolCall hook → 结果入队              │     │
│  │                                                           │     │
│  │  parallel 模式:                                            │     │
│  │  Promise.all(tools.map(execute)) → 结果入队                │     │
│  │                                                           │     │
│  │  每个工具执行时发出:                                       │     │
│  │  AgentEvent.tool_execution_start                          │     │
│  │  AgentEvent.tool_execution_update (流式)                   │     │
│  │  AgentEvent.tool_execution_end                            │     │
│  └──────────────────────────────┬────────────────────────────┘     │
│                                 ▼                                  │
│                     回到步骤 2（继续调 LLM，传入 tool results）     │
└──────────────────────────────────────────────────────────────────┘
```

**对照** `mini_agent.py` 的 while True：
```
mini_agent.py             agent-loop.ts
────────────────────      ──────────────────────
while True:               runLoop()
client.chat...create()    streamAssistantResponse()
msg.tool_calls            executeToolCalls()
for tool in ...           for tool in ...
messages.append(tool)     ToolResult → 回填
else: break               最终回答 → 事件发射
```

**动手**：用伪代码在纸上画出 `agentLoop()` 的执行流程图

---

### Day 6 — Agent 类

**架构图：Agent 类的状态和方法**

```
┌──────────────────────────────────────────────────────────────────┐
│                     Agent 实例                                     │
│                                                                   │
│  状态:                                                            │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  state.messages: AgentMessage[]  ← 当前完整对话              │  │
│  │  state.tools: AgentTool[]        ← 可用工具列表               │  │
│  │  state.model: String             ← 当前模型                   │  │
│  │  state.thinkingLevel             ← thinking 等级              │  │
│  │  listeners: Set<EventHandler>    ← 事件订阅者                 │  │
│  │  pendingMessages: PendingMessageQueue                        │  │
│  │    · steering messages (高优先级注入)                          │  │
│  │    · follow-up messages (低优先级注入)                         │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  方法:                                                            │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  prompt(text | AgentMessage[]): EventStream                 │  │
│  │    → 设置初始消息 → 调 agentLoop()                           │  │
│  │                                                             │  │
│  │  continue(): EventStream                                    │  │
│  │    → 从 state.messages 继续 → 调 agentLoopContinue()         │  │
│  │                                                             │  │
│  │  steer(msgs): void                                          │  │
│  │    → 注入高优先级消息（下一轮 LLM 调用前插入）                  │  │
│  │                                                             │  │
│  │  followUp(msgs): void                                       │  │
│  │    → 注入低优先级消息                                         │  │
│  │                                                             │  │
│  │  subscribe(listener): unsubscribe                            │  │
│  │    → 注册事件监听器                                          │  │
│  │                                                             │  │
│  │  abort() / reset() / waitForIdle()                          │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘

      外部使用者（coding-agent / test / custom app）：
      Agent 实例.on("turn_start", ...)
      Agent 实例.on("tool_execution_start", ...)
      Agent 实例.prompt("Hello")
      Agent 实例.continue()
```

**读** `packages/agent/src/agent.ts`：
- `Agent.prompt()` — 启动新对话，对应 `messages.append(user_input)` + while True 第一轮
- `Agent.continue()` — 继续已有对话，对应 while True 后续轮次
- `Agent.subscribe()` — 事件订阅，对应你的 `print()`
- `Agent.abort()` / `Agent.waitForIdle()` / `Agent.reset()` — 生命周期控制

**理解**：`Agent` 类 = `agentLoop()` + 状态管理 + 事件订阅。你的 while True 循环被拆分成了 `prompt()` 和 `continue()` 两个方法。

**优秀设计：AgentLoop 为什么不直接改 Agent 状态？**

AgentLoop 不直接摸外层 Agent 的 state，它通过**事件**通知外层：

```
AgentLoop 负责执行 → 发事件 → Agent 负责消费事件 + 更新状态
```

这就是经典的**事件驱动**设计，带来的好处：
- 执行流与状态管理解耦，职责单一，修改代码不出副作用
- UI 可以直接订阅事件来渲染（不依赖 Agent 内部实现）
- 扩展日志与审计系统变得极其省心
- 未来接 CLI / SDK / RPC 不用改循环核心

反之，如果在 AgentLoop 内部直接改外部状态，执行循环会越来越重，每接入一个新客户端都得重构循环核心。

**动手**：在 `mini_agent.py` 里提取一个 `Agent` 类，把 while 循环封进去

---

### Day 7 — AgentHarness（串联所有组件）

**架构图：AgentHarness 生命周期协调器**

```
┌──────────────────────────────────────────────────────────────────┐
│                    AgentHarness                                    │
│                                                                   │
│  职责: 连接 Agent + Session + ExecutionEnv + 事件系统             │
│                                                                   │
│  构造时接收:                                                       │
│  · Agent 实例                                                     │
│  · SessionRepo (持久化存储)                                        │
│  · ExecutionEnv (FS / Shell 抽象)                                  │
│  · CompactionConfig                                               │
│  · Hooks 配置                                                     │
│                                                                   │
│  运行时流程:                                                       │
│                                                                   │
│  用户输入                                                          │
│      │                                                             │
│      ▼                                                             │
│  ┌─────────────────────────────────────────────────────────┐      │
│  │  AgentHarness.prompt() / continue()                     │      │
│  │                                                         │      │
│  │  1. 构建 system prompt (含工具描述 + skills + 项目规则)   │      │
│  │  2. 设置 steering messages（如果有）                     │      │
│  │  3. 调 Agent.prompt()                                    │      │
│  │  4. 订阅 agent 事件 → 转发到 harness 事件系统             │      │
│  │  5. 事件触发自动持久化 session                            │      │
│  │  6. 检查上下文水位 → 触发 compaction                      │      │
│  │  7. 返回最终结果                                         │      │
│  └─────────────────────────────────────────────────────────┘      │
│                                                                   │
│  Compaction 触发时机:                    Session 操作:             │
│  · 消息数 > threshold                   · save() → 写 JSONL       │
│  · 预估 token 接近模型限制               · load() → 恢复历史对话   │
│  · 用户手动 /compact                    · fork() → 创建分支       │
│                                         · switch() / tree() → 导航│
└──────────────────────────────────────────────────────────────────┘
```

**读** `packages/agent/src/harness/agent-harness.ts` 前 300 行：
- 构造函数 → 理解 `AgentHarness` 接收哪些依赖
- `run()` / `prompt()` → 理解它怎么把 `Agent` + `Session` + `ExecutionEnv` 串起来
- `compact()` → 理解上下文压缩的触发时机

**理解补全**：Harness 的功能 = `mini_agent.py` 的 while True 外层又包了一层：
- Session 管理（持久化、分支、恢复）
- Compaction（上下文窗口控制）
- Skills 加载（SKILL.md 解析）
- 事件发射到 UI

**动手**：用一周学到的，把 `mini_agent.py` 重构为三层：
```
LLMProvider → Agent → AgentHarness（含 Session 持久化 + Compaction）
```

---

## 第三周：工具系统 + Compaction + System Prompt

---

### Day 8 — 工具系统

**架构图：pi-coding-agent 7 个内置工具**

```
┌──────────────────────────────────────────────────────────────────┐
│                   工具注册与执行                                     │
│                                                                   │
│  内置工具 (packages/coding-agent/src/tools/):                      │
│                                                                   │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌──────────┐   │
│  │  bash   │ │  read   │ │  edit   │ │  write  │ │  grep    │   │
│  ├─────────┤ ├─────────┤ ├─────────┤ ├─────────┤ ├──────────┤   │
│  │执行shell│ │读文件   │ │编辑文件  │ │写文件   │ │内容搜索  │   │
│  │spawn钩子│ │编码检测 │ │diff计算  │ │路径校验 │ │rg 封装   │   │
│  │输出截断 │ │行数限制 │ │patch生成 │ │         │ │          │   │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └──────────┘   │
│  ┌─────────┐ ┌───────┐                                           │
│  │  find   │ │  ls   │                                           │
│  ├─────────┤ ├───────┤                                           │
│  │文件查找 │ │目录列 │                                           │
│  │fd/find  │ │表     │                                           │
│  └─────────┘ └───────┘                                           │
│                                                                   │
│  工具 = name + description + parameters(TypeBox) + execute()      │
│                                                                   │
│  每个工具还有:                                                     │
│  · executionMode: "sequential" | "parallel"                       │
│  · prepareArguments() → 参数预处理                                 │
│  · beforeToolCall / afterToolCall hook                            │
│                                                                   │
│  Extension 注册的工具和内置工具走同一个 AgentTool 接口              │
└──────────────────────────────────────────────────────────────────┘
```

**读** `packages/coding-agent/src/tools/` 下各工具的前 50 行：
- `bash.ts` — 工具定义 + execute 函数
- `read.ts` — 工具定义 + execute 函数
- `edit.ts` — 工具定义 + execute 函数
- `write.ts` — 工具定义 + execute 函数

**理解**：每个工具 = 名字 + 描述 + 参数 schema + execute 逻辑，和 `mini_agent.py` 的 `execute_function()` 一一对应。

**动手**：在 `mini_agent.py` 的 `execute_function` 基础上，给每个工具加上重试逻辑和错误处理

---

### Day 9 — Compaction（上下文管理）

**架构图：Compaction 流程**

```
  messages 增长:
  ┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐
  │sys │user│asst│tool│user│asst│tool│user│asst│tool│user│... │  ← 越来越多
  └────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┘
  接近 token 上限 ──→ 触发 compact()

  compact() 做的事:
  1. 选择早期消息（前 N 条或多轮对话）
  2. 调 LLM 把它们总结成一段摘要：
     "用户询问了北京天气，助手返回了晴22-28°C。
      用户设置了明天下午3点的开会提醒。"
  3. 用摘要替换掉原始消息

  结果:
  ┌────┬────────────────────────────┬────┬────┬────┬────┐
  │sys │[compaction summary]        │user│asst│tool│user│...  ← 变短了
  └────┴────────────────────────────┴────┴────┴────┴────┘

  Pi Agent 的 compaction 策略:
  · 自动触发：消息数 > threshold 或预估 token 接近限制
  · 手动触发：用户输入 /compact
  · 分支摘要：切换到旧分支时自动摘要
```

**读** `packages/agent/src/harness/compaction/compaction.ts`：
- `compact()` 函数签名 → 输入 messages，输出压缩后的 messages
- 策略：把早期消息总结成一段摘要，替换掉原文

**理解**：这就是"messages 一直加怎么办"的答案。Pi Agent 在上下文接近模型限制时自动触发 compaction。

**动手**：给 `mini_agent.py` 加一个简单的 compaction：当消息超过 20 条时，把前 10 条用 LLM 总结成一段摘要，替换掉原文

---

### Day 10 — System Prompt 组装

**架构图：System Prompt 组装过程**

```
  buildSystemPrompt() 的输出:
  ┌──────────────────────────────────────────────────────────────┐
  │  System Message                                                │
  │                                                               │
  │  [角色定义]                                                    │
  │  你是 Pi，一个 AI 编程助手...                                   │
  │                                                               │
  │  [工具描述]  ← 从 tools 列表自动生成                            │
  │  ## Available Tools                                           │
  │  - bash: 执行 shell 命令，参数: command(string)               │
  │  - read: 读文件，参数: file_path(string)                       │
  │  - edit: 编辑文件，参数: file_path(string), old(string)...    │
  │                                                               │
  │  [技能]  ← 从 .pi/skills/ 加载 (SKILL.md 解析)                │
  │  ## Skills                                                    │
  │  - react-pattern: 遵循 思考→行动→观察 循环...                  │
  │                                                               │
  │  [项目上下文]  ← 从 AGENTS.md / CLAUDE.md 加载                 │
  │  ## Project Context                                           │
  │  本项目是一个 TypeScript monorepo...                           │
  │                                                               │
  │  [规则和约束]                                                  │
  │  - 不要删除未跟踪的文件                                        │
  │  - 运行测试前先检查 lint                                       │
  │                                                               │
  │  [输出格式]                                                    │
  │  - 用中文回答                                                 │
  │  - 给出代码示例时标明文件路径                                   │
  └──────────────────────────────────────────────────────────────┘

  分区标注的好处:
  · 模型能区分"规则"和"证据"和"技能"
  · 不同来源的内容不会互相污染
  · 方便调试（知道哪部分 prompt 导致了什么问题）
```

**读** `packages/coding-agent/src/core/system-prompt.ts`：
- 系统提示怎么组装：工具描述 + 技能 + 项目上下文 + 规则 + 格式要求
- 不同部分怎么分区、怎么排序

**理解**：`mini_agent.py` 里 `system` role 消息的那一行，在这里变成了一个完整的组装工厂。

**动手**：在 `mini_agent.py` 里把 system prompt 拆成独立的 `build_system_prompt()` 函数，根据不同场景拼接不同内容（无工具版 / 有工具版 / 带上下文版）

---

### Day 11 — Session 管理

**架构图：Session 树结构**

```
  Session 树（一个项目一个根）:
  ┌──────────────────────────────────────────────────────────────┐
  │  ~/.pi/sessions/<project-id>/                                │
  │                                                              │
  │  session_001/  ← 初始对话                                    │
  │  ├── entries/                                                │
  │  │   ├── 0001.jsonl  ← user: "调研一下 React 19"            │
  │  │   ├── 0002.jsonl  ← asst: <思考><调工具>...               │
  │  │   └── ...                                                 │
  │  ├── metadata.json  ← 模型、token 数、创建时间               │
  │  │                                                           │
  │  ├─ fork at turn 3 ── session_002/  ← "换个方向研究"         │
  │  │   ├── entries/                                            │
  │  │   │   ├── 0001.jsonl  (继承自 session_001 前 3 轮)        │
  │  │   │   ├── 0002.jsonl  ← user: "换个方向"                  │
  │  │   │   └── ...                                             │
  │  │   └── metadata.json                                       │
  │  │                                                           │
  │  └─ fork at turn 7 ── session_003/  ← "写代码"              │
  │      ├── entries/                                            │
  │      │   ├── 0001-0007.jsonl  (继承)                         │
  │      │   ├── 0008.jsonl  ← user: "开始写"                   │
  │      │   └── ...                                             │
  │      └── metadata.json                                       │
  │                                                              │
  │  持久化方式: JSONL（每行一个 JSON，追加写）或 内存            │
  │  每个 entry 保存: role + content + tool_calls + timestamp    │
  └──────────────────────────────────────────────────────────────┘

  /fork → 创建新分支（继承历史到当前轮，之后互不影响）
  /tree → 查看所有分支
  /switch → 切换到其他分支
  /compact → 压缩当前分支历史
```

**读** `packages/agent/src/harness/session/session.ts`：
- `Session` 类型 → messages + metadata + tree 结构
- 分支（fork）→ 在 session 树上创建新分支，互不干扰

**理解**：Session = messages + metadata 的持久化容器。目前的 `mini_agent.py` 退出后对话就丢了，Session 让它可以恢复。

**动手**：给 `mini_agent.py` 加 JSON 文件持久化：退出时保存 messages，下次启动时检查有无历史文件可恢复

---

## 第四周：Extension 系统 + 实战整合

---

### Day 12 — Extension 系统

**架构图：Extension 的加载和执行流程**

```
┌──────────────────────────────────────────────────────────────────┐
│                    Extension 系统                                   │
│                                                                   │
│  加载流程:                                                         │
│                                                                   │
│  CLI 启动                                                          │
│    │ -e ext1.ts -e ext2.ts                                        │
│    ▼                                                              │
│  ┌──────────────────────────────────────────────────────────┐     │
│  │  ExtensionLoader (loader.ts)                              │     │
│  │  · 用 jiti（Node）/ virtual modules（Bun）加载 TS 文件     │     │
│  │  · 调用默认导出函数，传入 ExtensionAPI                     │     │
│  │  · 收集注册的工具/命令/快捷键                              │     │
│  └──────────────────────────┬───────────────────────────────┘     │
│                             ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐     │
│  │  ExtensionRunner (runner.ts)                              │     │
│  │  · 管理 extension 生命周期                                │     │
│  │  · 事件分发 → 通知所有订阅该事件的 extension                │     │
│  │  · 工具注册 → 转成 AgentTool 格式，注入 agent              │     │
│  │  · 命令注册 → 注入 slash command 列表                      │     │
│  │  · Provider 注册 → 注册到 model registry                  │     │
│  └──────────────────────────────────────────────────────────┘     │
│                                                                   │
│  ExtensionAPI 可做的事情:                                          │
│  · on(event, handler)  → 订阅 20+ 生命周期事件                    │
│  · registerTool(def)    → 注册自定义工具                           │
│  · registerCommand(cmd) → 注册 /slash 命令                        │
│  · registerShortcut(key) → 注册快捷键                             │
│  · registerProvider(p)  → 注册模型提供商                           │
│  · sendMessage(text)    → 向会话发消息                             │
│  · setFooter(data)      → 自定义底部状态栏                         │
│  · setWidget(component) → 挂载 UI 组件                            │
│  · exec(cmd)            → 执行 bash 命令                          │
│                                                                   │
│  可订阅的事件（20+）：                                              │
│  session_start / session_end / session_before_compact             │
│  turn_start / turn_end                                            │
│  message_start / message_update / message_end                     │
│  tool_call / tool_result                                          │
│  input / user_bash                                                │
│  model_select / context                                            │
│  before_provider_request / before_agent_start                     │
│  project_trust / resources_discover                               │
└──────────────────────────────────────────────────────────────────┘
```

**读** `packages/coding-agent/src/core/extensions/types.ts`：
- `ExtensionAPI` 接口 — `on()` 订阅事件、`registerTool()` 注册工具、`registerCommand()` 注册命令
- `ExtensionContext` — UI、mode、cwd、abort 等上下文

**读** `packages/coding-agent/src/core/extensions/runner.ts`：
- Extension 怎么被加载、事件怎么分发、工具怎么注册

**理解**：Extension = 插件，可以在 agent 生命周期事件里注入自定义行为。`pi -e extensions/minimal.ts` 就是加载一个 extension。

**动手**：写一个简单 extension（概念验证，用 Python 模拟）：在 AI 每次调用工具前打印一条日志

---

### Day 13 — 实操跑 Pi Agent

**安装**：
```bash
npm install -g @earendil-works/pi-coding-agent
```

**跑 session**：
```bash
pi "hello world"
```

**尝试命令**：
- `/compact` — 手动触发压缩
- `/fork` — 创建分支
- `/tree` — 查看 session 树
- `/model` — 切换模型

**写最小 extension**（TypeScript）：
```typescript
// my-ext.ts
export default (pi) => {
  pi.registerCommand("hello", "Says hello", (_ctx) => {
    pi.sendMessage("Hello from extension!");
  });
};
```

跑：`pi -e my-ext.ts`，然后输入 `/hello`

---

### Day 14 — 回读 agent-loop.ts 对照

**架构图：一次用户输入的全链路数据流**

```
用户输入 "北京天气怎么样"
      │
      ▼
┌──────────────────────────────────────────────────┐
│  pi-coding-agent                                   │
│  ┌──────────────────────────────────────────────┐ │
│  │  interactive-mode / print-mode               │ │
│  │  → 收到输入                                   │ │
│  │  → 构建 AgentMessage (role: user)            │ │
│  └──────────────────┬───────────────────────────┘ │
└─────────────────────┼─────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────┐
│  pi-agent-core                                    │
│  ┌──────────────────────────────────────────────┐ │
│  │  AgentHarness.prompt(msgs)                   │ │
│  │  → buildSystemPrompt()                       │ │
│  │  → Agent.prompt()                            │ │
│  └──────────────────┬───────────────────────────┘ │
│  ┌──────────────────────────────────────────────┐ │
│  │  Agent.prompt()                               │ │
│  │  → state.messages = system + user             │ │
│  │  → agentLoop()                                │ │
│  └──────────────────┬───────────────────────────┘ │
│  ┌──────────────────────────────────────────────┐ │
│  │  agentLoop() → runLoop()                     │ │
│  │                                              │ │
│  │  ┌─ 1. streamAssistantResponse()            │ │
│  │  │   → 调 pi-ai.stream()                    │ │
│  │  │   ← 返回: tool_use(query_weather)        │ │
│  │  │                                          │ │
│  │  └─ 2. executeToolCalls()                   │ │
│  │      → 执行 query_weather("北京")            │ │
│  │      → 结果: "晴, 22°C"                     │ │
│  │      → tool result 回填                      │ │
│  │                                              │ │
│  │  ┌─ 3. streamAssistantResponse() (第二次)   │ │
│  │  │   → messages += tool_result              │ │
│  │  │   → 调 pi-ai.stream()                    │ │
│  │  │   ← end_turn: "北京今日晴,22-28°C"      │ │
│  │  └─ 4. 返回最终消息 ✅                       │ │
│  └──────────────────────────────────────────────┘ │
└─────────────────────┼─────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────┐
│  pi-coding-agent                                   │
│  ┌──────────────────────────────────────────────┐ │
│  │  收到 AgentEvent.turn_end                    │ │
│  │  → 显示 "北京今日晴,22-28°C"                 │ │
│  │  → 自动持久化 session                         │ │
│  │  → 更新 footer/status                        │ │
│  └──────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

**重读** `packages/agent/src/agent-loop.ts`，这次带着实操经验：

按一次回车 -> 发生了什么？
1. `prompt()` → messages 入队
2. `runLoop()` → 进入 while 循环
3. `streamAssistantResponse()` → 调 LLM API
4. 检查 stop_reason
5. 如果是 tool_use → `executeToolCalls()` → 结果回填 → 回到步骤 3
6. 如果是 end_turn → 发出最终回答 → 退出循环

**验证**：你之前学的"20 行核心循环"和 Pi Agent 的 748 行 `agent-loop.ts`，本质是相同的。20 行是骨架，748 行是骨架 + 肌肉 + 血管。

---

### Day 15 — 产出总结

**架构图：4 层整体架构（依赖方向）**

```
┌────────────────────────────────────────────────────────────────────┐
│                     pi-coding-agent                                │
│           @earendil-works/pi-coding-agent                          │
│                                                                    │
│  modes/          core/                cli/                         │
│  interactive/    agent-session       args.ts                       │
│  rpc/            tools/              startup-ui.ts                 │
│  print/          extensions/                                       │
│                  system-prompt                                     │
│                  skills/slash-commands                             │
└──────────────────────┬─────────────────────────────────────────────┘
                       │  import / runtime 依赖
                       │  pi-coding-agent → pi-agent-core
                       ▼
┌────────────────────────────────────────────────────────────────────┐
│                      pi-agent-core                                 │
│           @earendil-works/pi-agent-core                            │
│                                                                    │
│  agent.ts        harness/                                          │
│  · prompt()      agent-harness.ts                                  │
│  · continue()    session/ (持久化)                                 │
│  · steer()       compaction/ (上下文压缩)                          │
│                   skills/ (技能加载)                                │
│  agent-loop.ts    env/ (执行环境抽象)                                │
│  · runLoop()                                                       │
│  · executeToolCalls()                                              │
│  ← 20 行 while 循环的生产版 (748行)                                 │
└──────────────────────┬─────────────────────────────────────────────┘
                       │  import / runtime 依赖
                       │  pi-agent-core → pi-ai
                       ▼
┌────────────────────────────────────────────────────────────────────┐
│                          pi-ai                                     │
│                @earendil-works/pi-ai                               │
│                                                                    │
│  types.ts     api/ (28 files)     providers/ (75 files)            │
│  Message      anthropic-msgs      anthropic.ts / openai.ts         │
│  Model        openai-responses    deepseek.ts / google.ts          │
│  StreamEvent  google-gen-ai       openrouter.ts / groq.ts          │
│  auth/        bedrock-converse    fireworks.ts / together.ts       │
│               mistral-conv        30+ 厂商                         │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│                          pi-tui                                     │
│                @earendil-works/pi-tui                               │
│                                                                    │
│  tui.ts (差分渲染) | terminal.ts | components/ | editor-component │
│                                                                    │
│  ↑ 仅 pi-coding-agent 引用（UI 模式需要），pi-ai 不依赖 pi-tui       │
└────────────────────────────────────────────────────────────────────┘
```

**重点理解**：
- 图中 `▼` 箭头方向 = import 方向（上层引用下层）
- `pi-coding-agent` **import** `pi-agent-core` 和 `pi-tui`
- `pi-agent-core` **import** `pi-ai`
- `pi-tui` 和 `pi-ai` **同级**，互不依赖
- 你写的 `mini_agent.py` 只到 pi-agent-core 这层（agent-loop.ts 对应你的 while True）
- pi-coding-agent 是**应用层**（CLI / TUI），和核心逻辑无关

**图例**：
```
┌──────────┐  模块         ▼   import 方向（谁引用谁）
│ 内容     │
└──────────┘
```

**标记**（对照上面每张图逐一标注）：
- ✅ 已看懂（能解释给别人听）
- 🔶 大致理解（能说出来干什么用，但细节不清楚）
- ❌ 没看懂（需要再花时间）

**决定**：对于 🔶 和 ❌ 的部分，判断是暂时跳过还是深入读。

---

## Pi Agent 优秀设计思想总结

读完 15 天，你应该能从源码里提取出以下**可被借鉴到任何 Agent 项目**的东西。

### 一、架构层次

**1. 三层分离，各安其分**

| 层 | 角色 | 特点 | 可以独立测试 |
|----|------|------|-------------|
| `agentLoop` | 纯流式生成器 | **无状态**，在 (messages, tools, model) 上循环 | ✅ 给入参就能跑 |
| `Agent` | 有状态调用门面 | 含 steer/followUp 队列，支持中途打断、多订阅者 | ✅ Mock 事件即可 |
| `AgentHarness` | Runtime 控制层 | 持久化、Compaction、Skill 加载、Hook、Session Tree | ✅ 替换底层即可 |

**为什么这样做**：AgentLoop 无条件、无分支、不依赖外部，是最干净的执行内核。所有工程复杂度（持久化、压缩、权限）都放在 Harness 层。这让内核永远可测试、可替换、可复用。

**2. 事件驱动解耦**

AgentLoop 不直接修改 Agent 状态。

```
AgentLoop 执行 → 发事件 → Agent 消费事件 + 更新状态
                        → UI 渲染
                        → 审计日志
                        → Session 持久化
```

不同消费者各自订阅自己关心的事件，谁也不干扰谁。

---

### 二、执行模型

**3. Agent = LLM + Tools + Message Context + Runtime Loop + Event Stream**

不是 LLM + Tools。Tools 只是零件，真正的 Agent 还包含：消息上下文管理、运行循环、事件流系统。缺一样都不是 Agent。

**4. 双层循环**

- **内层**：处理工具调用 + 用户中途打断（Steering）
- **外层**：处理 FollowUp 消息（Agent 结束后追加的新任务）

两种中断走两个通道，不混用。混用是 90% Agent 框架逻辑混乱的根源。

**5. 工具结果必须回灌**

工具返回的原始内容 → toolResult message → 回到上下文 → LLM 重新消化 → 用户可读回答。

不是直接把工具结果丢给用户。少了这个闭环，Agent 就只是"缝合了 API 返回值的聊天机器人"。

**6. 工具失败也必须回灌**

不是 try-catch 就完了。模型只有看到 `{error: "timeout", retryable: true}` 才知道重试还是换策略。这是 Agent 自主决策的基础设施。

---

### 三、设计品位

**7. 工具极致收敛**

Pi 只有 4 个内置工具（bash / read / edit / write），不到 7000 行 TypeScript，系统提示词 1500 token。

选择的工具越少，LLM 的正确选取率和调用质量反而越高。

**8. 执行过程全透明**

Agent 写了什么代码、执行了什么命令、工具调了什么参数、返回了什么东西——终端里全看得见。不做黑盒。

**9. 职责高度单一**

执行内核不管状态，状态不管持久化，持久化不管 UI。每个模块只做一件事，做好一件事。

**10. currentContext.messages 和 newMessages 分离**

| | currentContext.messages | newMessages |
|---|---|---|
| 范围 | 完整上下文 | 本次增量 |
| 谁看 | 模型推理 | 事件/状态/返回 |
| 类比 | 事务里的全部业务上下文 | 本次请求的变更日志 |

---

### 四、三个常见误区（带走的判断力）

**误区 1：Agent = LLM + Tools**

不够。正确公式：Agent = LLM + Tools + Message Context + Runtime Loop + Event Stream。

**误区 2：把工具结果直接塞回给用户**

Demo 可以偷懒，生产系统绝对不行。工具返回是给模型的，不是给用户的。

**误区 3：AgentLoop 应该包办一切**

千万不要。AgentLoop 只负责模型与工具的闭环交互。Session、权限、审计、压缩、UI 事件，全部交给 Harness 层。让内核负重前行，项目最后无法重构、无法测试、无法复用。

---

### 五、你的 mini_agent.py 借鉴清单

按这个优先级往你的 mini_agent.py 里加：

1. **工具结果回灌**（现在已做 ✅）
2. **工具失败也回灌**（Day 8 做了重试 ✅，再加：把错误信息格式化为 `{error: xxx, retryable: bool}` 再回灌）
3. **双层循环**（内层处理 tool calling + 中止，外层处理 followUp 追加任务）
4. **事件驱动**（AgentLoop 发事件，Agent 消费事件更新状态，不要在循环里直接改 messages）
5. **currentContext vs newMessages 分离**（模型看完整上下文，事件系统只看增量）
6. **三层架构**（agentLoop 无状态 → Agent 有状态 → Harness 管理 Session/Compaction）
7. **工具收敛**（能不注册的工具先不注册，工具越少模型越稳）

---

## 附录

### mini_agent.py 与 Pi Agent 架构对应关系

| mini_agent.py 组件 | 对应 Pi Agent 位置 | 说明 |
|------|------|------|
| `client.chat.completions.create()` | `packages/ai/src/api/openai-responses.ts` | LLM API 调用，pi-ai 支持 30+ 厂商 |
| `tools = [...]` (JSON dict) | `packages/agent/src/types.ts` → `AgentTool` | 类型化的工具定义 + 生命周期钩子 |
| `messages = [...]` (list of dict) | `packages/ai/src/types.ts` → `Message` | 类型化的消息结构 |
| `while True` 循环 | `packages/agent/src/agent-loop.ts` → `runLoop()` | 核心循环，mini 版 20 行，Pi 版 748 行 |
| `execute_function()` | `packages/agent/src/agent-loop.ts` → `executeToolCalls()` | 工具执行，Pi 版支持并行 + 钩子 |
| `if msg.tool_calls:` | `stop_reason == "tool_use"` | 判断 LLM 是否想调工具 |
| `messages.append({"role": "tool"})` | `ToolResultMessage` 回填 | 工具结果回传 |
| `if msg.content:` | `stop_reason == "end_turn"` | LLM 给出最终回答 |
| 无（内存仅当前会话） | `packages/agent/src/harness/session/session.ts` | Session 持久化 |
| 无（消息无限增长） | `packages/agent/src/harness/compaction/compaction.ts` | 上下文压缩 |
| `{"role": "system", "content": "..."}` | `packages/coding-agent/src/core/system-prompt.ts` | 系统提示组装工厂 |
| 无 | `packages/coding-agent/src/core/extensions/` | Extension 插件系统 |
| 无 | `packages/coding-agent/src/core/tools/bash.ts` | 7 个内置工程工具 |

### 关键文件速查表

| 文件 | 行数 | 优先级 | 说明 |
|------|------|--------|------|
| `packages/ai/src/types.ts` | ~500 | ⭐⭐⭐ | 所有类型的源头，必须先读 |
| `packages/ai/src/api/anthropic-messages.ts` | ~300 | ⭐⭐ | 看一个具体 API 实现 |
| `packages/ai/src/api/openai-responses.ts` | ~300 | ⭐⭐ | 对比 OpenAI 实现 |
| `packages/agent/src/types.ts` | ~400 | ⭐⭐⭐ | Agent 类型系统 |
| `packages/agent/src/agent-loop.ts` | 748 | ⭐⭐⭐ | 核心循环，最重要的文件 |
| `packages/agent/src/agent.ts` | ~300 | ⭐⭐⭐ | Agent 类包装 |
| `packages/agent/src/harness/agent-harness.ts` | 1029 | ⭐⭐ | 完整 Harness |
| `packages/agent/src/harness/compaction/compaction.ts` | ~200 | ⭐⭐ | 上下文压缩 |
| `packages/agent/src/harness/session/session.ts` | ~200 | ⭐⭐ | Session 持久化 |
| `packages/coding-agent/src/tools/bash.ts` | ~150 | ⭐⭐ | 工具实现示例 |
| `packages/coding-agent/src/core/system-prompt.ts` | ~200 | ⭐⭐ | System prompt 组装 |
| `packages/coding-agent/src/core/extensions/types.ts` | 1476+ | ⭐ | Extension 类型（量大，扫读接口签名即可） |
| `packages/coding-agent/src/core/extensions/runner.ts` | 1135 | ⭐ | Extension 运行时（量大，扫读流程） |

### mini_agent.py 演进路线

```
Day 1:  types.py — Message dataclass
Day 2:  provider.py — LLMProvider 抽象类（OpenAI / Anthropic）
Day 3:  流式输出 — stream=True 逐 token 打印
Day 4:  agent_tool.py — AgentTool 类，每个工具一个实例
Day 6:  agent.py — Agent 类，封装 while 循环为 prompt() / continue()
Day 7:  harness.py — AgentHarness 类，串联 Provider + Agent + Session
Day 9:  compaction.py — 消息数 > N 时自动压缩
Day 10: system_prompt.py — 组装系统提示
Day 11: session.py — JSON 文件持久化
Day 12: extension.py — 注册表 + 3 个固定钩子点（简化版 Extension 系统）
Day 13: mini_agent.py 全链路调试 — 从 agent.prompt() 到 LLM 调用完整走通
Day 14: agent-loop.ts 回读 — 5 个内核设计模式
Day 15: mini_agent.py 最终版 — 完整的三层架构可用
```

---

## 15 天精读最终总结

### 4 条通用设计原则

**原则 1：内核做减法，外层做加法**

核心循环（agent-loop.ts 748 行）不知道持久化、API key、UI 的存在。所有外部依赖通过 `AgentLoopConfig` 回调注入。如果内核里出现了 `saveToFile` / `emitToUI` / `getApiKey`，就是分层失误。

Java 对应：Spring 的 `JdbcTemplate.query(sql, RowMapper)`——骨架固定，业务逻辑通过 `RowMapper` 函数注入，不改框架。

**原则 2：给钩子，别给抽象基类**

十几个可选的 config 回调（`convertToLlm` / `transformContext` / `prepareNextTurn` / `getSteeringMessages` / `shouldStopAfterTurn`...）让调用者组合行为。不需要继承框架类。

模板方法 vs 钩子注入：
- 模板方法：继承 + 重写 protected 方法（Java 生态主流）
- 钩子注入：构造参数传函数/接口（Pi 的主流方式）
- 两种方式在同一问题上的解，手段不同，核心相同——让内核稳定，让扩展灵活

**原则 3：消息是核心抽象**

`AgentMessage`（Agent 内部）≠ `Message`（LLM 协议）。中间加一层 `convertToLlm` 做转换。所有扩展消息类型（`bashExecution` / `compactionSummary` / `branchSummary`）通过声明合并加入，不改循环代码。

**原则 4：两阶段初始化解循环依赖**

Extension 在加载时必须调用 `pi.registerProvider()`，但那时 `modelRegistry` 还不存在。Pi 的做法：先缓存到 `pendingProviderRegistrations` 队列，`bindCore()` 再刷新。

### 多框架运行模式对比

| 框架 | 核心模式 | 说明 |
|------|---------|------|
| **Pi Agent** | ReAct + 简化 Plan | 内循环 tool_use，外循环 steer/followUp 队列 |
| **OpenAI Agents SDK** | ReAct | 纯 tool_calls → execute → loop |
| **CrewAI** | Plan-and-Execute | 角色 = 不同提示词 + 不同工具白名单，顶层规划底层 ReAct |
| **LangGraph** | 自定（ReAct / Plan / CodeAct 均可） | 图结构自定，底层是状态机 |
| **OpenHands** | CodeAct | 核心动作通过生成代码表达 |
| **AutoGen** | Conversation 驱动 | Agent 间多轮对话，内部再套 ReAct |
| **OpenCode** | Plan + ReAct 混合 | 先 Plan 模式生成计划（只读），确认后进入 ReAct 执行 |
| **Cursor** | ReAct（Agent 模式）/ Plan（Plan 模式） | 工具集：读+写+终端，无 steering/followUp 队列 |

### 关键认知升级

| 做之前以为 | 现在知道 |
|---|---|
| Agent = 会调工具的聊天机器人 | Agent = LLM + Tools + Message Context + Runtime Loop + Event Stream |
| 工具结果直接返回给用户 | 工具结果回灌给模型继续推理 |
| 出错抛异常 | 错误通过 stopReason 编码在消息里（流协议） |
| 循环一层就够了 | 双层循环——steering 和 followUp 是不同控制流 |
| Compaction 自动触发 | agent-core 层不做决定，默认手动 `/compact` |
| Extension 随便调 API | 两阶段初始化：pre-bind 缓存 → bindCore 刷新 |
| config 放配置项 | config 其实是依赖注入容器（回调函数 + 静态值混合） |
| 工具执行是单步的 | 三阶段：prepare（串行校验）→ execute（并行 IO）→ finalize（串行收尾） |```
