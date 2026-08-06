import { tool } from "@opencode-ai/plugin"

const SIDECAR_URL = process.env.INV_SIDECAR_URL ?? "http://127.0.0.1:8700"
const TOOL_TOKEN = process.env.INV_PI_TOOL_TOKEN ?? "local-dev-token"

export default tool({
  description: "采集 dev/sit 环境 ES 日志（按 traceId/告警/业务键）。结果含各应用命中数与错误数，以及日志原文采样。",
  args: {
    env: tool.schema.string().describe("环境：dev 或 sit"),
    app: tool.schema.string().describe("主应用"),
    mode: tool.schema.enum(["trace_id", "alert", "biz_key"]).optional().describe("排查模式"),
    query: tool.schema.string().optional().describe("查询值：traceId 或业务键"),
    alert: tool.schema.string().optional().describe("告警/报错文本（mode=alert 时）"),
    biz_key: tool.schema.string().optional().describe("业务键（mode=biz_key 时）"),
    apps: tool.schema.array(tool.schema.string()).optional().describe("涉及应用列表（默认仅主应用）"),
  },
  async execute(args, context) {
    return await callSidecar(context.sessionID, "collect_logs", args)
  },
})

async function callSidecar(sessionId: string, name: string, args: unknown): Promise<string> {
  const resp = await fetch(`${SIDECAR_URL}/tool/${name}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-tool-token": TOOL_TOKEN,
    },
    body: JSON.stringify({ session_id: sessionId, args }),
  })
  const text = await resp.text()
  if (!resp.ok) {
    return `tool ${name} failed (${resp.status}): ${text.slice(0, 500)}`
  }
  return text.length > 24000 ? text.slice(0, 24000) + "\n...(截断)" : text
}
