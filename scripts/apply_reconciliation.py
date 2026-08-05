#!/usr/bin/env python3
"""Safely preview or apply a validated rules-architect reconciliation plan."""
import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

try:
    from .recommendation_contract import validate_recommendations
    from .rule_inventory import InventoryBuilder
    from .state_store import atomic_private_write, default_state_path, state_root
except (ImportError, ValueError):
    from recommendation_contract import validate_recommendations
    from rule_inventory import InventoryBuilder
    from state_store import atomic_private_write, default_state_path, state_root


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def atomic_write_text(path, content, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if executable and os.name != "nt":
            os.chmod(temporary, 0o755)
        os.replace(temporary, str(path))
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def resolved(path):
    return Path(path).expanduser().absolute().resolve(strict=False)


def allowed_roots(project_root):
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME") or (home / ".codex"))
    return [
        resolved(home / ".claude" / "hooks"),
        resolved(codex_home / "hooks"),
        resolved(project_root / ".claude" / "hooks"),
        resolved(project_root / ".claude" / "rules"),
    ]


def validate_target(path, project_root):
    target = Path(path).expanduser().absolute()
    if target.is_symlink():
        raise ValueError("拒绝修改符号链接：{}".format(target))
    parent = target.parent.resolve(strict=False)
    if not any(parent == root or root in parent.parents for root in allowed_roots(project_root)):
        raise ValueError("目标不在允许目录内：{}".format(target))
    return target


def validate_config_path(path, project_root):
    candidate = resolved(path)
    home = Path.home()
    allowed = {
        resolved(home / ".claude" / "settings.json"),
        resolved(Path(os.environ.get("CODEX_HOME") or (home / ".codex")) / "hooks.json"),
        resolved(project_root / ".claude" / "settings.json"),
        resolved(project_root / ".claude" / "settings.local.json"),
    }
    if candidate not in allowed:
        raise ValueError("Hook 配置不在允许清单内：{}".format(candidate))
    return candidate


def current_hash(path):
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def remove_exact_registration(config, registration):
    hooks = config.get("hooks", {})
    event = registration.get("event")
    entries = hooks.get(event, []) if isinstance(hooks, dict) else []
    changed = False
    kept_entries = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("matcher") != registration.get("matcher"):
            kept_entries.append(entry)
            continue
        kept_hooks = [
            hook for hook in entry.get("hooks", [])
            if not isinstance(hook, dict) or hook.get("command") != registration.get("command")
        ]
        if len(kept_hooks) != len(entry.get("hooks", [])):
            changed = True
        if kept_hooks:
            copied = dict(entry)
            copied["hooks"] = kept_hooks
            kept_entries.append(copied)
    if changed:
        if kept_entries:
            hooks[event] = kept_entries
        else:
            hooks.pop(event, None)
    return changed


def same_registration(left, right):
    return all(left.get(key) == right.get(key) for key in (
        "config_path", "event", "matcher", "command"
    ))


def same_manifest_registration(left, right):
    return all(left.get(key) == right.get(key) for key in (
        "event", "matcher", "command"
    ))


def add_exact_registration(config, registration):
    event = registration["event"]
    matcher = registration["matcher"]
    command = registration["command"]
    entries = config.setdefault("hooks", {}).setdefault(event, [])
    for entry in entries:
        if entry.get("matcher") == matcher:
            if any(h.get("command") == command for h in entry.get("hooks", []) if isinstance(h, dict)):
                return False
            entry.setdefault("hooks", []).append({"type": "command", "command": command})
            return True
    entries.append({"matcher": matcher, "hooks": [{"type": "command", "command": command}]})
    return True


def mutate_config(config_path, callback):
    path = Path(config_path).expanduser()
    if path.is_symlink():
        raise ValueError("拒绝修改符号链接配置：{}".format(path))
    config = read_json(path) if path.is_file() else {}
    validate_hook_config(config, path)
    if callback(config):
        atomic_write_text(path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")


def validate_hook_config(config, path):
    if not isinstance(config, dict) or not isinstance(config.get("hooks", {}), dict):
        raise ValueError("Hook 配置结构无效：{}".format(path))
    for event, entries in config.get("hooks", {}).items():
        if not isinstance(entries, list):
            raise ValueError("Hook 事件必须是列表：{} / {}".format(path, event))
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks", []), list):
                raise ValueError("Hook 注册项结构无效：{} / {}".format(path, event))


def rebuild_inventory(inventory):
    inputs = inventory.get("inputs", {})
    limits = inventory.get("limits", {})
    builder = InventoryBuilder(
        project_root=Path(inventory["project_root"]),
        platforms=set(inventory.get("platforms", [])),
        memory_dir=Path(inputs["memory_dir"]) if inputs.get("memory_dir") else None,
        lessons_path=inputs.get("lessons_path"),
        max_file_bytes=limits.get("max_file_bytes", 1024 * 1024),
        max_total_bytes=limits.get("max_total_bytes", 8 * 1024 * 1024),
        max_files=limits.get("max_files", 500),
        redact_secrets=inputs.get("redact_secrets", True),
        state_path=inventory.get("state_path"),
    )
    return builder.build()


def apply_plan(
    plan, inventory, confirm=False, verify_current=True,
    selected_operation_ids=None, selected_actions=None,
):
    if plan.get("schema_version") != "1.2" or plan.get("plan_status") != "ready":
        raise ValueError("实际应用只接受 schema 1.2 且 plan_status=ready 的最终方案")
    errors = validate_recommendations(plan, inventory)
    if errors:
        raise ValueError("；".join(errors))
    if verify_current:
        live = rebuild_inventory(inventory)
        if live["inventory_fingerprint"] != inventory["inventory_fingerprint"]:
            raise ValueError("扫描结果已经变化，请重新运行分析后再应用")

    artifacts = {
        item["artifact_id"]: item
        for item in (
            inventory.get("hook_artifacts", [])
            + inventory.get("path_rule_artifacts", [])
        )
    }
    all_operations = plan.get("operations", [])
    known_operation_ids = {
        operation["operation_id"] for operation in all_operations
    }
    selected_operation_ids = set(selected_operation_ids or [])
    selected_actions = set(selected_actions or [])
    if selected_operation_ids and selected_actions:
        raise ValueError("不能同时按操作 ID 和动作类型筛选")
    unknown_operation_ids = selected_operation_ids - known_operation_ids
    if unknown_operation_ids:
        raise ValueError(
            "选择了未知操作 ID：{}".format(
                ", ".join(sorted(unknown_operation_ids))
            )
        )
    if selected_operation_ids:
        operations = [
            operation for operation in all_operations
            if operation["operation_id"] in selected_operation_ids
        ]
    elif selected_actions:
        operations = [
            operation for operation in all_operations
            if operation["action"] in selected_actions
        ]
    else:
        operations = list(all_operations)
    if (selected_operation_ids or selected_actions) and not operations:
        raise ValueError("所选条件没有匹配任何可执行操作")
    if not operations:
        return {
            "mode": "no_op" if confirm else "preview",
            "operations": 0,
            "selected_operation_ids": [],
            "applied": 0,
        }

    applied = []
    manifest_path = Path(os.environ.get("RULES_ARCHITECT_MANIFEST") or (Path.home() / ".claude" / ".rules-architect-manifest.json"))
    manifest = read_json(manifest_path) if manifest_path.is_file() else {
        "skill_name": "rules-architect", "installed_files": [], "settings_hooks_added": []
    }
    if not isinstance(manifest, dict):
        raise ValueError("Manifest 根节点必须是对象：{}".format(manifest_path))
    for key in (
        "installed_files", "codex_installed_files",
        "settings_hooks_added", "codex_hooks_added",
    ):
        if key in manifest and not isinstance(manifest[key], list):
            raise ValueError("Manifest 字段必须是列表：{}".format(key))
    state_path = resolved(
        inventory.get("state_path") or default_state_path(inventory["project_root"])
    )
    allowed_state_root = resolved(state_root())
    if state_path.parent != allowed_state_root and allowed_state_root not in state_path.parents:
        raise ValueError("状态文件不在私有状态目录内：{}".format(state_path))
    previous_state = read_json(state_path) if state_path.is_file() else {}
    if not isinstance(previous_state, dict):
        raise ValueError("状态文件根节点必须是对象：{}".format(state_path))
    for key in ("applied_operation_ids", "rule_ids", "history"):
        if key in previous_state and not isinstance(previous_state[key], list):
            raise ValueError("状态字段必须是列表：{}".format(key))
    prepared_paths = {}
    seen_paths = set()
    for operation in operations:
        artifact = artifacts.get(operation.get("artifact_id"))
        if artifact:
            if artifact.get("ownership") != "rules_architect" or not artifact.get("safe_to_modify"):
                raise ValueError("产物不满足安全修改条件：{}".format(artifact["artifact_id"]))
            path = validate_target(artifact["path"], Path(inventory["project_root"]))
            if operation.get("path") and resolved(operation["path"]) != resolved(path):
                raise ValueError("操作路径与 artifact_id 不一致：{}".format(operation["operation_id"]))
            if operation["action"] in {"update", "delete"} \
                    and current_hash(path) != operation["expected_hash"]:
                raise ValueError("目标哈希已经变化：{}".format(path))
        else:
            path = validate_target(operation["path"], Path(inventory["project_root"]))
        if str(path) in seen_paths:
            raise ValueError("同一目标不能在一个计划中重复操作：{}".format(path))
        seen_paths.add(str(path))
        if operation["action"] == "create" and (path.exists() or path.is_symlink()):
            raise ValueError("创建目标已存在：{}".format(path))
        registrations = list((artifact or {}).get("registrations", []))
        registrations.extend(operation.get("registrations", []))
        for registration in registrations:
            config_path = validate_config_path(
                registration["config_path"], Path(inventory["project_root"])
            )
            if config_path.is_file():
                config = read_json(config_path)
                validate_hook_config(config, config_path)
        prepared_paths[operation["operation_id"]] = path

    if not confirm:
        return {
            "mode": "preview",
            "operations": len(operations),
            "selected_operation_ids": [
                operation["operation_id"] for operation in operations
            ],
            "applied": 0,
        }

    for operation in operations:
        action = operation["action"]
        artifact = artifacts.get(operation.get("artifact_id"))
        path = prepared_paths[operation["operation_id"]]

        if action == "create":
            if path.exists() or path.is_symlink():
                raise ValueError("创建目标已存在：{}".format(path))
            atomic_write_text(
                path, operation["content"],
                executable=path.suffix.lower() in {
                    ".py", ".sh", ".bash", ".zsh", ".fish", ".ps1",
                    ".js", ".mjs", ".cjs", ".rb", ".pl"
                },
            )
        elif action == "update":
            atomic_write_text(
                path, operation["content"],
                executable=path.suffix.lower() in {
                    ".py", ".sh", ".bash", ".zsh", ".fish", ".ps1",
                    ".js", ".mjs", ".cjs", ".rb", ".pl"
                },
            )
        elif action in {"disable", "delete"}:
            for registration in artifact.get("registrations", []):
                config_path = validate_config_path(
                    registration["config_path"], Path(inventory["project_root"])
                )
                mutate_config(
                    config_path,
                    lambda config, r=registration: remove_exact_registration(config, r),
                )
                registration_key = (
                    "codex_hooks_added"
                    if registration.get("platform") == "codex"
                    else "settings_hooks_added"
                )
                manifest.setdefault(registration_key, [])[:] = [
                    entry for entry in manifest.get(registration_key, [])
                    if not (
                        entry.get("event") == registration.get("event")
                        and entry.get("matcher") == registration.get("matcher")
                        and entry.get("command") == registration.get("command")
                    )
                ]
            if action == "delete":
                path.unlink()

        desired_registrations = operation.get("registrations", [])
        if action == "update" and artifact:
            for previous in artifact.get("registrations", []):
                if any(
                    same_registration(previous, desired)
                    for desired in desired_registrations
                ):
                    continue
                config_path = validate_config_path(
                    previous["config_path"], Path(inventory["project_root"])
                )
                mutate_config(
                    config_path,
                    lambda config, r=previous: remove_exact_registration(config, r),
                )
                registration_key = (
                    "codex_hooks_added"
                    if previous.get("platform") == "codex"
                    else "settings_hooks_added"
                )
                manifest.setdefault(registration_key, [])[:] = [
                    entry for entry in manifest.get(registration_key, [])
                    if not same_manifest_registration(entry, previous)
                ]
        for registration in (
            desired_registrations if action in {"create", "update"} else []
        ):
            config_path = validate_config_path(
                registration["config_path"], Path(inventory["project_root"])
            )
            mutate_config(
                config_path,
                lambda config, r=registration: add_exact_registration(config, r),
            )
            registration_key = (
                "codex_hooks_added"
                if resolved(config_path).name == "hooks.json"
                else "settings_hooks_added"
            )
            tracked = manifest.setdefault(registration_key, [])
            if not any(
                entry.get("event") == registration["event"]
                and entry.get("matcher") == registration["matcher"]
                and entry.get("command") == registration["command"]
                for entry in tracked
            ):
                tracked.append({
                    "platform": registration["platform"],
                    "config_path": registration["config_path"],
                    "event": registration["event"],
                    "matcher": registration["matcher"],
                    "command": registration["command"],
                    "owner": "rules-architect",
                    "kind": "reconciliation",
                })

        codex_root = resolved(Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")) / "hooks")
        manifest_key = "codex_installed_files" if codex_root in resolved(path).parents else "installed_files"
        if action in {"create", "update", "delete"}:
            for key in ("installed_files", "codex_installed_files"):
                manifest.setdefault(key, [])[:] = [
                    entry for entry in manifest.get(key, []) if entry.get("path") != str(path)
                ]
        if action in {"create", "update"}:
            entries = manifest.setdefault(manifest_key, [])
            entries.append({
                "path": str(path),
                "hash_sha256": current_hash(path),
                "owner": "rules-architect",
                "kind": "reconciliation",
                "rule_id": operation.get("rule_id"),
                "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            })
        applied.append(operation["operation_id"])

    atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    applied_rule_ids = {
        operation.get("rule_id") for operation in operations
        if operation.get("operation_id") in applied and operation.get("rule_id")
    }
    applied_details = [
        {
            "operation_id": operation["operation_id"],
            "operation_digest": sha256_bytes(json.dumps(
                operation, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")),
            "action": operation["action"],
            "rule_id": operation.get("rule_id"),
            "artifact_id": operation.get("artifact_id"),
            "path": str(prepared_paths[operation["operation_id"]]),
        }
        for operation in operations
        if operation["operation_id"] in applied
    ]
    history = list(previous_state.get("history", []))[-19:]
    history.append({
        "inventory_fingerprint": inventory["inventory_fingerprint"],
        "operations": applied_details,
        "applied_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })
    atomic_private_write(state_path, {
        "schema_version": "1.1",
        "project_root": inventory["project_root"],
        "based_on_inventory_fingerprint": inventory["inventory_fingerprint"],
        "applied_operation_ids": list(applied),
        "rule_ids": sorted(applied_rule_ids),
        "last_applied_operations": applied_details,
        "history": history,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })
    return {
        "mode": "apply",
        "operations": len(operations),
        "selected_operation_ids": applied,
        "applied": len(applied),
        "state_path": str(state_path),
    }


def comma_separated(values):
    out = []
    for value in values or []:
        out.extend(item.strip() for item in value.split(",") if item.strip())
    return out


def main():
    parser = argparse.ArgumentParser(description="安全预览或应用规则收敛操作")
    parser.add_argument("recommendations", help="建议 JSON")
    parser.add_argument("inventory", help="生成建议时使用的清单 JSON")
    parser.add_argument("--yes", action="store_true", help="确认执行写入；省略时只预览")
    parser.add_argument(
        "--operation", action="append", default=[], metavar="ID[,ID]",
        help="只处理指定操作 ID；可重复使用或用逗号分隔",
    )
    parser.add_argument(
        "--action", action="append", choices=["create", "update", "disable", "delete"],
        help="只处理指定动作；可重复使用，例如 --action create",
    )
    args = parser.parse_args()
    try:
        result = apply_plan(
            read_json(args.recommendations), read_json(args.inventory),
            confirm=args.yes, verify_current=True,
            selected_operation_ids=comma_separated(args.operation),
            selected_actions=args.action,
        )
    except (OSError, ValueError, KeyError) as exc:
        print("错误：{}".format(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
