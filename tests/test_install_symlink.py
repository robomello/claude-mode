import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests._repo import BIN_CLAUDE_MODE

FIXTURE_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures_profile.json")


class InstalledSymlinkTests(unittest.TestCase):
    """Regression test for the realpath/abspath bug: bin/claude-mode resolved
    its own location with os.path.abspath(__file__), which does not follow
    symlinks. install.sh always installs via symlink, so every real install
    crashed with ModuleNotFoundError the moment it ran through the symlink.

    tests/_repo.py's load_bin_claude_mode() imports bin/claude-mode by its
    real path via importlib, which is exactly why that bug stayed invisible
    to every other test in this suite - __file__ never went through a
    symlink there either. This test deliberately runs the script as a
    subprocess through a symlink, the same way install.sh's output is
    actually invoked, so it can't be hidden the same way again.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="claude-mode-test-symlink-home-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

        install_dir = os.path.join(self.home, ".local", "bin")
        os.makedirs(install_dir)
        self.symlink_path = os.path.join(install_dir, "claude-mode")
        os.symlink(BIN_CLAUDE_MODE, self.symlink_path)

        with open(os.path.join(self.home, ".env"), "w") as f:
            f.write("TEST_BEARER_TOKEN=fixture-token-value\n")

    def test_status_runs_clean_through_installed_symlink(self):
        env = dict(os.environ)
        env["HOME"] = self.home
        env["CLAUDE_MODE_PROFILE"] = FIXTURE_PROFILE

        result = subprocess.run(
            [sys.executable, self.symlink_path, "status"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        self.assertEqual(
            result.returncode, 0,
            f"symlinked claude-mode exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertNotIn("ModuleNotFoundError", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("Active backend", result.stdout)


if __name__ == "__main__":
    unittest.main()
