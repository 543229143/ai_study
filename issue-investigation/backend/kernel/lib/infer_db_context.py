"""从日志与代码扫描结果推断 DB 查询所需的 biz_key 与场景。"""
from __future__ import annotations

import re
from typing import Any

from lib.common import extract_java_classes_from_logs, load_catalog, parse_problem_text

# 内置兜底 biz_key 模式（当 app-catalog.json 未配置 biz_key_patterns 时使用）
_BIZ_PATTERNS_DEFAULT: list[tuple[str, str, str]] = [
    (r'(?:loan[_ ]?no|loanNo|借据)[:：=\s"]+\s*"?([A-Za-z0-9_-]+)', "loan_no", "loanNo"),
    (r'"loanNo"\s*:\s*"([^"]+)"', "loan_no", "loanNo"),
    (r'"loan_no"\s*:\s*"([^"]+)"', "loan_no", "loan_no"),
    (r'\b(LN[a-f0-9]{10,})\b', "loan_no", ""),
    (r'\b(L\d{10,})\b', "loan_no", ""),
    (r'"fundPrivilegeOrderNo"\s*:\s*"([^"]+)"', "fund_order_no", "fundPrivilegeOrderNo"),
    (r'"fundOrderNo"\s*:\s*"([^"]+)"', "fund_order_no", "fundOrderNo"),
    (r'"fundTranReqNo"\s*:\s*"([^"]+)"', "fund_tran_req_no", "fundTranReqNo"),
    (r'(?:order[_ ]?no|orderNo|订单)[:：=\s"]+\s*"?([A-Za-z0-9_-]+)', "order_no", "orderNo"),
    (r'(?<![a-zA-Z])"orderNo"\s*:\s*"([^"]+)"', "order_no", "orderNo"),
    (r'"order_no"\s*:\s*"([^"]+)"', "order_no", "order_no"),
    (r'\b(O\d{10,})\b', "order_no", ""),
    (r'"applyNo"\s*:\s*"([^"]+)"', "apply_no", "applyNo"),
    (r'"apply_no"\s*:\s*"([^"]+)"', "apply_no", "apply_no"),
    (r'(?:apply[_ ]?no|applyNo)[:：=\s"]+\s*"?([A-Za-z0-9_-]+)', "apply_no", "applyNo"),
    (r'\b(CR\d{10,})\b', "apply_no", ""),
    (r'(?:appl[_ ]?no|applNo)[:：=\s"]+\s*"?([A-Za-z0-9_-]+)', "appl_no", "applNo"),
    (r'"applNo"\s*:\s*"([^"]+)"', "appl_no", "applNo"),
    (r'"appl_no"\s*:\s*"([^"]+)"', "appl_no", "appl_no"),
    (r'"acctNo"\s*:\s*"([^"]+)"', "acct_no", "acctNo"),
    (r'"acct_no"\s*:\s*"([^"]+)"', "acct_no", "acct_no"),
    (r'(?:acct[_ ]?no|acctNo)[:：=\s"]+\s*"?([A-Za-z0-9_*]+)', "acct_no", "acctNo"),
    (r'"custNo"\s*:\s*"([^"]+)"', "cust_no", "custNo"),
    (r'"cust_no"\s*:\s*"([^"]+)"', "cust_no", "cust_no"),
    (r'(?:privilege[_ ]?plan[_ ]?no|privilegePlanNo)[:：=\s"]+\s*"?([A-Za-z0-9_-]+)', "privilege_plan_no", "privilegePlanNo"),
]

_BIZ_PATTERNS_CACHE: dict[str, list[tuple[str, str, str]]] = {}


def _load_biz_patterns(apps: list[str] | None = None) -> list[tuple[str, str, str]]:
    """从 app-catalog.json 加载业务键模式（合并全局 + 按应用定制）。"""
    catalog = load_catalog()
    cfg = catalog.get("biz_key_patterns") or {}
    global_cfg = cfg.get("_global") or []
    merged: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def _add(item: dict) -> None:
        key = f"{item.get('kind','')}:{item.get('pattern','')}"
        if key in seen:
            return
        seen.add(key)
        merged.append((item["pattern"], item["kind"], item.get("log_field", "")))

    # 先加全局
    for item in global_cfg:
        _add(item)

    # 再加各应用定制（优先级更高）
    for app in (apps or []):
        app_str = (app or "").strip().lower()
        if app_str not in _BIZ_PATTERNS_CACHE:
            app_patterns = cfg.get(app_str) or []
            _BIZ_PATTERNS_CACHE[app_str] = [
                (p["pattern"], p["kind"], p.get("log_field", ""))
                for p in app_patterns
            ]
        for pat in _BIZ_PATTERNS_CACHE[app_str]:
            key = f"{pat[1]}:{pat[0]}"
            if key not in seen:
                seen.add(key)
                merged.append(pat)

    # 兜底默认
    for pat in _BIZ_PATTERNS_DEFAULT:
        key = f"{pat[1]}:{pat[0]}"
        if key not in seen:
            seen.add(key)
            merged.append(pat)

    return merged

