#!/usr/bin/env python3
"""
基于源码的问题排查上下文扫描（不依赖 llm-wiki）。

从日志堆栈 / 关键词在 --repo-root 下 rg 搜索相关类、枚举、Service 实现。
性能：合并 rg、剔除噪声类、按应用包名过滤，避免对 goa 万级 Java 文件扫 18 次。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.common import extract_java_classes_from_logs, write_json

# 日志里常见但无助于定位业务根因的类/片段
_NOISE_SIMPLE = frozenset(
    {
        "AlarmLogUtil",
        "AESUtil",
        "MockAspect",
        "FacadeLogAspect",
        "JavassistProxyFactory",
        "ResponseUtils",
        "StringUtils",
        "CollectionUtils",
        "JSONObject",
        "JSON",
        "Objects",
        "Optional",
        "Supplier",
        "wrap",
        "lambda",
    }
)

_NOISE_PACKAGE_PREFIXES = (
    "java.",
    "javax.",
    "sun.",
    "jdk.",
    "org.springframework.",
    "org.apache.dubbo.",
    "org.apache.catalina.",
    "com.alibaba.",
    "io.kyoto.sole.",
)

# 按仓过滤：只保留「像本服务业务包」的日志类；其余应用的类不在本仓互扫
_APP_PACKAGE_HINTS: dict[str, tuple[str, ...]] = {
    "lps": ("io.kyoto.dam.lps", ".dam.lps."),
    "goa": ("io.kyoto.support.goa", ".support.goa.", ".tpfund."),
    "lcs": ("io.kyoto.pillar.lcs", ".pillar.lcs."),
    "ams": ("io.kyoto.pillar.ams", ".pillar.ams."),
}

_RG_EXCLUDES = (
    "!.cursor/**",
    "!.git/**",
    "!**/target/**",
    "!**/build/**",
    "!**/node_modules/**",
)


def _rg(
    repo_root: Path,
    pattern: str,
    globs: tuple[str, ...] = ("*.java",),
    head_limit: int = 30,
) -> list[dict]:
    hits: list[dict] = []
    for g in globs:
        cmd = [
            "rg",
            "--glob",
            g,
            *[x for ex in _RG_EXCLUDES for x in ("--glob", ex)],
            "-n",
            "--max-count",
            str(head_limit),
            pattern,
            str(repo_root),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        except FileNotFoundError:
            return [{"error": "rg 未安装，跳过代码扫描"}]
        except subprocess.TimeoutExpired:
            return [{"error": f"rg 超时: {pattern[:80]}"}]
        for line in proc.stdout.splitlines()[:head_limit]:
            parts = line.split(":", 2)
            if len(parts) >= 3:
                hits.append(
                    {
                        "file": parts[0],
                        "line": parts[1],
                        "text": parts[2][:300],
                        "file_type": g.lstrip("*").lstrip("."),
                    }
                )
    return hits


def _simple_name(fqcn: str) -> str:
    return fqcn.rsplit(".", 1)[-1]


def _class_simple_from_token(raw: str) -> str | None:
    """从日志 token 提取 Java 简单类名（去掉 [F]、方法后缀、内部类）。"""
    token = (raw or "").strip()
    if token.startswith("[F]"):
        token = token[3:]
    if not token:
        return None
    parts = [p.split("$")[0] for p in token.split(".") if p]
    # 自后向前找首个「大写开头」片段；若最后一段是小写方法名则跳过
    for p in reversed(parts):
        if not p or not p[0].isalpha():
            continue
        if p[0].islower():
            continue  # 方法名 / wrap / lambda
        if p in _NOISE_SIMPLE:
            return None
        if len(p) < 3:
            continue
        return p
    return None


def _fqcn_package_path(raw: str) -> str:
    token = (raw or "").strip()
    if token.startswith("[F]"):
        token = token[3:]
    return token.lower()


def _is_noise_fqcn(raw: str) -> bool:
    pkg = _fqcn_package_path(raw)
    return any(pkg.startswith(p) or f".{p.rstrip('.')}" in pkg for p in _NOISE_PACKAGE_PREFIXES)


def _belongs_to_app(raw: str, app: str | None) -> bool:
    if not app:
        return True
    hints = _APP_PACKAGE_HINTS.get(app.lower())
    if not hints:
        return True
    pkg = _fqcn_package_path(raw)
    return any(h.lower() in pkg for h in hints)


def _build_keywords(
    *,
    log_messages: list[str] | None,
    keywords: list[str] | None,
    app: str | None,
    limit: int = 6,
) -> tuple[list[str], list[str]]:
    """返回 (keywords, classes_from_logs)。按应用过滤 + 去噪声，最多 limit 个检索词。"""
    classes = extract_java_classes_from_logs(log_messages or [])
    user_kw = [k.strip() for k in (keywords or []) if k and str(k).strip()]
    out: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        if not name or name in seen or name in _NOISE_SIMPLE or len(name) < 3:
            return
        # 纯小写片段（方法名）不作为类检索词
        if name[0].islower():
            return
        seen.add(name)
        out.append(name)

    for u in user_kw:
        _add(_class_simple_from_token(u) or u)

    for cls in classes:
        if cls.startswith("[F]") or _is_noise_fqcn(cls):
            continue
        if not _belongs_to_app(cls, app):
            continue
        sn = _class_simple_from_token(cls)
        if sn:
            _add(sn)

    return out[:limit], classes


def _partition_hits_by_keyword(hits: list[dict], keywords: list[str]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {k: [] for k in keywords}
    lower_map = {k.lower(): k for k in keywords}
    for h in hits:
        text = (h.get("text") or "") + " " + (h.get("file") or "")
        text_l = text.lower()
        for lk, orig in lower_map.items():
            if lk in text_l and len(by[orig]) < 8:
                by[orig].append(h)
    return by


def _trace_callers(repo_root: Path, class_name: str, method_name: str | None = None) -> list[dict]:
    """从异常类/方法反向搜索调用者（谁调用了出错的方法）。"""
    simple = _class_simple_from_token(class_name) or _simple_name(class_name)
    if not simple or simple in _NOISE_SIMPLE:
        return []
    patterns = [rf"\.{re.escape(simple)}\.", rf"new\s+{re.escape(simple)}\("]
    if method_name:
        patterns.insert(0, rf"\.{re.escape(method_name)}\(")
    hits: list[dict] = []
    for pat in patterns[:2]:
        for h in _rg(repo_root, pat, globs=("*.java",), head_limit=10):
            if h.get("file") and "error" not in h.get("file", ""):
                hits.append({**h, "relation": "caller"})
    return hits[:8]


def _recent_changes(repo_root: Path, days: int = 3) -> list[dict]:
    """最近 N 天 git 变更文件（缩短窗口，降低 git log 成本）。"""
    try:
        proc = subprocess.run(
            [
                "git",
                "log",
                f"--since={days} days ago",
                "--name-only",
                "--pretty=format:---%h %s",
                "--",
                "*.java",
                "*.xml",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    changed: dict[str, list[str]] = {}
    current_commit = ""
    for raw in proc.stdout.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("---"):
            current_commit = line[3:].strip()
        elif current_commit:
            changed.setdefault(line, []).append(current_commit)
    return [{"file": k, "commits": v[:3]} for k, v in list(changed.items())[:80]]


def _scan_mapper_xml(repo_root: Path, keywords: list[str]) -> list[dict]:
    if not keywords:
        return []
    safe_kws = [re.escape(k) for k in keywords[:8] if k and len(k) >= 3]
    if not safe_kws:
        return []
    combined = "|".join(safe_kws)
    hits: list[dict] = []
    for h in _rg(repo_root, combined, globs=("*.xml",), head_limit=16):
        if "mapper" in h.get("file", "").lower() or "mybatis" in h.get("file", "").lower():
            for kw in keywords:
                if kw and kw.lower() in h.get("text", "").lower():
                    h = {**h, "keyword": kw}
                    break
            hits.append({**h, "source_type": "mapper_xml"})
    return hits[:12]


def _scan_spring_config(repo_root: Path, keywords: list[str]) -> list[dict]:
    if not keywords:
        return []
    safe_kws = [re.escape(k) for k in keywords[:6] if k and len(k) >= 2]
    if not safe_kws:
        return []
    combined = "|".join(safe_kws)
    hits: list[dict] = []
    for h in _rg(repo_root, combined, globs=("*.properties", "*.yml", "*.yaml"), head_limit=10):
        fn = h.get("file", "").lower()
        if "application" in fn or "bootstrap" in fn or "biz" in fn:
            for kw in keywords:
                if kw and kw.lower() in h.get("text", "").lower():
                    h = {**h, "keyword": kw}
                    break
            hits.append({**h, "source_type": "spring_config"})
    return hits[:8]


def scan(
    repo_root: Path,
    *,
    log_messages: list[str] | None = None,
    keywords: list[str] | None = None,
    app: str | None = None,
    output: Path | None = None,
) -> dict:
    repo_root = Path(repo_root).resolve()
    if not repo_root.is_dir():
        raise SystemExit(f"repo-root 不存在: {repo_root}")

    # 未显式传 app 时用目录名猜
    app_id = (app or repo_root.name).strip().lower() or None
    kw, classes = _build_keywords(
        log_messages=log_messages, keywords=keywords, app=app_id, limit=6
    )

    result: dict = {
        "repo_root": str(repo_root),
        "app": app_id,
        "classes_from_logs": classes,
        "keywords": kw,
        "code_hits": [],
        "mapper_xml_hits": [],
        "spring_config_hits": [],
        "callers": [],
        "recent_changes": [],
    }

    if not kw:
        if output:
            write_json(output, result)
        return result

    # Mapper / Spring：各 1 次合并 rg
    result["mapper_xml_hits"] = _scan_mapper_xml(repo_root, kw)
    result["spring_config_hits"] = _scan_spring_config(repo_root, kw)

    # 类定义 + 引用：各合并为 1 次 rg（原方案每词 2 次，可到 24 次）
    alt = "|".join(re.escape(k) for k in kw)
    class_pat = rf"class\s+(?:{alt})\b"
    ref_pat = rf"\b(?:{alt})\b"
    class_hits_all = _rg(repo_root, class_pat, globs=("*.java",), head_limit=40)
    ref_hits_all = _rg(repo_root, ref_pat, globs=("*.java",), head_limit=24)

    class_by = _partition_hits_by_keyword(class_hits_all, kw)
    ref_by = _partition_hits_by_keyword(ref_hits_all, kw)
    for item in kw:
        ch = class_by.get(item) or []
        rh = (ref_by.get(item) or [])[:8]
        if ch or rh:
            result["code_hits"].append(
                {
                    "keyword": item,
                    "class_definitions": ch,
                    "references": rh,
                }
            )
        if "Exception" in item:
            callers = _trace_callers(repo_root, item)
            if callers:
                result["callers"].append({"keyword": item, "callers": callers})

    changes = _recent_changes(repo_root)
    if changes and result["code_hits"]:
        changed_files = {c["file"] for c in changes}
        for hit in result["code_hits"]:
            for ref in hit.get("references", []) + hit.get("class_definitions", []):
                f = ref.get("file", "")
                base = f.split("/")[-1]
                for cf in changed_files:
                    if cf.endswith(base) or f.endswith(cf.split("/")[-1]):
                        hit["recently_changed"] = True
                        hit["change_commits"] = [c for c in changes if c["file"] == cf][:3]
                        break
        result["recent_changes"] = changes[:40]

    if output:
        write_json(output, result)
    return result


def scan_multi(
    repo_roots: dict[str, Path],
    *,
    log_messages: list[str] | None = None,
    keywords: list[str] | None = None,
    output: Path | None = None,
) -> dict:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    by_app: dict[str, dict] = {}
    merged_hits: list[dict] = []
    items = [(app, root) for app, root in repo_roots.items()]

    def _one(app: str, root: Path) -> tuple[str, dict]:
        if not root.is_dir():
            return app, {"error": f"代码仓不存在: {root}"}
        # 按应用过滤关键词，避免 lps/goa 交叉全量互扫
        return app, scan(
            root,
            log_messages=log_messages,
            keywords=keywords,
            app=app,
        )

    if not items:
        result = {"repo_roots": {}, "by_app": {}, "code_hits": [], "keywords": keywords or []}
        if output:
            write_json(output, result)
        return result

    # 仓少时串行往往更快（避免磁盘上多路 rg 互抢）；>2 再并行
    if len(items) <= 2:
        for app, root in items:
            a, one = _one(app, root)
            by_app[a] = one
            for block in one.get("code_hits") or []:
                merged_hits.append({"app": a, **block})
    else:
        workers = min(4, len(items))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_one, app, root) for app, root in items]
            for fut in as_completed(futs):
                app, one = fut.result()
                by_app[app] = one
                for block in one.get("code_hits") or []:
                    merged_hits.append({"app": app, **block})

    result = {
        "repo_roots": {k: str(v) for k, v in repo_roots.items()},
        "by_app": by_app,
        "code_hits": merged_hits,
        "keywords": keywords or [],
    }
    if output:
        write_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="issue-investigation 代码上下文扫描")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--keywords", help="逗号分隔关键词")
    parser.add_argument("--log-file", help="从 collect_logs 输出的 JSON 读取 message")
    parser.add_argument("--app", help="应用标识，用于按包名过滤日志类")
    parser.add_argument("--output", "-o")
    args = parser.parse_args()

    messages: list[str] = []
    if args.log_file:
        data = json.loads(Path(args.log_file).read_text(encoding="utf-8"))
        for e in data.get("entries", []):
            if e.get("message"):
                messages.append(e["message"])

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()] if args.keywords else []
    out = Path(args.output) if args.output else None
    result = scan(
        Path(args.repo_root),
        log_messages=messages,
        keywords=keywords,
        app=args.app,
        output=out,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
