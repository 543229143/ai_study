import { tool } from "@opencode-ai/plugin"

const SIDECAR_URL = process.env.INV_SIDECAR_URL ?? "http://127.0.0.1:8700"
const TOOL_TOKEN = process.env.INV_PI_TOOL_TOKEN ?? "local-dev-token"

export default tool({
  description: "扫描 Java 源码 + Mapper XML + Spring 配置 + git 变更，定位异常类/方法/调用链。",
  args: {
    env: tool.schema.string().describe("环境：dev 或 sit"),
    app: tool.schema.string().describe("主应用"),
    keywords: tool.schema.array(tool.schema.string()).describe("扫描关键词（类名/方法名/字段）"),
    log_messages: tool.schema.array(tool.schema.string()).optional().describe("日志片段（可选，作为扫描上下文）"),
  },
  async execute(args, context) {
    const resp = await fetch(`${SIDECAR_URL}/tool/scan_code`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-tool-token": TOOL_TOKEN,
      },
      body: JSON.stringify({ session_id: context.sessionID, args }),
    })
    const text = await resp.text()
    if (!resp.ok) {
      return `tool scan_code failed (${resp.status}): ${text.slice(0, 500)}`
    }
    return text.length > 24000 ? text.slice(0, 24000) + "\n...(截断)" : text
  },
})
