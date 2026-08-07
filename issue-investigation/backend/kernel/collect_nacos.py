#!/usr/bin/env python3
"""
Nacos 配置只读采集（dev/sit）。

流程（类似 Java 里的 Facade → Client）：
1. discover_nacos：从启动类 @NacosPropertySource 得到 group/dataId 列表
2. _nacos_get：登录 Nacos OpenAPI，按 tenant+group+dataId 拉配置正文
3. collect / collect_multi：组装 JSON 结果，供 inv_runner 写入 evidence.json

命令行示例：
  python3 collect_nacos.py --app lcs --env dev --repo-root /path/to/lcs \\
      --keys pilot.trial.sync.save.fundCodes
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.common import assert_app_supported, assert_env_supported, write_json
from lib.deps import ensure_requests
from lib.discover_nacos import catalog_fallback, discover_from_repo
from lib.env_config import get_nacos_config


def _nacos_login(base_url: str, username: str, password: str) -> str:
    """登录 Nacos，返回 accessToken（可跨多次 GET 复用）。"""
    requests = ensure_requests()
    base = base_url.rstrip("/")
    login_resp = requests.post(
        f"{base}/v1/auth/users/login",
        data={"username": username, "password": password},
        timeout=30,
    )
    login_resp.raise_for_status()
    token = login_resp.json().get("accessToken") or login_resp.json().get("access_token")
    if not token:
        raise RuntimeError("Nacos 登录未返回 accessToken")
    return token


def _nacos_fetch_config(
    base_url: str,
    token: str,
    tenant: str,
    group: str,
    data_id: str,
) -> str:
    """用已有 token 拉取单条配置正文。"""
    requests = ensure_requests()
    base = base_url.rstrip("/")
    url = f"{base}/v1/cs/configs"
    params = {
        "dataId": data_id,
        "group": group,
        "tenant": tenant,
        "accessToken": token,
    }
    resp = requests.get(url, headers={"accesstoken": token}, params=params, timeout=30)
    resp.raise_for_status()
    return resp.text


def _nacos_get(base_url: str, username: str, password: str, tenant: str, group: str, data_id: str) -> str:
    """
    调用 Nacos OpenAPI 读取单条配置（原始字符串）。

    兼容入口：内部 login 一次再 GET。批量场景请用 _nacos_login + _nacos_fetch_config。
    """
    token = _nacos_login(base_url, username, password)
    return _nacos_fetch_config(base_url, token, tenant, group, data_id)


def _parse_property_kv(line: str) -> tuple[str, str] | None:
    """从 properties 行解析 key 与 value。"""
    text = (line or "").strip()
    if not text or text.startswith("#"):
        return None
    for sep in ("=", ":"):
        if sep in text:
            key, val = text.split(sep, 1)
            key, val = key.strip(), val.strip()
            if key:
                return key, val
    return None


def _extract_key_values(lines: list[str], filter_keys: list[str]) -> list[dict]:
    """按请求的 key 提取 key/value 列表（用于报告，不含整份配置）。"""
    items: list[dict] = []
    for req in filter_keys:
        found = False
        for ln in lines:
            if req not in ln:
                continue
            kv = _parse_property_kv(ln)
            if kv:
                items.append({"key": kv[0], "value": kv[1], "requested": req})
            else:
                items.append({"key": req, "value": ln.strip(), "requested": req})
            found = True
            break
        if not found:
            items.append({"key": req, "value": None, "requested": req, "missing": True})
    return items


def _parse_property_key(line: str) -> str | None:
    """从 properties 行解析 key（`key=value` 或 `key:value`）。"""
    kv = _parse_property_kv(line)
    return kv[0] if kv else None


def _match_config_keys(lines: list[str], filter_keys: list[str]) -> tuple[list[str], list[str]]:
    """
    按请求的 key 在配置行中匹配，返回 (matched_lines, matched_keys)。

    matched_keys 为实际 properties 里的 key 名（去重保序）。
    """
    matched_lines: list[str] = []
    matched_keys: list[str] = []
    seen_keys: set[str] = set()
    for req in filter_keys:
        hit = False
        for ln in lines:
            if req not in ln:
                continue
            matched_lines.append(ln)
            prop_key = _parse_property_key(ln) or req
            if prop_key not in seen_keys:
                seen_keys.add(prop_key)
                matched_keys.append(prop_key)
            hit = True
        # 未命中时不写入 matched_keys，checked_keys 由上层记录「曾排查」
        _ = hit
    dedup_lines = list(dict.fromkeys(matched_lines))
    dedup_keys = list(dict.fromkeys(matched_keys))
    return dedup_lines, dedup_keys


def _normalize_content(raw: str) -> tuple[str, str]:
    """
    规范化 Nacos 响应体。

    返回 (content, status)：
    - 空 body → ("", "not_found")
    - 正常 properties 文本 → (text, "ok")
    """
    text = raw or ""
    if not text.strip():
        return "", "not_found"
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
            if isinstance(payload, dict) and payload.get("content") is not None:
                return str(payload["content"]), "ok"
        except json.JSONDecodeError:
            pass
    return text, "ok"


def _resolve_sources(app: str, repo_root: Path | None) -> dict:
    """
    决定本次要拉哪些 Nacos 配置：优先启动类扫描，否则按应用名推导兜底。
    """
    if repo_root and repo_root.is_dir():
        discovered = discover_from_repo(repo_root)
        if discovered.get("sources"):
            return discovered
    fallback = catalog_fallback(app)
    if fallback:
        return {
            "repo_root": str(repo_root) if repo_root else "",
            "startup_classes": [],
            "sources": fallback,
            "discovery": "config",
        }
    return {
        "repo_root": str(repo_root) if repo_root else "",
        "startup_classes": [],
        "sources": [],
        "discovery": "none",
    }


def collect(
    app: str,
    env: str,
    *,
    repo_root: Path | None = None,
    keys: list[str] | None = None,
    output: Path | None = None,
    access_token: str | None = None,
) -> dict:
    """
    采集单个应用的 Nacos 配置（核心入口，类似 XxxCollector.collect()）。

    参数:
        app: 应用名，如 lcs / goa
        env: dev 或 sit
        repo_root: 本地代码仓，用于扫描启动类；可为 None
        keys: 若指定，只保留 properties 行里包含这些 key 的行（模糊包含）
        output: 可选，写入 JSON 文件路径
        access_token: 可选，复用已登录 token（collect_multi 传入）

    返回:
        dict，含 configs 列表，每项含 group/dataId/excerpt/status 等
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    env = assert_env_supported(env)
    assert_app_supported(app)
    if repo_root is not None and not isinstance(repo_root, Path):
        repo_root = Path(repo_root)
    nacos = get_nacos_config(env)
    discovery = _resolve_sources(app, repo_root)
    sources = discovery.get("sources") or []

    filter_keys = [k.strip() for k in (keys or []) if k and k.strip()]
    result: dict = {
        "app": app,
        "env": env,
        "nacos_base": nacos["base_url"],
        "tenant": nacos["tenant"],
        "discovery": discovery.get("discovery"),
        "startup_classes": discovery.get("startup_classes") or [],
        "repo_root": discovery.get("repo_root") or "",
        "mode": "key_check" if filter_keys else "context",
        "checked_keys": filter_keys,
        "matched_keys": [],
        "configs": [],
        "error": None,
    }

    if not sources:
        result["error"] = "未从启动类或配置页发现 Nacos 配置"
        if output:
            write_json(output, result)
        return result

    try:
        token = access_token or _nacos_login(
            nacos["base_url"], nacos["username"], nacos["password"],
        )

        def _fetch_one(item: tuple[int, dict]) -> dict:
            idx, src = item
            group = src["group"]
            data_id = src["dataId"]
            raw = _nacos_fetch_config(
                nacos["base_url"], token, nacos["tenant"], group, data_id,
            )
            content, status = _normalize_content(raw)
            lines = content.splitlines()
            cfg_matched_keys: list[str] = []
            if filter_keys and status == "ok":
                matched_lines, cfg_matched_keys = _match_config_keys(lines, filter_keys)
                excerpt = "\n".join(matched_lines[:80]) if matched_lines else ""
                cfg_mode = "key_check"
                key_values = _extract_key_values(lines, filter_keys)
            else:
                excerpt = ""
                cfg_mode = "context"
                key_values = []
            return {
                "group": group,
                "dataId": data_id,
                "source_file": src.get("source_file") or "",
                "mode": cfg_mode,
                "checked_keys": filter_keys if filter_keys else [],
                "matched_keys": cfg_matched_keys,
                "key_values": key_values,
                "excerpt": excerpt,
                "status": status,
                "truncated": len(content) > len(excerpt) if content else False,
                "_src_order": idx,
            }

        indexed = list(enumerate(sources))
        if len(indexed) <= 1:
            cfgs = [_fetch_one(item) for item in indexed]
        else:
            cfgs = []
            with ThreadPoolExecutor(max_workers=min(8, len(indexed))) as pool:
                futs = [pool.submit(_fetch_one, item) for item in indexed]
                for fut in as_completed(futs):
                    cfgs.append(fut.result())
            cfgs.sort(key=lambda c: c.get("_src_order", 0))

        all_matched_keys: list[str] = []
        for cfg in cfgs:
            cfg.pop("_src_order", None)
            all_matched_keys.extend(cfg.get("matched_keys") or [])
            result["configs"].append(cfg)
        result["matched_keys"] = list(dict.fromkeys(all_matched_keys))
    except Exception as exc:
        result["error"] = str(exc)

    if output:
        write_json(output, result)
    return result