_KIND_PRIORITY = (
    "loan_no",
    "fund_order_no",
    "fund_tran_req_no",
    "apply_no",
    "order_no",
    "acct_no",
    "cust_no",
    "appl_no",
    "privilege_plan_no",
)

# 日志点名缺定价/利率时，优先用 apply_no 查账户产品费率表
_PRICING_GAP = re.compile(
    r"interestRateMap|机构产品利率|获取不到|定价|PrdTermFee|feeRate",
    re.I,
)

# (pattern, scenario, app_hint or None)
_SCENARIO_RULES: list[tuple[str, str, str | None]] = [
    (r"PilotPrivilegePlan|pilot_privilege_plan|insertBatchSelective", "privilege-plan", "lcs"),
    (r"RepayPlan|repay_plan|RepayFacade|queryRepayPlan|repayPlan", "repay", None),
    (r"Callback|callback|FundCallback", "callback", "goa"),
    (r"Appl|CreditApply|credit_apply|ap_appl", "credit-apply", "lps"),
]

_APP_CONTAINER = {
    "lps-service": "lps",
    "lcs-service": "lcs",
    "goa-service": "goa",
    "ams-service": "ams",
}


def collect_log_messages(logs: dict[str, Any]) -> list[tuple[str, str]]:
    """返回 (app, message) 列表，app 来自 entry 或 by_app 键。"""
    pairs: list[tuple[str, str]] = []
    for app, block in (logs.get("by_app") or {}).items():
        for e in block.get("entries") or []:
            msg = e.get("message") or ""
            if msg:
                pairs.append((app, msg))
    if not pairs:
        for e in logs.get("entries") or []:
            msg = e.get("message") or ""
            if not msg:
                continue
            container = (e.get("container") or "").strip()
            app = _APP_CONTAINER.get(container, "")
            pairs.append((app or "?", msg))
    return pairs


def _is_usable_biz_value(val: str) -> bool:
    if not val or len(val) < 4:
        return False
    if val.lower() in ("null", "none", "true", "false"):
        return False
    if "*" in val or "…" in val or "..." in val:
        return False  # 脱敏账号等不可用于 SQL
    if re.fullmatch(r"[a-f0-9]{32}", val, re.I):
        return False  # traceId
    return True


def _extract_keys_from_text(text: str, apps: list[str] | None = None) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pat, kind, log_field in _load_biz_patterns(apps):
        for m in re.finditer(pat, text, re.I):
            val = m.group(1).strip()
            if not _is_usable_biz_value(val):
                continue
            key = (kind, val)
            if key not in seen:
                seen.add(key)
                found.append({
                    "kind": kind,
                    "value": val,
                    "source": "logs",
                    "log_field": log_field,
                })
    return found


