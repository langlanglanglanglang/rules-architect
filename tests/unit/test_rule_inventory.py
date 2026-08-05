import json
import os
import subprocess
import sys
import tempfile
import unittest
import hashlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "rule_inventory.py"


class RuleInventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.project = self.home / "work" / "demo"
        self.project.mkdir(parents=True)
        self.external = self.home / "private-rules.md"
        self.external.write_text("- 必须泄露外部规则。\n")

        (self.project / "AGENTS.md").write_text(
            "# Team password=heading-secret\n\n"
            "- 必须运行测试。\n"
            "提交信息使用中文。\n\n"
            "| 文件 | 语言 |\n| --- | --- |\n| README | 中文 |\n"
            "```text\n"
            "- 必须忽略代码块里的示例。\n"
            "```\n"
        )
        (self.project / "CLAUDE.md").write_text(
            "# Claude\n\n- @shared.md\n\n@AGENTS.md\n\n"
            "@{}\n\n不要覆盖用户文件。\n".format(self.external)
        )
        (self.project / "shared.md").write_text(
            "# Shared\n\n- Always verify the result.\n"
        )
        nested = self.project / ".claude" / "rules" / "nested"
        nested.mkdir(parents=True)
        (nested / "proto.md").write_text(
            "---\npaths:\n  - \"**/*.proto\"\n---\n"
            "# Proto\n\n- 字段编号必须递增。\n"
        )
        (self.project / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {
                "PreToolUse": [{
                    "matcher": "Bash",
                    "hooks": [{
                        "type": "command",
                        "command": "python3 missing.py --api-key=super-secret-value",
                    }],
                }],
            },
        }))

        encoded = str(self.project.resolve()).replace(os.sep, "-")
        memory = self.home / ".claude" / "projects" / encoded / "memory"
        memory.mkdir(parents=True)
        (memory / "MEMORY.md").write_text(
            "# Memory\n\n- [Preference](feedback_pref.md)\n"
        )
        (memory / "feedback_pref.md").write_text(
            "---\ndescription: concise\n---\n回答应该简洁。\n"
        )
        (memory / "feedback_old.md").write_text(
            "---\ndescription: old\n---\n"
            "Promoted to: AGENTS.md @ 2026-01-01\n"
        )
        (memory / "conventions.md").write_text("Never push main.\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_inventory(self, project_root=None):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env.pop("XDG_STATE_HOME", None)
        env.pop("RULES_ARCHITECT_STATE_HOME", None)
        env.pop("RULES_ARCHITECT_MANIFEST", None)
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--project-root",
                str(project_root or self.project),
                "--platform",
                "both",
            ],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        return json.loads(proc.stdout)

    def test_discovers_platform_sources_and_exact_memory(self):
        data = self.run_inventory()
        paths = {s["path"]: s for s in data["sources"]}
        self.assertIn(str((self.project / "AGENTS.md").resolve()), paths)
        self.assertIn(str((self.project / "CLAUDE.md").resolve()), paths)
        self.assertIn(str((self.project / "shared.md").resolve()), paths)
        proto = str(
            (self.project / ".claude" / "rules" / "nested" / "proto.md").resolve()
        )
        self.assertEqual(paths[proto]["paths"], ["**/*.proto"])
        texts = [c["text"] for c in data["rule_candidates"]]
        self.assertTrue(any("运行测试" in text for text in texts))
        self.assertTrue(any("字段编号必须递增" in text for text in texts))
        self.assertTrue(any("回答应该简洁" in text for text in texts))
        self.assertTrue(any("提交信息使用中文" in text for text in texts))
        self.assertTrue(any("README | 中文" in text for text in texts))
        self.assertTrue(any("Never push main" in text for text in texts))
        self.assertTrue(any(
            source["kind"] == "memory_topic"
            and source["path"].endswith("conventions.md")
            for source in data["sources"]
        ))
        self.assertFalse(any("忽略代码块" in text for text in texts))
        self.assertFalse(any("泄露外部规则" in text for text in texts))
        self.assertFalse(any(text.startswith("Promoted to:") for text in texts))
        self.assertFalse(any(
            e["code"] == "memory_not_found" for e in data["source_errors"]
        ))
        agents_occurrences = [
            s for s in data["sources"]
            if s["path"] == str((self.project / "AGENTS.md").resolve())
        ]
        self.assertEqual(
            {s["platform"] for s in agents_occurrences},
            {"claude", "codex"},
        )
        hook_candidates = [
            candidate for candidate in data["rule_candidates"]
            if candidate["candidate_kind"] == "hook_registration"
        ]
        self.assertEqual(
            len(hook_candidates),
            data["summary"]["hook_registrations"],
        )
        self.assertEqual(len(hook_candidates), 1)
        self.assertIn("[REDACTED]", hook_candidates[0]["text"])
        self.assertNotIn(
            "heading-secret",
            json.dumps(data["rule_candidates"], ensure_ascii=False),
        )
        self.assertNotIn(
            "super-secret-value",
            json.dumps(data["hook_registrations"], ensure_ascii=False),
        )
        self.assertTrue(any(
            item["reason"] == "external_import_requires_confirmation"
            for item in data["skipped_sources"]
        ))

    def test_inventory_is_deterministic(self):
        first = self.run_inventory()
        second = self.run_inventory()
        self.assertEqual(
            first["inventory_fingerprint"],
            second["inventory_fingerprint"],
        )
        self.assertEqual(first["rule_candidates"], second["rule_candidates"])

    def test_previous_private_state_participates_in_next_run(self):
        key = hashlib.sha256(str(self.project.resolve()).encode()).hexdigest()[:24]
        state = (
            self.home / ".local" / "state" / "rules-architect"
            / "projects" / (key + ".json")
        )
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"schema_version": "1.0", "applied_operation_ids": ["OP-1"]}))
        first = self.run_inventory()
        self.assertEqual(first["previous_state"]["applied_operation_ids"], ["OP-1"])
        state.write_text(json.dumps({"schema_version": "1.0", "applied_operation_ids": ["OP-2"]}))
        second = self.run_inventory()
        self.assertNotEqual(first["inventory_fingerprint"], second["inventory_fingerprint"])

    def test_codex_override_wins_and_fallback_is_supported(self):
        (self.project / "AGENTS.override.md").write_text(
            "- 必须采用 override。\n"
        )
        data = self.run_inventory()
        codex_agents = [
            source for source in data["sources"]
            if source["platform"] == "codex"
            and source["kind"] == "agents_md"
            and source["scope"] == "project"
        ]
        self.assertEqual(
            [Path(source["path"]).name for source in codex_agents],
            ["AGENTS.override.md"],
        )

        (self.project / "AGENTS.override.md").unlink()
        (self.project / "AGENTS.md").unlink()
        codex_home = self.home / ".codex"
        codex_home.mkdir()
        (codex_home / "config.toml").write_text(
            'project_doc_fallback_filenames = ["GUIDE.md"]\n'
        )
        (self.project / "GUIDE.md").write_text("- Always use the fallback.\n")
        data = self.run_inventory()
        self.assertTrue(any(
            source["path"] == str((self.project / "GUIDE.md").resolve())
            and source["platform"] == "codex"
            for source in data["sources"]
        ))

    def test_repo_root_rules_and_memory_are_found_from_subdirectory(self):
        subprocess.run(
            ["git", "init", "-q", str(self.project)],
            check=True,
        )
        subdirectory = self.project / "src" / "nested"
        subdirectory.mkdir(parents=True)
        data = self.run_inventory(project_root=subdirectory)
        self.assertTrue(any(
            source["kind"] == "path_rule"
            and source["path"].endswith("proto.md")
            for source in data["sources"]
        ))
        self.assertFalse(any(
            error["code"] == "memory_not_found"
            for error in data["source_errors"]
        ))

    def test_hook_artifact_ownership_and_health_are_discovered_statically(self):
        hooks = self.home / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        managed = hooks / "managed.py"
        managed.write_text(
            "# rules-architect-id: R-managed\n"
            "# rules-architect-owner: rules-architect\n"
            "REMINDER = '不要跳过测试'\n"
        )
        modified = hooks / "modified.py"
        modified.write_text("# rules-architect-owner: rules-architect\nREMINDER = 'changed'\n")
        external = hooks / "external.py"
        external.write_text(
            "# generated-by: other-tool\n"
            "raise RuntimeError('扫描器绝不能执行此文件')\n"
        )
        shell_hook = hooks / "third-party.sh"
        shell_hook.write_text(
            "#!/bin/sh\n# generated-by: shell-hook-tool\nexit 0\n"
        )
        settings = self.project / ".claude" / "settings.json"
        settings.write_text(json.dumps({
            "hooks": {"PreToolUse": [{
                "matcher": "Bash", "hooks": [{
                    "type": "command", "command": "python3 missing.py",
                }, {
                    "type": "command", "command": "bash {}".format(shell_hook),
                }],
            }]},
        }))
        proto = self.project / ".claude" / "rules" / "nested" / "proto.md"
        proto.write_text(
            "---\npaths:\n  - \"**/*.proto\"\n---\n"
            "<!-- generated-by: path-rule-tool -->\n"
            "- 字段编号必须递增。\n"
        )
        (self.home / ".claude" / ".rules-architect-manifest.json").write_text(
            json.dumps({"installed_files": [
                {"path": str(managed), "hash_sha256": hashlib.sha256(managed.read_bytes()).hexdigest()},
                {"path": str(modified), "hash_sha256": "0" * 64},
            ]})
        )
        data = self.run_inventory()
        by_name = {
            Path(item["path"]).name: item
            for item in data["hook_artifacts"] if item.get("path")
        }
        self.assertEqual(by_name["managed.py"]["ownership"], "rules_architect")
        self.assertEqual(by_name["managed.py"]["status"], "orphan")
        self.assertTrue(by_name["managed.py"]["safe_to_modify"])
        self.assertEqual(by_name["modified.py"]["status"], "modified_orphan")
        self.assertFalse(by_name["modified.py"]["safe_to_modify"])
        self.assertEqual(by_name["external.py"]["ownership"], "external_tool")
        self.assertEqual(by_name["third-party.sh"]["ownership"], "external_tool")
        self.assertEqual(by_name["third-party.sh"]["status"], "active")
        self.assertEqual(by_name["missing.py"]["status"], "dangling_registration")
        path_rules = {Path(item["path"]).name: item for item in data["path_rule_artifacts"]}
        self.assertIn("proto.md", path_rules)
        self.assertEqual(path_rules["proto.md"]["ownership"], "external_tool")
        self.assertEqual(path_rules["proto.md"]["generator"], "path-rule-tool")


if __name__ == "__main__":
    unittest.main()
