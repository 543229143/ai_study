"""issue-investigation 公共工具（路径、JSON、环境校验、文本解析）。

Java 对照：类似 utils + 常量类；无 Spring，均为纯函数。
详见 scripts/PYTHON_FOR_JAVA.md
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


SUPPORTED_ENVS = frozenset({"dev", "sit"})
BLOCKED_ENVS = frozenset({"prod", "production", "prd", "online"})


def skill_root() -> Path:
    """平台内核根目录（本文件在 kernel/lib/ 下，向上两级 = kernel/）。"""
    return Path(__file__).resolve().parents[1]


_CATALOG_CACHE: dict[str, Any] | None = None


def load_catalog() -> dict[str, Any]:
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE
    path = skill_root() / "references" / "app-catalog.json"
    _CATALOG_CACHE = json.loads(path.read_text(encoding="utf-8"))
    return _CATALOG_CACHE


def assert_env_supported(env: str) -> str:
    env = env.strip().lower()
    if env in BLOCKED_ENVS:
        raise SystemExit(
            f"错误: 环境 '{env}' 为生产环境，本技能暂不介入。"
            "生产问题请使用独立生产排查方案。"
        )
    catalog = load_catalog()
    env_cfg = catalog.get("environments", {}).get(env)
    if not env_cfg:
        raise SystemExit(f"错误: 未知环境 '{env}'，支持: dev, sit")
    if not env_cfg.get("supported"):
        raise SystemExit(
            f"错误: 环境 '{env}' 暂未开放。{env_cfg.get('note', '')}"
        )
    return env


def assert_app_supported(app: str) -> dict[str, Any]:
    app = app.strip().lower()
    catalog = load_catalog()
    apps = catalog.get("apps", {})
    if app not in apps:
        raise SystemExit(
            f"错误: 未知应用 '{app}'，支持: {', '.join(sorted(apps))}"
        )
    return apps[app]


def env_var(name: str, default: str = "") -> str:
    val = os.environ.get(name, default)
    return val.strip() if val else default


def now_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


LOG_TIME_FROM_TRACE_ID = "now-3d"
LOG_TIME_FROM_ALERT = "now-24h"
LOG_TIME_FROM_BIZ_KEY = "now-7d"


def default_log_time_from(query_mode: str) -> str:
    """traceId → 3d；告警 → 24h；数据核对（仅业务键）→ 7d。"""
    mode = (query_mode or "").strip().lower()
    if mode == "alert":
        return LOG_TIME_FROM_ALERT
    if mode == "biz_key":
        return LOG_TIME_FROM_BIZ_KEY
    return LOG_TIME_FROM_TRACE_ID


LATEST_REPORT_FILENAME = "investigation-report.md"
LATEST_EVIDENCE_FILENAME = "evidence.json"
LATEST_RECEIPT_FILENAME = "receipt.json"
_RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z$")

# installSkill.sh 合并后的跨工具权威路径（Cursor / Claude / OpenCode 共用）
_SKILL_NAME = "issue-investigation"


def skill_root(*, repo_root: Path | None = None) -> Path:
    """平台内核根目录（kernel/），references/templates 位于其下。"""
    _ = repo_root  # 平台版忽略 repo_root，固定返回内核目录
    return Path(__file__).resolve().parents[1]


def skill_script(name: str, *, repo_root: Path | None = None) -> Path:
    """返回技能 scripts/ 下某脚本的绝对路径。"""
    return skill_root(repo_root=repo_root) / "scripts" / name


def skill_python_cmd(script_name: str, *, repo_root: Path | None = None) -> str:
    """生成行首为 python3 的绝对路径调用（便于终端白名单）。"""
    return f"python3 {skill_script(script_name, repo_root=repo_root)}"


def resolve_form_ui(explicit: str | None = None) -> str:
    """表单 UI：text（「问题排查」默认 HTML）| canvas（仅 /issue-inv）。

    优先级：显式参数 → 环境变量 ISSUE_INV_UI → 默认 text。
    仅 Cursor 斜杠 /issue-inv 应传 --ui canvas 或 export ISSUE_INV_UI=canvas；
    用户打字「问题排查」禁止加 --ui canvas（与宿主是否为 Cursor 无关）。
    """
    raw = (explicit or os.environ.get("ISSUE_INV_UI") or "text").strip().lower()
    if raw in ("canvas", "text"):
        return raw
    if raw in ("auto", ""):
        # auto 仍默认 text，避免非 Cursor 环境卡在 Canvas
        return "text"
    return "text"


def investigation_root(repo_root: Path) -> Path:
    """排查产物根目录。

    平台版：环境变量 ISSUE_INV_DATA_DIR 优先（后端将产物写入 data/）；
    未设置时保持仓库下 `.issue-inv/`（兼容原 CLI 行为）。
    """
    data_dir = (os.environ.get("ISSUE_INV_DATA_DIR") or "").strip()
    if data_dir:
        return Path(data_dir).expanduser().resolve()
    return Path(repo_root) / ".issue-inv"


def investigation_temp_dir(repo_root: Path) -> Path:
    return investigation_root(repo_root) / "temp"


def investigation_report_dir(repo_root: Path) -> Path:
    p = investigation_root(repo_root) / "report"
    p.mkdir(parents=True, exist_ok=True)
    return p


def latest_report_path(repo_root: Path) -> Path:
    return investigation_report_dir(repo_root) / LATEST_REPORT_FILENAME


def latest_evidence_path(repo_root: Path) -> Path:
    return investigation_report_dir(repo_root) / LATEST_EVIDENCE_FILENAME


def prune_stale_temp_runs(repo_root: Path, *, keep_run_ids: frozenset[str] | None = None) -> list[str]:
    """删除 temp 下历史 run 目录（保留 _runtime 与 keep_run_ids）。"""
    keep = keep_run_ids or frozenset()
    temp = investigation_temp_dir(repo_root)
    removed: list[str] = []
    if not temp.is_dir():
        return removed
    for child in temp.iterdir():
        if not child.is_dir() or child.name == "_runtime" or child.name in keep:
            continue
        if _RUN_ID_RE.match(child.name):
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child.name)
    return removed


def publish_investigation_report(repo_root: Path, run_dir: Path, ctx: dict | None = None) -> Path | None:
    """将 temp run 内报告复制到 report/investigation-report.md（固定路径，覆盖）。"""
    _ = ctx  # 保留参数兼容旧调用
    src = run_dir / LATEST_REPORT_FILENAME
    if not src.is_file():
        return None
    report_dir = investigation_report_dir(repo_root)
    dest = report_dir / LATEST_REPORT_FILENAME
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    for legacy in report_dir.glob("*.md"):
        if legacy.name != LATEST_REPORT_FILENAME:
            legacy.unlink(missing_ok=True)
    return dest


def publish_investigation_evidence(repo_root: Path, run_dir: Path) -> Path | None:
    """将 evidence.json 复制到 report/（固定路径，覆盖）。"""
    src = run_dir / LATEST_EVIDENCE_FILENAME
    if not src.is_file():
        return None
    dest = latest_evidence_path(repo_root)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def latest_receipt_path(repo_root: Path) -> Path:
    return investigation_report_dir(repo_root) / LATEST_RECEIPT_FILENAME


def publish_investigation_receipt(repo_root: Path, run_dir: Path) -> Path | None:
    src = run_dir / LATEST_RECEIPT_FILENAME
    if not src.is_file():
        return None
    dest = latest_receipt_path(repo_root)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def ensure_run_dir(repo_root: Path, run_id: str | None = None) -> Path:
    rid = run_id or now_run_id()
    run_dir = investigation_temp_dir(repo_root) / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def write_json(path: Path, data: Any) -> None:
    """原子写入 JSON：先写临时文件，再 os.replace（同卷原子 rename），避免中途崩溃损坏文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)
    fd, tmp = tempfile.mkstemp(suffix=".json", prefix="." + path.name + ".", dir=str(path.parent))
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def extract_java_classes_from_logs(messages: list[str], limit: int = 8) -> list[str]:
    """从日志 message 中提取 Java 类名，供代码扫描。

    返回的类名中，框架类（java.*/sun.*/org.springframework.*）会在末尾附加，
    并以 [F] 前缀标记，不计入 limit。
    """
    pattern = re.compile(r"(?:\[|at\s+|Caused by:\s*)([a-z][a-z0-9_.]*\.[A-Z][A-Za-z0-9_$.]+)")
    found: list[str] = []
    framework: list[str] = []
    seen: set[str] = set()
    for msg in messages:
        for m in pattern.finditer(msg or ""):
            cls = m.group(1).split("$")[0]
            if cls in seen:
                continue
            seen.add(cls)
            if cls.startswith(("java.", "sun.", "org.springframework.")):
                framework.append(f"[F]{cls}")
            else:
                found.append(cls)
            if len(found) >= limit:
                # 把框架类追加在后面
                result = found[:limit] + framework[:limit // 2]
                return result
    result = found[:limit] + framework[:limit // 2]
    return result


def list_apps() -> list[str]:
    return sorted(load_catalog().get("apps", {}).keys())


def detect_app_from_repo(repo_root: Path) -> str | None:
    """从目录名、pom.xml、git 根目录名推断应用标识（lcs/goa/lps/ams）。"""
    repo_root = Path(repo_root).resolve()
    name = repo_root.name.lower()
    apps = list_apps()
    # 目录名精确命中（最快路径，避免扫 pom / 调 git）
    if name in apps:
        return name
    for app in apps:
        if app in name:
            return app
    for pom in sorted(repo_root.glob("*/pom.xml")):
        try:
            text = pom.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for app in apps:
            if f"{app}-service" in text or f"<artifactId>{app}" in text:
                return app
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        top = Path(proc.stdout.strip()).name.lower()
        if top in apps:
            return top
        for app in apps:
            if app in top:
                return app
    return None


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def investigation_runtime(repo_root: Path) -> Path:
    p = investigation_temp_dir(repo_root) / "_runtime"
    p.mkdir(parents=True, exist_ok=True)
    return p


def parse_problem_text(text: str) -> dict[str, str]:
    t = text.strip()
    out = {"raw": t, "query": "", "biz_key": "", "scenario": "default", "hint": ""}
    hex32 = re.search(r"\b([a-f0-9]{32})\b", t, re.I)
    if hex32:
        out["query"] = hex32.group(1)
    for pat in (
        r"(?:order[_ ]?no|orderNo|订单号)[:：=]\s*([A-Za-z0-9_-]+)",
        r"(?:appl[_ ]?no|applNo)[:：=]\s*([A-Za-z0-9_-]+)",
        r"(?:loan[_ ]?no|loanNo|借据)[:：=]\s*([A-Za-z0-9_-]+)",
        r"(?:trace[_ ]?id|request[_ ]?no|requestNo)[:：=]\s*([A-Za-z0-9_-]+)",
        r"\b(O\d{10,})\b",
        r"\b(L\d{10,})\b",
    ):
        m = re.search(pat, t, re.I)
        if m:
            val = m.group(1)
            if not out["biz_key"]:
                out["biz_key"] = val
            if not out["query"]:
                out["query"] = val
    if not out["query"]:
        tokens = re.findall(r"[A-Za-z0-9_-]{8,}", t)
        if tokens:
            out["query"] = tokens[0]
    lower = t.lower()
    if any(k in lower for k in ("授信", "credit", "appl")):
        out["scenario"] = "credit-apply"
    elif any(k in lower for k in ("回调", "callback")):
        out["scenario"] = "callback"
    elif any(k in lower for k in ("还款", "repay", "借据", "plan")):
        out["scenario"] = "repay"
    if "sit" in lower:
        out["hint"] = "sit"
    elif re.search(r"\bdev\b", lower):
        out["hint"] = "dev"
    return out


def parse_alert_text(text: str) -> dict[str, Any]:
    """
    从告警/原始日志片段提取 ES/Kibana 检索词与场景。
    若片段中含 traceId，优先走 trace_id 模式。
    """
    t = text.strip()
    out: dict[str, Any] = {
        "raw": t,
        "query_mode": "alert",
        "query": "",
        "alert_phrases": [],
        "alert_summary": "",
        "biz_key": "",
        "scenario": "default",
        "time_from": "now-24h",
    }

    hex32 = re.search(r"\b([a-f0-9]{32})\b", t, re.I)
    if hex32:
        out["query_mode"] = "trace_id"
        out["query"] = hex32.group(1)
        out["time_from"] = LOG_TIME_FROM_TRACE_ID
        extra = parse_problem_text(t)
        out["biz_key"] = extra.get("biz_key") or ""
        out["scenario"] = extra.get("scenario") or "default"
        out["alert_summary"] = f"告警中含 traceId: {out['query']}"
        return out

    exc = re.search(r"([\w.$]+Exception)", t)
    if exc:
        out["alert_phrases"].append(exc.group(1))
        out["query"] = exc.group(1)

    frames = re.findall(r"at\s+([a-z][\w.$]+)\([^)]+\)", t, re.I)
    seen_phrases: set[str] = set(out["alert_phrases"])
    for frame in frames:
        if frame.startswith(("java.", "sun.", "org.springframework.", "org.apache.")):
            continue
        cls = frame.rsplit(".", 1)[0] if "." in frame else frame
        simple_cls = cls.rsplit(".", 1)[-1]
        for candidate in (cls, simple_cls, frame):
            if candidate and candidate not in seen_phrases:
                seen_phrases.add(candidate)
                out["alert_phrases"].append(candidate)
        if len(out["alert_phrases"]) >= 5:
            break

    for line in t.splitlines():
        s = line.strip()
        if not s:
            continue
        if "ERROR" in s or "Exception" in s or "异常" in s:
            snippet = s[:100]
            if snippet not in seen_phrases:
                out["alert_phrases"].append(snippet)
                seen_phrases.add(snippet)
            break

    biz_frames = [f for f in frames if not f.startswith(("java.", "sun.", "org.springframework."))]
    if biz_frames:
        simple = biz_frames[0].rsplit(".", 1)[0].rsplit(".", 1)[-1]
        if out["query"]:
            out["query"] = f"{out['query']} {simple}"
        else:
            out["query"] = simple

    if not out["query"]:
        for line in t.splitlines():
            s = line.strip()
            if len(s) >= 6:
                out["query"] = s[:120]
                if s[:80] not in seen_phrases:
                    out["alert_phrases"].append(s[:80])
                break

    out["alert_summary"] = (out["query"] or t[:80]).replace("\n", " ")[:120]
    extra = parse_problem_text(t)
    out["biz_key"] = extra.get("biz_key") or ""
    if extra.get("scenario") and extra["scenario"] != "default":
        out["scenario"] = extra["scenario"]
    elif exc and "NullPointer" in exc.group(1):
        pass
    if any(k in t for k in ("回调", "callback", "Callback")):
        out["scenario"] = "callback"
    return out
