import { tool } from "@opencode-ai/plugin"

const SIDECAR_URL = process.env.INV_SIDECAR_URL ?? "http://127.0.0.1:8700"
const TOOL_TOKEN = process.env.INV_PI_TOOL_TOKEN ?? "local-dev-token"

export default tool({
  description: "读取当前 run 的中间产物全文（artifacts/ 下相对路径）。当工具返回的采样/摘要不足以判断（如日志采样被截断、需要看完整日志/完整 SQL 结果/完整报告）时使用。",
  args: {
    path: tool.schema.string().describe("artifacts/ 下相对路径，如 collect_logs-001/logs.json、db_query-001/database.json、run_investigation-001/investigation-report.md"),
    max_chars: tool.schema.number().optional().describe("读取字符数上限（默认 20000，最大 60000，配合 offset 按字符分段读）"),
    offset: tool.schema.number().optional().describe("起始偏移（配合 max_chars 分段读大文件）"),
  },
  async execute(args, context) {
    const resp = await fetch(`${SIDECAR_URL}/tool/read_artifact`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-tool-token": TOOL_TOKEN,
      },
      body: JSON.stringify({ session_id: context.sessionID, args }),
    })
    const text = await resp.text()
    if (!resp.ok) {
      return `tool read_artifact failed (${resp.status}): ${text.slice(0, 500)}`
    }
    return text.length > 60000 ? text.slice(0, 60000) + "\n...(截断)" : text
  },
})
