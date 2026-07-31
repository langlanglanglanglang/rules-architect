#!/usr/bin/env python3
"""
rules-architect skill: diagnose.py

Scan current rule architecture across 5 layers:
  L0 hooks         — ~/.claude/hooks/*.py + settings.json registration
  L1 memory        — ~/.claude/projects/*/memory/MEMORY.md + feedback_*.md
  L2 path-scoped   — <project>/.claude/rules/*.md
  L3 CLAUDE.md     — DELEGATED to claude-md-management:claude-md-improver
  L5 team lessons  — configured path (env LESSONS_PATH or --lessons-path)

Each layer gets:
  - Grade (A-F) with reason
  - List of files / entries
  - Issues (severity: blocker / warn / info)
  - Actionable recommendations

Output modes:
  - human-readable (default)
  - --json (structured for CI / tests / scripts)

Does NOT modify any files. Safe to run on any project.

Usage:
  diagnose.py
  diagnose.py --json
  diagnose.py --memory-dir <path>
  diagnose.py --rules-dir <path>
  diagnose.py --lessons-path <path>
"""
import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path


SKILL_VERSION = "1.0.0"


# === Platform abstraction ===
def get_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def get_hooks_dir() -> Path:
    return Path.home() / ".claude" / "hooks"


def get_projects_root() -> Path:
    return Path.home() / ".claude" / "projects"


# === CC version detection ===
def detect_cc_version() -> str:
    try:
        out = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "未知"


# === L0: Hooks scan ===
# Core generic hooks (5-Q SOP injection + base infrastructure).
# error_recovery_checkpoint / dangerous_branch_reminder were removed in v2.0.0
# — they encode individual workflow preferences, not universal patterns.
# See examples/ for opt-in versions.
GENERIC_HOOKS = {
    "memory_intake_check.py",
    "rule_intake_reminder.py",
    "cleanup_hook.py",
}


def scan_l0_hooks() -> dict:
    settings_path = get_settings_path()
    hooks_dir = get_hooks_dir()

    installed_files = []
    if hooks_dir.exists():
        installed_files = sorted(
            p.name for p in hooks_dir.glob("*.py") if p.is_file()
        )

    registered = []
    settings_hooks = {}
    if settings_path.exists():
        try:
            d = json.loads(settings_path.read_text())
            settings_hooks = d.get("hooks", {})
            for event, configs in settings_hooks.items():
                for c in configs:
                    matcher = c.get("matcher", "*")
                    for h in c.get("hooks", []):
                        cmd = h.get("command", "")
                        registered.append({
                            "event": event,
                            "matcher": matcher,
                            "command": cmd,
                        })
        except Exception as e:
            return {
                "grade": "F",
                "issues": [{"severity": "blocker",
                            "message": f"无法读取 settings.json：{e}"}],
                "installed_files": installed_files,
                "registered": [],
            }

    generic_present = sum(1 for f in installed_files if f in GENERIC_HOOKS)
    total_generic = len(GENERIC_HOOKS)

    issues = []
    if generic_present < total_generic:
        missing = sorted(GENERIC_HOOKS - set(installed_files))
        issues.append({
            "severity": "info",
            "message": (
                f"rules-architect 基础 Hook 已安装 {generic_present}/{total_generic}。"
                f"缺少：{', '.join(missing)}"
            ),
        })
    if not registered:
        issues.append({
            "severity": "warn",
            "message": "settings.json 中没有 hooks 配置；"
                       "即使 .py 文件存在，Hook 也不会触发",
        })

    if generic_present == 0:
        grade = "F"
    elif generic_present == 1:
        grade = "D"
    elif generic_present == 2:
        grade = "C"
    elif generic_present == 3:
        grade = "A"
    else:
        grade = "A"   # >3 means extra custom hooks installed

    return {
        "grade": grade,
        "installed_files": installed_files,
        "generic_installed": generic_present,
        "generic_total": total_generic,
        "registered_count": len(registered),
        "registered": registered,
        "issues": issues,
        "recommendations": [] if grade in {"A", "B"} else [
            "运行 install_hooks.py 补齐基础 Hook",
        ],
    }


# === L1: Memory scan ===
def find_memory_dirs() -> list:
    root = get_projects_root()
    if not root.exists():
        return []
    found = []
    for project_dir in root.iterdir():
        if not project_dir.is_dir():
            continue
        mem = project_dir / "memory"
        if mem.is_dir() and (mem / "MEMORY.md").exists():
            try:
                mtime = mem.stat().st_mtime
                found.append((mtime, mem))
            except Exception:
                continue
    found.sort(reverse=True)
    return [m for _, m in found]


