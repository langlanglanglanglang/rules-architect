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
    ("hooks", "Hook 强制规则"),
    ("path_rules", "路径规则"),
    ("team_baseline", "团队基线"),
    ("memory", "个人记忆"),
    ("lessons", "团队经验"),
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
ACTION_LABEL = {
    "keep": "保留",
    "reuse": "复用",
    "move": "迁移",
    "create": "创建",
    "update": "修改",
    "disable": "禁用",
    "delete": "删除",
    "review": "复核",
}
DELIVERY_LABEL = {
    "always_loaded": "始终加载",
    "path_scoped": "按路径加载",
    "on_demand": "按需加载",
    "delivery": "加载方式",
}
MODE_LABEL = {"block": "阻断", "remind": "提醒", "unknown": "未知"}
OWNERSHIP_LABEL = {
    "rules_architect": "rules-architect",
    "external_tool": "外部工具",
    "user_managed": "用户维护",
    "unknown": "未知",
}
STATUS_LABEL = {
    "active": "已启用",
    "orphan": "孤立文件",
    "modified_orphan": "已修改的孤立文件",
    "dangling_registration": "失效注册",
    "registered_command": "命令型注册",
    "modified": "本地已修改",
    "missing": "文件缺失",
    "symlink": "符号链接",
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
    parts = ["{} / {}".format(platform, MODE_LABEL.get(mode, mode))]
    if event:
        parts.append(event)
    if matcher:
        parts.append(str(matcher))
    return " / ".join(parts)


def render(data, inventory=None, verbose=False):
    inventory_map = {}
    artifact_map = {}
    if inventory:
        inventory_map = {
            c["occurrence_id"]: c
            for c in inventory.get("rule_candidates", [])
        }
        artifact_map = {
            artifact["artifact_id"]: artifact
            for artifact in (
                inventory.get("hook_artifacts", [])
                + inventory.get("path_rule_artifacts", [])
            )
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

    action_counts = {}
    for item in data.get("recommendations", []):
        action = item.get("action", "review")
        action_counts[action] = action_counts.get(action, 0) + 1
    lines.append("生命周期变更摘要")
    lines.append("")
    if action_counts:
        lines.append("；".join(
            "{} {}".format(ACTION_LABEL.get(action, action), count)
            for action, count in (
                (name, action_counts[name])
                for name in (
                    "create", "reuse", "update", "move", "disable",
                    "delete", "keep", "review"
                )
                if name in action_counts
            )
        ))
    else:
        lines.append("无规则建议")
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
                    ACTION_LABEL.get(item["action"], item["action"]),
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
                            DELIVERY_LABEL.get(
                                d.get("type", "delivery"),
                                d.get("type", "delivery"),
                            )
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
            for artifact_id in item.get("artifact_ids", []):
                artifact = artifact_map.get(artifact_id)
                if not artifact:
                    continue
                lines.append(
                    "产物：{} [{} / {}]".format(
                        artifact.get("path") or artifact.get("command") or artifact_id,
                        OWNERSHIP_LABEL.get(
                            artifact.get("ownership"), artifact.get("ownership", "未知")
                        ),
                        STATUS_LABEL.get(
                            artifact.get("status"), artifact.get("status", "未知")
                        ),
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
                lines.append("出现位置 ID：" + ", ".join(item["occurrence_ids"]))
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
        artifacts = inventory.get("hook_artifacts", [])
        decisions = {
            item.get("artifact_id"): item
            for item in data.get("artifact_decisions", [])
            if isinstance(item, dict)
        }
        active = sum(1 for artifact in artifacts if artifact.get("status") == "active")
        findings = [
            artifact for artifact in artifacts
            if artifact.get("status") != "active"
        ]
        lines.append(
            "Hook 实际状态（{} 个，正常 {} 个，需关注 {} 个）".format(
                len(artifacts), active, len(findings)
            )
        )
        lines.append("")
        if not findings:
            lines.append("（无异常）")
        else:
            for artifact in findings:
                lines.append(
                    "- [{}][{}] {}".format(
                        STATUS_LABEL.get(
                            artifact.get("status"), artifact.get("status", "未知")
                        ),
                        OWNERSHIP_LABEL.get(
                            artifact.get("ownership"), artifact.get("ownership", "未知")
                        ),
                        artifact.get("path") or artifact.get("command") or artifact["artifact_id"],
                    )
                )
                if artifact.get("modified_since_managed"):
                    lines.append("  本地内容与 Manifest 哈希不一致，只能人工复核。")
                decision = decisions.get(artifact.get("artifact_id"))
                if decision:
                    lines.append(
                        "  建议：{}；{}".format(
                            ACTION_LABEL.get(decision["action"], decision["action"]),
                            decision["reason"],
                        )
                    )
        lines.append("")

        path_artifacts = inventory.get("path_rule_artifacts", [])
        lines.append("路径规则实际状态（{} 个）".format(len(path_artifacts)))
        lines.append("")
        if not path_artifacts:
            lines.append("（无）")
        else:
            for artifact in path_artifacts:
                decision = decisions.get(artifact.get("artifact_id"))
                line = "- [{}][{}] {}".format(
                    STATUS_LABEL.get(artifact.get("status"), artifact.get("status")),
                    OWNERSHIP_LABEL.get(artifact.get("ownership"), artifact.get("ownership")),
                    artifact["path"],
                )
                if decision:
                    line += " → {}".format(ACTION_LABEL.get(decision["action"], decision["action"]))
                lines.append(line)
        lines.append("")

        artifact_decisions = data.get("artifact_decisions", [])
        lines.append("产物决策（{}）".format(len(artifact_decisions)))
        lines.append("")
        if not artifact_decisions:
            lines.append("（无）")
        else:
            for index, decision in enumerate(artifact_decisions, 1):
                artifact = artifact_map.get(decision["artifact_id"], {})
                lines.append(
                    "{}. [{}] {} — {}".format(
                        index,
                        ACTION_LABEL.get(decision["action"], decision["action"]),
                        artifact.get("path") or artifact.get("command") or decision["artifact_id"],
                        decision["reason"],
                    )
                )
        lines.append("")

        operations = data.get("operations", [])
        lines.append("待应用操作（{}）".format(len(operations)))
        lines.append("")
        if not operations:
            lines.append("（无）")
        else:
            for index, operation in enumerate(operations, 1):
                lines.append(
                    "{}. [{}] {}".format(
                        index,
                        ACTION_LABEL.get(operation["action"], operation["action"]),
                        operation["reason"],
                    )
                )
                target = operation.get("path") or operation.get("artifact_id")
                if target:
                    lines.append("   目标：{}".format(target))
                lines.append(
                    "   需要确认：{}".format(
                        "是" if operation.get("requires_confirmation") else "否"
                    )
                )
        lines.append("")

        errors = inventory.get("source_errors", [])
        skipped = inventory.get("skipped_sources", [])
        lines.append("扫描问题（{}）".format(len(errors) + len(skipped)))
        lines.append("")
        if not errors and not skipped:
            lines.append("（无）")
        else:
            for item in errors:
                lines.append(
                    "- 错误 {}：{}".format(
                        item.get("path") or "（未知）", item["message"]
                    )
                )
            for item in skipped:
                lines.append(
                    "- 跳过 {}：{}".format(item["path"], item["reason"])
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description="渲染五档规则分布建议")
    parser.add_argument("recommendations", help="建议 JSON 文件")
    parser.add_argument("--inventory", help="规则清单 JSON 文件")
    parser.add_argument("--verbose", action="store_true", help="显示出现位置 ID")
    parser.add_argument("--output", help="将报告写入指定文件")
    args = parser.parse_args()
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
    output = render(recommendations, inventory, args.verbose)
    if args.output:
        atomic_private_write(args.output, output)
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
