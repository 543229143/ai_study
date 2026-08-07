"""
跨应用代码仓解析与排查范围。

决定「本轮查哪些服务」以及「各服务本地代码路径在哪」。
Java 对照：类似根据 scope 枚举要调用的下游服务，并解析各服务 workspace 根目录。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.common import (
    detect_app_from_repo,
    load_platform_app_names,
    load_platform_config,
    skill_root,
)


def load_workspace_layout() -> dict[str, Any]:
    """读取 workspace-layout.json（ sibling 目录、各 app 文件夹名）。"""
    path = skill_root() / "references" / "workspace-layout.json"
    if not path.is_file():
        return {"sibling_dir": "..", "app_repo_names": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def list_cross_flows() -> dict[str, Any]:
    """配置页里定义的跨服务链路（repay/credit-apply 等）。"""
    return load_platform_config().get("cross_service_flows") or {}


def flow_for_scenario(scenario: str) -> str | None:
    """业务场景名 → 跨服务 flow 名（如 repay → repay flow）。"""
    if scenario in list_cross_flows():
        return scenario
    mapping = {
        "credit-apply": "credit-apply",
        "callback": "callback",
        "repay": "repay",
        "privilege-plan": "repay",
    }
    return mapping.get(scenario)


def resolve_apps(primary_app: str, scope: str, scenario: str) -> list[str]:
    """
    根据排查范围解析涉及的应用列表。

    scope 取值：
    - primary_only：只查主应用
    - all：配置页（config/apps.json）里全部 app
    - flow:repay：还款链路涉及的应用
    - auto：按 scenario 推断 flow
    """
    primary_app = primary_app.strip().lower()
    if scope == "primary_only":
        return [primary_app]
    if scope == "all":
        return sorted(load_platform_app_names())
    if scope.startswith("flow:"):
        flow_name = scope[5:]
        flow = list_cross_flows().get(flow_name)
        if flow:
            return list(flow.get("apps") or [primary_app])
    if scope == "auto":
        flow_name = flow_for_scenario(scenario)
        if flow_name:
            flow = list_cross_flows().get(flow_name)
            if flow:
                apps = list(flow.get("apps") or [])
                if primary_app not in apps:
                    apps.insert(0, primary_app)
                return apps
        return [primary_app]
    return [primary_app]


def scenario_for_app(app: str, scope: str, default_scenario: str) -> str:
    """单个应用在跨服务 flow 下的场景子类型（多数为 default）。"""
    if scope.startswith("flow:"):
        flow = list_cross_flows().get(scope[5:], {})
        return (flow.get("scenarios") or {}).get(app, default_scenario)
    if scope == "auto":
        flow_name = flow_for_scenario(default_scenario)
        if flow_name:
            flow = list_cross_flows().get(flow_name, {})
            return (flow.get("scenarios") or {}).get(app, default_scenario)
    return default_scenario if app == default_scenario else default_scenario


def resolve_scenarios(apps: list[str], scope: str, default_scenario: str) -> dict[str, str]:
    """为每个 app 生成 scenario 映射 Map<app, scenario>。"""
    result: dict[str, str] = {}
    for app in apps:
        if scope.startswith("flow:"):
            flow = list_cross_flows().get(scope[5:], {})
            result[app] = (flow.get("scenarios") or {}).get(app, "default")
        elif scope == "auto":
            flow_name = flow_for_scenario(default_scenario)
            if flow_name:
                flow = list_cross_flows().get(flow_name, {})
                result[app] = (flow.get("scenarios") or {}).get(app, "default")
            else:
                result[app] = default_scenario if app == apps[0] else "default"
        else:
            result[app] = default_scenario if app == apps[0] else "default"
    return result


def resolve_repo_roots(primary_repo: Path, apps: list[str]) -> dict[str, Path]:
    """
    为每个 app 解析本地 Git 代码仓绝对路径。

    策略：当前仓 + sibling 目录（../lcs ../goa）按 pom/目录名匹配。
    inv_runner 把结果传给 Nacos 扫描、代码扫描。
    """
    layout = load_workspace_layout()
    names = layout.get("app_repo_names") or {}
    sibling = (primary_repo / layout.get("sibling_dir", "..")).resolve()
    roots: dict[str, Path] = {}

    detected = detect_app_from_repo(primary_repo)
    if detected and detected in apps:
        roots[detected] = primary_repo.resolve()

    for app in apps:
        if app in roots:
            continue
        dir_name = names.get(app, app)
        for base in (sibling, primary_repo.parent):
            candidate = (base / dir_name).resolve()
            if candidate.is_dir() and detect_app_from_repo(candidate) == app:
                roots[app] = candidate
                break
    return roots
