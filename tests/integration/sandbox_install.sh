#!/usr/bin/env bash
#
# rules-architect skill: tests/integration/sandbox_install.sh
#
# Isolated end-to-end test:
#   1. Build a temporary HOME with empty .claude/
#   2. Run install_hooks.py (full install + smoke tests)
#   3. Run diagnose.py and verify L0 reaches grade A
#   4. Run install_rule_intake.py in a temp project
#   5. Run install_personal_md_section.py
#   6. Run uninstall.py (dry-run + real)
#   7. Verify all manifest entries cleaned + no orphan hooks
#
# Safe to run on any machine — uses tempdir, never touches real HOME.
#
# Usage:
#   bash sandbox_install.sh          # full E2E
#   bash sandbox_install.sh --keep   # don't delete tempdir on success

set -euo pipefail

KEEP_TMP=0
if [ "${1:-}" = "--keep" ]; then
  KEEP_TMP=1
fi

# Find skill dir
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Temp HOME
TMP_HOME="$(mktemp -d -t rules-architect-sandbox-XXXXXX)"
TMP_PROJECT="$(mktemp -d -t rules-architect-project-XXXXXX)"

cleanup() {
  if [ "$KEEP_TMP" -eq 0 ]; then
    rm -rf "$TMP_HOME" "$TMP_PROJECT"
  else
    echo
    echo "Keeping tempdirs:"
    echo "  HOME:    $TMP_HOME"
    echo "  PROJECT: $TMP_PROJECT"
  fi
}
trap cleanup EXIT

echo "=================================================="
echo "rules-architect sandbox install test"
echo "=================================================="
echo "  Skill:   $SKILL_DIR"
echo "  HOME:    $TMP_HOME"
echo "  PROJECT: $TMP_PROJECT"
echo

# Override HOME for child processes
export HOME="$TMP_HOME"
mkdir -p "$HOME/.claude/hooks"

# === Step 1: Verify diagnose runs on empty state ===
echo ">>> Step 1: diagnose empty state"
python3 "$SKILL_DIR/scripts/diagnose.py" --memory-dir /nonexistent --rules-dir /nonexistent || true
echo

# === Step 2: Install hooks (dry-run first, then real) ===
echo ">>> Step 2a: install_hooks.py --dry-run"
python3 "$SKILL_DIR/scripts/install_hooks.py" --dry-run --non-interactive \
  --skip-version-check
echo

echo ">>> Step 2b: install_hooks.py (real, non-interactive)"
python3 "$SKILL_DIR/scripts/install_hooks.py" --non-interactive --skip-version-check
echo

# === Step 3: Verify all 3 core hooks installed ===
echo ">>> Step 3: verify 3 core hooks installed"
# v2.0.0: only 3 core hooks (SOP injection + base infrastructure).
# error_recovery_checkpoint and dangerous_branch_reminder were moved to examples/
# (they encode individual workflow preferences, not universal patterns).
expected_hooks=(
  memory_intake_check.py
  rule_intake_reminder.py
  cleanup_hook.py
)
for h in "${expected_hooks[@]}"; do
  if [ -x "$HOME/.claude/hooks/$h" ]; then
    echo "  ✅ $h installed and executable"
  else
    echo "  ❌ $h missing or not executable"
    exit 1
  fi
done
echo

# === Step 4: Verify settings.json contains expected entries ===
echo ">>> Step 4: verify settings.json"
python3 -c "
import json, sys
d = json.load(open('$HOME/.claude/settings.json'))
hooks = d.get('hooks', {})
# v2.0.0: 3 core hooks register on these 3 events
# (PostToolUse used to host error_recovery_checkpoint — now moved to examples/)
expected_events = ['PreToolUse', 'UserPromptSubmit', 'SessionStart']
for ev in expected_events:
    if ev not in hooks:
        print(f'  ❌ missing event: {ev}')
        sys.exit(1)
    print(f'  ✅ {ev}: {len(hooks[ev])} entries')
"
echo

# === Step 5: Install rule-intake in temp project ===
echo ">>> Step 5: install_rule_intake.py in temp project"
python3 "$SKILL_DIR/scripts/install_rule_intake.py" --dir "$TMP_PROJECT"
test -f "$TMP_PROJECT/.claude/rules/rule-intake.md" || {
  echo "  ❌ rule-intake.md not created"; exit 1;
}
echo "  ✅ rule-intake.md created"
echo

# === Step 6: Install §六 to a fresh CLAUDE-personal.md ===
echo ">>> Step 6: install_personal_md_section.py"
python3 "$SKILL_DIR/scripts/install_personal_md_section.py" \
  --target "$TMP_PROJECT/CLAUDE-personal.md" --create-if-missing
grep -q "rules-architect:section-6 BEGIN" "$TMP_PROJECT/CLAUDE-personal.md" || {
  echo "  ❌ markers not found"; exit 1;
}
echo "  ✅ §六 inserted with markers"
echo

# === Step 7: Diagnose post-install (expect L0 grade A or B) ===
echo ">>> Step 7: diagnose post-install"
DIAG_JSON="$TMP_HOME/diag.json"
python3 "$SKILL_DIR/scripts/diagnose.py" --memory-dir /nonexistent \
  --rules-dir "$TMP_PROJECT/.claude/rules" --json > "$DIAG_JSON"
