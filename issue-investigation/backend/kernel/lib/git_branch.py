"""dev/sit 排查前自动对齐本地 Git 分支。

Java 对照：类似部署前 checkout 到目标 profile 对应分支，保证读到的源码与运行环境一致。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

_ENV_BRANCHES = frozenset({"dev", "sit"})


def _run_git(repo: Path, *args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def _is_git_repo(repo: Path) -> bool:
    code, _, _ = _run_git(repo, "rev-parse", "--is-inside-work-tree")
    return code == 0


def get_current_branch(repo: Path) -> str | None:
    code, out, _ = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0 or not out or out == "HEAD":
        return None
    return out


def _local_branch_exists(repo: Path, branch: str) -> bool:
    code, _, _ = _run_git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    return code == 0


def _remote_branch_exists(repo: Path, branch: str, remote: str = "origin") -> bool:
    code, _, _ = _run_git(
        repo, "show-ref", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}",
    )
    return code == 0


def _has_uncommitted_changes(repo: Path) -> bool:
    code, out, _ = _run_git(repo, "status", "--porcelain")
    return code == 0 and bool(out.strip())


def _fetch_origin(repo: Path, remote: str = "origin") -> tuple[bool, str]:
    code, _, err = _run_git(repo, "fetch", remote, "--prune")
    if code == 0:
        return True, ""
    return False, err or "fetch 失败"


def _commits_behind(repo: Path, branch: str, remote: str = "origin") -> int | None:
    ref = f"{remote}/{branch}"
    if not _remote_branch_exists(repo, branch, remote):
        return None
    code, out, _ = _run_git(repo, "rev-list", "--count", f"HEAD..{ref}")
    if code != 0:
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


def sync_branch_with_remote(repo: Path, branch: str, *, dirty: bool) -> dict[str, Any]:
    """
    fetch + pull --ff-only，尽量与 origin/<branch> 对齐。
    不 stash、不 commit；仅 fast-forward，本地未跟踪文件不受影响。
    """
    result: dict[str, Any] = {
        "fetch_ok": False,
        "pull_ok": None,
        "behind_before": None,
        "behind_after": None,
        "message": "",
    }

    fetch_ok, fetch_msg = _fetch_origin(repo)
    result["fetch_ok"] = fetch_ok
    if not fetch_ok:
        result["message"] = f"fetch 失败：{fetch_msg}"
        return result

    behind = _commits_behind(repo, branch)
    result["behind_before"] = behind

    if behind == 0:
        result["pull_ok"] = True
        result["behind_after"] = 0
        result["message"] = "已与 origin 同步"
        return result

    if behind is None:
        result["message"] = f"origin/{branch} 不存在，跳过 pull"
        return result

    code, out, err = _run_git(repo, "pull", "--ff-only", "origin", branch)
    detail = (err or out).strip()
    after = _commits_behind(repo, branch)
    result["behind_after"] = after

    if code == 0:
        result["pull_ok"] = True
        if after == 0:
            result["message"] = f"已 fast-forward 同步（原落后 {behind} commits）"
        else:
            result["message"] = f"pull 完成但仍落后 origin/{branch} {after} commits"
        return result

    result["pull_ok"] = False
    hint = "；可能与本地未提交变更冲突" if dirty else ""
    lag = f"，仍落后 {after} commits" if isinstance(after, int) and after > 0 else ""
    result["message"] = f"pull --ff-only 失败{hint}{lag}：{detail or '未知原因'}"
    return result


def checkout_branch(repo: Path, branch: str) -> tuple[bool, str]:
    """
    切换到目标分支（优先本地分支，否则 tracking origin/<branch>）。

    返回 (ok, message)。
    """
    branch = branch.strip()
    if not branch:
        return False, "分支名为空"

    current = get_current_branch(repo)
    if current == branch:
        return True, f"已在 {branch}"

    if _local_branch_exists(repo, branch):
        code, _, err = _run_git(repo, "checkout", branch)
        if code == 0:
            return True, f"{current or '?'} → {branch}"
        return False, err or f"checkout {branch} 失败"

    if _remote_branch_exists(repo, branch):
        code, _, err = _run_git(repo, "checkout", "-B", branch, f"origin/{branch}")
        if code == 0:
            return True, f"{current or '?'} → {branch}（跟踪 origin/{branch}）"
        return False, err or f"checkout -B {branch} origin/{branch} 失败"

    return False, f"本地与 origin 均无分支 {branch}"


def _has_branch_align_issue(info: dict[str, Any]) -> bool:
    if info.get("status") == "failed":
        return True
    if info.get("fetch_ok") is False:
        return True
    if info.get("pull_ok") is False:
        return True
    behind = info.get("behind_commits")
    return isinstance(behind, int) and behind > 0


def ensure_repo_env_branch(
    repo: Path,
    env: str,
    *,
    sync_remote: bool | None = None,
) -> dict[str, Any]:
    """
    单个代码仓：dev/sit 排查时 checkout 到 env。

    sync_remote:
      - True：始终 fetch/pull
      - False：不访问远端
      - None（默认）：已在目标分支则跳过 fetch（加速）；切分支后仍 sync
        环境变量 ISSUE_INV_GIT_FETCH=1 可强制拉取。
    """
    import os

    env_l = (env or "").strip().lower()
    repo = repo.resolve()
    result: dict[str, Any] = {
        "repo": str(repo),
        "env": env_l,
        "status": "skipped",
        "branch_before": None,
        "branch_after": None,
        "switched": False,
        "fetch_ok": None,
        "pull_ok": None,
        "behind_commits": None,
        "message": "",
    }

    if env_l not in _ENV_BRANCHES:
        result["message"] = f"环境 {env_l} 无需对齐 Git 分支"
        return result

    if not repo.is_dir():
        result["status"] = "failed"
        result["message"] = "代码仓路径不存在"
        return result

    if not _is_git_repo(repo):
        result["status"] = "failed"
        result["message"] = "非 Git 仓库"
        return result

    before = get_current_branch(repo)
    result["branch_before"] = before
    dirty = _has_uncommitted_changes(repo)

    force_fetch = (os.environ.get("ISSUE_INV_GIT_FETCH") or "").strip().lower() in (
        "1", "true", "yes",
    )
    if sync_remote is None:
        do_sync = force_fetch or (before != env_l)
    else:
        do_sync = bool(sync_remote) or force_fetch

    checkout_msg = f"已在 {env_l}"
    if before != env_l:
        ok, checkout_msg = checkout_branch(repo, env_l)
        after = get_current_branch(repo) or env_l
        result["branch_after"] = after
        result["switched"] = ok and before != after
        if not ok:
            result["status"] = "failed"
            hint = "；工作区本地变更与目标分支冲突" if dirty else ""
            result["message"] = f"{checkout_msg}{hint}（未 stash/提交，请手动处理后重试）"
            return result
        if sync_remote is not False:
            do_sync = True
    else:
        result["branch_after"] = before

    if not do_sync:
        result["message"] = (
            f"{checkout_msg}；跳过 fetch（加速；设 ISSUE_INV_GIT_FETCH=1 可强制同步）"
        )
        result["status"] = "ok"
        return result

    sync = sync_branch_with_remote(repo, env_l, dirty=dirty)
    result["fetch_ok"] = sync["fetch_ok"]
    result["pull_ok"] = sync["pull_ok"]
    result["behind_commits"] = sync.get("behind_after")

    parts = [checkout_msg]
    if dirty and result.get("switched"):
        parts.append("工作区本地文件已保留，未 stash/提交")
    if sync.get("message"):
        parts.append(sync["message"])
    result["message"] = "；".join(parts)
    result["status"] = "ok"
    return result


def ensure_repos_on_env_branch(repo_roots: dict[str, Path], env: str) -> dict[str, dict[str, Any]]:
    """批量对齐各应用代码仓分支（线程池并行）。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    items = [(str(app).lower(), Path(path)) for app, path in repo_roots.items()]
    out: dict[str, dict[str, Any]] = {}
    if not items:
        return out
    workers = min(8, len(items))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(ensure_repo_env_branch, path, env): app for app, path in items
        }
        for fut in as_completed(futs):
            app = futs[fut]
            try:
                out[app] = fut.result()
            except Exception as exc:  # noqa: BLE001
                out[app] = {
                    "status": "failed",
                    "env": (env or "").strip().lower(),
                    "repo": "",
                    "message": f"对齐异常: {exc}",
                }
    return out


