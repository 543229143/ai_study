"""
执行一轮证据采集并生成报告骨架（支持跨 lps/lcs/ams/goa）。

两阶段：
  --phase logs  ES + 代码 +（用户表单 probe 不在此执行）+ 报告骨架；**不跑脚本猜表**
  --phase db    读取 Agent 写出的 agent_db_plan.json + 用户表单 probe，只读执行 SQL

默认 --phase all = logs 后若已有 agent_db_plan 则继续 db（兼容旧调用）。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from collect_db import collect_multi as collect_db_multi
from collect_logs import collect_multi as collect_logs_multi
from collect_nacos import collect_multi as collect_nacos_multi
from lib.agent_db_plan import (
    agent_plan_help_text,
    load_agent_db_plan,
    queries_as_mapper_tuples,
    validate_and_normalize_plan,
    write_suggest_plan,
)
from lib.hypotheses import format_hypotheses_markdown, generate_hypotheses
from lib.common import read_json, write_json, default_log_time_from
from lib.evidence_slim import slim_evidence
from lib.correlate import format_cross_section as correlate_format_section
from lib.deps import ensure_collect_deps
from lib.db_probe import select_probes_for_log_context
from lib.infer_db_context import infer_db_context
from lib.log_collect import apply_log_profile_to_ctx, collect_kwargs_from_ctx, resolve_log_collect_profile
from lib.git_branch import (
    code_scan_apps,
    ensure_repos_on_env_branch,
    format_branch_failure_block,
    format_branch_summary,
)
from lib.workspace import resolve_apps, resolve_repo_roots, resolve_scenarios
from scan_code_context import scan_multi as scan_code_multi


def _log_entries_count(logs: dict, app: str) -> int:
    block = (logs.get("by_app") or {}).get(app) or {}
    return len(block.get("entries") or [])


def _error_summaries(logs: dict, *, limit: int = 8) -> list[str]:
    """智能错误摘要：根因优先 + 指纹去重 + 异常评分降噪。"""
    aggregated = _aggregate_stack_traces(logs)

    # 计算指纹分组和频率
    fingerprint_groups: dict[str, list[dict]] = {}
    for e in aggregated:
        fp = _stack_fingerprint(e)
        e["_fingerprint"] = fp
        fingerprint_groups.setdefault(fp, []).append(e)

    # 异常评分
    scored: list[tuple[float, dict, str]] = []  # (score, entry, display_text)
    seen_fingerprints: set[str] = set()

    for e in aggregated:
        msg = (e.get("message") or "").replace("\n", " ")
        if not msg:
            continue
        if not re.search(r"\bERROR\b|BusinessException|Exception:", msg, re.I):
            continue

        fp = e.get("_fingerprint", "")
        if fp in seen_fingerprints:
            continue
        seen_fingerprints.add(fp)

        # 提取根因异常（优于外层 wrapping 异常）
        root = _root_cause_exception(msg)
        root_str = f"（根因 {root}）" if root and root not in msg[:60] else ""

        # 提取摘要
        short = msg
        for pat in (
            r".{0,40}(\bERROR\b.{0,220})",
            r".{0,20}(BusinessException:[^:]{0,160})",
            r".{0,20}(数据异常[^。；]{0,160})",
        ):
            m = re.search(pat, msg, re.I)
            if m:
                short = m.group(1).strip()
                break
        else:
            short = msg[:200]

        # 异常评分：级别权重 × 频率权重 × 新颖度
        level_score = 3.0 if re.search(r"\bERROR\b", msg, re.I) else 1.5
        freq = len(fingerprint_groups.get(fp, [e]))
        freq_score = math.log2(freq) + 1 if freq > 0 else 1
        novelty = 1.0
        for pat, penalty in _NORMAL_PATTERNS:
            if re.search(pat, msg, re.I):
                novelty *= max(0.15, 1.0 - penalty * 0.2)
                break
        score = level_score * freq_score * novelty

        app = e.get("app") or "?"
        freq_suffix = f"（出现 {freq} 次）" if freq > 1 else ""
        display = f"- `[{app}]` {short[:240]}{root_str}{freq_suffix}"
        scored.append((score, e, display))

    # 按评分降序
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s[2][:300] for s in scored[:limit]]


def _aggregate_stack_traces(logs: dict) -> list[dict]:
    """将跨行的 Exception 堆栈合并为单条 entry，提升报告可读性。"""
    entries = list(logs.get("entries") or [])
    # 也包含 by_app 中的条目
    for block in (logs.get("by_app") or {}).values():
        entries.extend(block.get("entries") or [])
    if not entries:
        return []

    # 按时间戳排序
    entries.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    stack_start = re.compile(
        r"(?:^|\n|\t)(?:Caused by:\s*|[\w.$]+Exception[:]?)", re.I
    )
    stack_cont = re.compile(r"^\s+at\s+[\w.$]+\(.*\)", re.I)
    suppressed = re.compile(r"^\s+\.\.\.\s+\d+\s+more", re.I)

    aggregated: list[dict] = []
    buffer = None
    for e in entries:
        msg = (e.get("message") or "").strip()
        if buffer is not None:
            # 检查当前行是否是堆栈续行
            if stack_cont.match(msg) or suppressed.match(msg) or stack_start.search(msg):
                buffer["message"] = buffer["message"] + "\n" + msg
                continue
            # 当前行不再属于前一条异常，flush buffer
            aggregated.append(buffer)
            buffer = None

        if stack_start.search(msg):
            buffer = dict(e)
            continue
        aggregated.append(dict(e))

    if buffer is not None:
        aggregated.append(buffer)

    return aggregated


def _normalize_frame(frame: str) -> str:
    """提取 `at com.xxx.Method(File.java:42)` → 保留 `com.xxx.Method`（去除行号噪音）。"""
    m = re.search(r"at\s+([\w.$]+)\(([^)]*)\)", (frame or "").strip(), re.I)
    if not m:
        return (frame or "").strip()[:120]
    cls_method = m.group(1)
    # 去除匿名内部类编号，如 $1, $Lambda$42
    cls_method = re.sub(r"\$\d+", "$N", cls_method)
    return cls_method


def _stack_fingerprint(entry: dict) -> str:
    """取归一化后的 top 3 帧做 sha256 前 12 位。"""
    msg = (entry.get("message") or "").strip()
    frames: list[str] = []
    for line in msg.splitlines():
        stripped = line.strip()
        if re.match(r"^\s+at\s+", stripped) or re.match(r"^Caused by:", stripped, re.I):
            frames.append(_normalize_frame(stripped))
    if not frames:
        # fallback: 对 message 本身做 hash
        return hashlib.sha256(msg[:500].encode()).hexdigest()[:12]
    key = "|".join(frames[:3])
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _root_cause_exception(message: str) -> str | None:
    """从 Caused by 链中取最深层的异常类名（不再只看最外层）。"""
    causes = re.findall(r"Caused by:\s*([\w.$]+(?:Exception|Error))", message or "", re.I)
    if causes:
        return causes[-1]  # 最深层
    # 没有 Caused by 链，取第一个异常
    m = re.search(r"([\w.$]+(?:Exception|Error))", message or "", re.I)
    return m.group(1) if m else None


# 常见周期性/健康检查日志模式（降低权重，避免噪音）
_NORMAL_PATTERNS: list[tuple[str, int]] = [
    (r"health\s*check|/health|actuator", 3),
    (r"connection\s*pool|HikariPool|Druid", 2),
    (r"heartbeat|心跳", 3),
    (r"sync.*task|定时任务|scheduled", 2),
    (r"mock|MockAspect", 2),
    (r"traceId.*生成|generateTraceId", 1),
]


_EXCEPTION_CLASS_RE = re.compile(r"([\w.$]+(?:Exception|Error))")
_TRACE_LOC_RE = re.compile(
    r"\s+at\s+([\w.$]+)\(([^)]*?):(\d+)\)"
)


def _cross_service_timeline(logs: dict, apps: list[str]) -> str | None:
    """跨服务日志时间聚类：自适应窗口 + 方向推断。"""

    if len(apps) <= 1:
        return None

    entries = list(logs.get("entries") or [])
    for block in (logs.get("by_app") or {}).values():
        for e in block.get("entries") or []:
            app = e.get("app")
            if app:
                entries.append({"app": app, **{k: v for k, v in e.items() if k != "app"}})

    if len(entries) < 5:
        return None

    # 只分析含异常/错误的条目
    error_entries: list[dict] = []
    for e in entries:
        if re.search(r"\bERROR\b|Exception|异常|失败", (e.get("message") or ""), re.I):
            ts_str = (e.get("timestamp") or "").strip()
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            error_entries.append({**e, "_parsed_ts": ts})

    if len(error_entries) < 2:
        return None

    error_entries.sort(key=lambda x: x["_parsed_ts"])

    # 自适应窗口：计算相邻异常间隔中位数
    intervals: list[float] = []
    for i in range(1, len(error_entries)):
        delta = (error_entries[i]["_parsed_ts"] - error_entries[i - 1]["_parsed_ts"]).total_seconds()
        if delta > 0:
            intervals.append(delta)
    if intervals:
        intervals.sort()
        median_interval = intervals[len(intervals) // 2]
    else:
        median_interval = 5.0
    window_sec = max(5.0, min(median_interval * 3, 300.0))

    # 自适应窗口聚类
    clusters: list[dict] = []
    current_cluster: dict | None = None

    for e in error_entries:
        ts = e["_parsed_ts"]
        app = (e.get("app") or "?").lower()
        exc = None
        exc_m = _EXCEPTION_CLASS_RE.search(e.get("message") or "")
        if exc_m:
            exc = exc_m.group(1)

        if current_cluster is None:
            current_cluster = {
                "start": ts, "end": ts,
                "apps": {app}, "count": 1,
                "exceptions": [exc] if exc else [],
                "first_app": app,
                "app_timestamps": {app: ts},
            }
            continue

        delta = (ts - current_cluster["end"]).total_seconds()
        if delta <= window_sec:
            current_cluster["end"] = ts
            current_cluster["apps"].add(app)
            current_cluster["count"] += 1
            if exc:
                current_cluster["exceptions"].append(exc)
            if app not in current_cluster["app_timestamps"]:
                current_cluster["app_timestamps"][app] = ts
        else:
            clusters.append(current_cluster)
            current_cluster = {
                "start": ts, "end": ts,
                "apps": {app}, "count": 1,
                "exceptions": [exc] if exc else [],
                "first_app": app,
                "app_timestamps": {app: ts},
            }

    if current_cluster:
        clusters.append(current_cluster)

    # 只保留多应用参与的聚类
    multi_app = [c for c in clusters if len(c["apps"]) >= 2]
    if not multi_app:
        return None

    lines = ["### 跨服务时序", ""]
    lines.append(
        f"在 {len(multi_app)} 个时间窗口中发现 {len(apps)} 个服务同时出现异常，"
        f"可能为调用链传导（自适应窗口 {window_sec:.0f}s）："
    )
    lines.append("")
    for i, c in enumerate(multi_app[:5], 1):
        ts_fmt = c["start"].strftime("%H:%M:%S")
        exc_list = list(dict.fromkeys(c["exceptions"]))[:3]
        exc_str = "、".join(exc_list) if exc_list else "—"

        # 方向推断：按时间戳排序，早→晚即为传导方向
        sorted_apps = sorted(c["app_timestamps"].items(), key=lambda x: x[1])
        if len(sorted_apps) >= 2:
            chain = " → ".join(a for a, _ in sorted_apps)
        else:
            chain = ", ".join(sorted(c["apps"]))

        lines.append(
            f"- **{ts_fmt}**：{chain} "
            f"（{c['count']} 条异常；{exc_str}）"
        )
    lines.append("")
    return "\n".join(lines)


def _analyze_query_result(
    q: dict,
    *,
    expectations: list[dict] | None = None,
    problem_raw: str = "",
) -> str:
    if q.get("error"):
        return f"执行失败：{q['error']}"
    rows = q.get("rows")
    cnt = q.get("count")
    if cnt is None:
        cnt = len(rows) if isinstance(rows, list) else None
    if cnt == 0 or rows == []:
        # 提供替代查询建议
        hint = ""
        cols = q.get("available_columns") or []
        if cols:
            hint = f"（可用列：{', '.join(cols[:8])}）"
        return f"结果为空（0 行）→ 与「缺数据」假设相符时可作佐证{hint}"
    if not isinstance(rows, list) or not rows:
        return f"返回 {cnt} 行"
    row0 = rows[0] if isinstance(rows[0], dict) else {}
    # 通用摘要：展示所有非空列（排除通用管理字段）
    _skip = {"id", "create_time", "created_at", "update_time", "updated_at",
             "create_by", "update_by", "creator", "updater", "is_deleted",
             "deleted", "version", "revision", "remark", "remarks"}
    bits: list[str] = [f"命中 {cnt} 行"]

    # 期望值高亮：同表期望列的命中值强制展示，并打 ✅/⚠ 差异标记
    highlight: dict[str, str] = {}
    sql_lower = (q.get("sql") or "").lower()
    for e in expectations or []:
        col = e.get("column") or ""
        if not col or col not in row0:
            continue
        tbl = e.get("table") or ""
        if q.get("probe_table") != tbl and tbl and tbl not in sql_lower:
            continue
        actual = str(row0.get(col) if row0.get(col) is not None else "")
        expected = str(e.get("expected") or e.get("value") or "")
        if actual == expected:
            highlight[col] = f"{col}={actual}（✅ 符合期望）"
        else:
            highlight[col] = f"{col}={actual}（⚠ 不符期望，期望{expected}）"
    # 现象关联列：现象描述中提及的行内列名优先展示
    phen = _norm_compact(problem_raw or "")
    for col in row0:
        if col in phen and col not in highlight and col not in _skip and row0.get(col) is not None:
            highlight[col] = f"{col}={row0[col]}（现象相关）"
    for col in highlight:
        bits.append(highlight[col])
    shown = len(highlight)
    for k, v in row0.items():
        if k in _skip or k in highlight or v is None:
            continue
        if shown < 6:
            bits.append(f"{k}={v}")
            shown += 1
    # 标注 NULL 列（潜在数据缺失信号）
    nullish = [
        k for k, v in row0.items()
        if (v is None or str(v).strip() == "") and k not in _skip
    ]
    if nullish:
        bits.append(f"⚠ 列为空：{'/'.join(nullish[:4])}")
    return "；".join(bits)


def _norm_compact(text: str) -> str:
    return re.sub(r"[_\s:：=，,。．、（）()\-]", "", (text or "").lower())


def _evidence_sufficiency_score(evidence: dict) -> dict:
    """评估证据充分性：0-100 分。维度：日志覆盖/DB命中/代码命中/Nacos/跨服务覆盖。"""
    ctx = evidence.get("context") or {}
    logs = evidence.get("logs") or {}
    db = evidence.get("database") or {}
    code = evidence.get("code") or {}
    nacos = evidence.get("nacos") or {}
    apps = ctx.get("apps") or [ctx.get("app", "?")]
    nacos_keys = ctx.get("nacos_keys") or []

    score = 0
    gaps: list[str] = []

    # 1. 日志覆盖 (0-25)
    log_apps_with_data = 0
    for app in apps:
        block = (logs.get("by_app") or {}).get(app, {})
        if block.get("entries"):
            log_apps_with_data += 1
    log_coverage = log_apps_with_data / max(len(apps), 1)
    log_score = int(25 * log_coverage)
    score += log_score
    if log_coverage < 0.5:
        gaps.append(f"仅 {log_apps_with_data}/{len(apps)} 个服务有 ES 日志")
    if not any(
        re.search(r"\bERROR\b|Exception", e.get("message") or "", re.I)
        for e in _collect_all_entries(logs)
    ):
        gaps.append("日志中未发现 ERROR/Exception")

    # 2. DB 命中 (0-25)
    queries = db.get("queries") or []
    if db.get("skipped") and not queries:
        db_score = 0
        gaps.append("未执行 DB 查询（Agent 判断无需或未制定计划）")
    elif queries:
        queries_with_rows = sum(1 for q in queries if q.get("count", 0) > 0)
        db_score = int(25 * (queries_with_rows / max(len(queries), 1)))
        score += db_score
        if queries_with_rows == 0:
            gaps.append(f"所有 {len(queries)} 条 SQL 均返回空")
    else:
        db_score = 0
    score += db_score

    # 3. 代码命中 (0-20)
    code_hits = code.get("code_hits") or []
    code_apps = set()
    for h in code_hits:
        if h.get("app"):
            code_apps.add(h["app"])
    code_cov = len(code_apps) / max(len(apps), 1) if apps else 0
    code_score = int(20 * min(code_cov * 1.5, 1.0)) if code_hits else 0
    score += code_score
    if not code_hits:
        gaps.append("代码扫描未命中相关类")

    # 4. Nacos (0-15)
    nacos_checked = [k for k in (nacos.get("checked_keys") or []) if k]
    if nacos_keys:
        nacos_score = int(15 * (len(nacos_checked) / max(len(nacos_keys), 1)))
    elif nacos_checked:
        nacos_score = 15
    else:
        nacos_score = 5  # 未指定 nacos_keys，给基础分
    score += nacos_score

    # 5. 跨服务覆盖 (0-15)
    if len(apps) > 1:
        cross_score = int(15 * log_coverage)
    else:
        cross_score = 10  # 单应用默认 ok
    score += cross_score

    level = "高" if score >= 70 else ("中" if score >= 40 else "低")
    return {"score": min(score, 100), "level": level, "gaps": gaps}


def _collect_all_entries(logs: dict) -> list[dict]:
    entries: list[dict] = []
    for block in (logs.get("by_app") or {}).values():
        entries.extend(block.get("entries") or [])
    if not entries:
        entries = list(logs.get("entries") or [])
    return entries


def _render_report(evidence: dict) -> str:
    ctx = evidence.get("context", {})
    logs = evidence.get("logs", {})
    db = evidence.get("database", {})
    db_inf = evidence.get("db_inference") or ctx.get("db_inference") or {}
    nacos = evidence.get("nacos", {})
    code = evidence.get("code", {})
    apps = ctx.get("apps") or [ctx.get("app")]
    agent_plan = evidence.get("agent_db_plan") or db_inf.get("agent_db_plan") or {}

    lines = [
        "# 问题排查报告",
        "",
        f"- 生成时间: {evidence.get('generated_at')}",
        f"- 主应用: {ctx.get('app')} | 涉及应用: {', '.join(apps)}",
        f"- 环境: {ctx.get('env')} | 范围: {ctx.get('scope', 'primary_only')}",
        f"- 检索: `{ctx.get('query_mode') or 'trace_id'}` = `{ctx.get('query')}`",
        f"- 时间窗: `{ctx.get('time_from')}`",
        "",
        "## 1. 日志摘要",
        "",
    ]
    by_app = logs.get("by_app") or {}
    if by_app:
        parts = []
        for app in sorted(by_app.keys()):
            cnt = len(by_app[app].get("entries") or [])
            err = by_app[app].get("es_error")
            parts.append(f"{app} {cnt}条" + ("(ES异常)" if err else ""))
        lines.append("- 拉取：" + "；".join(parts))
    refetched = logs.get("refetched_apps") or []
    if refetched:
        lines.append(f"- 补拉：{', '.join(refetched)}")
    if logs.get("es_error"):
        lines.append(f"- ES：{logs['es_error']}")
    err_sum = _error_summaries(logs)
    if err_sum:
        lines.append("- 关键错误：")
        lines.extend(err_sum)
    else:
        lines.append("- 关键错误：无（或未抓到 ERROR 级日志）")

    # 时间窗口扩展提示
    if logs.get("time_window_expanded"):
        effective_window = logs.get("time_from") or ctx.get("time_from") or ""
        lines.append(f"- ⚠ 原时间窗口无结果，已自动扩大至 `{effective_window}`")

    # 跨服务时间聚类
    cross = _cross_service_timeline(logs, apps)
    if cross:
        lines.extend(["", cross])

    lines.extend(["", "## 2. 数据库佐证", ""])
    executed = list(db.get("queries") or [])
    phase = evidence.get("collect_phase") or ctx.get("collect_phase") or ""
    if phase == "logs" and not executed:
        lines.append("- 状态：日志阶段完成，**等待 Agent 写出库表计划**（`agent_db_plan.json`）后再查库。")
        lines.append("- 原则：仅当分析需要库真相佐证时才查；脚本不猜表。")
    elif not executed:
        reason = (
            (agent_plan.get("reason") if isinstance(agent_plan, dict) else None)
            or db.get("error")
            or "未执行 SQL"
        )
        lines.append(f"- 本轮未查库：{reason}")
    else:
        if isinstance(agent_plan, dict) and agent_plan.get("reason"):
            lines.append(f"- Agent 计划：{agent_plan.get('reason')}")
        lines.append("")
        for i, q in enumerate(executed, 1):
            why = (q.get("inference_reason") or "").strip() or "库表佐证"
            if "；biz_key=" in why:
                why = why.split("；biz_key=")[0].strip()
            m = re.search(r"=\s*'([^']+)'", q.get("sql") or "")
            if m and m.group(1) and m.group(1) not in why:
                why = f"{why}（键={m.group(1)}）"
            lines.append(f"### SQL {i}（{q.get('app') or '?'}）")
            lines.append(f"- **为何查**：{why[:220]}")
            lines.append("- **SQL**：")
            lines.append(f"```sql\n{(q.get('sql') or '').strip()}\n```")
            lines.append(f"- **结果分析**：{_analyze_query_result(q, expectations=ctx.get('db_expectations'), problem_raw=ctx.get('problem_raw') or '')}")
            lines.append("")

    # 证据交叉验证（仅当有足够数据时展示）
    cross_text = correlate_format_section(evidence)
    if cross_text:
        lines.extend(["", cross_text])

    # 证据充分性评估
    suff = _evidence_sufficiency_score(evidence)
    suff_bar = "█" * (suff["score"] // 10) + "░" * (10 - suff["score"] // 10)
    lines.extend([
        "",
        "### 证据充分性",
        f"评分：`[{suff_bar}]` {suff['score']}/100（{suff['level']}）",
    ])
    if suff["gaps"]:
        for g in suff["gaps"]:
            lines.append(f"- ⚠ {g}")
    if suff["score"] <= 40:
        lines.append("- ⚠ 证据可能不足，建议排查结束前补充" + (
            "（见 §5 ### 待补线索）" if phase in ("db", "all") else ""
        ))

    # 矛盾检测
    contradictions: list[str] = []
    for q in executed:
        rows = q.get("rows") or []
        sql = q.get("sql") or ""
        # 日志报 ERROR 但 DB 查询正常
        if rows and len(rows) > 0:
            err_msgs = [e.get("message", "") for e in _collect_all_entries(logs)
                       if re.search(r"\bERROR\b|Exception", e.get("message", ""), re.I)]
            if err_msgs and re.search(r"状态.*(异常|不一致|不对)", "\n".join(err_msgs), re.I):
                contradictions.append("⚠ DB 返回正常数据但日志报告状态异常 → 需人工判断是否为时序问题")
        # 日志明确提到某值但 DB 为空
        if not rows or len(rows) == 0:
            biz_mentions = re.findall(r"\b(L\d{10,}|CR\d{10,}|O\d{10,})\b", "\n".join(
                e.get("message", "") for e in _collect_all_entries(logs)
            ))
            if biz_mentions:
                contradictions.append(f"⚠ 日志含业务键（如 {biz_mentions[0]}）但 DB 查询为空 → 可能缺数据或键值不对")
    if contradictions:
        lines.extend(["", "### 矛盾发现", ""])
        for c in contradictions[:3]:
            lines.append(f"- {c}")

    nacos_checked = [k for k in (nacos.get("checked_keys") or []) if k]
    if nacos_checked:
        lines.extend(["", "## 3. Nacos", ""])
        lines.append(f"- 已查 key：{', '.join(nacos_checked)}")

    lines.extend(["", "## 4. 代码线索", ""])
    git_branches = ctx.get("git_branches") or evidence.get("git_branches") or {}
    env = ctx.get("env") or ""
    scan_apps = code_scan_apps(evidence)
    failure_block = format_branch_failure_block(git_branches, env=env, apps=scan_apps)
    if failure_block:
        lines.extend(failure_block)
    else:
        branch_note = format_branch_summary(git_branches)
        if branch_note:
            lines.append(f"- 分支：{branch_note}")
    hit_names: list[str] = []
    for block in (code.get("code_hits") or [])[:8]:
        app = block.get("app") or "?"
        kw = (block.get("keyword") or "").strip()
        if not kw:
            continue
        simple = kw.rsplit(".", 1)[-1] if "." in kw else kw
        changed = " ⚠最近变更" if block.get("recently_changed") else ""
        hit_names.append(f"{app}.{simple}{changed}")
    if hit_names:
        lines.append("- 相关：" + "、".join(dict.fromkeys(hit_names)))
    else:
        lines.append("- 相关：无额外命中（或未扫描）")

    # 框架类
    fw_classes = [c for c in (code.get("classes_from_logs") or []) if c.startswith("[F]")]
    if fw_classes:
        lines.append("- 框架层：" + "、".join(fw_classes[:5]))

    # Mapper XML 命中
    mapper_hits = code.get("mapper_xml_hits") or []
    if mapper_hits:
        mapper_files = list(dict.fromkeys(
            h.get("file", "").split("/")[-1] for h in mapper_hits[:5]
        ))
        lines.append(f"- Mapper XML：{', '.join(mapper_files)}")

    # 调用者反向搜索
    callers = code.get("callers") or []
    if callers:
        for c in callers[:3]:
            kw = c.get("keyword", "?")
            cs = c.get("callers") or []
            caller_files = list(dict.fromkeys(
                cl.get("file", "").split("/")[-1] for cl in cs[:3]
            ))
            if caller_files:
                lines.append(f"- `{kw}` 调用者：{', '.join(caller_files)}")

    # Git 变更提示
    changed_hits = [b for b in (code.get("code_hits") or []) if b.get("recently_changed")]
    if changed_hits:
        lines.append(f"- ⚠ {len(changed_hits)} 个命中类最近 7 天有变更（疑为引入点）")

    lines.extend([
        "",
        "## 5. 根因分析（Agent 填写）",
        "",
    ])
    hyps = generate_hypotheses(evidence)
    hyp_lines = format_hypotheses_markdown(hyps)
    if hyp_lines:
        lines.extend(hyp_lines)
        lines.append("")
    conf = max(int(suff.get("score") or 50), 40)
    lines.extend([
        "### 5.1 排查结果",
        "**根因**：（必填）简明描述根因，含调用链（如 lps→goa→ams）；可先采纳上方候选假设再改写",
        f"**置信度**：[████████░░] {conf}%（证据充分性评分 {suff.get('score', '?')}/100，可作起点）",
        "**证据链**：",
        "- ES 日志：[引用 §1 关键 ERROR]",
        "- DB 佐证：[引用 §2 命中的行/空结果]",
        "- 代码定位：[引用 §4 命中的类/方法]",
        "",
        "### 5.2 排除的假设",
        "- ❌ 假设 A — 排除依据（如：DB 查询确认该表数据正常）",
        "- ❌ 假设 B — 排除依据",
        "（若无需排除项，写「无」）",
        "",
        "### 5.3 待补线索",
        "（未能定位时必填；已定位可写「无」）",
        "- 需补充什么 / 为什么需要",
        "",
        "### 5.4 修复建议",
        "**代码修复**：（如有）",
        "**配置修复**：（如有）",
        "**数据修复**：（如有）",
        "**预防措施**：监控 / 告警 / 校验",
        "",
        "### 5.5 关联排查服务",
        "（可选：仅写已补拉的服务，每行一个）",
    ])
    return "\n".join(lines)


def _collect_logs_phase(repo_root: Path, context: dict, run_dir: Path) -> dict:
    ensure_collect_deps()
    primary = context["app"]
    env = context["env"]
    query = context["query"]
    query_mode = context.get("query_mode") or "trace_id"
    time_from = context.get("time_from") or default_log_time_from(query_mode)
    alert_phrases = context.get("alert_phrases") or []
    biz_key = context.get("biz_key") or ""
    scenario = context.get("scenario") or "default"
    scope = context.get("scope") or "primary_only"
    apps = context.get("apps") or resolve_apps(primary, scope, scenario)
    apply_log_profile_to_ctx(context, apps)
    if query_mode in ("biz_key", "db_probe"):
        context["log_errors_only"] = False
        context["time_from"] = time_from or default_log_time_from("biz_key")
    log_profile = resolve_log_collect_profile(context, apps)
    log_kw = collect_kwargs_from_ctx(context)
    scenarios = context.get("scenarios") or resolve_scenarios(apps, scope, scenario)
    repo_roots = context.get("repo_roots") or resolve_repo_roots(repo_root, apps)
    repo_roots = {a: Path(p) for a, p in repo_roots.items()}
    git_branches = ensure_repos_on_env_branch(repo_roots, env)
    context["git_branches"] = git_branches

    logs = collect_logs_multi(
        apps, env, query,
        mode="both",
        time_from=time_from,
        query_mode=query_mode,
        alert_phrases=alert_phrases,
        log_collect_profile=log_profile,
        primary_app=primary,
        **log_kw,
        output=run_dir / "logs.json",
    )

    messages = []
    for app in apps:
        for e in (logs.get("by_app", {}).get(app, {}).get("entries") or []):
            messages.append(e.get("message", ""))
    if not messages:
        messages = [e.get("message", "") for e in logs.get("entries", [])]

    keywords = [biz_key] if biz_key else None
    if query_mode in ("biz_key", "db_probe") and context.get("problem_raw"):
        keywords = list(dict.fromkeys([biz_key, context.get("problem_raw", "")[:80]] + (keywords or [])))
    if not keywords and query_mode == "alert":
        keywords = [p for p in alert_phrases if p][:5] or ([query] if query else None)
    # 代码扫描范围：主应用 + 本轮有 ES 命中的应用（避免 scope=all 时扫 goa 空仓）
    if log_profile == "focused" and len(apps) == 1:
        scan_apps = list(apps)
    else:
        hit_counts: dict[str, int] = {}
        for e in logs.get("entries") or []:
            a = (e.get("app") or "").strip().lower()
            if a:
                hit_counts[a] = hit_counts.get(a, 0) + 1
        for a, block in (logs.get("by_app") or {}).items():
            n = block.get("hit_count") or block.get("count") or len(block.get("entries") or [])
            if isinstance(n, int) and n > 0:
                hit_counts[a] = max(hit_counts.get(a, 0), n)
        scan_apps = []
        if primary:
            scan_apps.append(primary)
        for a in apps:
            if a != primary and hit_counts.get(a, 0) > 0:
                scan_apps.append(a)
        if not scan_apps:
            scan_apps = list(apps[:1]) if apps else []
    scan_roots = {a: Path(repo_roots[a]) for a in scan_apps if a in repo_roots}
    code = scan_code_multi(
        scan_roots,
        log_messages=messages,
        keywords=keywords,
        output=run_dir / "code.json",
    )

    code_classes: list[str] = []
    for block in code.get("code_hits") or []:
        code_classes.append(block.get("keyword") or "")
    code_classes.extend(code.get("classes_from_logs") or [])

    db_inference = infer_db_context(
        logs,
        user_biz_key=biz_key,
        user_scenario=scenario,
        apps=apps,
        code_classes=code_classes,
    )
    db_inference["principle"] = (
        "Agent 分析日志后写出 agent_db_plan.json，脚本只执行该计划；"
        "禁止脚本按业务场景写死猜表"
    )
    db_inference["sql_investigation_triggered"] = False
    db_inference["agent_plan_pending"] = True
    write_json(run_dir / "db_inference.json", db_inference)

    db = {
        "apps": [],
        "investigation_apps": apps,
        "db_apps": [],
        "env": env,
        "biz_key": db_inference.get("biz_key") or biz_key,
        "db_host": None,
        "by_app": {},
        "queries": [],
        "db_probes": [],
        "skipped": True,
        "error": "等待 Agent 库表计划（agent_db_plan.json）",
        "source": "pending_agent",
    }
    write_json(run_dir / "database.json", db)

    nacos_keys = [k.strip() for k in (context.get("nacos_keys") or []) if k and str(k).strip()]
    if nacos_keys:
        nacos = collect_nacos_multi(
            apps, env, repo_roots=repo_roots, keys=nacos_keys, output=run_dir / "nacos.json",
        )
    else:
        nacos = {
            "apps": apps, "env": env, "mode": "skipped", "checked_keys": [],
            "matched_keys": [], "by_app": {}, "configs": [], "error": None,
            "skip_reason": "未指定 nacos_keys，跳过 Nacos 采集",
        }
        write_json(run_dir / "nacos.json", nacos)

    full_ctx = {
        **context,
        "apps": apps,
        "scenarios": scenarios,
        "scope": scope,
        "repo_roots": {k: str(v) for k, v in repo_roots.items()},
        "biz_key": db_inference.get("biz_key") or biz_key,
        "scenario": db_inference.get("scenario") or scenario,
        "biz_key_source": db_inference.get("biz_key_source") or ("user" if biz_key else ""),
        "scenario_source": db_inference.get("scenario_source") or ("user" if scenario != "default" else "default"),
        "db_inference": db_inference,
        "nacos_keys": nacos_keys,
        "git_branches": git_branches,
        "collect_phase": "logs",
        "db_probes": list(context.get("db_probes") or []),
        "db_expectations": list(context.get("db_expectations") or []),
    }
    evidence = {
        "run_id": run_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "collect_phase": "logs",
        "context": full_ctx,
        "git_branches": git_branches,
        "logs": logs,
        "database": db,
        "db_inference": db_inference,
        "nacos": nacos,
        "code": code,
    }
    write_json(run_dir / "git_branches.json", git_branches)
    write_json(run_dir / "evidence.json", slim_evidence(evidence))
    write_json(run_dir / "context.json", full_ctx)
    write_suggest_plan(run_dir, evidence, ctx=full_ctx)
    report = _render_report(evidence)
    (run_dir / "investigation-report.md").write_text(report, encoding="utf-8")
    (run_dir / "agent_db_plan.HELP.md").write_text(
        agent_plan_help_text(run_dir, evidence=evidence, ctx=full_ctx), encoding="utf-8"
    )
    return evidence


def _collect_db_phase(repo_root: Path, context: dict, run_dir: Path) -> dict:
    ensure_collect_deps()
    evidence = read_json(run_dir / "evidence.json", {})
    if not evidence:
        raise SystemExit("请先执行 --phase logs")
    ctx = {**(evidence.get("context") or {}), **context}
    env = ctx["env"]
    primary = ctx["app"]
    apps = list(ctx.get("apps") or [primary])
    # Agent 计划可能要求关联服务仓（如 form 只选了 lcs，但要查 ams）
    repo_roots = {a: Path(p) for a, p in (ctx.get("repo_roots") or {}).items()}
    extra_roots = resolve_repo_roots(repo_root, ["lcs", "lps", "ams", "goa"])
    for a, p in extra_roots.items():
        repo_roots.setdefault(a, Path(p))

    agent_raw = load_agent_db_plan(run_dir)
    if agent_raw is None and ctx.get("query_mode") not in ("biz_key", "db_probe") and not ctx.get("db_probes"):
        # 允许空计划：写成无查库
        from lib.agent_db_plan import empty_plan, save_agent_db_plan
        save_agent_db_plan(run_dir, empty_plan(reason="未找到 agent_db_plan.json，视为无需查库"))
        agent_raw = load_agent_db_plan(run_dir)

    agent_queries, plan_meta = validate_and_normalize_plan(
        agent_raw, env=env, investigation_apps=apps + list(repo_roots.keys()),
    )
    mapper_by_app = queries_as_mapper_tuples(agent_queries)
    db_apps = sorted(mapper_by_app.keys())

    messages = []
    logs = evidence.get("logs") or {}
    for app in apps:
        for e in (logs.get("by_app", {}).get(app, {}).get("entries") or []):
            messages.append(e.get("message", ""))

    db_inference = evidence.get("db_inference") or {}
    db_inference["agent_db_plan"] = agent_raw
    db_inference["agent_plan_meta"] = plan_meta
    db_inference["agent_plan_pending"] = False
    db_inference["verification_claims"] = agent_raw.get("queries") if isinstance(agent_raw, dict) else []
    db_inference["sql_investigation_triggered"] = bool(agent_queries) or bool(ctx.get("db_probes"))
    db_inference["principle"] = "Agent 写出 agent_db_plan.json → 脚本校验后只读执行"

    db_probe_hints = list(ctx.get("db_probes") or [])
    db_expectations = list(ctx.get("db_expectations") or [])
    probes_to_run = db_probe_hints
    skipped_probes: list[dict] = []
    selection_note = ""
    query_mode = ctx.get("query_mode") or "trace_id"
    if db_probe_hints and query_mode in ("trace_id", "alert"):
        probes_to_run, skipped_probes, selection_note = select_probes_for_log_context(
            db_probe_hints, messages, db_inference, (evidence.get("code") or {}).get("code_hits") or [],
        )

    # 确保 probes 涉及的 app 也在 db_apps
    for p in probes_to_run:
        sch = (p.get("schema") or "").strip().lower()
        if sch and sch not in db_apps:
            db_apps.append(sch)

    if not db_apps and not probes_to_run:
        db = {
            "apps": [],
            "investigation_apps": apps,
            "db_apps": [],
            "env": env,
            "biz_key": ctx.get("biz_key") or "",
            "db_host": None,
            "by_app": {},
            "queries": [],
            "db_probes": [],
            "db_probes_skipped": skipped_probes,
            "skipped": True,
            "error": plan_meta.get("reason") or "Agent 判断无需查库",
            "source": "agent",
            "agent_plan_meta": plan_meta,
        }
        if plan_meta.get("errors"):
            db["plan_errors"] = plan_meta["errors"]
    else:
        effective_biz = ctx.get("biz_key") or ""
        db = collect_db_multi(
            db_apps or [primary],
            env,
            effective_biz,
            biz_keys={a: effective_biz for a in (db_apps or [primary])},
            biz_key_kinds={a: "loan_no" for a in (db_apps or [primary])},
            repo_roots=repo_roots,
            mapper_queries_by_app=mapper_by_app,
            db_probes=probes_to_run,
            db_expectations=db_expectations,
            db_probe_hints=db_probe_hints,
            db_probes_skipped=skipped_probes,
            db_probe_selection_note=selection_note,
            mapper_queries_skipped=[],
            db_apps_out_of_scope=[],
            investigation_apps=apps,
            output=run_dir / "database.json",
        )
        db["source"] = "agent_plan"
        db["agent_plan_meta"] = plan_meta
        # 给每条 agent 查询补上 app 字段（collect 可能已有）
        for q in db.get("queries") or []:
            if not q.get("app") and q.get("file", "").startswith("agent:"):
                # 从 SQL 推断
                m = re.search(r"FROM\s+`?([a-zA-Z0-9_]+)`?\.", q.get("sql") or "", re.I)
                if m:
                    q["app"] = m.group(1).lower()

    write_json(run_dir / "database.json", db)
    write_json(run_dir / "db_inference.json", db_inference)

    ctx["collect_phase"] = "db"
    evidence["collect_phase"] = "db"
    evidence["database"] = db
    evidence["db_inference"] = db_inference
    evidence["agent_db_plan"] = agent_raw
    evidence["context"] = ctx
    evidence["generated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(run_dir / "evidence.json", slim_evidence(evidence))
    write_json(run_dir / "context.json", ctx)
    (run_dir / "investigation-report.md").write_text(_render_report(evidence), encoding="utf-8")
    return evidence


def run_collection(
    repo_root: Path,
    context: dict,
    run_dir: Path,
    *,
    phase: str = "all",
) -> dict:
    phase = (phase or "all").strip().lower()
    if phase == "logs":
        return _collect_logs_phase(repo_root, context, run_dir)
    if phase == "db":
        return _collect_db_phase(repo_root, context, run_dir)
    # all：先 logs；若已有 plan 或用户表查模式再 db
    evidence = _collect_logs_phase(repo_root, context, run_dir)
    if load_agent_db_plan(run_dir) or context.get("db_probes") or context.get("query_mode") in ("db_probe", "biz_key"):
        evidence = _collect_db_phase(repo_root, context, run_dir)
    return evidence


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="执行证据采集（支持多应用）")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--phase",
        choices=("logs", "db", "all"),
        default="logs",
        help="logs=仅日志/代码；db=执行 Agent 库表计划；all=logs 后若有计划则 db",
    )
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    ctx = read_json(run_dir / "context.json")
    if not ctx:
        ctx = read_json(run_dir / "active_workflow.json", {}).get("context", {})
    if not ctx:
        raise SystemExit("run-dir 缺少 context.json")
    evidence = run_collection(Path(args.repo_root).resolve(), ctx, run_dir, phase=args.phase)
    print(json.dumps({
        "evidence": str(run_dir / "evidence.json"),
        "phase": args.phase,
        "collect_phase": evidence.get("collect_phase"),
        "apps": evidence["context"].get("apps"),
        "kibana_urls": evidence.get("logs", {}).get("kibana_urls"),
        "db_queries": len((evidence.get("database") or {}).get("queries") or []),
        "agent_plan": str(run_dir / "agent_db_plan.json"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
