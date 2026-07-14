---
name: sre-oncall
description: >-
  SRE 告警分诊与根因调查。三阶段流水线：分诊(Triage)→调查(Investigation)→复盘(Postmortem)。
  支持告警JSON输入，自动生成排查计划和RCA报告。
---

# SRE On-Call Agent

当用户提出 SRE 排障、告警排查、根因分析、incident 调查等需求时使用本 skill。

## 运行方式

```bash
python3 core/cli.py <incident_id>
```

## 可用 incident

- `db_pool_exhaustion` — 数据库连接池耗尽导致 503
- `memory_leak_oom` — 缓存服务内存泄漏被 OOM Killer 杀死
- `external_api_ratelimit` — 外部支付API限流导致订单超时

## 流程说明

1. **Triage** (Plan-and-Solve): 解析告警 → 生成分步排查计划
2. **Investigation** (ReAct): 按计划循环执行 log_search / metric_query / runbook_lookup
3. **Postmortem** (Reflection): draft → critique → revise 生成 RCA 报告

报告输出到 `data/reports/<incident_id>_report.md`
