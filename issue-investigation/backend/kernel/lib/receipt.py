"""排查完成回执：固定排版（环境 / 服务 / 表 / 结果 + 待补线索）。

从 evidence.json 自动提取字段，合并 Agent 在报告 §5 填写的内容，
最终由 format_finished_message 输出给用户。

Java 对照：类似 ReceiptDTO Builder + Validator。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from lib.git_branch import collect_branch_align_warning, is_branch_failed

RECEIPT_FILENAME = "receipt-summary.txt"
RECEIPT_JSON_FILENAME = "receipt.json"

_PLACEHOLDER_MARKERS = (
    "请结合各应用证据",
    "Agent 填写",
    "（Agent 填写）",
    "（1-2 句话，用于完成回执自动提取）",
    "（必填：已定位根因",
    "（必填）简明描述根因",
    "（列出已排除的可能性",
    "（若无需排除项",
)

_INCONCLUSIVE_MARKERS = (
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
)

_RESULT_HEADINGS = (
    r"###\s*5\.1\s*排查结果",
    r"###\s*排查结果",
    r"###\s*现象摘要",
    r"###\s*根因(?:分析)?",
    r"###\s*原因",
    r"\*\*根因\*\*[:：]",
)

_CLUES_HEADINGS = (
    r"###\s*5\.3\s*待补线索",
    r"###\s*待补线索",
    r"###\s*补充线索",
    r"###\s*所需线索",
)

_EXCLUDED_HEADINGS = (
    r"###\s*5\.2\s*排除的假设",
    r"###\s*排除的假设",
    r"###\s*排除假设",
)

_FIX_HEADINGS = (
    r"###\s*5\.4\s*修复建议",
    r"###\s*修复建议",
)

_SERVICES_OVERRIDE_HEADINGS = (r"###\s*排查服务",)
_SERVICES_EXTRA_HEADINGS = (
    r"###\s*关联排查服务",
    r"###\s*排查服务补充",
)

_KNOWN_APPS = ("lcs", "lps", "goa", "ams")
_TRACE_PEER_RE = re.compile(r"\[[^\]|]+\|([a-zA-Z0-9_-]+)\]")
_AUDIT_PEER_RE = re.compile(r"\]\s*-\s*([A-Z]{2,})\|NA\|NA\|")


def _clean_block(text: str) -> str:
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("```"):
            continue
        if line.startswith("|") and line.endswith("|"):
            continue
        lines.append(line)
    return " ".join(lines).strip()


def _is_placeholder(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) < 6:
        return True
    return any(m in t for m in _PLACEHOLDER_MARKERS)


_CONFIDENCE_RE = re.compile(
    r"(?:置信度|confidence)[^0-9]*?(\d{1,3})\s*%", re.I,
)


def _extract_confidence(result_text: str) -> int | None:
    """从「置信度」行提取百分比。"""
    m = _CONFIDENCE_RE.search(result_text or "")
    if m:
        val = int(m.group(1))
        return max(0, min(100, val))
    return None


def _extract_excluded_hypotheses(body: str) -> list[str]:
    """提取排除的假设列表。"""
    excluded: list[str] = []
    for pat in _EXCLUDED_HEADINGS:
        m = re.search(rf"{pat}\s*\n+(.*?)(?:\n###|\n##|\Z)", body, re.DOTALL | re.IGNORECASE)
        if m:
            for line in m.group(1).splitlines():
                stripped = line.strip().lstrip("-•❌ ").strip()
                if stripped and not stripped.startswith("（") and not _is_placeholder(stripped):
                    excluded.append(stripped)
            break
    return excluded


def _section5_body(report_text: str) -> str:
    m = re.search(
        r"##\s*5\.\s*根因分析[^\n]*\n+(.*?)(?:\n##\s[^#]|\n---\s|\Z)",
        report_text,
        re.DOTALL | re.IGNORECASE,
    )
    return m.group(1) if m else ""


def _extract_root_cause_line(body: str) -> str:
    """提取 **根因**：行中的具体文本。"""
    m = re.search(r"\*\*根因\*\*\s*[:：]\s*(.+?)(?:\n|$)", body or "", re.I)
    if m:
        text = m.group(1).strip()
        if text and not _is_placeholder(text):
            return text
    return ""


def _extract_section(body: str, heading_patterns: tuple[str, ...]) -> str:
    for pat in heading_patterns:
        m = re.search(rf"{pat}\s*\n+(.*?)(?:\n###|\n##|\Z)", body, re.DOTALL | re.IGNORECASE)
        if m:
            block = _clean_block(m.group(1))
            if block and not _is_placeholder(block):
                return block
    return ""


def _tables_from_sql(sql: str) -> list[str]:
    found: list[str] = []
    for m in re.finditer(r"`?(\w+)`?\s*\.\s*`?(\w+)`?", sql or "", re.IGNORECASE):
        found.append(f"{m.group(1).lower()}.{m.group(2).lower()}")
    return found


def _collect_tables(ctx: dict, evidence: dict) -> str:
    db = evidence.get("database") or {}
    tables: list[str] = []
    seen: set[str] = set()

    for probe in ctx.get("db_probes") or []:
        t = (probe.get("table") or probe.get("raw") or "").strip()
        if t and t not in seen:
            seen.add(t)
            tables.append(t if "." in t else f"?{t}")

    for q in db.get("queries") or []:
        for tbl in _tables_from_sql(q.get("sql") or ""):
            if tbl not in seen:
                seen.add(tbl)
                tables.append(tbl)

    for app_data in (db.get("by_app") or {}).values():
        for q in app_data.get("queries") or []:
            for tbl in _tables_from_sql(q.get("sql") or ""):
                if tbl not in seen:
                    seen.add(tbl)
                    tables.append(tbl)

    if db.get("skipped"):
        reason = db.get("error") or db.get("skip_reason") or "未执行 DB 采集"
        out_scope = db.get("db_apps_out_of_scope") or []
        if out_scope:
            names = "、".join(x.get("app", "?") for x in out_scope[:4])
            reason = f"{reason}（ES 广扫含 {names} 等未连库）"
        return f"未查表（{reason}）"
    if not tables:
        return "未查表（日志/Mapper 无 biz_key 或未命中）"
    return "、".join(tables[:8]) + (" 等" if len(tables) > 8 else "")


def _collect_db_inference_note(ctx: dict, evidence: dict) -> str:
    """回执用：简要说明 SQL 是否触发及结果。"""
    db = evidence.get("database") or {}
    db_inf = evidence.get("db_inference") or ctx.get("db_inference") or {}
    if not db_inf.get("sql_investigation_triggered") and not db.get("sql_investigation_triggered"):
        if db.get("skipped") and "未触发" in (db.get("error") or ""):
            return "日志未触发 SQL 辅助，未连库"
    skipped = [
        s for s in (db.get("mapper_queries_skipped") or db_inf.get("mapper_queries_skipped") or [])
        if (s.get("label") or "").strip()
    ]
    notes: list[str] = []
    if skipped:
        notes.append(f"Mapper SQL {len(skipped)} 条绑定校验未通过")
    elif (db_inf.get("sql_binding") or {}).get("note"):
        notes.append(str(db_inf["sql_binding"]["note"]))
    elif db.get("queries"):
        notes.append(f"已执行 {len(db.get('queries') or [])} 条 SQL")
    return "；".join(notes)


def _extract_section_lines(body: str, heading_patterns: tuple[str, ...]) -> list[str]:
    for pat in heading_patterns:
        m = re.search(rf"{pat}\s*\n+(.*?)(?:\n###|\n##|\Z)", body, re.DOTALL | re.IGNORECASE)
        if not m:
            continue
        lines = [
            ln.strip().lstrip("-•").strip()
            for ln in m.group(1).splitlines()
            if ln.strip()
            and not ln.strip().startswith("#")
            and not ln.strip().startswith("（可选")
            and not ln.strip().startswith("（必填")
            and not ln.strip().startswith("（未能")
            and not ln.strip().startswith("（自动")
            and not _is_placeholder(ln.strip())
        ]
        if lines:
            return lines
    return []


def _name_to_app(name: str) -> str:
    n = (name or "").strip().lower()
    if not n:
        return ""
    for app in _KNOWN_APPS:
        if n == app or n == f"{app}-service" or n.startswith(f"{app}-service"):
            return app
    if n.endswith("-service"):
        return n[: -len("-service")]
    if n in _KNOWN_APPS:
        return n
    return n


_SERVICE_LINE_RE = re.compile(r"^([a-z][a-z0-9_-]*(?:-service)?)\s*[（(]", re.IGNORECASE)


def _is_service_receipt_line(line: str) -> bool:
    """True if line is `lcs（主应用，ES 39 条）` style — not narrative notes."""
    text = (line or "").strip().lstrip("-•").strip()
    if not text or _is_placeholder(text):
        return False
    if text.startswith("（") or text.startswith("("):
        return False
    m = _SERVICE_LINE_RE.match(text)
    if not m:
        return False
    return bool(_name_to_app(m.group(1)))


def _filter_service_lines(lines: list[str]) -> list[str]:
    return [ln.strip() for ln in lines if _is_service_receipt_line(ln)]


def _merge_service_lines(base: str, extra: list[str]) -> str:
    seen: set[str] = set()
    merged: list[str] = []
    for block in (base, *extra):
        for raw in (block.splitlines() if isinstance(block, str) else [block]):
            line = raw.strip()
            if not line or not _is_service_receipt_line(line):
                continue
            app = _name_to_app(_SERVICE_LINE_RE.match(line.lstrip("-•").strip()).group(1))
            if app in seen:
                continue
            seen.add(app)
            merged.append(line)
    return "\n".join(merged) if merged else base.strip()


def _subsystem_apps(evidence: dict, key: str) -> set[str]:
    block = evidence.get(key) or {}
    apps: set[str] = set()
    for app in block.get("by_app") or {}:
        apps.add(str(app).lower())
    if block.get("apps"):
        apps.update(str(a).lower() for a in block["apps"])
    return apps


def _peer_apps_from_logs(logs: dict, *, exclude: set[str]) -> dict[str, str]:
    """从 trace / audit 日志推断关联服务（未单独采 ES 的）。"""
    peers: dict[str, str] = {}
    entries: list[dict] = list(logs.get("entries") or [])
    for block in (logs.get("by_app") or {}).values():
        entries.extend(block.get("entries") or [])

    for entry in entries:
        msg = entry.get("message") or ""
        for m in _TRACE_PEER_RE.finditer(msg):
            token = (m.group(1) or "").strip()
            if not token or token in ("", "NA"):
                continue
            app = _name_to_app(token)
            if not app or app in exclude:
                continue
            if app not in peers:
                peers[app] = "链路可见（主服务日志 trace 命中）"
        for m in _AUDIT_PEER_RE.finditer(msg):
            token = (m.group(1) or "").strip().lower()
            app = _name_to_app(token)
            if not app or app in exclude:
                continue
            if app not in peers:
                peers[app] = "外部调用（audit 命中，未单独采 ES）"
    return peers


def _format_service_line(
    app: str,
    *,
    primary: bool,
    es_count: int = 0,
    refetched: bool = False,
    has_db: bool = False,
    has_code: bool = False,
    branch_not_aligned: bool = False,
    nacos_checked_keys: list[str] | None = None,
    note: str = "",
) -> str:
    tags: list[str] = []
    if primary:
        tags.append("主应用")
    else:
        tags.append("关联")
    if es_count > 0:
        tags.append(f"ES {es_count} 条")
    if refetched:
        tags.append("补拉")
    if has_db:
        tags.append("DB")
    if has_code:
        tags.append("代码")
    if branch_not_aligned:
        tags.append("分支未对齐")
    checked = [k for k in (nacos_checked_keys or []) if k]
    if checked:
        if len(checked) == 1:
            tags.append(f"Nacos {checked[0]}")
        elif len(checked) <= 3:
            tags.append(f"Nacos {'、'.join(checked)}")
        else:
            tags.append(f"Nacos {checked[0]} 等 {len(checked)} key")
    if note:
        tags.append(note)
    if len(tags) == 1 and tags[0] == "关联":
        tags.append("已纳入排查范围")
    return f"{app}（{'，'.join(tags)}）"


def _nacos_checked_keys_for_app(evidence: dict, app: str) -> list[str]:
    """仅统计「专项 key 排查」请求的 key，整份配置拉取不计入。"""
    block = ((evidence.get("nacos") or {}).get("by_app") or {}).get(app) or {}
    keys: list[str] = []
    if block.get("mode") == "key_check":
        keys.extend(block.get("checked_keys") or [])
    for cfg in block.get("configs") or []:
        if cfg.get("mode") == "key_check":
            keys.extend(cfg.get("checked_keys") or [])
    return list(dict.fromkeys(k for k in keys if k))


def _nacos_apps_with_checked_keys(evidence: dict) -> dict[str, list[str]]:
    counts: dict[str, list[str]] = {}
    nacos = evidence.get("nacos") or {}
    for app in (nacos.get("by_app") or {}):
        checked = _nacos_checked_keys_for_app(evidence, str(app))
        if checked:
            counts[str(app).lower()] = checked
    # 顶层 checked_keys（collect_multi 汇总）
    if nacos.get("mode") == "key_check":
        top_keys = [k for k in (nacos.get("checked_keys") or []) if k]
        if top_keys and not counts:
            for app in nacos.get("apps") or []:
                counts[str(app).lower()] = top_keys
    return counts


def _subsystem_apps_with_work(evidence: dict) -> tuple[set[str], set[str], set[str]]:
    """返回实际执行过 DB / 代码 / Nacos key 排查的应用集合。"""
    db_apps: set[str] = set()
    for app, data in ((evidence.get("database") or {}).get("by_app") or {}).items():
        if data.get("skipped"):
            continue
        if data.get("queries") or data.get("error") is None:
            db_apps.add(str(app).lower())

    code_apps: set[str] = set()
    for app, data in ((evidence.get("code") or {}).get("by_app") or {}).items():
        if data.get("code_hits") or data.get("classes_from_logs") or not data.get("error"):
            if data.get("error") and not data.get("code_hits"):
                continue
            code_apps.add(str(app).lower())

    nacos_apps: set[str] = set(_nacos_apps_with_checked_keys(evidence).keys())

    return db_apps, code_apps, nacos_apps


def _collect_chain_peers(ctx: dict, evidence: dict, investigated: set[str]) -> str:
    """从主服务日志推断调用链上的其他服务（未单独采 ES，不计入排查服务）。"""
    logs = evidence.get("logs") or {}
    peers = _peer_apps_from_logs(logs, exclude=investigated)
    if not peers:
        return ""
    parts = [f"{app}（{note}）" for app, note in sorted(peers.items())]
    return "、".join(parts)


def _collect_services(ctx: dict, evidence: dict) -> str:
    # 仅列出实际执行过采集的服务（ES / DB / 代码 / Nacos 至少一项）
    primary = (ctx.get("app") or "unknown").strip().lower()
    logs = evidence.get("logs") or {}
    refetched = {str(a).lower() for a in (logs.get("refetched_apps") or [])}
    by_app = logs.get("by_app") or {}

    es_counts: dict[str, int] = {}
    for app, block in by_app.items():
        app_l = str(app).lower()
        cnt = len(block.get("entries") or [])
        if cnt > 0:
            es_counts[app_l] = cnt

    db_apps, code_apps, nacos_apps = _subsystem_apps_with_work(evidence)
    nacos_checked = _nacos_apps_with_checked_keys(evidence)
    investigated = set(es_counts) | db_apps | code_apps | nacos_apps
    git_branches = evidence.get("git_branches") or ctx.get("git_branches") or {}

    lines: list[str] = []
    seen: set[str] = set()

    def _append(app: str, *, primary_flag: bool) -> None:
        app_l = app.lower()
        if app_l in seen:
            return
        seen.add(app_l)
        lines.append(
            _format_service_line(
                app_l,
                primary=primary_flag,
                es_count=es_counts.get(app_l, 0),
                refetched=app_l in refetched,
                has_db=app_l in db_apps,
                has_code=app_l in code_apps,
                branch_not_aligned=(
                    app_l in code_apps and is_branch_failed(git_branches, app_l)
                ),
                nacos_checked_keys=nacos_checked.get(app_l, []),
            )
        )

    order = sorted(investigated, key=lambda a: (a != primary, -es_counts.get(a, 0), a))
    for app in order:
        _append(app, primary_flag=(app == primary))

    if not lines:
        return f"{primary}（主应用，未成功采集证据）"
    return "\n".join(lines)


def _collect_env(ctx: dict) -> str:
    env = (ctx.get("env") or "dev").strip().lower()
    mode = ctx.get("query_mode") or "trace_id"
    query = (ctx.get("query") or "").strip()
    biz = (ctx.get("biz_key") or "").strip()
    bits = [env]
    if mode == "trace_id" and query:
        bits.append(f"traceId={query[:32]}")
    elif mode == "alert":
        bits.append("告警日志模式")
    elif mode in ("biz_key", "db_probe"):
        bits.append("数据核对")
        if biz:
            bits.append(f"biz_key={biz}")
    return " · ".join(bits)


def _parse_override_text(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    t = (text or "").strip()
    if not t:
        return out
    if t.startswith("{"):
        try:
            data = json.loads(t)
            if isinstance(data, dict):
                for k, v in data.items():
                    if not v:
                        continue
                    ks = str(k)
                    if ks in ("result", "排查结果"):
                        out["result"] = str(v).strip()
                    elif ks in ("clues_needed", "待补线索"):
                        out["clues_needed"] = str(v).strip()
                    elif ks in ("services", "排查服务"):
                        out["services"] = str(v).strip()
                    elif ks in ("services_extra", "关联排查服务"):
                        out["services_extra"] = str(v).strip()
                return out
        except json.JSONDecodeError:
            pass
    for line in t.splitlines():
        line = line.strip()
        if not line:
            continue
        for label, key in (
            ("排查结果", "result"),
            ("现象摘要", "result"),
            ("待补线索", "clues_needed"),
            ("补充线索", "clues_needed"),
            ("排查服务", "services"),
            ("关联排查服务", "services_extra"),
        ):
            if line.startswith(label):
                val = line.split(":", 1)[-1].split("：", 1)[-1].strip()
                if val:
                    out[key] = val
                break
        else:
            if "result" not in out:
                out["result"] = line
    return out


def _is_inconclusive(result: str) -> bool:
    r = (result or "").strip()
    return any(m in r for m in _INCONCLUSIVE_MARKERS)


def build_receipt_fields(ctx: dict, evidence: dict) -> dict[str, str]:
    """从 evidence 自动生成回执字段（环境/服务/表；结果留空待 Agent 填）。"""
    primary = (ctx.get("app") or "unknown").strip().lower()
    logs = evidence.get("logs") or {}
    es_apps = {
        str(a).lower()
        for a, b in (logs.get("by_app") or {}).items()
        if len(b.get("entries") or []) > 0
    }
    db_apps, code_apps, nacos_apps = _subsystem_apps_with_work(evidence)
    investigated = es_apps | db_apps | code_apps | nacos_apps
    return {
        "env": _collect_env(ctx),
        "services": _collect_services(ctx, evidence),
        "branch_align_warning": collect_branch_align_warning(ctx, evidence),
        "chain_peers": _collect_chain_peers(ctx, evidence, investigated),
        "tables": _collect_tables(ctx, evidence),
        "db_inference_note": _collect_db_inference_note(ctx, evidence),
        "result": "",
        "clues_needed": "",
    }


def extract_agent_fields_from_report(report_path: Path) -> dict[str, str]:
    if not report_path.is_file():
        return {}
    body = _section5_body(report_path.read_text(encoding="utf-8"))
    if not body.strip():
        return {}
    out: dict[str, str] = {
        "result": _extract_section(body, _RESULT_HEADINGS),
        "clues_needed": _extract_section(body, _CLUES_HEADINGS),
    }
    # 若是新格式，优先用 **根因** 行
    root_line = _extract_root_cause_line(body)
    if root_line and not out.get("result"):
        out["result"] = root_line
    elif root_line:
        out["result"] = root_line  # 覆盖直接从 heading 提取的

    # 排除的假设
    excluded = _extract_excluded_hypotheses(body)
    if excluded:
        out["excluded_hypotheses"] = "\n".join(excluded)

    override = _extract_section_lines(body, _SERVICES_OVERRIDE_HEADINGS)
    if override:
        out["services"] = "\n".join(override)
    extra = _extract_section_lines(body, _SERVICES_EXTRA_HEADINGS)
    if extra:
        out["services_extra"] = "\n".join(extra)
    return out


def read_receipt_json(run_dir: Path) -> dict[str, str]:
    path = run_dir / RECEIPT_JSON_FILENAME
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {k: str(v).strip() for k, v in data.items() if v}


def write_receipt_json(path: Path, fields: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_receipt_fields(
    run_dir: Path,
    ctx: dict,
    evidence: dict,
    *,
    override_text: str = "",
) -> dict[str, str]:
    """
    合并自动字段 + Agent 填写（报告 §5 / receipt.json / --text）。

    优先级：override_text > receipt.json > 报告 §5 > build_receipt_fields 自动值。
    """
    fields = build_receipt_fields(ctx, evidence)
    agent = extract_agent_fields_from_report(run_dir / "investigation-report.md")
    agent.update({k: v for k, v in read_receipt_json(run_dir).items() if v})
    agent.update(_parse_override_text(override_text))

    if agent.get("result"):
        fields["result"] = agent["result"]
    if agent.get("clues_needed"):
        fields["clues_needed"] = agent["clues_needed"]
    override_lines = _filter_service_lines(
        (agent.get("services") or "").splitlines()
    )
    extra_lines = _filter_service_lines(
        (agent.get("services_extra") or "").splitlines()
    )
    if override_lines:
        fields["services"] = "\n".join(override_lines)
    elif extra_lines:
        fields["services"] = _merge_service_lines(fields["services"], extra_lines)

    if fields["result"] and not _is_inconclusive(fields["result"]) and not fields["clues_needed"]:
        fields["clues_needed"] = "无"

    write_receipt_json(run_dir / RECEIPT_JSON_FILENAME, fields)
    legacy = fields["result"]
    if fields.get("clues_needed") and fields["clues_needed"] != "无":
        legacy = f"{legacy}\n待补线索：{fields['clues_needed']}"
    write_receipt_file(run_dir, legacy)
    return fields


def validate_receipt_fields(fields: dict[str, str]) -> list[str]:
    errors: list[str] = []
    result = (fields.get("result") or "").strip()
    clues = (fields.get("clues_needed") or "").strip()
    if not result or _is_placeholder(result):
        errors.append(
            "缺少「排查结果」：请在报告 §5 填写 ### 5.1 排查结果（或 ### 排查结果），"
            "或回调 --text \"排查结果：...\""
        )
    if _is_inconclusive(result):
        if not clues or clues in ("无", "—", "-", "暂无"):
            errors.append(
                "未能定位根因时须填写 ### 5.3 待补线索，说明还缺什么信息（traceId/表字段/机构响应等）"
            )
    # 置信度校验
    confidence = _extract_confidence(result)
    if confidence is not None and confidence < 30:
        if not clues or clues in ("无", "—", "-", "暂无"):
            errors.append(
                f"置信度仅 {confidence}%，须在 ### 5.3 待补线索 中说明还需什么信息"
            )
    return errors


def read_receipt_file(run_dir: Path) -> str:
    path = run_dir / RECEIPT_FILENAME
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def write_receipt_file(run_dir: Path, text: str) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / RECEIPT_FILENAME
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def format_finished_message(
    *,
    fields: dict[str, str],
    report_path: Path | str,
    evidence_path: Path | str,
) -> str:
    """拼装「问题排查完成」回执 Markdown（Driver finished 态直接输出）。"""
    result = (fields.get("result") or "—").strip()
    clues = (fields.get("clues_needed") or "").strip()
    lines = [
        "问题排查完成",
        "",
        "**排查环境**",
        fields.get("env") or "—",
        "",
        "**排查服务**",
        fields.get("services") or "—",
    ]
    branch_warn = (fields.get("branch_align_warning") or "").strip()
    if branch_warn:
        lines.extend(["", "**代码分支对齐**", branch_warn])
    lines.extend([
        "",
        "**排查表**",
        fields.get("tables") or "—",
    ])
    db_note = (fields.get("db_inference_note") or "").strip()
    if db_note:
        lines.extend(["", "**DB 推断**", db_note])
    lines.extend([
        "",
        "**排查结果**",
        result,
    ])
    if clues and clues != "无":
        lines.extend(["", "**待补线索**", clues])
    lines.extend([
        "",
        "---",
        f"详情见完整报告：`{report_path}`",
        f"证据：`{evidence_path}`",
    ])
    return "\n".join(lines)


def receipt_to_display_text(fields: dict[str, str]) -> str:
    return (fields.get("result") or "").strip()
