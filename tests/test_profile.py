import json
import os
import tempfile
import unittest

from tests._repo import REPO_ROOT  # noqa: F401 ensures repo root on sys.path

from lib.profile import Profile, ProfileError, DEFAULTS


class ProfileTests(unittest.TestCase):
    def _write(self, data):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_missing_key_names_the_exact_key(self):
        path = self._write({})
        prof = Profile(path=path)
        with self.assertRaises(ProfileError) as ctx:
            prof.get("nonexistent.made.up.key")
        self.assertIn("nonexistent.made.up.key", str(ctx.exception))

    def test_malformed_url_rejected(self):
        path = self._write({"bedrock": {"base_url": "not-a-url", "port": 8104}})
        with self.assertRaises(ProfileError) as ctx:
            Profile(path=path)
        self.assertIn("bedrock.base_url", str(ctx.exception))

    def test_url_missing_scheme_rejected(self):
        path = self._write({"local": {"base_url": "127.0.0.1:8901", "port": 8901}})
        with self.assertRaises(ProfileError) as ctx:
            Profile(path=path)
        self.assertIn("local.base_url", str(ctx.exception))

    def test_url_missing_host_rejected(self):
        path = self._write({"bedrock": {"base_url": "http://", "port": 8104}})
        with self.assertRaises(ProfileError):
            Profile(path=path)

    def test_out_of_range_port_rejected_too_high(self):
        path = self._write({"bedrock": {"base_url": "http://localhost:8104", "port": 70000}})
        with self.assertRaises(ProfileError) as ctx:
            Profile(path=path)
        self.assertIn("bedrock.port", str(ctx.exception))

    def test_out_of_range_port_rejected_zero(self):
        path = self._write({"local": {"base_url": "http://localhost:8901", "port": 0}})
        with self.assertRaises(ProfileError):
            Profile(path=path)

    def test_non_numeric_port_rejected(self):
        path = self._write({"bedrock": {"base_url": "http://localhost:8104", "port": "not-a-port"}})
        with self.assertRaises(ProfileError):
            Profile(path=path)

    def test_defaults_apply_when_profile_partial(self):
        path = self._write({"tunnel": {"host": "example.invalid"}})
        prof = Profile(path=path)
        # explicitly set value comes from the profile
        self.assertEqual(prof.get("tunnel.host"), "example.invalid")
        # everything else falls back to the built-in generic default
        self.assertEqual(prof.get("bedrock.base_url"), DEFAULTS["bedrock"]["base_url"])
        self.assertEqual(prof.get("bedrock.port"), DEFAULTS["bedrock"]["port"])
        self.assertEqual(prof.get("models.oauth.opus"), DEFAULTS["models"]["oauth"]["opus"])
        self.assertEqual(prof.get("toggle_cycle"), DEFAULTS["toggle_cycle"])

    def test_missing_profile_file_uses_pure_defaults(self):
        missing_path = os.path.join(tempfile.mkdtemp(), "does-not-exist.json")
        prof = Profile(path=missing_path)
        self.assertEqual(prof.get("bedrock.port"), DEFAULTS["bedrock"]["port"])

    def test_get_or_returns_fallback_without_raising(self):
        path = self._write({})
        prof = Profile(path=path)
        self.assertEqual(prof.get_or("nonexistent.key", "fallback-value"), "fallback-value")

    def test_null_value_is_a_valid_resolution(self):
        # tunnel.host defaults to null / None - that's a legitimate resolved
        # value, not a missing key.
        path = self._write({})
        prof = Profile(path=path)
        self.assertIsNone(prof.get("tunnel.host"))

    def test_cli_get_prints_value_and_exits_zero(self):
        import subprocess
        import sys

        path = self._write({"bedrock": {"base_url": "http://localhost:9999", "port": 9999}})
        profile_py = os.path.join(REPO_ROOT, "lib", "profile.py")
        out = subprocess.run(
            [sys.executable, profile_py, "--get", "bedrock.port"],
            capture_output=True, text=True,
            env={**os.environ, "CLAUDE_MODE_PROFILE": path},
        )
        self.assertEqual(out.returncode, 0)
        self.assertEqual(out.stdout.strip(), "9999")

    def test_cli_get_missing_key_exits_nonzero_with_stderr(self):
        import subprocess
        import sys

        path = self._write({})
        profile_py = os.path.join(REPO_ROOT, "lib", "profile.py")
        out = subprocess.run(
            [sys.executable, profile_py, "--get", "totally.missing.key"],
            capture_output=True, text=True,
            env={**os.environ, "CLAUDE_MODE_PROFILE": path},
        )
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("totally.missing.key", out.stderr)


if __name__ == "__main__":
    unittest.main()
