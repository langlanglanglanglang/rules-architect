
## ⭐ Opt-in workflow hooks (moved here in v2.0.0)

The following were **shipped by default in v1.x** but moved to `examples/` in v2.0.0
because they encode personal / team workflow preferences, not universal patterns:

| File | Why opt-in |
|---|---|
| `error_recovery_checkpoint.py.example` | "Force a 3-line recovery report" is a personal feedback-cadence preference. Some users prefer terse retries instead. |
| `dangerous_branch_reminder.py.example` | Protected branch list varies wildly between teams (`develop\|test\|master` vs `main` vs trunk-based with no protection). The hook hard-codes a team's git flow. |

To use:
```bash
cp examples/error_recovery_checkpoint.py.example ~/.claude/hooks/error_recovery_checkpoint.py
chmod +x ~/.claude/hooks/error_recovery_checkpoint.py
# Then register in ~/.claude/settings.json under PostToolUse with matcher "Edit|Write|Bash|MultiEdit"
```

Or fork into your project and have a custom install script handle them.

# rules-architect examples

These are **NOT installed** by the skill. They demonstrate how to extend the
generic system with project-specific hooks, rules, and cross-tool shims.

Copy + adapt to your needs. Don't put these directly in `templates/` or they
become part of the generic skill (which defeats the "stay generic" purpose).

## Contents

| File | Purpose |
|---|---|
| `mr_created_reminder.py.example` | PostToolUse hook for **codeup MCP** MR creation — generalize the matcher to your VCS MCP |
| `path-scoped-rule-skeleton.md` | Skeleton for any custom `.claude/rules/*.md` — fill in paths + constraints |
| `extension-hook-skeleton.py` | Minimal hook template (dedupe + audit + JSON output) for your own logic |
| `cross-tool-shim.md` | How to mirror rule placement to codex / gemini via `AGENTS.md` + githooks |

## Recommended workflow for adding your own

1. **5-Q SOP first** (see the SKILL or `.claude/rules/rule-intake.md`) — pick the right layer
2. If **L0 hook**: copy `extension-hook-skeleton.py` → customize matcher + reminder text
3. If **L2 path-scoped**: copy `path-scoped-rule-skeleton.md` → set `paths:` glob
4. Register: for hooks, add entry to `~/.claude/settings.json` (or use a custom
   install script modeled on `install_hooks.py`)
5. Test: dry-run + real-trigger + check `~/.cache/claude-hooks/audit.jsonl`

## Important

- Examples here may reference vendor-specific tools (codeup, lark, etc).
  Strip / replace those when adapting.
- Don't share company-internal hooks in public skill distribution.
