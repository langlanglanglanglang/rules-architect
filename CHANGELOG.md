# Changelog

All notable changes to rules-architect skill will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
