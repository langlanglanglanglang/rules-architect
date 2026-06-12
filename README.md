**English** | [中文](README.zh.md)

> See also: [How does this compare to the official claude-md-improver?](docs/comparison-vs-claude-md-improver.md)

# rules-architect

> Self-improving rule architecture for Claude Code. Install 4 hooks + path-scoped rule to make rule placement reliable instead of relying on CLAUDE.md attention.

## What's in the box

| Component | Purpose | Generic? |
|---|---|---|
| 4 hooks | Real-time interception at rule-writing moment | ✅ Parametrized |
| 1 path-scoped rule (`rule-intake.md`) | Inject SOP when editing rule files | ✅ |
| §六 template for `CLAUDE-personal.md` | Upgrade / retire / team sync flows | ✅ |
| `memory_sync.py` | Push memory → team lessons (single direction) | ✅ Parametrized |
| `cleanup_hook.py` | SessionStart cleanup (lock TTL + audit rotation) | ✅ |
| `examples/` | Non-generic project rules for inspiration | NOT installed |

## Why

Default CC behavior: every nuance gets dumped to **L1 memory** because it's the most convenient layer. Consequences:
- Memory bloats with rules that should be elsewhere
- Team can't see your memory (private to user)
- CLAUDE.md gets diluted in long sessions
- Hook-pluckable rules left in memory keep getting forgotten

This skill provides **3 layers of real-time interception** at the rule-writing moment.

## Requirements

- **Claude Code >= 1.5.0** (UserPromptSubmit hook required)
- Python 3.7+
- macOS / Linux fully supported; Windows partial (see Cross-platform section)

## 5-minute getting started

```bash
# 1. Trigger skill in any CC session
/rules-architect

# 2. Choose mode D (diagnose only) for first run — SAFEST
#    Reviews current state, suggests improvements, modifies nothing.

# 3. After understanding the 5-layer model + SOP:
#    Re-run with mode A (full install) or B/C for partial
```


## Content preservation guarantees

This skill **never modifies your existing content** without explicit consent and manifest tracking:

| Your data | Action |
|---|---|
| L1 memory files | ✋ Never touched |
| CLAUDE.md | ✋ Never touched |
| CLAUDE-personal.md (§一~§五 etc) | ✋ Outside `<!-- rules-architect:section-6 BEGIN/END -->` markers: untouched |
| Existing hooks in `~/.claude/settings.json` | ✋ Preserved via deep-merge with conflict detection |
| Existing `.claude/rules/*.md` files | ✋ Only `rule-intake.md` is added (mode C/A) |
| Files you locally modified | ✋ Skipped on hash mismatch (no overwrite or delete) |

What this skill **adds** (all tracked in `~/.claude/.rules-architect-manifest.json`):
- 5 hook entries in `~/.claude/settings.json` (settings.json backed up to `.bak.<ts>` first)
- 5 hook scripts in `~/.claude/hooks/`
- Mode C / A: `<project>/.claude/rules/rule-intake.md`
- Mode A only: §六 section in `<project>/CLAUDE-personal.md` (marker-protected for precise removal)

**Migration vs Modification**: `diagnose.py` **suggests** memory entries that could be upgraded to other layers (e.g. rhythm-related rules → L0 hook), but **never auto-moves anything**. All migration is human-triggered (see §六 Upgrade flow).

Uninstall is precise (per-manifest, hash-verified). Files you modified locally are never overwritten or deleted.

## What modes do

| Mode | Risk | Files changed |
|---|---|---|
| D. Diagnose | Zero | None |
| C. Path-scoped only | Very low | `.claude/rules/rule-intake.md` |
| B. Hooks only | Low | `~/.claude/settings.json` + `~/.claude/hooks/*.py` |
| A. Full | Medium | All of B + `<your-project>/CLAUDE-personal.md` (adds §六) |
| E. Uninstall | — | Precise rollback per manifest |

