#!/usr/bin/env python3
"""Validate the compact rules-architect recommendation contract.

This module is the single executable source of truth for the report format.
Use ``--example`` to print a valid skeleton for the main agent.
"""
import argparse
import json
import sys
from pathlib import Path

try:
    from .rule_inventory import compute_inventory_fingerprint
except (ImportError, ValueError):
    from rule_inventory import compute_inventory_fingerprint


SCHEMA_VERSION = "1.1"
SUPPORTED_SCHEMA_VERSIONS = {"1.0", "1.1"}
GROUPS = {"hooks", "path_rules", "team_baseline", "memory", "lessons"}
TARGETS = {
    "agents_md", "claude_md", "path_rule", "memory", "lessons", "existing"
}
ACTIONS = {
    "keep", "reuse", "move", "create", "update", "disable", "delete",
    "review",
}
CONFIDENCE = {"high", "medium", "low"}
ENFORCEMENT_MODES = {"block", "remind"}
OPERATION_ACTIONS = {"create", "update", "disable", "delete"}


def require_type(errors, obj, key, expected, where):
    if key not in obj:
        errors.append("{}：缺少 '{}'".format(where, key))
        return None
    value = obj[key]
    if not isinstance(value, expected):
        errors.append("{}：'{}' 类型错误".format(where, key))
        return None
    return value


def require_nonempty_strings(errors, values, where):
    if not values:
        errors.append("{}：至少需要一个出现位置 ID".format(where))
        return []
    valid = []
    for value in values:
        if not isinstance(value, str) or not value:
            errors.append("{}：出现位置 ID 必须是非空字符串".format(where))
        else:
            valid.append(value)
    return valid


def validate_inventory(data):
    errors = []
    if not isinstance(data, dict):
        return ["inventory：根节点必须是对象"]
    if data.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append("inventory：不支持该 schema_version")
    fingerprint = require_type(
        errors, data, "inventory_fingerprint", str, "inventory"
    )
    required_lists = [
        "sources", "rule_candidates", "hook_registrations",
        "source_errors", "skipped_sources",
    ]
    if data.get("schema_version") == "1.1":
        required_lists.extend(["hook_artifacts", "path_rule_artifacts"])
    for key in required_lists:
        require_type(errors, data, key, list, "inventory")
    seen = set()
    for idx, source in enumerate(data.get("sources", [])):
        where = "sources[{}]".format(idx)
        if not isinstance(source, dict):
            errors.append("{}：必须是对象".format(where))
            continue
        for key in ("path", "content_hash", "kind"):
            require_type(errors, source, key, str, where)
    for idx, candidate in enumerate(data.get("rule_candidates", [])):
        where = "rule_candidates[{}]".format(idx)
        if not isinstance(candidate, dict):
            errors.append("{}：必须是对象".format(where))
            continue
        occurrence_id = require_type(
            errors, candidate, "occurrence_id", str, where
        )
        for key in ("text", "text_hash", "source_path"):
            require_type(errors, candidate, key, str, where)
        if occurrence_id:
            if occurrence_id in seen:
                errors.append("{}：occurrence_id 重复".format(where))
            seen.add(occurrence_id)
    if fingerprint and not errors:
        if compute_inventory_fingerprint(data) != fingerprint:
            errors.append("inventory：指纹与内容不匹配")
    return errors


def validate_delivery(errors, delivery, where):
    for idx, adapter in enumerate(delivery):
        adapter_where = "{}[{}]".format(where, idx)
        if not isinstance(adapter, dict):
            errors.append("{}：必须是对象".format(adapter_where))
            continue
        require_type(errors, adapter, "type", str, adapter_where)
        if "paths" in adapter:
            paths = adapter["paths"]
            if not isinstance(paths, list) or not paths or not all(
                isinstance(path, str) and path for path in paths
            ):
                errors.append(
                    "{}：paths 必须是非空字符串列表".format(
                        adapter_where
                    )
                )


def validate_enforcement(errors, enforcement, where):
    for idx, adapter in enumerate(enforcement):
        adapter_where = "{}[{}]".format(where, idx)
        if not isinstance(adapter, dict):
            errors.append("{}：必须是对象".format(adapter_where))
            continue
        if adapter.get("mode") not in ENFORCEMENT_MODES:
            errors.append("{}：mode 无效".format(adapter_where))
        require_type(errors, adapter, "platform", str, adapter_where)
        for field in ("event", "matcher"):
            if not isinstance(adapter.get(field), str) or not adapter[field]:
                errors.append(
                    "{}：Hook 强制规则需要 '{}'".format(
                        adapter_where, field
                    )
                )
        if adapter.get("mode") == "block":
            if (
                not isinstance(adapter.get("predicate"), str)
                or not adapter["predicate"]
            ):
                errors.append(
                    "{}：阻断型 Hook 需要 'predicate'".format(
                        adapter_where
                    )
                )


