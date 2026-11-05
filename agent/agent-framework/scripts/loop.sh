#!/usr/bin/env bash
# 可选的无值守循环。默认保守：小轮数、强熔断、绝不 push。
#
# 用法：
#   MAX=5 AGENT_CMD="codex exec" ./scripts/loop.sh
#
# 前置：
#   - 仓库根有 AGENTS.md 和 PROMPT.md
#   - docs/plan.md 含字面标题「## 已知缺口」（改名或删掉都会拒绝运行）
#   - 当前不在 main/master，且工作区干净
#   - tmp/ 已被 gitignore（轮次日志写在这里，否则拒绝运行）
#
# 进展 = 「## 已知缺口」之前的待办变少。只提交、不勾选，算空转。
# 该标题之后的条目（缺口、暂缓）不计入，也不会被自动做。
#
# 退出码：
#   0 没有可执行待办
#   1 前置条件不满足
#   2 连续空转，熔断
#   3 达到最大轮数
#   4 本轮改了文件但没提交

set -euo pipefail

PLAN="${PLAN:-docs/plan.md}"
PROMPT="${PROMPT:-PROMPT.md}"
AGENT_CMD="${AGENT_CMD:-codex exec}"
MAX="${MAX:-5}"
STALL="${STALL:-2}"

die() { echo "[loop] $*" >&2; exit 1; }

posint() {
  case "$2" in
    ''|*[!0-9]*) die "$1 必须是正整数，收到: ${2:-空}" ;;
  esac
  [ "$2" -ge 1 ] || die "$1 必须 >= 1"
}

posint MAX "$MAX"
posint STALL "$STALL"

root="$(git rev-parse --show-toplevel 2>/dev/null)" || die "当前目录不在 git 仓库里"
cd "$root"

[ -f "$PLAN" ]   || die "缺少 $PLAN"
[ -f "$PROMPT" ] || die "缺少 $PROMPT"
[ -f AGENTS.md ] || die "缺少 AGENTS.md"

branch="$(git rev-parse --abbrev-ref HEAD)"
case "$branch" in
  main|master) die "拒绝在 $branch 上循环，请先切功能分支" ;;
esac

[ -z "$(git status --porcelain)" ] || die "工作区不干净，先提交或 stash"

# 只认字面标题，不认近义词。改名会让缺口被当成待办，所以缺标题直接失败。
if ! grep -q '^## 已知缺口' "$PLAN"; then
  die "plan.md 缺少标题「## 已知缺口」。循环靠它把缺口和待办分开，改名或删掉都会把缺口当成待办。请保留这个标题，节内可以空着。"
fi

# 只数该标题之前的未勾选项。
remaining() {
  awk '
    /^## 已知缺口/ { exit }
    /^- \[ \]/ { c++ }
    END { print c + 0 }
  ' "$PLAN"
}

left="$(remaining)"
[ "$left" -gt 0 ] || { echo "[loop] 没有可执行待办（已知缺口不计），无需运行"; exit 0; }

# 日志先于 agent 落盘。没被忽略的话，后面的「脏即停」会栽在自己的日志上。
if ! git check-ignore -q tmp/loop/round.log 2>/dev/null; then
  die "tmp/ 未被 gitignore，轮次日志会把工作区弄脏。在 .gitignore 加上 tmp/，或重跑 init.sh。"
fi
mkdir -p tmp/loop

echo "[loop] 分支=$branch 待办=$left 最大轮数=$MAX 熔断=$STALL"
stalled=0

for i in $(seq 1 "$MAX"); do
  left="$(remaining)"
  if [ "$left" -eq 0 ]; then
    echo "[loop] 可执行待办已清空，退出"
    exit 0
  fi

  echo "[loop] ── 第 $i/$MAX 轮，剩 $left 项"
  log="tmp/loop/round-${i}.log"
  set +e
  # AGENT_CMD 按空格拆开，以便写成 AGENT_CMD="codex exec"
  # shellcheck disable=SC2086
  $AGENT_CMD < "$PROMPT" 2>&1 | tee "$log"
  rc=${PIPESTATUS[0]}
  set -e
  if [ "$rc" -ne 0 ]; then
    echo "[loop] agent 退出码 ${rc}，输出见 $log"
  fi

  if [ -n "$(git status --porcelain)" ]; then
    echo "[loop] 本轮有未提交改动，停止。先提交或还原，再决定要不要续跑。" >&2
    git status --porcelain >&2
    exit 4
  fi

  now="$(remaining)"
  if [ "$now" -lt "$left" ]; then
    stalled=0
    echo "[loop] 本轮待办 $left → ${now}，最近提交 $(git log -1 --format='%h %s')"
  else
    stalled=$((stalled + 1))
    echo "[loop] 本轮待办没减少（仍为 ${now}，连续 $stalled 次）"
  fi

  if [ "$stalled" -ge "$STALL" ]; then
    echo "[loop] 连续 $STALL 轮待办没减少，熔断。请看 plan 和最后一条 checkpoint" >&2
    exit 2
  fi
done

echo "[loop] 达到最大轮数 ${MAX}，停止（未 push）" >&2
exit 3
