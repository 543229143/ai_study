---
title: "LCS 账务核心表"
date_created: 2026-06-12
date_modified: 2026-06-12
summary: "LCS 项目账务模块的核心数据库表。"
tags: [xurong, lcs, 账务]
type: entity
status: draft
---

# LCS 账务核心表

## 放款流水
- `lcs.pilot_tran_proc_db` — 放款交易流水表

## 权益
- `lcs.pilot_privilege_tran_proc` — 权益流水表
- `lcs.pilot_privilege_order` — 权益订单表
- `lcs.pilot_privilege_plan` — 权益还款计划表

## 搭售产品（AMC）
- `lcs.pilot_addon_tran_proc` — 搭售产品流水表
- `lcs.pilot_addon_order` — 搭售产品订单表
- `lcs.pilot_addon_plan` — 搭售产品还款计划表

详见 [[账务对外常用解释]]。
