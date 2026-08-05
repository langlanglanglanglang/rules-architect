import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from recommendation_contract import enforcement_digest, validate_recommendations
from render_distribution import render
from rule_inventory import compute_inventory_fingerprint


class RecommendationContractTest(unittest.TestCase):
    def occurrence_outcome(
        self, action, group="hooks", mode="block", target="agents_md",
        path="/repo/AGENTS.md", artifact_ids=None, paths=None,
    ):
        enforcement = []
        if group == "hooks":
            adapter = {
                "mode": mode, "platform": "claude", "event": "PreToolUse",
                "matcher": "Bash",
            }
            if mode == "block":
                adapter["predicate"] = "git push targets main"
            enforcement = [adapter]
        return {
            "target_type": "occurrence", "target_id": "O-one",
            "action": action, "canonical_target": target,
            "canonical_path": path, "report_group": group,
            "artifact_ids": list(artifact_ids or []),
            "paths": list(paths or []), "enforcement": enforcement,
        }

    def automatic_hook_operation(self, operation_id="OP-create", rule_id="R-main-push"):
        adapter = {
            "mode": "block", "platform": "claude", "event": "PreToolUse",
            "matcher": "Bash", "predicate": "git push targets main",
        }
        path = "/repo/.claude/hooks/main.py"
        return {
            "operation_id": operation_id, "rule_id": rule_id,
            "action": "create", "path": path,
            "content": (
                "# rules-architect-id: {}\n"
                "# rules-architect-enforcement: {}\n"
                "def main():\n    return 0\n"
            ).format(rule_id, enforcement_digest(adapter)),
            "reason": "创建阻断 Hook", "requires_confirmation": False,
            "registrations": [{
                "platform": "claude", "config_path": "/repo/.claude/settings.json",
                "event": "PreToolUse", "matcher": "Bash",
                "command": "python3 {}".format(path),
            }],
        }

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
        self.assertIn("Hook 强制规则（1）", output)
        self.assertIn("claude / 阻断 / PreToolUse / Bash", output)
        self.assertIn("/repo/AGENTS.md:8", output)
        self.assertIn("路径规则（0）", output)

    def test_blocking_hook_requires_predicate(self):
        data = self.recommendations()
        del data["recommendations"][0]["enforcement"][0]["predicate"]
        errors = validate_recommendations(data, self.inventory())
        self.assertTrue(any("需要 'predicate'" in error for error in errors))

    def test_reminder_hook_requires_event_and_matcher(self):
        data = self.recommendations()
        enforcement = data["recommendations"][0]["enforcement"][0]
        enforcement["mode"] = "remind"
        del enforcement["predicate"]
        del enforcement["matcher"]
        errors = validate_recommendations(data, self.inventory())
        self.assertTrue(any("需要 'matcher'" in error for error in errors))

    def test_every_occurrence_must_be_covered(self):
        data = self.recommendations()
        data["recommendations"] = []
        errors = validate_recommendations(data, self.inventory())
        self.assertTrue(any("尚未归类的出现位置" in error for error in errors))

    def test_tampered_inventory_is_rejected(self):
        inventory = self.inventory()
        inventory["rule_candidates"][0]["text_hash"] = "changed"
        errors = validate_recommendations(
            self.recommendations(), inventory
        )
        self.assertTrue(any("指纹与内容不匹配" in error for error in errors))

    def test_project_root_must_match(self):
        data = self.recommendations()
        data["project_root"] = "/different"
        errors = validate_recommendations(data, self.inventory())
        self.assertTrue(any("project_root 不匹配" in error for error in errors))

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
        self.assertTrue(any("必须包含非空 paths" in error for error in errors))

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
        self.assertTrue(any("必须是非空字符串" in error for error in errors))

    def test_schema_11_requires_decision_for_every_hook_artifact(self):
        inventory = self.inventory()
        inventory["schema_version"] = "1.1"
        inventory["hook_artifacts"] = [{
            "artifact_id": "H-external", "path": "/repo/external.py",
            "status": "orphan", "ownership": "external_tool",
            "registrations": [], "content_hash": "c" * 64,
        }]
        inventory["path_rule_artifacts"] = []
        inventory["inventory_fingerprint"] = compute_inventory_fingerprint(inventory)
        data = self.recommendations()
        data["schema_version"] = "1.1"
        data["inventory_fingerprint"] = inventory["inventory_fingerprint"]
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("尚未决策的规则产物" in error for error in errors))
        data["artifact_decisions"] = [{
            "artifact_id": "H-external", "action": "delete",
            "reason": "误判", "confidence": "low",
        }]
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("只能保留、复用或复核" in error for error in errors))
        data["artifact_decisions"][0]["action"] = "reuse"
        data["operations"] = [{
            "operation_id": "OP-delete-external", "action": "delete",
            "artifact_id": "H-external", "expected_hash": "c" * 64,
            "reason": "不应允许", "requires_confirmation": True,
        }]
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("不得修改外部或未知所有权产物" in error for error in errors))

    def schema_12_inventory(self):
        inventory = self.inventory()
        inventory["schema_version"] = "1.1"
        inventory["hook_artifacts"] = []
        inventory["path_rule_artifacts"] = []
        inventory["inventory_fingerprint"] = compute_inventory_fingerprint(inventory)
        return inventory

    def test_confirmation_stage_precedes_final_recommendations(self):
        inventory = self.schema_12_inventory()
        data = {
            "schema_version": "1.2",
            "plan_status": "needs_confirmation",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "project_root": "/repo",
            "recommendations": [],
            "artifact_decisions": [],
            "operations": [],
            "resolved_occurrence_ids": [],
            "resolved_artifact_ids": [],
            "clarifications": [{
                "clarification_id": "C01",
                "summary": "确认 push 规则的执行方式",
                "question": "需要阻断还是仅提醒？",
                "occurrence_ids": ["O-one"],
                "artifact_ids": [],
                "options": [
                    {"option_id": "block", "label": "阻断", "outcomes": [
                        self.occurrence_outcome("create")
                    ]},
                    {"option_id": "keep", "label": "保持不变", "outcomes": [
                        self.occurrence_outcome("keep")
                    ]},
                ],
                "selected_option_id": None,
            }],
            "duplicates": [], "conflicts": [], "unclassified": [],
        }
        self.assertEqual(validate_recommendations(data, inventory), [])
        output = render(data, inventory)
        self.assertIn("扫描结果与前置确认", output)
        self.assertIn("需要确认（1 项未确认）", output)
        self.assertNotIn("最终规则推荐方案", output)
        self.assertNotIn("执行全部可安全应用项", output)

        data["operations"] = [{
            "operation_id": "OP-invalid", "action": "create",
            "path": "/repo/.claude/hooks/x.py", "content": "x",
            "reason": "不应提前生成", "requires_confirmation": False,
        }]
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("确认完成前不得生成待应用操作" in error for error in errors))

    def test_ready_plan_forbids_review_and_shows_execution_menu(self):
        inventory = self.schema_12_inventory()
        data = self.recommendations()
        data.update({
            "schema_version": "1.2", "plan_status": "ready",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "clarifications": [], "resolved_occurrence_ids": [],
            "resolved_artifact_ids": [],
            "artifact_decisions": [], "operations": [],
        })
        data["recommendations"][0]["decision_source"] = "inferred"
        data["recommendations"][0]["action"] = "keep"
        data["recommendations"][0]["execution_mode"] = "none"
        data["recommendations"][0]["operation_ids"] = []
        self.assertEqual(validate_recommendations(data, inventory), [])
        output = render(data, inventory)
        self.assertIn("最终规则推荐方案", output)
        self.assertIn("当前没有可安全应用的自动操作", output)
        self.assertNotIn("1. 执行全部可安全应用项", output)
        self.assertNotIn("待确认（", output)

        data["recommendations"][0]["action"] = "review"
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("action 无效" in error for error in errors))

    def test_resolved_clarification_requires_user_confirmation_marker(self):
        inventory = self.schema_12_inventory()
        data = self.recommendations()
        data.update({
            "schema_version": "1.2", "plan_status": "ready",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "artifact_decisions": [], "resolved_occurrence_ids": [],
            "resolved_artifact_ids": [],
            "operations": [self.automatic_hook_operation()],
            "clarifications": [{
                "clarification_id": "C01", "summary": "确认执行方式",
                "question": "是否创建阻断 Hook？",
                "occurrence_ids": ["O-one"], "artifact_ids": [],
                "options": [
                    {"option_id": "create", "label": "创建", "outcomes": [
                        self.occurrence_outcome("create")
                    ]},
                    {"option_id": "keep", "label": "保持", "outcomes": [
                        self.occurrence_outcome("keep")
                    ]},
                ],
                "selected_option_id": "create",
                "decision_source": "user_confirmed",
            }],
        })
        data["recommendations"][0]["decision_source"] = "user_confirmed"
        data["recommendations"][0]["execution_mode"] = "automatic"
        data["recommendations"][0]["operation_ids"] = ["OP-create"]
        self.assertEqual(validate_recommendations(data, inventory), [])
        del data["clarifications"][0]["decision_source"]
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("user_confirmed" in error for error in errors))
        data["clarifications"][0]["decision_source"] = "user_confirmed"
        data["recommendations"][0]["action"] = "keep"
        data["recommendations"][0]["execution_mode"] = "none"
        data["recommendations"][0]["operation_ids"] = []
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("用户选择的 action 未落实" in error for error in errors))

    def test_confirmation_stage_must_cover_every_occurrence(self):
        inventory = self.schema_12_inventory()
        second = dict(inventory["rule_candidates"][0])
        second.update({
            "occurrence_id": "O-two", "text": "提交前运行测试",
            "text_hash": "d" * 64, "line_start": 9,
        })
        inventory["rule_candidates"].append(second)
        inventory["inventory_fingerprint"] = compute_inventory_fingerprint(inventory)
        data = {
            "schema_version": "1.2", "plan_status": "needs_confirmation",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "project_root": "/repo", "recommendations": [],
            "artifact_decisions": [], "operations": [],
            "resolved_occurrence_ids": [], "resolved_artifact_ids": [],
            "duplicates": [], "conflicts": [],
            "unclassified": [],
            "clarifications": [{
                "clarification_id": "C01", "summary": "确认第一条",
                "question": "如何处理？", "occurrence_ids": ["O-one"],
                "artifact_ids": [], "selected_option_id": None,
                "options": [
                    {"option_id": "keep", "label": "保留", "outcomes": [
                        self.occurrence_outcome("keep", group="team_baseline")
                    ]},
                    {"option_id": "hook", "label": "创建 Hook", "outcomes": [
                        self.occurrence_outcome("create")
                    ]},
                ],
            }],
        }
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("前置阶段遗漏出现位置：O-two" in error for error in errors))
        data["resolved_occurrence_ids"] = ["O-two"]
        self.assertEqual(validate_recommendations(data, inventory), [])

    def test_confirmation_stage_must_cover_every_artifact(self):
        inventory = self.schema_12_inventory()
        inventory["hook_artifacts"] = [{
            "artifact_id": "H-external", "kind": "hook",
            "path": "/repo/external.sh", "status": "orphan",
            "ownership": "external_tool", "safe_to_modify": False,
            "modified_since_managed": False, "registrations": [],
            "content_hash": "c" * 64,
        }]
        inventory["inventory_fingerprint"] = compute_inventory_fingerprint(inventory)
        data = {
            "schema_version": "1.2", "plan_status": "needs_confirmation",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "project_root": "/repo", "recommendations": [],
            "artifact_decisions": [], "operations": [],
            "resolved_occurrence_ids": ["O-one"], "resolved_artifact_ids": [],
            "duplicates": [], "conflicts": [], "unclassified": [],
            "clarifications": [{
                "clarification_id": "C01", "summary": "确认外部 Hook",
                "question": "保留还是复用？", "occurrence_ids": [],
                "artifact_ids": ["H-external"], "selected_option_id": None,
                "options": [
                    {"option_id": "keep", "label": "保留", "outcomes": [{
                        "target_type": "artifact", "target_id": "H-external",
                        "action": "keep",
                    }]},
                    {"option_id": "reuse", "label": "复用", "outcomes": [{
                        "target_type": "artifact", "target_id": "H-external",
                        "action": "reuse",
                    }]},
                ],
            }],
        }
        self.assertEqual(validate_recommendations(data, inventory), [])
        data["clarifications"][0]["artifact_ids"] = []
        data["clarifications"][0]["occurrence_ids"] = ["O-one"]
        data["resolved_occurrence_ids"] = []
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("前置阶段遗漏规则产物：H-external" in error for error in errors))

    def test_ready_plan_rejects_semantic_clarification_mismatch(self):
        inventory = self.schema_12_inventory()
        data = self.recommendations()
        data.update({
            "schema_version": "1.2", "plan_status": "ready",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "resolved_occurrence_ids": [], "resolved_artifact_ids": [],
            "artifact_decisions": [],
            "operations": [self.automatic_hook_operation()],
            "clarifications": [{
                "clarification_id": "C01", "summary": "选择强制方式",
                "question": "阻断还是提醒？", "occurrence_ids": ["O-one"],
                "artifact_ids": [], "selected_option_id": "remind",
                "decision_source": "user_confirmed",
                "options": [
                    {"option_id": "remind", "label": "提醒", "outcomes": [
                        self.occurrence_outcome("create", mode="remind")
                    ]},
                    {"option_id": "block", "label": "阻断", "outcomes": [
                        self.occurrence_outcome("create")
                    ]},
                ],
            }],
        })
        data["recommendations"][0].update({
            "decision_source": "user_confirmed", "execution_mode": "automatic",
            "operation_ids": ["OP-create"]
        })
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("enforcement 未落实" in error for error in errors))

    def test_ready_plan_rejects_unlinked_or_conflicting_operations(self):
        inventory = self.schema_12_inventory()
        data = self.recommendations()
        data.update({
            "schema_version": "1.2", "plan_status": "ready",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "resolved_occurrence_ids": [], "resolved_artifact_ids": [],
            "clarifications": [],
            "artifact_decisions": [], "operations": [],
        })
        data["recommendations"][0].update({
            "decision_source": "inferred", "execution_mode": "automatic",
            "operation_ids": []
        })
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("变更结论必须绑定可执行操作" in error for error in errors))

        data["operations"] = [self.automatic_hook_operation()]
        data["recommendations"][0]["operation_ids"] = ["OP-create"]
        self.assertEqual(validate_recommendations(data, inventory), [])

    def test_ready_plan_rejects_low_confidence_relationship(self):
        inventory = self.schema_12_inventory()
        data = self.recommendations()
        data.update({
            "schema_version": "1.2", "plan_status": "ready",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "resolved_occurrence_ids": [], "resolved_artifact_ids": [],
            "clarifications": [],
            "artifact_decisions": [], "operations": [],
        })
        data["recommendations"][0].update({
            "action": "keep", "decision_source": "existing_state",
            "execution_mode": "none", "operation_ids": [],
        })
        data["conflicts"] = [{
            "relation_id": "C-low", "summary": "仍不确定",
            "occurrence_ids": ["O-one", "O-one"], "confidence": "low",
        }]
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("最终方案不得保留低置信度关系" in error for error in errors))

    def test_artifact_keep_cannot_hide_delete_operation(self):
        inventory = self.schema_12_inventory()
        inventory["hook_artifacts"] = [{
            "artifact_id": "H-managed", "kind": "hook",
            "path": "/repo/.claude/hooks/managed.py", "status": "active",
            "ownership": "rules_architect", "safe_to_modify": True,
            "modified_since_managed": False, "registrations": [],
            "content_hash": "c" * 64,
        }]
        inventory["inventory_fingerprint"] = compute_inventory_fingerprint(inventory)
        data = self.recommendations()
        data.update({
            "schema_version": "1.2", "plan_status": "ready",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "resolved_occurrence_ids": [], "resolved_artifact_ids": [],
            "clarifications": [],
            "operations": [{
                "operation_id": "OP-delete", "action": "delete",
                "artifact_id": "H-managed", "expected_hash": "c" * 64,
                "reason": "删除", "requires_confirmation": True,
            }],
            "artifact_decisions": [{
                "artifact_id": "H-managed", "action": "keep",
                "reason": "保留", "confidence": "high",
                "decision_source": "existing_state",
                "operation_ids": ["OP-delete"],
            }],
        })
        data["recommendations"][0].update({
            "action": "keep", "decision_source": "existing_state",
            "execution_mode": "none", "artifact_ids": [], "operation_ids": [],
        })
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("非自动结论不得绑定写操作" in error for error in errors))

    def test_expected_hash_must_be_real_sha256(self):
        inventory = self.schema_12_inventory()
        inventory["hook_artifacts"] = [{
            "artifact_id": "H-managed", "kind": "hook",
            "path": "/repo/.claude/hooks/managed.py", "status": "active",
            "ownership": "rules_architect", "safe_to_modify": True,
            "modified_since_managed": False, "registrations": [],
            "content_hash": "c" * 64,
        }]
        inventory["inventory_fingerprint"] = compute_inventory_fingerprint(inventory)
        data = self.recommendations()
        data.update({
            "schema_version": "1.2", "plan_status": "ready",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "resolved_occurrence_ids": [], "resolved_artifact_ids": [],
            "clarifications": [],
            "operations": [{
                "operation_id": "OP-delete", "action": "delete",
                "artifact_id": "H-managed", "expected_hash": "",
                "reason": "删除", "requires_confirmation": True,
                "registrations": [],
            }],
            "artifact_decisions": [{
                "artifact_id": "H-managed", "action": "delete", "reason": "删除",
                "confidence": "high", "decision_source": "existing_state",
                "operation_ids": ["OP-delete"],
            }],
        })
        data["recommendations"][0].update({
            "action": "keep", "execution_mode": "none",
            "decision_source": "existing_state", "operation_ids": [],
        })
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("64 位小写 SHA-256" in error for error in errors))

    def test_manual_move_has_no_automatic_operations(self):
        inventory = self.schema_12_inventory()
        data = self.recommendations()
        data.update({
            "schema_version": "1.2", "plan_status": "ready",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "resolved_occurrence_ids": [], "resolved_artifact_ids": [],
            "clarifications": [], "operations": [], "artifact_decisions": [],
        })
        data["recommendations"][0].update({
            "action": "move", "execution_mode": "manual",
            "decision_source": "inferred", "operation_ids": [],
        })
        self.assertEqual(validate_recommendations(data, inventory), [])
        data["recommendations"][0]["execution_mode"] = "automatic"
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("move 当前只允许 manual" in error for error in errors))

    def test_automatic_hook_requires_registration_and_bound_content(self):
        inventory = self.schema_12_inventory()
        data = self.recommendations()
        data.update({
            "schema_version": "1.2", "plan_status": "ready",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "resolved_occurrence_ids": [], "resolved_artifact_ids": [],
            "clarifications": [], "artifact_decisions": [],
            "operations": [self.automatic_hook_operation()],
        })
        data["recommendations"][0].update({
            "execution_mode": "automatic", "decision_source": "inferred",
            "operation_ids": ["OP-create"],
        })
        data["operations"][0]["registrations"] = []
        data["operations"][0]["content"] = "# empty hook\n"
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("registrations 与 enforcement 不一致" in error for error in errors))
        self.assertTrue(any("缺少受管 rule_id 标记" in error for error in errors))

    def test_clarification_binds_full_enforcement_adapter(self):
        inventory = self.schema_12_inventory()
        data = self.recommendations()
        data.update({
            "schema_version": "1.2", "plan_status": "ready",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "resolved_occurrence_ids": [], "resolved_artifact_ids": [],
            "artifact_decisions": [], "operations": [self.automatic_hook_operation()],
            "clarifications": [{
                "clarification_id": "C-platform", "summary": "选择平台",
                "question": "使用 Claude 还是 Codex？", "occurrence_ids": ["O-one"],
                "artifact_ids": [], "selected_option_id": "claude",
                "decision_source": "user_confirmed",
                "options": [
                    {"option_id": "claude", "label": "Claude", "outcomes": [
                        self.occurrence_outcome("create")
                    ]},
                    {"option_id": "codex", "label": "Codex", "outcomes": [
                        dict(self.occurrence_outcome("create"), enforcement=[{
                            "mode": "block", "platform": "codex",
                            "event": "PreToolUse", "matcher": "apply_patch",
                            "predicate": "git push targets main",
                        }])
                    ]},
                ],
            }],
        })
        data["recommendations"][0].update({
            "execution_mode": "automatic", "decision_source": "user_confirmed",
            "operation_ids": ["OP-create"],
        })
        data["recommendations"][0]["enforcement"][0]["platform"] = "codex"
        errors = validate_recommendations(data, inventory)
        self.assertTrue(any("用户选择的 enforcement 未落实" in error for error in errors))

    def test_scan_section_explains_hook_content_and_registration(self):
        inventory = self.schema_12_inventory()
        inventory["hook_artifacts"] = [{
            "artifact_id": "H-external", "kind": "hook",
            "path": "/repo/.claude/hooks/external.sh", "status": "active",
            "ownership": "external_tool", "safe_to_modify": False,
            "modified_since_managed": False, "registrations": [{
                "platform": "claude", "event": "PreToolUse", "matcher": "Bash",
                "command": "bash /repo/.claude/hooks/external.sh",
                "config_path": "/repo/.claude/settings.json",
            }],
            "content_hash": "c" * 64, "generator": "other-tool",
            "analysis": {
                "mode": "static_reminder", "confidence": "high",
                "reminder": "提交前必须运行测试",
            },
        }]
        inventory["inventory_fingerprint"] = compute_inventory_fingerprint(inventory)
        data = self.recommendations()
        data.update({
            "schema_version": "1.2", "plan_status": "ready",
            "inventory_fingerprint": inventory["inventory_fingerprint"],
            "resolved_occurrence_ids": [], "resolved_artifact_ids": [],
            "clarifications": [], "operations": [],
            "artifact_decisions": [{
                "artifact_id": "H-external", "action": "keep", "reason": "保留外部 Hook",
                "confidence": "high", "decision_source": "existing_state",
                "operation_ids": [],
            }],
        })
        data["recommendations"][0].update({
            "action": "keep", "execution_mode": "none",
            "decision_source": "existing_state", "operation_ids": [],
        })
        output = render(data, inventory)
        self.assertIn("规则：提交前必须运行测试", output)
        self.assertIn("注册：claude / PreToolUse / Bash", output)
        self.assertIn("生成器：other-tool", output)


if __name__ == "__main__":
    unittest.main()
