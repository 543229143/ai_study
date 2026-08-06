import { validateConclusion } from "./conclusion_check.ts";
import { test, expect } from "bun:test";

test("空回答 → 缺结论", () => {
  const r = validateConclusion("");
  expect(r.ok).toBe(false);
  expect(r.reason).toContain("结论");
});

test("过短回答 → 缺结论", () => {
  expect(validateConclusion("好的").ok).toBe(false);
});

test("占位模板 → 缺结论", () => {
  expect(validateConclusion("Agent 填写：排查结果...").ok).toBe(false);
});

test("完整结论（置信度 80%+证据）→ 通过", () => {
  const r = validateConclusion(
    "## 结论\n根因：XX 服务未配置超时导致超时重试。置信度 80%，依据日志超时错误与代码路径一致。",
  );
  expect(r.ok).toBe(true);
  expect(r.reason).toBeNull();
});

test("未定位但无待补线索 → 拦截", () => {
  const r = validateConclusion("## 结论\n未能定位根因。");
  expect(r.ok).toBe(false);
  expect(r.reason).toContain("待补线索");
});

test("未定位但有待补线索 → 通过", () => {
  const r = validateConclusion(
    "## 结论\n未能定位根因，还需提供该笔业务的 traceId 与机构响应报文才能继续。",
  );
  expect(r.ok).toBe(true);
});

test("置信度 20% 且无线索 → 拦截", () => {
  const r = validateConclusion("## 结论\n推测是网络问题。置信度 20%。");
  expect(r.ok).toBe(false);
});

test("置信度 20% 但有线索 → 通过", () => {
  const r = validateConclusion(
    "## 结论\n推测是网络问题，置信度 20%。建议进一步抓取网关访问日志确认。",
  );
  expect(r.ok).toBe(true);
});

test("置信度 85% 无线索 → 通过", () => {
  const r = validateConclusion("## 结论\n根因：参数校验失败。置信度 85%。");
  expect(r.ok).toBe(true);
});

test("英文 confidence 兼容", () => {
  const r = validateConclusion("conclusion: root cause unknown. confidence 15%.");
  expect(r.ok).toBe(false);
  expect(r.reason).toContain("置信度");
});

test("显式否定线索（暂无待补线索）→ 视为未填", () => {
  const r = validateConclusion("## 结论\n无法确定根因，暂无待补线索。");
  expect(r.ok).toBe(false);
});

test("多余断言（无需用户侧干预）且用户未问下一步 → 拦截", () => {
  const r = validateConclusion(
    "## 结论\n根因：资金方风控拒绝。置信度 90%。\n3. 同用户本次授信已由其他资金方正常承接（盛备等已出额度），无需用户侧干预。",
    { userText: "查一下日志id CR1260470767292911616 为什么被拒绝" },
  );
  expect(r.ok).toBe(false);
  expect(r.reason).toContain("多余断言");
});

test("多余断言但用户问了下一步 → 通过", () => {
  const r = validateConclusion(
    "## 结论\n根因：资金方风控拒绝。置信度 90%。\n无需用户侧干预。",
    { userText: "这个还需要处理吗？下一步怎么办" },
  );
  expect(r.ok).toBe(true);
});

test("正常结论（无多余断言）→ 通过", () => {
  const r = validateConclusion(
    "## 结论\n根因：资金方风控拒绝，回调明文 failed_reason 即拒绝原因。置信度 90%。",
    { userText: "查一下为什么被拒绝" },
  );
  expect(r.ok).toBe(true);
});

test("回显用户消息（含平台注入标记）→ 拦截", () => {
  const r = validateConclusion(
    "[当前排查环境: sit]（所有日志/库表/配置查询均按 sit 执行；如与之前声明不一致，以此为准）\n\n用户消息: [识别提示: 业务键命中表字段: lps.ap_fund_appl.appl_no]\n\n查一下日志id CR1260470767292911616 为什么被拒绝",
  );
  expect(r.ok).toBe(false);
  expect(r.reason).toContain("回显");
});

test("含识别提示前缀的回显 → 拦截", () => {
  const r = validateConclusion("[识别提示: 命中 lps.ap_fund_appl.appl_no]\n\n查一下为什么被拒绝");
  expect(r.ok).toBe(false);
});

test("中间过程文本（无置信度/未定位标记）→ 拦截（防模型早停被当结论）", () => {
  const r = validateConclusion("我先检查平台是否已自动执行过初始日志采集，复用产物避免重复采集。");
  expect(r.ok).toBe(false);
  expect(r.reason).toContain("结论结构");
});

test("已定位但缺置信度 → 拦截", () => {
  const r = validateConclusion("## 结论\n根因：参数校验失败，证据已列出。");
  expect(r.ok).toBe(false);
});
