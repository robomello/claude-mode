import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests._repo import REPO_ROOT

from lib import platform as cm_platform

PLATFORMS = {"macos", "windows", "wsl", "linux"}
PLATFORM_PY = os.path.join(REPO_ROOT, "lib", "platform.py")


@contextlib.contextmanager
def env(**overrides):
    """Set env vars for the duration of the block; a None value unsets."""
    saved = {k: os.environ.get(k) for k in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class DetectTests(unittest.TestCase):
    def test_detect_returns_a_known_platform(self):
        self.assertIn(cm_platform.detect(), PLATFORMS)

    def test_detect_agrees_with_sys_platform(self):
        expected = {"darwin": "macos", "win32": "windows"}.get(sys.platform)
        if expected is None:
            self.skipTest(f"no fixed expectation for sys.platform={sys.platform!r}")
        self.assertEqual(cm_platform.detect(), expected)


class RunAsScriptTests(unittest.TestCase):
    """install.sh and uninstall.sh execute lib/platform.py as a script, which
    puts lib/ first on sys.path. Anything in it importing a stdlib module that
    shares a name with a file in lib/ - `platform` above all - then silently
    imports the sibling instead and blows up on first attribute access.
    Importing the module in-process cannot catch that (there it is lib.platform,
    a package submodule, and `import platform` still finds the stdlib); only a
    subprocess reproduces the real invocation.
    """

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, PLATFORM_PY, *args],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_bare_invocation_prints_a_platform(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn(result.stdout.strip(), PLATFORMS)

    def test_install_dir_flag_prints_a_path(self):
        result = self._run("--install-dir")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertTrue(result.stdout.strip())

    def test_home_flag_prints_a_path(self):
        result = self._run("--home")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertTrue(result.stdout.strip())


class HomeTests(unittest.TestCase):
    def test_claude_mode_home_override_wins(self):
        with env(CLAUDE_MODE_HOME=os.path.join("somewhere", "explicit")):
            self.assertEqual(cm_platform.home(), os.path.join("somewhere", "explicit"))

    def test_shell_home_is_honored_on_posix_and_ignored_on_windows(self):
        # The whole point of resolving HOME here rather than in the shell:
        # Git Bash on Windows routinely points $HOME at a corporate network
        # share, while the claude CLI reads %USERPROFILE%. install.sh must
        # follow the CLI, or it writes profile.json where nothing reads it.
        with env(CLAUDE_MODE_HOME=None, HOME=os.path.join("shell", "home")):
            if os.name == "nt":
                self.assertNotEqual(cm_platform.home(), os.path.join("shell", "home"))
            else:
                self.assertEqual(cm_platform.home(), os.path.join("shell", "home"))

    def test_home_matches_profile_module_resolution(self):
        # These are deliberately separate implementations (platform.py imports
        # nothing from its siblings); this pins them together.
        from lib import profile as cm_profile

        with env(CLAUDE_MODE_HOME=None):
            self.assertEqual(cm_platform.home(), cm_profile._home())


class InstallDirTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="claude-mode-test-platform-home-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def test_install_dir_is_local_bin_under_home(self):
        with env(CLAUDE_MODE_HOME=self.home):
            self.assertEqual(
                cm_platform.install_dir(),
                os.path.join(self.home, ".local", "bin"),
            )

    def test_is_on_path_ignores_case_and_separator_differences(self):
        with env(CLAUDE_MODE_HOME=self.home):
            target = cm_platform.install_dir()
            # A spelling that differs only in normalizable ways - on Windows
            # that includes case and backslash-vs-slash, which is exactly how
            # PATH and install_dir() disagree there in practice.
            variant = os.path.join(target, ".")
            if os.name == "nt":
                variant = variant.upper().replace("\\", "/")
            with env(PATH=os.pathsep.join([variant, os.path.join(self.home, "other")])):
                self.assertTrue(cm_platform.is_on_path())

    def test_is_on_path_is_false_when_absent(self):
        with env(CLAUDE_MODE_HOME=self.home, PATH=os.path.join(self.home, "elsewhere")):
            self.assertFalse(cm_platform.is_on_path())


@unittest.skipUnless(shutil.which("sh"), "no POSIX sh on PATH")
class InstallDryRunTests(unittest.TestCase):
    """install.sh is the one thing a new user runs before anything else works.
    A dry run exercises its whole path - interpreter probe, platform branch,
    home resolution - without touching the machine."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="claude-mode-test-install-home-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.env = dict(os.environ)
        self.env["CLAUDE_MODE_HOME"] = self.home
        self.env.pop("XDG_CONFIG_HOME", None)

    def _run(self, script):
        return subprocess.run(
            ["sh", script, "--dry-run"],
            cwd=REPO_ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_install_dry_run_succeeds_and_writes_nothing(self):
        result = self._run("install.sh")
        self.assertEqual(result.returncode, 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        self.assertIn("install.sh: done", result.stdout)
        self.assertEqual(os.listdir(self.home), [], "dry run created files under HOME")

    def test_install_dry_run_targets_the_resolved_home_not_shell_home(self):
        result = self._run("install.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(".local", result.stdout)
        # Every bin/ script must be accounted for, whether linked or shimmed.
        # Directories (a stray __pycache__ from `make pycompile`) are not
        # scripts and install.sh is right to skip them.
        bin_dir = os.path.join(REPO_ROOT, "bin")
        for name in os.listdir(bin_dir):
            if not os.path.isfile(os.path.join(bin_dir, name)):
                continue
            self.assertIn(name, result.stdout, f"install.sh never mentions bin/{name}")

    def test_uninstall_dry_run_succeeds(self):
        result = self._run("uninstall.sh")
        self.assertEqual(result.returncode, 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        self.assertIn("uninstall.sh: done", result.stdout)


if __name__ == "__main__":
    unittest.main()
