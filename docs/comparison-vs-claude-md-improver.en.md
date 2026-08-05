# rules-architect vs claude-md-improver

[中文](comparison-vs-claude-md-improver.md) | **English**

> Two complementary Claude Code skills addressing different aspects of rule management.

## TL;DR

| Skill | Question it answers |
|---|---|
| **claude-md-improver** (official, Anthropic) | Is your CLAUDE.md content **well-written**? |
| **rules-architect** (this repo) | At which **layer** should your rule live? |

They are designed to coexist. `rules-architect` actively delegates L3 (CLAUDE.md content) audit to `claude-md-improver`.

## Quick comparison

| Dimension | claude-md-improver | rules-architect |
|---|---|---|
| **Scope** | CLAUDE.md files | 5-layer ecosystem (L0 hook / L1 memory / L2 path-scoped / L3 CLAUDE.md / L5 team lessons) |
| **Core question** | Content quality | Rule placement |
| **Output** | Score report + diff approval → Edit | Install 3 core hooks + path-scoped rule + maintenance docs + scripts |
| **Mechanism** | One-shot audit (read report → fix) | Continuous interception (real-time hook fires, no attention dependency) |
| **Modifies settings.json** | No | Yes (registers hooks, with manifest-based rollback) |
| **L3 CLAUDE.md content audit** | ✅ Specialty (6-criteria A–F grading) | ❌ Explicitly delegates to claude-md-improver |
| **L1 memory management** | ❌ | ✅ 5-Q SOP / upgrade / retire / team sync |
| **L0 hook real-time interception** | ❌ | ✅ 3 core Hooks; project workflow Hooks are examples only |
| **L2 path-scoped edit-triggered injection** | ❌ | ✅ `rule-intake.md` |
| **L5 team lessons sync** | ❌ | ✅ `memory_sync.py` |

## Real-world scenarios

| Scenario | claude-md-improver | rules-architect |
|---|---|---|
| Stale build command in CLAUDE.md | ✅ Detects + proposes fix | ❌ Doesn't care about content |
| A rule keeps being forgotten in memory | ❌ Doesn't look at memory | ✅ 5-Q SOP → upgrade to L0 hook |
| Forgetting status summary after PR creation | ❌ | ⚠️ Derive from the optional `mr_created_reminder` example; not installed by default |
| CLAUDE.md too long, attention diluted | ⚠️ Conciseness grade only | ✅ 5-Q SOP pushes rules down to L2 path-scoped |
| Personal memory ↔ team lessons sync | ❌ | ✅ `memory_sync.py` (push only, by design) |
| Comprehensive CLAUDE.md audit | ✅ **Its specialty** | ❌ Delegates |
| Team rules invisible to codex/gemini | ❌ | ✅ 5-Q SOP Q3 pushes to L3/L5 |
| Automatic interception when rules misplaced | ❌ One-shot only | ✅ Real-time hook fires every session |

## Mental model

- **claude-md-improver** = **Editor / proofreader** — checks if your writing is well-crafted.
- **rules-architect** = **Librarian / architect** — decides which "shelf" each rule belongs on.

## Coordination (built-in)

`rules-architect`'s `diagnose.py` delegates L3 to claude-md-improver:

```python
def scan_l3_claude_md():
    return {
        "grade": "(delegated)",
        "delegated_to": "claude-md-management:claude-md-improver",
        "plugin_enabled": <detected>,
        "recommendation": (
            "Run /claude-md-management:claude-md-improver for L3 audit"
            if plugin_enabled else
            "Install claude-md-management plugin first..."
        ),
    }
```

`install_hooks.py` also actively prompts you to install claude-md-improver when not enabled, with an optional `--enable-claude-md-management` flag to auto-flip the `enabledPlugins` switch if the plugin is already cached.

## Best practice: install both

| When to use | Which skill |
|---|---|
| Monthly / periodic CLAUDE.md content audit | `/claude-md-management:claude-md-improver` |
| Day-to-day rule-placement interception | `rules-architect`'s installed hooks (automatic) |
| New rule emerges, need placement decision | `rules-architect`'s 5-Q SOP (auto-injected by hook + path-scoped) |
| Upgrade a memory entry to team lessons | `rules-architect`'s `memory_sync.py push` |

## Timing difference

- **claude-md-improver**: **Reflective** — you trigger it, read report once, apply fixes.
- **rules-architect**: **Preventive** — install once, then **every rule write** gets auto-intercepted + SOP injected.

Analogy: claude-md-improver is a yearly checkup. rules-architect is a resident doctor + ongoing prescription.

## Risk surface

| | claude-md-improver | rules-architect |
|---|---|---|
| Install risk | Very low (enable skill only) | Medium (deep-merges `settings.json`; manifest enables precise rollback) |
| False-positive trigger | N/A (manual invocation) | Low (per-session dedupe + question-form sentence rejection) |
| Undo | Disable plugin | `uninstall.py` precise rollback via manifest |
| CC version requirement | None special | ≥ 1.5.0 (UserPromptSubmit hook required) |

## One diagram

```
Your CC rule ecosystem
│
├── Content quality ─────→ claude-md-improver (one-shot audit + Edit)
│
└── Placement structure ─→ rules-architect (interception + persistent)
                                  │
                                  └── L3 portion auto-delegates ──→ claude-md-improver
```

Both are **orthogonal**, should be installed together. `rules-architect` actively prompts you to enable `claude-md-improver` during install.
