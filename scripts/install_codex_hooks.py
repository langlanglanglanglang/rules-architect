#!/usr/bin/env python3
"""
rules-architect skill: install_codex_hooks.py

Install the 3 generic rules-architect hooks into a Codex CLI setup:
  - render the same self-contained templates into ~/.codex/hooks/
  - deep-merge entries into ~/.codex/hooks.json (preserving everything already
    there, with same-matcher conflict detection)
  - track every artifact in the shared manifest under codex_* keys so
    uninstall.py can roll back precisely

Why this works: Codex's hook I/O contract is identical to Claude Code's —
snake_case stdin fields (session_id / tool_name / tool_input / hook_event_name)
and `hookSpecificOutput.additionalContext` output. The only differences are
the config file location and the event matchers:

  | rules-architect hook   | CC matcher          | Codex event / matcher       |
  |------------------------|---------------------|-----------------------------|
  | memory_intake_check.py | PreToolUse          | PreToolUse / apply_patch    |
  |                        | Write|Edit|MultiEdit|  (codex file edits = apply_patch) |
  | rule_intake_reminder.py| UserPromptSubmit /* | UserPromptSubmit (no matcher)|
  | cleanup_hook.py        | SessionStart /*     | SessionStart / startup|resume|

memory_intake_check.py is dual-runtime: it reads tool_input.file_path (CC) and
also parses apply_patch patch text (Codex). The same rendered script serves
both tools.

Codex TRUST NOTE: non-managed command hooks must be reviewed and trusted (by
hash) before Codex runs them. This installer writes hooks.json but does NOT
auto-trust — that is a security boundary owned by the user. After install, run
`/hooks` in the Codex TUI to review and toggle them on, or Codex will prompt on
first tool use.

Usage:
  install_codex_hooks.py                        # interactive, install
  install_codex_hooks.py --dry-run              # print plan, modify nothing
  install_codex_hooks.py --non-interactive      # CI: skip on conflict
  install_codex_hooks.py --rule-intake-keywords english
  install_codex_hooks.py --force                # overwrite existing
  install_codex_hooks.py --skip-version-check
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional


SKILL_VERSION = "1.0.0"
MIN_CODEX_VERSION = "0.124.0"   # hooks engine stable as of v0.124.0

# Codex event/matcher mapping. matcher=None → emit an entry with no "matcher"
# key (required for UserPromptSubmit, where Codex ignores matcher).
CODEX_HOOK_TEMPLATES = [
    ("memory_intake_check.py", {"event": "PreToolUse", "matcher": "apply_patch"}),
    ("rule_intake_reminder.py", {"event": "UserPromptSubmit", "matcher": None}),
    ("cleanup_hook.py", {"event": "SessionStart", "matcher": "startup|resume"}),
]


# === Paths ===
SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_DIR / "templates" / "hooks"
CODEX_HOME = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
HOOKS_DEST = CODEX_HOME / "hooks"
HOOKS_JSON = CODEX_HOME / "hooks.json"
MANIFEST_PATH = Path((os.environ.get("RULES_ARCHITECT_MANIFEST") or "").strip()
                     or (Path.home() / ".claude" / ".rules-architect-manifest.json"))


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


def check_codex_version(skip: bool) -> bool:
    if skip:
        warn("Skipping Codex version check (--skip-version-check)")
        return True
    try:
        out = subprocess.run(
            ["codex", "--version"],
            capture_output=True, text=True, timeout=5
        )
        if out.returncode != 0:
            err(f"`codex --version` failed: {out.stderr}")
            return False
        version_str = out.stdout.strip()
        current = parse_version(version_str)
        required = parse_version(MIN_CODEX_VERSION)
        if current < required:
            err(
                f"Codex version {version_str} < required {MIN_CODEX_VERSION} "
                "(hooks engine stabilized in v0.124.0)"
            )
            return False
        ok(f"Codex version {version_str} >= {MIN_CODEX_VERSION}")
        return True
    except FileNotFoundError:
        err("`codex` CLI not found in PATH. Install Codex CLI first.")
        return False
    except Exception as e:
        err(f"Codex version check failed: {e}")
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
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


# === Manifest (shared with CC installer; codex_* keys are additive) ===
def load_manifest(dry_run: bool = False) -> dict:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text())
        except Exception:
            if dry_run:
                warn("Manifest unreadable (DRY-RUN: would quarantine to "
                     ".corrupt.<ts>); using a fresh in-memory manifest, no files touched")
            else:
                ts = time.strftime("%Y%m%d-%H%M%S")
                bad = MANIFEST_PATH.with_suffix(f".json.corrupt.{ts}")
                try:
                    MANIFEST_PATH.rename(bad)
                    warn(f"Manifest unreadable → quarantined to {bad.name}; starting fresh. "
                         "Old install entries are NOT auto-tracked — recover from that file.")
                except Exception:
                    warn("Manifest unreadable and could not be quarantined; starting fresh")
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


# === hooks.json backup ===
def backup_hooks_json(dry_run: bool) -> Optional[str]:
    if not HOOKS_JSON.exists():
        info("hooks.json does not exist yet — will create new")
        return None
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = HOOKS_JSON.with_suffix(f".json.bak.{ts}")
    if dry_run:
        info(f"DRY-RUN: would back up {HOOKS_JSON} → {bak}")
        return str(bak)
    shutil.copy2(HOOKS_JSON, bak)
    ok(f"Backed up {HOOKS_JSON.name} → {bak.name}")
    return str(bak)


# === Hook file installation ===
def install_hook_file(
    template_name: str,
    vars_: dict,
    manifest: dict,
    dry_run: bool,
    force: bool,
    interactive: bool,
) -> str:
    # Returns one of: "ok" (our file is in place → register it), "skip" (a
    # foreign same-named file was left untouched → must NOT register it),
    # "abort" (fatal, stop the install).
    template_path = TEMPLATES_DIR / (template_name + ".tmpl")
    if not template_path.exists():
        err(f"Template missing: {template_path}")
        return "abort"
    raw = template_path.read_text()
    rendered = substitute(raw, vars_)
    rendered_hash = text_sha256(rendered)
    dest_path = HOOKS_DEST / template_name

    if dest_path.exists():
        existing_hash = file_sha256(dest_path)
        if existing_hash == rendered_hash:
            info(f"{template_name}: already installed and identical, skip")
            # Adopt into manifest if untracked (e.g. manifest was lost/reset),
            # so uninstall can still remove it precisely later.
            tracked = manifest.setdefault("codex_installed_files", [])
            if not any(f.get("path") == str(dest_path) for f in tracked):
                tracked.append({
                    "path": str(dest_path),
                    "hash_sha256": rendered_hash,
                    "owner": "rules-architect",
                    "template_version": SKILL_VERSION,
                    "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                })
                info(f"{template_name}: adopted into manifest (was untracked)")
            return "ok"
        if not force:
            if interactive:
                print(f"\n  Hook {template_name} exists with different content.")
                print("    [s]kip  [r]eplace  [b]ackup-then-replace  [a]bort")
                choice = input("  Choice? ").strip().lower()
                if choice == "s":
                    info(f"{template_name}: skipped by user (will NOT be registered)")
                    return "skip"
                if choice == "b":
                    bak = dest_path.with_suffix(f".py.bak.{int(time.time())}")
                    if not dry_run:
                        shutil.copy2(dest_path, bak)
                    info(f"{template_name}: backup → {bak.name}")
                elif choice == "a":
                    err("Aborted by user")
                    return "abort"
                elif choice != "r":
                    info(f"{template_name}: unrecognized choice, skipping (will NOT be registered)")
                    return "skip"
            else:
                warn(f"{template_name}: differs from template, skipping "
                     "(use --force to overwrite; will NOT be registered)")
                return "skip"

    if dry_run:
        info(f"DRY-RUN: would write {dest_path} ({len(rendered)} bytes)")
        return "ok"

    atomic_write(dest_path, rendered)
    try:
        os.chmod(dest_path, 0o755)
    except Exception:
        pass
    ok(f"Installed {template_name} → {dest_path}")

    manifest["codex_installed_files"] = [
        f for f in manifest.get("codex_installed_files", [])
        if f.get("path") != str(dest_path)
    ]
    manifest["codex_installed_files"].append({
        "path": str(dest_path),
        "hash_sha256": rendered_hash,
        "owner": "rules-architect",
        "template_version": SKILL_VERSION,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })
    return "ok"


def _adopt_registration(manifest: dict, event, matcher, command) -> None:
    """Record an already-present hooks.json registration into the manifest if
    it isn't tracked yet (e.g. the manifest was lost/reset), so uninstall won't
    leave a dangling entry after deleting the script."""
    tracked = manifest.setdefault("codex_hooks_added", [])
    if not any(e.get("event") == event and e.get("matcher") == matcher
               and e.get("command") == command for e in tracked):
        tracked.append({"event": event, "matcher": matcher,
                        "command": command, "owner": "rules-architect"})
        info(f"hooks.json: {event} adopted into manifest")


# === hooks.json deep-merge ===
def merge_hooks_json(
    manifest: dict,
    dry_run: bool,
    force: bool,
    interactive: bool,
    registerable: set,
) -> bool:
    if HOOKS_JSON.exists():
        try:
            config = json.loads(HOOKS_JSON.read_text())
        except Exception as e:
            err(f"hooks.json unreadable: {e}")
            return (False, 0, 0)
        if not isinstance(config, dict):
            err("hooks.json is not a JSON object")
            return (False, 0, 0)
    else:
        config = {}

    config.setdefault("hooks", {})
    hooks_section = config["hooks"]

    added_this_run = []
    skipped_conflicts = []   # same-matcher groups we did NOT register into

    for template_name, hook_def in CODEX_HOOK_TEMPLATES:
        # Never register a template whose file we did NOT install (a foreign
        # same-named file was skipped) — otherwise hooks.json would activate
        # that script as ours while it stays untracked in the manifest.
        if template_name not in registerable:
            warn(f"hooks.json: not registering {template_name} — its file was "
                 "skipped (not our content)")
            continue
        event = hook_def["event"]
        matcher = hook_def["matcher"]
        # Quote the script path so a CODEX_HOME / home dir containing spaces
        # (e.g. "/Users/Jane Doe/.codex") does not split the command.
        # (python3 is left bare, resolved via PATH — matches the CC installer;
        # Windows remains "partial support" per docs.)
        command = f"python3 {shlex.quote(str(HOOKS_DEST / template_name))}"

        hooks_section.setdefault(event, [])

        # Matcher-less events (UserPromptSubmit): Codex ignores the matcher, so
        # ALL entries for the event form one pool. Match our command across all
        # of them to stay idempotent, and never create a second matcher-less
        # group beside an existing matcher:"*" one.
        if matcher is None:
            if any(h.get("command") == command
                   for e in hooks_section[event] for h in e.get("hooks", [])):
                info(f"hooks.json: {event} already has our command, skip")
                _adopt_registration(manifest, event, matcher, command)
                continue
            if hooks_section[event]:
                hooks_section[event][0].setdefault("hooks", []).append(
                    {"type": "command", "command": command})
            else:
                hooks_section[event].append(
                    {"hooks": [{"type": "command", "command": command}]})
            added_this_run.append({
                "event": event, "matcher": matcher,
                "command": command, "owner": "rules-architect",
            })
            continue

        # Find an existing group with the same matcher
        existing_entry = None
        for entry in hooks_section[event]:
            if entry.get("matcher") == matcher:
                existing_entry = entry
                break

        if existing_entry is None:
            new_entry = {"hooks": [{"type": "command", "command": command}]}
            if matcher is not None:
                new_entry = {"matcher": matcher, **new_entry}
            hooks_section[event].append(new_entry)
            added_this_run.append({
                "event": event, "matcher": matcher,
                "command": command, "owner": "rules-architect",
            })
        else:
            commands_in_entry = [
                h.get("command", "") for h in existing_entry.get("hooks", [])
            ]
            if command in commands_in_entry:
                info(f"hooks.json: {event}/{matcher} already has our command, skip")
                _adopt_registration(manifest, event, matcher, command)
                continue
            if force:
                existing_entry.setdefault("hooks", []).append(
                    {"type": "command", "command": command}
                )
                added_this_run.append({
                    "event": event, "matcher": matcher,
                    "command": command, "owner": "rules-architect",
                })
                info(f"hooks.json: {event}/{matcher}: appended (forced)")
            elif interactive:
                print(f"\n  Conflict: {event}/{matcher} has commands:")
                for c in commands_in_entry:
                    print(f"    {c}")
                print(f"  Want to add: {command}")
                choice = input(
                    "  [a]ppend  [s]kip  abort? ").strip().lower()
                if choice == "a":
                    existing_entry["hooks"].append(
                        {"type": "command", "command": command}
                    )
                    added_this_run.append({
                        "event": event, "matcher": matcher,
                        "command": command, "owner": "rules-architect",
                    })
                else:
                    info(f"hooks.json: {event}/{matcher}: skipped")
                    skipped_conflicts.append((event, matcher))
                    continue
            else:
                warn(f"hooks.json: {event}/{matcher} conflicts, skipping. "
                     "Re-run with --force or interactively")
                skipped_conflicts.append((event, matcher))
                continue

    def _note_skips():
        for event, matcher in skipped_conflicts:
            warn(f"NOT registered: {event}"
                 + (f"/{matcher}" if matcher else "")
                 + " already has a different command — re-run with --force to append")

    if not added_this_run:
        if skipped_conflicts:
            _note_skips()
            info(f"hooks.json: 0 added, {len(skipped_conflicts)} skipped (conflicts)")
        else:
            info("hooks.json: no changes needed")
        return (True, 0, len(skipped_conflicts))

    if dry_run:
        info(f"DRY-RUN: would write {HOOKS_JSON}")
        info(f"DRY-RUN: would add {len(added_this_run)} hook entries")
        for a in added_this_run:
            info(f"   + {a['event']}"
                 + (f"/{a['matcher']}" if a['matcher'] else "")
                 + f" → {a['command']}")
        _note_skips()
        return (True, len(added_this_run), len(skipped_conflicts))

    atomic_write(HOOKS_JSON, json.dumps(config, indent=2, ensure_ascii=False))
    ok(f"hooks.json: added {len(added_this_run)} entries")
    _note_skips()

    existing = manifest.get("codex_hooks_added", [])
    seen = {(e["event"], e["matcher"], e["command"]) for e in existing}
    for a in added_this_run:
        key = (a["event"], a["matcher"], a["command"])
        if key not in seen:
            existing.append(a)
            seen.add(key)
    manifest["codex_hooks_added"] = existing
    return (True, len(added_this_run), len(skipped_conflicts))


# === Smoke test ===
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
        # Codex apply_patch shape — must fire on a memory path
        "memory_intake_check.py": {
            "session_id": "smoke-codex",
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: /x/memory/feedback_y.md\n+z\n*** End Patch"
            },
        },
        "rule_intake_reminder.py": {
            "session_id": "smoke-codex",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "test message",
        },
        "cleanup_hook.py": {"hook_event_name": "SessionStart"},
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


def print_summary(backup_path: Optional[str], added: int, skipped: int) -> None:
    print()
    print("✅ Content preservation summary (Codex):")
    print()
    print("   ✋ Codex private memory        — NOT touched")
    print("   ✋ AGENTS.md                   — NOT touched")
    print("   ✋ Existing hooks.json entries — deep-merge preserves everything else")
    print("   ✋ Existing hook scripts       — skipped on hash mismatch")
    print()
    print("   ⭐ Changes (all tracked in manifest under codex_* keys):")
    print(f"      + up to 3 hook scripts in {HOOKS_DEST}/")
    print(f"      + {added} hook entr{'y' if added == 1 else 'ies'} in {HOOKS_JSON}")
    if skipped:
        print(f"      ! {skipped} entr{'y' if skipped == 1 else 'ies'} SKIPPED (conflict) "
              "— re-run with --force to append")
    print("        (memory_intake_check / rule_intake_reminder / cleanup_hook)")
    if backup_path:
        print(f"      → hooks.json backed up: {backup_path}")
    print()
    print("   Uninstall is precise (hash-verified per manifest):")
    print(f"      python3 {SKILL_DIR}/scripts/uninstall.py")
    print()


def print_trust_notice() -> None:
    print("🔐 Codex trust step (required — hooks stay OFF until you trust them):")
    print("   Codex only runs non-managed command hooks after you review and")
    print("   trust them by hash. To activate:")
    print("     1. Start Codex, run  /hooks  in the TUI")
    print("     2. Review the 3 rules-architect hooks and toggle them on")
    print("   (Or: Codex will prompt for review on first matching tool use.)")
    print("   If you edit a hook later, Codex marks it for re-review by hash.")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Install rules-architect hooks for Codex CLI")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print plan, modify nothing")
    ap.add_argument("--non-interactive", action="store_true",
                    help="Never prompt; default to safe choice (skip conflicts)")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing files & hook entries")
    ap.add_argument("--rule-intake-keywords",
                    choices=["chinese", "english"], default="chinese",
                    help="Keyword preset for rule_intake_reminder.py")
    ap.add_argument("--skip-version-check", action="store_true",
                    help="Bypass Codex version check (not recommended)")
    args = ap.parse_args()

    print(f"\n📦 rules-architect Codex installer v{SKILL_VERSION}")
    print(f"   Mode: {'DRY-RUN' if args.dry_run else 'INSTALL'}")
    print(f"   Interactive: {not args.non_interactive}")
    print(f"   Force: {args.force}")
    print(f"   Templates:  {TEMPLATES_DIR}")
    print(f"   Codex home: {CODEX_HOME}")
    print(f"   Hooks dest: {HOOKS_DEST}")
    print(f"   hooks.json: {HOOKS_JSON}")
    print(f"   Manifest:   {MANIFEST_PATH}")
    print()

    if not check_codex_version(args.skip_version_check):
        return 2

    # Pre-flight: refuse to write ANY hook file if the target hooks.json is
    # present but unparseable — otherwise we'd leave untracked files behind
    # (merge would fail after files are already written), breaking rollback.
    if HOOKS_JSON.exists():
        try:
            _cfg = json.loads(HOOKS_JSON.read_text())
        except Exception as e:
            err(f"hooks.json is present but not valid JSON ({e}). "
                "Fix it first so install stays atomic and rollback precise.")
            return 2
        if not isinstance(_cfg, dict) or not isinstance(_cfg.get("hooks", {}), dict):
            err("hooks.json has an unexpected shape (root must be an object "
                "with an object 'hooks'). Fix it first so the merge can't fail "
                "mid-install after files are written.")
            return 2

    backup_path = backup_hooks_json(args.dry_run)

    manifest = load_manifest(args.dry_run)
    if backup_path:
        manifest["codex_hooks_backup_path"] = backup_path

    template_vars = {
        "SKILL_VERSION": SKILL_VERSION,
        "AUDIT_MAX_BYTES": "1048576",
        "RULE_INTAKE_KEYWORDS": args.rule_intake_keywords,
    }

    print("\n--- Installing hook files ---")
    registerable = set()
    for template_name, _ in CODEX_HOOK_TEMPLATES:
        status = install_hook_file(
            template_name, template_vars, manifest,
            args.dry_run, args.force,
            interactive=not args.non_interactive
        )
        if status == "abort":
            err("Hook installation failed.")
            return 3
        if status == "ok":
            registerable.add(template_name)

    print("\n--- Merging hooks.json ---")
    merge_ok, n_added, n_skipped = merge_hooks_json(
        manifest, args.dry_run, args.force,
        interactive=not args.non_interactive,
        registerable=registerable)
    if not merge_ok:
        err("hooks.json merge failed.")
        return 4

    if not args.dry_run:
        manifest["last_install_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        manifest["skill_version"] = SKILL_VERSION
        manifest["min_codex_version"] = MIN_CODEX_VERSION
        save_manifest(manifest)
        ok(f"Manifest saved → {MANIFEST_PATH}")

    if not args.dry_run:
        print("\n--- Smoke-testing installed hooks ---")
        smoke_test_all()

    print_summary(backup_path, n_added, n_skipped)
    print_trust_notice()
    print("✨ Codex install complete.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