def format_branch_summary(git_branches: dict[str, dict[str, Any]]) -> str:
    """报告用一行摘要。"""
    parts: list[str] = []
    for app in sorted(git_branches.keys()):
        info = git_branches[app]
        if info.get("status") == "skipped":
            continue
        before = info.get("branch_before") or "?"
        after = info.get("branch_after") or before
        if info.get("status") == "failed":
            parts.append(f"{app} 分支未切换（{info.get('message', before)}）")
        elif info.get("switched"):
            parts.append(f"{app} {before}→{after}")
        else:
            parts.append(f"{app} {after}")
        behind = info.get("behind_commits")
        if isinstance(behind, int) and behind > 0:
            parts.append(f"{app} 落后 origin {behind} commits")
        elif info.get("pull_ok") is True and info.get("switched"):
            parts.append(f"{app} 已同步")
    return "；".join(parts) if parts else ""


def code_scan_apps(evidence: dict) -> set[str]:
    """参与代码扫描的应用集合（repo_roots / by_app）。"""
    code = evidence.get("code") or {}
    apps: set[str] = set()
    for app in code.get("repo_roots") or {}:
        apps.add(str(app).lower())
    for app in code.get("by_app") or {}:
        apps.add(str(app).lower())
    return apps


def branch_failures_for_apps(
    git_branches: dict[str, dict[str, Any]],
    apps: set[str],
) -> list[tuple[str, dict[str, Any]]]:
    """返回指定应用中分支/checkout 失败或未能同步远端的列表 (app, info)。"""
    out: list[tuple[str, dict[str, Any]]] = []
    for app in sorted(apps):
        info = git_branches.get(app) or {}
        if _has_branch_align_issue(info):
            out.append((app, info))
    return out


