#!/usr/bin/env bash
# 一键启动三进程：backend(8000) + analysis(8100) + frontend(5173)
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$ROOT/backend/.venv" ]; then
  echo "[dev] 创建 backend venv..."
  python3 -m venv "$ROOT/backend/.venv"
  "$ROOT/backend/.venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt"
fi

if [ ! -d "$ROOT/analysis/node_modules" ]; then
  echo "[dev] 安装 analysis 依赖..."
  (cd "$ROOT/analysis" && bun install --ignore-scripts)
fi

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "[dev] 安装 frontend 依赖..."
  (cd "$ROOT/frontend" && npm install --silent)
fi

cleanup() {
  [ -n "$P1" ] && kill "$P1" 2>/dev/null
  [ -n "$P2" ] && kill "$P2" 2>/dev/null
  [ -n "$P3" ] && kill "$P3" 2>/dev/null
}
trap cleanup EXIT

(cd "$ROOT/backend" && exec .venv/bin/uvicorn app.main:app --port 8000) & P1=$!
(cd "$ROOT/analysis" && exec bun run src/index.ts) & P2=$!
(cd "$ROOT/frontend" && exec npm run dev -- --port 5173) & P3=$!

echo "[dev] backend  : http://127.0.0.1:8000  (pid $P1)"
echo "[dev] analysis : http://127.0.0.1:8100  (pid $P2)"
echo "[dev] frontend : http://localhost:5173  (pid $P3)"
echo "[dev] Ctrl+C 退出全部"

wait
