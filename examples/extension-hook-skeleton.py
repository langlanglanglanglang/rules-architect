#!/usr/bin/env python3
"""
EXAMPLE — minimal CC hook skeleton with dedupe + audit + JSON output.

Use this as the starting point for any custom hook you want to add.

Pick a hook event from CC docs:
  - PreToolUse / PostToolUse (parametrize by tool matcher)
  - UserPromptSubmit (parametrize by message regex)
  - SessionStart / SessionEnd (no matcher)

CUSTOMIZE the placeholders marked with TODO.
"""
import json
import os
import re
import sys
import time
from pathlib import Path


# === TODO 1: Name your hook ===
HOOK_NAME = "my_custom_hook"


# === TODO 2: Define your trigger condition ===
def should_trigger(data: dict) -> bool:
    """Return True if this invocation should inject the reminder."""
    # Example: PostToolUse Bash matching a git command
    tool_input = data.get("tool_input") or {}
    cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    # TODO: replace this regex with your actual trigger
    return bool(re.search(r"\bgit\s+push\b", cmd))


# === TODO 3: Write your reminder text ===
REMINDER = (
    "TODO: Replace this with the actual reminder you want injected.\n"
    "Keep it self-contained — don't reference external CLAUDE.md sections.\n"
    "If the user can act on the reminder in this same turn, say so explicitly."
)


def get_cache_dir() -> Path:
    """Cross-platform cache dir."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "claude-hooks"
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "Claude" / "cache" / "claude-hooks"
    return Path.home() / ".cache" / "claude-hooks"


CACHE = get_cache_dir()
CACHE.mkdir(parents=True, exist_ok=True)


def log_audit(decision: str, **kwargs) -> None:
    rec = {"ts": time.time(), "hook": HOOK_NAME, "decision": decision, **kwargs}
    try:
        with open(CACHE / "audit.jsonl", "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0

    # Sanitize the runtime-supplied id before it lands in a lock filename.
    session_id = "".join(
        c if (c.isalnum() or c in "_-") else "_"
        for c in str(data.get("session_id", "unknown"))
    )[:128]

    if not should_trigger(data):
        return 0

    # Per-session dedupe — fire once per session
    lock = CACHE / f"{HOOK_NAME}-{session_id}.lock"
    if lock.exists():
        log_audit("dedupe-skip", session=session_id)
        return 0
    lock.touch()

    output = {"hookSpecificOutput": {"additionalContext": REMINDER}}
    print(json.dumps(output, ensure_ascii=False))
    log_audit("inject", session=session_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())


# === TODO 4: Register in ~/.claude/settings.json ===
# Add an entry like:
#
#   "hooks": {
#     "PostToolUse": [  # or PreToolUse / UserPromptSubmit / SessionStart
#       {
#         "matcher": "Bash",  # or "Edit|Write" / "mcp__YourMCP__yourTool" / "*"
#         "hooks": [
#           {"type": "command", "command": "python3 ~/.claude/hooks/my_custom_hook.py"}
#         ]
#       }
#     ]
#   }
#
# Then test:
#   echo '<stub JSON>' | python3 ~/.claude/hooks/my_custom_hook.py
#
# And observe real triggers in:
#   jq '.' ~/.cache/claude-hooks/audit.jsonl | tail
