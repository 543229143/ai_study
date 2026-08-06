import { tool } from "@opencode-ai/plugin"

const SIDECAR_URL = process.env.INV_SIDECAR_URL ?? "http://127.0.0.1:8700"
const TOOL_TOKEN = process.env.INV_PI_TOOL_TOKEN ?? "local-dev-token"

export default tool({
  description: "只读执行数据库查询（自动 LIMIT 20，单次≤5条）。plan 结构：{need_db:true, queries:[{app,table,sql}]}；无假设时返回 need_db:false。",
  args: {
    env: tool.schema.string().describe("环境：dev 或 sit"),
    app: tool.schema.string().optional().describe("主应用"),
    plan: tool.schema
      .object({
        need_db: tool.schema.boolean().describe("是否需要查库"),
        queries: tool.schema
          .array(
            tool.schema.object({
              app: tool.schema.string().describe("应用"),
              table: tool.schema.string().optional().describe("表名"),
              sql: tool.schema.string().describe("只读 SELECT"),
              where: tool.schema.string().optional().describe("where 条件描述"),
            }),
          )
          .optional()
          .describe("查询列表（≤5 条）"),
      })
      .describe("库表排查计划"),
  },
  async execute(args, context) {
    const resp = await fetch(`${SIDECAR_URL}/tool/db_query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-tool-token": TOOL_TOKEN,
      },
      body: JSON.stringify({ session_id: context.sessionID, args }),
    })
    const text = await resp.text()
    if (!resp.ok) {
      return `tool db_query failed (${resp.status}): ${text.slice(0, 500)}`
    }
    return text.length > 24000 ? text.slice(0, 24000) + "\n...(截断)" : text
  },
})
