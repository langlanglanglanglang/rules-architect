#!/usr/bin/env python3
"""
rules-architect skill: install_personal_md_section.py

Insert §六 Rule architecture maintenance section into <project>/CLAUDE-personal.md
(or other target). Uses HTML comment markers for precise round-trip:

  <!-- rules-architect:section-6 BEGIN -->
  ...
  <!-- rules-architect:section-6 END -->

If markers exist: replace content between them.
If markers don't exist: append at end of file (or before '## 维护' if found).

Tracks in manifest so uninstall.py can precisely remove only the marker block,
preserving everything else.

Usage:
  install_personal_md_section.py
  install_personal_md_section.py --target ./CLAUDE-personal.md
  install_personal_md_section.py --dry-run
  install_personal_md_section.py --create-if-missing  # create new file if absent
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path


SKILL_VERSION = "1.0.0"
MARKER_BEGIN = "<!-- rules-architect:section-6 BEGIN -->"
MARKER_END = "<!-- rules-architect:section-6 END -->"

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_DIR / "templates" / "personal-section-6.md.tmpl"
MANIFEST_PATH = Path((os.environ.get("RULES_ARCHITECT_MANIFEST") or "").strip()
                     or (Path.home() / ".claude" / ".rules-architect-manifest.json"))


def info(msg): print(f"  ℹ {msg}")
def ok(msg):   print(f"  ✅ {msg}")
def warn(msg): print(f"  ⚠️  {msg}")
def err(msg):  print(f"  ❌ {msg}", file=sys.stderr)


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
        "personal_md_sections": [],
        "last_install_at": None,
    }


def save_manifest(m: dict) -> None:
    atomic_write(MANIFEST_PATH, json.dumps(m, indent=2, ensure_ascii=False))


def render_section(cache_dir: str, protected_branches: str) -> str:
    raw = TEMPLATE_PATH.read_text()
    section_body = (
        raw
        .replace("{{SKILL_VERSION}}", SKILL_VERSION)
        .replace("{{CACHE_DIR}}", cache_dir)
        .replace("{{PROTECTED_BRANCHES}}", protected_branches)
    )
    return f"{MARKER_BEGIN}\n{section_body.strip()}\n{MARKER_END}\n"


def extract_block(text: str):
    """Return the exact stored §六 block (MARKER_BEGIN..MARKER_END + optional
    trailing newline) — matches the form section_hash was computed over."""
    m = re.search(
        re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END) + r"\n?",
        text, re.DOTALL,
    )
    return m.group(0) if m else None


def recorded_section_hash(target: Path, dry_run: bool = False):
    for s in load_manifest(dry_run).get("personal_md_sections", []):
        if s.get("file") == str(target):
            return s.get("section_hash")
    return None


def replace_or_append(text: str, new_section: str) -> tuple:
    """Returns (new_text, action)"""
    if MARKER_BEGIN in text and MARKER_END in text:
        # Replace existing markered region
        pattern = re.compile(
            re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END) + r"\n?",
            re.DOTALL
        )
        new_text = pattern.sub(new_section, text, count=1)
        return new_text, "replaced"

    # Insert before '## 维护' if present, else append
    maintain_pat = re.compile(r"^## 维护\b", re.MULTILINE)
    m = maintain_pat.search(text)
    if m:
        prefix = text[:m.start()].rstrip() + "\n\n"
        suffix = text[m.start():]
        new_text = prefix + new_section + "\n" + suffix
        return new_text, "inserted_before_维护"

    sep = "" if text.endswith("\n") else "\n"
    new_text = text + sep + "\n" + new_section
    return new_text, "appended"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="CLAUDE-personal.md",
                    help="Target file path (default: ./CLAUDE-personal.md)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--create-if-missing", action="store_true",
                    help="Create a fresh CLAUDE-personal.md if target doesn't exist")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite the §六 block even if it was edited since install")
    ap.add_argument("--protected-branches", default="develop|test|master",
                    help="For §六 'Hook health' subsection reference")
    ap.add_argument("--cache-dir",
                    default=str(Path.home() / ".cache" / "claude-hooks"),
                    help="Cache dir referenced in §六")
    args = ap.parse_args()

    target = Path(args.target).resolve()
    if not TEMPLATE_PATH.exists():
        err(f"Template missing: {TEMPLATE_PATH}")
        return 2

    print(f"\n📦 personal-section-6 installer v{SKILL_VERSION}")
    print(f"   Target: {target}")
    print(f"   Template: {TEMPLATE_PATH}")
    print()

    rendered = render_section(args.cache_dir, args.protected_branches)
    rendered_hash = text_sha256(rendered)

    if not target.exists():
        if not args.create_if_missing:
            err(f"Target {target} does not exist. "
                "Use --create-if-missing to create.")
            return 1
        info(f"Creating new {target}")
        body = (
            "# Personal CLAUDE\n\n"
            "Personal preferences and workflow tweaks for this project.\n\n"
            + rendered
        )
        if args.dry_run:
            info(f"DRY-RUN: would create {target}")
            return 0
        atomic_write(target, body)
        ok(f"Created {target}")
        action = "created"
    else:
        existing = target.read_text()
        # Content-protection guard: if a §六 block exists and was edited since
        # install (its hash differs from the recorded section_hash), refuse to
        # overwrite unless --force. Mirrors the file hash-protection promise.
        if MARKER_BEGIN in existing:
            rec = recorded_section_hash(target, args.dry_run)
            cur = extract_block(existing)
            if rec and cur is not None and text_sha256(cur) != rec and not args.force:
                warn(f"§六 block in {target.name} was modified since install "
                     "(hash mismatch) — refusing to overwrite. Use --force to replace.")
                return 1
        new_text, action = replace_or_append(existing, rendered)
        if new_text == existing:
            ok("Already up to date — nothing to do")
            return 0
        if args.dry_run:
            info(f"DRY-RUN: would {action} ({len(rendered)} bytes inserted)")
            return 0
        atomic_write(target, new_text)
        ok(f"§六 {action} in {target}")

    # Manifest
    manifest = load_manifest()
    manifest.setdefault("personal_md_sections", [])
    manifest["personal_md_sections"] = [
        s for s in manifest["personal_md_sections"]
        if s.get("file") != str(target)
    ]
    manifest["personal_md_sections"].append({
        "file": str(target),
        "marker_begin": MARKER_BEGIN,
        "marker_end": MARKER_END,
        "section_hash": rendered_hash,
        "owner": "rules-architect",
        "template_version": SKILL_VERSION,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "action": action,
    })
    manifest["last_install_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save_manifest(manifest)
    ok(f"Manifest updated → {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
