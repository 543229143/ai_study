"""
从 Java 启动类扫描 Nacos 配置项（group / dataId）。

Java 对照：
- 扫描目标类似 `LcsServiceApplication` 上的 `@NacosPropertySource`
- 返回 list[dict] 相当于 List<Map<String,String>>
- Path 类似 java.nio.file.Path，指向本地代码仓目录
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# 正则：匹配 @NacosPropertySource(...) 注解块
_ANNOTATION_RE = re.compile(
    r"@NacosPropertySource\s*\((.*?)\)",
    re.DOTALL,
)
_DATA_ID_RE = re.compile(r"""dataId\s*=\s*["']([^"']+)["']""")
_GROUP_ID_RE = re.compile(r"""groupId\s*=\s*["']([^"']+)["']""")


def _strip_comments(text: str) -> str:
    """去掉 Java 单行注释 //，避免把已注释的 @NacosPropertySource 算进去。"""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _find_service_resource_dirs(repo_root: Path) -> list[Path]:
    """
    查找 *-service 模块下的 src/main/resources 目录。

    例如 lcs 仓 → lcs-service/src/main/resources。
    """
    roots: list[Path] = []
    for svc in sorted(repo_root.glob("*-service")):
        res = svc / "src/main/resources"
        if res.is_dir():
            roots.append(res)
    if not roots:
        res = repo_root / "src/main/resources"
        if res.is_dir():
            roots.append(res)
    return roots


def _read_properties_value(repo_root: Path, key: str) -> str:
    """
    从 application.properties / bootstrap.properties 读取某个 key 的值。

    用于解析 groupId="${spring.application.name}" 这类占位符。
    """
    pattern = re.compile(rf"^{re.escape(key)}\s*=\s*(\S+)", re.MULTILINE)
    for res in _find_service_resource_dirs(repo_root):
        for name in ("application.properties", "bootstrap.properties"):
            path = res / name
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            m = pattern.search(text)
            if m:
                return m.group(1).strip()
    return ""


def _resolve_group_id(expr: str, repo_root: Path) -> str:
    """
    把注解里的 groupId 表达式解析成 Nacos 实际 group 字符串。

    例：${spring.application.name} → lcs-service
    """
    expr = (expr or "").strip()
    if not expr:
        return ""
    if "${spring.application.name}" in expr:
        app_name = _read_properties_value(repo_root, "spring.application.name")
        return app_name or expr
    return expr


def find_startup_classes(repo_root: Path) -> list[Path]:
    """
    定位 Spring Boot 启动类（*Application.java）。

    优先返回带 @SpringBootApplication 的类；找不到则返回全部候选。
    """
    if not repo_root.is_dir():
        return []
    candidates: list[Path] = []
    search_roots = [p / "src/main/java" for p in repo_root.glob("*-service")]
    if not search_roots:
        alt = repo_root / "src/main/java"
        if alt.is_dir():
            search_roots = [alt]
    for java_root in search_roots:
        if not java_root.is_dir():
            continue
        for path in java_root.rglob("*Application.java"):
            candidates.append(path)
    boot: list[Path] = []
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "@SpringBootApplication" in text:
            boot.append(path)
    return boot or candidates


def parse_nacos_sources(java_path: Path, repo_root: Path) -> list[dict[str, str]]:
    """
    解析单个启动类上所有 @NacosPropertySource，返回去重后的配置清单。

    返回字段：group, dataId, source_file（来源 Java 文件路径）。
    """
    try:
        raw = java_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    text = _strip_comments(raw)
    default_group = _read_properties_value(repo_root, "nacos.cofig.group-id")
    if not default_group:
        default_group = _read_properties_value(repo_root, "nacos.config.group-id")

    seen: set[tuple[str, str]] = set()
    sources: list[dict[str, str]] = []
    for block in _ANNOTATION_RE.findall(text):
        m_data = _DATA_ID_RE.search(block)
        if not m_data:
            continue
        data_id = m_data.group(1).strip()
        m_group = _GROUP_ID_RE.search(block)
        group = _resolve_group_id(m_group.group(1), repo_root) if m_group else default_group
        if not group:
            group = _read_properties_value(repo_root, "spring.application.name")
        if not group or not data_id:
            continue
        key = (group, data_id)
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "group": group,
            "dataId": data_id,
            "source_file": str(java_path),
        })
    return sources


def discover_from_repo(repo_root: Path | str) -> dict[str, Any]:
    """
    扫描整个代码仓，汇总所有启动类上的 Nacos 配置（入口方法）。

    返回 discovery=startup_class 表示从 Java 注解发现；none 表示未发现。
    """
    root = Path(repo_root).resolve()
    startup_files = find_startup_classes(root)
    all_sources: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for java_path in startup_files:
        for src in parse_nacos_sources(java_path, root):
            key = (src["group"], src["dataId"])
            if key in seen:
                continue
            seen.add(key)
            all_sources.append(src)
    return {
        "repo_root": str(root),
        "startup_classes": [str(p) for p in startup_files],
        "sources": all_sources,
        "discovery": "startup_class" if all_sources else "none",
    }


def catalog_fallback(app: str) -> list[dict[str, str]]:
    """
    启动类扫描失败时，按应用名推导 Nacos 配置兜底（config/apps.json 已删除该字段）。

    group 同时尝试「应用名」与「应用名-service」（两种命名都存在），
    dataId 尝试 biz.properties 与 application.properties；不存在的组合拉取返回 not_found，不报错。
    """
    app = (app or "").strip().lower()
    if not app:
        return []
    groups = [app, f"{app}-service"]
    data_ids = ["biz.properties", "application.properties"]
    return [
        {"group": group, "dataId": did, "source_file": "config/apps.json"}
        for group in groups
        for did in data_ids
    ]
