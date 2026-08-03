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


SKILL_VERSION = "2.4.0"
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
                warn("Manifest 无法读取（仅预览：原本会隔离为 .corrupt.<时间戳>）；"
                     "将使用新的内存 Manifest，不修改任何文件")
            else:
                ts = time.strftime("%Y%m%d-%H%M%S")
                bad = MANIFEST_PATH.with_suffix(f".json.corrupt.{ts}")
                try:
                    MANIFEST_PATH.rename(bad)
                    warn(f"Manifest 无法读取，已隔离为 {bad.name}；将重新创建。"
                         "旧安装条目不会自动恢复，请从隔离文件中找回。")
                except Exception:
                    warn("Manifest 无法读取且无法隔离，将重新创建")
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


def record_section(target: Path, section_hash: str, action: str) -> None:
    """Upsert this target's §六 entry into the manifest (used both for a fresh
    install and to adopt an already-present pristine block after manifest loss)."""
    manifest = load_manifest()
    manifest.setdefault("personal_md_sections", [])
    manifest["personal_md_sections"] = [
        s for s in manifest["personal_md_sections"] if s.get("file") != str(target)
    ]
    manifest["personal_md_sections"].append({
        "file": str(target),
        "marker_begin": MARKER_BEGIN,
        "marker_end": MARKER_END,
        "section_hash": section_hash,
        "owner": "rules-architect",
        "template_version": SKILL_VERSION,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "action": action,
    })
    manifest["last_install_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save_manifest(manifest)


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
                    help="目标文件路径（默认：./CLAUDE-personal.md）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--create-if-missing", action="store_true",
                    help="目标不存在时新建 CLAUDE-personal.md")
    ap.add_argument("--force", action="store_true",
                    help="即使 §六区块在安装后被编辑过也覆盖")
    ap.add_argument("--protected-branches", default="develop|test|master",
                    help="供 §六“Hook 健康检查”小节引用")
    ap.add_argument("--cache-dir",
                    default=str(Path.home() / ".cache" / "claude-hooks"),
                    help="§六引用的缓存目录")
    args = ap.parse_args()

    target = Path(args.target).resolve()
    if not TEMPLATE_PATH.exists():
        err(f"模板不存在：{TEMPLATE_PATH}")
        return 2

    print(f"\n📦 personal-section-6 安装器 v{SKILL_VERSION}")
    print(f"   目标：{target}")
    print(f"   模板：{TEMPLATE_PATH}")
    print()

    rendered = render_section(args.cache_dir, args.protected_branches)
    rendered_hash = text_sha256(rendered)

    if not target.exists():
        if not args.create_if_missing:
            err(f"目标 {target} 不存在。"
                "请使用 --create-if-missing 创建。")
            return 1
        info(f"正在新建 {target}")
        body = (
            "# 个人 CLAUDE 配置\n\n"
            "本项目的个人偏好与工作流调整。\n\n"
            + rendered
        )
        if args.dry_run:
            info(f"仅预览：将创建 {target}")
            return 0
        atomic_write(target, body)
        ok(f"已创建 {target}")
        action = "created"
    else:
        existing = target.read_text()
        # Content-protection guard: if a §六 block exists and was edited since
        # install (its hash differs from the recorded section_hash), refuse to
        # overwrite unless --force. Mirrors the file hash-protection promise.
        if MARKER_BEGIN in existing and not args.force:
            rec = recorded_section_hash(target, args.dry_run)
            cur = extract_block(existing)
            if cur is not None and rec is None:
                if text_sha256(cur) == rendered_hash:
                    # Markers present, manifest lost, but the block is pristine
                    # (identical to a fresh render) → safe to adopt into manifest
                    # instead of refusing, so uninstall can remove it later.
                    if not args.dry_run:
                        record_section(target, rendered_hash, "adopted")
                    ok(f"{target.name} 中的 §六与模板一致，已纳入 Manifest")
                    return 0
                # Markers exist, no record, and block differs from template:
                # can't prove it's safe, so don't overwrite blindly.
                warn(f"{target.name} 中存在 §六标记，但 Manifest 无记录且内容与模板"
                     "不同，已拒绝覆盖。请使用 --force。")
                return 1
            if cur is not None and rec is not None and text_sha256(cur) != rec:
                warn(f"{target.name} 中的 §六区块在安装后已被修改"
                     "（哈希不一致），已拒绝覆盖。请使用 --force 替换。")
                return 1
        new_text, action = replace_or_append(existing, rendered)
        if new_text == existing:
            ok("已是最新状态，无需操作")
            return 0
        if args.dry_run:
            action_zh = {
                "replaced": "替换",
                "inserted_before_维护": "插入到“维护”小节之前",
                "appended": "追加",
            }.get(action, action)
            info(f"仅预览：将{action_zh}（插入 {len(rendered)} 字节）")
            return 0
        atomic_write(target, new_text)
        action_zh = {
            "replaced": "已替换",
            "inserted_before_维护": "已插入到“维护”小节之前",
            "appended": "已追加",
        }.get(action, action)
        ok(f"{target} 中的 §六{action_zh}")

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
    ok(f"Manifest 已更新 → {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
