#!/usr/bin/env python3
"""Record bootstrap-owned Skill discovery targets for precise uninstall."""
import argparse
import json
import os
import tempfile
import time
from pathlib import Path


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, str(path))
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--checkout-created", action="store_true")
    parser.add_argument(
        "--target", action="append", nargs=3, metavar=("PLATFORM", "PATH", "CREATED")
    )
    args = parser.parse_args()
    manifest_path = Path(
        os.environ.get("RULES_ARCHITECT_MANIFEST")
        or (Path.home() / ".claude" / ".rules-architect-manifest.json")
    )
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        if not isinstance(manifest, dict):
            raise ValueError("Manifest 根节点必须是对象")
    else:
        manifest = {"skill_name": "rules-architect"}
    for key in (
        "installed_files", "codex_installed_files", "settings_hooks_added",
        "codex_hooks_added", "personal_md_sections", "skill_targets",
    ):
        manifest.setdefault(key, [])
    checkout = str(Path(args.checkout).expanduser().resolve())
    previous_checkout = manifest.get("canonical_checkout") or {}
    manifest["canonical_checkout"] = {
        "path": checkout,
        "created_by_bootstrap": bool(args.checkout_created) or (
            previous_checkout.get("path") == checkout
            and bool(previous_checkout.get("created_by_bootstrap"))
        ),
    }
    tracked = manifest.setdefault("skill_targets", [])
    for platform, raw_path, created in args.target or []:
        path = str(Path(raw_path).expanduser().absolute())
        previous = next((item for item in tracked if item.get("path") == path), {})
        entry = {
            "platform": platform,
            "path": path,
            "checkout": checkout,
            "created_by_bootstrap": created == "1" or bool(
                previous.get("created_by_bootstrap")
            ),
        }
        tracked[:] = [item for item in tracked if item.get("path") != path]
        tracked.append(entry)
    manifest["skill_install_recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    atomic_write(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
