# HTTP 单次提交排查 + 企业微信结果通知（`POST /invoke`）

> 状态：方案待实现
> 背景：平台 = Vue 前端（5178）+ FastAPI 后端（8600）+ opencode sidecar（8700，双引擎共存 pi 8701）+ kernel 排查内核。
> 关联：`技术方案-问题排查平台.md`、`doc/agent-architecture-routes.md`。

---

## 一、业务背景

### 1.1 场景来源

问题排查平台目前的服务对象是**人**：用户在浏览器里打开页面，选择环境、粘贴 traceId / 告警 / 业务单号，与 agent 对话式完成排查。

但实际工作中，问题不只是人发现的：

- **监控系统**（告警平台、日志监控）检测到异常（接口报错、落库失败、超时）时，需要自动发起排查；
- **批处理任务**（夜间跑批、定时任务）失败时，需要自动定位原因；
- **用户报障系统**（工单、IM 机器人）收到用户反馈"借据没结清、订单状态不对"时，需要自动跟进；
- **运维脚本 / CI 流水线**在发布后需要自动验证数据正确性。

这些**机器调用方**发现问题后，期望：**组装问题 → 一次 HTTP 调用交给平台 → 平台自动排查 → 排查结束把结果通知到人**（不管成功还是失败），全程不关心平台内部细节。

### 1.2 现状痛点

现有 API 面向"人机对话"设计，机器调用方用起来有三个问题：

1. **交互次数多**：需要先 `POST /runs` 创建会话，再 `POST /runs/{id}/messages` 发送问题，至少两次调用；
2. **结果获取难**：排查是异步的（agent 跑几十秒到几分钟），调用方要开 WebSocket 监听事件流，或不断轮询状态，才知道是否结束、结果如何；
3. **结果不可达**：即使拿到结果，也只是接口返回，无法触达"真正需要知道结果的人"（值班研发、报障运营、故障群）。

### 1.3 需求定义

> 调用方发现问题，组装问题，**异步调用一次 HTTP 接口**（fire-and-forget）；
> 平台接收后自动创建排查任务并开始排查；
> **排查结束后，不管成功/失败，自动向调用方传入的企业微信机器人 webhook 发送消息**；
> 消息内容为本次问题的详情链接（点击进入平台查看完整排查过程与结论）。

关键约束：

- 调用方与平台**只交互一次**，不轮询、不监听、不关心平台内部状态；
- **成功、失败都要通知**（失败包含：排查异常中断、平台转发故障、问题不在排查范围被拒绝）；
- webhook 地址由**调用方传入**（每次调用各自指定，平台不配置全局）；
- 通知内容是**问题链接**（落地到前端详情页），消息正文带简要结论，便于一眼判断；
- 排查流程与现有平台能力完全一致：门禁、业务键识别、初始采集、agent 工具编排、结论快照全部复用。

### 1.4 术语

| 术语 | 说明 |
|---|---|
| 调用方 | 外部系统/脚本，通过 HTTP 提交排查任务的机器方 |
| run | 一次排查任务（`data/runs/{run_id}/`），平台基本单位 |
| webhook | 企业微信群机器人 webhook 地址，调用方传入，平台 POST 通知 |
| done / error | 排查结束事件：done=agent 正常结束；error=异常终止（LLM 报错/超时/转发失败） |

---

## 二、方案设计

### 2.1 调用时序

```
调用方                     平台后端                      opencode sidecar              企业微信
  │  POST /invoke              │                              │                            │
  ├──────────────────────────▶ │                              │                            │
  │  {text, env, webhook_url}  │                              │                            │
  │                            │ create_run（识别参数）        │                            │
  │                            │ send_message（过门禁+注入+初始采集）                          │
  │                            ├─────────────────────────────▶│（agent 开始排查）           │
  │  ◀── 202 {run_id, url} ───┤   立即返回，不等排查           │                            │
  │                            │   （后台异步排查中…）         │                            │
  │                            │                              │ 工具调用/分析/结论          │
  │                            │ ◀── done / error 事件 ──────┤                            │
  │                            │ 落盘 + 结论快照                │                            │
  │                            │ 读 run.webhook_url → 组装消息  │                            │
  │                            ├────────────────────────────────────────────────────────▶ │
  │                            │   ✅ 排查完成 / ❌ 排查失败     │                            │
  │                            │   + 问题链接                    │                            │
  │                            │                              │                            │
  │      （调用方全程无感知，收企微即结果）                        │                            │
```

### 2.2 新接口 `POST /invoke`

```
POST /invoke
Content-Type: application/json

{
  "text": "CR1263932754740039680 结清状态不对，查询无结果",
  "env": "sit",
  "app": "lps",              // 可选，未传时从 text 自动识别
  "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx",
  "engine": "opencode",      // 可选，默认 opencode
  "agent": "investigation"   // 可选，默认 investigation
}
```

成功响应（立即返回，不等待排查结束）：

```
202 Accepted
{
  "run_id": "20260806T120000Z-abcdef",
  "status": "accepted",        // accepted | rejected（门禁拒绝）
  "url": "http://<前端地址>/runs/20260806T120000Z-abcdef"   // 问题详情链接
}
```

内部流程（全部复用现有函数）：

1. `create_run`：识别业务键/应用/模式（`detect_from_text`），`webhook_url` 存入 run.json；
2. `send_message`：**照常过意图门禁**（gate.py，与其他入口一致），识别提示注入 `[识别提示: …]`、首轮初始采集照旧；
3. 返回 202，排查异步进行；结束事件（done/error）由平台统一处理通知。

### 2.3 通知触发分支（不管成功失败都发）