def is_branch_failed(git_branches: dict[str, dict[str, Any]], app: str) -> bool:
    info = git_branches.get(str(app).lower()) or {}
    return _has_branch_align_issue(info)


def format_branch_failure_block(
    git_branches: dict[str, dict[str, Any]],
    *,
    env: str,
    apps: set[str],
) -> list[str]:
    """报告 §4 用：代码排查涉及且分支未对齐或未能同步远端时的醒目告警块。"""
    env_l = (env or "").strip().lower()
    if env_l not in _ENV_BRANCHES:
        return []
    failures = branch_failures_for_apps(git_branches, apps)
    if not failures:
        return []
    lines = [
        f"> **⚠ 代码分支/版本未对齐**（{len(failures)} 个服务 checkout 失败或未与 `origin/{env_l}` 同步，"
        "代码扫描结果可能与运行环境不一致）",
    ]
    for app, info in failures:
        before = info.get("branch_before") or "?"
        msg = info.get("message") or "分支对齐失败"
        lines.append(f"> - **{app}**：{msg}")
    return lines


def collect_branch_align_warning(ctx: dict, evidence: dict) -> str:
    """
    完成回执用：日志排查触发了代码扫描，且部分服务未能对齐 env 分支/远端时返回告警正文。
    """
    env = (ctx.get("env") or "").strip().lower()
    if env not in _ENV_BRANCHES:
        return ""

    code = evidence.get("code") or {}
    if not (code.get("code_hits") or code.get("by_app") or code.get("repo_roots")):
        return ""

    scan_apps = code_scan_apps(evidence)
    if not scan_apps:
        return ""

    git_branches = evidence.get("git_branches") or ctx.get("git_branches") or {}
    failures = branch_failures_for_apps(git_branches, scan_apps)
    if not failures:
        return ""

    lines = [
        f"以下 {len(failures)} 个服务未能与 `{env}` / `origin/{env}` 完全对齐，"
        f"代码排查可能与 {env} 运行代码不一致：",
    ]
    for app, info in failures:
        msg = info.get("message") or "分支对齐失败"
        lines.append(f"- **{app}**：{msg}")
    return "\n".join(lines)
