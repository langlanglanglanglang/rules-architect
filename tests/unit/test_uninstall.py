import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import uninstall
from recovery_archive import RecoveryArchive


class UninstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def archive(self, manifest_path=None):
        return RecoveryArchive(
            "test-uninstall",
            manifest_path=manifest_path,
            base_dir=self.root / "backups",
        )

    def test_project_registration_is_removed_from_exact_config_only(self):
        project_config = self.root / "project" / ".claude" / "settings.json"
        global_config = self.root / "home" / ".claude" / "settings.json"
        for path in (project_config, global_config):
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "hooks": {"PreToolUse": [{
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "python3 hook.py"}],
                }]},
            }))
        manifest = {"settings_hooks_added": [{
            "platform": "claude", "config_path": str(project_config),
            "event": "PreToolUse", "matcher": "Bash",
            "command": "python3 hook.py",
        }]}
        archive = self.archive()
        uninstall.remove_settings_hooks(manifest, dry_run=False, archive=archive)
        self.assertEqual(json.loads(project_config.read_text()).get("hooks"), {})
        self.assertIn("PreToolUse", json.loads(global_config.read_text())["hooks"])
        self.assertEqual(manifest["settings_hooks_added"], [])
        self.assertTrue(archive.created)
        self.assertEqual(
            archive.records[0]["original_path"], str(project_config.resolve())
        )

    def test_installed_file_is_moved_to_recovery_archive(self):
        target = self.root / "home" / ".claude" / "hooks" / "managed.py"
        target.parent.mkdir(parents=True)
        target.write_text("print('managed')\n")
        digest = uninstall.file_sha256(target)
        manifest_path = self.root / "manifest.json"
        manifest_path.write_text(json.dumps({"installed_files": []}))
        manifest = {"installed_files": [{
            "path": str(target), "hash_sha256": digest,
        }]}
        archive = self.archive(manifest_path)

        uninstall.remove_installed_files(
            manifest, False, False, True, archive
        )

        self.assertFalse(target.exists())
        self.assertEqual(manifest["installed_files"], [])
        self.assertEqual(len(archive.records), 1)
        self.assertEqual(archive.records[0]["disposition"], "moved")
        archived = archive.root / archive.records[0]["archive_path"]
        self.assertEqual(archived.read_text(), "print('managed')\n")
        self.assertTrue((archive.root / "manifest.before.json").is_file())

    def test_archive_failure_prevents_delete(self):
        target = self.root / "managed.py"
        target.write_text("keep me\n")
        manifest = {"installed_files": [{
            "path": str(target), "hash_sha256": uninstall.file_sha256(target),
        }]}

        class FailingArchive:
            planned_path = self.root / "never"

            def move_file(self, *args, **kwargs):
                raise OSError("disk full")

        uninstall.remove_installed_files(
            manifest, False, False, True, FailingArchive()
        )
        self.assertTrue(target.exists())
        self.assertEqual(len(manifest["installed_files"]), 1)

    def test_bootstrap_owned_skill_link_and_clean_checkout_are_removed(self):
        checkout = self.root / "checkout"
        checkout.mkdir()
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        link = self.root / "skills" / "rules-architect"
        link.parent.mkdir()
        link.symlink_to(checkout, target_is_directory=True)
        manifest = {
            "canonical_checkout": {
                "path": str(checkout), "created_by_bootstrap": True,
            },
            "skill_targets": [{
                "platform": "codex", "path": str(link),
                "checkout": str(checkout), "created_by_bootstrap": True,
            }],
        }
        uninstall.remove_skill_install(manifest, dry_run=False)
        self.assertFalse(link.exists())
        self.assertFalse(link.is_symlink())
        self.assertFalse(checkout.exists())
        self.assertEqual(manifest["skill_targets"], [])


if __name__ == "__main__":
    unittest.main()
