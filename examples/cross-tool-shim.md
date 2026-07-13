# Cross-tool: codex / gemini / general

This skill targets **Claude Code first**, but the two highest-value layers —
L0 real-time hook injection and L2 path-scoped injection — now port to
**Codex CLI natively**, because Codex (>= v0.124.0) ships a hook system whose
I/O contract is identical to Claude Code's.

## Quick mapping

| rules-architect (CC) | Codex CLI | gemini / other |
|---|---|---|
| L0 `~/.claude/hooks/` + settings.json | **`~/.codex/hooks/` + `hooks.json`** (native) | pre-commit / pre-push githooks |
| L1 memory | (no cross-tool equivalent — private per tool) | (none) |
| L2 `.claude/rules/` path-scoped | **PreToolUse `apply_patch` hook** (emulated, same behavior) | `AGENTS.md` + per-file discovery |
| L3 `CLAUDE.md` @import | **`AGENTS.md`** (codex reads it; CC via `@AGENTS.md`) | `AGENTS.md` |
| L5 team lessons | `docs/ai/lessons.md` (any tool `cat`s it) | same |

## Codex is a first-class target now

Run the Codex installer to get the 3 core hooks on Codex:

```bash
python3 ~/.claude/skills/rules-architect/scripts/install_codex_hooks.py
```

It writes the same self-contained hook scripts into `~/.codex/hooks/` and
deep-merges entries into `~/.codex/hooks.json`, preserving anything already
there. Uninstall is precise via the same `uninstall.py` (codex artifacts are
tracked under `codex_*` manifest keys).

### Why it works: the contracts match

Verified against Codex CLI v0.144.x:

| Aspect | Claude Code | Codex CLI |
|---|---|---|
| stdin fields | `session_id` / `tool_name` / `tool_input` / `hook_event_name` | **identical** (snake_case) |
| context injection | `hookSpecificOutput.additionalContext` | **identical** |
| tool block | `permissionDecision: "deny"` | **identical** (+ `updatedInput` rewrite) |
| UserPromptSubmit field | `prompt` | **`prompt`** |
| config file | `~/.claude/settings.json` | `~/.codex/hooks.json` (or `[hooks]` in `config.toml`) |

### The three differences the installer handles for you

1. **Event matchers.** File edits are `Write|Edit|MultiEdit` on CC but
   **`apply_patch`** on Codex. `SessionStart` matches `startup|resume`.
   `UserPromptSubmit` takes **no matcher** on Codex (it's ignored).

2. **`apply_patch` has no structured path field** — only `tool_input.command`
   (the patch text). `memory_intake_check.py` is dual-runtime: it reads
   `tool_input.file_path` (CC) *and* parses the `*** Add/Update/Delete/Move`
   headers out of the patch text (Codex). Same script, both tools.

3. **Trust.** Codex won't run a non-managed command hook until you review and
   trust it by hash. After install, run `/hooks` in the Codex TUI to toggle the
   3 hooks on (or Codex prompts on first matching tool use). Editing a hook
   later marks it for re-review.

### What still does NOT port to Codex

- **L1 memory** — each tool keeps its own private store. If a memory entry is
  worth sharing across tools, upgrade it to L3 (`AGENTS.md`) or L5 (team
  lessons). This is by design: L1 is the "personal, tool-specific" layer and
  was never meant to carry team rules.

## L2 on Codex: path-scoped via a single apply_patch hook

CC injects `.claude/rules/*.md` declaratively when you edit matching files.
Codex has no declarative file-glob rule injection, so the equivalent is one
PreToolUse `apply_patch` hook that parses touched paths and injects the matching
rules. `memory_intake_check.py` already demonstrates the path-extraction half;
a project that wants full path-scoped rules on Codex writes a hook that reads
its rule files and globs the extracted paths (behaviorally identical to CC).

## L3 / L5: one source of truth across tools

**Option A (recommended):** put the shared baseline in `AGENTS.md`, and make
`CLAUDE.md` a single line: `@AGENTS.md`. Both CC and Codex read the same
content. Trade-off: every session pays the `AGENTS.md` token cost — keep it
concise.

**Option B:** hand-mirror the most important rules in both `.claude/rules/*.md`
(CC, auto-injected on edit) and an `AGENTS.md` section (loaded every session).

L5 lessons (`<repo>/docs/ai/lessons.md`) are plain markdown — the **only** layer
guaranteed cross-tool durable. Any tool can read it; it survives tool changes.

## gemini / tools without a hook contract

For tools that don't publish a hook contract, migrate the safety-critical rules
to git hooks (tool-agnostic, runs on every committer's machine):

```bash
# .git/hooks/pre-commit — block commits on protected branches
#!/bin/sh
branch=$(git rev-parse --abbrev-ref HEAD)
case "$branch" in
  develop|test|master)
    echo "❌ Don't commit directly on $branch — switch to a feature branch first"
    exit 1
    ;;
esac
```

Plus an `AGENTS.md § Always remember` section (re-loaded each session) and CI
checks for team-level enforcement. These lack the per-turn freshness of native
hooks but provide reasonable discipline.

## Decision tree

```
Which tool?
├── Claude Code → full skill (install_hooks.py)
├── Codex CLI   → install_codex_hooks.py (L0 + L2 emulated + L3/L5 via AGENTS.md)
└── other       → git hooks + AGENTS.md + lessons.md

Is the rule mission-critical (data loss / wrong branch)?
├── yes → L0 hook (CC/Codex) or git hook (everyone)
├── team-wide → AGENTS.md / lessons.md
└── just personal → CC/Codex L1 memory, accept the tool-specific cost
```
