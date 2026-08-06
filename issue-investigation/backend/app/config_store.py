"""平台应用配置（config/apps.json）：应用清单/数据库名/业务键规则/业务术语。

- 应用名 → 数据库名（空则取应用名）；一个应用可配多个业务键规则（pattern → 表/字段）
- 业务术语 → 应用名（可多选）
- 保存即时生效（每次读取文件），页面配置通过 GET/PUT /config
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from . import config

CONFIG_PATH = Path(
    os.environ.get("INV_APP_CONFIG_PATH") or config.PROJECT_ROOT.parent / "config" / "apps.json"
)

_lock = threading.Lock()

DEFAULT_CONFIG: dict[str, Any] = {
    "apps": {
        "lps": {
            "db_name": "",
            "biz_keys": [
                {"pattern": r"CR\d{19}", "table": "ap_fund_appl", "field": "appl_no"},
            ],
        },
        "lcs": {
            "db_name": "",
            "biz_keys": [
                {"pattern": r"LO\d{19}", "table": "pilot_loan", "field": "loan_no"},
            ],
        },
        "goa": {"db_name": "", "biz_keys": []},
        "ams": {"db_name": "", "biz_keys": []},
    },
    "terms": [
        {"term": "授信号", "apps": ["lps", "lcs", "ams"]},
        {"term": "借据号", "apps": ["lcs", "lps"]},
        {"term": "账户", "apps": ["ams", "lcs"]},
    ],
    "system_terms": [
        {
            "term": "日志id",
            "meaning": "ES 的 32 位十六进制 traceId（=requestNo），用于 ES 日志与跨服务链路检索",
        },
        {
            "term": "机构日志",
            "meaning": "goa系统  优先搜索es并带io.kyoto.support.goa.aspect.FacadeLogAspect",
        },
    ],
}


def _default_config() -> dict[str, Any]:
    import copy

    return copy.deepcopy(DEFAULT_CONFIG)


def load_config() -> dict[str, Any]:
    """读取配置；文件不存在或损坏时写默认配置并返回。"""
    with _lock:
        if not CONFIG_PATH.is_file():
            return save_config(_default_config())
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "apps" not in data:
                return save_config(_default_config())
            return data
        except (json.JSONDecodeError, OSError):
            return save_config(_default_config())


def validate_config(cfg: dict[str, Any]) -> list[str]:
    """结构校验，返回错误列表（空 = 通过）。"""
    errors: list[str] = []
    apps = cfg.get("apps")
    if not isinstance(apps, dict) or not apps:
        return ["apps 至少需要一个应用"]
    for name, app_cfg in apps.items():
        if not isinstance(app_cfg, dict):
            errors.append(f"应用 {name}: 配置必须是对象")
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", str(name)):
            errors.append(f"应用名 {name!r} 非法（小写字母开头，仅字母/数字/_-）")
        db = app_cfg.get("db_name") or ""
        if db and not re.fullmatch(r"[A-Za-z0-9_]+", str(db)):
            errors.append(f"应用 {name}: 数据库名 {db!r} 非法")
        for i, rule in enumerate(app_cfg.get("biz_keys") or []):
            pat = (rule or {}).get("pattern") or ""
            try:
                re.compile(pat)
            except re.error as exc:
                errors.append(f"应用 {name}: 业务键规则 #{i + 1} 正则非法: {exc}")
            if "\\\\" in pat:
                errors.append(
                    f"应用 {name}: 业务键规则 #{i + 1} 疑似双重转义（{pat!r}）："
                    "应写单反斜杠，如 \\d 匹配数字，而不是 \\\\d"
                )
            for k in ("table", "field"):
                v = (rule or {}).get(k) or ""
                if v and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(v)):
                    errors.append(f"应用 {name}: 业务键规则 #{i + 1} 的 {k} 非法: {v!r}")
    terms = cfg.get("terms")
    if not isinstance(terms, list):
        errors.append("terms 必须是数组")
        return errors
    for i, t in enumerate(terms):
        term = (t or {}).get("term") or ""
        ta = (t or {}).get("apps") or []
        if not term:
            errors.append(f"术语 #{i + 1}: 缺少术语名称")
        if not isinstance(ta, list) or not ta:
            errors.append(f"术语 {term!r}: 至少选择一个应用")
        else:
            for a in ta:
                if a not in apps:
                    errors.append(f"术语 {term!r}: 应用 {a} 不在应用清单中")
    sys_terms = cfg.get("system_terms")
    if sys_terms is None:
        errors.append("system_terms 必须是数组")
        return errors
    if not isinstance(sys_terms, list):
        errors.append("system_terms 必须是数组")
        return errors
    for i, st in enumerate(sys_terms):
        term = (st or {}).get("term") or ""
        meaning = (st or {}).get("meaning") or ""
        if not term:
            errors.append(f"系统术语 #{i + 1}: 缺少术语名称")
        if not meaning:
            errors.append(f"系统术语 {term!r}: 缺少系统含义")
    return errors


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """校验并保存；errors 非空则拒绝写入。"""
    errors = validate_config(cfg)
    if errors:
        return {"errors": errors, "saved": False, "config": None}
    with _lock:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)
    return {"errors": [], "saved": True, "config": cfg}


def app_names() -> list[str]:
    return list(load_config().get("apps", {}).keys())


def db_name_of(app: str) -> str:
    """应用配置的数据库名（空 → 由调用方回退 schemas/应用名）。"""
    cfg = load_config()
    return str((cfg.get("apps", {}).get(app) or {}).get("db_name") or "")


def detect_hits(text: str) -> dict[str, Any]:
    """从文本识别命中：显式应用词 / 业务键规则 / 业务术语。

    返回:
        explicit_app: 文本中显式出现的应用名（用户明确指定，主 app 优先用它）
        biz_hits: [{app, table, field, pattern}] 全部命中的业务键规则（去重）
        term_apps: 术语命中的应用名（去重）
    """
    cfg = load_config()
    apps = cfg.get("apps", {})
    t = text or ""
    low = t.lower()

    explicit_app = ""
    for a in apps:
        if re.search(rf"\b{re.escape(a)}\b", low):
            explicit_app = a
            break

    biz_hits: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for a, app_cfg in apps.items():
        for rule in app_cfg.get("biz_keys") or []:
            pat = (rule or {}).get("pattern") or ""
            if not pat:
                continue
            try:
                m = re.search(pat, t)
            except re.error:
                continue
            if not m:
                continue
            key = (a, rule.get("table"), rule.get("field"))
            if key in seen:
                continue
            seen.add(key)
            biz_hits.append({
                "app": a,
                "table": rule.get("table") or "",
                "field": rule.get("field") or "",
                "pattern": pat,
            })

    term_apps: list[str] = []
    for item in cfg.get("terms") or []:
        term = (item or {}).get("term") or ""
        if term and term in t:
            for a in (item or {}).get("apps") or []:
                if a not in term_apps:
                    term_apps.append(a)

    # 系统术语命中：用户词 → 系统含义（供 agent 理解，不映射应用）
    sys_term_hits: list[dict[str, str]] = []
    for item in cfg.get("system_terms") or []:
        term = (item or {}).get("term") or ""
        meaning = (item or {}).get("meaning") or ""
        if term and meaning and term in t:
            sys_term_hits.append({"term": term, "meaning": meaning})

    return {
        "explicit_app": explicit_app,
        "biz_hits": biz_hits,
        "term_apps": term_apps,
        "sys_term_hits": sys_term_hits,
    }


def priority_apps(hits: dict[str, Any], default: str | None = None) -> list[str]:
    """优先扫描应用（命中者在前，不排除其他）。"""
    names = app_names()
    ordered: list[str] = []
    for a in [h.get("app") for h in hits.get("biz_hits") or []] + (hits.get("term_apps") or []):
        if a and a not in ordered:
            ordered.append(a)
    # 用户显式指定的应用永远置首位（明确意图 > 规则命中）
    if hits.get("explicit_app") and hits["explicit_app"] in ordered:
        ordered.remove(hits["explicit_app"])
    if hits.get("explicit_app"):
        ordered.insert(0, hits["explicit_app"])
    if default and default not in ordered:
        ordered.insert(0, default)
    return ordered + [a for a in names if a not in ordered]


def build_hint(hits: dict[str, Any]) -> str:
    """识别提示（注入消息头部，供 agent 生成查询/扫描计划时参考）。"""
    parts: list[str] = []
    for h in hits.get("biz_hits") or []:
        parts.append(
            f"{h['app']}.{h['table']}.{h['field']}" if h["table"] else h["app"]
        )
    pri = priority_apps(hits)
    text = ""
    if parts:
        text += f"业务键命中表字段: {', '.join(parts)}；"
    if hits.get("term_apps"):
        text += f"术语命中应用: {', '.join(hits['term_apps'])}；"
    for st in hits.get("sys_term_hits") or []:
        text += f"术语「{st['term']}」= {st['meaning']}；"
    if pri:
        text += f"优先排查应用 {','.join(pri[:3])} 的日志/代码（其他应用有线索也排查）"
    return text
