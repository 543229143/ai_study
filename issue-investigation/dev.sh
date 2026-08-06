#!/usr/bin/env bash
# 一键启动：backend(8600) + opencode sidecar(8700) + pi sidecar(8701) + frontend(5178)
# 引擎选择：INV_AGENT_ENGINE=opencode|pi（默认 opencode，双引擎共存）
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
ENGINE="${INV_AGENT_ENGINE:-opencode}"

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

# 启动前自动清理端口残留进程（上次异常退出/Ctrl+C 之外的场景）
PORTS=(8600 8700 8701 5178 14100)
for PORT in "${PORTS[@]}"; do
  PIDS=$(lsof -ti :$PORT -sTCP:LISTEN 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "[dev] 清理端口 $PORT 残留进程: $PIDS"
    kill -9 $PIDS 2>/dev/null || true
    sleep 1
  fi
done

cleanup() {
  echo "[dev] 停止服务..."
  [ -n "$P1" ] && kill "$P1" 2>/dev/null
  [ -n "$P2" ] && kill "$P2" 2>/dev/null
  [ -n "$P3" ] && kill "$P3" 2>/dev/null
  [ -n "$P4" ] && kill "$P4" 2>/dev/null
  # 子进程（vite/bun/opencode）可能残留，按端口兜底清理
  for PORT in "${PORTS[@]}"; do
    lsof -ti :$PORT -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
  done
}
trap cleanup EXIT
# Ctrl+C / kill 时立即退出（不等待子进程），再由 EXIT 陷阱统一清理
trap 'exit 130' INT TERM

# 两个 agent 引擎同时启动（双引擎共存；后端用 INV_AGENT_ENGINE 选择）
(cd "$ROOT/backend" && exec env INV_AGENT_ENGINE="$ENGINE" .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8600) & P1=$!
(cd "$ROOT/analysis" && exec bun run src/opencode/index.ts) & P2=$!
(cd "$ROOT/analysis" && exec bun run src/pi/index.ts) & P4=$!
(cd "$ROOT/frontend" && exec npm run dev -- --port 5178) & P3=$!

echo "[dev] backend  : http://127.0.0.1:8600  (pid $P1, engine=$ENGINE)"
echo "[dev] opencode : http://127.0.0.1:8700  (pid $P2)"
echo "[dev] pi       : http://127.0.0.1:8701  (pid $P4)"
echo "[dev] frontend : http://localhost:5178  (pid $P3)"
echo "[dev] Ctrl+C 退出全部"

wait
