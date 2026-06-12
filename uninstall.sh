#!/usr/bin/env bash
# rules-architect uninstall wrapper. Forwards all args to scripts/uninstall.py.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/scripts/uninstall.py" "$@"
