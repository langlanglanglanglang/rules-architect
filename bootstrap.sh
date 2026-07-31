#!/usr/bin/env bash
#
# rules-architect one-line installer.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash
#
# Options (pass with -s -- before args):
#   curl ... | bash -s -- --platforms claude,codex --mode B
#
#   --platforms <value>   claude, codex, or claude,codex (default: prompt;
#                         both when no TTY is available)
#   --install-dir <path>  Canonical clone location (default: selected platform
#                         skill directory; Claude directory when both selected)
#   --mode <D|C|B|A>      Install mode after clone (default: B = core hooks)
#                          D = diagnose only, no hook install
#                          C = Claude path-scoped rule only
#                          B = selected-platform hooks (default)
#                          A = B + Claude path-scoped rule + §六
#   --skip-install        Install/link selected skills, but skip hooks/rules
#   --skip-clone-pull     If install dir exists, fail instead of git pull
#   --non-interactive     Do not prompt; default to both platforms and safely
#                         skip hook conflicts
#   --branch <name>       Clone a specific branch (default: main)
#   --tag <name>          Clone a specific tag; takes precedence over --branch

set -euo pipefail

REPO_URL="${RULES_ARCHITECT_REPO:-https://github.com/langlanglanglanglang/rules-architect.git}"
INSTALL_DIR=""
INSTALL_DIR_SET=0
PLATFORMS=""
MODE="B"
SKIP_INSTALL=0
SKIP_PULL=0
NON_INTERACTIVE=0
BRANCH="main"
TAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --platforms) PLATFORMS="$2"; shift 2 ;;
    --install-dir) INSTALL_DIR="$2"; INSTALL_DIR_SET=1; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    --skip-clone-pull) SKIP_PULL=1; shift ;;
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --tag) TAG="$2"; shift 2 ;;
    --help|-h)
      sed -n '3,25p' "$0"
      exit 0 ;;
    *) echo "❌ Unknown option: $1" >&2; exit 1 ;;
  esac
done

normalize_platforms() {
  local value
  value="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  case "$value" in
    claude|1) printf '%s' "claude" ;;
    codex|2) printf '%s' "codex" ;;
    both|3|claude,codex|codex,claude|1,2|2,1)
      printf '%s' "claude,codex" ;;
    *)
      echo "❌ Invalid --platforms value: $1 (use claude, codex, or claude,codex)" >&2
      return 1 ;;
  esac
}

select_platforms() {
  local choice
  if [ -n "$PLATFORMS" ]; then
    PLATFORMS="$(normalize_platforms "$PLATFORMS")"
    return
  fi
  if [ "$NON_INTERACTIVE" -eq 0 ] && [ -r /dev/tty ] && [ -w /dev/tty ]; then
    printf '%s\n' "请选择安装目标（可多选）：" > /dev/tty
    printf '%s\n' "  [ ] 1. Claude Code（Skill + Hook）" > /dev/tty
    printf '%s\n' "  [ ] 2. Codex（Skill + Hook）" > /dev/tty
    printf '%s' "输入 1、2 或 1,2 [默认 1,2]：" > /dev/tty
    IFS= read -r choice < /dev/tty || choice=""
    PLATFORMS="$(normalize_platforms "${choice:-1,2}")"
  else
    PLATFORMS="claude,codex"
  fi
}

platform_selected() {
  case ",$PLATFORMS," in
    *",$1,"*) return 0 ;;
    *) return 1 ;;
  esac
}

select_platforms

# === 1. Check dependencies and resolve paths ===
for cmd in git python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "❌ Required dependency '$cmd' not found in PATH" >&2
    exit 1
  fi
done

CLAUDE_SKILL_DIR="${HOME}/.claude/skills/rules-architect"
CODEX_SKILL_DIR="${HOME}/.agents/skills/rules-architect"
if [ "$INSTALL_DIR_SET" -eq 0 ]; then
  if platform_selected claude; then
    INSTALL_DIR="$CLAUDE_SKILL_DIR"
  else
    INSTALL_DIR="$CODEX_SKILL_DIR"
  fi
fi
INSTALL_DIR="$(python3 - "$INSTALL_DIR" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"

echo "🪝 rules-architect installer"
echo "   Repo:        $REPO_URL"
echo "   Platforms:   $PLATFORMS"
echo "   Install dir: $INSTALL_DIR"
echo "   Mode:        $MODE"
[ -n "$TAG" ] && echo "   Tag:         $TAG" || echo "   Branch:      $BRANCH"
echo
echo "  ✅ git + python3 found"

validate_skill_target() {
  local target_dir="$1"
  if [ "$target_dir" = "$INSTALL_DIR" ]; then
    return
  fi
  if [ -e "$target_dir" ] || [ -L "$target_dir" ]; then
    if [ -e "$INSTALL_DIR" ] && [ "$target_dir" -ef "$INSTALL_DIR" ]; then
      return
    fi
    echo "❌ Skill target already exists and points elsewhere: $target_dir" >&2
    echo "   Move it aside or choose a matching --install-dir." >&2
    exit 1
  fi
}

