#!/usr/bin/env bash
# 可选的无值守循环。默认保守：小轮数、强熔断、绝不 push。
#
# 用法：
#   MAX=5 AGENT_CMD="codex exec" ./scripts/loop.sh
#
# 前置：
#   - 仓库根有 AGENTS.md 和 PROMPT.md
#   - docs/plan.md 里有 "- [ ]" 条目（全文计数，示例请用 "> - [ ]" 包起来）
#   - 当前不在 main/master，且工作区干净
#
# 退出码：
#   0 计划清空（或 agent 明确 COMPLETE）
#   1 前置条件不满足
#   2 连续无产出，熔断
#   3 达到最大轮数

set -euo pipefail

PLAN="${PLAN:-docs/plan.md}"
PROMPT="${PROMPT:-PROMPT.md}"
AGENT_CMD="${AGENT_CMD:-codex exec}"
MAX="${MAX:-5}"
STALL="${STALL:-2}"

die() { echo "[loop] $*" >&2; exit 1; }

[ -f "$PLAN" ]   || die "缺少 $PLAN"
[ -f "$PROMPT" ] || die "缺少 $PROMPT"
[ -f AGENTS.md ] || die "缺少 AGENTS.md"

branch="$(git rev-parse --abbrev-ref HEAD)"
case "$branch" in
  main|master) die "拒绝在 $branch 上循环，请先切功能分支" ;;
esac

[ -z "$(git status --porcelain)" ] || die "工作区不干净，先提交或 stash"

remaining() { grep -c '^- \[ \]' "$PLAN" 2>/dev/null || true; }

left="$(remaining)"
[ "$left" -gt 0 ] || { echo "[loop] 计划已清空，无需运行"; exit 0; }

echo "[loop] 分支=$branch 待办=$left 最大轮数=$MAX 熔断=$STALL"
last="$(git rev-parse HEAD)"
stalled=0

for i in $(seq 1 "$MAX"); do
  left="$(remaining)"
  if [ "$left" -eq 0 ]; then
    echo "[loop] 计划清空，退出"
    exit 0
  fi

  echo "[loop] ── 第 $i/$MAX 轮，剩 $left 项"
  # 每轮全新上下文：把提示词管道给 agent
  $AGENT_CMD < "$PROMPT" || echo "[loop] agent 非零退出，检查输出"

  now="$(git rev-parse HEAD)"
  if [ "$now" = "$last" ]; then
    stalled=$((stalled + 1))
    echo "[loop] 本轮无提交（连续 $stalled 次）"
  else
    stalled=0
    last="$now"
    echo "[loop] 本轮提交 $(git log -1 --format='%h %s')"
  fi

  if [ "$stalled" -ge "$STALL" ]; then
    echo "[loop] 连续 $STALL 轮无产出，熔断。请看 plan 和最后一条 checkpoint" >&2
    exit 2
  fi
done

echo "[loop] 达到最大轮数 $MAX，停止（未 push）" >&2
exit 3
