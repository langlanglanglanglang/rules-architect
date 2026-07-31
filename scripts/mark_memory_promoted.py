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
import shutil
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
                    help="记忆反馈名称（例如 feedback_no_mid_task_pause）")
    ap.add_argument("--target", required=True,
                    help="已提升到的位置（自由文本说明）")
    ap.add_argument("--memory-dir",
                    help="指定记忆目录")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    candidates = find_memory_file(args.feedback, args.memory_dir)
    if not candidates:
        err(f"未找到记忆文件：{args.feedback}")
        info("已搜索：")
        for d in find_memory_dirs():
            info(f"  {d}")
        return 1
    if len(candidates) > 1:
        warn(f"找到多个匹配项，将使用第一个：{candidates[0]}")
    path = candidates[0]

    text = path.read_text()
    today = time.strftime("%Y-%m-%d")

    # Extract frontmatter
    m = re.match(r"^(---\n.+?\n---\n)(.*)", text, re.DOTALL)
    if not m:
        warn(f"{path}：未找到 YAML frontmatter，将把整个文件视为正文")
        frontmatter = ""
        body = text
    else:
        frontmatter = m.group(1)
        body = m.group(2)

    # Match only the generated-stub shape. Ordinary prose may legitimately
    # mention the phrase "Promoted to:".
    if re.match(r"^\s*Promoted to:\s+\S", body):
        warn(f"{path}：已标记为提升，跳过")
        return 0

    new_body = f"\nPromoted to: {args.target} @ {today}\n\n（原始正文已保存在备份和 Git 历史中。）\n"
    new_text = frontmatter + new_body

    print(f"\n📦 正在把记忆标记为已提升：")
    print(f"   文件：{path}")
    print(f"   目标：{args.target}")
    print(f"   日期：{today}")
    print()

    if args.dry_run:
        info("仅预览：将把正文替换为：")
        for line in new_body.strip().split("\n"):
            info(f"   | {line}")
        return 0

    # Back up the original memory file before rewriting. git history only helps
    # if the memory dir is a git repo — this snapshot always works.
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak.{ts}")
    try:
        shutil.copy2(path, backup)
        ok(f"已备份原文件 → {backup.name}")
    except Exception as e:
        warn(f"无法备份 {path.name}（{e}）；为避免数据丢失，操作已中止")
        return 1

    atomic_write(path, new_text)
    ok("正文已替换为提升位置占位说明")
    info(f"   原文备份位置：{backup}")
    info("   如果记忆目录是 Git 仓库，也可从 Git 历史找回")
    return 0


if __name__ == "__main__":
    sys.exit(main())
