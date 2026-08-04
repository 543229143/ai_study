"""运行时按需自动安装 Python 依赖（首次采集时触发，无需使用者预装）。"""
from __future__ import annotations

import importlib
import subprocess
import sys

_PIP_SPECS: dict[str, str] = {
    "requests": "requests>=2.28",
    "pymysql": "pymysql>=1.0",
}

_INSTALLED: set[str] = set()


def ensure_package(name: str):
    """确保包可 import；缺失时用当前解释器 pip 自动安装。"""
    if name in _INSTALLED:
        return importlib.import_module(name)
    try:
        mod = importlib.import_module(name)
        _INSTALLED.add(name)
        return mod
    except ImportError:
        pass

    spec = _PIP_SPECS.get(name, name)
    base_cmd = [sys.executable, "-m", "pip", "install", spec, "-q"]
    # macOS/Homebrew PEP 668：依次尝试 user / break-system-packages
    flag_sets = ([], ["--user"], ["--break-system-packages"], ["--user", "--break-system-packages"])
    last_err = ""
    for flags in flag_sets:
        cmd = base_cmd + flags
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"自动安装 {name} 超时") from e
        if proc.returncode == 0:
            mod = importlib.import_module(name)
            _INSTALLED.add(name)
            return mod
        last_err = (proc.stderr or proc.stdout or "").strip()[:400]

    raise RuntimeError(
        f"无法自动安装依赖 {name}（{spec}）。"
        f"请手动执行: {sys.executable} -m pip install {spec}\n{last_err}"
    )


def ensure_requests():
    return ensure_package("requests")


def ensure_pymysql():
    return ensure_package("pymysql")


def ensure_collect_deps() -> None:
    """证据采集前预装 requests + pymysql（已装则几乎零开销）。"""
    # 热路径：两边 import 成功即返回，避免反复进 ensure_package
    try:
        import requests  # noqa: F401
        import pymysql  # noqa: F401
        _INSTALLED.update(("requests", "pymysql"))
        return
    except ImportError:
        pass
    ensure_requests()
    ensure_pymysql()
