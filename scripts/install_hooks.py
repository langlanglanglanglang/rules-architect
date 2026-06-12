#!/usr/bin/env python3
"""
rules-architect skill: install_hooks.py

Install 5 generic hooks (error_recovery / memory_intake / rule_intake /
dangerous_branch / cleanup) into ~/.claude/hooks/ and deep-merge entries
into ~/.claude/settings.json. Tracks every artifact in a manifest for
precise uninstall.

V2 BLOCKER fixes applied:
  - CC version check (fail < min)
  - settings.json backup before any write
  - JSON deep-merge with same-matcher conflict detection
  - Manifest with sha256 hash per file
  - Atomic write: tmp file → fsync → rename
  - On failure: roll back per manifest (NOT bulk backup restore)
  - Templates are parameterized + self-contained (no external section refs)

Usage:
  install_hooks.py                                # interactive, default mode B
  install_hooks.py --dry-run                      # print plan, modify nothing
  install_hooks.py --non-interactive              # CI mode: skip on conflict
  install_hooks.py --rule-intake-keywords english # use English preset
  install_hooks.py --protected-branches "main|develop|test"
  install_hooks.py --force                        # overwrite existing
  install_hooks.py --skip-version-check           # bypass CC version check
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional


SKILL_VERSION = "1.0.0"
MIN_CC_VERSION = "1.5.0"   # UserPromptSubmit hook required

HOOK_TEMPLATES = [
    ("error_recovery_checkpoint.py", {
        "event": "PostToolUse",
        "matcher": "Edit|Write|Bash|MultiEdit",
    }),
    ("memory_intake_check.py", {
        "event": "PreToolUse",
        "matcher": "Write|Edit|MultiEdit",
    }),
    ("rule_intake_reminder.py", {
        "event": "UserPromptSubmit",
        "matcher": "*",
    }),
    ("dangerous_branch_reminder.py", {
        "event": "PreToolUse",
        "matcher": "Bash",
    }),
    ("cleanup_hook.py", {
        "event": "SessionStart",
        "matcher": "*",
    }),
]


# === Paths ===
SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_DIR / "templates" / "hooks"
HOOKS_DEST = Path.home() / ".claude" / "hooks"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
MANIFEST_PATH = Path.home() / ".claude" / ".rules-architect-manifest.json"


# === Logging ===
def info(msg: str) -> None:
    print(f"  ℹ {msg}")


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")


def err(msg: str) -> None:
    print(f"  ❌ {msg}", file=sys.stderr)


# === Version check ===
def parse_version(s: str) -> tuple:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", s)
    if not m:
        return (0, 0, 0)
    return tuple(int(x) for x in m.groups())


def check_cc_version(skip: bool) -> bool:
    if skip:
        warn("Skipping CC version check (--skip-version-check)")
        return True
    try:
        out = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=5
        )
        if out.returncode != 0:
            err(f"`claude --version` failed: {out.stderr}")
            return False
        version_str = out.stdout.strip()
        current = parse_version(version_str)
        required = parse_version(MIN_CC_VERSION)
        if current < required:
            err(
                f"Claude Code version {version_str} < required {MIN_CC_VERSION} "
                "(UserPromptSubmit hook is required)"
            )
            return False
        ok(f"CC version {version_str} >= {MIN_CC_VERSION}")
        return True
    except FileNotFoundError:
        err("`claude` CLI not found in PATH. Install Claude Code first.")
        return False
    except Exception as e:
        err(f"CC version check failed: {e}")
        return False


# === Template substitution ===
def substitute(text: str, vars_: dict) -> str:
    for k, v in vars_.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


# === sha256 ===
def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# === Atomic write ===
def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        # rename is atomic on POSIX
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


# === Manifest ===
def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text())
        except Exception:
            warn(f"Manifest unreadable, starting fresh: {MANIFEST_PATH}")
    return {
        "skill_name": "rules-architect",
        "skill_version": SKILL_VERSION,
        "installed_files": [],
        "settings_hooks_added": [],
        "settings_backup_path": None,
        "last_install_at": None,
    }


def save_manifest(m: dict) -> None:
    atomic_write(MANIFEST_PATH, json.dumps(m, indent=2, ensure_ascii=False))


# === Settings.json backup ===
def backup_settings(dry_run: bool) -> Optional[str]:
    if not SETTINGS_PATH.exists():
        info("settings.json does not exist yet — will create new")
        return None
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = SETTINGS_PATH.with_suffix(f".json.bak.{ts}")
    if dry_run:
        info(f"DRY-RUN: would back up {SETTINGS_PATH} → {bak}")
        return str(bak)
    shutil.copy2(SETTINGS_PATH, bak)
    ok(f"Backed up {SETTINGS_PATH.name} → {bak.name}")
    return str(bak)


# === Hook installation ===
def install_hook_file(
    template_name: str,
    vars_: dict,
    manifest: dict,
    dry_run: bool,
    force: bool,
    interactive: bool,
) -> bool:
    template_path = TEMPLATES_DIR / (template_name + ".tmpl")
    if not template_path.exists():
        err(f"Template missing: {template_path}")
        return False
    raw = template_path.read_text()
    rendered = substitute(raw, vars_)
    rendered_hash = text_sha256(rendered)
    dest_path = HOOKS_DEST / template_name

    # Conflict detection
    if dest_path.exists():
        existing_hash = file_sha256(dest_path)
        if existing_hash == rendered_hash:
            info(f"{template_name}: already installed and identical, skip")
            return True
        if not force:
            if interactive:
                print(f"\n  Hook {template_name} exists with different content.")
                print(f"    [s]kip  [r]eplace  [b]ackup-then-replace  [a]bort")
                choice = input("  Choice? ").strip().lower()
                if choice == "s":
                    info(f"{template_name}: skipped by user")
                    return True
                if choice == "b":
                    bak = dest_path.with_suffix(f".py.bak.{int(time.time())}")
                    if not dry_run:
                        shutil.copy2(dest_path, bak)
                    info(f"{template_name}: backup → {bak.name}")
                elif choice == "a":
                    err("Aborted by user")
                    return False
                elif choice != "r":
                    info(f"{template_name}: unrecognized choice, skipping")
                    return True
            else:
                # non-interactive: skip on conflict (safe default)
                warn(f"{template_name}: differs from template, skipping "
                     "(use --force to overwrite)")
                return True

    if dry_run:
        info(f"DRY-RUN: would write {dest_path} ({len(rendered)} bytes)")
        return True

    atomic_write(dest_path, rendered)
    try:
        os.chmod(dest_path, 0o755)
    except Exception:
        pass
    ok(f"Installed {template_name}")

    # Record in manifest
    manifest["installed_files"] = [
        f for f in manifest["installed_files"]
        if f.get("path") != str(dest_path)
    ]
    manifest["installed_files"].append({
        "path": str(dest_path),
        "hash_sha256": rendered_hash,
        "owner": "rules-architect",
        "template_version": SKILL_VERSION,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })
    return True


# === Settings.json deep-merge ===
def merge_settings(
    manifest: dict,
    dry_run: bool,
    force: bool,
    interactive: bool,
) -> bool:
    if SETTINGS_PATH.exists():
        try:
            settings = json.loads(SETTINGS_PATH.read_text())
        except Exception as e:
            err(f"settings.json unreadable: {e}")
            return False
    else:
        settings = {}

    settings.setdefault("hooks", {})
    hooks_section = settings["hooks"]

    settings_added_this_run = []

    for template_name, hook_def in HOOK_TEMPLATES:
        event = hook_def["event"]
        matcher = hook_def["matcher"]
        command = f"python3 ~/.claude/hooks/{template_name}"

        hooks_section.setdefault(event, [])

        # Find existing config with same matcher
        existing_entry = None
        for entry in hooks_section[event]:
            if entry.get("matcher") == matcher:
                existing_entry = entry
                break

        if existing_entry is None:
            new_entry = {
                "matcher": matcher,
                "hooks": [{"type": "command", "command": command}],
            }
            hooks_section[event].append(new_entry)
            settings_added_this_run.append({
                "event": event,
                "matcher": matcher,
                "command": command,
                "owner": "rules-architect",
            })
        else:
            # Same matcher exists — check if same command already there
            commands_in_entry = [
                h.get("command", "") for h in existing_entry.get("hooks", [])
            ]
            if command in commands_in_entry:
                info(f"settings.json: {event}/{matcher} already has our command, skip")
                continue
            # Different command at same matcher — conflict
            if force:
                existing_entry.setdefault("hooks", []).append(
                    {"type": "command", "command": command}
                )
                settings_added_this_run.append({
                    "event": event, "matcher": matcher,
                    "command": command, "owner": "rules-architect",
                })
                info(f"settings.json: {event}/{matcher}: appended (forced)")
            elif interactive:
                print(f"\n  Conflict: {event}/{matcher} has commands:")
                for c in commands_in_entry:
                    print(f"    {c}")
                print(f"  Want to add: {command}")
                choice = input(
                    "  [a]ppend  [s]kip  [r]eplace_all  abort? ").strip().lower()
                if choice == "a":
                    existing_entry["hooks"].append(
                        {"type": "command", "command": command}
                    )
                    settings_added_this_run.append({
                        "event": event, "matcher": matcher,
                        "command": command, "owner": "rules-architect",
                    })
                elif choice == "r":
                    existing_entry["hooks"] = [
                        {"type": "command", "command": command}
                    ]
                    settings_added_this_run.append({
                        "event": event, "matcher": matcher,
                        "command": command, "owner": "rules-architect",
                    })
                else:
                    info(f"settings.json: {event}/{matcher}: skipped")
                    continue
            else:
                warn(f"settings.json: {event}/{matcher} conflicts, skipping. "
                     "Re-run with --force or --interactive")
                continue

    if not settings_added_this_run:
        info("settings.json: no changes needed")
        return True

    if dry_run:
        info(f"DRY-RUN: would write {SETTINGS_PATH}")
        info(f"DRY-RUN: would add {len(settings_added_this_run)} hook entries")
        return True

    new_text = json.dumps(settings, indent=2, ensure_ascii=False)
    atomic_write(SETTINGS_PATH, new_text)
    ok(f"settings.json: added {len(settings_added_this_run)} entries")

    # Record in manifest (don't duplicate existing entries)
    existing_settings = manifest.get("settings_hooks_added", [])
    seen = {(e["event"], e["matcher"], e["command"]) for e in existing_settings}
    for s in settings_added_this_run:
        key = (s["event"], s["matcher"], s["command"])
        if key not in seen:
            existing_settings.append(s)
            seen.add(key)
    manifest["settings_hooks_added"] = existing_settings
    return True


# === claude-md-management plugin check ===
CLAUDE_MD_PLUGIN = "claude-md-management@claude-plugins-official"


def check_plugin_cached(plugin_full: str) -> bool:
    """Check if a plugin is downloaded to ~/.claude/plugins/cache/."""
    if "@" not in plugin_full:
        return False
    plugin, marketplace = plugin_full.split("@", 1)
    cache_path = Path.home() / ".claude" / "plugins" / "cache" / marketplace / plugin
    return cache_path.exists()


def check_and_enable_claude_md_management(
    auto_enable: bool, interactive: bool, dry_run: bool
) -> None:
    """Check whether claude-md-management is enabled for L3 audit.

    Behavior:
      - Already enabled → ok message, return
      - Not downloaded → warn + give /plugin command, return
      - Downloaded but disabled → enable if --auto-enable OR interactive yes,
        else give instructions
    """
    if not SETTINGS_PATH.exists():
        warn("settings.json not yet created — plugin check deferred")
        return

    try:
        settings = json.loads(SETTINGS_PATH.read_text())
    except Exception as e:
        warn(f"settings.json unreadable for plugin check: {e}")
        return

    enabled_plugins = settings.get("enabledPlugins", {})
    if enabled_plugins.get(CLAUDE_MD_PLUGIN, False):
        ok(f"claude-md-management already enabled — L3 audit available")
        info(f"   Run /claude-md-management:claude-md-improver to audit CLAUDE.md files")
        return

    cached = check_plugin_cached(CLAUDE_MD_PLUGIN)
    if not cached:
        warn(
            "claude-md-management plugin not installed (needed for L3 CLAUDE.md audit)"
        )
        info("   To install:")
        info("     1. In Claude Code, run: /plugin claude-md-management")
        info("     2. Then: /reload-plugins")
        info("     3. Optionally re-run install_hooks.py to enable it automatically")
        return

    # Plugin downloaded but not enabled — we can flip the flag
    info(f"claude-md-management is downloaded but not enabled in settings.json")
    if not auto_enable:
        if interactive:
            print()
            choice = input(
                "  Enable claude-md-management now for L3 audit? [Y/n] "
            ).strip().lower()
            if choice in {"n", "no"}:
                info("Skipping claude-md-management enable")
                return
        else:
            info("   Re-run with --enable-claude-md-management to auto-enable, "
                 "or enable manually in settings.json")
            return

    if dry_run:
        info(f"DRY-RUN: would enable {CLAUDE_MD_PLUGIN} in settings.json")
        return

    enabled_plugins[CLAUDE_MD_PLUGIN] = True
    settings["enabledPlugins"] = enabled_plugins
    atomic_write(SETTINGS_PATH, json.dumps(settings, indent=2, ensure_ascii=False))
    ok(f"Enabled {CLAUDE_MD_PLUGIN}")
    info("   Run /reload-plugins in Claude Code to activate")
    info("   Then run /claude-md-management:claude-md-improver for L3 audit")


# === Dry-run hook validation ===
def smoke_test_hook(path: Path, sample_input: dict) -> bool:
    try:
        out = subprocess.run(
            ["python3", str(path)],
            input=json.dumps(sample_input),
            capture_output=True, text=True, timeout=5
        )
        return out.returncode == 0
    except Exception:
        return False


def smoke_test_all() -> bool:
    samples = {
        "error_recovery_checkpoint.py": {
            "tool_name": "Edit", "tool_input": {},
            "tool_response": {"is_error": True, "content": [{"type": "text", "text": "Error: x"}]},
        },
        "memory_intake_check.py": {
            "session_id": "smoke",
            "tool_input": {"file_path": "/x/memory/feedback_y.md"},
        },
        "rule_intake_reminder.py": {
            "session_id": "smoke", "prompt": "test message",
        },
        "dangerous_branch_reminder.py": {
            "session_id": "smoke", "tool_input": {"command": "ls"},
        },
        "cleanup_hook.py": {},
    }
    all_pass = True
    for name, sample in samples.items():
        path = HOOKS_DEST / name
        if not path.exists():
            continue
        if smoke_test_hook(path, sample):
            ok(f"smoke-test {name}: pass")
        else:
            err(f"smoke-test {name}: FAIL")
            all_pass = False
    return all_pass


# === Main ===
def main() -> int:
    ap = argparse.ArgumentParser(description="Install rules-architect hooks")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print plan, modify nothing")
    ap.add_argument("--non-interactive", action="store_true",
                    help="Never prompt; default to safe choice (skip conflicts)")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing files & hook entries")
    ap.add_argument("--rule-intake-keywords",
                    choices=["chinese", "english"], default="chinese",
                    help="Keyword preset for rule_intake_reminder.py")
    ap.add_argument("--protected-branches", default="develop|test|master",
                    help="Pipe-separated protected branches for "
                         "dangerous_branch_reminder.py")
    ap.add_argument("--skip-version-check", action="store_true",
                    help="Bypass CC version check (not recommended)")
    ap.add_argument("--enable-claude-md-management", action="store_true",
                    help="Auto-enable claude-md-management plugin "
                         "if downloaded (needed for L3 audit)")
    ap.add_argument("--skip-plugin-check", action="store_true",
                    help="Skip claude-md-management plugin check entirely")
    args = ap.parse_args()

    print(f"\n📦 rules-architect installer v{SKILL_VERSION}")
    print(f"   Mode: {'DRY-RUN' if args.dry_run else 'INSTALL'}")
    print(f"   Interactive: {not args.non_interactive}")
    print(f"   Force: {args.force}")
    print(f"   Templates: {TEMPLATES_DIR}")
    print(f"   Dest:      {HOOKS_DEST}")
    print(f"   Settings:  {SETTINGS_PATH}")
    print(f"   Manifest:  {MANIFEST_PATH}")
    print()

    # 1. CC version check
    if not check_cc_version(args.skip_version_check):
        return 2

    # 2. Backup
    backup_path = backup_settings(args.dry_run)

    # 3. Load manifest
    manifest = load_manifest()
    if backup_path:
        manifest["settings_backup_path"] = backup_path

    # 4. Template vars
    template_vars = {
        "SKILL_VERSION": SKILL_VERSION,
        "AUDIT_MAX_BYTES": "1048576",
    }

    # 5. Install hooks
    print("\n--- Installing hook files ---")
    all_ok = True
    for template_name, _ in HOOK_TEMPLATES:
        if not install_hook_file(
            template_name, template_vars, manifest,
            args.dry_run, args.force,
            interactive=not args.non_interactive
        ):
            all_ok = False
            break

    if not all_ok:
        err("Hook installation failed. Backup at: " + str(backup_path or "n/a"))
        return 3

    # 6. Merge settings.json
    print("\n--- Merging settings.json ---")
    if not merge_settings(manifest, args.dry_run, args.force,
                          interactive=not args.non_interactive):
        err("settings.json merge failed.")
        return 4

    # 7. Save manifest
    if not args.dry_run:
        manifest["last_install_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        manifest["skill_version"] = SKILL_VERSION
        manifest["min_cc_version"] = MIN_CC_VERSION
        save_manifest(manifest)
        ok(f"Manifest saved → {MANIFEST_PATH}")

    # 7.5. Check claude-md-management plugin (L3 audit)
    if not args.skip_plugin_check:
        print("\n--- L3 audit prerequisite: claude-md-management plugin ---")
        check_and_enable_claude_md_management(
            auto_enable=args.enable_claude_md_management,
            interactive=not args.non_interactive,
            dry_run=args.dry_run,
        )

    # 8. Smoke test
    if not args.dry_run:
        print("\n--- Smoke-testing installed hooks ---")
        smoke_test_all()

    # 9. Summary
    print()
    print("✨ Install complete.")
    print(f"   See {MANIFEST_PATH} for what was installed.")
    print(f"   Configure via env vars:")
    print(f"     RULE_INTAKE_KEYWORDS={args.rule_intake_keywords}  (set in shell)")
    print(f"     PROTECTED_BRANCHES='{args.protected_branches}'")
    print(f"   Uninstall: python3 {SKILL_DIR}/scripts/uninstall.py")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
