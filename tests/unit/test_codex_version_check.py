import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from install_codex_hooks import check_codex_version


class CodexVersionCheckTest(unittest.TestCase):
    def check(self, *args, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return check_codex_version(*args, **kwargs)

    @mock.patch("install_codex_hooks.subprocess.run")
    def test_current_cli_passes(self, run):
        run.return_value = subprocess.CompletedProcess(
            ["codex", "--version"], 0, "codex-cli 0.146.0\n", ""
        )
        self.assertTrue(self.check(skip=False))

    @mock.patch("install_codex_hooks.subprocess.run")
    def test_old_cli_warns_but_does_not_block_by_default(self, run):
        run.return_value = subprocess.CompletedProcess(
            ["codex", "--version"], 0, "codex-cli 0.100.0\n", ""
        )
        self.assertTrue(self.check(skip=False))
        self.assertFalse(self.check(skip=False, strict=True))

    @mock.patch("install_codex_hooks.subprocess.run")
    def test_missing_cli_warns_but_does_not_block_desktop_client(self, run):
        run.side_effect = FileNotFoundError("codex")
        self.assertTrue(self.check(skip=False))
        self.assertFalse(self.check(skip=False, strict=True))

    @mock.patch("install_codex_hooks.subprocess.run")
    def test_failed_cli_is_non_blocking_unless_strict(self, run):
        run.return_value = subprocess.CompletedProcess(
            ["codex", "--version"], 1, "", "launcher failed"
        )
        self.assertTrue(self.check(skip=False))
        self.assertFalse(self.check(skip=False, strict=True))

    @mock.patch("install_codex_hooks.subprocess.run")
    def test_skip_does_not_invoke_cli(self, run):
        self.assertTrue(self.check(skip=True, strict=False))
        run.assert_not_called()

    def test_full_install_succeeds_without_codex_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            bin_dir = Path(temporary) / "bin"
            home.mkdir()
            bin_dir.mkdir()
            python_link = bin_dir / "python3"
            python_link.symlink_to(Path(sys.executable))
            env = dict(os.environ)
            env["HOME"] = str(home)
            env["PATH"] = str(bin_dir)
            process = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "install_codex_hooks.py"),
                    "--non-interactive",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn("找不到独立 `codex` CLI", process.stdout)
            self.assertTrue(
                (home / ".codex" / "hooks" / "memory_intake_check.py").is_file()
            )

    def test_strict_mode_stops_before_writing_for_old_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            bin_dir = Path(temporary) / "bin"
            home.mkdir()
            bin_dir.mkdir()
            (bin_dir / "python3").symlink_to(Path(sys.executable))
            codex = bin_dir / "codex"
            codex.write_text("#!/bin/sh\necho 'codex-cli 0.100.0'\n")
            codex.chmod(0o755)
            env = dict(os.environ)
            env["HOME"] = str(home)
            env["PATH"] = str(bin_dir)
            process = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "install_codex_hooks.py"),
                    "--non-interactive",
                    "--strict-version-check",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(process.returncode, 2)
            self.assertIn("严格版本检查已启用", process.stderr)
            self.assertFalse((home / ".codex" / "hooks").exists())


if __name__ == "__main__":
    unittest.main()
