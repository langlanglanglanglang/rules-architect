import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from recommendation_contract import validate_recommendations
from render_distribution import render
from rule_inventory import compute_inventory_fingerprint


class RecommendationContractTest(unittest.TestCase):
    def inventory(self):
        inventory = {
            "schema_version": "1.0",
            "project_root": "/repo",
            "inventory_fingerprint": "a" * 64,
            "sources": [],
            "hook_registrations": [],
            "source_errors": [],
            "skipped_sources": [],
            "summary": {
                "sources": 1,
                "rule_candidates": 1,
                "source_errors": 0,
                "skipped": 0,
            },
            "rule_candidates": [{
                "occurrence_id": "O-one",
                "text": "禁止直接 push main",
                "text_hash": "b" * 64,
                "source_path": "/repo/AGENTS.md",
                "source_kind": "agents_md",
                "line_start": 8,
            }],
        }
        inventory["inventory_fingerprint"] = compute_inventory_fingerprint(
            inventory
        )
        return inventory

    def recommendations(self):
        inventory = self.inventory()
        return {
            "schema_version": "1.0",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "project_root": "/repo",
            "recommendations": [{
                "rule_id": "R-main-push",
                "occurrence_ids": ["O-one"],
                "summary": "禁止直接 push main",
                "canonical": {
                    "target": "agents_md",
                    "path": "/repo/AGENTS.md",
                },
                "delivery": [],
                "enforcement": [{
                    "mode": "block",
                    "platform": "claude",
                    "event": "PreToolUse",
                    "matcher": "Bash",
                    "predicate": "git push targets main",
                }],
                "report_group": "hooks",
                "reason": "动作可在执行前确定性验证",
                "confidence": "high",
                "action": "create",
            }],
            "duplicates": [],
            "conflicts": [],
            "unclassified": [],
        }

    def test_valid_contract_and_report(self):
        inventory = self.inventory()
        recommendations = self.recommendations()
        self.assertEqual(
            validate_recommendations(recommendations, inventory), []
        )
        output = render(recommendations, inventory)
        self.assertIn("Hooks（1）", output)
        self.assertIn("claude / block / PreToolUse / Bash", output)
        self.assertIn("/repo/AGENTS.md:8", output)
        self.assertIn("Path-scoped Rules（0）", output)

    def test_blocking_hook_requires_predicate(self):
        data = self.recommendations()
        del data["recommendations"][0]["enforcement"][0]["predicate"]
        errors = validate_recommendations(data, self.inventory())
        self.assertTrue(any("requires 'predicate'" in error for error in errors))

    def test_reminder_hook_requires_event_and_matcher(self):
        data = self.recommendations()
        enforcement = data["recommendations"][0]["enforcement"][0]
        enforcement["mode"] = "remind"
        del enforcement["predicate"]
        del enforcement["matcher"]
        errors = validate_recommendations(data, self.inventory())
        self.assertTrue(any("requires 'matcher'" in error for error in errors))

    def test_every_occurrence_must_be_covered(self):
        data = self.recommendations()
        data["recommendations"] = []
        errors = validate_recommendations(data, self.inventory())
        self.assertTrue(any("uncovered occurrences" in error for error in errors))

    def test_tampered_inventory_is_rejected(self):
        inventory = self.inventory()
        inventory["rule_candidates"][0]["text_hash"] = "changed"
        errors = validate_recommendations(
            self.recommendations(), inventory
        )
        self.assertTrue(any("fingerprint does not match" in error for error in errors))

    def test_project_root_must_match(self):
        data = self.recommendations()
        data["project_root"] = "/different"
        errors = validate_recommendations(data, self.inventory())
        self.assertTrue(any("project_root mismatch" in error for error in errors))

    def test_relationship_must_be_an_object(self):
        data = self.recommendations()
        data["duplicates"] = ["not-an-object"]
        errors = validate_recommendations(data, self.inventory())
        self.assertTrue(any("duplicates[0]" in error for error in errors))

    def test_path_group_requires_paths(self):
        data = self.recommendations()
        item = data["recommendations"][0]
        item["report_group"] = "path_rules"
        item["enforcement"] = []
        item["canonical"] = {"target": "path_rule", "path": ".claude/rules/x.md"}
        errors = validate_recommendations(data, self.inventory())
        self.assertTrue(any("requires non-empty paths" in error for error in errors))

    def test_unclassified_report_shows_text_and_source(self):
        inventory = self.inventory()
        data = self.recommendations()
        data["recommendations"] = []
        data["unclassified"] = [{
            "occurrence_ids": ["O-one"],
            "reason": "需要确认作用域",
            "confidence": "low",
        }]
        output = render(data, inventory)
        self.assertIn("禁止直接 push main", output)
        self.assertIn("/repo/AGENTS.md:8", output)

    def test_unclassified_occurrence_ids_must_be_strings(self):
        data = self.recommendations()
        data["recommendations"] = []
        data["unclassified"] = [{
            "occurrence_ids": [1],
            "reason": "invalid fixture",
            "confidence": "low",
        }]
        errors = validate_recommendations(data, self.inventory())
        self.assertTrue(any("must be non-empty strings" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
