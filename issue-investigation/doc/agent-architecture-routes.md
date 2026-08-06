# 问题排查平台 Agent 架构选型：路线 A / B / C

> 本文从资深 AI 架构视角，对比"平台内嵌 Agent"的三种形态，给出生产化平台的选型结论。
> 背景：平台 = Vue 前端 + FastAPI 后端（kernel 排查内核）+ pi sidecar（agent 编排）+ LLM（opencode-go）。
> 更新（2026-08）：pi sidecar 已替换为 opencode（`analysis/` = Bun + @opencode-ai/sdk + opencode serve 子进程 + 6 个 Custom Tools，
> 全部 opencode 配置/工具集中在 `config/opencode/`，公共提示词 `config/prompt.md`，代码在 `analysis/src/opencode/`；pi 引擎共存于 `src/pi/` + 端口 8701
> （双引擎正式共存，`INV_AGENT_ENGINE` 选择），结论仍为路线 C：显式工具 + 平台编排；opencode 侧通过自定义 agent 权限（`opencode.json` 全 deny + 白名单）实现工具级控制。

---

## 一、三种路线的模式定义

```
┌─────────────────────────────────────────────────────────────────┐
│                      问题排查内核（kernel/scripts）               │
│        collect_logs / collect_db / scan_code / nacos / inv_runner │
└─────────────────────────────────────────────────────────────────┘
          ↑ 三种方式被 Agent 编排层调用
```

### 路线 A：自定义工具桥接（现状）

```
浏览器 → FastAPI ──HTTP──▶ pi sidecar（自定义 6 工具）──HTTP──▶ 内核脚本
                              │
                         LLM 只能调这 6 个工具
```

| 特征 | 说明 |
|---|---|
| 工具清单 | `collect_logs` / `scan_code` / `nacos_query` / `db_query` / `run_investigation` / `read_artifact` |
| 工具定义 | `analysis/src/index.ts` 用 TypeBox 定义参数 schema，execute 回调后端 |
| 结果返回 | 工具摘要（`tools_exec.py` 采样）+ 全量落盘 `data/runs/{run_id}/artifacts/` |
| 上下文控制 | 平台决定喂给 LLM 什么（采样条数/长度/截断） |
| 流程保障 | prompt 纪律（弱约束），无强制状态机 |
| 典型问题 | 摘要截断导致信息丢失（问题2 根因）；agent 自由发挥易跑偏 |

### 路线 B：内嵌 pi 执行 skill（模型驱动 CLI）

```
浏览器 ──▶ FastAPI ──▶ pi sidecar（挂载 SKILL.md + 放开 bash/read 内置工具）
                            │
                    LLM 自己读 skill → 自己跑 CLI（driver-start/inv_runner）
```

| 特征 | 说明 |
|---|---|
| 知识来源 | `DefaultResourceLoader.skillPaths` 挂载 SKILL.md，自动注入 system prompt |
| 执行方式 | LLM 调 `bash` 跑 `issue_inv_cli.py driver-start` → `driver-choose` → `inv_runner.py` |
| 流程保障 | driver 状态机强约束（表单→采集→§5 结论→回执校验，漏步骤不给过） |
| 信息完整性 | LLM 直接 `read` evidence.json / logs.json 全量文件 |
| 控制面 | **在模型**：LLM 既是推理引擎又是编排器 |
| 典型问题 | 审计黑盒、权限失控、崩溃恢复难、事件流断裂、产物落点偏离平台 |

### 路线 C：显式工具 + 平台编排 + 结果引用（推荐）

```
浏览器 ──▶ FastAPI ──▶ pi sidecar（6 工具 + read_artifact）──▶ 内核脚本
                            │
      工具返回「结构化结果 + artifact 引用」，LLM 按需 read_artifact 读全量
```

| 特征 | 说明 |
|---|---|
| 工具清单 | 路线 A 的 6 工具（含 `read_artifact`） |
| 结果模式 | 工具返回结构化摘要 + artifact 路径引用（全量已落盘） |
| 信息完整性 | 不丢：全量落盘；不爆：按需读（max_chars/offset 分段） |
| 控制面 | **在平台**：平台是编排器，LLM 只做决策 |
| 流程保障 | 平台层 driver（复刻 skill 的"识别→采集→分析→结论校验"状态机） |
| 业界对应 | Anthropic artifacts / Codex 文件引用 / MCP resource / Agent SDK 工具注册 |

---

## 二、架构第一性原则：控制面放在哪一层

```
路线 A/C：控制面在平台         路线 B：控制面在模型
平台 = 编排器，LLM = 推理引擎    LLM = 既是推理引擎又是编排器
工具调用 = 平台可见的原子操作      bash 跑 CLI = 模型的黑盒动作
```

生产系统的三个硬约束，决定了控制面必须上移：

| 约束 | 路线 A/C（显式工具） | 路线 B（模型跑 CLI） |
|---|---|---|
| **审计/可观测** | `tool_start/end` 天然记录：工具名、参数、结果、耗时 | 只能看到 `bash collect_logs.py --query ...` 一串命令，参数意图靠猜 |
| **权限/安全** | 工具级白名单、参数校验、限流 | bash 是万能通道——要么全放行（危险）要么全禁（没意义） |
| **崩溃恢复** | 平台掌握 run 状态（run.json/pending），可续跑 | CLI 的 driver 状态是模型上下文外的副作用，进程一断就丢 |

> 路线 B 的"强流程保障"是个错觉——driver 状态机的价值确实高，但正确位置是**平台代码层**（平台自己维护"识别→采集→分析→结论校验"状态机），而不是让模型在一轮轮 `driver-choose` 里自己推进（每步一次 LLM 往返，token 翻倍、延迟翻倍、失败面翻倍）。

