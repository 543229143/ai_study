#!/usr/bin/env python3
"""校验 env-connections.json 是否已填写。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.env_config import validate_env_config


def main() -> None:
    parser = argparse.ArgumentParser(description="校验 issue-investigation 环境连接配置")
    parser.add_argument("--env", choices=("dev", "sit"), help="仅校验指定环境，默认 dev+sit")
    args = parser.parse_args()
    envs = [args.env] if args.env else ["dev", "sit"]
    ok = True
    for env in envs:
        issues = validate_env_config(env)
        # es_host 为空仅警告
        warnings = [i for i in issues if "es_host" in i]
        errors = [i for i in issues if "es_host" not in i]
        print(f"=== {env} ===")
        for w in warnings:
            print(f"  [warn] {w}")
        for e in errors:
            print(f"  [FAIL] {e}")
            ok = False
        if not errors and not warnings:
            print("  [OK] 配置完整")
        elif not errors:
            print("  [OK] 必填项已填（ES 可选）")
        print()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
