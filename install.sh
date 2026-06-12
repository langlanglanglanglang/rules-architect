#!/usr/bin/env bash
# rules-architect quick installer wrapper.
#
# Forwards all args to scripts/install_hooks.py with a confirmation prompt
# for first-time users.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=================================================="
echo " rules-architect installer"
echo "=================================================="
echo "  Will install to: ~/.claude/hooks/ and merge into ~/.claude/settings.json"
echo "  Backup at:       ~/.claude/settings.json.bak.<ts>"
echo "  Uninstall via:   bash $SCRIPT_DIR/uninstall.sh"
echo

if [ "${1:-}" != "--non-interactive" ] && [ "${1:-}" != "--dry-run" ]; then
  read -p "Continue? [y/N] " ans
  case "$ans" in
    y|Y) ;;
    *) echo "Aborted"; exit 0 ;;
  esac
fi

exec python3 "$SCRIPT_DIR/scripts/install_hooks.py" "$@"