# Patterns suggesting a memory entry should be upgraded to a hook
RHYTHM_KEYWORDS = [
    "声明", "汇报", "停顿", "thinking",
    "立刻", "立即", "实时",
]
# Sub-classification: which keywords strongly suggest L0 hook (rhythm/timing)
# vs which suggest L3 CLAUDE.md (rule-content stability)
L0_STRONG_KEYWORDS = {"声明", "停顿", "立刻", "立即", "实时", "thinking"}
TEAM_KEYWORDS = {"team", "team-wide", "所有", "全员", "团队", "everyone"}


def classify_upgrade_target(hits: list, desc: str) -> tuple:
    """Decide recommended target layer + reason."""
    desc_lower = desc.lower()
    has_l0 = any(k in L0_STRONG_KEYWORDS for k in hits)
    has_team = any(k in desc_lower for k in TEAM_KEYWORDS)
    if has_l0 and has_team:
        return ("L0 Hook + L3 CLAUDE.md",
                "同时涉及执行时机和团队范围：规则正文放在 L3，并安装 Hook 实时拦截")
    if has_l0:
        return ("L0 Hook",
                f"命中执行时机关键词 {hits[:2]}，需要实时拦截")
    if has_team:
        return ("L3 CLAUDE.md",
                "属于团队规则，Codex/Gemini 用户也需要看到")
    return ("L3 CLAUDE.md 或 L0 Hook",
            "稳定规则：L3 用于团队可见，L0 用于强制执行")


def detect_upgrade_candidates(memory_dir: Path) -> list:
    candidates = []
    for p in memory_dir.glob("feedback_*.md"):
        try:
            text = p.read_text(errors="ignore")
        except Exception:
            continue
        head = text[:500].lower() + text[:500]
        hits = [k for k in RHYTHM_KEYWORDS if k in head]
        if hits:
            m = re.search(r"description:\s*(.+?)(?:\n|$)", text)
            desc = m.group(1).strip()[:100] if m else ""
            target, why = classify_upgrade_target(hits, desc)
            candidates.append({
                "name": p.stem,
                "matched_keywords": hits[:5],
                "recommended_target": target,
                "reason": why,
                "description": desc,
            })
    return candidates


def scan_l1_memory(memory_dir_override: str = None) -> dict:
    if memory_dir_override:
        memory_dirs = [Path(memory_dir_override).expanduser()]
    else:
        memory_dirs = find_memory_dirs()

    if not memory_dirs:
        return {
            "grade": "（空）",
            "memory_dir": None,
            "issues": [{"severity": "info",
                        "message": "未找到记忆目录；可能是新项目，或尚未使用 /memory"}],
            "files_total": 0,
        }

    mem = memory_dirs[0]
    index_path = mem / "MEMORY.md"
    if not index_path.exists():
        return {
            "grade": "F",
            "memory_dir": str(mem),
            "issues": [{"severity": "blocker",
                        "message": "缺少 MEMORY.md 索引"}],
        }

    idx_text = index_path.read_text(errors="ignore")
    idx_lines = idx_text.count("\n") + 1
    idx_kb = len(idx_text.encode("utf-8")) / 1024.0

    feedback_files = list(mem.glob("feedback_*.md"))
    reference_files = list(mem.glob("reference_*.md"))

    # Topic groups (lines starting with ## A. ... ## H.)
    topic_re = re.compile(r"^##\s+([A-Z]\..+?)(?:\n|$)", re.MULTILINE)
    topics = {}
    for m in topic_re.finditer(idx_text):
        topic_name = m.group(1).strip()
        # count bullet lines until next ##
        rest = idx_text[m.end():]
        next_h = re.search(r"^##\s", rest, re.MULTILINE)
        section = rest[:next_h.start()] if next_h else rest
        bullets = sum(1 for ln in section.split("\n") if ln.strip().startswith("- "))
        topics[topic_name] = bullets

    upgrade_candidates = detect_upgrade_candidates(mem)

    issues = []
    if idx_lines > 200:
        issues.append({
            "severity": "warn",
            "message": f"MEMORY.md 共 {idx_lines} 行，Claude Code 会在 200 行后截断。"
                       "建议清理过期条目。",
        })
    if not topics:
        issues.append({
            "severity": "info",
            "message": "MEMORY.md 未按主题分组（没有“## A. …”标题）。"
                       "建议分组以提高信噪比。",
        })
    if upgrade_candidates:
        issues.append({
            "severity": "info",
            "message": f"有 {len(upgrade_candidates)} 条记忆疑似执行时机规则，"
                       "提升为 L0 Hook 会更可靠",
        })

    total = len(feedback_files) + len(reference_files)
    if total == 0:
        grade = "（空）"
    elif total < 5:
        grade = "C"
    elif total < 50 and topics and idx_lines <= 200:
        grade = "B+"
    elif idx_lines > 200:
        grade = "D"
    else:
        grade = "B"

    return {
        "grade": grade,
        "memory_dir": str(mem),
        "index_lines": idx_lines,
        "index_kb": round(idx_kb, 1),
        "feedback_count": len(feedback_files),
        "reference_count": len(reference_files),
        "files_total": total,
        "topics": topics,
        "upgrade_candidates": upgrade_candidates,
        "issues": issues,
    }