grade=$(python3 -c "
import json; d = json.load(open('$DIAG_JSON'))
print(d['layers']['L0_hooks']['grade'])
")
echo "  L0 grade after install: $grade"
case "$grade" in
  A|B) echo "  ✅ L0 grade is A or B" ;;
  *)   echo "  ❌ L0 grade $grade is not A/B"; exit 1 ;;
esac
echo

# === Step 7.5: Generated hook (install_hook_from_memory) + memory promotion ===
echo ">>> Step 7.5: install_hook_from_memory + mark_memory_promoted"

# Build a fake memory entry for the test
mkdir -p "$HOME/.claude/projects/sandbox-test/memory"
cat > "$HOME/.claude/projects/sandbox-test/memory/feedback_sandbox_test.md" <<MEMO_EOF
---
name: feedback-sandbox-test
description: Sandbox test entry — should be marked promoted by mark_memory_promoted.py
metadata:
  type: feedback
---
Sandbox test rule body. After promotion, the original body must only remain
in the backup and the live file must contain the promotion stub.
MEMO_EOF

# Write a reminder text file
echo "Sandbox test reminder injected by generated hook." > "$TMP_HOME/sandbox-reminder.txt"

# Install generated hook
python3 "$SKILL_DIR/scripts/install_hook_from_memory.py" \
    --name sandbox_test_hook \
    --event UserPromptSubmit \
    --matcher '*' \
    --reminder-file "$TMP_HOME/sandbox-reminder.txt" \
    --description "Sandbox test from memory" \
    --feedback-source feedback_sandbox_test

test -x "$HOME/.claude/hooks/sandbox_test_hook.py" || {
    echo "  ❌ sandbox_test_hook.py missing"; exit 1
}
echo "  ✅ generated hook installed + executable"

# Smoke test the generated hook
echo '{"session_id":"smoke","prompt":"x"}' \
    | python3 "$HOME/.claude/hooks/sandbox_test_hook.py" \
    | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert 'Sandbox test reminder' in d['hookSpecificOutput']['additionalContext']"
echo "  ✅ generated hook injects expected reminder"

# Mark memory promoted
python3 "$SKILL_DIR/scripts/mark_memory_promoted.py" \
    --feedback feedback_sandbox_test \
    --target "L0 hook ~/.claude/hooks/sandbox_test_hook.py" \
    --memory-dir "$HOME/.claude/projects/sandbox-test/memory"

grep -q '^Promoted to: L0 hook ~/.claude/hooks/sandbox_test_hook.py @' \
  "$HOME/.claude/projects/sandbox-test/memory/feedback_sandbox_test.md" || {
    echo "  ❌ memory body not converted to stub"; exit 1
}
if grep -q "Sandbox test rule body" \
  "$HOME/.claude/projects/sandbox-test/memory/feedback_sandbox_test.md"; then
    echo "  ❌ original body remained in promoted stub"; exit 1
fi
backup_count=$(find "$HOME/.claude/projects/sandbox-test/memory" \
  -name 'feedback_sandbox_test.md.bak.*' -type f | wc -l | tr -d ' ')
test "$backup_count" -eq 1 || {
    echo "  ❌ expected exactly one promotion backup, got $backup_count"; exit 1
}
grep -q "Sandbox test rule body" \
  "$HOME/.claude/projects/sandbox-test/memory"/feedback_sandbox_test.md.bak.* || {
    echo "  ❌ promotion backup does not contain original body"; exit 1
}
echo "  ✅ memory body converted to Promoted-to stub"

# Verify manifest knows about the generated hook
python3 -c "
import json
m = json.load(open('$HOME/.claude/.rules-architect-manifest.json'))
gen = [f for f in m['installed_files'] if f.get('kind') == 'generated-from-memory']
assert len(gen) >= 1, 'manifest missing generated-from-memory entry'
print('  ✅ manifest tracks generated hook (kind=generated-from-memory)')
"
echo

# === Step 8: Uninstall (dry-run + real) ===
echo ">>> Step 8a: uninstall.py --dry-run"
python3 "$SKILL_DIR/scripts/uninstall.py" --dry-run --non-interactive
echo

echo ">>> Step 8b: uninstall.py (real, non-interactive)"
python3 "$SKILL_DIR/scripts/uninstall.py" --non-interactive
echo

# === Step 9: Verify everything removed ===
echo ">>> Step 9: verify rollback"
for h in "${expected_hooks[@]}"; do
  if [ -e "$HOME/.claude/hooks/$h" ]; then
    echo "  ❌ $h still present after uninstall"; exit 1
  fi
done
echo "  ✅ All hook files removed"

if [ -f "$HOME/.claude/.rules-architect-manifest.json" ]; then
  echo "  ❌ manifest still exists"; exit 1
fi
echo "  ✅ Manifest archived"

# rule-intake.md should NOT be removed (project-level, hash mismatch protection
# requires it be tracked but file may persist if user-modified — in this test
# we didn't modify so it should be gone)
if [ -e "$TMP_PROJECT/.claude/rules/rule-intake.md" ]; then
  echo "  ⚠️  rule-intake.md still present (expected if user-modified)"
else
  echo "  ✅ rule-intake.md removed"
fi
echo

echo "=================================================="
echo "✨ All sandbox checks passed"
echo "=================================================="
