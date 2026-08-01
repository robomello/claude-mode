import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from tests._repo import REPO_ROOT, load_bin_claude_mode  # noqa: F401

from lib.profile import Profile
from lib import settings as cm_settings

FIXTURE_PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures_profile.json")

BASE_SETTINGS = {
    "someOtherTool": {"keep": "me"},
    "env": {
        "CUSTOM_UNMANAGED": "keep-me-too",
    },
}


class ModeSwitchTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="claude-mode-test-home-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        os.makedirs(os.path.join(self.home, ".claude"), exist_ok=True)
        self.settings_path = os.path.join(self.home, ".claude", "settings.json")
        with open(os.path.join(self.home, ".env"), "w") as f:
            f.write("TEST_BEARER_TOKEN=fixture-token-value\n")

        self._old_home = os.environ.get("HOME")
        self._old_profile = os.environ.get("CLAUDE_MODE_PROFILE")
        os.environ["HOME"] = self.home
        os.environ["CLAUDE_MODE_PROFILE"] = FIXTURE_PROFILE
        self.addCleanup(self._restore_env)

        self.cm = load_bin_claude_mode()
        self.profile = Profile(path=FIXTURE_PROFILE)

    def _restore_env(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        if self._old_profile is None:
            os.environ.pop("CLAUDE_MODE_PROFILE", None)
        else:
            os.environ["CLAUDE_MODE_PROFILE"] = self._old_profile

    def _fresh_cfg(self, extra_env=None):
        cfg = json.loads(json.dumps(BASE_SETTINGS))
        if extra_env:
            cfg["env"].update(extra_env)
        return cfg

    def test_oauth_strips_bedrock_keys_and_sets_force_login(self):
        cfg = self._fresh_cfg({
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "ANTHROPIC_BEDROCK_BASE_URL": "http://127.0.0.1:8104",
            "AWS_BEARER_TOKEN_BEDROCK": "should-be-removed",
        })
        self.cm.set_oauth(cfg, self.profile)

        for key in ("CLAUDE_CODE_USE_BEDROCK", "ANTHROPIC_BEDROCK_BASE_URL", "AWS_BEARER_TOKEN_BEDROCK"):
            self.assertNotIn(key, cfg["env"])
        self.assertEqual(cfg.get("forceLoginMethod"), "claudeai")
        self.assertEqual(cfg["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"], "test-oauth-sonnet")
        self.assertEqual(cfg["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"], "test-oauth-opus")
        self.assertEqual(cfg["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "test-oauth-haiku")
        self.assertEqual(cfg["env"]["ANTHROPIC_SMALL_FAST_MODEL"], "test-oauth-haiku")
        # unknown keys preserved
        self.assertEqual(cfg["someOtherTool"], {"keep": "me"})
        self.assertEqual(cfg["env"]["CUSTOM_UNMANAGED"], "keep-me-too")

    def test_nexus_sets_bedrock_env_and_strips_force_login(self):
        cfg = self._fresh_cfg()
        cfg["forceLoginMethod"] = "claudeai"
        self.cm.set_nexus(cfg, self.profile)

        self.assertEqual(cfg["env"]["CLAUDE_CODE_USE_BEDROCK"], "1")
        self.assertEqual(cfg["env"]["ANTHROPIC_BEDROCK_BASE_URL"], "http://127.0.0.1:8104")
        self.assertEqual(cfg["env"]["AWS_BEARER_TOKEN_BEDROCK"], "fixture-token-value")
        self.assertEqual(cfg["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"], "test-nexus-sonnet")
        self.assertEqual(cfg["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"], "test-nexus-opus")
        self.assertNotIn("forceLoginMethod", cfg)
        self.assertEqual(cfg["env"]["CUSTOM_UNMANAGED"], "keep-me-too")

    def test_gpt_sets_gpt_models_and_bedrock_env(self):
        cfg = self._fresh_cfg()
        self.cm.set_gpt(cfg, self.profile)

        self.assertEqual(cfg["env"]["CLAUDE_CODE_USE_BEDROCK"], "1")
        self.assertEqual(cfg["env"]["AWS_BEARER_TOKEN_BEDROCK"], "fixture-token-value")
        self.assertEqual(cfg["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"], "test-gpt-sonnet")
        self.assertEqual(cfg["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"], "test-gpt-opus")
        self.assertEqual(cfg["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "test-gpt-haiku")
        self.assertNotIn("forceLoginMethod", cfg)

    def test_gpt_falls_back_to_secondary_token_env(self):
        # primary token absent, only the fallback env var is set
        with open(os.path.join(self.home, ".env"), "w") as f:
            f.write("TEST_FALLBACK_TOKEN=fallback-token-value\n")
        cfg = self._fresh_cfg()
        self.cm.set_gpt(cfg, self.profile)
        self.assertEqual(cfg["env"]["AWS_BEARER_TOKEN_BEDROCK"], "fallback-token-value")

    def test_local_sets_local_models_and_bedrock_env(self):
        cfg = self._fresh_cfg()
        # local_health_ok does a real (loopback, non-fatal) probe; stub it out
        # so the test has zero network dependency either way.
        self.cm.local_health_ok = lambda profile: True
        self.cm.set_local(cfg, self.profile)

        self.assertEqual(cfg["env"]["CLAUDE_CODE_USE_BEDROCK"], "1")
        self.assertEqual(cfg["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"], "test-local-model")
        self.assertEqual(cfg["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"], "test-local-model")
        self.assertNotIn("forceLoginMethod", cfg)

    def test_local_uses_dummy_token_when_none_configured(self):
        os.remove(os.path.join(self.home, ".env"))
        cfg = self._fresh_cfg()
        self.cm.local_health_ok = lambda profile: True
        self.cm.set_local(cfg, self.profile)
        self.assertEqual(cfg["env"]["AWS_BEARER_TOKEN_BEDROCK"], "local-bypass")

    def test_current_mode_detailed_distinguishes_all_four(self):
        cfg = self._fresh_cfg()
        self.assertEqual(self.cm.current_mode_detailed(cfg, self.profile), "oauth")

        nexus_cfg = self._fresh_cfg()
        self.cm.set_nexus(nexus_cfg, self.profile)
        self.assertEqual(self.cm.current_mode_detailed(nexus_cfg, self.profile), "nexus")

        gpt_cfg = self._fresh_cfg()
        self.cm.set_gpt(gpt_cfg, self.profile)
        self.assertEqual(self.cm.current_mode_detailed(gpt_cfg, self.profile), "gpt")

        local_cfg = self._fresh_cfg()
        self.cm.local_health_ok = lambda profile: True
        self.cm.set_local(local_cfg, self.profile)
        self.assertEqual(self.cm.current_mode_detailed(local_cfg, self.profile), "local")

    def test_switch_end_to_end_via_settings_file(self):
        with open(self.settings_path, "w") as f:
            json.dump(self._fresh_cfg(), f)
        # Bypass the real network probe - covered separately by profile/URL
        # validation and by manual verification against a live proxy.
        self.cm.proxy_ok = lambda profile: True
        self.cm.switch("nexus", self.profile)

        reloaded = cm_settings.load(self.settings_path)
        self.assertEqual(reloaded["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"], "test-nexus-sonnet")
        self.assertEqual(reloaded["someOtherTool"], {"keep": "me"})

    def test_switch_prints_tunnel_command_when_proxy_down_and_tunnel_configured(self):
        with open(self.settings_path, "w") as f:
            json.dump(self._fresh_cfg(), f)
        self.cm.proxy_ok = lambda profile: False
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                self.cm.switch("nexus", self.profile)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("claude-mode-tunnel up", buf.getvalue())

    def test_switch_plain_abort_when_no_tunnel_configured(self):
        no_tunnel_profile_path = os.path.join(tempfile.mkdtemp(), "no-tunnel-profile.json")
        with open(FIXTURE_PROFILE) as f:
            data = json.load(f)
        data["tunnel"]["host"] = None
        with open(no_tunnel_profile_path, "w") as f:
            json.dump(data, f)
        no_tunnel_profile = Profile(path=no_tunnel_profile_path)

        with open(self.settings_path, "w") as f:
            json.dump(self._fresh_cfg(), f)
        self.cm.proxy_ok = lambda profile: False
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                self.cm.switch("nexus", no_tunnel_profile)
        self.assertEqual(ctx.exception.code, 1)
        self.assertNotIn("claude-mode-tunnel", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