---

## 三、三种路线完整对比

| 维度 | 路线 A（现状） | 路线 B（模型跑 skill CLI） | 路线 C（推荐） |
|---|---|---|---|
| **控制面** | 平台 | 模型 | 平台 |
| **工具可见性** | 6 个显式工具 | bash 黑盒 | 6 工具 + read_artifact |
| **信息完整性** | 摘要截断（8 条×300 字符） | 全量可读（read 文件） | 全量落盘 + 按需读取（artifact 引用） |
| **上下文成本** | 低（摘要） | 高（CLI 输出全量进上下文） | 低~中（按需读） |
| **流程保障** | prompt 纪律（弱） | driver 状态机（强，但由模型推进） | 平台层 driver（强，由平台推进） |
| **审计** | ✅ tool_start/end | ❌ 只能看命令串 | ✅ tool_start/end |
| **权限控制** | ✅ 工具级 | ❌ bash 万能通道 | ✅ 工具级 + artifact 路径校验 |
| **崩溃恢复** | ✅ run.json/pending 续跑 | ❌ CLI 状态是副作用 | ✅ run.json/pending 续跑 |
| **事件流（前端体验）** | ✅ 工具中间过程可见 | ❌ 只剩 thinking/文本 | ✅ 工具中间过程可见 |
| **产物归档** | ✅ data/runs/ 平台归档 | ❌ 落 .cursor/investigation/ | ✅ data/runs/ 平台归档 |
| **工程改动量** | 0（现状） | 大（重构为 skill 宿主） | 小（已实现 read_artifact，补平台层 driver） |
| **效果对齐 Cursor** | ❌ 差一截 | ✅ 等于 Cursor | ✅ 可对齐（平台层 driver 补流程） |

---

## 四、业界怎么做的（关键依据）

- **所有主流 agent 生产平台**（OpenAI Agent SDK / Codex、Anthropic Claude Agent SDK、LangGraph、AutoGen、Google ADK、企业平台 Agentforce/ServiceNow）：**清一色"显式工具注册 + 平台编排 + 权限审计"**。没有一家让模型去驱动内部 CLI 状态机。
- **MCP 的兴起**正是印证：工具服务化、平台统一接入、结果结构化——这就是路线 A/C 的思路被标准化。
- **Anthropic 推的 Agent Skills 标准**（agentskills.io，pi 已实现）：定位是"**给模型的领域知识包**"（prompt+脚本），用于复用人/团队的知识，**不是生产系统的主编排机制**。Skill 的强流程约束是给"单机开发环境"用的补偿设计。
- **唯一"模型直接跑 bash"的场景**：Claude Code / Cursor / opencode TUI——但这些是**坐在屏幕前的开发者工具**，且有权限弹窗+会话审计。而我们的平台是**多业务人员访问的生产服务**，形态不同，架构不能照搬。
- 即使如此，**opencode 自己也做了控制层**：permission 系统、session/event 流、结构化输出——都在收敛回"平台控制、模型决策"。

---

## 五、路线 C 的架构内核（为什么它是正确答案）

路线 C 不是"妥协"，它对应业界标准的 **artifact/reference 模式**：

> 工具返回**结构化结果 + 引用（artifact 路径）**，平台管理上下文，模型按需用 `read_artifact` 读取。

这就是 Anthropic artifacts、Codex 文件引用、MCP resource 的统一做法。信息不会丢（全量落盘），上下文不爆炸（按需读），agent 的能力边界清晰（6 个显式工具 + 1 个读文件工具）。

### 平台层 driver（完整形态）

把 skill 的"表单→采集→§5→回执校验"状态机用平台代码实现，模型只做决策不做编排：

```
用户提问
  → 识别（config_store：应用/业务键/术语）
  → 采集（工具：collect_logs / db_query / scan_code …）
  → 分析（LLM 决策，工具补查）
  → 结论校验（validateConclusion，缺结论自动补救一轮）
  → 完成（结构化快照落 run.json + 满意度评价）
```

再挂载 SKILL.md（`skillPaths`），吸收 skill 的领域知识进 prompt——**"吸收 skill 全部优点、又不犯控制面错位"**的形态。

---

## 六、结论

> **路线 B 把平台做成了"一个能跑 bash 的模型"，路线 C 把平台做成了"一个带审计的工具编排器"。前者是 Cursor 的简化版，后者是 MCP/Agent SDK 的标准形态。**

- 生产化平台选 **C**，没有悬念；
- B 的收益（driver 强约束、完整日志）在 C 里都可以用平台代码等价实现，且实现得更稳；
- 路线 C 的落地路径：**已实现** `read_artifact` + `time_coverage`（解决信息截断根因）→ **下一步** 平台层 driver 状态机（补流程保障）→ 可选挂载 SKILL.md（补领域知识）。

---

## 附：本次改造已在路线 C 上完成的落地项

| 改动 | 位置 | 解决什么 |
|---|---|---|
| `read_artifact` 工具（路径校验+分段读） | `backend/app/tools_exec.py`、`config/opencode/.opencode/tools/read_artifact.ts`、`analysis/src/pi/index.ts`、`config/prompt.md` | 信息截断根因：LLM 可按需读全量产物 |
| `time_coverage`（earliest/latest/entries） | `backend/app/tools_exec.py` | agent 感知采样时间覆盖，主动窗口化补查 |
| collect_logs 样本 8→15 条 | `backend/app/tools_exec.py` | 摘要信息量适度提升 |
