#!/usr/bin/env python3
"""
rules-architect skill: memory_sync.py

One-way push of an L1 memory entry → team lessons.md, so a rule that lives in
your private memory becomes visible to the whole team (and to any tool that can
read markdown: codex, gemini, CI, RAG, ...).

Single direction by design: this NEVER reads lessons.md back into memory, and
NEVER modifies/deletes anything in lessons.md outside the managed block it owns
for a given entry. Each pushed entry is wrapped in:

    <!-- ra-memory:<feedback_name> BEGIN -->
    ...
    <!-- ra-memory:<feedback_name> END -->

Re-running push for the same entry is idempotent (skips) unless --update, which
refreshes only that entry's block.

Target lessons file resolution order:
  1. --lessons <path>
  2. $LESSONS_PATH
  (errors if neither is set)

Usage:
  memory_sync.py push --feedback feedback_xxx --dry-run
  memory_sync.py push --feedback feedback_xxx --reason "team should know this"
  memory_sync.py push --feedback feedback_xxx --lessons ./docs/ai/lessons.md
  memory_sync.py push --feedback feedback_xxx --update   # refresh existing block
"""
import argparse
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


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
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
    dirs = [Path(memory_dir_override)] if memory_dir_override else find_memory_dirs()
    for d in dirs:
        for ext in (".md", ""):
            p = d / f"{feedback_name}{ext}"
            if p.exists():
                return p
    return None


def split_frontmatter(text: str):
    m = re.match(r"^(---\n.+?\n---\n)(.*)", text, re.DOTALL)
    if not m:
        return "", text
    return m.group(1), m.group(2)


def resolve_lessons(arg_lessons) -> Path:
    target = arg_lessons or os.environ.get("LESSONS_PATH")
    if not target:
        return None
    return Path(target).expanduser()


def build_block(feedback_name: str, body: str, reason: str) -> str:
    begin = f"<!-- ra-memory:{feedback_name} BEGIN -->"
    end = f"<!-- ra-memory:{feedback_name} END -->"
    today = time.strftime("%Y-%m-%d")
    lines = [begin, f"### {feedback_name}",
             f"_Synced from L1 memory @ {today}_"]
    if reason:
        lines.append(f"_Reason: {reason}_")
    lines += ["", body.strip(), "", end]
    return "\n".join(lines) + "\n"


def block_pattern(feedback_name: str):
    begin = re.escape(f"<!-- ra-memory:{feedback_name} BEGIN -->")
    end = re.escape(f"<!-- ra-memory:{feedback_name} END -->")
    return re.compile(begin + r".*?" + end + r"\n?", re.DOTALL)


def cmd_push(args) -> int:
    lessons = resolve_lessons(args.lessons)
    if lessons is None:
        err("No lessons file: pass --lessons <path> or set $LESSONS_PATH")
        return 2

    mem = find_memory_file(args.feedback, args.memory_dir)
    if mem is None:
        err(f"Memory file not found: {args.feedback}")
        for d in find_memory_dirs():
            info(f"  searched: {d}")
        return 1

    _, body = split_frontmatter(mem.read_text())
    if not body.strip():
        err(f"{mem}: empty body, nothing to push")
        return 1

    block = build_block(args.feedback, body, args.reason)
    existing = lessons.read_text() if lessons.exists() else ""
    already = block_pattern(args.feedback).search(existing)

    print(f"\n📤 memory_sync push")
    print(f"   From:    {mem}")
    print(f"   To:      {lessons}")
    print(f"   Entry:   {args.feedback}")
    print(f"   Present: {'yes' if already else 'no'}")
    print()

    if already and not args.update:
        ok(f"{args.feedback} already in lessons — skip (use --update to refresh)")
        return 0

    if already:
        new_text = block_pattern(args.feedback).sub(block, existing, count=1)
        action = "updated"
    else:
        sep = "" if existing.endswith("\n") or not existing else "\n"
        new_text = existing + sep + ("\n" if existing else "") + block
        action = "appended"

    if args.dry_run:
        info(f"DRY-RUN: would {action} block for {args.feedback} in {lessons}")
        for ln in block.splitlines():
            info(f"   | {ln}")
        return 0

    atomic_write(lessons, new_text)
    ok(f"{action} {args.feedback} → {lessons}")
    info("   One-way push only: lessons.md is never read back into memory.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Push L1 memory entries to team lessons.md")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("push", help="Push one memory entry to lessons.md")
    p.add_argument("--feedback", required=True,
                   help="Memory entry name (e.g. feedback_no_mid_task_pause)")
    p.add_argument("--reason", default="",
                   help="Why this is worth sharing team-wide")
    p.add_argument("--lessons", default="",
                   help="Target lessons.md (else $LESSONS_PATH)")
    p.add_argument("--memory-dir", default="",
                   help="Override memory directory to search")
    p.add_argument("--update", action="store_true",
                   help="Refresh the entry's block if already present")
    p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.command == "push":
        # normalize empty strings to None for override args
        args.lessons = args.lessons or None
        args.memory_dir = args.memory_dir or None
        return cmd_push(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