if platform_selected claude; then
  validate_skill_target "$CLAUDE_SKILL_DIR"
fi
if platform_selected codex; then
  validate_skill_target "$CODEX_SKILL_DIR"
fi

# === 2. Clone or pull canonical source ===
if [ -e "$INSTALL_DIR" ]; then
  if [ "$SKIP_PULL" -eq 1 ]; then
    echo "❌ $INSTALL_DIR already exists; --skip-clone-pull refuses to update it." >&2
    exit 1
  fi
  if [ ! -d "$INSTALL_DIR/.git" ]; then
    echo "❌ $INSTALL_DIR exists but is not a git repo. Refusing to touch." >&2
    exit 1
  fi
  if [ -n "$(git -C "$INSTALL_DIR" status --porcelain)" ]; then
    echo "  ⚠️  $INSTALL_DIR has local changes — using it without pull"
  else
    echo "  ℹ $INSTALL_DIR already exists — pulling latest"
    git -C "$INSTALL_DIR" fetch --tags origin
    git -C "$INSTALL_DIR" checkout "$BRANCH"
    git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
  fi
else
  mkdir -p "$(dirname "$INSTALL_DIR")"
  echo "  📦 Cloning $REPO_URL → $INSTALL_DIR"
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

if [ -n "$TAG" ]; then
  echo "  🏷  Checking out tag $TAG"
  git -C "$INSTALL_DIR" fetch --tags
  git -C "$INSTALL_DIR" checkout "tags/$TAG"
fi

# === 3. Install Skill discovery entries ===
install_skill_target() {
  local platform_name="$1"
  local target_dir="$2"
  if [ "$target_dir" = "$INSTALL_DIR" ] || (
    [ -e "$target_dir" ] && [ "$target_dir" -ef "$INSTALL_DIR" ]
  ); then
    echo "  ✅ $platform_name Skill → $target_dir"
    return
  fi
  mkdir -p "$(dirname "$target_dir")"
  ln -s "$INSTALL_DIR" "$target_dir"
  echo "  ✅ $platform_name Skill linked → $target_dir"
}

if platform_selected claude; then
  install_skill_target "Claude" "$CLAUDE_SKILL_DIR"
fi
if platform_selected codex; then
  install_skill_target "Codex" "$CODEX_SKILL_DIR"
fi

if [ "$SKIP_INSTALL" -eq 1 ]; then
  echo
  echo "✅ Skill install complete (--skip-install omitted hooks/rules)."
  exit 0
fi

run_hook_installer() {
  local script_name="$1"
  if [ "$NON_INTERACTIVE" -eq 0 ] && [ -r /dev/tty ] && [ -w /dev/tty ]; then
    python3 "$INSTALL_DIR/scripts/$script_name" < /dev/tty
  else
    python3 "$INSTALL_DIR/scripts/$script_name" --non-interactive
  fi
}

install_selected_hooks() {
  if platform_selected claude; then
    run_hook_installer "install_hooks.py"
  fi
  if platform_selected codex; then
    run_hook_installer "install_codex_hooks.py"
  fi
}

# === 4. Install selected runtime pieces ===
echo
echo "  🚀 Running install (mode: $MODE)..."
echo

case "$MODE" in
  D)
    python3 "$INSTALL_DIR/scripts/diagnose.py"
    ;;
  C)
    if platform_selected claude; then
      python3 "$INSTALL_DIR/scripts/install_rule_intake.py"
    else
      echo "  ℹ Mode C is Claude-specific; Codex Skill is installed, no Hook added."
    fi
    ;;
  B)
    install_selected_hooks
    ;;
  A)
    install_selected_hooks
    if platform_selected claude; then
      python3 "$INSTALL_DIR/scripts/install_rule_intake.py"
      python3 "$INSTALL_DIR/scripts/install_personal_md_section.py" --create-if-missing
    else
      echo "  ℹ Claude-only path rule and §六 skipped for Codex-only install."
    fi
    ;;
  *)
    echo "❌ Unknown --mode: $MODE (use D|C|B|A)" >&2
    exit 1 ;;
esac

echo
echo "✨ Done! rules-architect installed for: $PLATFORMS"
echo
echo "📋 Next steps:"
if platform_selected claude; then
  echo "   • Claude Code: start a new session, then run /rules-architect"
fi
if platform_selected codex; then
  echo '   • Codex: restart if needed, then run $rules-architect or select it in /skills'
  echo "   • Codex Hooks: run /hooks and trust the 3 new commands"
fi
echo "   • Diagnose:  python3 $INSTALL_DIR/scripts/diagnose.py"
echo "   • Uninstall: python3 $INSTALL_DIR/scripts/uninstall.py"
