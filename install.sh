#!/usr/bin/env bash
# rules-architect quick installer wrapper.
#
# Forwards all args to scripts/install_hooks.py with a confirmation prompt
# for first-time users.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=================================================="
echo " rules-architect 安装器"
echo "=================================================="
echo "  安装位置：~/.claude/hooks/，并合并到 ~/.claude/settings.json"
echo "  备份位置：~/.claude/settings.json.bak.<时间戳>"
echo "  卸载命令：bash $SCRIPT_DIR/uninstall.sh"
echo

if [ "${1:-}" != "--non-interactive" ] && [ "${1:-}" != "--dry-run" ]; then
  read -p "是否继续？[y/N] " ans
  case "$ans" in
    y|Y) ;;
    *) echo "已取消"; exit 0 ;;
  esac
fi

exec python3 "$SCRIPT_DIR/scripts/install_hooks.py" "$@"
