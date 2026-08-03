#!/usr/bin/env python3
"""
rules-architect skill: install_hooks.py

Install 3 core hooks (memory_intake / rule_intake / cleanup) into
~/.claude/hooks/ and deep-merge entries into ~/.claude/settings.json.
Individual workflow-preference hooks (error_recovery, dangerous_branch, ...)
live in examples/ for opt-in. Tracks every artifact in a manifest for
precise uninstall.

V2 BLOCKER fixes applied:
  - CC version check (fail < min)
  - settings.json backup before any write
  - JSON deep-merge with same-matcher conflict detection
  - Manifest with sha256 hash per file
  - Atomic write: tmp file → fsync → rename
  - On failure: roll back per manifest (NOT bulk backup restore)
  - Templates are parameterized + self-contained (no external section refs)

Usage:
  install_hooks.py                                # interactive, default mode B
  install_hooks.py --dry-run                      # print plan, modify nothing
  install_hooks.py --non-interactive              # CI mode: skip on conflict
  install_hooks.py --rule-intake-keywords english # use English preset
  install_hooks.py --protected-branches "main|develop|test"
  install_hooks.py --force                        # overwrite existing
  install_hooks.py --skip-version-check           # bypass CC version check
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional


SKILL_VERSION = "2.4.0"
MIN_CC_VERSION = "1.5.0"   # UserPromptSubmit hook required

# Core hooks: SOP injection + base infrastructure.
# Individual workflow preferences (error_recovery, dangerous_branch, etc) live
# in examples/ — copy + adapt for your own setup, then register manually or
# via your own install script.
HOOK_TEMPLATES = [
    ("memory_intake_check.py", {
        "event": "PreToolUse",
        "matcher": "Write|Edit|MultiEdit",
    }),
    ("rule_intake_reminder.py", {
        "event": "UserPromptSubmit",
        "matcher": "*",
    }),
    ("cleanup_hook.py", {
        "event": "SessionStart",
        "matcher": "*",
    }),
]


# === Paths ===
SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_DIR / "templates" / "hooks"
HOOKS_DEST = Path.home() / ".claude" / "hooks"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
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


def check_cc_version(skip: bool) -> bool:
    if skip:
        warn("已跳过 Claude Code 版本检查（--skip-version-check）")
        return True
    try:
        out = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=5
        )
        if out.returncode != 0:
            err(f"`claude --version` 执行失败：{out.stderr}")
            return False
        version_str = out.stdout.strip()
        current = parse_version(version_str)
        required = parse_version(MIN_CC_VERSION)
        if current < required:
            err(
                f"Claude Code 版本 {version_str} 低于最低要求 {MIN_CC_VERSION}"
                "（需要 UserPromptSubmit Hook）"
            )
            return False
        ok(f"Claude Code 版本 {version_str}，满足最低要求 {MIN_CC_VERSION}")
        return True
    except FileNotFoundError:
        err("PATH 中找不到 `claude`，请先安装 Claude Code。")
        return False
    except Exception as e:
        err(f"Claude Code 版本检查失败：{e}")
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
        # rename is atomic on POSIX
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


# === Manifest ===
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


# === Settings.json backup ===
def backup_settings(dry_run: bool) -> Optional[str]:
    if not SETTINGS_PATH.exists():
        info("settings.json 尚不存在，将创建新文件")
        return None
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = SETTINGS_PATH.with_suffix(f".json.bak.{ts}")
    if dry_run:
        info(f"预览：将备份 {SETTINGS_PATH} → {bak}")
        return str(bak)
    shutil.copy2(SETTINGS_PATH, bak)
    ok(f"已备份 {SETTINGS_PATH.name} → {bak.name}")
    return str(bak)


# === Hook installation ===
def install_hook_file(
    template_name: str,
    vars_: dict,
    manifest: dict,
    dry_run: bool,
    force: bool,
    interactive: bool,
) -> str:
    # Returns "ok" (our file is in place → register it), "skip" (a foreign
    # same-named file was left untouched → must NOT register it), or "abort".
    template_path = TEMPLATES_DIR / (template_name + ".tmpl")
    if not template_path.exists():
        err(f"模板不存在：{template_path}")
        return "abort"
    raw = template_path.read_text()
    rendered = substitute(raw, vars_)
    rendered_hash = text_sha256(rendered)
    dest_path = HOOKS_DEST / template_name

    # Conflict detection
    if dest_path.exists():
        existing_hash = file_sha256(dest_path)
        if existing_hash == rendered_hash:
            info(f"{template_name}：已安装且内容一致，跳过")
            # Adopt into manifest if untracked (e.g. manifest was lost/reset),
            # so uninstall can still remove it precisely later.
            tracked = manifest.setdefault("installed_files", [])
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
                # non-interactive: skip on conflict (safe default)
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
    ok(f"已安装 {template_name}")

    # Record in manifest
    manifest["installed_files"] = [
        f for f in manifest["installed_files"]
        if f.get("path") != str(dest_path)
    ]
    manifest["installed_files"].append({
        "path": str(dest_path),
        "hash_sha256": rendered_hash,
        "owner": "rules-architect",
        "rule_id": "R-" + Path(template_name).stem.replace("_", "-"),
        "template_version": SKILL_VERSION,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })
    return "ok"


# === Settings.json deep-merge ===
def merge_settings(
    manifest: dict,
    dry_run: bool,
    force: bool,
    interactive: bool,
    registerable: set,
) -> bool:
    if SETTINGS_PATH.exists():
        try:
            settings = json.loads(SETTINGS_PATH.read_text())
        except Exception as e:
            err(f"settings.json 无法读取：{e}")
            return False
    else:
        settings = {}

    settings.setdefault("hooks", {})
    hooks_section = settings["hooks"]

    settings_added_this_run = []

    for template_name, hook_def in HOOK_TEMPLATES:
        # Never register a template whose file we did NOT install (a foreign
        # same-named file was skipped) — else settings.json would activate that
        # script as ours while it stays untracked in the manifest.
        if template_name not in registerable:
            warn(f"settings.json：未注册 {template_name}，因为文件内容不是本项目版本")
            continue
        event = hook_def["event"]
        matcher = hook_def["matcher"]
        command = f"python3 ~/.claude/hooks/{template_name}"

        hooks_section.setdefault(event, [])

        # Find existing config with same matcher
        existing_entry = None
        for entry in hooks_section[event]:
            if entry.get("matcher") == matcher:
                existing_entry = entry
                break

        if existing_entry is None:
            new_entry = {
                "matcher": matcher,
                "hooks": [{"type": "command", "command": command}],
            }
            hooks_section[event].append(new_entry)
            settings_added_this_run.append({
                "event": event,
                "matcher": matcher,
                "command": command,
                "owner": "rules-architect",
            })
        else:
            # Same matcher exists — check if same command already there
            commands_in_entry = [
                h.get("command", "") for h in existing_entry.get("hooks", [])
            ]
            if command in commands_in_entry:
                info(f"settings.json：{event}/{matcher} 已有本项目命令，跳过")
                # Adopt: if the registration is present but untracked (manifest
                # was lost/reset), record it so uninstall won't leave it dangling.
                tracked = manifest.setdefault("settings_hooks_added", [])
                if not any(e.get("event") == event and e.get("matcher") == matcher
                           and e.get("command") == command for e in tracked):
                    tracked.append({"event": event, "matcher": matcher,
                                    "command": command, "owner": "rules-architect"})
                    info(f"settings.json：{event}/{matcher} 已补录到 Manifest")
                continue
            # Different command at same matcher — conflict
            if force:
                existing_entry.setdefault("hooks", []).append(
                    {"type": "command", "command": command}
                )
                settings_added_this_run.append({
                    "event": event, "matcher": matcher,
                    "command": command, "owner": "rules-architect",
                })
                info(f"settings.json：{event}/{matcher} 已强制追加")
            elif interactive:
                print(f"\n  冲突：{event}/{matcher} 已有命令：")
                for c in commands_in_entry:
                    print(f"    {c}")
                print(f"  准备添加：{command}")
                choice = input(
                    "  [a] 追加  [s] 跳过  [r] 全部替换，其他输入中止：").strip().lower()
                if choice == "a":
                    existing_entry["hooks"].append(
                        {"type": "command", "command": command}
                    )
                    settings_added_this_run.append({
                        "event": event, "matcher": matcher,
                        "command": command, "owner": "rules-architect",
                    })
                elif choice == "r":
                    existing_entry["hooks"] = [
                        {"type": "command", "command": command}
                    ]
                    settings_added_this_run.append({
                        "event": event, "matcher": matcher,
                        "command": command, "owner": "rules-architect",
                    })
                else:
                    info(f"settings.json：{event}/{matcher} 已跳过")
                    continue
            else:
                warn(f"settings.json：{event}/{matcher} 存在冲突，已跳过。"
                     "请使用 --force 或交互模式重试。")
                continue

    if not settings_added_this_run:
        info("settings.json：无需修改")
        return True

    if dry_run:
        info(f"预览：将写入 {SETTINGS_PATH}")
        info(f"预览：将新增 {len(settings_added_this_run)} 个 Hook 注册项")
        return True

    new_text = json.dumps(settings, indent=2, ensure_ascii=False)
    atomic_write(SETTINGS_PATH, new_text)
    ok(f"settings.json：已新增 {len(settings_added_this_run)} 个注册项")

    # Record in manifest (don't duplicate existing entries)
    existing_settings = manifest.get("settings_hooks_added", [])
    seen = {(e["event"], e["matcher"], e["command"]) for e in existing_settings}
    for s in settings_added_this_run:
        key = (s["event"], s["matcher"], s["command"])
        if key not in seen:
            existing_settings.append(s)
            seen.add(key)
    manifest["settings_hooks_added"] = existing_settings
    return True


# === claude-md-management plugin check ===
CLAUDE_MD_PLUGIN = "claude-md-management@claude-plugins-official"


def check_plugin_cached(plugin_full: str) -> bool:
    """Check if a plugin is downloaded to ~/.claude/plugins/cache/."""
    if "@" not in plugin_full:
        return False
    plugin, marketplace = plugin_full.split("@", 1)
    cache_path = Path.home() / ".claude" / "plugins" / "cache" / marketplace / plugin
    return cache_path.exists()


def check_and_enable_claude_md_management(
    auto_enable: bool, interactive: bool, dry_run: bool
) -> None:
    """Check whether claude-md-management is enabled for L3 audit.

    Behavior:
      - Already enabled → ok message, return
      - Not downloaded → warn + give /plugin command, return
      - Downloaded but disabled → enable if --auto-enable OR interactive yes,
        else give instructions
    """
    if not SETTINGS_PATH.exists():
        warn("settings.json 尚未创建，插件检查延后")
        return

    try:
        settings = json.loads(SETTINGS_PATH.read_text())
    except Exception as e:
        warn(f"插件检查无法读取 settings.json：{e}")
        return

    enabled_plugins = settings.get("enabledPlugins", {})
    if enabled_plugins.get(CLAUDE_MD_PLUGIN, False):
        ok("claude-md-management 已启用，可进行 L3 审计")
        info("   运行 /claude-md-management:claude-md-improver 审计 CLAUDE.md")
        return

    cached = check_plugin_cached(CLAUDE_MD_PLUGIN)
    if not cached:
        warn(
            "claude-md-management 插件未安装（L3 CLAUDE.md 审计需要）"
        )
        info("   安装步骤：")
        info("     1. 在 Claude Code 运行：/plugin claude-md-management")
        info("     2. 然后运行：/reload-plugins")
        info("     3. 可重新运行 install_hooks.py 自动启用")
        return

    # Plugin downloaded but not enabled — we can flip the flag
    info("claude-md-management 已下载，但未在 settings.json 中启用")
    if not auto_enable:
        if interactive:
            print()
            choice = input(
                "  现在启用 claude-md-management 以进行 L3 审计吗？[Y/n] "
            ).strip().lower()
            if choice in {"n", "no"}:
                info("已跳过启用 claude-md-management")
                return
        else:
            info("   可用 --enable-claude-md-management 自动启用，"
                 "或手动修改 settings.json")
            return

    if dry_run:
        info(f"预览：将在 settings.json 中启用 {CLAUDE_MD_PLUGIN}")
        return

    enabled_plugins[CLAUDE_MD_PLUGIN] = True
    settings["enabledPlugins"] = enabled_plugins
    atomic_write(SETTINGS_PATH, json.dumps(settings, indent=2, ensure_ascii=False))
    ok(f"已启用 {CLAUDE_MD_PLUGIN}")
    info("   在 Claude Code 运行 /reload-plugins 激活")
    info("   再运行 /claude-md-management:claude-md-improver 进行 L3 审计")


# === Dry-run hook validation ===
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
        "memory_intake_check.py": {
            "session_id": "smoke",
            "tool_input": {"file_path": "/x/memory/feedback_y.md"},
        },
        "rule_intake_reminder.py": {
            "session_id": "smoke", "prompt": "test message",
        },
        "cleanup_hook.py": {},
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


# === Main ===

def print_content_preservation_summary(backup_path: Optional[str]) -> None:
    """Show what the install touched vs preserved — for user trust."""
    print()
    print("✅ 内容保护摘要：")
    print()
    print("   ✋ L1 个人记忆文件            — 未修改")
    print("   ✋ CLAUDE.md                  — 未修改")
    print("   ✋ 已有 Hook 脚本             — 哈希不一致时跳过，保留你的修改")
    print("   ✋ settings.json 其他配置     — deep-merge 完整保留")
    print()
    print("   ⭐ 本次变更（全部记录在 Manifest）：")
    print("      + ~/.claude/hooks/ 中的 3 个核心 Hook")
    print("      + ~/.claude/settings.json 中的 3 个 Hook 注册项")
    print("        (memory_intake_check / rule_intake_reminder / cleanup_hook)")
    print("        可选工作流 Hook 见 examples/")
    if backup_path:
        print(f"      → settings.json 备份：{backup_path}")
    print()
    print("   除上述项目外，本 Skill 未修改其他内容。")
    print("   卸载时按 Manifest 和哈希精确回滚。")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="安装 rules-architect Hook")
    ap.add_argument("--dry-run", action="store_true",
                    help="仅显示计划，不修改文件")
    ap.add_argument("--non-interactive", action="store_true",
                    help="不询问；冲突时采用安全默认值（跳过）")
    ap.add_argument("--force", action="store_true",
                    help="覆盖已有文件并追加 Hook 注册项")
    ap.add_argument("--rule-intake-keywords",
                    choices=["chinese", "english"], default="chinese",
                    help="rule_intake_reminder.py 的关键词预设")
    ap.add_argument("--protected-branches", default="develop|test|master",
                    help="用竖线分隔的受保护分支，供 "
                         "dangerous_branch_reminder.py")
    ap.add_argument("--skip-version-check", action="store_true",
                    help="跳过 Claude Code 版本检查（不推荐）")
    ap.add_argument("--enable-claude-md-management", action="store_true",
                    help="若已下载则自动启用 claude-md-management 插件"
                         "（L3 审计需要）")
    ap.add_argument("--skip-plugin-check", action="store_true",
                    help="完全跳过 claude-md-management 插件检查")
    args = ap.parse_args()

    print(f"\n📦 rules-architect 安装器 v{SKILL_VERSION}")
    print(f"   模式：{'仅预览' if args.dry_run else '安装'}")
    print(f"   交互：{'是' if not args.non_interactive else '否'}")
    print(f"   强制：{'是' if args.force else '否'}")
    print(f"   模板目录：{TEMPLATES_DIR}")
    print(f"   安装目录：{HOOKS_DEST}")
    print(f"   配置文件：{SETTINGS_PATH}")
    print(f"   Manifest：{MANIFEST_PATH}")
    print()

    # 1. CC version check
    if not check_cc_version(args.skip_version_check):
        return 2

    # 1.5 Pre-flight: refuse to write ANY hook file if the target settings.json
    # is present but unparseable — otherwise we'd leave untracked files behind
    # (merge would fail after files are already written), breaking rollback.
    if SETTINGS_PATH.exists():
        try:
            _cfg = json.loads(SETTINGS_PATH.read_text())
        except Exception as e:
            err(f"settings.json 不是有效 JSON（{e}）。"
                "请先修复，以保证安装原子性和精确回滚。")
            return 2
        if not isinstance(_cfg, dict) or not isinstance(_cfg.get("hooks", {}), dict):
            err("settings.json 结构不符合预期：根节点和 hooks 必须是对象。"
                "请先修复，避免写入文件后合并失败。")
            return 2

    # 2. Backup
    backup_path = backup_settings(args.dry_run)

    # 3. Load manifest
    manifest = load_manifest(args.dry_run)
    if backup_path:
        manifest["settings_backup_path"] = backup_path

    # 4. Template vars
    template_vars = {
        "SKILL_VERSION": SKILL_VERSION,
        "AUDIT_MAX_BYTES": "1048576",
        "RULE_INTAKE_KEYWORDS": args.rule_intake_keywords,
    }

    # 5. Install hooks
    print("\n--- 安装 Hook 文件 ---")
    all_ok = True
    registerable = set()
    for template_name, _ in HOOK_TEMPLATES:
        status = install_hook_file(
            template_name, template_vars, manifest,
            args.dry_run, args.force,
            interactive=not args.non_interactive
        )
        if status == "abort":
            all_ok = False
            break
        if status == "ok":
            registerable.add(template_name)

    if not all_ok:
        err("Hook 安装失败。备份位置：" + str(backup_path or "无"))
        return 3

    # 6. Merge settings.json
    print("\n--- 合并 settings.json ---")
    if not merge_settings(manifest, args.dry_run, args.force,
                          interactive=not args.non_interactive,
                          registerable=registerable):
        err("settings.json 合并失败。")
        return 4

    # 7. Save manifest
    if not args.dry_run:
        manifest["last_install_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        manifest["skill_version"] = SKILL_VERSION
        manifest["min_cc_version"] = MIN_CC_VERSION
        save_manifest(manifest)
        ok(f"Manifest 已保存 → {MANIFEST_PATH}")

    # 7.5. Check claude-md-management plugin (L3 audit)
    if not args.skip_plugin_check:
        print("\n--- L3 审计依赖：claude-md-management 插件 ---")
        check_and_enable_claude_md_management(
            auto_enable=args.enable_claude_md_management,
            interactive=not args.non_interactive,
            dry_run=args.dry_run,
        )

    # 8. Smoke test
    if not args.dry_run:
        print("\n--- 对已安装 Hook 执行冒烟测试 ---")
        smoke_test_all()

    # 9. Summary
    print_content_preservation_summary(backup_path)
    print("✨ 安装完成。")
    print(f"   已安装内容见 {MANIFEST_PATH}")
    print("   可通过环境变量配置：")
    print(f"     RULE_INTAKE_KEYWORDS={args.rule_intake_keywords}  （在 Shell 中设置）")
    print(f"     PROTECTED_BRANCHES='{args.protected_branches}'")
    print(f"   卸载：python3 {SKILL_DIR}/scripts/uninstall.py")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
