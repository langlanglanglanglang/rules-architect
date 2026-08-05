# Changelog

All notable changes to rules-architect skill will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- A schema 1.2 two-stage recommendation flow: unresolved semantic choices are
  collected in `clarifications` before any final recommendation or operation
  can be produced.
- Final reports now include execution choices for all safe operations, selected
  operation IDs, create-only execution, plan adjustment, export, and rescan.
- `apply_reconciliation.py` supports partial selection with `--operation` and
  `--action`.
- Clarification outcomes now bind every affected occurrence/artifact to its
  final placement and action; final conclusions and operations are cross-linked.
- Mutating recommendations distinguish automatic, manual, and no-op execution;
  moves remain manual until transactional support exists.

### Changed

- Final plans reject `review`, non-empty `unclassified`, unresolved
  clarifications, and low-confidence recommendations. Review is now strictly a
  pre-plan user-confirmation activity.
- Partial apply state records only the successful transaction and appends a
  bounded fingerprint/digest history; empty plans write no manifest or state.
- Hook updates replace changed registrations, and inventory recognizes common
  non-Python Hook scripts plus third-party Path Rule generator markers.
- Preview and apply now share complete path/config/state/hash preflight, and
  apply rejects legacy or non-ready plans.
- Hook writes use an explicit desired registration set and must bind generated
  content to the final enforcement specification.

### Fixed

- Codex Hook installation no longer fails merely because the desktop client's
  shell cannot find a separate `codex` executable or finds an older CLI.
  Version detection is advisory by default; `--strict-version-check` preserves
  blocking behavior for CI.
- The Codex-only manual install example now uses the actual Skill discovery
  path at `~/.agents/skills/rules-architect`.

## [2.4.0] — 2026-08-03

### Added

- Interactive one-click target selection for Claude Code, Codex, or both.
- Codex Skill discovery installation at `~/.agents/skills/rules-architect`,
  sharing one checkout with Claude Code during dual-platform installs.
- Platform-aware, read-only rule inventory across exact-project memory,
  CLAUDE imports, AGENTS directory scope, recursive path rules, registered
  Claude/Codex hooks, and an explicitly configured lessons file.
- A compact executable recommendation contract with `--example`, plus a
  five-group distribution renderer.
- Unit coverage for discovery, extraction, deterministic fingerprints,
  recommendation coverage, blocking-hook requirements, and tamper detection.
- Isolated inventory → validate → render integration test.
- Convergent repeated-run reconciliation with stable rule IDs, private
  per-project state, hook ownership/health discovery, and a guarded apply tool.

### Changed

- All user-facing Skill dialogue, installer/uninstaller prompts, diagnostics,
  Hook-injected guidance, and five-group reports now use Chinese consistently;
  machine identifiers and the dedicated English reference docs remain stable.
- `bootstrap.sh` now installs both the Skill and selected-platform Hooks;
  `--platforms` and `--non-interactive` support reproducible CI installs.
- `/rules-architect` now defaults to a read-only distribution report; existing
  install and migration modes remain explicit, compatible flows.
- Hook recommendations distinguish `block` from `remind` instead of treating
  context injection as blocking.
- Lifecycle recommendations now distinguish create/reuse/update/disable/delete/
  keep/review and refuse automatic changes to external, unknown, or locally
  modified hook artifacts.

### Fixed

- `mark_memory_promoted.py` no longer treats ordinary prose containing
  `Promoted to:` as an existing promotion stub.
- Promotion integration coverage now proves that the live body changed and the
  backup contains the original text.
- Temporary diagnostic artifacts no longer use a fixed shared `/tmp` filename.
- Cleanup maintenance now removes expired `.cooldown` files as well as `.lock`
  files.

## [2.3.0] — 2026-07-13

### Added

