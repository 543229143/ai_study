"""从日志抽出「需要用库表佐证」的假设（claim）。

**已弃用（默认采集路径）**：`inv_runner` 改为由 Agent 写 `agent_db_plan.json`，
本模块仅供遗留 `plan_db_investigation` 调用，勿新增业务场景硬编码。
"""
from __future__ import annotations

import re
from typing import Any


def _all_messages(logs: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for _app, block in (logs.get("by_app") or {}).items():
        for e in block.get("entries") or []:
            msg = e.get("message") or ""
            if msg:
                out.append(msg)
    if out:
        return out
    return [e.get("message") or "" for e in (logs.get("entries") or []) if e.get("message")]


def _blob(logs: dict[str, Any]) -> str:
    return "\n".join(_all_messages(logs))


def _usable(val: str) -> bool:
    if not val or len(val) < 4:
        return False
    if "*" in val or "…" in val or "..." in val:
        return False
    if val.lower() in ("null", "none", "true", "false"):
        return False
    return True


def _missing_fund_apply_nos(text: str) -> list[str]:
    """兼容单文本；优先走 logs 结构化抽取。"""
    return _missing_fund_apply_nos_from_messages([text] if text else [])


def _parse_fund_apply_pairs(msg: str) -> list[tuple[str, str]]:
    """从一段日志提取 (fundCode, applyNo) 对（双向邻近匹配）。"""
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pat in (
        r'"fundCode"\s*:\s*"([^"]+)"[^\}]{0,500}?"applyNo"\s*:\s*"([^"]+)"',
        r'"applyNo"\s*:\s*"([^"]+)"[^\}]{0,500}?"fundCode"\s*:\s*"([^"]+)"',
    ):
        rev = "applyNo" in pat and pat.index("applyNo") < pat.index("fundCode")
        for m in re.finditer(pat, msg or "", re.I | re.S):
            if rev:
                apply_no, fund = m.group(1).strip(), m.group(2).strip()
            else:
                fund, apply_no = m.group(1).strip(), m.group(2).strip()
            if not _usable(apply_no) or not fund:
                continue
            key = (fund, apply_no)
            if key not in seen:
                seen.add(key)
                pairs.append(key)
    return pairs


def _missing_fund_apply_nos_from_messages(messages: list[str]) -> list[str]:
    """
    只在「利率缺失 ERROR」与「可借列表/AB 排序」日志内对照：
    interestRateMap 有费率的 fund vs 可借列表 fund → 只返回缺 map 的 applyNo。
    """
    rate_funds: set[str] = set()
    for msg in messages:
        if "interestRateMap" not in msg:
            continue
        if not re.search(r"获取不到|机构产品利率|\bERROR\b", msg, re.I):
            continue
        for m in re.finditer(r"interestRateMap\s*[:=]\s*(\{[^}]+\})", msg, re.I):
            rate_funds.update(re.findall(r'"([a-zA-Z][a-zA-Z0-9_]*)"\s*:', m.group(1)))

    if not rate_funds:
        return []

    # 可借列表：ERROR 里可能截断，需从同 trace 的 AB/可借 INFO 补齐
    pairs: list[tuple[str, str]] = []
    for msg in messages:
        if not re.search(
            r"availableLoanList|availableLoanListSort|进入AB实验|interestRateMap",
            msg,
            re.I,
        ):
            continue
        # 排除刷接口/全量机构名单等噪声（无 applyNo 成对通常也抽不到）
        if re.search(r"批量获取机构产品进件字段|接口限流", msg):
            continue
        pairs.extend(_parse_fund_apply_pairs(msg))

    if not pairs:
        return []

    missing_funds = {f for f, _ in pairs} - rate_funds
    preferred: list[str] = []
    for fund, apply_no in pairs:
        if fund in missing_funds and apply_no not in preferred:
            preferred.append(apply_no)
    return preferred


def extract_verification_claims(
    logs: dict[str, Any],
    investigation_apps: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    返回 claim 列表。每条大致包含：

    - id / description：假设说明（写入报告）
    - target_apps：只对这些服务连库
    - table_keywords：表名/Mapper 名须命中其一（小写子串）
    - key_kind / key_values：WHERE 键；多值仅限佐证所需
    - max_queries：每个键最多几条 SQL
    - max_keys：最多几个业务键
    """
    apps = {(a or "").strip().lower() for a in (investigation_apps or []) if a}
    messages = _all_messages(logs)
    text = "\n".join(messages)
    claims: list[dict[str, Any]] = []
    if not text.strip():
        return claims

    # —— 定价/利率字段缺失：只佐证 AMS 费率 ——
    if re.search(
        r"获取不到.*利率|机构产品利率|interestRateMap|"
        r"queryAccountPrdTermFee|PrdTermFee|可借列表存在机构获取不到",
        text,
        re.I,
    ):
        keys = _missing_fund_apply_nos_from_messages(messages)
        if not keys:
            # 退一步：利率 ERROR 片段内第一条可用 applyNo（单键）
            for msg in messages:
                if "interestRateMap" not in msg:
                    continue
                if not re.search(r"获取不到|\bERROR\b", msg, re.I):
                    continue
                for m in re.finditer(r'"applyNo"\s*:\s*"([^"]+)"', msg):
                    v = m.group(1).strip()
                    if _usable(v):
                        keys = [v]
                        break
                if keys:
                    break
        target = ["ams"]
        if apps:
            target = [a for a in target if a in apps]
        if target and keys:
            claims.append({
                "id": "pricing_fee_gap",
                "description": (
                    "interestRateMap 缺机构费率，核对 AMS.ac_pilot_prd_term_fee 是否缺行"
                ),
                "target_apps": target,
                "table_keywords": [
                    "prd_term_fee",
                    "term_fee",
                    "prdtermfee",
                ],
                "table_exclude": [
                    "archive",
                    "quota",
                    "change_record",
                    "iou",
                    "appl",
                    "flow",
                    "account",
                ],
                "key_kind": "apply_no",
                "key_values": keys[:2],
                "max_queries": 1,
                "max_keys": 2,
                "lock_kind": True,
            })

    # —— 明确「查无/0 行/不存在」且同句带表或实体线索 ——
    for m in re.finditer(
        r"(?P<ctx>.{0,80}?(?:查无|不存在|0\s*行|empty\s+result|查询为空|无记录).{0,80})",
        text,
        re.I,
    ):
        ctx = m.group("ctx")
        # 从表名线索猜
        table_hit = re.search(
            r"\b(ac_[a-z0-9_]+|pilot_[a-z0-9_]+|i_[a-z0-9_]+|ap_[a-z0-9_]+|[a-z]+_[a-z0-9_]{3,})\b",
            ctx,
            re.I,
        )
        if not table_hit:
            continue
        table = table_hit.group(1).lower()
        apply_nos = [g for g in re.findall(r"\b(CR\d{10,})\b", ctx) if _usable(g)]
        loan_nos = [g for g in re.findall(r"\b(L[NO]?\d{10,}|LN[a-f0-9]{10,})\b", ctx, re.I) if _usable(g)]
        key_kind, key_values = ("apply_no", apply_nos[:2]) if apply_nos else (
            ("loan_no", loan_nos[:2]) if loan_nos else ("", [])
        )
        if not key_kind or not key_values:
            continue
        # schema 粗判
        if table.startswith("ac_") or "account" in table or "prd" in table:
            target = ["ams"]
        elif table.startswith("i_") or table.startswith("ap_"):
            target = ["lps"]
        elif "pilot_loan" in table or "pilot_plan" in table:
            target = ["lcs"]
        else:
            continue
        if apps:
            target = [a for a in target if a in apps]
        if not target:
            continue
        cid = f"empty_result:{table}:{key_values[0]}"
        if any(c.get("id") == cid for c in claims):
            continue
        claims.append({
            "id": cid,
            "description": f"日志出现空结果语义，需核对表 `{table}` 是否确无对应数据",
            "target_apps": target,
            "table_keywords": [table, table.replace("_", "")[:12]],
            "table_exclude": [],
            "key_kind": key_kind,
            "key_values": key_values,
            "max_queries": 1,
            "max_keys": 2,
            "lock_kind": True,
        })

    # —— 持久化失败且栈里有明确 Mapper/Dao ——
    for m in re.finditer(
        r"(?P<cls>\w+(?:Mapper|Dao))\b.{0,200}?(?:失败|Exception|error)|"
        r"(?:失败|Exception|error).{0,200}?\b(?P<cls2>\w+(?:Mapper|Dao))\b",
        text,
        re.I | re.S,
    ):
        cls = (m.group("cls") or m.group("cls2") or "").strip()
        if not cls:
            continue
        # 无法可靠映射 app 时跳过；仅给关键命名提示
        stem = re.sub(r"(Mapper|Dao)$", "", cls, flags=re.I).lower()
        if not stem or len(stem) < 4:
            continue
        # 这类 claim 不强制 app：由后续「本仓是否有该 Mapper」决定
        cid = f"persist_fail:{cls}"
        if any(c.get("id") == cid for c in claims):
            continue
        claims.append({
            "id": cid,
            "description": f"日志持久化失败且出现 `{cls}`，需用对应 Mapper 表佐证当前数据",
            "target_apps": list(apps) if apps else ["lcs", "lps", "ams", "goa"],
            "table_keywords": [stem, stem.replace("pilot", "pilot_")],
            "table_exclude": [],
            "key_kind": "",  # 留给上层用已有 biz_key 填
            "key_values": [],
            "max_queries": 2,
            "max_keys": 1,
            "lock_kind": False,
            "mapper_hint": cls,
        })

    return claims


def claims_for_app(claims: list[dict[str, Any]], app: str) -> list[dict[str, Any]]:
    app = (app or "").strip().lower()
    return [c for c in claims if app in {(x or "").strip().lower() for x in (c.get("target_apps") or [])}]


def claim_table_allowed(table: str, claim: dict[str, Any]) -> bool:
    """表名是否服务该假设。"""
    t = (table or "").lower()
    excludes = [x.lower() for x in (claim.get("table_exclude") or []) if x]
    if any(x in t for x in excludes):
        return False
    kws = [x.lower() for x in (claim.get("table_keywords") or []) if x]
    if not kws:
        return True
    return any(k in t for k in kws)


def claim_mapper_path_allowed(path_name: str, claim: dict[str, Any]) -> bool:
    name = (path_name or "").lower()
    excludes = [x.lower() for x in (claim.get("table_exclude") or []) if x]
    if any(x in name for x in excludes):
        return False
    hint = (claim.get("mapper_hint") or "").lower()
    if hint and hint.replace("mapper", "").replace("dao", "") in name.replace(".xml", ""):
        return True
    kws = [x.lower() for x in (claim.get("table_keywords") or []) if x]
    if not kws:
        return True
    return any(k.replace("_", "") in name.replace("_", "") or k in name for k in kws)
