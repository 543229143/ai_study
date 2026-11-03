#!/usr/bin/env bash
# 把框架装进一个项目。幂等：已存在的文件不覆盖。
#
# 用法：
#   ./scripts/init.sh ~/code/your-project

set -euo pipefail

FRAMEWORK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-}"

if [ -z "$TARGET" ]; then
  echo "用法: $0 <项目目录>" >&2
  exit 1
fi
[ -d "$TARGET" ] || { echo "目录不存在: $TARGET" >&2; exit 1; }
TARGET="$(cd "$TARGET" && pwd)"

[ -d "$TARGET/.git" ] || echo "提示：$TARGET 不是 git 仓库，建议先 git init"

rel() { echo "${1#"$TARGET"/}"; }

copy() {
  local src="$1" dst="$2"
  if [ -e "$dst" ]; then
    echo "跳过（已存在）: $(rel "$dst")"
    if [ "$(basename "$dst")" = "AGENTS.md" ]; then
      echo "  ↑ 已存在 AGENTS.md：请手动把框架版的「验收」「停止」两节合并进去，这两节是核心。"
    fi
  else
    cp "$src" "$dst"
    echo "写入: $(rel "$dst")"
  fi
}

copy "$FRAMEWORK_DIR/AGENTS.md" "$TARGET/AGENTS.md"
copy "$FRAMEWORK_DIR/PROMPT.md" "$TARGET/PROMPT.md"

mkdir -p "$TARGET/docs/checkpoints" "$TARGET/docs/tasks" "$TARGET/docs/design" "$TARGET/docs/contracts"
copy "$FRAMEWORK_DIR/templates/plan.md" "$TARGET/docs/plan.md"
echo "建立: docs/checkpoints/  docs/tasks/  docs/design/  docs/contracts/"

# gitignore
GI="$TARGET/.gitignore"
touch "$GI"
for entry in "tmp/" ".local/"; do
  grep -qxF "$entry" "$GI" 2>/dev/null || echo "$entry" >> "$GI"
done
echo "确保 .gitignore 含 tmp/ 和 .local/"

echo
echo "装好了。下一步："
echo "  1. 打开 $(rel "$TARGET/docs/plan.md")，把第一条改成你的任务"
echo "     —— 必须有「判定证据」，写不出就换一件"
echo "  2. 手动跑一轮：cd $TARGET && codex exec < PROMPT.md"
echo "     （或把 PROMPT.md 的内容直接粘给任何 agent）"
echo "  3. 它做完后看 diff，按框架目录里的 templates/checkpoint.md 补记录并提交"
echo
echo "先手动跑 3 片，再用 scripts/loop.sh。"
