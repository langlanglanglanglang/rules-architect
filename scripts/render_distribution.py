#!/usr/bin/env python3
"""Render validated recommendations as the five-group user report."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

try:
    from .recommendation_contract import validate_recommendations
except (ImportError, ValueError):
    from recommendation_contract import validate_recommendations


GROUP_ORDER = [
    ("hooks", "Hooks"),
    ("path_rules", "Path-scoped Rules"),
    ("team_baseline", "Team Baseline"),
    ("memory", "Memory"),
    ("lessons", "Lessons"),
]
PREFIX = {
    "hooks": "H",
    "path_rules": "P",
    "team_baseline": "B",
    "memory": "M",
    "lessons": "L",
}
CONFIDENCE_LABEL = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "not_applicable": "不适用",
}


def load_json(path):
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text())


def atomic_private_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        if hasattr(os, "fchmod") and os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, str(path))
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def format_adapter(adapter):
    mode = adapter.get("mode", "unknown")
    platform = adapter.get("platform", "?")
    event = adapter.get("event")
    matcher = adapter.get("matcher")
    parts = ["{} / {}".format(platform, mode)]
    if event:
        parts.append(event)
    if matcher:
        parts.append(str(matcher))
    return " / ".join(parts)


def render(data, inventory=None, verbose=False):
    inventory_map = {}
    if inventory:
        inventory_map = {
            c["occurrence_id"]: c
            for c in inventory.get("rule_candidates", [])
        }
    lines = ["规则分布建议（只读，尚未修改文件）", ""]
    if inventory:
        summary = inventory.get("summary", {})
        lines.append(
            "扫描：{} 个来源，{} 条候选，{} 个来源错误，{} 个跳过项".format(
                summary.get("sources", 0),
                summary.get("rule_candidates", 0),
                summary.get("source_errors", 0),
                summary.get("skipped", 0),
            )
        )
        lines.append("")

    grouped = {name: [] for name, _ in GROUP_ORDER}
    for item in data.get("recommendations", []):
        grouped[item["report_group"]].append(item)

    for group, title in GROUP_ORDER:
        items = grouped[group]
        lines.append("{}（{}）".format(title, len(items)))
        lines.append("")
        if not items:
            lines.append("（无）")
            lines.append("")
            continue
        for index, item in enumerate(items, 1):
            confidence = item["confidence"]
            lines.append(
                "{}{:02d} [{}][{}][{}]".format(
                    PREFIX[group], index, item["rule_id"],
                    CONFIDENCE_LABEL.get(confidence, confidence),
                    item["action"],
                )
            )
            lines.append(item["summary"])
            canonical = item["canonical"]
            lines.append(
                "正文：{} {}".format(
                    canonical["target"], canonical.get("path") or ""
                ).rstrip()
            )
            if item.get("delivery"):
                lines.append(
                    "加载：{}".format(
                        "；".join(
                            d.get("type", "delivery")
                            + (
                                " " + ",".join(d.get("paths", []))
                                if d.get("paths") else ""
                            )
                            for d in item["delivery"]
                        )
                    )
                )
            if item.get("enforcement"):
                lines.append(
                    "执行：{}".format(
                        "；".join(format_adapter(e) for e in item["enforcement"])
                    )
                )
            if inventory_map:
                sources = []
                for occurrence_id in item["occurrence_ids"]:
                    candidate = inventory_map.get(occurrence_id)
                    if candidate:
                        sources.append(
                            "{}:{}".format(
                                candidate["source_path"],
                                candidate["line_start"],
                            )
                        )
                if sources:
                    lines.append("来源：" + "；".join(sources))
            lines.append("原因：" + item["reason"])
            if verbose:
                lines.append("Occurrence IDs：" + ", ".join(item["occurrence_ids"]))
            lines.append("")

    for key, title in [
        ("duplicates", "重复关系"),
        ("conflicts", "冲突关系"),
        ("unclassified", "待确认"),
    ]:
        items = data.get(key, [])
        lines.append("{}（{}）".format(title, len(items)))
        lines.append("")
        if not items:
            lines.append("（无）")
        else:
            for index, item in enumerate(items, 1):
                label = item.get("relation_id") or item.get("id") or str(index)
                summary = item.get("summary") or item.get("reason") or ""
                confidence = item.get("confidence", "low")
                lines.append(
                    "{}. [{}][{}] {}".format(
                        index,
                        label,
                        CONFIDENCE_LABEL.get(confidence, confidence),
                        summary,
                    )
                )
                for occurrence_id in item.get("occurrence_ids", []):
                    candidate = inventory_map.get(occurrence_id)
                    if candidate:
                        lines.append(
                            "   - {} — {}:{}".format(
                                candidate["text"],
                                candidate["source_path"],
                                candidate["line_start"],
                            )
                        )
        lines.append("")

    if inventory:
        errors = inventory.get("source_errors", [])
        skipped = inventory.get("skipped_sources", [])
        lines.append("扫描问题（{}）".format(len(errors) + len(skipped)))
        lines.append("")
        if not errors and not skipped:
            lines.append("（无）")
        else:
            for item in errors:
                lines.append(
                    "- ERROR {}：{}".format(
                        item.get("path") or "(unknown)", item["message"]
                    )
                )
            for item in skipped:
                lines.append(
                    "- SKIP {}：{}".format(item["path"], item["reason"])
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("recommendations")
    parser.add_argument("--inventory")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
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
    output = render(recommendations, inventory, args.verbose)
    if args.output:
        atomic_private_write(args.output, output)
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