def collect_multi(
    apps: list[str],
    env: str,
    *,
    repo_roots: dict[str, Path | str] | None = None,
    keys: list[str] | None = None,
    output: Path | None = None,
) -> dict:
    """
    批量采集多个应用：登录一次，各应用并行拉配置。

    repo_roots: Map<app, 代码仓Path>，如 {"lcs": Path("/code/lcs")}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    roots = repo_roots or {}
    apps = [a for a in apps if a]
    nacos = get_nacos_config(assert_env_supported(env))
    token = _nacos_login(nacos["base_url"], nacos["username"], nacos["password"])

    def _one(app: str) -> tuple[str, dict]:
        root = Path(roots[app]) if roots.get(app) else None
        return app, collect(app, env, repo_root=root, keys=keys, access_token=token)

    if len(apps) <= 1:
        results = [_one(a) for a in apps]
    else:
        results = []
        with ThreadPoolExecutor(max_workers=min(8, len(apps))) as pool:
            futs = {pool.submit(_one, a): a for a in apps}
            for fut in as_completed(futs):
                results.append(fut.result())
        order = {a: i for i, a in enumerate(apps)}
        results.sort(key=lambda x: order.get(x[0], 999))

    by_app: dict[str, dict] = {}
    configs: list[dict] = []
    for app, one in results:
        by_app[app] = one
        for cfg in one.get("configs") or []:
            configs.append({"app": app, **cfg})
    errors = [x.get("error") for x in by_app.values() if x.get("error")]
    checked_keys = keys or []
    matched_keys: list[str] = []
    for one in by_app.values():
        matched_keys.extend(one.get("matched_keys") or [])
    result = {
        "apps": apps,
        "env": env,
        "mode": "key_check" if checked_keys else "context",
        "checked_keys": checked_keys,
        "matched_keys": list(dict.fromkeys(matched_keys)),
        "by_app": by_app,
        "configs": configs,
        "error": "; ".join(errors) if errors else None,
    }
    if output:
        write_json(output, result)
    return result


def main() -> None:
    """命令行入口（argparse 解析参数后调用 collect）。"""
    parser = argparse.ArgumentParser(description="issue-investigation Nacos 只读")
    parser.add_argument("--app", required=True)
    parser.add_argument("--env", required=True, help="dev 或 sit")
    parser.add_argument("--repo-root", help="服务代码仓根目录，用于扫描启动类")
    parser.add_argument("--keys", help="逗号分隔，仅摘录含这些 key 的行")
    parser.add_argument("--output", "-o")
    args = parser.parse_args()
    keys = [k.strip() for k in args.keys.split(",") if k.strip()] if args.keys else None
    out = Path(args.output) if args.output else None
    repo = Path(args.repo_root) if args.repo_root else None
    result = collect(args.app, args.env, repo_root=repo, keys=keys, output=out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
