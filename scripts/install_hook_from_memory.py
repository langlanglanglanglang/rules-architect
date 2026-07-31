#!/usr/bin/env python3
"""
rules-architect skill: install_hook_from_memory.py

Programmatically install a customized hook generated from a memory entry.
Designed to be called by the MAIN AGENT during the /rules-architect 5-step
flow (the main agent provides the reminder text it crafted from the memory
body — Python scripts can't do that semantic step on their own).

Workflow:
  1. Render hook from generated-hook-skeleton.py.tmpl with --name / --event /
     --matcher / --reminder / --description / --feedback-source substitutions
  2. Write to ~/.claude/hooks/<name>.py (atomic + chmod +x)
  3. Deep-merge entry into ~/.claude/settings.json
  4. Append to ~/.claude/.rules-architect-manifest.json
  5. Smoke-test the new hook

Usage (typically invoked by the main agent, NOT user CLI):
  install_hook_from_memory.py \\
      --name no_mid_task_pause \\
      --event UserPromptSubmit \\
      --matcher '*' \\
      --reminder-file /path/to/private-temp/reminder.txt \\
      --description "Force assistant to output text after thinking" \\
      --feedback-source feedback_no_mid_task_pause
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


SKILL_VERSION = "2.1.0-dev"
SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_DIR / "templates" / "hooks" / "generated-hook-skeleton.py.tmpl"
HOOKS_DEST = Path.home() / ".claude" / "hooks"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
MANIFEST_PATH = Path((os.environ.get("RULES_ARCHITECT_MANIFEST") or "").strip()
                     or (Path.home() / ".claude" / ".rules-architect-manifest.json"))


def info(msg): print(f"  ℹ {msg}")
def ok(msg):   print(f"  ✅ {msg}")
def warn(msg): print(f"  ⚠️  {msg}")
def err(msg):  print(f"  ❌ {msg}", file=sys.stderr)


def text_sha256(t): return hashlib.sha256(t.encode("utf-8")).hexdigest()


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _quarantine_corrupt_manifest():
    ts = time.strftime("%Y%m%d-%H%M%S")
    bad = MANIFEST_PATH.with_suffix(f".json.corrupt.{ts}")
    try:
        MANIFEST_PATH.rename(bad)
        warn(f"Manifest 无法读取，已隔离为 {bad.name}；将重新创建。"
             "旧安装条目不会自动恢复，请从隔离文件中找回。")
    except Exception:
        warn("Manifest 无法读取且无法隔离，将重新创建")


def load_manifest():
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text())
        except Exception:
            _quarantine_corrupt_manifest()
    return {"skill_name": "rules-architect", "skill_version": SKILL_VERSION,
            "installed_files": [], "settings_hooks_added": [], "last_install_at": None}


def save_manifest(m):
    atomic_write(MANIFEST_PATH, json.dumps(m, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True,
                    help="Hook 文件名主体（小写字母和下划线）")
    ap.add_argument("--event", required=True,
                    choices=["PreToolUse", "PostToolUse", "UserPromptSubmit", "SessionStart"])
    ap.add_argument("--matcher", required=True,
                    help="Hook 匹配器（例如 'Bash'、'mcp__Github__*'、'*'）")
    ap.add_argument("--reminder-file", required=True,
                    help="包含提醒正文的文本文件路径")
    ap.add_argument("--description", default="",
                    help="单行说明")
    ap.add_argument("--feedback-source", default="",
                    help="来源记忆文件（例如 feedback_xxx）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Validate inputs
    name = args.name.strip()
    if not name.replace("_", "").isalnum():
        err(f"--name 无效：'{name}'（只能包含字母、数字和下划线）")
        return 1
    reminder = Path(args.reminder_file).read_text().rstrip("\n")
    if not reminder.strip():
        err("提醒文本为空")
        return 1

    if not TEMPLATE_PATH.exists():
        err(f"模板不存在：{TEMPLATE_PATH}")
        return 2

    print(f"\n📦 正在从记忆安装 Hook：{name}")
    print(f"   来源：{args.feedback_source or '（无）'}")
    print(f"   事件：{args.event}")
    print(f"   匹配器：{args.matcher}")
    print(f"   目标：{HOOKS_DEST / (name + '.py')}")
    print()

    # Render template.
    # REMINDER is injected as a Python string literal via json.dumps so any
    # reminder text (backslashes, triple-quotes, newlines) is safe. Fields that
    # land inside the module docstring are escaped so a stray backslash (e.g. a
    # Windows path) or `"""` can't produce invalid Python.
    def _docstring_safe(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')

    rendered = TEMPLATE_PATH.read_text()
    rendered = (rendered
        .replace("{{NAME}}", name)
        .replace("{{EVENT}}", args.event)
        .replace("{{MATCHER}}", _docstring_safe(args.matcher))
        .replace("{{REMINDER_JSON}}", json.dumps(reminder, ensure_ascii=False))
        .replace("{{DESCRIPTION}}", _docstring_safe(args.description or f"自动生成的 Hook {name}"))
        .replace("{{FEEDBACK_SOURCE}}", _docstring_safe(args.feedback_source or "（手动创建）"))
        .replace("{{SKILL_VERSION}}", SKILL_VERSION))

    dest_path = HOOKS_DEST / f"{name}.py"
    rendered_hash = text_sha256(rendered)

    if dest_path.exists():
        warn(f"{dest_path} 已存在，已拒绝覆盖"
             "（请先删除它或选择其他 --name）")
        return 3

    # Pre-flight: don't write the hook file if settings.json is present but
    # unparseable — the later merge would fail, leaving an untracked file.
    if SETTINGS_PATH.exists():
        try:
            _cfg = json.loads(SETTINGS_PATH.read_text())
        except Exception as e:
            err(f"settings.json 存在但不是有效 JSON（{e}）。"
                "请先修复，以保证安装过程的原子性。")
            return 4
        if not isinstance(_cfg, dict) or not isinstance(_cfg.get("hooks", {}), dict):
            err("settings.json 结构异常（根节点必须是对象，且 'hooks' 也必须是对象）。"
                "请先修复。")
            return 4

    if args.dry_run:
        info(f"仅预览：将写入 {dest_path}（{len(rendered)} 字节）")
        return 0

    atomic_write(dest_path, rendered)
    os.chmod(dest_path, 0o755)
    ok(f"已安装 {dest_path}")

    # Merge settings.json (back it up first — parity with the other installers,
    # which never mutate settings.json without a timestamped snapshot)
    settings_backup = None
    if SETTINGS_PATH.exists():
        ts = time.strftime("%Y%m%d-%H%M%S")
        settings_backup = SETTINGS_PATH.with_suffix(f".json.bak.{ts}")
        shutil.copy2(SETTINGS_PATH, settings_backup)
        ok(f"已备份 settings.json → {settings_backup.name}")
        settings = json.loads(SETTINGS_PATH.read_text())
    else:
        settings = {}
    settings.setdefault("hooks", {}).setdefault(args.event, [])
    settings["hooks"][args.event].append({
        "matcher": args.matcher,
        "hooks": [{"type": "command",
                   "command": f"python3 ~/.claude/hooks/{name}.py"}],
    })
    atomic_write(SETTINGS_PATH, json.dumps(settings, indent=2, ensure_ascii=False))
    ok(f"已注册到 settings.json：{args.event} / {args.matcher}")

    # Manifest
    m = load_manifest()
    m["installed_files"].append({
        "path": str(dest_path),
        "hash_sha256": rendered_hash,
        "owner": "rules-architect",
        "kind": "generated-from-memory",
        "feedback_source": args.feedback_source,
        "template_version": SKILL_VERSION,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })
    m.setdefault("settings_hooks_added", []).append({
        "event": args.event,
        "matcher": args.matcher,
        "command": f"python3 ~/.claude/hooks/{name}.py",
        "owner": "rules-architect",
        "kind": "generated-from-memory",
    })
    if settings_backup is not None:
        m["settings_backup_path"] = str(settings_backup)
    save_manifest(m)
    ok("Manifest 已更新")

    # Smoke test (uses unique session id to avoid colliding with user dedupe locks)
    smoke_session_id = f"install-smoke-{int(time.time())}"
    try:
        out = subprocess.run(
            ["python3", str(dest_path)],
            input=f'{{"session_id":"{smoke_session_id}","tool_input":{{}},"prompt":"test"}}',
            capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            ok("冒烟测试通过")
        else:
            warn(f"冒烟测试退出码={out.returncode}：{out.stderr[:200]}")
    except Exception as e:
        warn(f"已跳过冒烟测试：{e}")
    # Clean up the dedupe lock we just created so the hook fires fresh on
    # the user's first real session.
    for cache_root in [
        Path(os.environ.get("XDG_CACHE_HOME", "")) / "claude-hooks" if os.environ.get("XDG_CACHE_HOME") else None,
        Path.home() / ".cache" / "claude-hooks",
    ]:
        if cache_root is None:
            continue
        lock = cache_root / f"{name}-{smoke_session_id}.lock"
        if lock.exists():
            try: lock.unlink()
            except Exception: pass

    print()
    print(f"✨ Hook '{name}' 已安装并注册。")
    print("   请运行 /reload-plugins 或启动新的 Claude Code 会话使其生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
