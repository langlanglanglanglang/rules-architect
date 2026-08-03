#!/usr/bin/env python3
"""Private per-project reconciliation state for rules-architect.

The state contains identifiers and hashes only. Rule bodies remain in their
original files and are never copied into this store.
"""
import hashlib
import json
import os
import tempfile
from pathlib import Path


STATE_SCHEMA_VERSION = "1.0"


def project_key(project_root):
    value = str(Path(project_root).expanduser().resolve())
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def state_root():
    configured = (os.environ.get("RULES_ARCHITECT_STATE_HOME") or "").strip()
    if configured:
        return Path(configured).expanduser()
    xdg = (os.environ.get("XDG_STATE_HOME") or "").strip()
    if xdg:
        return Path(xdg).expanduser() / "rules-architect"
    if os.name == "nt":
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        if local:
            return Path(local) / "rules-architect" / "state"
    return Path.home() / ".local" / "state" / "rules-architect"


def default_state_path(project_root):
    return state_root() / "projects" / (project_key(project_root) + ".json")


def load_state(path):
    path = Path(path)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("状态文件根节点必须是 JSON 对象")
    return data


def atomic_private_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        if hasattr(os, "fchmod") and os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, str(path))
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