# === L2: path-scoped rules scan ===
def scan_l2_rules(rules_dir_override: str = None) -> dict:
    cwd = Path.cwd()
    if rules_dir_override:
        rules_dir = Path(rules_dir_override).expanduser()
    else:
        rules_dir = cwd / ".claude" / "rules"

    if not rules_dir.exists():
        return {
            "grade": "（空）",
            "rules_dir": str(rules_dir),
            "issues": [{"severity": "info",
                        "message": f"未找到 {rules_dir}；可运行 install_rule_intake.py "
                                   "创建 rule-intake.md"}],
            "files": [],
        }

    files = []
    for p in sorted(rules_dir.glob("*.md")):
        try:
            text = p.read_text(errors="ignore")
        except Exception:
            continue
        # Parse frontmatter paths:
        paths = []
        m = re.match(r"^---\n(.+?)\n---", text, re.DOTALL)
        if m:
            fm = m.group(1)
            in_paths = False
            for line in fm.split("\n"):
                line_stripped = line.strip()
                if line_stripped == "paths:" or line.startswith("paths:"):
                    in_paths = True
                    continue
                if in_paths:
                    if line_stripped.startswith("- "):
                        paths.append(line_stripped[2:].strip('"\''))
                    elif line_stripped and not line.startswith(" "):
                        in_paths = False
        files.append({
            "name": p.name,
            "paths": paths,
            "lines": text.count("\n"),
        })

    issues = []
    has_rule_intake = any(f["name"] == "rule-intake.md" for f in files)
    if not has_rule_intake:
        issues.append({
            "severity": "info",
            "message": "缺少 rule-intake.md；建议安装，以便编辑规则文件时注入归位流程",
        })

    grade = "（空）" if not files else ("A-" if has_rule_intake else "B")
    return {
        "grade": grade,
        "rules_dir": str(rules_dir),
        "files": files,
        "count": len(files),
        "has_rule_intake": has_rule_intake,
        "issues": issues,
    }


# === L3: delegated to claude-md-management ===
def scan_l3_claude_md() -> dict:
    settings_path = get_settings_path()
    plugin_enabled = False
    if settings_path.exists():
        try:
            d = json.loads(settings_path.read_text())
            plugins = d.get("enabledPlugins", {})
            plugin_enabled = plugins.get(
                "claude-md-management@claude-plugins-official", False
            )
        except Exception:
            pass

    cwd = Path.cwd()
    has_claude_md = (cwd / "CLAUDE.md").exists()
    has_global = (Path.home() / ".claude" / "CLAUDE.md").exists()

    issues = []
    if not plugin_enabled:
        issues.append({
            "severity": "info",
            "message": "claude-md-management 插件未启用。"
                       "请通过 /plugin claude-md-management 安装，以执行 L3 审计。",
        })

    return {
        "grade": "（已委托）",
        "delegated_to": "claude-md-management:claude-md-improver",
        "plugin_enabled": plugin_enabled,
        "project_claude_md": has_claude_md,
        "global_claude_md": has_global,
        "recommendation": (
            "运行 /claude-md-management:claude-md-improver 执行 L3 审计"
            if plugin_enabled else
            "先安装 claude-md-management 插件：/plugin claude-md-management"
        ),
        "issues": issues,
    }


