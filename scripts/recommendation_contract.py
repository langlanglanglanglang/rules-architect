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


SCHEMA_VERSION = "1.0"
GROUPS = {"hooks", "path_rules", "team_baseline", "memory", "lessons"}
TARGETS = {
    "agents_md", "claude_md", "path_rule", "memory", "lessons", "existing"
}
ACTIONS = {"keep", "move", "create", "review"}
CONFIDENCE = {"high", "medium", "low"}
ENFORCEMENT_MODES = {"block", "remind"}


def require_type(errors, obj, key, expected, where):
    if key not in obj:
        errors.append("{}: missing '{}'".format(where, key))
        return None
    value = obj[key]
    if not isinstance(value, expected):
        errors.append("{}: '{}' has wrong type".format(where, key))
        return None
    return value


def require_nonempty_strings(errors, values, where):
    if not values:
        errors.append("{}: must contain at least one occurrence id".format(where))
        return []
    valid = []
    for value in values:
        if not isinstance(value, str) or not value:
            errors.append("{}: occurrence ids must be non-empty strings".format(where))
        else:
            valid.append(value)
    return valid


def validate_inventory(data):
    errors = []
    if not isinstance(data, dict):
        return ["inventory: root must be an object"]
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append("inventory: unsupported schema_version")
    fingerprint = require_type(
        errors, data, "inventory_fingerprint", str, "inventory"
    )
    for key in (
        "sources", "rule_candidates", "hook_registrations",
        "source_errors", "skipped_sources",
    ):
        require_type(errors, data, key, list, "inventory")
    seen = set()
    for idx, source in enumerate(data.get("sources", [])):
        where = "sources[{}]".format(idx)
        if not isinstance(source, dict):
            errors.append("{}: must be an object".format(where))
            continue
        for key in ("path", "content_hash", "kind"):
            require_type(errors, source, key, str, where)
    for idx, candidate in enumerate(data.get("rule_candidates", [])):
        where = "rule_candidates[{}]".format(idx)
        if not isinstance(candidate, dict):
            errors.append("{}: must be an object".format(where))
            continue
        occurrence_id = require_type(
            errors, candidate, "occurrence_id", str, where
        )
        for key in ("text", "text_hash", "source_path"):
            require_type(errors, candidate, key, str, where)
        if occurrence_id:
            if occurrence_id in seen:
                errors.append("{}: duplicate occurrence_id".format(where))
            seen.add(occurrence_id)
    if fingerprint and not errors:
        if compute_inventory_fingerprint(data) != fingerprint:
            errors.append("inventory: fingerprint does not match contents")
    return errors


def validate_delivery(errors, delivery, where):
    for idx, adapter in enumerate(delivery):
        adapter_where = "{}[{}]".format(where, idx)
        if not isinstance(adapter, dict):
            errors.append("{}: must be an object".format(adapter_where))
            continue
        require_type(errors, adapter, "type", str, adapter_where)
        if "paths" in adapter:
            paths = adapter["paths"]
            if not isinstance(paths, list) or not paths or not all(
                isinstance(path, str) and path for path in paths
            ):
                errors.append(
                    "{}: paths must be a non-empty string list".format(
                        adapter_where
                    )
                )


def validate_enforcement(errors, enforcement, where):
    for idx, adapter in enumerate(enforcement):
        adapter_where = "{}[{}]".format(where, idx)
        if not isinstance(adapter, dict):
            errors.append("{}: must be an object".format(adapter_where))
            continue
        if adapter.get("mode") not in ENFORCEMENT_MODES:
            errors.append("{}: invalid mode".format(adapter_where))
        require_type(errors, adapter, "platform", str, adapter_where)
        for field in ("event", "matcher"):
            if not isinstance(adapter.get(field), str) or not adapter[field]:
                errors.append(
                    "{}: hook enforcement requires '{}'".format(
                        adapter_where, field
                    )
                )
        if adapter.get("mode") == "block":
            if (
                not isinstance(adapter.get("predicate"), str)
                or not adapter["predicate"]
            ):
                errors.append(
                    "{}: blocking hook requires 'predicate'".format(
                        adapter_where
                    )
                )


def validate_relationships(errors, data, key, known_occurrences):
    if key not in data:
        errors.append("recommendations: missing '{}'".format(key))
        return
    relationships = data.get(key, [])
    if not isinstance(relationships, list):
        errors.append("recommendations: '{}' has wrong type".format(key))
        return
    for idx, item in enumerate(relationships):
        where = "{}[{}]".format(key, idx)
        if not isinstance(item, dict):
            errors.append("{}: must be an object".format(where))
            continue
        require_type(errors, item, "relation_id", str, where)
        require_type(errors, item, "summary", str, where)
        occurrences = require_type(
            errors, item, "occurrence_ids", list, where
        )
        if occurrences is not None:
            valid = require_nonempty_strings(errors, occurrences, where)
            if len(valid) < 2:
                errors.append("{}: requires at least two occurrences".format(where))
            unknown = set(valid) - known_occurrences
            if unknown:
                errors.append(
                    "{}: unknown occurrences: {}".format(
                        where, ", ".join(sorted(unknown))
                    )
                )
        if item.get("confidence") not in CONFIDENCE:
            errors.append("{}: invalid confidence".format(where))