- **Codex CLI support (first-class)** — `scripts/install_codex_hooks.py`
  installs the 3 core hooks into `~/.codex/hooks/` and deep-merges into
  `~/.codex/hooks.json` (preserving existing entries), tracked in the manifest
  under `codex_*` keys. Codex's hook I/O contract is identical to CC's
  (snake_case stdin fields + `hookSpecificOutput.additionalContext`); verified
  against Codex CLI v0.144.x.
- **`uninstall.py` rolls back Codex artifacts** — removes `codex_installed_files`
  and `codex_hooks_added` (handles the matcher-less `UserPromptSubmit` entry).
- **`RULES_ARCHITECT_MANIFEST` env var** — all install/uninstall scripts now
  honor it, so the full flow can be tested in true isolation (previously the
  manifest path was hardcoded to `~/.claude/`).

### Changed

- **`memory_intake_check.py` is dual-runtime** — parses `apply_patch` patch
  text for target paths (Codex has no structured `file_path` field), while
  still reading `tool_input.file_path` (CC). Self-contained, no new imports.
- **`examples/cross-tool-shim.md`** rewritten — Codex is now a native target,
  not a "no hook contract" workaround. gemini remains the shim example.
- **README / SKILL** — "not for codex" claims replaced with the Codex install
  path; L1-memory-doesn't-port noted as by-design.

## [2.2.0] — 2026-06-12

### Added

