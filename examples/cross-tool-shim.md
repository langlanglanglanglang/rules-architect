# Cross-tool shim: codex / gemini / general

This skill is **Claude Code only** (CC hooks + path-scoped `paths:` frontmatter
are CC-specific mechanisms). To get equivalent rule placement enforcement
across codex / gemini / etc, use these substitutes.

## Quick mapping

| rules-architect (CC) | codex / gemini equivalent |
|---|---|
| L0 `~/.claude/hooks/` | **pre-commit / pre-push githooks** (or `lefthook` config) |
| L1 memory | (no equivalent — each tool has its own private memory) |
| L2 `.claude/rules/` path-scoped | **`AGENTS.md` + per-file context discovery** |
| L3 `CLAUDE.md` @import | **`AGENTS.md` @ project root** (codex reads it) |
| L5 team lessons | **`docs/ai/lessons.md` in repo** (any tool can `cat` it) |

## L0: hooks → githooks

Many rules-architect hooks (especially `error_recovery_checkpoint` and
`mr_created_reminder`) won't fire on codex / gemini because they don't
publish a hook contract.

Migrate the **most safety-critical** rules to git hooks instead:

```bash
# .git/hooks/pre-commit
#!/bin/sh
# Block commits on protected branches (mirrors dangerous_branch_reminder)
branch=$(git rev-parse --abbrev-ref HEAD)
case "$branch" in
  develop|test|master)
    echo "❌ Don't commit directly on $branch — switch to a feature branch first"
    exit 1
    ;;
esac
```

Tool-agnostic, lighter weight, runs on every committer's machine.

## L2: path-scoped → AGENTS.md

CC injects `.claude/rules/*.md` when you edit matching files. Codex doesn't —
it loads `AGENTS.md` at session start.

**Option A: keep both, hand-mirror the most important rules**
- `.claude/rules/proto.md` (CC, auto-injected when editing .proto)
- Same content summarized in `AGENTS.md` § Proto (codex, loaded every session)

**Option B: use `@AGENTS.md` in `CLAUDE.md`** (recommended)
- One source of truth: `AGENTS.md`
- `CLAUDE.md` is a single line: `@AGENTS.md`
- Both tools read the same content

The trade-off: every codex session pays the AGENTS.md token cost even when
not editing related files. Keep AGENTS.md concise.

## L1: memory has no equivalent

User-specific memory **doesn't port** across tools — each tool keeps its own
private store. If a memory entry is worth sharing across tools, upgrade it
to L3 (`CLAUDE.md` / `AGENTS.md`) or L5 (team lessons).

The rules-architect skill provides `memory_sync.py` for memory → team lessons
push — that path **does** make rules visible to all tools.

## L5: team lessons (the universal layer)

Plain markdown in `<repo>/docs/ai/lessons.md`:
- Any tool can read it (`cat`, included in context on demand, indexed by RAG, etc)
- Survives tool changes (move from codex to gemini? lessons still apply)
- Worth the discipline to keep current

This is the **only layer guaranteed cross-tool durable** — design accordingly.

## Hook-free reminder for codex / gemini

If you really want a "hook"-like behavior in codex:

1. **`AGENTS.md` § Always remember** — a section that lists the top 5 rules.
   Tool loads this every session, so the rules get re-injected each turn.

2. **`pre-commit` git hook** — blocks commits that violate hard rules.

3. **CI checks** — for team-level enforcement (e.g. lint that requires a SOP
   header in new rule files).

These don't have the per-turn freshness of CC hooks but provide reasonable
discipline.

## Decision tree

```
Is the rule mission-critical (data loss / wrong branch / etc)?
├── yes → L0 git hook (works for everyone)
├── no, but team-wide → AGENTS.md / lessons.md
└── no, just personal → leave it in CC L1 memory, accept the tool-specific cost
```
