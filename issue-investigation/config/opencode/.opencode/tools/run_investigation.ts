import { tool } from "@opencode-ai/plugin"

const SIDECAR_URL = process.env.INV_SIDECAR_URL ?? "http://127.0.0.1:8700"
const TOOL_TOKEN = process.env.INV_PI_TOOL_TOKEN ?? "local-dev-token"

export default tool({
  description: "一键执行完整排查流水线：ES 日志 + 源码扫描 + Nacos（可选）+ 报告 §1-§4（指纹去重/时序/交叉验证）。适合首次完整排查。",
  args: {
    env: tool.schema.string().describe("环境：dev 或 sit"),
    app: tool.schema.string().describe("主应用"),
    mode: tool.schema.enum(["trace_id", "alert", "biz_key"]).optional().describe("排查模式"),
    query: tool.schema.string().optional().describe("查询值：traceId 或业务键"),
    alert: tool.schema.string().optional().describe("告警/报错文本"),
    biz_key: tool.schema.string().optional().describe("业务键"),
    scope: tool.schema.enum(["primary_only", "all"]).optional().describe("范围：仅主应用 / 四应用广扫"),
  },
  async execute(args, context) {
    const resp = await fetch(`${SIDECAR_URL}/tool/run_investigation`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-tool-token": TOOL_TOKEN,
      },
      body: JSON.stringify({ session_id: context.sessionID, args }),
    })
    const text = await resp.text()
    if (!resp.ok) {
      return `tool run_investigation failed (${resp.status}): ${text.slice(0, 500)}`
    }
    return text.length > 24000 ? text.slice(0, 24000) + "\n...(截断)" : text
  },
})
