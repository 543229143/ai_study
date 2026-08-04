"""证据交叉关联引擎：将日志/DB/代码/Nacos 四个独立维度的证据串联分析。

核心能力：
- Log ↔ DB 交叉验证（日志中声称的值 vs DB 实际值）
- Exception ↔ Code 精确定位（堆栈中的 at File.java:line → 代码命中）
- Config ↔ Error 关联（Nacos 配置变更 vs 错误首次出现时间）
- 调用链重建（跨服务 trace 日志拼成完整调用路径）

所有函数均为纯函数，输入 dict/list，输出 dict/list。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

_EXCEPTION_CLASS_RE = re.compile(r"([\w.$]+(?:Exception|Error))")
_TRACE_LOC_RE = re.compile(r"\s+at\s+([\w.$]+)\(([^)]*?):(\d+)\)")
# trace/audit 日志中的服务名提取：[timestamp|service_name] 或 ] - SERVICENAME|...
_TRACE_SERVICE_RE = re.compile(r"\[[^\]|]+\|([a-zA-Z][a-zA-Z0-9_-]*)\]")
_AUDIT_SERVICE_RE = re.compile(r"\]\s*-\s*([A-Z]{2,})\|NA\|NA\|")

# 通用字段（不展示在结果摘要中）
_SKIP_COLUMNS = frozenset({
    "id", "create_time", "created_at", "update_time", "updated_at",
    "create_by", "update_by", "creator", "updater", "is_deleted",
    "deleted", "version", "revision", "remark", "remarks",
})


def _collect_log_messages(logs: dict) -> list[dict]:
    """展平日志 entries 为统一列表。"""
    entries: list[dict] = []
    for block in (logs.get("by_app") or {}).values():
        for e in block.get("entries") or []:
            entries.append(e)
    if not entries:
        entries = list(logs.get("entries") or [])
    return entries


def _extract_biz_values_from_messages(messages: list[str]) -> dict[str, set[str]]:
    """从日志 message 中提取可能的值（loan_no, order_no 等），返回 {kind: {values}}。"""
    patterns: dict[str, re.Pattern] = {
        "loan_no": re.compile(r"\b(L\d{10,}|LN[a-f0-9]{10,})\b", re.I),
        "order_no": re.compile(r"\b(O\d{10,})\b", re.I),
        "apply_no": re.compile(r"\b(CR\d{10,})\b", re.I),
    }
    found: dict[str, set[str]] = {}
    for msg in messages:
        for kind, pat in patterns.items():
            for m in pat.finditer(msg or ""):
                found.setdefault(kind, set()).add(m.group(1))
    return found


def correlate_log_db(logs: dict, db: dict) -> list[dict]:
    """交叉验证：日志中提取的 biz_key/状态 vs DB 查询实际结果。

    返回 [{type, log_value, db_value, table, column, detail}]
    """
    findings: list[dict] = []
    entries = _collect_log_messages(logs)
    messages = [e.get("message") or "" for e in entries]
    log_values = _extract_biz_values_from_messages(messages)

    queries = db.get("queries") or []
    if not queries or not log_values:
        return findings

    for q in queries:
        rows = q.get("rows") or []
        sql = (q.get("sql") or "").lower()
        # 从 SQL 推断被查的表/列
        tbl_m = re.search(r"from\s+`?(\w+)`?\s*\.\s*`?(\w+)`?", sql, re.I)
        table = f"{tbl_m.group(1)}.{tbl_m.group(2)}" if tbl_m else "?"
        where_col = ""
        where_m = re.search(r"where\s+`?(\w+)`?\s*=", sql, re.I)
        if where_m:
            where_col = where_m.group(1)

        # 关键场景：DB 0 行 → 数据缺失
        if not rows or (isinstance(rows, list) and len(rows) == 0):
            biz_in_log = any(
                any(v in msg for v in vals)
                for msg in messages
                for vals in log_values.values()
            ) if log_values else False
            findings.append({
                "type": "missing",
                "log_value": "日志中有业务键引用" if biz_in_log else "—",
                "db_value": "0 行",
                "table": table,
                "column": where_col or "?",
                "detail": f"DB {table} 查询返回 0 行 → 可能数据缺失，与「缺数据」假设一致",
            })
            continue

        if not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue
            for key, val in row.items():
                if key in _SKIP_COLUMNS or val is None:
                    continue
                val_str = str(val)
                # 与日志提取值对比
                for kind, vals in log_values.items():
                    if val_str in vals:
                        findings.append({
                            "type": "match",
                            "log_value": val_str,
                            "db_value": val_str,
                            "table": table,
                            "column": key,
                            "detail": f"DB {table}.{key}={val_str} 与日志 {kind} 一致",
                        })
                # 状态字段：日志可能声称不同的状态
                if key in ("status", "state", "loan_status"):
                    # 查日志中是否提到异常状态
                    status_patterns = [
                        rf"(?:状态|{key})[^。]*(?:异常|不一致|不对|应为)",
                        rf"(?:expected|expect)\w*\s+['\"]?({re.escape(val_str)})",
                    ]
                    for pat in status_patterns:
                        for msg in messages:
                            if re.search(pat, msg, re.I):
                                findings.append({
                                    "type": "mismatch" if "异常" in msg or "不对" in msg else "unchecked",
                                    "log_value": "异常状态" if "异常" in msg else msg[:80],
                                    "db_value": val_str,
                                    "table": table,
                                    "column": key,
                                    "detail": f"日志指出状态问题，DB 实际 {key}={val_str}",
                                })
                                break

    return findings[:10]


def correlate_exception_code(logs: dict, code: dict) -> list[dict]:
    """从堆栈 at com.xxx.Method(File.java:42) 提取文件/行号，与代码扫描结果精确匹配。

    返回 [{exception_class, source_file, line_number, code_hit, confidence}]
    """
    findings: list[dict] = []
    entries = _collect_log_messages(logs)
    code_hits = code.get("code_hits") or []

    # 构建代码命中索引 {keyword: [hit, ...]}
    hit_index: dict[str, list[dict]] = {}
    for h in code_hits:
        kw = (h.get("keyword") or "").lower()
        hit_index.setdefault(kw, []).append(h)
        # 也按简化类名索引
        simple = kw.rsplit(".", 1)[-1].lower()
        if simple != kw:
            hit_index.setdefault(simple, []).append(h)

    seen: set[str] = set()
    for entry in entries[:50]:
        msg = entry.get("message") or ""

        # 提取堆栈帧
        for loc_m in _TRACE_LOC_RE.finditer(msg):
            cls_method = loc_m.group(1)  # e.g. "com.xxx.PilotHomeServiceImpl.sort"
            file_path = loc_m.group(2)
            line_no = loc_m.group(3)

            # 拆分类名和方法名：rsplit(".", 1) → ["com.xxx.PilotHomeServiceImpl", "sort"]
            parts = cls_method.rsplit(".", 1)
            full_class = parts[0] if len(parts) > 1 else cls_method
            method_name = parts[-1] if len(parts) > 1 else ""
            simple = full_class.rsplit(".", 1)[-1].lower()  # "pilothomeserviceimpl"

            # 匹配代码命中：按全限定名 + 简化类名索引
            key = full_class.lower()
            matched = hit_index.get(key, []) + hit_index.get(simple, [])

            if matched:
                dedup_key = f"{full_class}:{file_path}:{line_no}"
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                findings.append({
                    "exception_class": full_class,
                    "method": method_name,
                    "source_file": file_path,
                    "line_number": int(line_no) if line_no.isdigit() else 0,
                    "code_hit": matched[0].get("keyword") or full_class,
                    "code_file": matched[0].get("class_definitions", [{}])[0].get("file", "") if matched[0].get("class_definitions") else "",
                    "confidence": "direct" if simple in (matched[0].get("keyword") or "").lower() else "partial",
                })
            elif full_class and full_class not in seen:
                # 跳过 JDK 框架帧，减少噪音
                if full_class.startswith(("java.", "javax.", "jdk.", "sun.", "jdk.internal.")):
                    continue
                seen.add(full_class)
                findings.append({
                    "exception_class": full_class,
                    "method": method_name,
                    "source_file": file_path,
                    "line_number": int(line_no) if line_no.isdigit() else 0,
                    "code_hit": None,
                    "code_file": "",
                    "confidence": "unmatched",
                })

    return findings[:8]


def correlate_config_error(logs: dict, nacos: dict) -> list[dict]:
    """若日志异常提及配置 key → 从 Nacos 采集结果匹配，标注配置变更风险。

    返回 [{key, nacos_value, log_reference, time_correlation}]
    """
    findings: list[dict] = []
    entries = _collect_log_messages(logs)
    nacos_configs = nacos.get("configs") or []

    # Nacos 实际产出：configs[].key_values 为 [{key, value, ...}, ...]；亦可 dict
    nacos_kv: dict[str, str] = {}

    def _ingest_key_values(raw: Any) -> None:
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k:
                    nacos_kv[str(k).lower()] = str(v)
            return
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                k = item.get("key")
                if k:
                    nacos_kv[str(k).lower()] = str(item.get("value") or "")

    def _ingest_matched_keys(keys: Any, placeholder: str) -> None:
        for k in keys or []:
            k_lower = str(k).lower()
            if k_lower and k_lower not in nacos_kv:
                nacos_kv[k_lower] = placeholder

    for cfg in nacos_configs:
        _ingest_key_values(cfg.get("key_values"))
        _ingest_matched_keys(cfg.get("matched_keys"), "（已匹配，值见 excerpt）")
    _ingest_matched_keys(nacos.get("matched_keys"), "（已匹配，值见 excerpt）")
    for app_data in (nacos.get("by_app") or {}).values():
        for cfg in app_data.get("configs") or []:
            _ingest_key_values(cfg.get("key_values"))
            _ingest_matched_keys(cfg.get("matched_keys"), "（匹配值见 excerpt）")
        _ingest_matched_keys(app_data.get("matched_keys"), "（匹配值见 excerpt）")

    # 常见配置引用模式
    config_ref = re.compile(
        r"(?:property|config|配置|key)\s*[:：=]?\s*['\"]?([a-zA-Z][\w.]*(?:\.[a-zA-Z][\w.]*)+)['\"]?",
        re.I,
    )

    for entry in entries[:30]:
        msg = entry.get("message") or ""
        for m in config_ref.finditer(msg):
            candidate = m.group(1).lower()
            if candidate in nacos_kv:
                findings.append({
                    "key": candidate,
                    "nacos_value": nacos_kv.get(candidate, "")[:100],
                    "log_reference": msg[:120],
                    "time_correlation": "unknown",  # Nacos 变更时间不可得时默认
                })

    # 标注最近错误时间 → Nacos 配置可能关联
    if findings:
        # 取最早异常时间
        timestamps: list[datetime] = []
        for e in entries:
            ts_str = (e.get("timestamp") or "").strip()
            if not ts_str:
                continue
            try:
                timestamps.append(datetime.fromisoformat(ts_str.replace("Z", "+00:00")))
            except (ValueError, TypeError):
                pass
        if timestamps:
            first_error = min(timestamps).strftime("%H:%M:%S")
            for f in findings:
                f["first_error_time"] = first_error
                f["time_correlation"] = f"错误首次出现 {first_error}（需人工比对 Nacos 变更历史）"

    return findings[:8]


def rebuild_call_chain(logs: dict) -> list[dict]:
    """从 trace/audit 日志重建跨服务调用链。只使用规范应用名，避免 lps-service/lps 重复。

    返回 [{from, to, timestamp, latency_ms, source}]
    """
    entries = _collect_log_messages(logs)
    if len(entries) < 2:
        return []

    # 服务名规范化为应用名（去 -service 后缀，去重）
    def _canonical(name: str) -> str:
        n = (name or "").strip().lower()
        for prefix in ("lcs", "lps", "goa", "ams"):
            if n == prefix or n == f"{prefix}-service" or n.startswith(f"{prefix}-service"):
                return prefix
        return n

    # 提取每个 entry 的 (timestamp, canonical_service)
    nodes: list[tuple[datetime, str]] = []
    for e in entries:
        msg = e.get("message") or ""
        ts_str = (e.get("timestamp") or "").strip()
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        services: set[str] = set()
        for m in _TRACE_SERVICE_RE.finditer(msg):
            svc = _canonical(m.group(1))
            if svc:
                services.add(svc)
        for m in _AUDIT_SERVICE_RE.finditer(msg):
            svc = _canonical(m.group(1))
            if svc:
                services.add(svc)
        # 从 container/app 补充
        container = _canonical(e.get("container") or e.get("app") or "")
        if container:
            services.add(container)

        for svc in services:
            nodes.append((ts, svc))

    if len(nodes) < 2:
        return []

    # 按时序排列 + 相邻去重（避免 A→A 自环）
    nodes.sort(key=lambda x: x[0])
    deduped: list[tuple[datetime, str]] = []
    for ts, svc in nodes:
        if not deduped or deduped[-1][1] != svc:
            deduped.append((ts, svc))

    # 仅当相邻服务不同时才建边（同 trace 内的时间邻近 ≈ 调用关系）
    edges: list[dict] = []
    for i in range(len(deduped) - 1):
        t1, s1 = deduped[i]
        t2, s2 = deduped[i + 1]
        latency = int((t2 - t1).total_seconds() * 1000)
        # 过滤明显不合理的长延迟（> 5min 且不是同 trace）
        if latency > 300000:
            continue
        edges.append({
            "from": s1,
            "to": s2,
            "timestamp": t2.isoformat(),
            "latency_ms": latency,
            "source": "trace_reconstruction",
        })

    return edges[:10]


def build_evidence_matrix(evidence: dict) -> dict:
    """生成证据覆盖矩阵：{app: {logs, db, code, nacos}, cross_correlations: [...]}"""
    ctx = evidence.get("context") or {}
    logs = evidence.get("logs") or {}
    db = evidence.get("database") or {}
    code = evidence.get("code") or {}
    nacos = evidence.get("nacos") or {}
    apps = ctx.get("apps") or [ctx.get("app", "?")]

    matrix: dict[str, dict] = {}
    for app in apps:
        app_l = app.lower()
        log_block = (logs.get("by_app") or {}).get(app_l, {})
        db_block = (db.get("by_app") or {}).get(app_l, {})
        code_block = (code.get("by_app") or {}).get(app_l, {})
        nacos_block = (nacos.get("by_app") or {}).get(app_l, {})

        matrix[app_l] = {
            "logs": "collected" if log_block.get("entries") else ("error" if log_block.get("es_error") else "missing"),
            "logs_count": len(log_block.get("entries") or []),
            "db": "collected" if db_block.get("queries") else ("skipped" if db_block.get("skipped") else "missing"),
            "db_queries": len(db_block.get("queries") or []),
            "code": "collected" if code_block.get("code_hits") else ("error" if code_block.get("error") else "missing"),
            "code_hits": len(code_block.get("code_hits") or []),
            "nacos": "collected" if nacos_block.get("configs") or nacos_block.get("checked_keys") else "missing",
        }

    correlations: dict[str, int] = {
        "log_db": len(correlate_log_db(logs, db)),
        "exception_code": len(correlate_exception_code(logs, code)),
        "config_error": len(correlate_config_error(logs, nacos)),
        "call_chain": len(rebuild_call_chain(logs)),
    }

    return {"by_app": matrix, "cross_correlations": correlations}


def format_cross_section(evidence: dict) -> str:
    """生成报告的「证据交叉验证」节。内部缓存一次计算，避免 build_evidence_matrix 重复算。"""
    # 一次计算全部关联结果，共享给 section
    logs = evidence.get("logs") or {}
    db = evidence.get("database") or {}
    code = evidence.get("code") or {}
    nacos = evidence.get("nacos") or {}

    log_db = correlate_log_db(logs, db)
    exc_code = correlate_exception_code(logs, code)
    config_err = correlate_config_error(logs, nacos)
    chain = rebuild_call_chain(logs)

    # 顺便产出 evidence matrix（避免 build_evidence_matrix 再算一轮）
    correlations = {
        "log_db": len(log_db),
        "exception_code": len(exc_code),
        "config_error": len(config_err),
        "call_chain": len(chain),
    }

    lines: list[str] = []
    has_content = False

    if log_db:
        has_content = True
        lines.extend(["### 证据交叉验证", ""])
        lines.append("**Log ↔ DB**：")
        for f in log_db[:3]:
            icon = {
                "match": "✅",
                "mismatch": "⚠️",
                "missing": "⚠",
                "unchecked": "❓",
            }.get(f.get("type", ""), "•")
            lines.append(f"- {icon} {f.get('detail', '')}")
        lines.append("")

    if exc_code:
        has_content = True
        if not lines:
            lines.extend(["### 证据交叉验证", ""])
        lines.append("**Exception ↔ Code**：")
        for f in exc_code[:3]:
            if f.get("code_hit"):
                lines.append(
                    f"- 🎯 `{f['exception_class']}` → "
                    f"`{f['source_file']}:{f['line_number']}`（{f['confidence']}）"
                )
            else:
                lines.append(
                    f"- 🔍 `{f['exception_class']}` at "
                    f"`{f['source_file']}:{f['line_number']}`（需补充代码扫描）"
                )
        lines.append("")

    if config_err:
        has_content = True
        if not lines:
            lines.extend(["### 证据交叉验证", ""])
        lines.append("**Config ↔ Error**：")
        for f in config_err[:3]:
            lines.append(f"- ⚙ `{f['key']}` → Nacos 值 `{f.get('nacos_value', '?')[:60]}`")
        lines.append("")

    if chain:
        has_content = True
        if not lines:
            lines.extend(["### 证据交叉验证", ""])
        chain_str = " → ".join(
            f"{e['from']}({e.get('latency_ms', '?')}ms)" if e.get("latency_ms") is not None else f"{e['from']}"
            for e in chain[:6]
        )
        if chain:
            chain_str += f" → {chain[-1]['to']}"
        lines.append(f"**调用链**：`{chain_str}`")
        lines.append("")

    if not has_content:
        return ""

    lines.append(f"（log↔db {correlations['log_db']} · exc↔code {correlations['exception_code']} · "
                 f"config↔error {correlations['config_error']} · 调用链 {correlations['call_chain']} 条边）")
    lines.append("")
    return "\n".join(lines)