def validate_relationships(errors, data, key, known_occurrences):
    if key not in data:
        errors.append("recommendations：缺少 '{}'".format(key))
        return
    relationships = data.get(key, [])
    if not isinstance(relationships, list):
        errors.append("recommendations：'{}' 类型错误".format(key))
        return
    for idx, item in enumerate(relationships):
        where = "{}[{}]".format(key, idx)
        if not isinstance(item, dict):
            errors.append("{}：必须是对象".format(where))
            continue
        require_type(errors, item, "relation_id", str, where)
        require_type(errors, item, "summary", str, where)
        occurrences = require_type(
            errors, item, "occurrence_ids", list, where
        )
        if occurrences is not None:
            valid = require_nonempty_strings(errors, occurrences, where)
            if len(valid) < 2:
                errors.append("{}：至少需要两个出现位置".format(where))
            unknown = set(valid) - known_occurrences
            if unknown:
                errors.append(
                    "{}：未知出现位置：{}".format(
                        where, ", ".join(sorted(unknown))
                    )
                )
        if item.get("confidence") not in CONFIDENCE:
            errors.append("{}：confidence 无效".format(where))


def validate_operations(errors, operations, inventory):
    known_artifacts = {
        item.get("artifact_id"): item
        for item in (
            (inventory or {}).get("hook_artifacts", [])
            + (inventory or {}).get("path_rule_artifacts", [])
        )
        if isinstance(item, dict) and item.get("artifact_id")
    }
    operation_ids = set()
    for idx, operation in enumerate(operations):
        where = "operations[{}]".format(idx)
        if not isinstance(operation, dict):
            errors.append("{}：必须是对象".format(where))
            continue
        operation_id = require_type(
            errors, operation, "operation_id", str, where
        )
        action = operation.get("action")
        if action not in OPERATION_ACTIONS:
            errors.append("{}：action 无效".format(where))
        require_type(errors, operation, "reason", str, where)
        requires_confirmation = require_type(
            errors, operation, "requires_confirmation", bool, where
        )
        if action in {"update", "disable", "delete"} and not requires_confirmation:
            errors.append("{}：修改、禁用和删除必须要求确认".format(where))
        artifact_id = operation.get("artifact_id")
        if action in {"update", "disable", "delete"}:
            if not isinstance(artifact_id, str) or not artifact_id:
                errors.append("{}：该动作必须提供 artifact_id".format(where))
            elif inventory is not None and artifact_id not in known_artifacts:
                errors.append("{}：引用了未知 artifact_id".format(where))
            elif inventory is not None:
                artifact = known_artifacts[artifact_id]
                if artifact.get("ownership") != "rules_architect":
                    errors.append("{}：不得修改外部或未知所有权产物".format(where))
                if artifact.get("modified_since_managed"):
                    errors.append("{}：本地修改过的托管产物只能进入 review".format(where))
                if not artifact.get("safe_to_modify"):
                    errors.append("{}：该产物不满足安全修改条件".format(where))
                if artifact.get("kind") == "path_rule" and action == "disable":
                    errors.append("{}：路径规则不支持 disable，请使用 update、delete 或 review".format(where))
        if action in {"create", "update"}:
            require_type(errors, operation, "path", str, where)
            require_type(errors, operation, "content", str, where)
        if action in {"update", "delete"}:
            require_type(errors, operation, "expected_hash", str, where)
        registration = operation.get("registration")
        if registration is not None and not isinstance(registration, dict):
            errors.append("{}：registration 必须是对象".format(where))
        elif isinstance(registration, dict):
            for field in ("config_path", "event", "matcher", "command"):
                require_type(errors, registration, field, str, where + ".registration")
        if operation_id:
            if operation_id in operation_ids:
                errors.append("{}：operation_id 重复".format(where))
            operation_ids.add(operation_id)


