import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

from tests._repo import REPO_ROOT

CC_GPT = os.path.join(REPO_ROOT, "bin", "cc-gpt")
FIXTURE_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures_profile.json")


class CcGptTokenSearchTests(unittest.TestCase):
    """cc-gpt must use the same token-file search as claude-mode's
    _env_search_paths: tokens.env_file, when set, pins the search to exactly
    that one file. Verified end-to-end through bash with a stub `claude` on
    PATH that just prints the exported token."""

    # Cached across tests: (found, path). Probing can take several seconds
    # per broken candidate (WSL shims, Windows Store python3 aliases), so
    # it must only ever run once per suite.
    _bash_cache = None

    @classmethod
    def _find_usable_bash(cls):
        """First bash whose environment can actually run cc-gpt: python3
        must execute (not just resolve - the Windows Store alias resolves
        but hangs), plus readlink and grep. The plain `bash` on PATH can be
        a broken WSL shim on Windows, so Git Bash is also tried."""
        if cls._bash_cache is not None:
            return cls._bash_cache[1]
        candidates = [shutil.which("bash")]
        if os.name == "nt":
            candidates.append(r"C:\Program Files\Git\bin\bash.exe")
        probe_cmd = 'python3 -c "print(1)" && command -v readlink && command -v grep'
        found = None
        for cand in candidates:
            if not cand or not os.path.isfile(cand):
                continue
            try:
                probe = subprocess.run(
                    [cand, "-c", probe_cmd],
                    capture_output=True, text=True, timeout=15,
                    stdin=subprocess.DEVNULL,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if probe.returncode == 0 and probe.stdout.strip().startswith("1"):
                found = cand
                break
        cls._bash_cache = (True, found)
        return found

    def setUp(self):
        self.bash = self._find_usable_bash()
        if not self.bash:
            self.skipTest("no bash with a working python3/readlink/grep available")

        self.home = tempfile.mkdtemp(prefix="cc-gpt-test-home-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

        # Stub `claude` that prints the token env var cc-gpt exported.
        self.stub_dir = os.path.join(self.home, "stub-bin")
        os.makedirs(self.stub_dir)
        stub = os.path.join(self.stub_dir, "claude")
        with open(stub, "w", newline="\n") as f:
            f.write('#!/usr/bin/env bash\nprintf "%s\\n" "${TEST_BEARER_TOKEN:-<unset>}"\n')
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _run_cc_gpt(self, profile_path):
        env = dict(os.environ)
        env["HOME"] = self.home
        env["CLAUDE_MODE_PROFILE"] = profile_path
        env["PATH"] = self.stub_dir + os.pathsep + env.get("PATH", "")
        return subprocess.run(
            [self.bash, CC_GPT],
            capture_output=True, text=True, timeout=60, env=env,
        )

    def _write_profile(self, env_file):
        with open(FIXTURE_PROFILE) as f:
            data = json.load(f)
        data["tokens"]["env_file"] = env_file
        path = os.path.join(self.home, "profile.json")
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def test_default_search_reads_home_env(self):
        with open(os.path.join(self.home, ".env"), "w") as f:
            f.write("TEST_BEARER_TOKEN=home-env-token\n")
        result = self._run_cc_gpt(self._write_profile(None))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "home-env-token")

    def test_tokens_env_file_override_pins_the_search(self):
        # The key sits in ~/.env too, but the override names another file:
        # only the overridden file may be consulted, same as claude-mode.
        with open(os.path.join(self.home, ".env"), "w") as f:
            f.write("TEST_BEARER_TOKEN=wrong-token\n")
        custom = os.path.join(self.home, "custom.env").replace("\\", "/")
        with open(custom, "w") as f:
            f.write("TEST_BEARER_TOKEN=custom-file-token\n")
        result = self._run_cc_gpt(self._write_profile(custom))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "custom-file-token")


if __name__ == "__main__":
    unittest.main()
