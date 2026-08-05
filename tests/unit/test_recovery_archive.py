import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from recovery_archive import RecoveryArchive


class RecoveryArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_backup_records_original_bytes_hash_and_mode(self):
        manifest = self.root / "manifest.json"
        manifest.write_text('{"installed_files": []}\n')
        target = self.root / "hook.py"
        target.write_text("print('before')\n")
        target.chmod(0o755)
        expected = hashlib.sha256(target.read_bytes()).hexdigest()
        archive = RecoveryArchive(
            "unit", manifest_path=manifest, base_dir=self.root / "archives"
        )

        first = archive.backup_file(target, "hook", expected_hash=expected)
        target.write_text("print('after')\n")
        second = archive.backup_file(target, "hook", expected_hash=expected)

        self.assertEqual(first, second)
        archived = archive.root / first["archive_path"]
        self.assertEqual(archived.read_text(), "print('before')\n")
        self.assertEqual(first["sha256"], expected)
        self.assertEqual(first["mode"], 0o755)
        index = json.loads((archive.root / "index.json").read_text())
        self.assertEqual(index["purpose"], "unit")
        self.assertEqual(len(index["files"]), 1)
        self.assertTrue((archive.root / "manifest.before.json").is_file())

    def test_hash_change_aborts_before_archive_creation(self):
        target = self.root / "hook.py"
        target.write_text("changed\n")
        archive = RecoveryArchive("unit", base_dir=self.root / "archives")
        with self.assertRaisesRegex(RuntimeError, "哈希已变化"):
            archive.backup_file(target, "hook", expected_hash="0" * 64)
        self.assertFalse(archive.created)
        self.assertTrue(target.exists())

    def test_move_relocates_original_file_and_records_disposition(self):
        target = self.root / "retired-hook.py"
        target.write_text("retired\n")
        expected = hashlib.sha256(target.read_bytes()).hexdigest()
        archive = RecoveryArchive(
            "unit", base_dir=self.root / "archives"
        )

        record = archive.move_file(target, "hook_delete", expected_hash=expected)

        self.assertFalse(target.exists())
        self.assertEqual(record["disposition"], "moved")
        self.assertEqual(
            (archive.root / record["archive_path"]).read_text(), "retired\n"
        )
        index = json.loads((archive.root / "index.json").read_text())
        self.assertEqual(index["files"][0]["disposition"], "moved")

    def test_dry_run_creates_nothing(self):
        target = self.root / "hook.py"
        target.write_text("content\n")
        archive = RecoveryArchive(
            "unit", base_dir=self.root / "archives", dry_run=True
        )
        record = archive.backup_file(target, "hook")
        self.assertTrue(record["dry_run"])
        self.assertEqual(record["disposition"], "copied")
        self.assertFalse(archive.created)
        self.assertFalse((self.root / "archives").exists())


if __name__ == "__main__":
    unittest.main()
