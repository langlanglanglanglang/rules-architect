import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class InstallRollbackTest(unittest.TestCase):
    def test_claude_abort_restores_earlier_file_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            hooks = home / ".claude" / "hooks"
            hooks.mkdir(parents=True)
            conflict = hooks / "rule_intake_reminder.py"
            conflict.write_text("third-party\n")
            env = dict(os.environ, HOME=str(home))
            proc = subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "scripts" / "install_hooks.py"),
                    "--skip-version-check", "--skip-plugin-check",
                ],
                input="a\n", text=True, capture_output=True, env=env,
            )
            self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
            self.assertFalse((hooks / "memory_intake_check.py").exists())
            self.assertEqual(conflict.read_text(), "third-party\n")
            self.assertFalse(
                (home / ".claude" / ".rules-architect-manifest.json").exists()
            )


if __name__ == "__main__":
    unittest.main()
