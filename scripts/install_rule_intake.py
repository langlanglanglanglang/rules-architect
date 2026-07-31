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
                warn(f"Manifest 无法读取，已隔离为 {bad.name}；将重新创建。"
                     "旧安装条目不会自动恢复，请从隔离文件中找回。")
            except Exception:
                warn("Manifest 无法读取且无法隔离，将重新创建")
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
                    help="项目根目录（默认为当前目录）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--paths",
                    help="以逗号分隔的 glob，用于覆盖默认路径列表")
    ap.add_argument("--force", action="store_true",
                    help="内容与模板不同时覆盖")
    args = ap.parse_args()

    project_root = Path(args.dir).resolve()
    rules_dir = project_root / ".claude" / "rules"
    dest_path = rules_dir / "rule-intake.md"

    if not TEMPLATE_PATH.exists():
        err(f"模板不存在：{TEMPLATE_PATH}")
        return 2

    paths_list = (
        [p.strip() for p in args.paths.split(",") if p.strip()]
        if args.paths else DEFAULT_PATHS
    )

    print(f"\n📦 rule-intake.md 安装器 v{SKILL_VERSION}")
    print(f"   项目：{project_root}")
    print(f"   目标：{dest_path}")
    print(f"   路径：{len(paths_list)} 个 glob（{'自定义' if args.paths else '默认'}）")
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
            ok("已安装且内容一致")
            # Adopt into the manifest if untracked (e.g. manifest lost/reset),
            # so uninstall can still remove this file later.
            if not args.dry_run:
                manifest = load_manifest()
                if not any(f.get("path") == str(dest_path)
                           for f in manifest.get("installed_files", [])):
                    manifest.setdefault("installed_files", []).append({
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
                    ok("已纳入 Manifest（原先未跟踪）")
            return 0
        if not args.force:
            warn(f"{dest_path} 已存在且内容不同。"
                 "请使用 --force 覆盖，或调整 --paths 使其匹配。")
            return 1

    if args.dry_run:
        info(f"仅预览：将写入 {dest_path}（{len(rendered)} 字节）")
        info(f"仅预览：路径区块：\n{render_paths_block(paths_list)}")
        return 0

    atomic_write(dest_path, rendered)
    ok(f"已安装 {dest_path}")

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
    ok(f"Manifest 已更新 → {MANIFEST_PATH}")

    print()
    print("✨ 完成。编辑任意规则文件（例如 MEMORY.md、.claude/rules/*.md），"
          "即可看到自动注入的归位流程。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
