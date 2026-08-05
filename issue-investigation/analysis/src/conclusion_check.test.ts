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
