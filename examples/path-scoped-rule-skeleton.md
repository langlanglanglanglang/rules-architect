---
# Replace these with your file glob(s). CC will auto-inject this rule
# whenever the assistant edits a matching file.
paths:
  - "**/*.<your-extension>"
  - "<other/glob/pattern>"
---

# <Your Rule Name>

> One-line: when does this rule apply? E.g. "Editing protobuf files in apis/."

## Why this rule exists

What goes wrong if you skip it? Reference the actual incident or constraint:
- "Forgetting to renumber proto fields breaks wire compatibility"
- "Skipping `make api` after .proto changes leaves codegen stale"
- etc.

## Core constraints (hard rules)

| # | Rule | Rationale |
|---|---|---|
| 1 | Do X | Because Y |
| 2 | Never do A | Because B (link incident if any) |

## Examples / anti-patterns

| Do this ✅ | Don't ❌ |
|---|---|
| `git tag -a v1.2.3 -m "..."` | `git checkout -b tag/v1.2.3` (legacy form) |
| ... | ... |

## Decision tree (optional, for complex rules)

```
Condition A?
├── yes → branch X
└── no  → branch Y
```

## Related rules / memory

- See L1 memory: `feedback_<related-topic>` (if any)
- See L3: `<repo>/CLAUDE.md §<section>`
- See L5 team lessons: `<repo>/docs/ai/lessons.md`

## When to retire / replace this rule

This rule becomes obsolete when:
- <condition>

Retirement steps:
1. Verify the condition has been met
2. Append `Deprecated: YYYY-MM-DD — <reason>` at the bottom
3. Remove from `paths:` frontmatter (CC stops auto-injecting)
4. Leave the file in git history for future reference
