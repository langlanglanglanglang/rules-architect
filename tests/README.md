# rules-architect tests

## Structure

```
tests/
├── README.md                            # This file
├── integration/
│   ├── bootstrap_platforms.sh            # One-click Claude + Codex install
│   ├── sandbox_install.sh               # E2E: install → verify → uninstall
│   └── distribution_report.sh           # inventory → validate → render
└── unit/
    ├── test_rule_inventory.py           # source discovery + extraction
    ├── test_recommendations.py           # contract + five-group renderer
    └── test_apply_reconciliation.py      # guarded preview/apply behavior
```

## Running

### Unit tests

```bash
python3 -m unittest discover -s tests/unit -v
```

The inventory tests use isolated temporary homes/projects and verify
exact-project memory mapping, Claude import safety, Codex override/fallback
precedence, repository-root discovery from a subdirectory, recursive path
rules, project hook registration coverage, redaction, code-fence exclusion,
promoted-stub exclusion, and deterministic output.
It also verifies registered/orphan/dangling/modified hook health and ownership
without executing hook code.

The recommendation tests verify full occurrence coverage, project/fingerprint
binding, blocking-hook predicates, path-scoped targets, malformed
duplicate/conflict rejection, unclassified rendering, and all five report
groups.
The apply tests verify preview-only defaults, allowed-path creation, executable
mode, private state recording, and refusal to overwrite existing files.

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

### Integration: platform-aware bootstrap

```bash
bash tests/integration/bootstrap_platforms.sh
```

Builds a local Git fixture with fake Claude/Codex version commands, runs the
non-interactive one-click installer for Claude-only, Codex-only, and both, and
verifies:

- both Skill discovery entries resolve to the same checkout;
- all three Claude and Codex Hook files are executable and registered;
- pre-existing Codex Hook commands are preserved;
- the shared manifest tracks both platforms.

### Integration: read-only distribution pipeline

```bash
bash tests/integration/distribution_report.sh
```

Runs from an arbitrary project working directory, builds an isolated
Claude/Codex inventory, validates a project- and fingerprint-bound
recommendation, and checks that all five groups plus duplicate/conflict source
details render successfully.

This is a deterministic pipeline test. Its fixture classifier supplies known
recommendations so the test can exercise inventory → contract → renderer
mechanics. Semantic placement judgment is supplied by the main agent during a
real `/rules-architect` run and is not reproducible as a standalone shell test.

### What sandbox_install.sh checks

| # | Assertion |
|---|---|
| 1 | `diagnose.py` runs on empty state without error |
| 2 | `install_hooks.py --dry-run` produces plan, modifies nothing |
| 3 | `install_hooks.py` (real) creates 3 core hooks + settings.json entries |
| 4 | All 3 expected hook files are executable |
| 5 | `settings.json` contains PreToolUse / UserPromptSubmit / SessionStart |
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

- **Legacy diagnose.py grading** does not yet have dedicated unit fixtures.
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
