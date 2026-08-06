/**
 * opencode 会话事件 → 平台事件映射。
 * opencode 升级若改了事件类型/字段名，这里会静默失效（编译不报错），
 * 升级后须按 README「opencode 升级 SOP」逐项核对本表。
 */
import { runBySession } from "./client.ts";

export const EVENT_PROTOCOL = {
  ocPartDelta: "message.part.delta",
  ocPartUpdated: "message.part.updated",
  ocMessageUpdated: "message.updated",
  ocSessionIdle: "session.idle",
  ocSessionStatus: "session.status",
  ocMessageError: "message.error",
  ocSessionError: "session.error",
  outTextDelta: "text_delta",
  outThinkingDelta: "thinking_delta",
  outToolStart: "tool_start",
  outToolEnd: "tool_end",
  outMessageEnd: "message_end",
  outDone: "done",
} as const;
export const EVENT_PROTOCOL_VERSION = "2.0";

export interface EventHandlerCtx {
  /** 推送平台事件（与 pi 版本协议一致） */
  forwardEvent(runId: string, ev: { type: string; data: any }): void;
  /** session.idle 且该 run 有进行中的轮次 → 结论校验/补救 */
  onSessionIdle(runId: string, sessionId: string): void;
}

const partTypes = new Map<string, "text" | "reasoning">(); // partID -> 类型
const partEmitted = new Set<string>(); // 已发过全量兜底文本的 partID
const partStreamed = new Set<string>(); // 已流式（delta）过的 partID——updated 不再兜底全量（防重复）
const toolStarted = new Set<string>(); // callID -> 已发 tool_start
const toolEnded = new Set<string>(); // callID -> 已发 tool_end

export function createEventHandler(ctx: EventHandlerCtx): (ev: any) => void {
  return (ev: any) => {
    const props = ev?.properties ?? {};
    const sessionId = props.sessionID;
    if (!sessionId) return;
    const runId = runBySession.get(sessionId);
    if (!runId) return;

    switch (ev.type) {
      case EVENT_PROTOCOL.ocPartDelta: {
        const { partID, field, delta } = props;
        if (field !== "text" || !delta) return;
        partStreamed.add(partID);
        const type =
          partTypes.get(partID) === "reasoning" ? EVENT_PROTOCOL.outThinkingDelta : EVENT_PROTOCOL.outTextDelta;
        ctx.forwardEvent(runId, { type, data: { text: delta } });
        return;
      }
      case EVENT_PROTOCOL.ocPartUpdated: {
        const part = props.part;
        if (!part) return;
        if (part.type === "text" || part.type === "reasoning") {
          partTypes.set(part.id, part.type);
          // 兜底：无 delta 流（非流式模型）时全量发出一次；已流式过的 part 不再重复发
          if (!partStreamed.has(part.id) && !partEmitted.has(part.id) && part.text) {
            partEmitted.add(part.id);
            ctx.forwardEvent(runId, {
              type: part.type === "reasoning" ? EVENT_PROTOCOL.outThinkingDelta : EVENT_PROTOCOL.outTextDelta,
              data: { text: part.text },
            });
          }
          return;
        }
        if (part.type === "tool") {
          const st = part.state?.status;
          if (st === "pending" || st === "running") {
            if (!toolStarted.has(part.callID)) {
              toolStarted.add(part.callID);
              ctx.forwardEvent(runId, { type: EVENT_PROTOCOL.outToolStart, data: { tool: part.tool } });
            }
          } else if (st === "completed" || st === "error") {
            if (!toolEnded.has(part.callID)) {
              toolEnded.add(part.callID);
              ctx.forwardEvent(runId, {
                type: EVENT_PROTOCOL.outToolEnd,
                data: { tool: part.tool, isError: st === "error" },
              });
            }
          }
          return;
        }
        return;
      }
      case EVENT_PROTOCOL.ocMessageUpdated: {
        const info = props.info;
        if (info?.role === "assistant" && info.time?.completed) {
          ctx.forwardEvent(runId, { type: EVENT_PROTOCOL.outMessageEnd, data: {} });
        }
        return;
      }
      case EVENT_PROTOCOL.ocSessionIdle: {
        ctx.onSessionIdle(runId, sessionId);
        return;
      }
      case EVENT_PROTOCOL.ocMessageError:
      case EVENT_PROTOCOL.ocSessionError: {
        const err = props.error ?? props.message ?? "";
        const message = typeof err === "string" ? err : err?.message || JSON.stringify(err);
        ctx.forwardEvent(runId, { type: "error", data: { message } });
        return;
      }
      default:
        return;
    }
  };
}
