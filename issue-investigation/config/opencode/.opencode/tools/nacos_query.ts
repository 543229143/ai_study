import { tool } from "@opencode-ai/plugin"

const SIDECAR_URL = process.env.INV_SIDECAR_URL ?? "http://127.0.0.1:8700"
const TOOL_TOKEN = process.env.INV_PI_TOOL_TOKEN ?? "local-dev-token"

export default tool({
  description: "查询指定应用的 Nacos 配置 key（group/dataId 自动发现）。",
  args: {
    env: tool.schema.string().describe("环境：dev 或 sit"),
    app: tool.schema.string().describe("应用"),
    keys: tool.schema.array(tool.schema.string()).describe("要查询的配置 key 列表"),
  },
  async execute(args, context) {
    const resp = await fetch(`${SIDECAR_URL}/tool/nacos_query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-tool-token": TOOL_TOKEN,
      },
      body: JSON.stringify({ session_id: context.sessionID, args }),
    })
    const text = await resp.text()
    if (!resp.ok) {
      return `tool nacos_query failed (${resp.status}): ${text.slice(0, 500)}`
    }
    return text.length > 24000 ? text.slice(0, 24000) + "\n...(截断)" : text
  },
})