# === L5: team lessons ===
def scan_l5_lessons(lessons_path: str = None) -> dict:
    path = lessons_path or os.environ.get("LESSONS_PATH")
    if not path:
        return {
            "grade": "（未配置）",
            "path": None,
            "issues": [{"severity": "info",
                        "message": "未设置 LESSONS_PATH；配置后才能将个人记忆同步到团队经验"}],
            "configured_via": "LESSONS_PATH 环境变量或 --lessons-path 参数",
        }
    p = Path(path).expanduser()
    if not p.exists():
        return {
            "grade": "F",
            "path": str(p),
            "issues": [{"severity": "warn",
                        "message": f"LESSONS_PATH 指向不存在的文件：{p}"}],
        }
    text = p.read_text(errors="ignore")
    return {
        "grade": "A",
        "path": str(p),
        "lines": text.count("\n"),
        "size_kb": round(len(text.encode("utf-8")) / 1024.0, 1),
        "issues": [],
    }


# === Token injection estimate ===
def estimate_token_injection() -> int:
    """Rough token cost of every-session L1 + L3 injections."""
    total_bytes = 0
    # Standard CC global files
    paths = [
        Path.home() / ".claude" / "CLAUDE.md",
        Path.home() / ".claude" / "RTK.md",
    ]
    # Project root: any CLAUDE*.md at cwd top-level
    cwd = Path.cwd()
    for p in cwd.glob("CLAUDE*.md"):
        if p.is_file():
            paths.append(p)
    # User can add project-specific files via env var (comma-separated relative paths)
    # E.g.  RA_TOKEN_EXTRA_PATHS="workflow.md,business-map.md,docs/ai/notes.md"
    extra = os.environ.get("RA_TOKEN_EXTRA_PATHS", "")
    for s in extra.split(","):
        s = s.strip()
        if not s:
            continue
        rel = Path(s)
        if not rel.is_absolute():
            rel = cwd / rel
        if rel.exists():
            paths.append(rel)
    for p in paths:
        if p.exists():
            try:
                total_bytes += p.stat().st_size
            except Exception:
                continue
    # Add MEMORY.md
    mem_dirs = find_memory_dirs()
    if mem_dirs:
        idx = mem_dirs[0] / "MEMORY.md"
        if idx.exists():
            try:
                total_bytes += idx.stat().st_size
            except Exception:
                pass
    return int(total_bytes / 2.3)  # rough English/Chinese mix divisor


# === Aggregation + rendering ===
def full_report(args) -> dict:
    return {
        "diagnosis_version": SKILL_VERSION,
        "diagnosed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "platform": platform.platform(),
        "claude_version": detect_cc_version(),
        "cwd": str(Path.cwd()),
        "layers": {
            "L0_hooks": scan_l0_hooks(),
            "L1_memory": scan_l1_memory(args.memory_dir),
            "L2_path_scoped": scan_l2_rules(args.rules_dir),
            "L3_claude_md": scan_l3_claude_md(),
            "L5_team_lessons": scan_l5_lessons(args.lessons_path),
        },
        "token_injection_estimate": estimate_token_injection(),
    }


