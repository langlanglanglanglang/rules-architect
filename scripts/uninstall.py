#!/usr/bin/env python3
"""
rules-architect skill: uninstall.py

Precise rollback per manifest (NOT bulk backup restore):
  1. For each installed_file: hash match → delete; mismatch → skip with warn
  2. For each settings_hooks_added: remove only those exact entries from
     settings.json (preserves user's other hooks)
  3. For each personal_md_sections: remove BEGIN/END marker block, keep rest

After completion: manifest itself is renamed to .removed with timestamp.

Usage:
  uninstall.py                     # interactive
  uninstall.py --dry-run
  uninstall.py --non-interactive
  uninstall.py --force             # delete even on hash mismatch (dangerous)
  uninstall.py --restore-backup    # also restore settings.json.bak.<ts>
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path


SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
MANIFEST_PATH = Path(os.environ.get("RULES_ARCHITECT_MANIFEST")
                     or (Path.home() / ".claude" / ".rules-architect-manifest.json"))
CODEX_HOME = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
CODEX_HOOKS_JSON = CODEX_HOME / "hooks.json"


def info(msg): print(f"  ℹ {msg}")
def ok(msg):   print(f"  ✅ {msg}")
def warn(msg): print(f"  ⚠️  {msg}")
def err(msg):  print(f"  ❌ {msg}", file=sys.stderr)


def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".",
                               suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except Exception: pass
        raise


def confirm(msg: str, default_yes: bool = False) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    try:
        a = input(f"  {msg} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default_yes
    if not a:
        return default_yes
    return a.startswith("y")


def remove_installed_files(manifest, dry_run, force, non_interactive,
                           key="installed_files"):
    removed_any = False
    for entry in list(manifest.get(key, [])):
        p = Path(entry["path"])
        recorded_hash = entry.get("hash_sha256")
        if not p.exists():
            info(f"{p}: already gone, skip")
            manifest[key].remove(entry)
            continue
        try:
            actual = file_sha256(p)
        except Exception as e:
            warn(f"{p}: cannot hash ({e}), skip")
            continue
        if actual != recorded_hash:
            if force:
                pass  # proceed
            elif non_interactive:
                warn(f"{p}: modified since install, skipping (use --force)")
                continue
            else:
                warn(f"{p}: hash mismatch — file modified since install")
                if not confirm("    Delete anyway?", default_yes=False):
                    continue
        if dry_run:
            info(f"DRY-RUN: would delete {p}")
        else:
            p.unlink()
            ok(f"Deleted {p}")
        manifest[key].remove(entry)
        removed_any = True
    return removed_any


def remove_settings_hooks(manifest, dry_run):
    added = manifest.get("settings_hooks_added", [])
    if not added or not SETTINGS_PATH.exists():
        return
    try:
        settings = json.loads(SETTINGS_PATH.read_text())
    except Exception as e:
        err(f"settings.json unreadable: {e}")
        return

    targets = set(
        (e["event"], e["matcher"], e["command"]) for e in added
    )
    hooks_section = settings.get("hooks", {})
    removed = 0
    for event in list(hooks_section.keys()):
        configs = hooks_section[event]
        new_configs = []
        for c in configs:
            matcher = c.get("matcher", "*")
            kept_hooks = []
            for h in c.get("hooks", []):
                cmd = h.get("command", "")
                if (event, matcher, cmd) in targets:
                    removed += 1
                    continue
                kept_hooks.append(h)
            if kept_hooks:
                c2 = dict(c)
                c2["hooks"] = kept_hooks
                new_configs.append(c2)
            # else: drop empty config block entirely
        if new_configs:
            hooks_section[event] = new_configs
        else:
            del hooks_section[event]

    if removed:
        if dry_run:
            info(f"DRY-RUN: would remove {removed} hook entries from settings.json")
        else:
            new_text = json.dumps(settings, indent=2, ensure_ascii=False)
            atomic_write(SETTINGS_PATH, new_text)
            ok(f"Removed {removed} hook entries from settings.json")
        manifest["settings_hooks_added"] = []
    else:
        info("No matching hook entries in settings.json")


def remove_codex_hooks(manifest, dry_run):
    """Remove only our entries from ~/.codex/hooks.json (mirror of
    remove_settings_hooks, but a codex UserPromptSubmit entry carries no
    'matcher' key → matcher is None, so compare with None default)."""
    added = manifest.get("codex_hooks_added", [])
    if not added or not CODEX_HOOKS_JSON.exists():
        return
    try:
        config = json.loads(CODEX_HOOKS_JSON.read_text())
    except Exception as e:
        err(f"codex hooks.json unreadable: {e}")
        return

    targets = set((e["event"], e["matcher"], e["command"]) for e in added)
    hooks_section = config.get("hooks", {})
    removed = 0
    for event in list(hooks_section.keys()):
        new_configs = []
        for c in hooks_section[event]:
            matcher = c.get("matcher")  # None when key absent (UserPromptSubmit)
            kept_hooks = []
            for h in c.get("hooks", []):
                cmd = h.get("command", "")
                if (event, matcher, cmd) in targets:
                    removed += 1
                    continue
                kept_hooks.append(h)
            if kept_hooks:
                c2 = dict(c)
                c2["hooks"] = kept_hooks
                new_configs.append(c2)
            # else: drop empty group entirely
        if new_configs:
            hooks_section[event] = new_configs
        else:
            del hooks_section[event]

    if removed:
        if dry_run:
            info(f"DRY-RUN: would remove {removed} entries from codex hooks.json")
        else:
            atomic_write(CODEX_HOOKS_JSON,
                         json.dumps(config, indent=2, ensure_ascii=False))
            ok(f"Removed {removed} entries from codex hooks.json")
        manifest["codex_hooks_added"] = []
    else:
        info("No matching entries in codex hooks.json")


def remove_personal_sections(manifest, dry_run, force, non_interactive):
    sections = manifest.get("personal_md_sections", [])
    for s in list(sections):
        f = Path(s["file"])
        begin = s["marker_begin"]
        end = s["marker_end"]
        if not f.exists():
            info(f"{f}: already gone, skip")
            sections.remove(s)
            continue
        text = f.read_text()
        if begin not in text or end not in text:
            warn(f"{f}: markers not found, leave untouched")
            sections.remove(s)
            continue
        # Remove the markered block
        pattern = re.compile(
            re.escape(begin) + r".*?" + re.escape(end) + r"\n?",
            re.DOTALL
        )
        new_text = pattern.sub("", text, count=1)
        if dry_run:
            info(f"DRY-RUN: would remove §六 markers from {f}")
        else:
            atomic_write(f, new_text)
            ok(f"Removed §六 from {f}")
        sections.remove(s)


def restore_backup_if_requested(manifest, dry_run):
    bak = manifest.get("settings_backup_path")
    if not bak:
        warn("No settings backup recorded in manifest")
        return
    bak_path = Path(bak)
    if not bak_path.exists():
        warn(f"Backup file missing: {bak}")
        return
    if dry_run:
        info(f"DRY-RUN: would restore {bak} → {SETTINGS_PATH}")
        return
    shutil.copy2(bak_path, SETTINGS_PATH)
    ok(f"Restored settings.json from {bak_path.name}")



def print_uninstall_preservation_summary() -> None:
    """Show what uninstall did NOT touch — for user trust."""
    print()
    print("✅ What we did NOT touch on uninstall:")
    print()
    print("   ✋ Your L1 memory files                — entirely yours, never deleted")
    print("   ✋ Your CLAUDE.md                       — never touched")
    print("   ✋ Your CLAUDE-personal.md outside §六  — §一~§五 (and others) preserved")
    print("   ✋ Other hooks in settings.json         — only our 3 entries removed")
    print("   ✋ Other .claude/rules/*.md             — only rule-intake.md removed")
    print("   ✋ Other entries in codex hooks.json    — only our entries removed")
    print()
    print("   Files you modified locally (hash mismatch) → skipped with warning, never deleted.")
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--non-interactive", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="Delete files even on hash mismatch (dangerous)")
    ap.add_argument("--restore-backup", action="store_true",
                    help="Also restore settings.json from backup file "
                         "(NOT precise rollback — full overwrite)")
    args = ap.parse_args()

    if not MANIFEST_PATH.exists():
        err(f"No manifest found at {MANIFEST_PATH} — nothing to uninstall")
        return 1

    manifest = json.loads(MANIFEST_PATH.read_text())
    print(f"\n📦 rules-architect uninstaller")
    print(f"   Manifest: {MANIFEST_PATH}")
    print(f"   Installed files: {len(manifest.get('installed_files', []))}")
    print(f"   Settings hook entries: {len(manifest.get('settings_hooks_added', []))}")
    print(f"   Personal MD sections: {len(manifest.get('personal_md_sections', []))}")
    print(f"   Codex hook files: {len(manifest.get('codex_installed_files', []))}")
    print(f"   Codex hook entries: {len(manifest.get('codex_hooks_added', []))}")
    print()

    if not args.non_interactive:
        if not confirm("Proceed with uninstall?", default_yes=False):
            err("Aborted")
            return 1

    print("\n--- Removing installed hook files ---")
    remove_installed_files(manifest, args.dry_run, args.force, args.non_interactive)

    print("\n--- Removing hook entries from settings.json ---")
    remove_settings_hooks(manifest, args.dry_run)

    print("\n--- Removing Codex hook files ---")
    remove_installed_files(manifest, args.dry_run, args.force,
                           args.non_interactive, key="codex_installed_files")

    print("\n--- Removing hook entries from codex hooks.json ---")
    remove_codex_hooks(manifest, args.dry_run)

    print("\n--- Removing §六 sections from personal markdown ---")
    remove_personal_sections(manifest, args.dry_run,
                              args.force, args.non_interactive)

    if args.restore_backup:
        print("\n--- Restoring settings.json backup ---")
        restore_backup_if_requested(manifest, args.dry_run)

    if args.dry_run:
        info("DRY-RUN complete. Nothing was actually changed.")
        return 0

    # Move manifest aside so future re-install starts fresh
    ts = time.strftime("%Y%m%d-%H%M%S")
    removed_path = MANIFEST_PATH.with_suffix(f".json.removed.{ts}")
    MANIFEST_PATH.rename(removed_path)
    ok(f"Manifest archived → {removed_path}")

    print_uninstall_preservation_summary()
    print("✨ Uninstall complete.")
    print("   Files you modified manually are preserved.")
    print("   Re-install: python3 .../scripts/install_hooks.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