def validate_artifact_decisions(errors, decisions, inventory, required=False):
    artifacts = {
        item.get("artifact_id"): item
        for item in (
            (inventory or {}).get("hook_artifacts", [])
            + (inventory or {}).get("path_rule_artifacts", [])
        )
        if isinstance(item, dict) and item.get("artifact_id")
    }
    seen = set()
    for idx, decision in enumerate(decisions):
        where = "artifact_decisions[{}]".format(idx)
        if not isinstance(decision, dict):
            errors.append("{}：必须是对象".format(where))
            continue
        artifact_id = require_type(errors, decision, "artifact_id", str, where)
        action = decision.get("action")
        if action not in ACTIONS - {"move", "create"}:
            errors.append("{}：action 无效".format(where))
        require_type(errors, decision, "reason", str, where)
        if decision.get("confidence") not in CONFIDENCE:
            errors.append("{}：confidence 无效".format(where))
        if artifact_id:
            if artifact_id in seen:
                errors.append("{}：artifact_id 重复".format(where))
            seen.add(artifact_id)
            artifact = artifacts.get(artifact_id)
            if inventory is not None and artifact is None:
                errors.append("{}：引用了未知 artifact_id".format(where))
            elif artifact is not None:
                if artifact.get("ownership") != "rules_architect" and action not in {
                    "keep", "reuse", "review"
                }:
                    errors.append("{}：外部或未知产物只能保留、复用或复核".format(where))
                if artifact.get("modified_since_managed") and action != "review":
                    errors.append("{}：本地修改过的托管产物只能进入 review".format(where))
                if action in {"update", "disable", "delete"} and not artifact.get("safe_to_modify"):
                    errors.append("{}：该产物不满足安全修改条件".format(where))
                if artifact.get("kind") == "path_rule" and action == "disable":
                    errors.append("{}：路径规则不支持 disable，请使用 update、delete 或 review".format(where))
    if required and inventory is not None:
        missing = set(artifacts) - seen
        if missing:
            errors.append(
                "artifact_decisions：尚未决策的规则产物：{}".format(
                    ", ".join(sorted(missing))
                )
            )


def validate_recommendations(data, inventory=None):
    errors = []
    if not isinstance(data, dict):
        return ["recommendations：根节点必须是对象"]
    if data.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append("recommendations：不支持该 schema_version")
    require_type(
        errors, data, "inventory_fingerprint", str, "recommendations"
    )
    require_type(errors, data, "project_root", str, "recommendations")
    recommendations = require_type(
        errors, data, "recommendations", list, "recommendations"
    ) or []
    unclassified = require_type(
        errors, data, "unclassified", list, "recommendations"
    ) or []
    operations = data.get("operations", [])
    if not isinstance(operations, list):
        errors.append("recommendations：'operations' 类型错误")
        operations = []
    artifact_decisions = data.get("artifact_decisions", [])
    if not isinstance(artifact_decisions, list):
        errors.append("recommendations：'artifact_decisions' 类型错误")
        artifact_decisions = []

    known_occurrences = set()
    known_artifacts = set()
    if inventory is not None:
        errors.extend(validate_inventory(inventory))
        known_occurrences = {
            candidate.get("occurrence_id")
            for candidate in inventory.get("rule_candidates", [])
            if candidate.get("occurrence_id")
        }
        known_artifacts = {
            artifact.get("artifact_id")
            for artifact in (
                inventory.get("hook_artifacts", [])
                + inventory.get("path_rule_artifacts", [])
            )
            if isinstance(artifact, dict) and artifact.get("artifact_id")
        }
        if data.get("inventory_fingerprint") != inventory.get(
            "inventory_fingerprint"
        ):
            errors.append("recommendations：inventory 指纹不匹配")
        try:
            recommendation_root = str(Path(data.get("project_root", "")).resolve())
            inventory_root = str(Path(inventory.get("project_root", "")).resolve())
            if recommendation_root != inventory_root:
                errors.append("recommendations：project_root 不匹配")
        except (OSError, TypeError):
            errors.append("recommendations：project_root 无效")

    rule_ids = set()
    covered = set()
    for idx, item in enumerate(recommendations):
        where = "recommendations[{}]".format(idx)
        if not isinstance(item, dict):
            errors.append("{}：必须是对象".format(where))
            continue
        rule_id = require_type(errors, item, "rule_id", str, where)
        occurrences = require_type(
            errors, item, "occurrence_ids", list, where
        )
        valid_occurrences = require_nonempty_strings(
            errors, occurrences or [], where
        )
        require_type(errors, item, "summary", str, where)
        require_type(errors, item, "reason", str, where)
        canonical = require_type(errors, item, "canonical", dict, where) or {}
        require_type(errors, canonical, "path", str, where + ".canonical")
        if canonical.get("target") not in TARGETS:
            errors.append("{}：canonical target 无效".format(where))
        delivery = require_type(errors, item, "delivery", list, where) or []
        enforcement = require_type(
            errors, item, "enforcement", list, where
        ) or []
        validate_delivery(errors, delivery, where + ".delivery")
        validate_enforcement(errors, enforcement, where + ".enforcement")
        group = item.get("report_group")
        if group not in GROUPS:
            errors.append("{}：report_group 无效".format(where))
        if item.get("action") not in ACTIONS:
            errors.append("{}：action 无效".format(where))
        if item.get("confidence") not in CONFIDENCE:
            errors.append("{}：confidence 无效".format(where))
        artifact_ids = item.get("artifact_ids", [])
        if not isinstance(artifact_ids, list) or not all(
            isinstance(value, str) and value for value in artifact_ids
        ):
            errors.append("{}：artifact_ids 必须是字符串列表".format(where))
            artifact_ids = []
        unknown_artifacts = set(artifact_ids) - known_artifacts
        if inventory is not None and unknown_artifacts:
            errors.append(
                "{}：引用了未知 artifact_id：{}".format(
                    where, ", ".join(sorted(unknown_artifacts))
                )
            )
        if item.get("action") in {"reuse", "update", "disable", "delete"} \
                and not artifact_ids:
            errors.append("{}：该动作必须引用 artifact_ids".format(where))
        if group == "hooks" and not enforcement:
            errors.append("{}：hooks 分组必须包含 enforcement".format(where))
        if group == "path_rules" and not any(
            isinstance(adapter, dict) and adapter.get("paths")
            for adapter in delivery
        ):
            errors.append(
                "{}：path_rules 分组必须包含非空 paths".format(where)
            )
        if rule_id:
            if rule_id in rule_ids:
                errors.append("{}：rule_id 重复".format(where))
            rule_ids.add(rule_id)
        for occurrence_id in valid_occurrences:
            if occurrence_id in covered:
                errors.append(
                    "{}：出现位置 '{}' 被重复归类".format(
                        where, occurrence_id
                    )
                )
            covered.add(occurrence_id)

    for idx, item in enumerate(unclassified):
        where = "unclassified[{}]".format(idx)
        if not isinstance(item, dict):
            errors.append("{}：必须是对象".format(where))
            continue
        occurrences = require_type(
            errors, item, "occurrence_ids", list, where
        )
        valid_occurrences = require_nonempty_strings(
            errors, occurrences or [], where
        )
        require_type(errors, item, "reason", str, where)
        if item.get("confidence") not in CONFIDENCE:
            errors.append("{}：confidence 无效".format(where))
        for occurrence_id in valid_occurrences:
            if occurrence_id in covered:
                errors.append(
                    "{}：出现位置 '{}' 被重复归类".format(
                        where, occurrence_id
                    )
                )
            covered.add(occurrence_id)

    validate_relationships(
        errors, data, "duplicates", known_occurrences or covered
    )
    validate_relationships(
        errors, data, "conflicts", known_occurrences or covered
    )
    if inventory is not None:
        unknown = covered - known_occurrences
        missing = known_occurrences - covered
        if unknown:
            errors.append(
                "recommendations：未知出现位置：{}".format(
                    ", ".join(sorted(unknown))
                )
            )
        if missing:
            errors.append(
                "recommendations：尚未归类的出现位置：{}".format(
                    ", ".join(sorted(missing))
                )
            )
    validate_operations(errors, operations, inventory)
    validate_artifact_decisions(
        errors,
        artifact_decisions,
        inventory,
        required=data.get("schema_version") == "1.1",
    )
    return errors