## Architecture: 5-Layer Memory Model

| Layer | What | Trigger |
|---|---|---|
| L0 hook | Real-time scripts | Tool call before/after |
| L1 memory | Private notes | CC platform auto-manages |
| L2 path-scoped | Project rules | Edit matching file |
| L3 CLAUDE.md | Team baseline | Session start |
| L5 team lessons | Cross-tool knowledge | Manual / triggered |

**Key insight**: L0 + L2 are **100% reliable** (no attention dilution). L3 gets forgotten in long sessions. This skill pushes rule placement toward L0/L2.

## What this skill is NOT

- ❌ **Not a CLAUDE.md auditor** — use `claude-md-management:claude-md-improver` (official Anthropic plugin) for L3 audit
- ❌ **Not project-specific** — `mr_created_reminder`, `wiki_publish_check`, business rules go in your project's `.claude/rules/` or `~/.claude/hooks/` directly, see `examples/`
- ❌ **Not for codex/gemini** — CC-only. See Cross-tool section below

## Configuration

After install, customize via env vars or `~/.claude/.rules-architect-config.json`:

| Variable | Default | What |
|---|---|---|
| `RULE_INTAKE_KEYWORDS` | `chinese` | `chinese` / `english` / custom regex |
| `PROTECTED_BRANCHES` | `develop\|test\|master` | Pipe-separated branch names |
| `LESSONS_PATH` | (none) | Absolute path to team lessons.md |
| `MIN_CC_VERSION` | `1.5.0` | Refuse install below this |

## Cross-platform notes

- macOS / Linux: full support, `XDG_CACHE_HOME` respected
- Windows: hooks work via Python; `~/.cache` path uses `%LOCALAPPDATA%\\Claude\\cache`
- WSL: treat as Linux

## Cross-tool (codex / gemini / etc)

CC hooks don't fire in codex / gemini. For those workflows:
- L3 rules: put in `AGENTS.md` (codex reads it; CC reads via `@AGENTS.md`)
- L0 equivalent: pre-commit / githook for branch protection
- L5 (team lessons): pure markdown, works for any tool

See `examples/cross-tool-shim.md` for details.

## Uninstall

```bash
python3 ~/.claude/skills/rules-architect/scripts/uninstall.py
```

Uninstall reads `~/.claude/.rules-architect-manifest.json` and:
1. Removes each installed file (verified by hash)
2. Removes only the hook entries this skill added from `settings.json`
3. Restores `~/.claude/settings.json.bak.<ts>` only if user explicitly opts in

**Does NOT delete**:
- Your own customizations to installed files (hash mismatch → skip with warning)
- Project-level `.claude/rules/rule-intake.md` (manual delete required to avoid accidental cleanup)
- Any L1 memory files (they're yours)

## Q&A

**Q: Will the hooks slow down CC?**
A: Each hook adds ~10-20ms; 4 hooks total < 100ms. Dedupe ensures same reminder fires once per session.

**Q: What if I already have hooks installed?**
A: `install_hooks.py` does deep-merge with conflict detection. If a same-matcher hook exists, you'll be prompted: append / skip / replace.

**Q: How do I know hooks are firing?**
A: Check `~/.cache/claude-hooks/audit.jsonl`:
```bash
jq -c 'select(.decision == "inject")' ~/.cache/claude-hooks/audit.jsonl | tail
```

**Q: How do I update to a newer version?**
A: Re-run `/rules-architect`. The skill compares manifest hashes and shows you what would change.

**Q: Can I use this with other CLAUDE.md tools?**
A: Yes, especially `claude-md-management:claude-md-improver` (this skill delegates L3 audit to it). Other compatible tools listed in SKILL.md.

## Reporting issues

The skill is at `~/.claude/skills/rules-architect/`. See `tests/` for reproducible test cases.

Audit log: `~/.cache/claude-hooks/audit.jsonl`
Manifest: `~/.claude/.rules-architect-manifest.json`