- **`bootstrap.sh`** — one-line remote installer. Users no longer need
  to clone manually:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash
  ```
  Supports `--install-dir`, `--mode D|C|B|A`, `--branch`, `--tag`,
  `--skip-install`, `--skip-clone-pull`. Handles existing-dir git pull
  and dependency check (git + python3).
- **README "Quick install" section** (English + 中文) showing curl
  one-liner + per-mode invocations + manual alternative.

### Rationale

Until v2.1.x users needed `git clone` + `python3 <script>` knowledge.
`bootstrap.sh` gives the standard "curl | bash" UX. Portable to any
project before/without official Anthropic plugin marketplace listing.

## [2.1.1] — 2026-06-12

### Fixed

- **`install_hook_from_memory.py` smoke test** previously used a static
  `session_id="smoke"` that left a stale dedupe lock at
  `~/.cache/claude-hooks/<hook>-smoke.lock`. Any later invocation with
  the same session id (e.g. sandbox verification, user's first real
  session) was silently skipped → empty output → broken downstream
  JSON parsing.
- Fix: smoke test now uses `install-smoke-<unix_ts>` (unique per run)
  and deletes its own lock immediately after, so the generated hook
  fires fresh on the user's first real CC session.
- Caught by sandbox Step 7.5 (Step 7.5 itself was correct; install was
  leaving stale state).

## [2.1.0] — 2026-06-12

### Added

- **`install_hook_from_memory.py`** — programmatic hook installer called by
  the main agent during the 5-step flow. Takes `--name`, `--event`,
  `--matcher`, `--reminder-file`, `--description`, `--feedback-source` and
  generates a fully wired hook (file + settings.json entry + manifest).
- **`mark_memory_promoted.py`** — replaces memory feedback body with a
  `Promoted to: <target> @ <date>` stub, preserving YAML frontmatter and the
  original body in git history.
- **`templates/hooks/generated-hook-skeleton.py.tmpl`** — base skeleton used
  by `install_hook_from_memory.py`; contains placeholders for name, event,
  matcher, reminder text, description, and feedback source.

### Changed

- **SKILL.md 5-Step Execution Flow** rewritten from the main-agent
  perspective. Memory migration is now integrated as Step 4b of the
  orchestrated flow — the main agent reads candidates from `diagnose.py`,
  asks the user per candidate, distills the reminder text from memory body,
  and calls the two new scripts.
- **`tests/integration/sandbox_install.sh`** — added Step 7.5 that
  exercises `install_hook_from_memory.py` and `mark_memory_promoted.py`
  end-to-end (creates a fake memory entry, installs generated hook, runs
  smoke test, verifies stub replacement and manifest tracking).

### Rationale

Prior to v2.1.0, memory parsing → migration would have required a separate
`migrate.py` script. That fragmented the natural flow (diagnose suggests →
install enacts). The two new scripts are designed to be called BY THE MAIN
AGENT, not directly by the user — the agent does the semantic distillation
(reading memory body → crafting concise reminder text → deciding matcher)
that a pure Python script can't.

## [2.0.0] — 2026-06-12

### BREAKING CHANGES

- **Core hook set reduced from 5 to 3** (universal SOP-injection + base infra
  only): `memory_intake_check`, `rule_intake_reminder`, `cleanup_hook`.
- **`error_recovery_checkpoint` and `dangerous_branch_reminder` moved to
  `examples/`** — they encode individual workflow preferences (preferred
  reporting cadence, team-specific protected branches) rather than universal
  patterns. Existing v1.x installs that want them retained should fork from
  `examples/` and register manually.

### Design philosophy

This release clarifies the boundary between:
- **What the skill installs by default**: only hooks that implement the
  skill's own methodology (5-Q SOP injection) and base infrastructure
  (cleanup).
- **What lives in `examples/`**: opinionated workflow hooks the user can
  fork. Documentation now explicitly addresses "this is opinionated, not
  universal" for each opt-in.

### Upgrading from 1.x

- Run `uninstall.py` then re-install with `install_hooks.py` (v2.0.0).
- If you relied on the 2 removed hooks: copy them from `examples/` into
  `~/.claude/hooks/` and add matching entries to `~/.claude/settings.json`.

### Other changes

- Updated `diagnose.py` `GENERIC_HOOKS` set + grading thresholds.
- Updated `tests/integration/sandbox_install.sh` expected hook list.
- Updated `templates/settings-snippet.json.tmpl` to reflect 3-hook layout.
- Documentation overhaul: README (English + 中文), SKILL.md, comparison doc.

## [1.0.0] — 2026-06-12

Initial release.

### Added
- 5-layer memory model (L0 hook / L1 memory / L2 path-scoped / L3 CLAUDE.md / L5 team lessons)
- 5-question placement SOP with self-contained reminders in every hook
- 5 generic Claude Code hooks (all parametrized, no project-specific assumptions):
  - `error_recovery_checkpoint` — tool error → force 3-line recovery report
  - `memory_intake_check` — writing to memory → inject 5-Q SOP
  - `rule_intake_reminder` — user message has rule keywords → inject 5-Q SOP
    (Chinese + English presets; question-form rejection)
  - `dangerous_branch_reminder` — checkout to protected branches → soft reminder
    (default `develop|test|master`, configurable via `PROTECTED_BRANCHES` env)
  - `cleanup_hook` — SessionStart: lock TTL + audit rotation
- 1 path-scoped rule (`rule-intake.md`) injecting SOP when editing any rule file
- §六 maintenance template for `CLAUDE-personal.md` (HTML markered for precise round-trip)
- 5 install/diagnose/uninstall scripts:
  - `diagnose.py` — scan L0/L1/L2/L5; delegate L3 to claude-md-improver; `--json` output
  - `install_hooks.py` — CC version check, atomic deep-merge into settings.json,
    sha256 manifest, smoke-test, optional `claude-md-management` auto-enable
  - `install_rule_intake.py` — project-level path-scoped install
  - `install_personal_md_section.py` — §六 marker-based insert
  - `uninstall.py` — precise per-manifest rollback
- 4 examples for project-specific extension (not installed by default)
- E2E sandbox test (`tests/integration/sandbox_install.sh`)
- Cross-platform cache directory abstraction (XDG_CACHE_HOME / LOCALAPPDATA)
- Manifest schema with sha256 hash, install timestamp, skill version

### Notes
- L3 (CLAUDE.md) audit is delegated to the official `claude-md-management` plugin.
  Install via `/plugin claude-md-management`; `install_hooks.py` detects and
  optionally enables it.
- Requires Claude Code >= 1.5.0 (UserPromptSubmit hook).