def render_human(report: dict) -> str:
    lines = []
    lines.append(f"\n🔍 rules-architect 诊断 v{report['diagnosis_version']}")
    lines.append(f"   {report['diagnosed_at']}  ({report['platform']})")
    lines.append(f"   Claude Code：{report['claude_version']}")
    lines.append(f"   当前目录：{report['cwd']}")
    lines.append("")
    lines.append(f"   Token 注入估算：每个会话约 {report['token_injection_estimate']:,}")
    lines.append("")

    L = report["layers"]
    lines.append("层级   组件                    评级    说明")
    lines.append("-----  ----------------------  ------  --------------------------------")

    l0 = L["L0_hooks"]
    lines.append(
        f"L0     Hook                    {l0['grade']:6s}  "
        f"基础 Hook {l0.get('generic_installed', 0)}/{l0.get('generic_total', 0)}，"
        f"已注册 {l0.get('registered_count', 0)} 个"
    )

    l1 = L["L1_memory"]
    if l1.get("files_total"):
        lines.append(
            f"L1     个人记忆                {l1['grade']:6s}  "
            f"{l1['files_total']} 个条目，"
            f"{l1['index_lines']} 行，{l1['index_kb']} KB"
        )
    else:
        lines.append(f"L1     个人记忆                {l1['grade']:6s}  （无）")

    l2 = L["L2_path_scoped"]
    lines.append(
        f"L2     路径规则                {l2['grade']:6s}  "
        f"{l2.get('rules_dir', '?')} 中有 {l2.get('count', 0)} 条规则"
    )

    l3 = L["L3_claude_md"]
    delegate = "✅ 可用" if l3["plugin_enabled"] else "❌ 需要安装插件"
    lines.append(
        f"L3     CLAUDE.md（已委托）    委托    claude-md-improver：{delegate}"
    )

    l5 = L["L5_team_lessons"]
    if l5.get("path"):
        lines.append(
            f"L5     团队经验                {l5['grade']:6s}  {l5['path']} "
            f"（{l5.get('lines', 0)} 行）"
        )
    else:
        lines.append(f"L5     团队经验                {l5['grade']:6s}  （未配置）")

    # Issues
    lines.append("")
    lines.append("⚠️  发现的问题：")
    any_issue = False
    layer_labels = {
        "L0_hooks": "L0 Hook",
        "L1_memory": "L1 个人记忆",
        "L2_path_scoped": "L2 路径规则",
        "L3_claude_md": "L3 CLAUDE.md",
        "L5_team_lessons": "L5 团队经验",
    }
    for layer_name, layer in L.items():
        for iss in layer.get("issues", []):
            any_issue = True
            severity = {"blocker": "阻断", "warn": "警告", "info": "提示"}.get(
                iss["severity"], iss["severity"]
            )
            lines.append(
                f"   [{layer_labels.get(layer_name, layer_name)}] "
                f"{severity}：{iss['message']}"
            )
    if not any_issue:
        lines.append("   （无）")

    # Upgrade candidates
    cands = l1.get("upgrade_candidates", [])
    if cands:
        lines.append("")
        lines.append("📋 个人记忆 → 建议提升位置（仅建议，不会移动文件）：")
        lines.append("")
        lines.append(f"   {'记忆条目':<40s} {'建议目标':<24s} 原因")
        lines.append(f"   {'-'*46} {'-'*26} {'-'*40}")
        for c in cands[:15]:
            name = c["name"][:44]
            tgt = c.get("recommended_target", "?")[:24]
            reason = c.get("reason", "")[:60]
            lines.append(f"   {name:<46s} {tgt:<26s} {reason}")
            desc = (c.get("description") or "").strip()
            if desc:
                if len(desc) > 110:
                    desc = desc[:107] + "..."
                lines.append(f"     ↳ {desc}")
        if len(cands) > 15:
            lines.append(f"   ……另有 {len(cands) - 15} 个候选项")
        lines.append("")
        lines.append("   ⚠️  diagnose.py 只提供建议，不会自动移动任何内容。")
        lines.append("")
        lines.append("   如需处理候选项，请告诉主代理：")
        lines.append("     • “提升 <候选项名称>” → 主代理执行五问归位，提出具体 Hook 方案")
        lines.append("       （事件 + 匹配器 + 提醒），等待确认后再执行安装与记忆标记脚本。")
        lines.append("     • “废弃 <候选项名称>” → 主代理追加 Deprecated 标记")
        lines.append("       （记忆正文仍保留在 Git 历史中）。")
        lines.append("     • 不处理：继续保留在 L1。")

    # Recommended next steps
    lines.append("")
    lines.append("📋 建议的后续步骤：")
    steps = []
    if l0.get("generic_installed", 0) < l0.get("generic_total", 0):
        steps.append("运行 install_hooks.py 补齐基础 Hook（B 模式）")
    if not l2.get("has_rule_intake"):
        steps.append("运行 install_rule_intake.py 创建 .claude/rules/rule-intake.md（C 模式）")
    if l3["plugin_enabled"]:
        steps.append("运行 /claude-md-management:claude-md-improver 执行 L3 审计")
    else:
        steps.append("安装 claude-md-management 插件：/plugin claude-md-management")
    if not steps:
        steps.append("当前架构状态良好，建议定期重新运行诊断。")
    for i, s in enumerate(steps, 1):
        lines.append(f"   {i}. {s}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="rules-architect 诊断")
    ap.add_argument("--json", action="store_true",
                    help="输出结构化 JSON（供 CI 或脚本使用）")
    ap.add_argument("--memory-dir", help="指定要扫描的 Claude Code 记忆目录")
    ap.add_argument("--rules-dir", help="指定要扫描的 .claude/rules/ 目录")
    ap.add_argument("--lessons-path", help="团队 lessons.md 路径")
    args = ap.parse_args()

    report = full_report(args)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, default=str, indent=2))
    else:
        print(render_human(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