def validate_recommendations(data, inventory=None):
    errors = []
    if not isinstance(data, dict):
        return ["recommendations: root must be an object"]
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append("recommendations: unsupported schema_version")
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

    known_occurrences = set()
    if inventory is not None:
        errors.extend(validate_inventory(inventory))
        known_occurrences = {
            candidate.get("occurrence_id")
            for candidate in inventory.get("rule_candidates", [])
            if candidate.get("occurrence_id")
        }
        if data.get("inventory_fingerprint") != inventory.get(
            "inventory_fingerprint"
        ):
            errors.append("recommendations: inventory fingerprint mismatch")
        try:
            recommendation_root = str(Path(data.get("project_root", "")).resolve())
            inventory_root = str(Path(inventory.get("project_root", "")).resolve())
            if recommendation_root != inventory_root:
                errors.append("recommendations: project_root mismatch")
        except (OSError, TypeError):
            errors.append("recommendations: invalid project_root")

    rule_ids = set()
    covered = set()
    for idx, item in enumerate(recommendations):
        where = "recommendations[{}]".format(idx)
        if not isinstance(item, dict):
            errors.append("{}: must be an object".format(where))
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
            errors.append("{}: invalid canonical target".format(where))
        delivery = require_type(errors, item, "delivery", list, where) or []
        enforcement = require_type(
            errors, item, "enforcement", list, where
        ) or []
        validate_delivery(errors, delivery, where + ".delivery")
        validate_enforcement(errors, enforcement, where + ".enforcement")
        group = item.get("report_group")
        if group not in GROUPS:
            errors.append("{}: invalid report_group".format(where))
        if item.get("action") not in ACTIONS:
            errors.append("{}: invalid action".format(where))
        if item.get("confidence") not in CONFIDENCE:
            errors.append("{}: invalid confidence".format(where))
        if group == "hooks" and not enforcement:
            errors.append("{}: hooks group requires enforcement".format(where))
        if group == "path_rules" and not any(
            isinstance(adapter, dict) and adapter.get("paths")
            for adapter in delivery
        ):
            errors.append(
                "{}: path_rules group requires non-empty paths".format(where)
            )
        if rule_id:
            if rule_id in rule_ids:
                errors.append("{}: duplicate rule_id".format(where))
            rule_ids.add(rule_id)
        for occurrence_id in valid_occurrences:
            if occurrence_id in covered:
                errors.append(
                    "{}: occurrence '{}' covered more than once".format(
                        where, occurrence_id
                    )
                )
            covered.add(occurrence_id)

    for idx, item in enumerate(unclassified):
        where = "unclassified[{}]".format(idx)
        if not isinstance(item, dict):
            errors.append("{}: must be an object".format(where))
            continue
        occurrences = require_type(
            errors, item, "occurrence_ids", list, where
        )
        valid_occurrences = require_nonempty_strings(
            errors, occurrences or [], where
        )
        require_type(errors, item, "reason", str, where)
        if item.get("confidence") not in CONFIDENCE:
            errors.append("{}: invalid confidence".format(where))
        for occurrence_id in valid_occurrences:
            if occurrence_id in covered:
                errors.append(
                    "{}: occurrence '{}' covered more than once".format(
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
                "recommendations: unknown occurrences: {}".format(
                    ", ".join(sorted(unknown))
                )
            )
        if missing:
            errors.append(
                "recommendations: uncovered occurrences: {}".format(
                    ", ".join(sorted(missing))
                )
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
            "summary": "Example rule",
            "canonical": {"target": "agents_md", "path": "AGENTS.md"},
            "delivery": [],
            "enforcement": [{
                "mode": "remind",
                "platform": "claude",
                "event": "PreToolUse",
                "matcher": "Bash",
            }],
            "report_group": "hooks",
            "reason": "Example only",
            "confidence": "medium",
            "action": "review",
        }],
        "duplicates": [],
        "conflicts": [],
        "unclassified": [],
    }


def load_json(path):
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("recommendations", nargs="?")
    parser.add_argument("--inventory")
    parser.add_argument("--example", action="store_true")
    args = parser.parse_args()
    if args.example:
        print(json.dumps(example_contract(), ensure_ascii=False, indent=2))
        return 0
    if not args.recommendations:
        parser.error("recommendations is required unless --example is used")
    try:
        recommendations = load_json(args.recommendations)
        inventory = load_json(args.inventory) if args.inventory else None
    except (OSError, ValueError) as exc:
        print("invalid JSON: {}".format(exc), file=sys.stderr)
        return 2
    errors = validate_recommendations(recommendations, inventory)
    if errors:
        for error in errors:
            print("ERROR: " + error, file=sys.stderr)
        return 1
    print("recommendations contract: valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
