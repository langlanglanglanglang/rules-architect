---
name: rules-architect
description: Self-improving Claude Code rule architecture - 5-layer memory model (L0 hook / L1 memory / L2 path-scoped / L3 CLAUDE.md / L5 team lessons) + 5-question placement SOP + 4 generic hooks + path-scoped rule-intake + team sync. Use when user asks "how to manage rules" / "rules keep getting forgotten" / "claude.md optimization" / "memory optimization" / "rules architect" / wants rule placement automation. L3 audit delegated to claude-md-management:claude-md-improver.
triggers:
  - rules architect
  - 自我改进规则
  - 规则归位
  - claude.md 优化
  - memory 优化
  - 规则容易忘
  - rule placement
  - memory optimization
---

# Rules Architect Skill

Self-improving rule architecture for Claude Code. Installs 4 hooks + 1 path-scoped rule + maintenance docs to make rule placement reliable, instead of relying on CLAUDE.md attention.

## The Problem This Solves

Default CC behavior: every nuance gets dumped to L1 memory (because it's the most convenient layer to write to). Result:
- Memory bloats with rules that should be elsewhere
- Team can't see your memory (private to user)
- CLAUDE.md instructions get diluted in long sessions
- Hook-pluckable rules left in memory keep getting forgotten

This skill provides **3 layers of interception** at rule-writing moment, forcing placement re-evaluation.

## 5-Layer Memory Model

| Layer | What | Trigger | Token cost |
|---|---|---|---|
| **L0 hooks** | `~/.claude/hooks/*.py` + settings.json config | Tool call before/after, real-time | 0 startup, ~50-200/inject |
| **L1 memory** | `~/.claude/projects/.../memory/*.md` | Index injected every session; details on demand | ~3k index |
| **L2 path-scoped** | `.claude/rules/*.md` with frontmatter `paths:` | Edit matching file → auto-inject | 0 startup |
| **L3 CLAUDE.md** | `CLAUDE.md` + `@import` chain | Session start, fully loaded | 40k+ |
| **L5 team lessons** | Repo `docs/ai/lessons.md` | Manual or workflow-triggered | 0 (on demand) |

## 5-Question Placement SOP

Walk these 5 questions **before** writing any new rule:

| # | Question | Pick layer |
|---|---|---|
| 1 | Can trigger condition be expressed by tool/matcher? (e.g. "git commit", "edit .proto") | **L0 hook** or **L2 path-scoped** |
| 2 | Only relevant when editing specific files/dirs? | **L2** `.claude/rules/` |
| 3 | All team members need it (incl. codex/gemini users)? | **L3** CLAUDE.md or **L5** lessons |
| 4 | Personal collaboration preference, team needn't know? | **L1** memory |
| 5 | Overlaps with existing rule? grep keywords → yes → edit existing, don't create new | — |

**FORBIDDEN**: Skip the 5 questions and default to L1 memory. This is the biggest source of leakage.

## 5-Step Installation Flow

When user triggers `/rules-architect`:

### Step 1: Diagnose (safe, no file changes)

Run `scripts/diagnose.py`:
- Map current architecture per layer
- Grade each rule with reason (placement mismatch / duplicate / stale)
- **Delegate L3 (CLAUDE.md audit) to `claude-md-management:claude-md-improver`** if plugin enabled
- Output: structured JSON report + human-readable summary

### Step 2: Present model + SOP

Show user 5-layer model + 5-question SOP for buy-in.

### Step 3: Choose install mode

| Mode | What it does | Risk |
|---|---|---|
| **D. Diagnose only** (default for first run) | No file changes | Zero |
| **C. Path-scoped only** | `.claude/rules/rule-intake.md` + nothing else | Very low |
| **B. Hooks only** | 4 hooks + settings.json merge + manifest | Low (backup + manifest) |
| **A. Full install** | All of B + rule-intake + §六 to CLAUDE-personal.md | Medium (changes 3+ files) |
| **E. Uninstall** | Roll back per manifest | — |

### Step 4: Execute

For chosen mode:
1. `claude --version` check (fail if < min supported)
2. Backup `~/.claude/settings.json.bak.<ts>`
3. Copy templates with variable substitution
4. JSON deep-merge into settings.json (atomic: tmp → rename)
5. Update `~/.claude/.rules-architect-manifest.json`
6. Dry-run each hook with stub JSON
7. Report: command summary + audit.jsonl path + min CC version

### Step 5: Configure

User customizes:
- `RULE_INTAKE_KEYWORDS` (Chinese / English preset)
- `PROTECTED_BRANCHES` (default `develop|test|master`)
- `LESSONS_PATH` for team sync
- Project-specific rules in `.claude/rules/`

## What This Skill Provides

**4 generic hooks (parametrized + self-contained reminders)**:
- `error_recovery_checkpoint.py` — tool errors → force 3-line recovery report
- `memory_intake_check.py` — writing to memory → inject 5-Q SOP
- `rule_intake_reminder.py` — user msg has rule keywords → inject 5-Q SOP
- `dangerous_branch_reminder.py` — git checkout to protected branches → soft reminder

**1 path-scoped rule**:
- `.claude/rules/rule-intake.md` — editing any rule file → inject 5-Q SOP

**Maintenance docs + scripts**:
- `CLAUDE-personal.md §六` template (upgrade / retire / team sync flows)
- `memory_sync.py` — single-direction push memory → team lessons.md
- `cleanup_hook.py` — SessionStart cleanup (lock TTL + audit rotation)

## What This Skill Does NOT Provide

- ❌ Project-specific hooks (e.g. `mr_created_reminder` for codeup MCP) — see `examples/`
- ❌ Business path-scoped rules (proto / sql / release-notes / meta-md) — see `examples/`
- ❌ L3 CLAUDE.md audit — delegated to `claude-md-management:claude-md-improver`
- ❌ Cross-tool support — CC-only. codex / gemini users: see README "Cross-tool" section


## Content Preservation Guarantees

This skill **never modifies your existing content** without explicit consent. All changes are tracked in `~/.claude/.rules-architect-manifest.json` for precise rollback.

**Never touched**:
- L1 memory files (your private notes)
- CLAUDE.md content
- CLAUDE-personal.md sections outside `<!-- rules-architect:section-6 BEGIN/END -->` markers
- Your existing `~/.claude/settings.json` entries (deep-merge preserves them)
- Other `.claude/rules/*.md` files
- Files you've modified locally (hash mismatch → skipped with warning)

**Added (with consent)**:
- Up to 5 hook scripts in `~/.claude/hooks/`
- Up to 5 hook entries in `~/.claude/settings.json` (backed up first)
- Mode C/A: `.claude/rules/rule-intake.md`
- Mode A: §六 section in `CLAUDE-personal.md` (marker-protected)

**Migration vs Modification**: `diagnose.py` suggests which memory entries could be upgraded to other layers (with target + reason), but never auto-moves them. Migration is human-triggered via §六 Upgrade flow.

## Minimum Requirements

- Claude Code >= 1.5.0 (UserPromptSubmit hook required)
- Python 3.7+
- macOS / Linux (Windows: partial, see README)

## File Layout

```
~/.claude/skills/rules-architect/
├── SKILL.md                              # This file
├── README.md                             # 5-min start + Q&A
├── scripts/
│   ├── diagnose.py                       # L0-L5 scan, --json output
│   ├── install_hooks.py                  # Deep-merge into settings.json
│   ├── install_rule_intake.py            # Project-level path-scoped install
│   ├── install_personal_md_section.py    # Add §六 to CLAUDE-personal.md
│   ├── uninstall.py                      # Roll back per manifest
│   └── memory_sync.py                    # Memory → team lessons (push only)
├── templates/
│   ├── hooks/
│   │   ├── error_recovery_checkpoint.py.tmpl
│   │   ├── memory_intake_check.py.tmpl
│   │   ├── rule_intake_reminder.py.tmpl  # {{RULE_INTAKE_KEYWORDS}}
│   │   ├── dangerous_branch_reminder.py.tmpl  # {{PROTECTED_BRANCHES}}
│   │   └── cleanup_hook.py.tmpl
│   ├── rules/
│   │   └── rule-intake.md.tmpl
│   ├── personal-section-6.md.tmpl
│   └── settings-snippet.json.tmpl
├── examples/                             # NOT installed
│   ├── README.md
│   ├── mr_created_reminder.py.example    # Codeup MCP specific
│   ├── path-scoped-rule-skeleton.md      # Generic frame
│   └── extension-hook-skeleton.py
└── tests/
    ├── unit/
    ├── integration/
    │   └── sandbox_install.sh            # Isolated $HOME test
    └── README.md
```

## Manifest

`~/.claude/.rules-architect-manifest.json` tracks every installed file:
```json
{
  "skill_version": "1.0.0",
  "installed_at": "2026-06-12T...",
  "files": [
    {"path": "~/.claude/hooks/error_recovery_checkpoint.py",
     "hash": "sha256...", "owner": "rules-architect", "version": "1.0.0"}
  ],
  "settings_hooks_added": [
    {"event": "PostToolUse", "matcher": "Edit|Write|Bash|MultiEdit",
     "command": "python3 ~/.claude/hooks/error_recovery_checkpoint.py"}
  ]
}
```

`uninstall.py` removes only items in manifest (precise rollback, NOT full backup restore).

## Output Convention

Each step outputs:
1. **What we're about to do** (one line)
2. **Result** (success/fail + details)
3. **Next action** (or stop on failure)

Failures roll back automatically via manifest.

## References

- `templates/` — all installable artifacts
- `scripts/` — install + diagnose + uninstall + sync
- `examples/` — non-generic templates for inspiration (NOT installed)
- `tests/` — unit + sandbox integration
- `README.md` — 5-minute getting started + Q&A
