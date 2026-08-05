#!/usr/bin/env python3
"""Persistent recovery archives for destructive rules-architect mutations."""
import hashlib
import errno
import json
import os
import stat
import tempfile
import time
from pathlib import Path


def sha256_bytes(content):
    return hashlib.sha256(content).hexdigest()


def _atomic_write(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, str(path))
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class RecoveryArchive:
    """Archive the pre-mutation bytes of each file at most once per run.

    The archive is created lazily. A failed archive write raises before the
    caller mutates the source, making "backup succeeded" a deletion/update
    precondition instead of a best-effort side effect.
    """

    def __init__(self, purpose, manifest_path=None, base_dir=None, dry_run=False):
        self.purpose = purpose
        self.manifest_path = Path(manifest_path) if manifest_path else None
        configured = (os.environ.get("RULES_ARCHITECT_RECOVERY_DIR") or "").strip()
        self.base_dir = Path(
            base_dir or configured or (Path.home() / ".claude" / "rules-architect-backups")
        ).expanduser()
        self.dry_run = dry_run
        self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self._prefix = time.strftime("%Y%m%d-%H%M%S") + "-{}-".format(purpose)
        self.root = None
        self.records = []
        self._by_original_path = {}
        self._manifest_snapshot = None

    @property
    def planned_path(self):
        return self.root or (self.base_dir / (self._prefix + "<run-id>"))

    @property
    def created(self):
        return self.root is not None

    def _ensure_created(self):
        if self.root is not None:
            return
        if self.base_dir.is_symlink():
            raise RuntimeError("恢复归档根目录不能是符号链接：{}".format(self.base_dir))
        self.base_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.base_dir, 0o700)
        self.root = Path(tempfile.mkdtemp(prefix=self._prefix, dir=str(self.base_dir)))
        os.chmod(self.root, 0o700)
        (self.root / "files").mkdir(mode=0o700)
        if self.manifest_path and self.manifest_path.is_file():
            if self.manifest_path.is_symlink():
                raise RuntimeError(
                    "Manifest 不能是符号链接：{}".format(self.manifest_path)
                )
            content = self.manifest_path.read_bytes()
            _atomic_write(self.root / "manifest.before.json", content)
            self._manifest_snapshot = {
                "original_path": str(self.manifest_path),
                "sha256": sha256_bytes(content),
                "archive_path": "manifest.before.json",
            }
        self._write_index()

    def _write_index(self):
        if self.root is None:
            return
        payload = {
            "schema_version": "1.0",
            "purpose": self.purpose,
            "created_at": self.created_at,
            "manifest_snapshot": self._manifest_snapshot,
            "files": self.records,
        }
        _atomic_write(
            self.root / "index.json",
            (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )

    def backup_file(self, path, category, expected_hash=None):
        path = Path(path).expanduser().absolute()
        key = str(path)
        if key in self._by_original_path:
            return self._by_original_path[key]
        if self.dry_run:
            return {
                "original_path": key,
                "archive_path": str(self.planned_path / "files" / path.name),
                "category": category,
                "disposition": "copied",
                "dry_run": True,
            }
        if path.is_symlink():
            raise RuntimeError("拒绝归档符号链接目标：{}".format(path))
        if not path.is_file():
            raise RuntimeError("待归档目标不是普通文件：{}".format(path))

        content = path.read_bytes()
        digest = sha256_bytes(content)
        if expected_hash and digest != expected_hash:
            raise RuntimeError("归档前目标哈希已变化：{}".format(path))
        mode = stat.S_IMODE(path.stat().st_mode)
        self._ensure_created()
        path_key = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        destination = self.root / "files" / (path_key + "-" + path.name)
        _atomic_write(destination, content, mode=mode)
        archived_hash = sha256_bytes(destination.read_bytes())
        if archived_hash != digest:
            raise RuntimeError("恢复归档校验失败：{}".format(destination))
        record = {
            "original_path": key,
            "archive_path": str(destination.relative_to(self.root)),
            "sha256": digest,
            "mode": mode,
            "category": category,
            "disposition": "copied",
            "backed_up_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        self.records.append(record)
        self._by_original_path[key] = record
        self._write_index()
        return record

    def move_file(self, path, category, expected_hash=None):
        """Move a retired file into the archive instead of deleting it.

        ``os.replace`` is used on the same filesystem. For a cross-device
        archive root, verified copy+unlink provides equivalent final semantics.
        Any failure before the index is durable restores or preserves the
        original path.
        """
        path = Path(path).expanduser().absolute()
        key = str(path)
        if key in self._by_original_path:
            record = self._by_original_path[key]
            if record.get("disposition") == "moved" and not path.exists():
                return record
            raise RuntimeError("目标已按其他方式归档，拒绝重复移动：{}".format(path))
        if self.dry_run:
            return {
                "original_path": key,
                "archive_path": str(self.planned_path / "files" / path.name),
                "category": category,
                "disposition": "moved",
                "dry_run": True,
            }
        if path.is_symlink():
            raise RuntimeError("拒绝移动符号链接目标：{}".format(path))
        if not path.is_file():
            raise RuntimeError("待移动目标不是普通文件：{}".format(path))

        content = path.read_bytes()
        digest = sha256_bytes(content)
        if expected_hash and digest != expected_hash:
            raise RuntimeError("移动前目标哈希已变化：{}".format(path))
        mode = stat.S_IMODE(path.stat().st_mode)
        self._ensure_created()
        path_key = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        destination = self.root / "files" / (path_key + "-" + path.name)
        cross_device = False
        try:
            os.replace(str(path), str(destination))
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            cross_device = True
            _atomic_write(destination, content, mode=mode)
            if sha256_bytes(destination.read_bytes()) != digest:
                raise RuntimeError("跨文件系统移动校验失败：{}".format(destination))
            path.unlink()

        try:
            if sha256_bytes(destination.read_bytes()) != digest:
                raise RuntimeError("移动归档校验失败：{}".format(destination))
            record = {
                "original_path": key,
                "archive_path": str(destination.relative_to(self.root)),
                "sha256": digest,
                "mode": mode,
                "category": category,
                "disposition": "moved",
                "backed_up_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            self.records.append(record)
            self._by_original_path[key] = record
            self._write_index()
            return record
        except Exception:
            self._by_original_path.pop(key, None)
            if self.records and self.records[-1].get("original_path") == key:
                self.records.pop()
            if not path.exists() and destination.is_file():
                if cross_device:
                    _atomic_write(path, destination.read_bytes(), mode=mode)
                    destination.unlink()
                else:
                    os.replace(str(destination), str(path))
            raise

    def summary(self):
        if not self.created:
            return None
        return {
            "path": str(self.root),
            "index_path": str(self.root / "index.json"),
            "purpose": self.purpose,
            "created_at": self.created_at,
            "file_count": len(self.records),
        }
