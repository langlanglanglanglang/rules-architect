#!/usr/bin/env bash
#
# rules-architect 一键安装器。
#
# 用法：
#   curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash
#
# 选项（通过 -s -- 传入参数）：
#   curl ... | bash -s -- --platforms claude,codex --mode B
#
#   --platforms <值>      claude、codex 或 claude,codex（默认弹出选择；
#                         无 TTY 时默认两者都装）
#   --install-dir <路径>  主仓库克隆位置（默认使用所选平台的 Skill 目录；
#                         同时选择时使用 Claude 目录）
#   --mode <D|C|B|A>      克隆后的安装模式（默认 B = 核心 Hook）
#                          D = 仅诊断，不安装 Hook
#                          C = 仅安装 Claude 路径规则
#                          B = 安装所选平台的 Hook（默认）
#                          A = B + Claude 路径规则 + §六
#   --skip-install        安装或链接所选 Skill，但跳过 Hook 和规则
#   --skip-clone-pull     安装目录存在时直接失败，不执行 git pull
#   --non-interactive     不弹出提示；默认安装两个平台并安全跳过 Hook 冲突
#   --branch <名称>       克隆指定分支（默认 main）
#   --tag <名称>          克隆指定标签；优先级高于 --branch

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
    *) echo "❌ 未知选项：$1" >&2; exit 1 ;;
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
      echo "❌ --platforms 值无效：$1（请使用 claude、codex 或 claude,codex）" >&2
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
    echo "❌ PATH 中未找到必需依赖：$cmd" >&2
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

echo "🪝 rules-architect 安装器"
echo "   仓库：$REPO_URL"
echo "   目标平台：$PLATFORMS"
echo "   安装目录：$INSTALL_DIR"
echo "   安装模式：$MODE"
[ -n "$TAG" ] && echo "   标签：$TAG" || echo "   分支：$BRANCH"
echo
echo "  ✅ 已找到 git 和 python3"

validate_skill_target() {
  local target_dir="$1"
  if [ "$target_dir" = "$INSTALL_DIR" ]; then
    return
  fi
  if [ -e "$target_dir" ] || [ -L "$target_dir" ]; then
    if [ -e "$INSTALL_DIR" ] && [ "$target_dir" -ef "$INSTALL_DIR" ]; then
      return
    fi
    echo "❌ Skill 目标已存在且指向其他位置：$target_dir" >&2
    echo "   请先移动该目录，或选择与之匹配的 --install-dir。" >&2
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
    echo "❌ $INSTALL_DIR 已存在；--skip-clone-pull 禁止更新它。" >&2
    exit 1
  fi
  if [ ! -d "$INSTALL_DIR/.git" ]; then
    echo "❌ $INSTALL_DIR 已存在但不是 Git 仓库，已拒绝改动。" >&2
    exit 1
  fi
  if [ -n "$(git -C "$INSTALL_DIR" status --porcelain)" ]; then
    echo "  ⚠️  $INSTALL_DIR 存在本地修改，将直接使用且不拉取更新"
  else
    echo "  ℹ $INSTALL_DIR 已存在，正在拉取最新版本"
    git -C "$INSTALL_DIR" fetch --tags origin
    git -C "$INSTALL_DIR" checkout "$BRANCH"
    git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
  fi
else
  mkdir -p "$(dirname "$INSTALL_DIR")"
  echo "  📦 正在克隆 $REPO_URL → $INSTALL_DIR"
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

if [ -n "$TAG" ]; then
  echo "  🏷  正在检出标签 $TAG"
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
  echo "  ✅ $platform_name Skill 已链接 → $target_dir"
}

if platform_selected claude; then
  install_skill_target "Claude" "$CLAUDE_SKILL_DIR"
fi
if platform_selected codex; then
  install_skill_target "Codex" "$CODEX_SKILL_DIR"
fi

if [ "$SKIP_INSTALL" -eq 1 ]; then
  echo
  echo "✅ Skill 安装完成（--skip-install 已跳过 Hook 和规则）。"
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
echo "  🚀 正在执行安装（模式：${MODE}）……"
echo

case "$MODE" in
  D)
    python3 "$INSTALL_DIR/scripts/diagnose.py"
    ;;
  C)
    if platform_selected claude; then
      python3 "$INSTALL_DIR/scripts/install_rule_intake.py"
    else
      echo "  ℹ C 模式仅适用于 Claude；Codex Skill 已安装，但未添加 Hook。"
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
      echo "  ℹ 当前仅安装 Codex，已跳过 Claude 专用路径规则和 §六。"
    fi
    ;;
  *)
    echo "❌ 未知 --mode：${MODE}（请使用 D、C、B 或 A）" >&2
    exit 1 ;;
esac

echo
echo "✨ 安装完成！rules-architect 已安装到：$PLATFORMS"
echo
echo "📋 后续步骤："
if platform_selected claude; then
  echo "   • Claude Code：启动新会话，然后运行 /rules-architect"
fi
if platform_selected codex; then
  echo '   • Codex：如有需要请重启，然后运行 $rules-architect，或在 /skills 中选择它'
  echo "   • Codex Hook：运行 /hooks，并信任新增的 3 条命令"
fi
echo "   • 诊断：python3 $INSTALL_DIR/scripts/diagnose.py"
echo "   • 卸载：python3 $INSTALL_DIR/scripts/uninstall.py"
