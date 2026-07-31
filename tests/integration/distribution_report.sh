#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_HOME="$(mktemp -d)"
TMP_PROJECT="$(mktemp -d)"
trap 'rm -rf "$TMP_HOME" "$TMP_PROJECT"' EXIT

export HOME="$TMP_HOME"
mkdir -p "$TMP_PROJECT/.claude/rules"

cat > "$TMP_PROJECT/AGENTS.md" <<'EOF'
# Team baseline

- 必须运行测试。
- 禁止直接 push main。
EOF

cat > "$TMP_PROJECT/CLAUDE.md" <<'EOF'
# Claude baseline

- 必须运行测试。
EOF

cat > "$TMP_PROJECT/.claude/rules/proto.md" <<'EOF'
---
paths:
  - "**/*.proto"
---
# Proto

- 字段编号必须递增。
EOF

cat > "$TMP_PROJECT/.claude/settings.json" <<'EOF'
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "echo project-hook"}]
      }
    ]
  }
}
EOF

TMP_MEMORY="$TMP_HOME/memory"
mkdir -p "$TMP_MEMORY"
cat > "$TMP_MEMORY/feedback_concise.md" <<'EOF'
---
description: concise responses
---
回答应该简洁。
EOF

TMP_LESSONS="$TMP_HOME/lessons.md"
cat > "$TMP_LESSONS" <<'EOF'
# Lessons

- 生产配置事故必须保留复盘记录。
EOF

INVENTORY="$TMP_HOME/inventory.json"
RECOMMENDATIONS="$TMP_HOME/recommendations.json"
REPORT="$TMP_HOME/report.txt"

cd "$TMP_PROJECT"
python3 "$SKILL_DIR/scripts/rule_inventory.py" \
  --project-root "$TMP_PROJECT" \
  --platform both \
  --memory-dir "$TMP_MEMORY" \
  --lessons-path "$TMP_LESSONS" \
  --output "$INVENTORY"

python3 - "$INVENTORY" "$RECOMMENDATIONS" <<'PY'
import json
import sys

inventory = json.load(open(sys.argv[1]))
source_by_id = {source["source_id"]: source for source in inventory["sources"]}
recommendations = []
for index, candidate in enumerate(inventory["rule_candidates"], 1):
    kind = candidate["source_kind"]
    delivery = []
    enforcement = []
    if candidate["candidate_kind"] == "hook_registration":
        group = "hooks"
        target = "existing"
        action = "keep"
        metadata = candidate["metadata"]
        enforcement = [{
            "mode": "remind",
            "platform": metadata["platform"],
            "event": metadata["event"],
            "matcher": metadata.get("matcher") or "*"
        }]
    elif kind == "path_rule":
        group = "path_rules"
        target = "path_rule"
        action = "keep"
        delivery = [{
            "type": "path_rule",
            "paths": source_by_id[candidate["source_id"]]["paths"]
        }]
    elif kind.startswith("memory_"):
        group = "memory"
        target = "memory"
        action = "keep"
    elif kind == "lessons":
        group = "lessons"
        target = "lessons"
        action = "keep"
    else:
        group = "team_baseline"
        target = "agents_md" if kind == "agents_md" else "claude_md"
        action = "keep"
    recommendations.append({
        "rule_id": "R{:03d}".format(index),
        "occurrence_ids": [candidate["occurrence_id"]],
        "summary": candidate["text"],
        "canonical": {
            "target": target,
            "path": candidate["source_path"]
        },
        "delivery": delivery,
        "enforcement": enforcement,
        "report_group": group,
        "reason": "integration fixture placement",
        "confidence": candidate["extraction_confidence"],
        "action": action
    })

test_rules = [
    candidate for candidate in inventory["rule_candidates"]
    if candidate["text"] == "必须运行测试。"
]
assert len(test_rules) == 2, test_rules
relation_occurrences = [candidate["occurrence_id"] for candidate in test_rules]
report = {
    "schema_version": "1.0",
    "inventory_fingerprint": inventory["inventory_fingerprint"],
    "project_root": inventory["project_root"],
    "recommendations": recommendations,
    "duplicates": [{
        "relation_id": "D-test",
        "occurrence_ids": relation_occurrences,
        "summary": "相同测试规则出现在 AGENTS 与 CLAUDE",
        "confidence": "high"
    }],
    "conflicts": [{
        "relation_id": "C-review",
        "occurrence_ids": relation_occurrences,
        "summary": "fixture conflict rendering check",
        "confidence": "low"
    }],
    "unclassified": []
}
with open(sys.argv[2], "w") as handle:
    json.dump(report, handle, ensure_ascii=False, indent=2)
PY

python3 "$SKILL_DIR/scripts/recommendation_contract.py" \
  "$RECOMMENDATIONS" --inventory "$INVENTORY"
python3 "$SKILL_DIR/scripts/render_distribution.py" \
  "$RECOMMENDATIONS" --inventory "$INVENTORY" --output "$REPORT"

grep -Eq 'Hook 强制规则（[1-9]' "$REPORT"
grep -Eq '路径规则（[1-9]' "$REPORT"
grep -Eq '团队基线（[1-9]' "$REPORT"
grep -Eq '个人记忆（[1-9]' "$REPORT"
grep -Eq '团队经验（[1-9]' "$REPORT"
grep -q '重复关系（1）' "$REPORT"
grep -q '冲突关系（1）' "$REPORT"
grep -q "$TMP_PROJECT/AGENTS.md" "$REPORT"

MALFORMED="$TMP_HOME/malformed.json"
MALFORMED_ERROR="$TMP_HOME/malformed.err"
python3 - "$RECOMMENDATIONS" "$MALFORMED" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    report = json.load(handle)
report["duplicates"] = ["not-an-object"]
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    json.dump(report, handle)
PY
if python3 "$SKILL_DIR/scripts/render_distribution.py" \
  "$MALFORMED" --inventory "$INVENTORY" 2>"$MALFORMED_ERROR"; then
    echo "malformed recommendation unexpectedly rendered" >&2
    exit 1
fi
grep -Fq 'duplicates[0]：必须是对象' "$MALFORMED_ERROR"
if grep -q 'Traceback' "$MALFORMED_ERROR"; then
    echo "malformed recommendation caused a traceback" >&2
    exit 1
fi

echo "distribution report integration: passed"