def example_contract():
    return {
        "schema_version": SCHEMA_VERSION,
        "inventory_fingerprint": "<copy from inventory>",
        "project_root": "<copy from inventory>",
        "recommendations": [{
            "rule_id": "R-example",
            "occurrence_ids": ["O-example"],
            "summary": "示例规则",
            "canonical": {"target": "agents_md", "path": "AGENTS.md"},
            "delivery": [],
            "enforcement": [{
                "mode": "remind",
                "platform": "claude",
                "event": "PreToolUse",
                "matcher": "Bash",
            }],
            "report_group": "hooks",
            "reason": "仅作示例",
            "confidence": "medium",
            "action": "review",
            "artifact_ids": [],
        }],
        "operations": [],
        "artifact_decisions": [],
        "duplicates": [],
        "conflicts": [],
        "unclassified": [],
    }


def load_json(path):
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text())


def main():
    parser = argparse.ArgumentParser(description="校验规则分布建议的数据契约")
    parser.add_argument("recommendations", nargs="?", help="建议 JSON 文件")
    parser.add_argument("--inventory", help="规则清单 JSON 文件")
    parser.add_argument("--example", action="store_true", help="输出有效示例")
    args = parser.parse_args()
    if args.example:
        print(json.dumps(example_contract(), ensure_ascii=False, indent=2))
        return 0
    if not args.recommendations:
        parser.error("除非使用 --example，否则必须提供 recommendations")
    try:
        recommendations = load_json(args.recommendations)
        inventory = load_json(args.inventory) if args.inventory else None
    except (OSError, ValueError) as exc:
        print("JSON 无效：{}".format(exc), file=sys.stderr)
        return 2
    errors = validate_recommendations(recommendations, inventory)
    if errors:
        for error in errors:
            print("错误：" + error, file=sys.stderr)
        return 1
    print("建议数据契约：有效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
