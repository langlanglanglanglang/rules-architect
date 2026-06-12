#!/usr/bin/env python3
"""
rules-architect skill: mark_memory_promoted.py

Mark a memory feedback entry as promoted to another layer. Replaces the body
with a stub preserving the YAML frontmatter. Original body remains in git
history for retrieval if needed.

Usage:
  mark_memory_promoted.py --feedback feedback_no_mid_task_pause \\
      --target "L0 hook ~/.claude/hooks/no_mid_task_pause.py"

  mark_memory_promoted.py --feedback feedback_no_mid_task_pause \\
      --target "L3 CLAUDE-personal.md §一.7"
      --dry-run
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path


def info(msg): print(f"  ℹ {msg}")
def ok(msg):   print(f"  ✅ {msg}")
def warn(msg): print(f"  ⚠️  {msg}")
def err(msg):  print(f"  ❌ {msg}", file=sys.stderr)


def atomic_write(path, content):
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except: pass
        raise


def find_memory_dirs():
    root = Path.home() / ".claude" / "projects"
    if not root.exists():
        return []
    out = []
    for d in root.iterdir():
        m = d / "memory"
        if m.is_dir():
            out.append((m.stat().st_mtime, m))
    out.sort(reverse=True)
    return [m for _, m in out]


def find_memory_file(feedback_name, memory_dir_override=None):
    """Try to find the feedback file across all memory dirs."""
    if memory_dir_override:
        dirs = [Path(memory_dir_override)]
    else:
        dirs = find_memory_dirs()
    candidates = []
    for d in dirs:
        for ext in [".md", ""]:
            p = d / f"{feedback_name}{ext}"
            if p.exists():
                candidates.append(p)
    return candidates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feedback", required=True,
                    help="Memory feedback name (e.g. feedback_no_mid_task_pause)")
    ap.add_argument("--target", required=True,
                    help="Where it was promoted to (free-text description)")
    ap.add_argument("--memory-dir",
                    help="Override memory directory")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    candidates = find_memory_file(args.feedback, args.memory_dir)
    if not candidates:
        err(f"Memory file not found: {args.feedback}")
        info("Searched in:")
        for d in find_memory_dirs():
            info(f"  {d}")
        return 1
    if len(candidates) > 1:
        warn(f"Multiple matches found, using first: {candidates[0]}")
    path = candidates[0]

    text = path.read_text()
    today = time.strftime("%Y-%m-%d")

    # Extract frontmatter
    m = re.match(r"^(---\n.+?\n---\n)(.*)", text, re.DOTALL)
    if not m:
        warn(f"{path}: no YAML frontmatter found, will treat whole file as body")
        frontmatter = ""
        body = text
    else:
        frontmatter = m.group(1)
        body = m.group(2)

    # Check if already a stub
    if "Promoted to:" in body[:200]:
        warn(f"{path}: already marked as Promoted (skip)")
        return 0

    new_body = f"\nPromoted to: {args.target} @ {today}\n\n(Original body preserved in git history.)\n"
    new_text = frontmatter + new_body

    print(f"\n📦 Marking memory as promoted:")
    print(f"   File:   {path}")
    print(f"   Target: {args.target}")
    print(f"   Date:   {today}")
    print()

    if args.dry_run:
        info("DRY-RUN: would replace body with:")
        for line in new_body.strip().split("\n"):
            info(f"   | {line}")
        return 0

    atomic_write(path, new_text)
    ok(f"Body replaced with Promoted-to stub")
    info(f"   Original body remains in git history: cd {path.parent} && git log {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
