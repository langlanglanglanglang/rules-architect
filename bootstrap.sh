#!/usr/bin/env bash
#
# rules-architect one-line installer.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash
#
# Options (pass with -s -- before args):
#   curl ... | bash -s -- --install-dir ~/my-workspace --mode A --skip-clone-pull
#
#   --install-dir <path>   Where to clone (default: ~/.claude/skills/rules-architect)
#   --mode <D|C|B|A>       Install mode after clone (default: B = core hooks only)
#                            D = diagnose only, no install
#                            C = path-scoped only
#                            B = hooks only (default, safest install)
#                            A = full (hooks + rule-intake + §六)
#   --skip-install         Just clone; don't run install_hooks.py
#   --skip-clone-pull      If install dir exists, fail instead of git pull
#   --branch <name>        Clone a specific branch (default: main)
#   --tag <name>           Clone a specific tag (e.g. v2.1.1); takes precedence over --branch

set -euo pipefail

REPO_URL="${RULES_ARCHITECT_REPO:-https://github.com/langlanglanglanglang/rules-architect.git}"
INSTALL_DIR="${HOME}/.claude/skills/rules-architect"
MODE="B"
SKIP_INSTALL=0
SKIP_PULL=0
BRANCH="main"
TAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    --skip-clone-pull) SKIP_PULL=1; shift ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --tag) TAG="$2"; shift 2 ;;
    --help|-h)
      sed -n '3,22p' "$0"
      exit 0 ;;
    *) echo "❌ Unknown option: $1" >&2; exit 1 ;;
  esac
done

echo "🪝 rules-architect installer"
echo "   Repo:        $REPO_URL"
echo "   Install dir: $INSTALL_DIR"
echo "   Mode:        $MODE"
[ -n "$TAG" ] && echo "   Tag:         $TAG" || echo "   Branch:      $BRANCH"
echo

# === 1. Check dependencies ===
for cmd in git python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "❌ Required dependency '$cmd' not found in PATH" >&2
    exit 1
  fi
done
echo "  ✅ git + python3 found"

# === 2. Clone or pull ===
if [ -e "$INSTALL_DIR" ]; then
  if [ "$SKIP_PULL" -eq 1 ]; then
    echo "❌ $INSTALL_DIR already exists. Pass --skip-clone-pull=0 to allow update, or rm -rf manually." >&2
    exit 1
  fi
  if [ ! -d "$INSTALL_DIR/.git" ]; then
    echo "❌ $INSTALL_DIR exists but is not a git repo. Refusing to touch. Move it aside first." >&2
    exit 1
  fi
  echo "  ℹ $INSTALL_DIR already exists — pulling latest"
  (cd "$INSTALL_DIR" && git fetch --tags origin && git checkout "$BRANCH" && git pull --ff-only origin "$BRANCH")
else
  mkdir -p "$(dirname "$INSTALL_DIR")"
  echo "  📦 Cloning $REPO_URL → $INSTALL_DIR"
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

# Optional: checkout specific tag
if [ -n "$TAG" ]; then
  echo "  🏷  Checking out tag $TAG"
  (cd "$INSTALL_DIR" && git fetch --tags && git checkout "tags/$TAG")
fi

# === 3. Run install ===
if [ "$SKIP_INSTALL" -eq 1 ]; then
  echo
  echo "✅ Clone done (--skip-install). Run later:"
  echo "   python3 $INSTALL_DIR/scripts/install_hooks.py"
  exit 0
fi

echo
echo "  🚀 Running install (mode: $MODE)..."
echo

case "$MODE" in
  D)
    python3 "$INSTALL_DIR/scripts/diagnose.py"
    ;;
  C)
    python3 "$INSTALL_DIR/scripts/install_rule_intake.py"
    ;;
  B)
    python3 "$INSTALL_DIR/scripts/install_hooks.py" --non-interactive
    ;;
  A)
    python3 "$INSTALL_DIR/scripts/install_hooks.py" --non-interactive
    python3 "$INSTALL_DIR/scripts/install_rule_intake.py"
    python3 "$INSTALL_DIR/scripts/install_personal_md_section.py" --create-if-missing
    ;;
  *)
    echo "❌ Unknown --mode: $MODE (use D|C|B|A)" >&2
    exit 1 ;;
esac

echo
echo "✨ Done! rules-architect installed at $INSTALL_DIR"
echo
echo "📋 Next steps:"
echo "   • Start a new Claude Code session for hooks to load"
echo "   • Run in CC: /rules-architect (for interactive memory migration)"
echo "   • Diagnose:    python3 $INSTALL_DIR/scripts/diagnose.py"
echo "   • Uninstall:   python3 $INSTALL_DIR/scripts/uninstall.py"
