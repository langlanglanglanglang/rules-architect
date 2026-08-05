import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from apply_reconciliation import apply_plan
from recommendation_contract import enforcement_digest
from rule_inventory import compute_inventory_fingerprint


class ApplyReconciliationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.project = self.home / "project"
        self.project.mkdir()
        self.target = self.project / ".claude" / "hooks" / "new.py"
        self.config = self.project / ".claude" / "settings.json"
        self.enforcement = {
            "mode": "block", "platform": "claude", "event": "PreToolUse",
            "matcher": "Bash", "predicate": "git push targets main",
        }
        self.inventory = {
            "schema_version": "1.1", "project_root": str(self.project),
            "platforms": ["claude"], "sources": [],
            "rule_candidates": [{
                "occurrence_id": "O-one", "text": "禁止 push main",
                "text_hash": "b" * 64, "source_path": str(self.project / "AGENTS.md"),
                "source_kind": "agents_md", "line_start": 1,
            }],
            "hook_registrations": [], "source_errors": [], "skipped_sources": [],
            "hook_artifacts": [], "path_rule_artifacts": [],
            "inventory_fingerprint": "",
        }
        self.refresh_fingerprint()
        self.plan = {
            "schema_version": "1.2", "plan_status": "ready",
            "inventory_fingerprint": self.inventory["inventory_fingerprint"],
            "project_root": str(self.project),
            "recommendations": [{
                "rule_id": "R-new", "occurrence_ids": ["O-one"],
                "summary": "禁止 push main",
                "canonical": {"target": "agents_md", "path": str(self.project / "AGENTS.md")},
                "delivery": [], "enforcement": [self.enforcement],
                "report_group": "hooks", "reason": "可确定阻断",
                "confidence": "high", "action": "create",
                "execution_mode": "automatic", "decision_source": "inferred",
                "artifact_ids": [], "operation_ids": ["OP-create"],
            }],
            "duplicates": [], "conflicts": [], "unclassified": [],
            "clarifications": [], "resolved_occurrence_ids": [],
            "resolved_artifact_ids": [], "artifact_decisions": [],
            "operations": [self.create_operation("OP-create", self.target)],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def refresh_fingerprint(self):
        self.inventory["inventory_fingerprint"] = compute_inventory_fingerprint(self.inventory)

    def hook_content(self, rule_id="R-new"):
        return (
            "#!/usr/bin/env python3\n"
            "# rules-architect-id: {}\n"
            "# rules-architect-enforcement: {}\n"
            "def main():\n    return 0\n"
        ).format(rule_id, enforcement_digest(self.enforcement))

    def registration(self, path, event="PreToolUse", command=None):
        return {
            "platform": "claude", "config_path": str(self.config),
            "event": event, "matcher": "Bash",
            "command": command or "python3 {}".format(path),
        }

    def create_operation(self, operation_id, path):
        return {
            "operation_id": operation_id, "action": "create",
            "path": str(path), "content": self.hook_content(),
            "reason": "新增托管 Hook", "requires_confirmation": False,
            "rule_id": "R-new", "registrations": [self.registration(path)],
        }

    def test_preview_does_full_preflight_and_apply_records_private_state(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False):
            preview = apply_plan(self.plan, self.inventory, confirm=False, verify_current=False)
            self.assertEqual(preview["applied"], 0)
            self.assertFalse(self.target.exists())
            result = apply_plan(self.plan, self.inventory, confirm=True, verify_current=False)
        self.assertEqual(result["applied"], 1)
        self.assertTrue(self.target.exists())
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o755)
        state = json.loads(Path(result["state_path"]).read_text())
        self.assertEqual(state["schema_version"], "1.1")
        self.assertEqual(state["applied_operation_ids"], ["OP-create"])
        self.assertEqual(len(state["history"]), 1)

    def test_preview_rejects_unsupported_target(self):
        self.plan["operations"][0]["path"] = str(self.project / "AGENTS.md")
        self.plan["operations"][0]["registrations"][0]["command"] = "python3 AGENTS.md"
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False):
            with self.assertRaisesRegex(ValueError, "Hook 写操作必须落在 hooks 目录"):
                apply_plan(self.plan, self.inventory, confirm=False, verify_current=False)

    def test_create_refuses_to_overwrite_existing_file(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text("user content")
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False):
            with self.assertRaisesRegex(ValueError, "已存在"):
                apply_plan(self.plan, self.inventory, confirm=True, verify_current=False)

    def test_partial_selection_applies_only_requested_operation(self):
        second = self.project / ".claude" / "hooks" / "second.py"
        self.plan["operations"].append(self.create_operation("OP-second", second))
        self.plan["recommendations"][0]["operation_ids"].append("OP-second")
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False):
            preview = apply_plan(
                self.plan, self.inventory, confirm=False, verify_current=False,
                selected_operation_ids={"OP-second"},
            )
            self.assertEqual(preview["selected_operation_ids"], ["OP-second"])
            result = apply_plan(
                self.plan, self.inventory, confirm=True, verify_current=False,
                selected_operation_ids={"OP-second"},
            )
        self.assertFalse(self.target.exists())
        self.assertTrue(second.exists())
        state = json.loads(Path(result["state_path"]).read_text())
        self.assertEqual(state["rule_ids"], ["R-new"])
        self.assertEqual(state["applied_operation_ids"], ["OP-second"])

    def test_partial_selection_rejects_unknown_operation(self):
        with self.assertRaisesRegex(ValueError, "未知操作 ID"):
            apply_plan(
                self.plan, self.inventory, confirm=False, verify_current=False,
                selected_operation_ids={"OP-missing"},
            )

    def test_legacy_plan_is_read_only(self):
        self.plan["schema_version"] = "1.1"
        self.plan.pop("plan_status")
        with self.assertRaisesRegex(ValueError, "只接受 schema 1.2"):
            apply_plan(self.plan, self.inventory, confirm=False, verify_current=False)

    def test_empty_apply_has_no_side_effects(self):
        self.plan["operations"] = []
        recommendation = self.plan["recommendations"][0]
        recommendation.update({
            "action": "keep", "execution_mode": "none", "operation_ids": [],
        })
        manifest = self.home / ".claude" / ".rules-architect-manifest.json"
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False):
            result = apply_plan(self.plan, self.inventory, confirm=True, verify_current=False)
        self.assertEqual(result["mode"], "no_op")
        self.assertFalse(manifest.exists())

    def test_corrupt_state_blocks_before_mutation(self):
        from state_store import default_state_path
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False):
            state_path = default_state_path(self.project)
            state_path.parent.mkdir(parents=True)
            state_path.write_text("not json")
            with self.assertRaises(json.JSONDecodeError):
                apply_plan(self.plan, self.inventory, confirm=True, verify_current=False)
        self.assertFalse(self.target.exists())

    def test_update_uses_explicit_desired_registration_set(self):
        hook = self.project / ".claude" / "hooks" / "managed.py"
        hook.parent.mkdir(parents=True)
        hook.write_text("old\n")
        old_hash = hashlib.sha256(hook.read_bytes()).hexdigest()
        old = self.registration(hook, command="python3 old.py")
        preserved = self.registration(hook, event="PostToolUse", command="python3 {}".format(hook))
        replacement = self.registration(hook, command="python3 {}".format(hook))
        self.config.write_text(json.dumps({
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 old.py"}]}],
                "PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 {}".format(hook)}]}],
            },
        }))
        manifest_path = self.home / ".claude" / ".rules-architect-manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({
            "installed_files": [],
            "settings_hooks_added": [
                {"event": old["event"], "matcher": old["matcher"], "command": old["command"]},
                {"event": preserved["event"], "matcher": preserved["matcher"], "command": preserved["command"]},
            ],
        }))
        self.inventory["hook_artifacts"] = [{
            "artifact_id": "H-managed", "kind": "hook", "path": str(hook),
            "status": "active", "ownership": "rules_architect",
            "safe_to_modify": True, "modified_since_managed": False,
            "registrations": [old, preserved], "content_hash": old_hash,
            "managed_hash": old_hash, "platforms": ["claude"],
            "scopes": ["project"], "registered": True, "exists": True,
            "symlink": False, "rule_id": "R-new", "generator": None,
        }]
        self.refresh_fingerprint()
        self.plan["inventory_fingerprint"] = self.inventory["inventory_fingerprint"]
        recommendation = self.plan["recommendations"][0]
        second_enforcement = dict(self.enforcement, event="PostToolUse")
        recommendation.update({
            "action": "update", "artifact_ids": ["H-managed"],
            "operation_ids": ["OP-update"],
            "enforcement": [self.enforcement, second_enforcement],
        })
        self.plan["artifact_decisions"] = [{
            "artifact_id": "H-managed", "action": "update", "reason": "更新",
            "confidence": "high", "decision_source": "existing_state",
            "operation_ids": ["OP-update"],
        }]
        self.plan["operations"] = [{
            "operation_id": "OP-update", "action": "update", "rule_id": "R-new",
            "artifact_id": "H-managed", "path": str(hook),
            "content": (
                self.hook_content()
                + "# rules-architect-enforcement: {}\n".format(
                    enforcement_digest(second_enforcement)
                )
            ),
            "expected_hash": old_hash,
            "reason": "更新注册", "requires_confirmation": True,
            "registrations": [replacement, preserved],
        }]
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False):
            apply_plan(self.plan, self.inventory, confirm=True, verify_current=False)
        serialized = json.dumps(json.loads(self.config.read_text()), ensure_ascii=False)
        self.assertNotIn("python3 old.py", serialized)
        self.assertIn(str(hook), serialized)
        self.assertIn("PostToolUse", serialized)
        manifest_text = json.dumps(json.loads(manifest_path.read_text()), ensure_ascii=False)
        self.assertNotIn("python3 old.py", manifest_text)
        self.assertIn(str(hook), manifest_text)


if __name__ == "__main__":
    unittest.main()