def _prefer_missing_apply_nos(text: str, candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    从 interestRateMap vs availableLoanList 推断缺失 fund → 优先其 applyNo。
    例：map 有 meiyi/lifenqi/juduoduo，list 还有 yijie → 把 yijie 的 applyNo 提前。
    """
    if not _PRICING_GAP.search(text or ""):
        return candidates

    rate_funds: set[str] = set()
    for m in re.finditer(r"interestRateMap\s*[:=]\s*(\{[^}]+\})", text or "", re.I):
        rate_funds.update(re.findall(r'"([a-zA-Z][a-zA-Z0-9_]*)"\s*:', m.group(1)))

    list_funds = set(re.findall(r'"fundCode"\s*:\s*"([^"]+)"', text or ""))
    missing = list_funds - rate_funds if list_funds and rate_funds else set()
    if not missing:
        return candidates

    preferred_apply: list[str] = []
    for fund in missing:
        esc = re.escape(fund)
        pat_fwd = (
            r'"fundCode"\s*:\s*"' + esc + r'"[^\}]{0,500}?"applyNo"\s*:\s*"([^"]+)"'
        )
        pat_rev = (
            r'"applyNo"\s*:\s*"([^"]+)"[^\}]{0,500}?"fundCode"\s*:\s*"' + esc + r'"'
        )
        for pat in (pat_fwd, pat_rev):
            for m in re.finditer(pat, text or "", re.I | re.S):
                apply_no = m.group(1).strip()
                if apply_no and apply_no not in preferred_apply:
                    preferred_apply.append(apply_no)

    if not preferred_apply:
        return candidates

    head: list[dict[str, str]] = []
    seen: set[str] = set()
    for apply_no in preferred_apply:
        for c in candidates:
            if c.get("kind") == "apply_no" and c.get("value") == apply_no and apply_no not in seen:
                head.append(c)
                seen.add(apply_no)
    rest = [c for c in candidates if not (c.get("kind") == "apply_no" and c.get("value") in seen)]
    return head + rest


def _pick_best_key(candidates: list[dict[str, str]], preferred_kind: str | None = None) -> dict[str, str] | None:
    if not candidates:
        return None
    if preferred_kind:
        for c in candidates:
            if c["kind"] == preferred_kind:
                return c
    for kind in _KIND_PRIORITY:
        for c in candidates:
            if c["kind"] == kind:
                return c
    return candidates[0]


def _infer_scenario_from_text(text: str) -> tuple[str, str | None]:
    """返回 (scenario, app_hint)。"""
    for pat, scenario, app_hint in _SCENARIO_RULES:
        if re.search(pat, text, re.I):
            return scenario, app_hint
    parsed = parse_problem_text(text)
    sc = parsed.get("scenario") or "default"
    if sc != "default":
        return sc, None
    return "default", None


def infer_db_context_for_app(
    logs: dict[str, Any],
    app: str,
    *,
    user_biz_key: str = "",
    user_scenario: str = "default",
    code_classes: list[str] | None = None,
) -> dict[str, Any]:
    """
    仅从**该服务自身**日志提取 DB 填充字段（不合并其他服务日志）。

    排查 lcs 日志 → 只用 lcs 日志里的字段填 lcs SQL；goa/ams 同理。
    """
    app = (app or "").strip().lower()
    pairs = [(a, msg) for a, msg in collect_log_messages(logs) if a == app]
    app_text = "\n".join(msg for _, msg in pairs)
    if code_classes and app:
        app_text += "\n" + "\n".join(code_classes)

    candidates: list[dict[str, str]] = []
    for _, msg in pairs:
        candidates.extend(_extract_keys_from_text(msg, apps=[app]))

    if user_biz_key:
        user_parsed = parse_problem_text(user_biz_key)
        uk = user_parsed.get("biz_key") or user_biz_key.strip()
        if uk:
            kind = (
                "loan_no" if uk.startswith("L")
                else "order_no" if uk.startswith("O")
                else "unknown"
            )
            candidates.insert(0, {
                "kind": kind,
                "value": uk,
                "source": "user",
                "log_field": "",
            })

    scenario = user_scenario if user_scenario and user_scenario != "default" else "default"
    scenario_source = "user" if scenario != "default" else "default"
    app_hint: str | None = None

    if scenario == "default" and app_text:
        sc, hint = _infer_scenario_from_text(app_text)
        if sc != "default":
            scenario = sc
            scenario_source = "logs"
            app_hint = hint

    preferred_kind = None
    all_blob = "\n".join(msg for _, msg in collect_log_messages(logs))
    pricing_gap = bool(_PRICING_GAP.search(app_text) or _PRICING_GAP.search(all_blob))
    if pricing_gap:
        preferred_kind = "apply_no"
        candidates = _prefer_missing_apply_nos(all_blob if _PRICING_GAP.search(all_blob) else app_text, candidates)
    elif scenario == "credit-apply":
        preferred_kind = "order_no"
    elif scenario in ("repay", "privilege-plan"):
        preferred_kind = "loan_no"

    # 定价缺口：吸收全链路 ERROR / 对端日志中的 applyNo（对端常更完整）
    if preferred_kind == "apply_no":
        for a, msg in collect_log_messages(logs):
            if a == app:
                continue
            if _PRICING_GAP.search(msg) or re.search(r"\bERROR\b", msg):
                extras = _extract_keys_from_text(msg, apps=[a])
                extras = _prefer_missing_apply_nos(msg, extras)
                for c in extras:
                    if c.get("kind") in ("apply_no", "acct_no", "cust_no"):
                        candidates.append({**c, "source": f"peer:{a}"})
        deduped: list[dict[str, str]] = []
        seen_kv: set[tuple[str, str]] = set()
        for c in candidates:
            k = (c.get("kind") or "", c.get("value") or "")
            if k in seen_kv or not k[1]:
                continue
            seen_kv.add(k)
            deduped.append(c)
        candidates = _prefer_missing_apply_nos(all_blob, deduped)

    picked = _pick_best_key(candidates, preferred_kind)
    biz_key = picked["value"] if picked else (user_biz_key.strip() if user_biz_key else "")
    biz_key_source = picked["source"] if picked else ("user" if user_biz_key else "")
    biz_key_kind = picked["kind"] if picked else ""
    log_field = picked.get("log_field", "") if picked else ""

    return {
        "app": app,
        "biz_key": biz_key,
        "biz_key_source": biz_key_source,
        "biz_key_kind": biz_key_kind,
        "log_field": log_field,
        "biz_key_candidates": candidates[:16],
        "scenario": scenario,
        "scenario_source": scenario_source,
        "app_hint": app_hint,
        "log_entry_count": len(pairs),
    }


def infer_db_context(
    logs: dict[str, Any],
    *,
    user_biz_key: str = "",
    user_scenario: str = "default",
    apps: list[str] | None = None,
    code_classes: list[str] | None = None,
) -> dict[str, Any]:
    """
    合并用户输入与日志/代码推断，产出 DB 采集上下文（全局摘要，主用于报告头）。

    实际连库请用 infer_db_context_for_app / plan_db_investigation 按服务拆分。
    """
    apps = apps or []
    primary = apps[0] if apps else ""
    if primary:
        per = infer_db_context_for_app(
            logs,
            primary,
            user_biz_key=user_biz_key,
            user_scenario=user_scenario,
            code_classes=code_classes,
        )
        pairs = collect_log_messages(logs)
        scenarios: dict[str, str] = {}
        for app in apps:
            app_sc = per.get("scenario") or "default"
            app_msgs = [msg for a, msg in pairs if a == app]
            if app_msgs:
                local_sc, local_hint = _infer_scenario_from_text("\n".join(app_msgs))
                if local_sc != "default" and (local_hint is None or local_hint == app):
                    app_sc = local_sc
            if app_sc == "default" and app == primary and per.get("scenario") != "default":
                app_sc = per["scenario"]
            scenarios[app] = app_sc
        return {
            **{k: v for k, v in per.items() if k != "app"},
            "biz_key_candidates": per.get("biz_key_candidates") or [],
            "scenarios": scenarios or {a: per.get("scenario", "default") for a in apps},
        }

    # fallback：无 apps 时合并全量日志（兼容旧调用）
    pairs = collect_log_messages(logs)
    all_text = "\n".join(msg for _, msg in pairs)
    if code_classes:
        all_text += "\n" + "\n".join(code_classes)

    candidates: list[dict[str, str]] = []
    for _, msg in pairs:
        candidates.extend(_extract_keys_from_text(msg, apps=apps))
    if user_biz_key:
        user_parsed = parse_problem_text(user_biz_key)
        uk = user_parsed.get("biz_key") or user_biz_key.strip()
        if uk:
            kind = "loan_no" if uk.startswith("L") else "order_no" if uk.startswith("O") else "unknown"
            candidates.insert(0, {
                "kind": kind,
                "value": uk,
                "source": "user",
                "log_field": "",
            })

    scenario = user_scenario if user_scenario and user_scenario != "default" else "default"
    scenario_source = "user" if scenario != "default" else "default"
    app_hint: str | None = None

    if scenario == "default":
        sc, hint = _infer_scenario_from_text(all_text)
        if sc != "default":
            scenario = sc
            scenario_source = "logs"
            app_hint = hint

    if scenario == "default" and code_classes:
        sc, hint = _infer_scenario_from_text("\n".join(code_classes))
        if sc != "default":
            scenario = sc
            scenario_source = "code"
            app_hint = hint

    preferred_kind = None
    if scenario == "credit-apply":
        preferred_kind = "order_no"
    elif scenario in ("repay", "privilege-plan"):
        preferred_kind = "loan_no"

    picked = _pick_best_key(candidates, preferred_kind)
    biz_key = picked["value"] if picked else (user_biz_key.strip() if user_biz_key else "")
    biz_key_source = picked["source"] if picked else ("user" if user_biz_key else "")
    biz_key_kind = picked["kind"] if picked else ""
    log_field = picked.get("log_field", "") if picked else ""

    # 按应用细化场景（广扫时 lcs/goa/lps 可能不同）
    scenarios: dict[str, str] = {}
    for app in apps:
        app_sc = scenario if scenario != "default" else "default"
        app_msgs = [msg for a, msg in pairs if a == app]
        if app_msgs:
            local_text = "\n".join(app_msgs)
            local_sc, local_hint = _infer_scenario_from_text(local_text)
            if local_sc != "default" and (local_hint is None or local_hint == app):
                app_sc = local_sc
        if app_sc == "default" and app == apps[0] and scenario != "default":
            app_sc = scenario
        scenarios[app] = app_sc

    if not scenarios and apps:
        scenarios = {a: scenario for a in apps}

    return {
        "biz_key": biz_key,
        "biz_key_source": biz_key_source,
        "biz_key_kind": biz_key_kind,
        "log_field": log_field,
        "biz_key_candidates": candidates[:10],
        "scenario": scenario,
        "scenario_source": scenario_source,
        "scenarios": scenarios,
        "app_hint": app_hint,
    }
