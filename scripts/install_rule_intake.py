#!/usr/bin/env python3
"""
rules-architect skill: install_rule_intake.py

Install `.claude/rules/rule-intake.md` into the CURRENT PROJECT (cwd or --dir).
This is the L2 path-scoped rule that auto-injects the 5-Question SOP when
editing any rule file.

Distinct from install_hooks.py: that one is USER-LEVEL (~/.claude/), this one
is PROJECT-LEVEL (<project>/.claude/rules/).

Atomic write + manifest tracking + idempotent re-install.

Usage:
  install_rule_intake.py                          # cwd
  install_rule_intake.py --dir /path/to/project   # explicit
  install_rule_intake.py --dry-run
  install_rule_intake.py --paths "**/MEMORY.md,**/*.foo"  # custom paths
  install_rule_intake.py --force                  # overwrite existing
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path


SKILL_VERSION = "1.0.0"
DEFAULT_PATHS = [
    "**/MEMORY.md",
    "**/feedback_*.md",
    "**/reference_*.md",
    "**/.claude/rules/*.md",
    "**/CLAUDE.md",
    "**/CLAUDE-personal.md",
    "**/CLAUDE-company.md",
    "**/AGENTS.md",
    "**/GEMINI.md",
]
# Project-specific rule docs (e.g. your team's workflow.md) can be added at
# install time via the --paths flag, comma-separated globs.

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_DIR / "templates" / "rules" / "rule-intake.md.tmpl"
MANIFEST_PATH = Path((os.environ.get("RULES_ARCHITECT_MANIFEST") or "").strip()
                     or (Path.home() / ".claude" / ".rules-architect-manifest.json"))


def info(msg): print(f"  ℹ {msg}")
def ok(msg):   print(f"  ✅ {msg}")
def warn(msg): print(f"  ⚠️  {msg}")
def err(msg):  print(f"  ❌ {msg}", file=sys.stderr)


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(p: Path) -> str:
    return text_sha256(p.read_text(errors="ignore"))


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


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text())
        except Exception:
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
        "last_install_at": None,
    }


def save_manifest(m: dict) -> None:
    atomic_write(MANIFEST_PATH, json.dumps(m, indent=2, ensure_ascii=False))


def render_paths_block(paths: list) -> str:
    return "\n".join(f"  - \"{p}\"" for p in paths)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(Path.cwd()),
                    help="Project root (default cwd)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--paths",
                    help="Comma-separated globs to override default paths list")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite if differs from template")
    args = ap.parse_args()

    project_root = Path(args.dir).resolve()
    rules_dir = project_root / ".claude" / "rules"
    dest_path = rules_dir / "rule-intake.md"

    if not TEMPLATE_PATH.exists():
        err(f"Template missing: {TEMPLATE_PATH}")
        return 2

    paths_list = (
        [p.strip() for p in args.paths.split(",") if p.strip()]
        if args.paths else DEFAULT_PATHS
    )

    print(f"\n📦 rule-intake.md installer v{SKILL_VERSION}")
    print(f"   Project: {project_root}")
    print(f"   Dest:    {dest_path}")
    print(f"   Paths:   {len(paths_list)} globs ({'custom' if args.paths else 'default'})")
    print()

    template = TEMPLATE_PATH.read_text()
    rendered = template.replace(
        "{{RULE_INTAKE_PATHS}}", render_paths_block(paths_list)
    ).replace("{{SKILL_VERSION}}", SKILL_VERSION)
    rendered_hash = text_sha256(rendered)

    # Idempotency check
    if dest_path.exists():
        existing_hash = file_sha256(dest_path)
        if existing_hash == rendered_hash:
            ok("Already installed with identical content — nothing to do")
            return 0
        if not args.force:
            warn(f"{dest_path} exists with different content. "
                 "Use --force to overwrite, or edit --paths to match.")
            return 1

    if args.dry_run:
        info(f"DRY-RUN: would write {dest_path} ({len(rendered)} bytes)")
        info(f"DRY-RUN: paths block:\n{render_paths_block(paths_list)}")
        return 0

    atomic_write(dest_path, rendered)
    ok(f"Installed {dest_path}")

    # Update manifest
    manifest = load_manifest()
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
        "kind": "rule-intake",
        "project_root": str(project_root),
    })
    manifest["last_install_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save_manifest(manifest)
    ok(f"Manifest updated → {MANIFEST_PATH}")

    print()
    print("✨ Done. Edit any rule file (e.g. MEMORY.md, .claude/rules/*.md) "
          "to see the SOP injected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
