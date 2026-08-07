"""从业务代码仓 MyBatis Mapper XML 自动生成只读 SELECT 并执行。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from lib.common import load_platform_config
from lib.env_config import get_schema_name, resolve_sql_placeholders

# biz_key_kind → Mapper WHERE 列名
_BIZ_COL = {
    "loan_no": "loan_no",
    "order_no": "order_no",
    "appl_no": "appl_no",
    "apply_no": "apply_no",
    "acct_no": "acct_no",
    "cust_no": "cust_no",
    "privilege_plan_no": "privilege_plan_no",
    "fund_order_no": "fund_order_no",
    "fund_tran_req_no": "fund_tran_req_no",
}

_SELECT_BLOCK = re.compile(r"<select\b[^>]*>.*?</select>", re.I | re.S)
_FROM_TABLE = re.compile(r"\bfrom\s+([a-z_][a-z0-9_]*)", re.I)
_WHERE_BIZ = re.compile(
    r"\bwhere\b[\s\S]*?\b__COL__\s*=\s*#\{[^}]+\}",
    re.I,
)


def _mapper_dirs(repo_root: Path) -> list[Path]:
    roots: list[Path] = []
    for pattern in (
        "*/src/main/resources/mybatis/mappings/**/*.xml",
        "*/src/main/resources/mybatis/**/*.xml",
    ):
        roots.extend(repo_root.glob(pattern))
    return [p for p in roots if p.is_file()]


def _score_mapper(path: Path, keywords: list[str]) -> int:
    name = path.stem.lower()
    score = 0
    if name in ("pilotloanmapper", "pilotplanmapper", "pilotprivilegeplanmapper"):
        score += 25
    elif "pilotloan" in name and "control" not in name and "black" not in name:
        score += 15
    for kw in keywords:
        s = kw.lower()
        simple = s.rsplit(".", 1)[-1].replace("serviceimpl", "").replace("service", "").replace("mapper", "")
        if simple and simple in name:
            score += 10
        if "privilegeplan" in name and "privilege" in s:
            score += 8
        if "pilotplan" in name and "plan" in s:
            score += 6
    return score


def _extract_selects(xml_text: str, where_col: str) -> list[tuple[str, str, str]]:
    """返回 (select_id, table, snippet_source)。"""
    found: list[tuple[str, str, str]] = []
    where_re = re.compile(_WHERE_BIZ.pattern.replace("__COL__", re.escape(where_col)), re.I)
    for block in _SELECT_BLOCK.findall(xml_text):
        if not where_re.search(block):
            continue
        sid = re.search(r'id="([^"]+)"', block)
        select_id = sid.group(1) if sid else "unknown"
        # 去掉 include，便于取 from
        flat = re.sub(r"<include[^>]*/>", " ", block, flags=re.I)
        flat = re.sub(r"<[^>]+>", " ", flat)
        m = _FROM_TABLE.search(flat)
        if not m:
            continue
        table = m.group(1).lower()
        if table in ("dual", "information_schema"):
            continue
        found.append((select_id, table, block[:120]))
    return found


def _build_select_sql(
    schema: str,
    table: str,
    where_col: str,
    biz_key: str,
    *,
    limit: int | None = None,
) -> str:
    """生成只读 SELECT；默认带 LIMIT，避免全表结果灌入 evidence。"""
    from lib.evidence_slim import DB_SELECT_ROW_LIMIT, ensure_select_limit

    row_limit = DB_SELECT_ROW_LIMIT if limit is None else limit
    sql = (
        f"SELECT * FROM `{schema}`.`{table}` "
        f"WHERE `{where_col}` = '{biz_key}'"
    )
    return ensure_select_limit(sql, row_limit)


def infer_queries_from_code(
    repo_root: Path,
    app: str,
    env: str,
    biz_key: str,
    biz_key_kind: str,
    keywords: list[str] | None = None,
    *,
    max_queries: int = 2,
    table_allow: Callable[[str], bool] | None = None,
    path_allow: Callable[[str], bool] | None = None,
    claim_note: str = "",
) -> list[tuple[str, str, str]]:
    """
    扫描 Mapper XML，按 biz_key 列生成只读 SELECT。
    若提供 table_allow/path_allow（来自 verification claim），只保留服务该假设的表。
    返回 [(source_label, sql, inference_reason), ...]
    """
    if not biz_key or not repo_root.is_dir():
        return []
    where_col = _BIZ_COL.get(biz_key_kind) or "loan_no"
    app_cfg = load_platform_config().get("apps", {}).get(app) or {}
    schema = get_schema_name(env, app_cfg.get("primary_schema") or app)

    mappers = _mapper_dirs(repo_root)
    if not mappers:
        return []

    kw = [k for k in (keywords or []) if k and len(k) > 3]
    ranked = sorted(mappers, key=lambda p: _score_mapper(p, kw), reverse=True)

    seen_tables: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for path in ranked:
        if path_allow is not None and not path_allow(path.name):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for select_id, table, _ in _extract_selects(text, where_col):
            if table_allow is not None and not table_allow(table):
                continue
            key = f"{table}:{where_col}"
            if key in seen_tables:
                continue
            seen_tables.add(key)
            sql = _build_select_sql(schema, table, where_col, biz_key)
            sql = resolve_sql_placeholders(sql, env, app_cfg, biz_key)
            label = f"code:{path.name}#{select_id}"
            reason = (
                f"假设佐证：{claim_note}" if claim_note else ""
            )
            if reason:
                reason += "；"
            reason += (
                f"biz_key=`{biz_key}`（{biz_key_kind}），"
                f"匹配 Mapper `{path.name}#{select_id}` 表 `{table}`"
            )
            out.append((label, sql, reason))
            if len(out) >= max_queries:
                return out
    return out
