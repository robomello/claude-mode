import json
import os
import shutil
import tempfile
import unittest

from tests._repo import REPO_ROOT  # noqa: F401 ensures repo root on sys.path

from lib.profile import Profile, ProfileError, DEFAULTS, _profile_path


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
        self.assertEqual(prof.get("toggle_cycle"), DEFAULTS["toggle_cycle"])

    def test_model_ids_have_no_generic_default(self):
        # A real model ID has no sane generic value: resolving one without a
        # profile entry must raise, naming the key - never hand back a
        # placeholder that would get written into settings.json.
        prof = Profile(path=self._write({}))
        with self.assertRaises(ProfileError) as ctx:
            prof.get("models.oauth.opus")
        self.assertIn("models.oauth.opus", str(ctx.exception))
        with self.assertRaises(ProfileError):
            prof.get("models.nexus.sonnet")

    def test_missing_profile_file_leaves_model_ids_unresolved(self):
        # A lost/unfound profile.json must not silently resolve to
        # placeholder model ids (the file simply not being found is exactly
        # the failure this guards against).
        missing_path = os.path.join(tempfile.mkdtemp(), "does-not-exist.json")
        prof = Profile(path=missing_path)
        with self.assertRaises(ProfileError) as ctx:
            prof.get("models.nexus.sonnet")
        self.assertIn("models.nexus.sonnet", str(ctx.exception))

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

    def test_test_timeout_default_and_override(self):
        # default resolves from DEFAULTS...
        prof = Profile(path=self._write({}))
        self.assertEqual(prof.get("test.timeout_seconds"), 20)
        # ...and a profile override wins.
        prof = Profile(path=self._write({"test": {"timeout_seconds": 45}}))
        self.assertEqual(prof.get("test.timeout_seconds"), 45)

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


class ProfilePathTests(unittest.TestCase):
    """Resolution order of _profile_path(): env override, then
    ~/.claude/claude-mode/, then the XDG path, with the ~/.claude path as
    the canonical answer when neither file exists yet."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="claude-mode-test-home-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self._saved = {
            key: os.environ.get(key)
            for key in ("HOME", "CLAUDE_MODE_HOME", "XDG_CONFIG_HOME", "CLAUDE_MODE_PROFILE")
        }
        self.addCleanup(self._restore_env)
        os.environ["HOME"] = self.home
        # HOME alone is ignored on native Windows (claude-mode follows the
        # CLI's %USERPROFILE% there); CLAUDE_MODE_HOME is the explicit
        # cross-platform test override.
        os.environ["CLAUDE_MODE_HOME"] = self.home
        os.environ.pop("XDG_CONFIG_HOME", None)
        os.environ.pop("CLAUDE_MODE_PROFILE", None)
        self.claude_profile = os.path.join(self.home, ".claude", "claude-mode", "profile.json")
        self.xdg_profile = os.path.join(self.home, ".config", "claude-mode", "profile.json")

    def _restore_env(self):
        for key, val in self._saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    def _touch(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("{}")

    def test_env_override_always_wins(self):
        self._touch(self.claude_profile)
        self._touch(self.xdg_profile)
        os.environ["CLAUDE_MODE_PROFILE"] = "/explicit/override.json"
        self.assertEqual(_profile_path(), "/explicit/override.json")

    def test_claude_path_preferred_when_it_exists(self):
        self._touch(self.claude_profile)
        self._touch(self.xdg_profile)
        self.assertEqual(_profile_path(), self.claude_profile)

    def test_xdg_fallback_when_only_it_exists(self):
        self._touch(self.xdg_profile)
        self.assertEqual(_profile_path(), self.xdg_profile)

    def test_xdg_config_home_env_respected(self):
        xdg_base = tempfile.mkdtemp(prefix="claude-mode-test-xdg-")
        self.addCleanup(shutil.rmtree, xdg_base, ignore_errors=True)
        os.environ["XDG_CONFIG_HOME"] = xdg_base
        custom_xdg = os.path.join(xdg_base, "claude-mode", "profile.json")
        self._touch(custom_xdg)
        self.assertEqual(_profile_path(), custom_xdg)

    def test_claude_path_is_canonical_when_neither_exists(self):
        self.assertEqual(_profile_path(), self.claude_profile)


if __name__ == "__main__":
    unittest.main()
