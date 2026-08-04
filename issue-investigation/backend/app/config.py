"""平台配置：路径、内核、LLM、Pi sidecar 地址。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KERNEL_DIR = PROJECT_ROOT / "kernel"
DATA_DIR = Path(os.environ.get("INV_DATA_DIR") or PROJECT_ROOT.parent / "data")

# 代码工作区根：业务仓父目录（4 仓所在），kernel 的 repo_roots 基于此解析
WORKSPACE_ROOT = Path(
    os.environ.get("INV_WORKSPACE_ROOT") or "/Users/zhaoxin/code/inner"
)
# 传给内核的 repo_root（任选一仓，sibling 解析向上找到全部）
KERNEL_REPO_ROOT = Path(
    os.environ.get("INV_KERNEL_REPO_ROOT") or WORKSPACE_ROOT / "lcs"
)

PI_BASE_URL = os.environ.get("INV_PI_BASE_URL", "http://127.0.0.1:8700")
PI_TOOL_TOKEN = os.environ.get("INV_PI_TOOL_TOKEN", "local-dev-token")

# 意图门禁 LLM 通道（opencode-go，OpenAI 兼容）
LLM_BASE_URL = os.environ.get(
    "INV_LLM_BASE_URL", "https://opencode.ai/zen/go/v1"
)
LLM_MODEL = os.environ.get("INV_LLM_MODEL", "deepseek-v4-flash")
PI_AGENT_DIR = Path(os.environ.get("INV_PI_AGENT_DIR", Path.home() / ".pi" / "agent"))

TURN_LIMIT = 10

RUNS_DIR = DATA_DIR / "runs"
PI_SESSIONS_DIR = DATA_DIR / "pi-sessions"
for _d in (RUNS_DIR, PI_SESSIONS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def load_llm_api_key() -> str:
    """读取 LLM key：环境变量优先，其次 ~/.pi/agent/auth.json 的 opencode-go。"""
    env_key = os.environ.get("INV_LLM_API_KEY", "").strip()
    if env_key:
        return env_key
    auth = PI_AGENT_DIR / "auth.json"
    if auth.is_file():
        data = json.loads(auth.read_text(encoding="utf-8"))
        cred = (data.get("opencode-go") or {}).get("key") or ""
        if cred:
            return cred
    return ""


def ensure_kernel_on_path() -> None:
    """将 kernel 目录加入 sys.path，供内核脚本互相 import（from lib.xxx / from collect_logs）。"""
    if str(KERNEL_DIR) not in sys.path:
        sys.path.insert(0, str(KERNEL_DIR))
