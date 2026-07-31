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
import copy
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
MANIFEST_PATH = Path((os.environ.get("RULES_ARCHITECT_MANIFEST") or "").strip()
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


def text_sha256(t: str) -> str:
    # Matches install_personal_md_section.py's section_hash computation.
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


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


def save_manifest(m: dict) -> None:
    atomic_write(MANIFEST_PATH, json.dumps(m, indent=2, ensure_ascii=False))


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
            info(f"{p}：文件已不存在，跳过")
            manifest[key].remove(entry)
            continue
        try:
            actual = file_sha256(p)
        except Exception as e:
            warn(f"{p}：无法计算哈希（{e}），跳过")
            continue
        if actual != recorded_hash:
            if force:
                pass  # proceed
            elif non_interactive:
                warn(f"{p}：安装后已被修改，跳过（可使用 --force）")
                continue
            else:
                warn(f"{p}：哈希不一致，文件在安装后被修改")
                if not confirm("    仍要删除吗？", default_yes=False):
                    continue
        if dry_run:
            info(f"仅预览：将删除 {p}")
        else:
            p.unlink()
            ok(f"已删除 {p}")
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
        err(f"无法读取 settings.json：{e}")
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
            info(f"仅预览：将从 settings.json 移除 {removed} 个 Hook 条目")
        else:
            new_text = json.dumps(settings, indent=2, ensure_ascii=False)
            atomic_write(SETTINGS_PATH, new_text)
            ok(f"已从 settings.json 移除 {removed} 个 Hook 条目")
        manifest["settings_hooks_added"] = []
    else:
        info("settings.json 中没有匹配的 Hook 条目")


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
        err(f"无法读取 Codex hooks.json：{e}")
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
                # Match exact (event,matcher,cmd), and also (event,None,cmd):
                # matcher-less events (UserPromptSubmit) are recorded with
                # matcher=None but our command may live in a matcher:"*" group.
                if (event, matcher, cmd) in targets or (event, None, cmd) in targets:
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
            info(f"仅预览：将从 Codex hooks.json 移除 {removed} 个条目")
        else:
            atomic_write(CODEX_HOOKS_JSON,
                         json.dumps(config, indent=2, ensure_ascii=False))
            ok(f"已从 Codex hooks.json 移除 {removed} 个条目")
        manifest["codex_hooks_added"] = []
    else:
        info("Codex hooks.json 中没有匹配条目")


def remove_personal_sections(manifest, dry_run, force, non_interactive):
    sections = manifest.get("personal_md_sections", [])
    for s in list(sections):
        f = Path(s["file"])
        begin = s["marker_begin"]
        end = s["marker_end"]
        if not f.exists():
            info(f"{f}：文件已不存在，跳过")
            sections.remove(s)
            continue
        text = f.read_text()
        if begin not in text or end not in text:
            warn(f"{f}：未找到区块标记，保持不变")
            sections.remove(s)
            continue
        # Remove the markered block
        pattern = re.compile(
            re.escape(begin) + r".*?" + re.escape(end) + r"\n?",
            re.DOTALL
        )
        # Content-protection: if the block was edited since install (hash differs
        # from recorded section_hash), don't silently delete the user's edits.
        recorded = s.get("section_hash")
        m = pattern.search(text)
        current_hash = text_sha256(m.group(0)) if m else None
        if recorded and current_hash and current_hash != recorded and not force:
            if non_interactive:
                warn(f"{f}：§六区块在安装后已被修改，将予以保留"
                     "（如确需删除，请使用 --force）")
                # keep tracked so a later --force can still find/remove it
                continue
            if not confirm(f"{f}：§六区块在安装后已被编辑，仍要删除吗？",
                           default_yes=False):
                info(f"{f}：已按用户选择保留 §六")
                continue  # keep tracked
        new_text = pattern.sub("", text, count=1)
        if dry_run:
            info(f"仅预览：将从 {f} 移除 §六标记区块")
        else:
            atomic_write(f, new_text)
            ok(f"已从 {f} 移除 §六")
        sections.remove(s)


def restore_backup_if_requested(manifest, dry_run):
    bak = manifest.get("settings_backup_path")
    if not bak:
        warn("Manifest 中没有记录 settings 备份")
        return
    bak_path = Path(bak)
    if not bak_path.exists():
        warn(f"备份文件不存在：{bak}")
        return
    if dry_run:
        info(f"仅预览：将恢复 {bak} → {SETTINGS_PATH}")
        return
    shutil.copy2(bak_path, SETTINGS_PATH)
    ok(f"已从 {bak_path.name} 恢复 settings.json")



def print_uninstall_preservation_summary() -> None:
    """Show what uninstall did NOT touch — for user trust."""
    print()
    print("✅ 卸载时不会改动以下内容：")
    print()
    print("   ✋ L1 个人记忆文件                    — 完全归用户所有，绝不删除")
    print("   ✋ CLAUDE.md                           — 不做改动")
    print("   ✋ CLAUDE-personal.md 的 §六之外内容  — 保留 §一～§五及其他内容")
    print("   ✋ settings.json 中的其他 Hook        — 只移除本项目添加的条目")
    print("   ✋ 其他 .claude/rules/*.md            — 只移除 rule-intake.md")
    print("   ✋ Codex hooks.json 中的其他条目      — 只移除本项目添加的条目")
    print()
    print("   本地修改过且哈希不一致的文件 → 警告后跳过，绝不直接删除。")
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--non-interactive", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="即使哈希不一致也删除文件（危险：手动指定 "
                         "RULES_ARCHITECT_MANIFEST 会绕过哈希保护，并可能删除"
                         "其中列出的任意路径）")
    ap.add_argument("--restore-backup", action="store_true",
                    help="同时从备份恢复 settings.json"
                         "（不是精确回滚，而是完整覆盖）")
    args = ap.parse_args()

    if not MANIFEST_PATH.exists():
        err(f"在 {MANIFEST_PATH} 未找到 Manifest，没有可卸载内容")
        return 1

    try:
        manifest = json.loads(MANIFEST_PATH.read_text())
    except Exception as e:
        err(f"无法读取 {MANIFEST_PATH} 中的 Manifest（{e}）。")
        err("已拒绝卸载：没有有效 Manifest 就无法判断哪些文件属于本项目。"
            "请修复或移除该 Manifest 后重新运行。")
        return 1
    # Dry-run must not mutate any state that affects observable output; the
    # remove_* helpers pop entries from the manifest dict, so operate on a
    # throwaway copy when previewing. (Real runs mutate the live manifest,
    # which is then archived below.)
    work = copy.deepcopy(manifest) if args.dry_run else manifest
    print(f"\n📦 rules-architect 卸载器")
    print(f"   Manifest：{MANIFEST_PATH}")
    print(f"   已安装文件：{len(manifest.get('installed_files', []))}")
    print(f"   settings Hook 条目：{len(manifest.get('settings_hooks_added', []))}")
    print(f"   个人 Markdown 区块：{len(manifest.get('personal_md_sections', []))}")
    print(f"   Codex Hook 文件：{len(manifest.get('codex_installed_files', []))}")
    print(f"   Codex Hook 条目：{len(manifest.get('codex_hooks_added', []))}")
    print()

    if not args.non_interactive:
        if not confirm("是否继续卸载？", default_yes=False):
            err("已取消")
            return 1

    print("\n--- 正在移除已安装的 Hook 文件 ---")
    remove_installed_files(work, args.dry_run, args.force, args.non_interactive)

    print("\n--- 正在从 settings.json 移除 Hook 条目 ---")
    remove_settings_hooks(work, args.dry_run)

    print("\n--- 正在移除 Codex Hook 文件 ---")
    remove_installed_files(work, args.dry_run, args.force,
                           args.non_interactive, key="codex_installed_files")

    print("\n--- 正在从 Codex hooks.json 移除 Hook 条目 ---")
    remove_codex_hooks(work, args.dry_run)

    print("\n--- 正在从个人 Markdown 移除 §六区块 ---")
    remove_personal_sections(work, args.dry_run,
                             args.force, args.non_interactive)

    if args.restore_backup:
        print("\n--- 正在恢复 settings.json 备份 ---")
        restore_backup_if_requested(work, args.dry_run)

    if args.dry_run:
        info("仅预览完成，没有实际修改任何内容。")
        return 0

    # If any tracked entries were preserved/skipped (e.g. locally-modified files
    # or §六 blocks), keep a reduced manifest so a later deliberate --force run
    # can still find them. Only archive when everything tracked is resolved.
    remaining = sum(len(work.get(k, [])) for k in (
        "installed_files", "codex_installed_files",
        "settings_hooks_added", "codex_hooks_added", "personal_md_sections"))
    if remaining:
        save_manifest(work)
        warn(f"已保留 {remaining} 个跟踪项（被修改或跳过）— Manifest 仍保存在 "
             f"{MANIFEST_PATH}，未归档。如需移除，请使用 --force 重新运行。")
    else:
        ts = time.strftime("%Y%m%d-%H%M%S")
        removed_path = MANIFEST_PATH.with_suffix(f".json.removed.{ts}")
        MANIFEST_PATH.rename(removed_path)
        ok(f"Manifest 已归档 → {removed_path}")

    print_uninstall_preservation_summary()
    print("✨ 卸载完成。")
    print("   手动修改过的文件均已保留。")
    print("   重新安装：python3 .../scripts/install_hooks.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