| 场景 | 触发 | 企微消息 |
|---|---|---|
| 排查正常结束 | done 事件 → `_snapshot_conclusion` | ✅ **排查完成** + 结论摘要（≤200 字） |
| 结论缺失（自动补救后仍缺） | done + warning | ✅ + 「结论不完整，请人工复核」 |
| 排查异常中断 | error 事件 → `_record_event` | ❌ **排查失败** + 错误信息（≤200 字，如模型服务繁忙/超时） |
| 问题不在排查范围 | 门禁拒绝（send_message 返回 rejected） | ❌ **拒绝排查** + 拒绝原因 |
| 平台转发故障（sidecar 不可用） | send_message 抛异常 | ❌ **平台故障** + 排查未开始 |

注：门禁拒绝与转发故障在接口内同步处理（仍在排查"结束"语义内），done/error 由事件挂点异步处理。

### 2.4 企微消息格式（markdown，链接可点击）

成功：

```
**✅ 排查完成** ｜ sit ｜ lps
> 问题: CR1263932754740039680 结清状态不对
> 结论: 落库异常，ap_fund_appl.appl_no 存在脏数据…（≤200 字）
[查看排查详情](http://<前端地址>/runs/<run_id>)
```

失败：

```
**❌ 排查失败** ｜ sit ｜ lps
> 问题: CR1263932754740039680 结清状态不对
> 错误: 模型服务繁忙，请稍后重试
[查看排查详情](http://<前端地址>/runs/<run_id>)
```

约束：

- 消息总体 ≤3500 字节（企微 markdown 上限 4096 字节），长内容截断；
- 链接落地页为前端现有 `/runs/:id` 详情页（对话记录 + 排查报告 + 产物），**前端零改动**；
- 消息正文只放摘要（结论/错误），完整证据链在平台详情页，防止敏感数据外泄到企微。

### 2.5 链接地址配置

`backend/app/config.py` 新增：

```python
FRONTEND_BASE_URL = os.environ.get("INV_FRONTEND_BASE_URL") or "http://127.0.0.1:5178"
```

- 开发默认 `http://127.0.0.1:5178`（dev.sh 前端端口）；
- 部署时通过环境变量配置为实际可达地址（内网域名/IP）；
- 链接 = `{FRONTEND_BASE_URL}/runs/{run_id}`。

---

## 三、实现清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `backend/app/models.py` | `CreateRunRequest` 加 `webhook_url: Optional[str]`（校验 http/https 前缀）；新增 `InvokeRequest` |
| 2 | `backend/app/api_runs.py` | `create_run` 存 `webhook_url`；新增 `POST /invoke`（create_run → send_message → 202，处理门禁拒绝/转发故障并同步触发企微） |
| 3 | `backend/app/notify.py`（新建） | `send_wecom_webhook(url, content)`：`run_in_executor` 异步 POST `{"msgtype":"markdown","markdown":{"content":...}}`，超时 5s；失败捕获并记 timeline `webhook_failed`，不重试、不影响排查；`build_notice(run, kind, summary)` 组装消息 |
| 4 | `backend/app/api_tools.py` | `_record_event`（error）与 `_snapshot_conclusion`（done）后读取 run.json `webhook_url`，有则异步发送 |
| 5 | `backend/app/config.py` | 新增 `FRONTEND_BASE_URL` |

---

## 四、已确认决策

| 决策点 | 结论 |
|---|---|
| webhook 传参位置 | `POST /invoke`（创建 run）时传一次，整个 run 生命周期有效 |
| 通知时机 | 仅排查结束（done / error），不逐轮通知 |
| done-with-warning | 算成功，✅ 发送 + 「结论不完整，请人工复核」 |
| 门禁 | `/invoke` 照常过意图门禁（与其他入口一致） |
| 鉴权 | 不加（内部平台，内网信任） |
| 发送失败处理 | 静默 + timeline 记录，不重试，不影响排查 |

---

## 五、验证方案

1. **成功路径**：本地起平台（`dev.sh`），用 webhook.site 或本地接收服务作 webhook，`curl POST /invoke` 提交真实业务单号 → 等待排查完成 → 确认收到 ✅ 消息（结论摘要 + 链接）；点击链接可打开详情页。
2. **失败路径 A（error）**：制造 agent 异常（如断 sidecar / 触发模型限流）→ 确认 ❌ 消息（错误信息）。
3. **失败路径 B（门禁拒绝）**：提交明显无关内容（如"今天天气"）→ 确认 ❌ 拒绝排查消息。
4. **失败路径 C（平台故障）**：停掉 sidecar 后提交 → 确认 ❌ 平台故障消息，接口仍返回 202。
5. **边界**：超长问题/结论截断验证；webhook 不可达时 timeline 出现 `webhook_failed` 且排查不受影响。

---

## 六、风险与注意事项

| 风险 | 说明 | 对策 |
|---|---|---|
| 企微消息外发敏感数据 | 消息经企微服务器转发，可能泄露业务数据 | 只发摘要（结论/错误 ≤200 字），完整证据留在平台详情页 |
| webhook 地址 SSRF | 调用方传入的 URL 由平台 POST 请求 | 校验 http/https 协议前缀；内网平台风险可控（内部调用方） |
| 免费档模型 503 限流 | 并发高峰网关报 "The request queue is full" | 走 error 事件 → ❌ 通知（模型服务繁忙），用户可点链接回平台继续排查 |
| 调用方重复提交 | 调用方重试可能导致重复 run | 一期不处理（每次调用 = 一次独立排查）；后续可按需加 client_request_id 幂等 |
| 发送阻塞主流程 | 企微 HTTP 调用可能慢/超时 | 全程 `run_in_executor` 异步 + 5s 超时 + 失败仅记日志 |
