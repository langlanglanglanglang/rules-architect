# rules-architect tests

## Structure

```
tests/
├── README.md                            # This file
├── integration/
│   └── sandbox_install.sh               # E2E: install → verify → uninstall
└── unit/                                # (TBD — diagnose.py unit tests)
```

## Running

### Integration: sandbox install/uninstall round-trip

5-minute end-to-end test. Builds an isolated temporary `$HOME`, installs all
hooks + rule-intake + §六 section, verifies state via diagnose, then uninstalls
and verifies precise rollback.

```bash
bash tests/integration/sandbox_install.sh
# Or with --keep to preserve tempdirs on success:
bash tests/integration/sandbox_install.sh --keep
```

Exit code 0 = all assertions passed.
Exit code != 0 = some assertion failed; details printed.

### What sandbox_install.sh checks

| # | Assertion |
|---|---|
| 1 | `diagnose.py` runs on empty state without error |
| 2 | `install_hooks.py --dry-run` produces plan, modifies nothing |
| 3 | `install_hooks.py` (real) creates 5 hooks + settings.json entries |
| 4 | All 5 expected hook files are executable |
| 5 | `settings.json` contains PostToolUse / PreToolUse / UserPromptSubmit / SessionStart |
| 6 | `install_rule_intake.py` creates `.claude/rules/rule-intake.md` |
| 7 | `install_personal_md_section.py` inserts §六 with markers |
| 8 | `diagnose.py` post-install reports L0 grade A or B |
| 9 | `uninstall.py --dry-run` previews removals |
| 10 | `uninstall.py` actually removes all hooks + clears settings.json + archives manifest |
| 11 | No hook files remain after uninstall |
| 12 | Manifest is gone (archived to `.json.removed.<ts>`) |

## CI integration

The script uses `set -euo pipefail` so any failure aborts immediately and
returns non-zero. Suitable as a GitHub Actions / GitLab CI step:

```yaml
- name: rules-architect sandbox test
  run: bash ~/.claude/skills/rules-architect/tests/integration/sandbox_install.sh
```

## Coverage gaps (known)

- **Unit tests for diagnose.py**: `unit/test_diagnose.py` — TBD
- **Cross-platform**: only tested on macOS/Linux (XDG paths). Windows untested.
- **CC version mismatch**: integration test uses `--skip-version-check`. To test
  version detection, mock `claude --version` separately.
- **Hook conflict resolution**: install_hooks.py interactive prompt path not
  exercised (sandbox uses --non-interactive). Add manual test case if you
  customize install logic.

## Debugging a failed test

If sandbox_install.sh fails:

1. Re-run with `--keep` to preserve tempdirs:
   ```bash
   bash tests/integration/sandbox_install.sh --keep
   ```
2. Inspect tempdirs printed at end (e.g. `/tmp/rules-architect-sandbox-XXXXXX/.claude/`)
3. Look for partial state:
   - `.rules-architect-manifest.json` — what was tracked
   - `settings.json` — what was registered
   - `hooks/*.py` — which files made it
4. Check `~/.cache/claude-hooks/audit.jsonl` from hook smoke tests
