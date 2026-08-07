import { tool } from "@opencode-ai/plugin"

const SIDECAR_URL = process.env.INV_SIDECAR_URL ?? "http://127.0.0.1:8700"
const TOOL_TOKEN = process.env.INV_PI_TOOL_TOKEN ?? "local-dev-token"

export default tool({
  description:
    "采集 dev/sit 环境 ES 日志（按 traceId/告警/业务键）。结果含各应用命中数与错误数，以及日志原文采样。apps[] 显式指定 = 真实采集清单（只采这些应用）；不传默认扫描全部配置应用（app 仅主应用标记，无需按应用分别调用）。",
  args: {
    env: tool.schema.string().describe("环境：dev 或 sit"),
    app: tool.schema.string().describe("主应用（仅标记/排序，不限制采集范围）"),
    mode: tool.schema.enum(["trace_id", "alert", "biz_key"]).optional().describe("排查模式"),
    query: tool.schema.string().optional().describe("查询值：traceId 或业务键"),
    alert: tool.schema.string().optional().describe("告警/报错文本（mode=alert 时）"),
    biz_key: tool.schema.string().optional().describe("业务键（mode=biz_key 时）"),
    scope: tool.schema.enum(["primary_only", "all"]).optional().describe("不传 apps 时的采集范围：all=全部配置应用（默认），primary_only=仅主应用"),
    apps: tool.schema.array(tool.schema.string()).optional().describe("真实采集应用清单（显式传则只采这些，如 ['goa','lps']；不传默认按 scope 全量）"),
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
