"""DB 排查范围：假设驱动 —— 仅当分析需要库表佐证时才生成/执行 SQL。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.common import load_catalog
from lib.infer_db_binding import filter_mapper_queries
from lib.infer_db_claims import (
    claim_mapper_path_allowed,
    claim_table_allowed,
    claims_for_app,
    extract_verification_claims,
)
from lib.infer_db_context import infer_db_context_for_app
from lib.infer_db_signals import assess_sql_need_for_app, detect_cross_app_sql_hints
from lib.infer_db_sql import infer_queries_from_code

_MAX_MULTI_KEYS_DEFAULT = 3


def _log_entry_count(logs: dict[str, Any], app: str) -> int:
    block = (logs.get("by_app") or {}).get(app) or {}
    return len(block.get("entries") or [])


def schema_to_app(schema: str, investigation_apps: list[str]) -> str | None:
    sch = (schema or "").strip().lower()
    if not sch:
        return None
    for app in investigation_apps:
        cfg = load_catalog().get("apps", {}).get(app) or {}
        if sch == (cfg.get("primary_schema") or app).lower():
            return app
    return None


_schema_to_app = schema_to_app


def resolve_db_apps(
    primary_app: str,
    investigation_apps: list[str],
    logs: dict[str, Any],
    mapper_queries_by_app: dict[str, list],
    db_probes: list[dict] | None = None,
) -> tuple[list[str], list[dict]]:
    """决定本轮实际连库的应用（仅有推断 SQL / 用户 probe 的服务）。"""
    db_probes = list(db_probes or [])
    out_of_scope: list[dict] = []
    db_apps: list[str] = []

    probe_apps: set[str] = set()
    for probe in db_probes:
        app = _schema_to_app(probe.get("schema") or "", investigation_apps)
        if app:
            probe_apps.add(app)

    primary = (primary_app or "").strip().lower()
    if primary:
        has_work = (
            bool(mapper_queries_by_app.get(primary))
            or bool(probe_apps & {primary})
            or bool(db_probes)
        )
        if has_work or mapper_queries_by_app is not None:
            db_apps.append(primary)

    for app in investigation_apps:
        app = app.strip().lower()
        if not app or app == primary:
            continue
        if app in probe_apps:
            if app not in db_apps:
                db_apps.append(app)
            continue
        if mapper_queries_by_app.get(app):
            db_apps.append(app)
            continue
        log_cnt = _log_entry_count(logs, app)
        if log_cnt == 0:
            out_of_scope.append({
                "app": app,
                "skip_reason": "本轮 trace 无该服务日志，非 DB 排查范围",
            })
        else:
            out_of_scope.append({
                "app": app,
                "skip_reason": "有关联日志但无针对该服务的库表佐证假设，跳过 DB",
            })

    ordered: list[str] = []
    seen: set[str] = set()
    for a in db_apps:
        if a and a not in seen:
            seen.add(a)
            ordered.append(a)
    return ordered, out_of_scope


def _infer_from_claim(
    repo_root: Path,
    app: str,
    env: str,
    claim: dict[str, Any],
    fallback_biz: dict[str, Any],
    code_kw: list[str],
) -> tuple[list[tuple[str, str, str]], list[dict], dict[str, Any]]:
    """按单条假设生成 SQL：只查假设关心的表/键。"""
    kind = (claim.get("key_kind") or fallback_biz.get("biz_key_kind") or "").strip()
    values = [v for v in (claim.get("key_values") or []) if v]
    if not values and fallback_biz.get("biz_key") and (
        not claim.get("lock_kind") or kind == (fallback_biz.get("biz_key_kind") or "")
    ):
        if kind and kind == (fallback_biz.get("biz_key_kind") or ""):
            values = [fallback_biz["biz_key"]]
        elif not kind:
            kind = fallback_biz.get("biz_key_kind") or ""
            values = [fallback_biz["biz_key"]] if kind else []

    log_field = {
        "apply_no": "applyNo",
        "acct_no": "acctNo",
        "cust_no": "custNo",
        "loan_no": "loanNo",
        "order_no": "orderNo",
    }.get(kind, fallback_biz.get("log_field") or kind)

    if not kind or not values:
        return [], [{
            "app": app,
            "biz_key": "",
            "biz_key_kind": kind,
            "log_field": log_field,
            "label": "",
            "sql": "",
            "skip_reason": f"假设 `{claim.get('id')}` 未能确定查库业务键",
        }], {}

    max_keys = int(claim.get("max_keys") or _MAX_MULTI_KEYS_DEFAULT)
    max_q = int(claim.get("max_queries") or 2)
    values = values[:max_keys]
    note = (claim.get("description") or claim.get("id") or "").strip()

    def _table_ok(table: str) -> bool:
        return claim_table_allowed(table, claim)

    def _path_ok(name: str) -> bool:
        return claim_mapper_path_allowed(name, claim)

    all_accepted: list[tuple[str, str, str]] = []
    all_skipped: list[dict] = []
    seen_sql: set[str] = set()

    for value in values:
        raw = infer_queries_from_code(
            repo_root,
            app,
            env,
            value,
            kind,
            code_kw + list(claim.get("table_keywords") or []),
            max_queries=max_q,
            table_allow=_table_ok,
            path_allow=_path_ok,
            claim_note=note[:120],
        )
        if not raw:
            all_skipped.append({
                "app": app,
                "biz_key": value,
                "biz_key_kind": kind,
                "log_field": log_field,
                "label": "",
                "sql": "",
                "skip_reason": (
                    f"假设 `{claim.get('id')}`：本仓无匹配表关键字 "
                    f"{claim.get('table_keywords')} 的 Mapper SELECT"
                ),
            })
            continue
        accepted, skipped = filter_mapper_queries(
            raw,
            repo_root=repo_root,
            log_field=log_field,
            biz_key=value,
            biz_key_kind=kind,
            biz_key_source="claim",
            app=app,
        )
        all_skipped.extend(skipped)
        for item in accepted:
            if item[1].strip().lower() in seen_sql:
                continue
            seen_sql.add(item[1].strip().lower())
            all_accepted.append(item)

    binding = {
        "note": (
            f"假设驱动 `{claim.get('id')}`：采用 `{kind}` 查 "
            f"{claim.get('table_keywords')}，共 {len(values)} 个关键业务键"
        ),
        "biz_key": values[0],
        "biz_key_kind": kind,
        "log_field": log_field,
        "biz_keys": values,
        "claim_id": claim.get("id"),
        "claim_description": note,
    }
    return all_accepted, all_skipped, binding


def infer_mapper_queries_for_app(
    repo_root: Path,
    app: str,
    env: str,
    db_inference: dict[str, Any],
    code_kw: list[str] | None,
    *,
    biz_key_source: str = "logs",
    claims: list[dict[str, Any]] | None = None,
) -> tuple[list[tuple[str, str, str]], list[dict], dict[str, Any]]:
    """仅按 verification claims 生成 SQL；无 claim 时不广扫 Mapper。"""
    code_kw = code_kw or []
    app_claims = claims_for_app(claims or [], app)
    if not app_claims:
        return [], [], {
            "note": "无针对本服务的库表佐证假设，不生成 Mapper SQL",
        }

    all_accepted: list[tuple[str, str, str]] = []
    all_skipped: list[dict] = []
    bindings: list[dict] = []
    seen_sql: set[str] = set()

    for claim in app_claims:
        accepted, skipped, binding = _infer_from_claim(
            repo_root, app, env, claim, db_inference, code_kw,
        )
        all_skipped.extend(skipped)
        if binding:
            bindings.append(binding)
        for item in accepted:
            if item[1].strip().lower() in seen_sql:
                continue
            seen_sql.add(item[1].strip().lower())
            all_accepted.append(item)

    sql_binding = bindings[0] if bindings else {}
    if len(bindings) > 1:
        sql_binding["extra_claims"] = [b.get("claim_id") for b in bindings[1:]]
    return all_accepted, all_skipped, sql_binding


def _probes_for_app(db_probes: list[dict], app: str, investigation_apps: list[str]) -> list[dict]:
    out: list[dict] = []
    for probe in db_probes:
        sch = (probe.get("schema") or "").strip().lower()
        if not sch:
            out.append(probe)
            continue
        mapped = _schema_to_app(sch, investigation_apps)
        if mapped == app or (not mapped and app == investigation_apps[0] if investigation_apps else False):
            out.append(probe)
    return out


def _code_keywords_for_app(code: dict[str, Any], app: str) -> list[str]:
    kws: list[str] = []
    for block in code.get("code_hits") or []:
        if block.get("app") == app and block.get("keyword"):
            kws.append(block["keyword"])
    for block in (code.get("by_app") or {}).get(app, {}).get("code_hits") or []:
        if block.get("keyword"):
            kws.append(block["keyword"])
    return list(dict.fromkeys(kws))


def plan_db_investigation(
    investigation_apps: list[str],
    primary_app: str,
    logs: dict[str, Any],
    repo_roots: dict[str, Path],
    code: dict[str, Any],
    env: str,
    *,
    user_biz_key: str = "",
    user_scenario: str = "default",
    db_probes: list[dict] | None = None,
    query_mode: str = "trace_id",
    phenomenon: str = "",
) -> dict[str, Any]:
    """
    【遗留】脚本猜表 DB 计划；默认 inv_runner 已改走 agent_db_plan.json。
    假设驱动：先从日志抽出 claim → 再只对这些目标生成 SQL。
    """
    db_probes = list(db_probes or [])
    primary = (primary_app or "").strip().lower()
    db_inference_by_app: dict[str, dict[str, Any]] = {}
    sql_need_by_app: dict[str, dict[str, Any]] = {}
    code_queries_by_app: dict[str, list[tuple[str, str, str]]] = {}
    mapper_queries_skipped: list[dict] = []
    db_apps: list[str] = []
    db_apps_out_of_scope: list[dict] = []

    claims = extract_verification_claims(logs, investigation_apps)
    cross_hints = detect_cross_app_sql_hints(logs, investigation_apps)

    for app in investigation_apps:
        app = app.strip().lower()
        if not app:
            continue
        app_probes = _probes_for_app(db_probes, app, investigation_apps)
        need = assess_sql_need_for_app(
            app,
            logs,
            code,
            user_biz_key=user_biz_key,
            db_probes=app_probes,
            query_mode=query_mode,
            phenomenon=phenomenon,
            is_primary=(app == primary),
            cross_peer_reasons=cross_hints.get(app) or [],
            verification_claims=claims,
        )
        sql_need_by_app[app] = need

        if not need.get("needed"):
            if _log_entry_count(logs, app) > 0 or app_probes or cross_hints.get(app):
                db_apps_out_of_scope.append({
                    "app": app,
                    "skip_reason": need.get("skip_reason") or "未触发 SQL 辅助排查",
                })
            continue

        root = repo_roots.get(app)
        app_inf = infer_db_context_for_app(
            logs,
            app,
            user_biz_key=user_biz_key if app == primary else "",
            user_scenario=user_scenario,
            code_classes=_code_keywords_for_app(code, app),
        )
        app_inf["sql_need"] = need
        app_inf["verification_claims"] = claims_for_app(claims, app)
        db_inference_by_app[app] = app_inf

        app_claims = claims_for_app(claims, app)
        if not app_inf.get("biz_key") and not app_probes and not any(c.get("key_values") for c in app_claims):
            db_apps_out_of_scope.append({
                "app": app,
                "skip_reason": "有查库假设但未提取到可填充业务键",
            })
            continue

        accepted: list[tuple[str, str, str]] = []
        skipped: list[dict] = []
        binding: dict[str, Any] = {}
        if root and app_claims:
            accepted, skipped, binding = infer_mapper_queries_for_app(
                Path(root),
                app,
                env,
                app_inf,
                _code_keywords_for_app(code, app),
                biz_key_source=app_inf.get("biz_key_source") or "logs",
                claims=claims,
            )
        elif root and app_probes and not app_claims:
            binding = {"note": "仅用户指定表查，不自动生成 Mapper SQL"}
        binding_skipped = [s for s in skipped if (s.get("label") or "").strip()]
        no_select_notes = [s for s in skipped if not (s.get("label") or "").strip()]
        mapper_queries_skipped.extend(binding_skipped)
        if no_select_notes:
            app_inf["mapper_no_select_notes"] = no_select_notes
        if binding:
            app_inf["sql_binding"] = binding
        code_queries_by_app[app] = accepted

        if accepted or app_probes:
            db_apps.append(app)
        else:
            trigger = "；".join(need.get("reasons") or ["假设触发"])
            db_apps_out_of_scope.append({
                "app": app,
                "skip_reason": f"{trigger}，但未生成可执行的定向 SQL",
            })

    primary_inf = db_inference_by_app.get(primary) or {}
    any_needed = any(n.get("needed") for n in sql_need_by_app.values())
    db_inference: dict[str, Any] = {
        **primary_inf,
        "by_app": db_inference_by_app,
        "sql_need_by_app": sql_need_by_app,
        "db_apps": db_apps,
        "db_apps_out_of_scope": db_apps_out_of_scope,
        "sql_investigation_triggered": any_needed,
        "cross_app_sql_hints": cross_hints,
        "verification_claims": claims,
        "code_queries": {
            a: [label for label, _, _ in qs]
            for a, qs in code_queries_by_app.items()
        },
        "mapper_queries_skipped": mapper_queries_skipped,
        "principle": (
            "假设驱动：先从日志判断「缺哪条数据/哪张表需佐证」→ "
            "只对该假设生成定向 SELECT；禁止按 biz_key 广扫无关 Mapper（如 Iou）"
        ),
    }

    return {
        "db_inference": db_inference,
        "db_apps": db_apps,
        "db_apps_out_of_scope": db_apps_out_of_scope,
        "db_inference_by_app": db_inference_by_app,
        "sql_need_by_app": sql_need_by_app,
        "code_queries_by_app": code_queries_by_app,
        "mapper_queries_skipped": mapper_queries_skipped,
        "sql_investigation_triggered": any_needed,
    }
