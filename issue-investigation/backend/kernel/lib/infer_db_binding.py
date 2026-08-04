"""校验日志字段与 Mapper SQL WHERE 列的语义绑定；不确定则跳过执行。"""
from __future__ import annotations

import re
from pathlib import Path

from lib.infer_db_sql import _BIZ_COL, _SELECT_BLOCK

_CAMEL_SPLIT = re.compile(r"([a-z0-9])([A-Z])")
_WHERE_PARAM = re.compile(r"`?(\w+)`?\s*=\s*#\{(\w+)", re.I)
_LABEL_RE = re.compile(r"^code:(?P<file>[^#]+)#(?P<select_id>.+)$")


def camel_to_snake(name: str) -> str:
    s = _CAMEL_SPLIT.sub(r"\1_\2", name).lower()
    return re.sub(r"_+", "_", s)


def norm(s: str) -> str:
    return re.sub(r"[_\s]", "", (s or "").lower())


def _semantic_overlap(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if shorter in longer:
        return len(shorter) / len(longer)
    prefix = 0
    for x, y in zip(a, b):
        if x != y:
            break
        prefix += 1
    return prefix / max(len(a), len(b))


def _guess_param_from_col(where_col: str) -> str:
    parts = where_col.split("_")
    if not parts:
        return where_col
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _where_col_from_sql(sql: str) -> str:
    m = re.search(r"WHERE\s+`(\w+)`", sql or "", re.I)
    return m.group(1) if m else ""


def extract_where_binding(mapper_block: str, where_col: str) -> tuple[str, str] | None:
    """从 select 块中提取指定列对应的 #{param}。"""
    target = where_col.lower()
    for m in _WHERE_PARAM.finditer(mapper_block):
        col, param = m.group(1).lower(), m.group(2)
        if col == target:
            return where_col, param
    return None


def _load_mapper_binding(
    repo_root: Path,
    label: str,
    where_col: str,
) -> tuple[str, str, str] | None:
    m = _LABEL_RE.match(label or "")
    if not m:
        return None
    mapper_name = m.group("file")
    select_id = m.group("select_id")
    candidates: list[Path] = []
    for pattern in (
        "*/src/main/resources/mybatis/mappings/**/*.xml",
        "*/src/main/resources/mybatis/**/*.xml",
    ):
        for path in repo_root.glob(pattern):
            if path.is_file() and path.name == mapper_name:
                candidates.append(path)
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for block in _SELECT_BLOCK.findall(text):
            sid = re.search(r'id="([^"]+)"', block)
            if not sid or sid.group(1) != select_id:
                continue
            binding = extract_where_binding(block, where_col)
            if not binding:
                first = next(_WHERE_PARAM.finditer(block), None)
                if first:
                    binding = (first.group(1), first.group(2))
            if binding:
                col, param = binding
                return col, param, block[:240]
    return None


def validate_log_sql_binding(
    *,
    log_field: str,
    where_col: str,
    param_name: str,
    biz_key_source: str = "logs",
) -> tuple[bool, str]:
    """返回 (should_execute, reason)。"""
    if biz_key_source == "user":
        return True, "业务键由用户指定"

    if not log_field:
        return False, "日志中未识别出明确的 JSON/字段名，无法确认 SQL 应使用的列"

    lf = norm(log_field)
    wc = norm(where_col)
    pm = norm(param_name)
    snake = norm(camel_to_snake(log_field))

    if lf == pm:
        return True, f"日志字段 `{log_field}` 与 Mapper 参数 `{param_name}` 一致"
    if snake == wc:
        return True, f"日志字段 `{log_field}` 对应列 `{where_col}`"
    if pm == wc and snake == wc:
        return True, f"Mapper 参数 `{param_name}` 绑定列 `{where_col}`"

    if pm and lf.endswith(pm) and lf != pm and len(lf) - len(pm) >= 4:
        return False, (
            f"日志字段 `{log_field}` 仅后缀匹配 Mapper 参数 `{param_name}`，"
            "疑为子串误匹配（例如 fundPrivilegeOrderNo 被 orderNo 规则命中）"
        )

    if wc == "orderno" and "fund" in lf:
        return False, (
            f"日志字段 `{log_field}` 为机构侧单号语义，不宜映射内部列 `order_no`"
        )

    if wc == "fundorderno" and "fund" not in lf:
        return False, f"列 `fund_order_no` 与日志字段 `{log_field}` 语义不一致"

    overlap = max(_semantic_overlap(lf, pm), _semantic_overlap(lf, wc), _semantic_overlap(snake, wc))
    if overlap >= 0.72:
        return True, (
            f"日志字段 `{log_field}` 与列 `{where_col}` / 参数 `{param_name}` 语义相近"
        )

    return False, (
        f"无法确认日志字段 `{log_field}` 与 SQL 列 `{where_col}`"
        f"（参数 `{param_name or '未知'}）` 的对应关系"
    )


def filter_mapper_queries(
    queries: list[tuple[str, str, str]],
    *,
    repo_root: Path | None,
    log_field: str,
    biz_key: str,
    biz_key_kind: str,
    biz_key_source: str = "logs",
    app: str = "",
) -> tuple[list[tuple[str, str, str]], list[dict]]:
    """过滤 Mapper 推断 SQL，返回 (accepted, skipped_records)。"""
    if not queries:
        return [], []

    accepted: list[tuple[str, str, str]] = []
    skipped: list[dict] = []

    default_col = _BIZ_COL.get(biz_key_kind) or ""

    for label, sql, reason in queries:
        where_col = default_col or _where_col_from_sql(sql)
        param_name = _guess_param_from_col(where_col) if where_col else ""

        if repo_root and label.startswith("code:") and where_col:
            loaded = _load_mapper_binding(Path(repo_root), label, where_col)
            if loaded:
                where_col, param_name, _ = loaded

        ok, bind_reason = validate_log_sql_binding(
            log_field=log_field,
            where_col=where_col,
            param_name=param_name,
            biz_key_source=biz_key_source,
        )

        if ok:
            accepted.append((label, sql, f"{reason}；绑定校验：{bind_reason}"))
        else:
            skipped.append({
                "app": app,
                "label": label,
                "sql": sql,
                "biz_key": biz_key,
                "biz_key_kind": biz_key_kind,
                "log_field": log_field,
                "where_col": where_col,
                "param_name": param_name,
                "inference_reason": reason,
                "skip_reason": bind_reason,
            })

    return accepted, skipped
