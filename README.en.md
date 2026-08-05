**English** | [中文](README.md)

> See also: [How does this compare to the official claude-md-improver?](docs/comparison-vs-claude-md-improver.md)

**TL;DR install**: `curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash` — select Claude Code, Codex, or both during installation; see [Quick install](#quick-install-one-liner).

# rules-architect

> Self-improving rule architecture for Claude Code **and Codex CLI**. Install 3 core hooks + path-scoped rule to make rule placement reliable instead of relying on CLAUDE.md attention. (First-class Codex support: see the [Codex support](#codex-support-first-class) section.)

The default run also produces a **read-only rule distribution report** across
platform-resolved memory, CLAUDE, AGENTS, path rules, and registered hooks. It groups
advice into Hooks / Rules / Team Baseline / Memory / Lessons without moving or
overwriting rules.

## What's in the box

| Component | Purpose | Generic? |
|---|---|---|
| 3 core hooks | SOP injection + base infrastructure (memory_intake / rule_intake / cleanup) | ✅ Universal |
| 1 path-scoped rule (`rule-intake.md`) | Inject SOP when editing rule files | ✅ |
| Read-only distribution tools | Inventory, validate, and render five-group advice | ✅ |
| §六 template for `CLAUDE-personal.md` | Upgrade / retire / team sync flows | ✅ |
| `memory_sync.py` | Push memory → team lessons (single direction) | ✅ Parametrized |
| `examples/` | Non-generic project rules for inspiration | NOT installed |

## Why

Default CC behavior: every nuance gets dumped to **L1 memory** because it's the most convenient layer. Consequences:
- Memory bloats with rules that should be elsewhere
- Team can't see your memory (private to user)
- CLAUDE.md gets diluted in long sessions
- Hook-pluckable rules left in memory keep getting forgotten

This skill provides **3 layers of real-time interception** at the rule-writing moment.


## Design philosophy: opinionated vs. universal

This skill ships **only 3 core hooks** that encode the skill's methodology (5-Q SOP injection + base infrastructure) — not individual workflow preferences. Per-user workflow hooks (e.g. `error_recovery_checkpoint`, `dangerous_branch_reminder`) live in `examples/` for you to fork and customize.

**Universal (installed by default)**:
- `memory_intake_check.py` — intercepts memory writes with 5-Q SOP
- `rule_intake_reminder.py` — intercepts user rule keywords with 5-Q SOP
- `cleanup_hook.py` — SessionStart cleanup (lock TTL + audit rotation)

**Opinionated (in `examples/`, copy + adapt)**:
- `error_recovery_checkpoint.py.example` — force 3-line recovery report on tool error
- `dangerous_branch_reminder.py.example` — warn on `git checkout <protected branch>`
- `mr_created_reminder.py.example` — codeup MCP MR created → status summary
- `extension-hook-skeleton.py` — minimal template for your own hook

Migration of your existing memory entries to per-user hooks is orchestrated by the main agent following SKILL.md Step 4b — triggered after the core 3 hooks are installed.


## Quick install (one-liner)

```bash
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash
```

The interactive installer asks which targets to install:

```text
[ ] 1. Claude Code (Skill + Hooks)
[ ] 2. Codex (Skill + Hooks)
Choose 1, 2, or 1,2 [default 1,2]:
```

It keeps one canonical checkout and creates the selected discovery entries:

- Claude Code: `~/.claude/skills/rules-architect`
- Codex: `~/.agents/skills/rules-architect`

Mode B installs the three core hooks for every selected platform. Without a
TTY, both platforms are selected; CI can use `--platforms` explicitly.

For more control:
```bash
# Non-interactive Claude + Codex Skill and Hook install
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | \
  bash -s -- --platforms claude,codex --non-interactive

# Codex only
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | \
  bash -s -- --platforms codex

# Diagnose only: temporary checkout, cleaned automatically; installs nothing
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash -s -- --mode D

# Full install (hooks + rule-intake + §六)
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash -s -- --mode A

# Custom install location
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash -s -- --install-dir ~/workspace/rules-architect

# Pin to a specific tag
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash -s -- --tag v2.5.0
```

### Or manual Claude Code install (more transparent)
```bash
git clone https://github.com/langlanglanglanglang/rules-architect.git ~/.claude/skills/rules-architect
python3 ~/.claude/skills/rules-architect/scripts/install_hooks.py
```

## Requirements

- **Claude Code >= 1.5.0** (UserPromptSubmit hook required)
- Python 3.7+
- macOS / Linux fully supported; Windows partial (see Cross-platform section)

## 5-minute getting started

```bash
# 1a. Trigger in Claude Code
/rules-architect

# 1b. Trigger in Codex
$rules-architect

# 2. Review the default read-only distribution report.
#    It inventories and classifies rules without modifying them.

# 3. After understanding the 5-layer model + SOP:
#    Explicitly request install mode A (full) or B/C (partial)
```

### Read-only rule distribution report

Running `/rules-architect` in Claude Code or `$rules-architect` in Codex
(also selectable through `/skills`) makes the main agent:

1. build a current-project inventory with `scripts/rule_inventory.py`;
2. discover registered, orphaned, dangling, and locally modified hooks;
3. choose a canonical body, delivery adapters, and enforcement mode;
4. resolve ambiguity first, then reconcile as create/reuse/update/disable/delete/keep;
5. validate coverage, ownership, and fingerprint binding;
6. render the five groups and actual hook health.

Conflicts, low-confidence classifications, and ambiguous external artifacts
are confirmed with the user before a final plan exists. No operations are
allowed during that stage. Final recommendations contain resolved actions only
(`create/reuse/move/update/disable/delete/keep`) and never use `review` as a
result.

The user still performs one Skill invocation. The current session's main agent
supplies semantic classification; the Python tools only discover, validate,
and render deterministic data and do not claim standalone language
understanding.

Hooks are labeled `block` or `remind`.
Only a deterministically testable pre-action block is called enforcement;
existing `additionalContext` hooks are reminders.

Repeated runs are intentional. Hooks produced by other tools are included in
comparison but are never automatically modified. Applying remains read-only by
default and requires an explicit `apply_reconciliation.py --yes` confirmation.
The final menu supports all safe operations, selected operation IDs,
create-only execution, plan adjustment, export, rescan, and exit. Updates,
disables, and deletes receive a second confirmation before execution. Execution
choices are hidden when no operation exists. Partial selection records only
successful operations. Operations bound to the same recommendation are
indivisible, preventing a half-installed Hook. Moves and
unsupported document/memory writes remain manual rather than pretending to be
transactional.

Schema 1.2 covers every scanned occurrence, binds confirmed outcomes to the
final target/group/enforcement/action, and cross-links final conclusions with
operations. A report cannot say “keep” while an operation silently deletes the
same artifact.
Preview and apply use the same path/config/state/hash preflight; legacy schemas
are view-only, and writes require a schema 1.2 ready plan. Automatic Hook writes
also require a complete desired registration set and content markers bound to
the final enforcement specification. A blocking Hook must contain its managed
blocking marker and an actual deny-protocol output; `return 0` is rejected.
Apply failures restore every file, config, Manifest, and state file touched by
that transaction.

Example output shape:

```text
Hooks（2）
H01 [R-main-push][高][create] Do not push directly to main
执行：claude / block / PreToolUse / Bash

Path-scoped Rules（1）
P01 [R-proto-field][高][keep] Proto field numbers must increase

Team Baseline（3）
...
Memory（1）
...
Lessons（1）
...
```


## Content preservation guarantees

This skill **never modifies your existing content** without explicit consent and manifest tracking:

| Your data | Action |
|---|---|
| L1 memory files | Unchanged by default scans/installs; only an individually confirmed promotion with an exact directory and backup replaces that entry with a stub |
| CLAUDE.md | ✋ Never touched |
| CLAUDE-personal.md (§一~§五 etc) | ✋ Outside `<!-- rules-architect:section-6 BEGIN/END -->` markers: untouched |
| Existing hooks in `~/.claude/settings.json` | ✋ Preserved via deep-merge with conflict detection |
| Existing hooks in `~/.codex/hooks.json` | ✋ Preserved via deep-merge with conflict detection |
| Existing `.claude/rules/*.md` files | ✋ Only `rule-intake.md` is added (mode C/A) |
| Files you locally modified | ✋ Skipped on hash mismatch (no overwrite or delete) |

What this skill **adds** (all tracked in `~/.claude/.rules-architect-manifest.json`):
- 3 hook entries in `~/.claude/settings.json` (settings.json backed up to `.bak.<ts>` first)
- 3 hook scripts in `~/.claude/hooks/`
- When Codex is selected: matching entries/scripts in `~/.codex/hooks.json`
  and `~/.codex/hooks/`
- Selected-platform Skill discovery directories pointing to one checkout
- Mode C / A: `<project>/.claude/rules/rule-intake.md`
- Mode A only: §六 section in `<project>/CLAUDE-personal.md` (marker-protected for precise removal)

**Migration vs Modification**: `diagnose.py` **suggests** memory entries that could be upgraded to other layers (e.g. rhythm-related rules → L0 hook), but **never auto-moves anything**. All migration is human-triggered (see §六 Upgrade flow).

Uninstall is precise (per-manifest, hash-verified). It removes bootstrap-created
Skill links that still point to the recorded checkout, and removes a
bootstrap-created checkout only when its Git worktree is clean. Files you
modified locally are never overwritten or deleted.

## What modes do

| Mode | Risk | Files changed |
|---|---|---|
| D. Diagnose | Zero | None |
| C. Path-scoped only | Very low | `.claude/rules/rule-intake.md` |
| B. Hooks only | Low | Hook configuration and scripts for selected platforms |
| A. Full | Medium | B + Claude path rule and `CLAUDE-personal.md` §六 when Claude is selected |
| E. Uninstall | — | Precise rollback per manifest |

## Architecture: 5-Layer Memory Model

| Layer | What | Trigger |
|---|---|---|
| L0 hook | Real-time scripts | Tool call before/after |
| L1 memory | Private notes | CC platform auto-manages |
| L2 path-scoped | Project rules | Edit matching file |
| L3 CLAUDE.md | Team baseline | Session start |
| L5 team lessons | Cross-tool knowledge | Manual / triggered |

**Key insight**: L0 + L2 trigger closer to the relevant action or file, but
triggering is not the same as enforcement. Blocking hooks, reminder hooks,
path-scoped context, and external CI are reported separately.

## What this skill is NOT

- ❌ **Does not judge CLAUDE.md factual correctness, command freshness, or writing quality** — keep using `claude-md-management:claude-md-improver`
- ❌ **Does not apply distribution advice by default** — reporting and mutation are separate flows
- ❌ **Not project-specific** — `mr_created_reminder`, `wiki_publish_check`, business rules go in your project's `.claude/rules/` or `~/.claude/hooks/` directly, see `examples/`
- ⚠️ **codex is first-class; gemini needs a shim** — select Codex in `bootstrap.sh` to install both Skill and Hooks; tools with no hook contract (gemini, etc.) see the Cross-tool section below

## Configuration

After install, customize via env vars:

| Variable | Default | What |
|---|---|---|
| `RULE_INTAKE_KEYWORDS` | `chinese` | `chinese` / `english` / custom regex |
| `PROTECTED_BRANCHES` | `develop\|test\|master` | Pipe-separated branch names |
| `LESSONS_PATH` | (none) | Absolute path to team lessons.md |
| `RA_TOKEN_EXTRA_PATHS` | (none) | Comma-separated relative paths for diagnose token estimation to scan in addition |

## Cross-platform notes

- macOS / Linux: full support, `XDG_CACHE_HOME` respected
- Windows: hooks work via Python; `~/.cache` path uses `%LOCALAPPDATA%\\Claude\\cache`
- WSL: treat as Linux

## Codex support (first-class)

Use the one-line installer and select Codex to install both the Skill and
Hooks:

```bash
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | \
  bash -s -- --platforms codex
```

The following command installs Codex Hooks only; it does not install the Skill:

```bash
python3 ~/.agents/skills/rules-architect/scripts/install_codex_hooks.py
```

Version detection is advisory by default. The Codex desktop client can run a
Skill without exposing a separate `codex` executable to the current shell's
`PATH`. A missing, failed, or older CLI therefore produces a warning and Hook
installation continues; it does not prove that the client lacks Hook support.
Use `--strict-version-check` when CI should fail, or `--skip-version-check` to
omit detection entirely.

It writes the same 3 self-contained hooks into `~/.codex/hooks/` and deep-merges
into `~/.codex/hooks.json` (preserving existing entries). The installer handles
every difference:
- file-edit matcher is `apply_patch` (not `Write|Edit`); `memory_intake_check.py`
  is dual-runtime and parses paths out of the patch text
- `UserPromptSubmit` takes no matcher; `SessionStart` matcher is `startup|resume`
- **trust step**: Codex trusts hooks by hash — after install, run `/hooks` in the
  Codex TUI to toggle the 3 on (or confirm on first use)

Invoke the installed Skill with `$rules-architect` or select it through
`/skills`.

Uninstall uses the same `uninstall.py` (codex artifacts tracked under `codex_*`
manifest keys for precise rollback). Retired managed files are moved into an
indexed recovery archive; config edits use copied snapshots. Archive failure
blocks the mutation.

L1 memory does not port across tools (Codex has its own private store) — by
design, L1 was never meant to carry team rules.

## Cross-tool (gemini / tools with no hook contract)

For tools that don't publish a hook contract:
- L3 rules: put in `AGENTS.md` (codex reads it; CC reads via `@AGENTS.md`)
- L0 equivalent: pre-commit / githook for branch protection
- L5 (team lessons): pure markdown, works for any tool

See `examples/cross-tool-shim.md` for details.

## Uninstall

```bash
# Claude discovery entry
python3 ~/.claude/skills/rules-architect/scripts/uninstall.py

# Codex-only discovery entry
python3 ~/.agents/skills/rules-architect/scripts/uninstall.py
```

Uninstall reads `~/.claude/.rules-architect-manifest.json` and:
1. Verifies each installed file and moves the original into the recovery archive
2. Removes only the hook entries this skill added from `settings.json`
3. Uses each recorded `config_path` for user-level or project-level Hook config
4. Removes unchanged bootstrap-created Skill entries and a clean owned checkout
5. Restores `~/.claude/settings.json.bak.<ts>` only if user explicitly opts in

Recovery archives default to
`~/.claude/rules-architect-backups/<timestamp>-uninstall-<run-id>/`.
`index.json` records each original path, SHA-256, mode, `moved`/`copied`
disposition, and archived location;
`manifest.before.json` preserves the pre-uninstall Manifest. Set
`RULES_ARCHITECT_RECOVERY_DIR` to use another archive root.

**Moves into the recovery archive** (manifest-tracked and hash-verified):
- Managed Hook scripts and project-level `.claude/rules/rule-intake.md`
- Managed Hook or Path Rule artifacts retired or replaced by reconciliation

**Directly removes installer-owned assets**:
- Bootstrap-created Skill symlinks that still point to the recorded checkout
- The bootstrap-created canonical checkout only when its Git worktree is clean

**Does NOT delete**:
- Your own customizations to installed files (hash mismatch → skip with warning)
- Any L1 memory files (they're yours)

## Q&A

**Q: Will the hooks slow down CC?**
A: Each hook adds ~10-20ms; 3 hooks total < 100ms. Dedupe ensures same reminder fires once per session.

**Q: What if I already have hooks installed?**
A: `install_hooks.py` deep-merges with conflict detection. For the same matcher,
you can append or skip; third-party Hooks are never replaced.

**Q: How do I know hooks are firing?**
A: Check `~/.cache/claude-hooks/audit.jsonl`:
```bash
jq -c 'select(.decision == "inject")' ~/.cache/claude-hooks/audit.jsonl | tail
```

**Q: How do I update to a newer version?**
A: Re-run `/rules-architect` in Claude Code or `$rules-architect` in Codex. The skill compares manifest hashes and shows you what would change.

**Q: Can I use this with other CLAUDE.md tools?**
A: Yes, especially `claude-md-management:claude-md-improver` (this skill delegates L3 audit to it). Other compatible tools listed in SKILL.md.

## Reporting issues

The Skill is at `~/.claude/skills/rules-architect/` for Claude Code and
`~/.agents/skills/rules-architect/` for Codex. See `tests/` for reproducible
test cases.

Audit log: `~/.cache/claude-hooks/audit.jsonl`
Manifest: `~/.claude/.rules-architect-manifest.json`
