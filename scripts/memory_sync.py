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
  memory_sync.py push --feedback feedback_xxx --memory-dir <path> --dry-run
  memory_sync.py push --feedback feedback_xxx --memory-dir <path> --reason "team should know this"
  memory_sync.py push --feedback feedback_xxx --memory-dir <path> --lessons ./docs/ai/lessons.md
  memory_sync.py push --feedback feedback_xxx --memory-dir <path> --update
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


def find_memory_file(feedback_name, memory_dir_override):
    dirs = [Path(memory_dir_override).expanduser().resolve()]
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
             f"_从 L1 个人记忆同步于 {today}_"]
    if reason:
        lines.append(f"_同步原因：{reason}_")
    lines += ["", body.strip(), "", end]
    return "\n".join(lines) + "\n"


def block_pattern(feedback_name: str):
    begin = re.escape(f"<!-- ra-memory:{feedback_name} BEGIN -->")
    end = re.escape(f"<!-- ra-memory:{feedback_name} END -->")
    return re.compile(begin + r".*?" + end + r"\n?", re.DOTALL)


def cmd_push(args) -> int:
    lessons = resolve_lessons(args.lessons)
    if lessons is None:
        err("未指定团队经验文件：请传入 --lessons <路径> 或设置 $LESSONS_PATH")
        return 2

    mem = find_memory_file(args.feedback, args.memory_dir)
    if mem is None:
        err(f"未找到记忆文件：{args.feedback}")
        info(f"  已搜索：{Path(args.memory_dir).expanduser()}")
        return 1

    _, body = split_frontmatter(mem.read_text())
    if not body.strip():
        err(f"{mem}：正文为空，没有可同步的内容")
        return 1

    block = build_block(args.feedback, body, args.reason)
    existing = lessons.read_text() if lessons.exists() else ""
    already = block_pattern(args.feedback).search(existing)

    print(f"\n📤 memory_sync 同步")
    print(f"   来源：{mem}")
    print(f"   目标：{lessons}")
    print(f"   条目：{args.feedback}")
    print(f"   已存在：{'是' if already else '否'}")
    print()

    if already and not args.update:
        ok(f"{args.feedback} 已存在于团队经验中，已跳过（使用 --update 刷新）")
        return 0

    if already:
        new_text = block_pattern(args.feedback).sub(block, existing, count=1)
        action = "更新"
    else:
        sep = "" if existing.endswith("\n") or not existing else "\n"
        new_text = existing + sep + ("\n" if existing else "") + block
        action = "追加"

    if args.dry_run:
        info(f"仅预览：将在 {lessons} 中{action} {args.feedback} 区块")
        for ln in block.splitlines():
            info(f"   | {ln}")
        return 0

    atomic_write(lessons, new_text)
    ok(f"已{action} {args.feedback} → {lessons}")
    info("   仅单向同步：不会把 lessons.md 反向写回个人记忆。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="将 L1 个人记忆同步到团队 lessons.md")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("push", help="将一条个人记忆同步到 lessons.md")
    p.add_argument("--feedback", required=True,
                   help="记忆条目名称（例如 feedback_no_mid_task_pause）")
    p.add_argument("--reason", default="",
                   help="值得向团队共享的原因")
    p.add_argument("--lessons", default="",
                   help="目标 lessons.md（未传入时读取 $LESSONS_PATH）")
    p.add_argument("--memory-dir", required=True,
                   help="已确认的精确记忆目录（必填）")
    p.add_argument("--update", action="store_true",
                   help="条目已存在时刷新对应区块")
    p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.command == "push":
        # normalize empty strings to None for override args
        args.lessons = args.lessons or None
        return cmd_push(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
