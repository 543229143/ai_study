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

export interface ConclusionCheckResult {
  ok: boolean;
  reason: string | null;
}

function hasClues(text: string): boolean {
  if (NEGATED_CLUE_RE.test(text)) return false;
  return CLUE_MARKERS.some((m) => text.includes(m));
}

export function validateConclusion(text: string): ConclusionCheckResult {
  const t = (text || "").trim();
  if (!t || t.length < 6 || PLACEHOLDER_MARKERS.some((m) => t.includes(m))) {
    return { ok: false, reason: "回答缺少明确的排查结论" };
  }
  const inconclusive = INCONCLUSIVE_MARKERS.some((m) => t.includes(m));
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
  return { ok: true, reason: null };
}
