#!/usr/bin/env python3
"""Validate the compact rules-architect recommendation contract.

This module is the single executable source of truth for the report format.
Use ``--example`` to print a valid skeleton for the main agent.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

try:
    from .rule_inventory import compute_inventory_fingerprint, parse_frontmatter_paths
except (ImportError, ValueError):
    from rule_inventory import compute_inventory_fingerprint, parse_frontmatter_paths


SCHEMA_VERSION = "1.2"
SUPPORTED_INVENTORY_VERSIONS = {"1.0", "1.1"}
SUPPORTED_SCHEMA_VERSIONS = {"1.0", "1.1", "1.2"}
GROUPS = {"hooks", "path_rules", "team_baseline", "memory", "lessons"}
TARGETS = {
    "agents_md", "claude_md", "path_rule", "memory", "lessons", "existing"
}
ACTIONS = {
    "keep", "reuse", "move", "create", "update", "disable", "delete",
    "review",
}
FINAL_ACTIONS = ACTIONS - {"review"}
CONFIDENCE = {"high", "medium", "low"}
DECISION_SOURCES = {"inferred", "user_confirmed", "existing_state"}
PLAN_STATUSES = {"needs_confirmation", "ready"}
ENFORCEMENT_MODES = {"block", "remind"}
OPERATION_ACTIONS = {"create", "update", "disable", "delete"}
MUTATING_ACTIONS = {"move", "create", "update", "disable", "delete"}
ARTIFACT_ACTIONS = {"keep", "reuse", "update", "disable", "delete"}
EXECUTION_MODES = {"automatic", "manual", "none"}
HASH_RE = re.compile(r"^[a-f0-9]{64}$")


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
    if data.get("schema_version") not in SUPPORTED_INVENTORY_VERSIONS:
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
        if not isinstance(adapter.get("event"), str) or not adapter["event"]:
            errors.append("{}：Hook 强制规则需要 'event'".format(adapter_where))
        matcher = adapter.get("matcher")
        matcher_optional = (
            adapter.get("platform") == "codex"
            and adapter.get("event") == "UserPromptSubmit"
        )
        if not matcher_optional and (not isinstance(matcher, str) or not matcher):
            errors.append("{}：Hook 强制规则需要 'matcher'".format(adapter_where))
        elif matcher_optional and matcher is not None \
                and (not isinstance(matcher, str) or not matcher):
            errors.append("{}：matcher 必须为非空字符串或 null".format(adapter_where))
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


def validate_relationships(errors, data, key, known_occurrences, final=False):
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
        elif final and item.get("confidence") == "low":
            errors.append("{}：最终方案不得保留低置信度关系".format(where))


def validate_operations(errors, operations, inventory, schema_12=False):
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
                    errors.append("{}：路径规则不支持 disable，请使用 update、delete 或 keep".format(where))
        if action in {"create", "update"}:
            require_type(errors, operation, "path", str, where)
            require_type(errors, operation, "content", str, where)
        if action in {"update", "delete"}:
            expected_hash = require_type(errors, operation, "expected_hash", str, where)
            if isinstance(expected_hash, str) and not HASH_RE.fullmatch(expected_hash):
                errors.append("{}：expected_hash 必须是 64 位小写 SHA-256".format(where))
        registrations = operation.get("registrations", [])
        if not isinstance(registrations, list):
            errors.append("{}：registrations 必须是列表".format(where))
            registrations = []
        for registration_idx, registration in enumerate(registrations):
            registration_where = "{}.registrations[{}]".format(where, registration_idx)
            if not isinstance(registration, dict):
                errors.append("{}：必须是对象".format(registration_where))
                continue
            for field in ("platform", "config_path", "event", "command"):
                require_type(errors, registration, field, str, registration_where)
            matcher = registration.get("matcher")
            matcher_optional = (
                registration.get("platform") == "codex"
                and registration.get("event") == "UserPromptSubmit"
            )
            if not matcher_optional:
                require_type(errors, registration, "matcher", str, registration_where)
            elif matcher is not None and not isinstance(matcher, str):
                errors.append("{}：matcher 必须为字符串或 null".format(registration_where))
        if schema_12:
            rule_id = operation.get("rule_id")
            if rule_id is not None and (not isinstance(rule_id, str) or not rule_id):
                errors.append("{}：rule_id 必须是非空字符串".format(where))
            if action in {"create", "update"} and not rule_id:
                errors.append("{}：create/update 操作必须绑定 rule_id".format(where))
            if not rule_id and not artifact_id:
                errors.append("{}：操作必须绑定 rule_id 或 artifact_id".format(where))
        if operation_id:
            if operation_id in operation_ids:
                errors.append("{}：operation_id 重复".format(where))
            operation_ids.add(operation_id)


def validate_artifact_decisions(
    errors, decisions, inventory, required=False, final_only=False
):
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
        allowed_actions = (FINAL_ACTIONS if final_only else ACTIONS) - {
            "move", "create"
        }
        if action not in allowed_actions:
            errors.append("{}：action 无效".format(where))
        require_type(errors, decision, "reason", str, where)
        if decision.get("confidence") not in CONFIDENCE:
            errors.append("{}：confidence 无效".format(where))
        if final_only and decision.get("decision_source") not in DECISION_SOURCES:
            errors.append("{}：decision_source 无效".format(where))
        if final_only:
            operation_ids = decision.get("operation_ids")
            if not isinstance(operation_ids, list) or not all(
                isinstance(value, str) and value for value in operation_ids
            ):
                errors.append("{}：operation_ids 必须是字符串列表".format(where))
            if decision.get("confidence") == "low":
                errors.append("{}：最终产物决策不得为低置信度".format(where))
        if artifact_id:
            if artifact_id in seen:
                errors.append("{}：artifact_id 重复".format(where))
            seen.add(artifact_id)
            artifact = artifacts.get(artifact_id)
            if inventory is not None and artifact is None:
                errors.append("{}：引用了未知 artifact_id".format(where))
            elif artifact is not None:
                allowed_external = {"keep", "reuse"}
                if not final_only:
                    allowed_external.add("review")
                if artifact.get("ownership") != "rules_architect" \
                        and action not in allowed_external:
                    message = (
                        "外部或未知产物只能保留或复用"
                        if final_only else
                        "外部或未知产物只能保留、复用或复核"
                    )
                    errors.append("{}：{}".format(where, message))
                if artifact.get("modified_since_managed"):
                    allowed_modified = {"keep", "reuse"} if final_only else {"review"}
                    if action not in allowed_modified:
                        errors.append(
                            "{}：本地修改过的托管产物不能自动变更".format(where)
                        )
                if action in {"update", "disable", "delete"} and not artifact.get("safe_to_modify"):
                    errors.append("{}：该产物不满足安全修改条件".format(where))
                if artifact.get("kind") == "path_rule" and action == "disable":
                    errors.append("{}：路径规则不支持 disable，请使用 update、delete 或 keep".format(where))
    if required and inventory is not None:
        missing = set(artifacts) - seen
        if missing:
            errors.append(
                "artifact_decisions：尚未决策的规则产物：{}".format(
                    ", ".join(sorted(missing))
                )
            )


def validate_outcome(errors, outcome, where, occurrence_ids, artifact_ids):
    if not isinstance(outcome, dict):
        errors.append("{}：必须是对象".format(where))
        return None
    target_type = outcome.get("target_type")
    if target_type not in {"occurrence", "artifact"}:
        errors.append("{}：target_type 无效".format(where))
        return None
    target_id = require_type(errors, outcome, "target_id", str, where)
    allowed_ids = occurrence_ids if target_type == "occurrence" else artifact_ids
    if target_id and target_id not in allowed_ids:
        errors.append("{}：target_id 不属于该确认项".format(where))
    action = outcome.get("action")
    allowed_actions = FINAL_ACTIONS if target_type == "occurrence" else ARTIFACT_ACTIONS
    if action not in allowed_actions:
        errors.append("{}：action 无效".format(where))
    if target_type == "occurrence":
        if outcome.get("canonical_target") not in TARGETS:
            errors.append("{}：canonical_target 无效".format(where))
        if outcome.get("report_group") not in GROUPS:
            errors.append("{}：report_group 无效".format(where))
        canonical_path = require_type(errors, outcome, "canonical_path", str, where)
        if isinstance(canonical_path, str) and not canonical_path:
            errors.append("{}：canonical_path 不能为空".format(where))
        expected_artifacts = require_type(errors, outcome, "artifact_ids", list, where)
        if isinstance(expected_artifacts, list) and not all(
            isinstance(value, str) and value for value in expected_artifacts
        ):
            errors.append("{}：artifact_ids 必须是字符串列表".format(where))
        paths = require_type(errors, outcome, "paths", list, where)
        if isinstance(paths, list) and not all(
            isinstance(value, str) and value for value in paths
        ):
            errors.append("{}：paths 必须是字符串列表".format(where))
        if outcome.get("report_group") == "path_rules" and not paths:
            errors.append("{}：路径规则 outcome 必须包含 paths".format(where))
        enforcement = require_type(errors, outcome, "enforcement", list, where) or []
        validate_enforcement(errors, enforcement, where + ".enforcement")
        if outcome.get("report_group") == "hooks" and not enforcement:
            errors.append("{}：Hook outcome 必须包含 enforcement".format(where))
    return (target_type, target_id) if target_id else None


def validate_clarifications(errors, clarifications, known_occurrences, known_artifacts):
    seen = set()
    unresolved = 0
    covered_occurrences = set()
    covered_artifacts = set()
    seen_targets = set()
    for idx, item in enumerate(clarifications):
        where = "clarifications[{}]".format(idx)
        if not isinstance(item, dict):
            errors.append("{}：必须是对象".format(where))
            continue
        clarification_id = require_type(
            errors, item, "clarification_id", str, where
        )
        require_type(errors, item, "summary", str, where)
        require_type(errors, item, "question", str, where)
        occurrence_ids = item.get("occurrence_ids", [])
        artifact_ids = item.get("artifact_ids", [])
        for field, values, known in (
            ("occurrence_ids", occurrence_ids, known_occurrences),
            ("artifact_ids", artifact_ids, known_artifacts),
        ):
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values
            ):
                errors.append("{}：{} 必须是字符串列表".format(where, field))
                continue
            unknown = set(values) - known
            if unknown:
                errors.append(
                    "{}：{} 引用了未知 ID：{}".format(
                        where, field, ", ".join(sorted(unknown))
                    )
                )
        covered_occurrences.update(
            value for value in occurrence_ids if isinstance(value, str)
        )
        covered_artifacts.update(
            value for value in artifact_ids if isinstance(value, str)
        )
        for target in (
            [("occurrence", value) for value in occurrence_ids]
            + [("artifact", value) for value in artifact_ids]
        ):
            if target in seen_targets:
                errors.append("{}：目标被多个确认项重复引用 {}".format(where, target[1]))
            seen_targets.add(target)
        if not occurrence_ids and not artifact_ids:
            errors.append("{}：必须关联出现位置或规则产物".format(where))
        options = require_type(errors, item, "options", list, where) or []
        option_ids = set()
        if len(options) < 2:
            errors.append("{}：至少需要两个选项".format(where))
        for option_idx, option in enumerate(options):
            option_where = "{}.options[{}]".format(where, option_idx)
            if not isinstance(option, dict):
                errors.append("{}：必须是对象".format(option_where))
                continue
            option_id = require_type(errors, option, "option_id", str, option_where)
            require_type(errors, option, "label", str, option_where)
            outcomes = require_type(errors, option, "outcomes", list, option_where) or []
            outcome_targets = []
            for outcome_idx, outcome in enumerate(outcomes):
                target = validate_outcome(
                    errors, outcome,
                    "{}.outcomes[{}]".format(option_where, outcome_idx),
                    set(occurrence_ids), set(artifact_ids),
                )
                if target:
                    outcome_targets.append(target)
            expected_targets = (
                {("occurrence", value) for value in occurrence_ids}
                | {("artifact", value) for value in artifact_ids}
            )
            if set(outcome_targets) != expected_targets or len(outcome_targets) != len(
                expected_targets
            ):
                errors.append("{}：outcomes 必须逐一覆盖该确认项的全部目标".format(option_where))
            if option_id:
                if option_id in option_ids:
                    errors.append("{}：option_id 重复".format(option_where))
                option_ids.add(option_id)
        selected = item.get("selected_option_id")
        if selected is None:
            unresolved += 1
        elif not isinstance(selected, str) or selected not in option_ids:
            errors.append("{}：selected_option_id 不属于可用选项".format(where))
        elif item.get("decision_source") != "user_confirmed":
            errors.append("{}：已确认项必须标记 decision_source=user_confirmed".format(where))
        if clarification_id:
            if clarification_id in seen:
                errors.append("{}：clarification_id 重复".format(where))
            seen.add(clarification_id)
    return unresolved, covered_occurrences, covered_artifacts


def validate_resolved_outcomes(
    errors, clarifications, recommendations, artifact_decisions
):
    for idx, clarification in enumerate(clarifications):
        selected = clarification.get("selected_option_id")
        if not selected:
            continue
        selected_options = [
            option for option in clarification.get("options", [])
            if option.get("option_id") == selected
        ]
        if not selected_options:
            continue
        where = "clarifications[{}]".format(idx)
        for outcome in selected_options[0].get("outcomes", []):
            target_type = outcome.get("target_type")
            target_id = outcome.get("target_id")
            if target_type == "occurrence":
                matched = [
                    item for item in recommendations
                    if target_id in item.get("occurrence_ids", [])
                ]
                if len(matched) != 1:
                    errors.append("{}：确认目标 {} 没有唯一最终推荐".format(where, target_id))
                    continue
                item = matched[0]
                expected_paths = sorted(outcome.get("paths", []))
                actual_paths = sorted({
                    path for delivery in item.get("delivery", [])
                    for path in delivery.get("paths", [])
                })
                checks = [
                    (item.get("action"), outcome.get("action"), "action"),
                    (item.get("canonical", {}).get("target"), outcome.get("canonical_target"), "canonical_target"),
                    (item.get("report_group"), outcome.get("report_group"), "report_group"),
                    (item.get("canonical", {}).get("path"), outcome.get("canonical_path"), "canonical_path"),
                    (sorted(item.get("artifact_ids", [])), sorted(outcome.get("artifact_ids", [])), "artifact_ids"),
                    (item.get("enforcement", []), outcome.get("enforcement", []), "enforcement"),
                    (actual_paths, expected_paths, "paths"),
                ]
            else:
                matched = [
                    item for item in artifact_decisions
                    if item.get("artifact_id") == target_id
                ]
                if len(matched) != 1:
                    errors.append("{}：确认产物 {} 没有唯一最终决策".format(where, target_id))
                    continue
                item = matched[0]
                checks = [(item.get("action"), outcome.get("action"), "action")]
            for actual, expected, field in checks:
                if actual != expected:
                    errors.append("{}：用户选择的 {} 未落实到目标 {}".format(where, field, target_id))
            if item.get("decision_source") != "user_confirmed":
                errors.append("{}：对应最终结论必须标记 user_confirmed".format(where))


def enforcement_digest(adapter):
    payload = json.dumps(adapter, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def content_has_blocking_behavior(content, adapter):
    """Conservatively reject marker-only/no-op blocking adapters.

    Automatic blockers currently use the Claude/Codex JSON deny protocol.  We
    intentionally require both a deterministic marker and executable-looking
    protocol tokens.  This is a static gate, not execution of generated code.
    """
    digest = enforcement_digest(adapter)
    marker = "rules-architect-blocking: {}".format(digest)
    if marker not in content:
        return False
    code_lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        code_lines.append(stripped)
    code = "\n".join(code_lines)
    emitters = ("print(", "sys.stdout.write(", "console.log(", "printf ")
    return (
        "permissionDecision" in code
        and "deny" in code
        and any(emitter in code for emitter in emitters)
    )


def validate_automatic_implementation(errors, item, selected, where):
    group = item.get("report_group")
    if group not in {"hooks", "path_rules"}:
        errors.append("{}：该分组只支持 manual 执行".format(where))
        return
    writable = [op for op in selected if op.get("action") in {"create", "update"}]
    if not writable:
        return
    if group == "hooks":
        if any("/hooks/" not in operation.get("path", "").replace("\\", "/") for operation in writable):
            errors.append("{}：Hook 写操作必须落在 hooks 目录".format(where))
        registrations = [
            registration for operation in writable
            for registration in operation.get("registrations", [])
            if isinstance(registration, dict)
        ]
        registered_adapters = {
            (item.get("platform"), item.get("event"), item.get("matcher"))
            for item in registrations
        }
        expected_adapters = {
            (adapter.get("platform"), adapter.get("event"), adapter.get("matcher"))
            for adapter in item.get("enforcement", [])
        }
        if registered_adapters != expected_adapters:
            errors.append("{}：Hook registrations 与 enforcement 不一致".format(where))
        marker = "rules-architect-id: {}".format(item.get("rule_id"))
        adapter_map = {
            (adapter.get("platform"), adapter.get("event"), adapter.get("matcher")): adapter
            for adapter in item.get("enforcement", [])
        }
        for operation in writable:
            path = operation.get("path", "")
            content = operation.get("content", "")
            if marker not in content:
                errors.append("{}：Hook 内容缺少受管 rule_id 标记".format(where))
            for registration in operation.get("registrations", []):
                command = registration.get("command", "")
                if path and str(path) not in command and Path(path).name not in command:
                    errors.append("{}：Hook registration 未引用对应脚本路径".format(where))
                identity = (
                    registration.get("platform"), registration.get("event"),
                    registration.get("matcher"),
                )
                adapter = adapter_map.get(identity)
                if not adapter:
                    continue
                enforcement_marker = "rules-architect-enforcement: {}".format(
                    enforcement_digest(adapter)
                )
                if enforcement_marker not in content:
                    errors.append("{}：Hook 内容未绑定 enforcement 规格".format(where))
                if adapter.get("mode") == "block" and not content_has_blocking_behavior(
                    content, adapter
                ):
                    errors.append(
                        "{}：阻断型 Hook 缺少受管 blocking 标记或实际 deny 输出".format(where)
                    )
    else:
        if any("/.claude/rules/" not in operation.get("path", "").replace("\\", "/") for operation in writable):
            errors.append("{}：Path Rule 写操作必须落在 .claude/rules 目录".format(where))
        expected_paths = sorted({
            path for delivery in item.get("delivery", [])
            for path in delivery.get("paths", [])
        })
        for operation in writable:
            actual_paths = sorted(parse_frontmatter_paths(operation.get("content", "")))
            if actual_paths != expected_paths:
                errors.append("{}：Path Rule 内容的 paths 与 delivery 不一致".format(where))


def validate_final_consistency(errors, recommendations, decisions, operations, inventory):
    operation_map = {
        item.get("operation_id"): item for item in operations
        if isinstance(item, dict) and item.get("operation_id")
    }
    referenced = set()
    recommendation_referenced = set()
    known_rule_ids = {
        item.get("rule_id") for item in recommendations if isinstance(item, dict)
    }
    decision_map = {
        item.get("artifact_id"): item for item in decisions
        if isinstance(item, dict) and item.get("artifact_id")
    }
    artifact_map = {
        item.get("artifact_id"): item
        for item in (
            (inventory or {}).get("hook_artifacts", [])
            + (inventory or {}).get("path_rule_artifacts", [])
        )
        if isinstance(item, dict) and item.get("artifact_id")
    }

    def operation_refs(item, where, expected_actions, execution_mode="automatic"):
        operation_ids = item.get("operation_ids")
        if not isinstance(operation_ids, list) or not all(
            isinstance(value, str) and value for value in operation_ids
        ):
            errors.append("{}：operation_ids 必须是字符串列表".format(where))
            return []
        unknown = set(operation_ids) - set(operation_map)
        if unknown:
            errors.append("{}：引用了未知 operation_id：{}".format(where, ", ".join(sorted(unknown))))
        selected = [operation_map[value] for value in operation_ids if value in operation_map]
        referenced.update(operation_ids)
        if item.get("action") in MUTATING_ACTIONS and execution_mode == "automatic" and not selected:
            errors.append("{}：变更结论必须绑定可执行操作".format(where))
        if execution_mode in {"manual", "none"} and selected:
            errors.append("{}：非自动结论不得绑定写操作".format(where))
        if selected and {operation.get("action") for operation in selected} != expected_actions:
            errors.append("{}：最终结论与操作动作不一致".format(where))
        return selected

    for idx, item in enumerate(recommendations):
        if not isinstance(item, dict):
            continue
        where = "recommendations[{}]".format(idx)
        action = item.get("action")
        execution_mode = item.get("execution_mode")
        if execution_mode not in EXECUTION_MODES:
            errors.append("{}：execution_mode 无效".format(where))
        if action in MUTATING_ACTIONS and execution_mode not in {"automatic", "manual"}:
            errors.append("{}：变更结论必须选择 automatic 或 manual".format(where))
        if action in {"keep", "reuse"} and execution_mode != "none":
            errors.append("{}：保留或复用结论的 execution_mode 必须为 none".format(where))
        if action == "move" and execution_mode != "manual":
            errors.append("{}：move 当前只允许 manual，禁止自动半迁移".format(where))
        expected = {action}
        selected = operation_refs(item, where, expected, execution_mode)
        recommendation_referenced.update(
            operation.get("operation_id") for operation in selected
        )
        for operation in selected:
            if operation.get("rule_id") != item.get("rule_id"):
                errors.append("{}：操作未绑定当前 rule_id".format(where))
        if execution_mode == "automatic":
            validate_automatic_implementation(errors, item, selected, where)
            expected_kind = "hook" if item.get("report_group") == "hooks" else "path_rule"
            for operation in selected:
                artifact = artifact_map.get(operation.get("artifact_id"))
                if artifact and artifact.get("kind") != expected_kind:
                    errors.append("{}：自动操作的产物类型与报告分组不一致".format(where))
        for artifact_id in item.get("artifact_ids", []):
            if action in {"update", "disable", "delete"} and execution_mode == "automatic" and not any(
                op.get("artifact_id") == artifact_id for op in selected
            ):
                errors.append("{}：产物 {} 缺少对应操作".format(where, artifact_id))
            decision = decision_map.get(artifact_id)
            if action in {"keep", "reuse", "update", "disable", "delete"} \
                    and decision and decision.get("action") != action:
                errors.append(
                    "{}：推荐动作与产物 {} 的最终决策不一致".format(
                        where, artifact_id
                    )
                )

    for idx, item in enumerate(decisions):
        if not isinstance(item, dict):
            continue
        where = "artifact_decisions[{}]".format(idx)
        action = item.get("action")
        decision_execution = "none" if action in {"keep", "reuse"} else "automatic"
        selected = operation_refs(item, where, {action}, decision_execution)
        if any(op.get("artifact_id") != item.get("artifact_id") for op in selected):
            errors.append("{}：操作未绑定当前 artifact_id".format(where))

    for operation_id, operation in operation_map.items():
        if operation_id not in referenced:
            errors.append("operations：存在未被最终结论引用的操作 {}".format(operation_id))
        rule_id = operation.get("rule_id")
        if rule_id and rule_id not in known_rule_ids:
            errors.append("operations：{} 引用了未知 rule_id {}".format(operation_id, rule_id))
        if operation.get("action") in {"create", "update"} \
                and operation_id not in recommendation_referenced:
            errors.append("operations：写入操作必须由最终推荐引用 {}".format(operation_id))


def validate_recommendations(data, inventory=None):
    errors = []
    if not isinstance(data, dict):
        return ["recommendations：根节点必须是对象"]
    if data.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append("recommendations：不支持该 schema_version")
    schema_12 = data.get("schema_version") == "1.2"
    plan_status = data.get("plan_status")
    if schema_12 and plan_status not in PLAN_STATUSES:
        errors.append("recommendations：plan_status 必须是 needs_confirmation 或 ready")
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
    clarifications = data.get("clarifications", [])
    if schema_12 and not isinstance(clarifications, list):
        errors.append("recommendations：'clarifications' 类型错误")
        clarifications = []
    elif not isinstance(clarifications, list):
        clarifications = []
    resolved_occurrence_ids = data.get("resolved_occurrence_ids", [])
    resolved_artifact_ids = data.get("resolved_artifact_ids", [])
    if schema_12:
        for field, values in (
            ("resolved_occurrence_ids", resolved_occurrence_ids),
            ("resolved_artifact_ids", resolved_artifact_ids),
        ):
            if field not in data:
                errors.append("recommendations：缺少 '{}'".format(field))
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values
            ):
                errors.append("recommendations：{} 必须是字符串列表".format(field))
                if field == "resolved_occurrence_ids":
                    resolved_occurrence_ids = []
                else:
                    resolved_artifact_ids = []

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
        allowed_actions = FINAL_ACTIONS if schema_12 else ACTIONS
        if item.get("action") not in allowed_actions:
            errors.append("{}：action 无效".format(where))
        if item.get("confidence") not in CONFIDENCE:
            errors.append("{}：confidence 无效".format(where))
        if schema_12:
            if item.get("decision_source") not in DECISION_SOURCES:
                errors.append("{}：decision_source 无效".format(where))
            if plan_status == "ready" and item.get("confidence") == "low":
                errors.append("{}：最终推荐不得保留低置信度结论".format(where))
            operation_ids = item.get("operation_ids")
            if not isinstance(operation_ids, list) or not all(
                isinstance(value, str) and value for value in operation_ids
            ):
                errors.append("{}：operation_ids 必须是字符串列表".format(where))
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
        errors, data, "duplicates", known_occurrences or covered,
        final=schema_12 and plan_status == "ready",
    )
    validate_relationships(
        errors, data, "conflicts", known_occurrences or covered,
        final=schema_12 and plan_status == "ready",
    )
    unresolved = 0
    clarification_occurrences = set()
    clarification_artifacts = set()
    if schema_12:
        unresolved, clarification_occurrences, clarification_artifacts = validate_clarifications(
            errors, clarifications, known_occurrences, known_artifacts
        )
        if unclassified:
            errors.append("recommendations：schema 1.2 使用 clarifications，unclassified 必须为空")
        if plan_status == "needs_confirmation":
            if unresolved == 0:
                errors.append("recommendations：needs_confirmation 必须包含未确认项")
            if recommendations:
                errors.append("recommendations：确认完成前不得生成最终推荐")
            if operations:
                errors.append("recommendations：确认完成前不得生成待应用操作")
            if artifact_decisions:
                errors.append("recommendations：确认完成前不得生成最终产物决策")
            resolved = set(resolved_occurrence_ids)
            unknown_resolved = resolved - known_occurrences
            if unknown_resolved:
                errors.append(
                    "recommendations：resolved_occurrence_ids 引用了未知出现位置：{}".format(
                        ", ".join(sorted(unknown_resolved))
                    )
                )
            overlap = resolved & clarification_occurrences
            if overlap:
                errors.append(
                    "recommendations：出现位置不能同时标记为已确定和待确认：{}".format(
                        ", ".join(sorted(overlap))
                    )
                )
            missing_preflight = known_occurrences - resolved - clarification_occurrences
            if missing_preflight:
                errors.append(
                    "recommendations：前置阶段遗漏出现位置：{}".format(
                        ", ".join(sorted(missing_preflight))
                    )
                )
            resolved_artifacts = set(resolved_artifact_ids)
            unknown_resolved_artifacts = resolved_artifacts - known_artifacts
            if unknown_resolved_artifacts:
                errors.append(
                    "recommendations：resolved_artifact_ids 引用了未知产物：{}".format(
                        ", ".join(sorted(unknown_resolved_artifacts))
                    )
                )
            artifact_overlap = resolved_artifacts & clarification_artifacts
            if artifact_overlap:
                errors.append(
                    "recommendations：产物不能同时标记为已确定和待确认：{}".format(
                        ", ".join(sorted(artifact_overlap))
                    )
                )
            missing_artifacts = known_artifacts - resolved_artifacts - clarification_artifacts
            if missing_artifacts:
                errors.append(
                    "recommendations：前置阶段遗漏规则产物：{}".format(
                        ", ".join(sorted(missing_artifacts))
                    )
                )
        elif plan_status == "ready" and unresolved:
            errors.append("recommendations：仍有未确认项，不能生成最终推荐")
        elif plan_status == "ready":
            if resolved_occurrence_ids or resolved_artifact_ids:
                errors.append("recommendations：ready 方案的 resolved_*_ids 必须为空")
            validate_resolved_outcomes(
                errors, clarifications, recommendations, artifact_decisions
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
        if missing and not (schema_12 and plan_status == "needs_confirmation"):
            errors.append(
                "recommendations：尚未归类的出现位置：{}".format(
                    ", ".join(sorted(missing))
                )
            )
    validate_operations(errors, operations, inventory, schema_12=schema_12)
    validate_artifact_decisions(
        errors,
        artifact_decisions,
        inventory,
        required=(
            data.get("schema_version") == "1.1"
            or (schema_12 and plan_status == "ready")
        ),
        final_only=schema_12,
    )
    if schema_12 and plan_status == "ready":
        validate_final_consistency(
            errors, recommendations, artifact_decisions, operations, inventory
        )
    return errors


def example_contract():
    adapter = {
        "mode": "remind", "platform": "claude",
        "event": "PreToolUse", "matcher": "Bash",
    }
    hook_path = "~/.claude/hooks/example.py"
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_status": "ready",
        "inventory_fingerprint": "<copy from inventory>",
        "project_root": "<copy from inventory>",
        "recommendations": [{
            "rule_id": "R-example",
            "occurrence_ids": ["O-example"],
            "summary": "示例规则",
            "canonical": {"target": "agents_md", "path": "AGENTS.md"},
            "delivery": [],
            "enforcement": [adapter],
            "report_group": "hooks",
            "reason": "仅作示例",
            "confidence": "medium",
            "action": "create",
            "execution_mode": "automatic",
            "decision_source": "inferred",
            "artifact_ids": [],
            "operation_ids": ["OP-example"],
        }],
        "operations": [{
            "operation_id": "OP-example",
            "action": "create",
            "rule_id": "R-example",
            "path": hook_path,
            "content": (
                "# rules-architect-id: R-example\n"
                "# rules-architect-enforcement: {}\n"
                "# rules-architect-blocking: {}\n"
                "import json\n"
                "def main():\n"
                "    print(json.dumps({{\"hookSpecificOutput\": "
                "{{\"permissionDecision\": \"deny\"}}}}))\n"
                "    return 0\n"
            ).format(enforcement_digest(adapter), enforcement_digest(adapter)),
            "reason": "示例自动 Hook",
            "requires_confirmation": False,
            "registrations": [{
                "platform": "claude",
                "config_path": "~/.claude/settings.json",
                "event": "PreToolUse",
                "matcher": "Bash",
                "command": "python3 {}".format(hook_path),
            }],
        }],
        "artifact_decisions": [],
        "clarifications": [],
        "resolved_occurrence_ids": [],
        "resolved_artifact_ids": [],
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
