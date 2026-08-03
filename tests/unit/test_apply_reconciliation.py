import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from apply_reconciliation import apply_plan
from rule_inventory import compute_inventory_fingerprint


class ApplyReconciliationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.project = self.home / "project"
        self.project.mkdir()
        self.target = self.project / ".claude" / "hooks" / "new.py"
        self.inventory = {
            "schema_version": "1.0", "project_root": str(self.project),
            "platforms": ["claude"], "sources": [], "rule_candidates": [],
            "hook_registrations": [], "source_errors": [], "skipped_sources": [],
            "hook_artifacts": [], "inventory_fingerprint": "",
        }
        self.inventory["inventory_fingerprint"] = compute_inventory_fingerprint(self.inventory)
        self.plan = {
            "schema_version": "1.0",
            "inventory_fingerprint": self.inventory["inventory_fingerprint"],
            "project_root": str(self.project), "recommendations": [],
            "duplicates": [], "conflicts": [], "unclassified": [],
            "operations": [{
                "operation_id": "OP-create", "action": "create",
                "path": str(self.target), "content": "#!/usr/bin/env python3\n",
                "reason": "新增托管 Hook", "requires_confirmation": False,
                "rule_id": "R-new",
            }],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_does_not_write_and_apply_records_private_state(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False):
            preview = apply_plan(self.plan, self.inventory, confirm=False, verify_current=False)
            self.assertEqual(preview["applied"], 0)
            self.assertFalse(self.target.exists())
            result = apply_plan(self.plan, self.inventory, confirm=True, verify_current=False)
        self.assertEqual(result["applied"], 1)
        self.assertTrue(self.target.exists())
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o755)
        self.assertTrue(Path(result["state_path"]).exists())

    def test_create_refuses_to_overwrite_existing_file(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text("user content")
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False):
            with self.assertRaisesRegex(ValueError, "已存在"):
                apply_plan(self.plan, self.inventory, confirm=True, verify_current=False)


if __name__ == "__main__":
    unittest.main()
