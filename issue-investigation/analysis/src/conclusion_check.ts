/**
 * 结论完整性校验（移植自 issue-investigation skill 的 lib/receipt.py validate_receipt_fields）：
 * 防 agent 不写结论就结束。判定作用在最终答案全文（回答风格规则要求"结论"为显式小节）。
 */

const PLACEHOLDER_MARKERS = [
  "请结合各应用证据",
  "Agent 填写",
  "（Agent 填写）",
  "（1-2 句话，用于完成回执自动提取）",
  "（必填：已定位根因",
  "（必填）简明描述根因",
  "（列出已排除的可能性",
  "（若无需排除项",
];

/** 回显标记：回答包含平台注入前缀/用户消息原文（模型空回复时常见），视为未作答。 */
export const ECHO_MARKERS = ["用户消息:", "[当前排查环境:", "[识别提示:"];

const INCONCLUSIVE_MARKERS = [
  "未能定位",
  "未定位根因",
  "无法确定",
  "暂未能",
  "未能分析",
  "未能得出",
  "证据不足",
  "无法定位",
  "暂未定位",
  "证据不充分",
  "有待进一步",
];

const CLUE_MARKERS = [
  "还需",
  "还缺",
  "需要进一步",
  "建议进一步",
  "建议补充",
  "补充线索",
  "下一步排查",
  "待获取",
  "需提供",
  "缺少",
  "缺失",
];

/** 显式否定（"无待补线索"等）→ 视为未提供线索（对齐 skill：无/暂无 算未填）。 */
const NEGATED_CLUE_RE = /(?:无|暂无|不需要|无需|不需要提供)\s*(?:待补|补充)?线索/;

const CONFIDENCE_RE = /(?:置信度|confidence)\D*?(\d{1,3})\s*%/i;

/** 文字置信度（"置信度：高/中/低"）——模型常用文字表述，与百分比等价视为已给出置信度。 */
const TEXT_CONFIDENCE_RE = /(?:置信度|confidence)\s*[:：]?\s*(?:极高|较高|高|中|较低|低)/i;

/** 多余断言：结论后的"无需干预/无需操作"类总结（用户未询问下一步时属于冗余，硬校验必补救）。 */
const EXTRA_CLAIM_RE = /(?:无需|不需要|不用)\s*(?:用户侧?|用户|人工|额外)?\s*(?:干预|操作|处理|关注|介入|跟进)/;

/** 用户问题含这些词 → 可能是在问"下一步怎么做"，此时"无需干预"类回答不算多余。 */
const ASK_NEXT_RE = /怎么办|下一步|建议|是否需要|需要做|后续|还(?:需要|要不要)/;

export interface ConclusionCheckOptions {
  /** 用户提问原文：询问"下一步"时，"无需干预"类回答不算多余断言。 */
  userText?: string;
}

export interface ConclusionCheckResult {
  ok: boolean;
  reason: string | null;
}

function hasClues(text: string): boolean {
  if (NEGATED_CLUE_RE.test(text)) return false;
  return CLUE_MARKERS.some((m) => text.includes(m));
}

export function validateConclusion(text: string, opts: ConclusionCheckOptions = {}): ConclusionCheckResult {
  const t = (text || "").trim();
  if (!t || t.length < 6 || PLACEHOLDER_MARKERS.some((m) => t.includes(m))) {
    return { ok: false, reason: "回答缺少明确的排查结论" };
  }
  if (ECHO_MARKERS.some((m) => t.includes(m))) {
    return { ok: false, reason: "回答疑似回显了用户消息/平台注入前缀（模型空回复），未给出排查结论" };
  }
  const inconclusive = INCONCLUSIVE_MARKERS.some((m) => t.includes(m));
  const hasConfidence = CONFIDENCE_RE.test(t) || TEXT_CONFIDENCE_RE.test(t);
  // 结论结构检查：已定位结论必须含置信度（prompt 规则要求）；未定位场景改为要求待补线索
  if (!inconclusive && !hasConfidence) {
    return { ok: false, reason: "回答未给出结论结构（缺置信度/未定位标记），疑似未完成" };
  }
  if (inconclusive && !hasClues(t)) {
    return { ok: false, reason: "未定位根因但回答未说明待补线索" };
  }
  const conf = CONFIDENCE_RE.exec(t);
  if (conf) {
    const v = Number(conf[1]);
    if (v < 30 && !hasClues(t)) {
      return { ok: false, reason: `置信度仅 ${v}%，回答未说明待补线索` };
    }
  }
  const askedNext = ASK_NEXT_RE.test(opts.userText || "");
  if (!askedNext && EXTRA_CLAIM_RE.test(t)) {
    return { ok: false, reason: "回答包含'无需干预/无需操作'类多余断言（用户未询问下一步），应在证据链+结论处收尾" };
  }
  return { ok: true, reason: null };
}
