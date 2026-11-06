#!/usr/bin/env bash
# 从本目录同步到实际生效位置
#   ./install.sh          安装/覆盖
#   ./install.sh --check  只比对，不写入
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mode="${1:-}"

targets=(
  "scripts/opencode-cr|$HOME/.local/bin/opencode-cr|755"
  "scripts/opencode-xcheck|$HOME/.local/bin/opencode-xcheck|755"
  "config/agents/cr.md|$HOME/.config/opencode/agents/cr.md|644"
  "config/commands/cr.md|$HOME/.config/opencode/commands/cr.md|644"
  "config/commands/xcheck.md|$HOME/.config/opencode/commands/xcheck.md|644"
)

dirty=0
for item in "${targets[@]}"; do
  IFS='|' read -r src dst perm <<<"$item"
  src="$here/$src"
  if [[ "$mode" == "--check" ]]; then
    if [[ -f "$dst" ]] && cmp -s "$src" "$dst"; then
      echo "same    $dst"
    else
      echo "differ  $dst"
      dirty=1
    fi
  else
    mkdir -p "$(dirname "$dst")"
    install -m "$perm" "$src" "$dst"
    echo "wrote   $dst"
  fi
done

if [[ "$mode" == "--check" ]]; then
  [[ $dirty -eq 0 ]] || { echo; echo "有差异：跑 ./install.sh 覆盖，或先确认线上改动是否要回流到本目录。"; exit 1; }
  echo; echo "全部一致。"
else
  echo
  echo "完成。重开 opencode（或 opencode reload）后 /cr、/xcheck 生效。"
fi
