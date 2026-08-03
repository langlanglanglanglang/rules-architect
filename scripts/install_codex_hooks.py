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


SKILL_VERSION = "2.4.0"
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
        warn("已跳过 Codex 版本检查（--skip-version-check）")
        return True
    try:
        out = subprocess.run(
            ["codex", "--version"],
            capture_output=True, text=True, timeout=5
        )
        if out.returncode != 0:
            err(f"`codex --version` 执行失败：{out.stderr}")
            return False
        version_str = out.stdout.strip()
        current = parse_version(version_str)
        required = parse_version(MIN_CODEX_VERSION)
        if current < required:
            err(
                f"Codex 版本 {version_str} 低于最低要求 {MIN_CODEX_VERSION}"
                "（Hook 引擎从 v0.124.0 起稳定）"
            )
            return False
        ok(f"Codex 版本 {version_str}，满足最低要求 {MIN_CODEX_VERSION}")
        return True
    except FileNotFoundError:
        err("PATH 中找不到 `codex`，请先安装 Codex CLI。")
        return False
    except Exception as e:
        err(f"Codex 版本检查失败：{e}")
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
                warn("Manifest 无法读取；预览模式将使用空 Manifest，不改文件")
            else:
                ts = time.strftime("%Y%m%d-%H%M%S")
                bad = MANIFEST_PATH.with_suffix(f".json.corrupt.{ts}")
                try:
                    MANIFEST_PATH.rename(bad)
                    warn(f"Manifest 无法读取，已隔离为 {bad.name}；将使用新 Manifest。"
                         "旧安装记录不会自动恢复，请从隔离文件找回。")
                except Exception:
                    warn("Manifest 无法读取且隔离失败；将使用新 Manifest")
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
        info("hooks.json 尚不存在，将创建新文件")
        return None
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = HOOKS_JSON.with_suffix(f".json.bak.{ts}")
    if dry_run:
        info(f"预览：将备份 {HOOKS_JSON} → {bak}")
        return str(bak)
    shutil.copy2(HOOKS_JSON, bak)
    ok(f"已备份 {HOOKS_JSON.name} → {bak.name}")
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
        err(f"模板不存在：{template_path}")
        return "abort"
    raw = template_path.read_text()
    rendered = substitute(raw, vars_)
    rendered_hash = text_sha256(rendered)
    dest_path = HOOKS_DEST / template_name

    if dest_path.exists():
        existing_hash = file_sha256(dest_path)
        if existing_hash == rendered_hash:
            info(f"{template_name}：已安装且内容一致，跳过")
            # Adopt into manifest if untracked (e.g. manifest was lost/reset),
            # so uninstall can still remove it precisely later.
            tracked = manifest.setdefault("codex_installed_files", [])
            if not any(f.get("path") == str(dest_path) for f in tracked):
                tracked.append({
                    "path": str(dest_path),
                    "hash_sha256": rendered_hash,
                    "owner": "rules-architect",
                    "rule_id": "R-" + Path(template_name).stem.replace("_", "-"),
                    "template_version": SKILL_VERSION,
                    "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                })
                info(f"{template_name}：已补录到 Manifest（此前未跟踪）")
            return "ok"
        if not force:
            if interactive:
                print(f"\n  Hook {template_name} 已存在，但内容不同。")
                print("    [s] 跳过  [r] 替换  [b] 备份后替换  [a] 中止")
                choice = input("  请选择：").strip().lower()
                if choice == "s":
                    info(f"{template_name}：用户选择跳过，不会注册")
                    return "skip"
                if choice == "b":
                    bak = dest_path.with_suffix(f".py.bak.{int(time.time())}")
                    if not dry_run:
                        shutil.copy2(dest_path, bak)
                    info(f"{template_name}：已备份 → {bak.name}")
                elif choice == "a":
                    err("用户已中止")
                    return "abort"
                elif choice != "r":
                    info(f"{template_name}：无法识别选项，已跳过且不会注册")
                    return "skip"
            else:
                warn(f"{template_name}：与模板不同，已跳过。"
                     "可用 --force 覆盖；本次不会注册。")
                return "skip"

    if dry_run:
        info(f"预览：将写入 {dest_path}（{len(rendered)} 字节）")
        return "ok"

    atomic_write(dest_path, rendered)
    try:
        os.chmod(dest_path, 0o755)
    except Exception:
        pass
    ok(f"已安装 {template_name} → {dest_path}")

    manifest["codex_installed_files"] = [
        f for f in manifest.get("codex_installed_files", [])
        if f.get("path") != str(dest_path)
    ]
    manifest["codex_installed_files"].append({
        "path": str(dest_path),
        "hash_sha256": rendered_hash,
        "owner": "rules-architect",
        "rule_id": "R-" + Path(template_name).stem.replace("_", "-"),
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
        info(f"hooks.json：{event} 已补录到 Manifest")


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
            err(f"hooks.json 无法读取：{e}")
            return (False, 0, 0)
        if not isinstance(config, dict):
            err("hooks.json 根节点不是 JSON 对象")
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
            warn(f"hooks.json：未注册 {template_name}，因为文件内容不是本项目版本")
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
                info(f"hooks.json：{event} 已有本项目命令，跳过")
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
                info(f"hooks.json：{event}/{matcher} 已有本项目命令，跳过")
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
                info(f"hooks.json：{event}/{matcher} 已强制追加")
            elif interactive:
                print(f"\n  冲突：{event}/{matcher} 已有命令：")
                for c in commands_in_entry:
                    print(f"    {c}")
                print(f"  准备添加：{command}")
                choice = input(
                    "  [a] 追加  [s] 跳过，其他输入中止：").strip().lower()
                if choice == "a":
                    existing_entry["hooks"].append(
                        {"type": "command", "command": command}
                    )
                    added_this_run.append({
                        "event": event, "matcher": matcher,
                        "command": command, "owner": "rules-architect",
                    })
                else:
                    info(f"hooks.json：{event}/{matcher} 已跳过")
                    skipped_conflicts.append((event, matcher))
                    continue
            else:
                warn(f"hooks.json：{event}/{matcher} 存在冲突，已跳过。"
                     "请使用 --force 或交互模式重试。")
                skipped_conflicts.append((event, matcher))
                continue

    def _note_skips():
        for event, matcher in skipped_conflicts:
            warn(f"未注册：{event}"
                 + (f"/{matcher}" if matcher else "")
                 + " 已有其他命令，可用 --force 追加")

    if not added_this_run:
        if skipped_conflicts:
            _note_skips()
            info(f"hooks.json：新增 0 项，因冲突跳过 {len(skipped_conflicts)} 项")
        else:
            info("hooks.json：无需修改")
        return (True, 0, len(skipped_conflicts))

    if dry_run:
        info(f"预览：将写入 {HOOKS_JSON}")
        info(f"预览：将新增 {len(added_this_run)} 个 Hook 注册项")
        for a in added_this_run:
            info(f"   + {a['event']}"
                 + (f"/{a['matcher']}" if a['matcher'] else "")
                 + f" → {a['command']}")
        _note_skips()
        return (True, len(added_this_run), len(skipped_conflicts))

    atomic_write(HOOKS_JSON, json.dumps(config, indent=2, ensure_ascii=False))
    ok(f"hooks.json：已新增 {len(added_this_run)} 个注册项")
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
            ok(f"冒烟测试 {name}：通过")
        else:
            err(f"冒烟测试 {name}：失败")
            all_pass = False
    return all_pass


def print_summary(backup_path: Optional[str], added: int, skipped: int) -> None:
    print()
    print("✅ 内容保护摘要（Codex）：")
    print()
    print("   ✋ Codex 私有记忆              — 未修改")
    print("   ✋ AGENTS.md                   — 未修改")
    print("   ✋ hooks.json 其他配置         — deep-merge 完整保留")
    print("   ✋ 已有 Hook 脚本              — 哈希不一致时跳过")
    print()
    print("   ⭐ 本次变更（全部记录在 Manifest 的 codex_* 字段）：")
    print(f"      + {HOOKS_DEST}/ 中最多 3 个 Hook 脚本")
    print(f"      + {HOOKS_JSON} 中 {added} 个 Hook 注册项")
    if skipped:
        print(f"      ! 因冲突跳过 {skipped} 个注册项，可用 --force 追加")
    print("        (memory_intake_check / rule_intake_reminder / cleanup_hook)")
    if backup_path:
        print(f"      → hooks.json 备份：{backup_path}")
    print()
    print("   卸载时按 Manifest 和哈希精确回滚：")
    print(f"      python3 {SKILL_DIR}/scripts/uninstall.py")
    print()


def print_trust_notice() -> None:
    print("🔐 Codex 信任步骤（必须完成；信任前 Hook 不会运行）：")
    print("   非托管命令 Hook 必须按哈希审核并信任。启用方法：")
    print("     1. 启动 Codex，在 TUI 中运行 /hooks")
    print("     2. 审核并启用 3 个 rules-architect Hook")
    print("   也可以在第一次匹配触发时确认。")
    print("   修改 Hook 后，Codex 会要求按新哈希重新审核。")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="为 Codex CLI 安装 rules-architect Hook")
    ap.add_argument("--dry-run", action="store_true",
                    help="仅显示计划，不修改文件")
    ap.add_argument("--non-interactive", action="store_true",
                    help="不询问；冲突时采用安全默认值（跳过）")
    ap.add_argument("--force", action="store_true",
                    help="覆盖已有文件并追加 Hook 注册项")
    ap.add_argument("--rule-intake-keywords",
                    choices=["chinese", "english"], default="chinese",
                    help="rule_intake_reminder.py 的关键词预设")
    ap.add_argument("--skip-version-check", action="store_true",
                    help="跳过 Codex 版本检查（不推荐）")
    args = ap.parse_args()

    print(f"\n📦 rules-architect Codex 安装器 v{SKILL_VERSION}")
    print(f"   模式：{'仅预览' if args.dry_run else '安装'}")
    print(f"   交互：{'是' if not args.non_interactive else '否'}")
    print(f"   强制：{'是' if args.force else '否'}")
    print(f"   模板目录：{TEMPLATES_DIR}")
    print(f"   Codex 目录：{CODEX_HOME}")
    print(f"   Hook 目录：{HOOKS_DEST}")
    print(f"   配置文件：{HOOKS_JSON}")
    print(f"   Manifest：{MANIFEST_PATH}")
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
            err(f"hooks.json 不是有效 JSON（{e}）。"
                "请先修复，以保证安装原子性和精确回滚。")
            return 2
        if not isinstance(_cfg, dict) or not isinstance(_cfg.get("hooks", {}), dict):
            err("hooks.json 结构不符合预期：根节点和 hooks 必须是对象。"
                "请先修复，避免写入文件后合并失败。")
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

    print("\n--- 安装 Hook 文件 ---")
    registerable = set()
    for template_name, _ in CODEX_HOOK_TEMPLATES:
        status = install_hook_file(
            template_name, template_vars, manifest,
            args.dry_run, args.force,
            interactive=not args.non_interactive
        )
        if status == "abort":
            err("Hook 安装失败。")
            return 3
        if status == "ok":
            registerable.add(template_name)

    print("\n--- 合并 hooks.json ---")
    merge_ok, n_added, n_skipped = merge_hooks_json(
        manifest, args.dry_run, args.force,
        interactive=not args.non_interactive,
        registerable=registerable)
    if not merge_ok:
        err("hooks.json 合并失败。")
        return 4

    if not args.dry_run:
        manifest["last_install_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        manifest["skill_version"] = SKILL_VERSION
        manifest["min_codex_version"] = MIN_CODEX_VERSION
        save_manifest(manifest)
        ok(f"Manifest 已保存 → {MANIFEST_PATH}")

    if not args.dry_run:
        print("\n--- 对已安装 Hook 执行冒烟测试 ---")
        smoke_test_all()

    print_summary(backup_path, n_added, n_skipped)
    print_trust_notice()
    print("✨ Codex 安装完成。")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
