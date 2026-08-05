#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_ROOT="$(mktemp -d)"
TMP_HOME="$TMP_ROOT/home"
TMP_SOURCE="$TMP_ROOT/source"
TMP_BIN="$TMP_ROOT/bin"
trap 'rm -rf "$TMP_ROOT"' EXIT

mkdir -p "$TMP_HOME" "$TMP_SOURCE" "$TMP_BIN" "$TMP_HOME/.codex"
cp -R "$REPO_ROOT/." "$TMP_SOURCE/"
python3 - "$TMP_SOURCE/.git" <<'PY'
import shutil
import sys

shutil.rmtree(sys.argv[1], ignore_errors=True)
PY
git -C "$TMP_SOURCE" init -q
git -C "$TMP_SOURCE" branch -M main
git -C "$TMP_SOURCE" config user.name "rules-architect test"
git -C "$TMP_SOURCE" config user.email "rules-architect@example.invalid"
git -C "$TMP_SOURCE" add -A
git -C "$TMP_SOURCE" commit -qm "bootstrap fixture"

cat > "$TMP_BIN/claude" <<'EOF'
#!/usr/bin/env bash
echo "2.1.0 (Claude Code)"
EOF
cat > "$TMP_BIN/codex" <<'EOF'
#!/usr/bin/env bash
echo "codex-cli 0.146.0"
EOF
chmod +x "$TMP_BIN/claude" "$TMP_BIN/codex"

cat > "$TMP_HOME/.codex/hooks.json" <<'EOF'
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "other-tool",
        "hooks": [{"type": "command", "command": "python3 /existing/hook.py"}]
      }
    ]
  }
}
EOF

HOME="$TMP_HOME" \
PATH="$TMP_BIN:$PATH" \
RULES_ARCHITECT_REPO="$TMP_SOURCE" \
bash "$REPO_ROOT/bootstrap.sh" \
  --platforms claude,codex \
  --mode B \
  --non-interactive

CLAUDE_SKILL="$TMP_HOME/.claude/skills/rules-architect"
CODEX_SKILL="$TMP_HOME/.agents/skills/rules-architect"
test -f "$CLAUDE_SKILL/SKILL.md"
test -L "$CODEX_SKILL"
test "$CLAUDE_SKILL/SKILL.md" -ef "$CODEX_SKILL/SKILL.md"

for hook_name in memory_intake_check.py rule_intake_reminder.py cleanup_hook.py; do
  test -x "$TMP_HOME/.claude/hooks/$hook_name"
  test -x "$TMP_HOME/.codex/hooks/$hook_name"
done

python3 - "$TMP_HOME" <<'PY'
import json
import sys
from pathlib import Path

home = Path(sys.argv[1])
expected = {
    "memory_intake_check.py",
    "rule_intake_reminder.py",
    "cleanup_hook.py",
}

def commands(config_path):
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return {
        hook.get("command", "")
        for groups in data.get("hooks", {}).values()
        for group in groups
        for hook in group.get("hooks", [])
    }

claude_commands = commands(home / ".claude" / "settings.json")
codex_commands = commands(home / ".codex" / "hooks.json")
assert all(
    any(command.endswith("/" + name) for command in claude_commands)
    for name in expected
)
assert all(
    any(command.endswith("/" + name) for command in codex_commands)
    for name in expected
)
assert "python3 /existing/hook.py" in codex_commands

manifest = json.loads(
    (home / ".claude" / ".rules-architect-manifest.json").read_text(
        encoding="utf-8"
    )
)
assert expected <= {
    Path(item["path"]).name
    for item in manifest.get("installed_files", [])
}
assert expected <= {
    Path(item["path"]).name
    for item in manifest.get("codex_installed_files", [])
}
PY

CLAUDE_ONLY_HOME="$TMP_ROOT/claude-only-home"
CODEX_ONLY_HOME="$TMP_ROOT/codex-only-home"
mkdir -p "$CLAUDE_ONLY_HOME" "$CODEX_ONLY_HOME"

HOME="$CLAUDE_ONLY_HOME" \
PATH="$TMP_BIN:$PATH" \
RULES_ARCHITECT_REPO="$TMP_SOURCE" \
bash "$REPO_ROOT/bootstrap.sh" \
  --platforms claude \
  --mode B \
  --non-interactive >/dev/null
test -f "$CLAUDE_ONLY_HOME/.claude/skills/rules-architect/SKILL.md"
test -x "$CLAUDE_ONLY_HOME/.claude/hooks/memory_intake_check.py"
test ! -e "$CLAUDE_ONLY_HOME/.agents/skills/rules-architect"
test ! -e "$CLAUDE_ONLY_HOME/.codex/hooks/memory_intake_check.py"

HOME="$CODEX_ONLY_HOME" \
PATH="$TMP_BIN:$PATH" \
RULES_ARCHITECT_REPO="$TMP_SOURCE" \
bash "$REPO_ROOT/bootstrap.sh" \
  --platforms codex \
  --mode B \
  --non-interactive >/dev/null
test -f "$CODEX_ONLY_HOME/.agents/skills/rules-architect/SKILL.md"
test -x "$CODEX_ONLY_HOME/.codex/hooks/memory_intake_check.py"
test ! -e "$CODEX_ONLY_HOME/.claude/skills/rules-architect"
test ! -e "$CODEX_ONLY_HOME/.claude/hooks/memory_intake_check.py"

# A stale standalone CLI must not block Codex desktop Hook installation. The
# app runtime and the executable found in PATH are not necessarily identical.
cat > "$TMP_BIN/codex" <<'EOF'
#!/usr/bin/env bash
echo "codex-cli 0.100.0"
EOF
chmod +x "$TMP_BIN/codex"
OLD_CLI_HOME="$TMP_ROOT/old-cli-home"
mkdir -p "$OLD_CLI_HOME"
HOME="$OLD_CLI_HOME" \
PATH="$TMP_BIN:$PATH" \
RULES_ARCHITECT_REPO="$TMP_SOURCE" \
bash "$REPO_ROOT/bootstrap.sh" \
  --platforms codex \
  --mode B \
  --non-interactive >/dev/null
test -x "$OLD_CLI_HOME/.codex/hooks/memory_intake_check.py"

echo "bootstrap platform matrix integration: passed"
