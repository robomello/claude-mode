import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from unittest import mock

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
        self._old_cm_home = os.environ.get("CLAUDE_MODE_HOME")
        self._old_profile = os.environ.get("CLAUDE_MODE_PROFILE")
        os.environ["HOME"] = self.home
        # HOME alone is ignored on native Windows (claude-mode follows the
        # CLI's %USERPROFILE% there); CLAUDE_MODE_HOME is the explicit
        # cross-platform test override.
        os.environ["CLAUDE_MODE_HOME"] = self.home
        os.environ["CLAUDE_MODE_PROFILE"] = FIXTURE_PROFILE
        self.addCleanup(self._restore_env)

        self.cm = load_bin_claude_mode()
        self.profile = Profile(path=FIXTURE_PROFILE)

    def _restore_env(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        if self._old_cm_home is None:
            os.environ.pop("CLAUDE_MODE_HOME", None)
        else:
            os.environ["CLAUDE_MODE_HOME"] = self._old_cm_home
        if self._old_profile is None:
            os.environ.pop("CLAUDE_MODE_PROFILE", None)
        else:
            os.environ["CLAUDE_MODE_PROFILE"] = self._old_profile

    def _fresh_cfg(self, extra_env=None):
        cfg = json.loads(json.dumps(BASE_SETTINGS))
        if extra_env:
            cfg["env"].update(extra_env)
        return cfg

    def _write_env_file(self, relpath, content):
        path = os.path.join(self.home, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

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

    def test_gpt_requires_the_shared_nexus_token(self):
        # A separate GPT token is intentionally not supported: both Nexus
        # modes must use the same profile.tokens.bedrock_env value.
        with open(os.path.join(self.home, ".env"), "w") as f:
            f.write("TEST_FALLBACK_TOKEN=fallback-token-value\n")
        cfg = self._fresh_cfg()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                self.cm.set_gpt(cfg, self.profile)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("TEST_BEARER_TOKEN", buf.getvalue())

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

    def _direct_local_profile(self):
        """Fixture profile with local.transport flipped to "direct"."""
        with open(FIXTURE_PROFILE) as f:
            raw = json.load(f)
        raw["local"] = dict(raw["local"], transport="direct")
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(raw, f)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return Profile(path=path)

    def test_local_direct_transport_sets_anthropic_base_url_not_bedrock(self):
        profile = self._direct_local_profile()
        cfg = self._fresh_cfg()
        self.cm.local_health_ok = lambda profile: True
        self.cm.set_local(cfg, profile)

        self.assertEqual(cfg["env"]["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8901")
        self.assertEqual(cfg["env"]["ANTHROPIC_AUTH_TOKEN"], "local-direct")
        self.assertEqual(cfg["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"], "test-local-model")
        # The Bedrock path must be fully torn down, not left dangling beside it.
        for key in ("CLAUDE_CODE_USE_BEDROCK", "ANTHROPIC_BEDROCK_BASE_URL",
                    "AWS_BEARER_TOKEN_BEDROCK"):
            self.assertNotIn(key, cfg["env"])
        self.assertNotIn("forceLoginMethod", cfg)
        self.assertEqual(cfg["env"]["CUSTOM_UNMANAGED"], "keep-me-too")

    def test_local_direct_transport_is_detected_and_distinct_from_oauth(self):
        profile = self._direct_local_profile()
        cfg = self._fresh_cfg()
        self.cm.local_health_ok = lambda profile: True
        self.cm.set_local(cfg, profile)
        self.assertEqual(self.cm.current_mode_detailed(cfg, profile), "local")
        # Same env minus the model id match is not silently "oauth" either.
        near_miss = dict(cfg, env=dict(cfg["env"],
                                       ANTHROPIC_DEFAULT_SONNET_MODEL="test-local-model-2"))
        self.assertEqual(self.cm.current_mode_detailed(near_miss, profile), "unknown")

    def test_switching_off_direct_local_removes_its_env_keys(self):
        # A stale ANTHROPIC_BASE_URL left behind would silently keep pointing
        # the next backend at the local server.
        profile = self._direct_local_profile()
        cfg = self._fresh_cfg()
        self.cm.local_health_ok = lambda profile: True
        self.cm.set_local(cfg, profile)
        self.cm.set_oauth(cfg, profile)
        self.assertNotIn("ANTHROPIC_BASE_URL", cfg["env"])
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", cfg["env"])

        cfg2 = self._fresh_cfg()
        self.cm.set_local(cfg2, profile)
        self.cm.set_nexus(cfg2, profile)
        self.assertNotIn("ANTHROPIC_BASE_URL", cfg2["env"])
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", cfg2["env"])

    def test_bedrock_transport_remains_the_default_for_local(self):
        # Profiles written before local.transport existed must keep the
        # proxied behavior with no edit.
        self.assertEqual(self.cm.local_transport(self.profile), "bedrock")

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

    def test_current_mode_detailed_returns_unknown_for_unrecognized_id(self):
        # gpt-family near-miss: one character off the fixture's exact id
        gpt_near_miss = self._fresh_cfg({
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "ANTHROPIC_BEDROCK_BASE_URL": "http://127.0.0.1:8104",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "test-gpt-sonnet-2",
        })
        self.assertEqual(self.cm.current_mode_detailed(gpt_near_miss, self.profile), "unknown")

        # local-family near-miss
        local_near_miss = self._fresh_cfg({
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "ANTHROPIC_BEDROCK_BASE_URL": "http://127.0.0.1:8104",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "test-local-model-2",
        })
        self.assertEqual(self.cm.current_mode_detailed(local_near_miss, self.profile), "unknown")

    def test_toggle_aborts_from_unknown_state_without_writing_settings(self):
        unknown_cfg = self._fresh_cfg({
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "ANTHROPIC_BEDROCK_BASE_URL": "http://127.0.0.1:8104",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "test-gpt-sonnet-2",
        })
        with open(self.settings_path, "w") as f:
            json.dump(unknown_cfg, f)
        with open(self.settings_path, "rb") as f:
            before = f.read()

        old_argv = list(__import__("sys").argv)
        __import__("sys").argv = ["claude-mode", "toggle"]
        self.addCleanup(lambda: setattr(__import__("sys"), "argv", old_argv))

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                self.cm.main()
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertIn("ABORT", buf.getvalue())
        self.assertIn("UNKNOWN", buf.getvalue())

        with open(self.settings_path, "rb") as f:
            after = f.read()
        self.assertEqual(before, after, "toggle must not write settings.json when starting from UNKNOWN")

    def _profile_variant(self, mutate):
        with open(FIXTURE_PROFILE) as f:
            data = json.load(f)
        mutate(data)
        path = os.path.join(tempfile.mkdtemp(), "variant-profile.json")
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def _run_main(self, *argv):
        old_argv = list(__import__("sys").argv)
        __import__("sys").argv = ["claude-mode", *argv]
        self.addCleanup(lambda: setattr(__import__("sys"), "argv", old_argv))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.cm.main()
        return buf.getvalue()

    def test_toggle_cycle_accepts_canonical_cli_names(self):
        # toggle_cycle entries written as the canonical CLI command names
        # ("nexus-claude", "nexus-gpt") must reach the mode they name -
        # not fall through switch()'s else-branch into oauth.
        variant = self._profile_variant(lambda d: d.update(
            toggle_cycle=["oauth", "nexus-claude", "nexus-gpt", "local"]))
        os.environ["CLAUDE_MODE_PROFILE"] = variant
        with open(self.settings_path, "w") as f:
            json.dump(self._fresh_cfg(), f)  # detected mode: oauth
        self.cm.proxy_ok = lambda profile, mode: True

        out = self._run_main("toggle")

        reloaded = cm_settings.load(self.settings_path)
        self.assertEqual(reloaded["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"], "test-nexus-sonnet")
        self.assertEqual(reloaded["env"]["CLAUDE_CODE_USE_BEDROCK"], "1")
        self.assertIn("NEXUS", out)

    def test_toggle_cycle_unknown_entry_aborts_without_writing_settings(self):
        variant = self._profile_variant(lambda d: d.update(
            toggle_cycle=["oauth", "frobnicate"]))
        os.environ["CLAUDE_MODE_PROFILE"] = variant
        with open(self.settings_path, "w") as f:
            json.dump(self._fresh_cfg(), f)
        with open(self.settings_path, "rb") as f:
            before = f.read()
        self.cm.proxy_ok = lambda profile, mode: True

        buf = io.StringIO()
        old_argv = list(__import__("sys").argv)
        __import__("sys").argv = ["claude-mode", "toggle"]
        self.addCleanup(lambda: setattr(__import__("sys"), "argv", old_argv))
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                self.cm.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("frobnicate", buf.getvalue())
        self.assertIn("ABORT", buf.getvalue())

        with open(self.settings_path, "rb") as f:
            after = f.read()
        self.assertEqual(before, after)

    def test_switch_rejects_unknown_target_instead_of_defaulting_to_oauth(self):
        with open(self.settings_path, "w") as f:
            json.dump(self._fresh_cfg({
                "CLAUDE_CODE_USE_BEDROCK": "1",
                "ANTHROPIC_BEDROCK_BASE_URL": "http://127.0.0.1:8104",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": "test-nexus-sonnet",
            }), f)
        with open(self.settings_path, "rb") as f:
            before = f.read()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                self.cm.switch("nexus-claude", self.profile)  # not canonicalized
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("unknown mode", buf.getvalue())
        with open(self.settings_path, "rb") as f:
            after = f.read()
        self.assertEqual(before, after)

    def test_switch_end_to_end_via_settings_file(self):
        with open(self.settings_path, "w") as f:
            json.dump(self._fresh_cfg(), f)
        # Bypass the real network probe - covered separately by profile/URL
        # validation and by manual verification against a live proxy.
        self.cm.proxy_ok = lambda profile, mode: True
        self.cm.switch("nexus", self.profile)

        reloaded = cm_settings.load(self.settings_path)
        self.assertEqual(reloaded["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"], "test-nexus-sonnet")
        self.assertEqual(reloaded["someOtherTool"], {"keep": "me"})

    def test_switch_prints_tunnel_command_when_proxy_down_and_tunnel_configured(self):
        with open(self.settings_path, "w") as f:
            json.dump(self._fresh_cfg(), f)
        self.cm.proxy_ok = lambda profile, mode: False
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
        self.cm.proxy_ok = lambda profile, mode: False
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                self.cm.switch("nexus", no_tunnel_profile)
        self.assertEqual(ctx.exception.code, 1)
        self.assertNotIn("claude-mode-tunnel", buf.getvalue())

    def test_switch_proceeds_when_probe_gets_http_error_status(self):
        # A 404/401 from the endpoint IS an answer: direct gateways without
        # a /v1/models route must still count as reachable.
        with open(self.settings_path, "w") as f:
            json.dump(self._fresh_cfg(), f)
        err = urllib.error.HTTPError("http://127.0.0.1:8104/v1/models", 404, "Not Found", None, None)
        buf = io.StringIO()
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with contextlib.redirect_stdout(buf):
                self.cm.switch("nexus", self.profile)
        reloaded = cm_settings.load(self.settings_path)
        self.assertEqual(reloaded["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"], "test-nexus-sonnet")

    def test_switch_aborts_when_probe_gets_no_http_answer(self):
        # URLError means nothing answered HTTP at all - that (and only
        # that) is what "not answering" means.
        with open(self.settings_path, "w") as f:
            json.dump(self._fresh_cfg(), f)
        buf = io.StringIO()
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            with contextlib.redirect_stdout(buf):
                with self.assertRaises(SystemExit) as ctx:
                    self.cm.switch("nexus", self.profile)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("not answering", buf.getvalue())

    def test_error_status_counts_as_reachable_but_not_healthy(self):
        # 502/503 from a reverse proxy with a dead backend: reachable (the
        # switch gate must not abort) but NOT healthy and NOT "up".
        err = urllib.error.HTTPError("http://127.0.0.1:8901/v1/models", 502, "Bad Gateway", None, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            self.assertTrue(self.cm.proxy_ok(self.profile, "nexus"))
            self.assertFalse(self.cm.local_health_ok(self.profile))

    def test_probe_label_distinguishes_up_answering_and_down(self):
        self.assertEqual(self.cm._probe_label(200), "up")
        self.assertIn("HTTP 503", self.cm._probe_label(503))
        self.assertNotEqual(self.cm._probe_label(503), "up")
        self.assertIn("not answering", self.cm._probe_label(None))

    def test_gpt_base_url_override_used_instead_of_shared_bedrock_url(self):
        # A site can point nexus-gpt at a different endpoint than
        # nexus-claude (e.g. a translating proxy the raw gateway lacks)
        # without disturbing nexus-claude's own base_url.
        with open(FIXTURE_PROFILE) as f:
            raw = json.load(f)
        raw["bedrock"] = {
            "base_url": "http://direct.invalid:443",
            "gpt_base_url": "http://127.0.0.1:8104",
        }
        fd, override_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(raw, f)
        self.addCleanup(lambda: os.path.exists(override_path) and os.remove(override_path))
        override_profile = Profile(path=override_path)
        cfg = self._fresh_cfg()
        self.cm.set_gpt(cfg, override_profile)
        self.assertEqual(cfg["env"]["ANTHROPIC_BEDROCK_BASE_URL"], "http://127.0.0.1:8104")
        cfg2 = self._fresh_cfg()
        self.cm.set_nexus(cfg2, override_profile)
        self.assertEqual(cfg2["env"]["ANTHROPIC_BEDROCK_BASE_URL"], "http://direct.invalid:443")

    def test_bedrock_base_url_used_when_no_mode_override_present(self):
        self.assertEqual(
            self.cm._bedrock_base_url(self.profile, "gpt"),
            self.profile.get("bedrock.base_url"),
        )

    def test_pinned_mode_writes_top_level_model(self):
        cfg = self._fresh_cfg()
        self.cm.set_gpt(cfg, self.profile)
        self.assertEqual(cfg["model"], "test-gpt-model-pin")

    def test_unpinned_mode_preserves_existing_top_level_model(self):
        # claude_model.nexus is null in the fixture: a user-set top-level
        # "model" must survive the switch verbatim.
        cfg = self._fresh_cfg()
        cfg["model"] = "user-chosen-alias"
        self.cm.set_nexus(cfg, self.profile)
        self.assertEqual(cfg["model"], "user-chosen-alias")

    def test_oauth_pin_restores_when_cycling_back(self):
        cfg = self._fresh_cfg()
        self.cm.set_gpt(cfg, self.profile)
        self.assertEqual(cfg["model"], "test-gpt-model-pin")
        self.cm.set_oauth(cfg, self.profile)
        self.assertEqual(cfg["model"], "test-oauth-model-pin")

    def test_stale_pin_does_not_leak_into_unpinned_mode(self):
        # claude_model.gpt is pinned, claude_model.nexus is null: leaving
        # gpt for nexus must remove the gpt-only pin instead of leaving a
        # GPT-tier alias active on the Claude backend.
        cfg = self._fresh_cfg()
        self.cm.set_gpt(cfg, self.profile)
        self.assertEqual(cfg["model"], "test-gpt-model-pin")
        self.cm.set_nexus(cfg, self.profile)
        self.assertNotIn("model", cfg)
        self.assertNotIn(self.cm.K_PIN_STATE, cfg)

    def test_user_model_restored_when_leaving_pinned_mode(self):
        # A pre-existing user-set "model" is replaced while the pinned mode
        # is active and comes back verbatim on leaving it.
        cfg = self._fresh_cfg()
        cfg["model"] = "user-opusplan"
        self.cm.set_gpt(cfg, self.profile)
        self.assertEqual(cfg["model"], "test-gpt-model-pin")
        self.cm.set_nexus(cfg, self.profile)
        self.assertEqual(cfg["model"], "user-opusplan")
        self.assertNotIn(self.cm.K_PIN_STATE, cfg)

    def test_user_prior_model_survives_pin_to_pin_switch(self):
        # gpt (pinned) -> oauth (pinned) -> nexus (unpinned): the original
        # user value rides through both pins and is restored at the end.
        cfg = self._fresh_cfg()
        cfg["model"] = "user-opusplan"
        self.cm.set_gpt(cfg, self.profile)
        self.cm.set_oauth(cfg, self.profile)
        self.assertEqual(cfg["model"], "test-oauth-model-pin")
        self.cm.set_nexus(cfg, self.profile)
        self.assertEqual(cfg["model"], "user-opusplan")

    def test_user_override_of_active_pin_is_never_touched(self):
        # The user hand-edited "model" while a pin was active: their value
        # no longer matches the recorded pin, so it wins from then on.
        cfg = self._fresh_cfg()
        self.cm.set_gpt(cfg, self.profile)
        cfg["model"] = "user-hand-edit"
        self.cm.set_nexus(cfg, self.profile)
        self.assertEqual(cfg["model"], "user-hand-edit")
        self.assertNotIn(self.cm.K_PIN_STATE, cfg)

    def test_token_found_in_claude_env(self):
        os.remove(os.path.join(self.home, ".env"))
        self._write_env_file(os.path.join(".claude", ".env"), "TEST_BEARER_TOKEN=claude-env-token\n")
        cfg = self._fresh_cfg()
        self.cm.set_nexus(cfg, self.profile)
        self.assertEqual(cfg["env"]["AWS_BEARER_TOKEN_BEDROCK"], "claude-env-token")

    def test_token_falls_back_to_home_env(self):
        # setUp only wrote ~/.env; ~/.claude/.env doesn't exist.
        cfg = self._fresh_cfg()
        self.cm.set_nexus(cfg, self.profile)
        self.assertEqual(cfg["env"]["AWS_BEARER_TOKEN_BEDROCK"], "fixture-token-value")

    def test_claude_env_wins_over_home_env(self):
        self._write_env_file(os.path.join(".claude", ".env"), "TEST_BEARER_TOKEN=claude-env-token\n")
        cfg = self._fresh_cfg()
        self.cm.set_nexus(cfg, self.profile)
        self.assertEqual(cfg["env"]["AWS_BEARER_TOKEN_BEDROCK"], "claude-env-token")

    def _override_profile(self, env_file):
        with open(FIXTURE_PROFILE) as f:
            data = json.load(f)
        data["tokens"]["env_file"] = env_file
        path = os.path.join(tempfile.mkdtemp(), "env-file-profile.json")
        with open(path, "w") as f:
            json.dump(data, f)
        return Profile(path=path)

    def test_tokens_env_file_override_is_used(self):
        custom = self._write_env_file("custom.env", "TEST_BEARER_TOKEN=custom-file-token\n")
        profile = self._override_profile(custom)
        cfg = self._fresh_cfg()
        self.cm.set_nexus(cfg, profile)
        self.assertEqual(cfg["env"]["AWS_BEARER_TOKEN_BEDROCK"], "custom-file-token")

    def test_tokens_env_file_override_pins_the_search(self):
        # The key sits in ~/.env, but the override names a file without it:
        # only the overridden file may be consulted, and the abort message
        # must name exactly that file.
        custom = self._write_env_file("custom.env", "SOME_OTHER_KEY=whatever\n")
        profile = self._override_profile(custom)
        cfg = self._fresh_cfg()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                self.cm.set_nexus(cfg, profile)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn(custom, buf.getvalue())
        self.assertNotIn(os.path.join(self.home, ".claude", ".env"), buf.getvalue())

    def test_token_found_in_env_file_with_utf8_bom(self):
        # Windows editors / PowerShell redirection prepend a UTF-8 BOM; a
        # first-line token must still be found, not reported MISSING.
        with open(os.path.join(self.home, ".env"), "w", encoding="utf-8-sig") as f:
            f.write("TEST_BEARER_TOKEN=bom-token\n")
        cfg = self._fresh_cfg()
        self.cm.set_nexus(cfg, self.profile)
        self.assertEqual(cfg["env"]["AWS_BEARER_TOKEN_BEDROCK"], "bom-token")

    def test_utf16_env_file_aborts_cleanly_instead_of_traceback(self):
        # PowerShell 5.1's `echo 'KEY=...' >> ~/.env` writes UTF-16: that
        # must produce a clean ABORT (plus a warning naming the file), not
        # an uncaught UnicodeDecodeError.
        with open(os.path.join(self.home, ".env"), "w", encoding="utf-16") as f:
            f.write("TEST_BEARER_TOKEN=utf16-token\n")
        cfg = self._fresh_cfg()
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                self.cm.set_nexus(cfg, self.profile)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("ABORT", out.getvalue())
        self.assertIn(os.path.join(self.home, ".env"), err.getvalue())
        self.assertIn("UTF-8", err.getvalue())

    def test_gpt_fallback_env_profile_key_gets_deprecation_note(self):
        # Removed key still present in an upgraded site profile: nexus-gpt
        # must name it at runtime, not silently ignore it.
        variant = self._profile_variant(
            lambda d: d["tokens"].update(gpt_fallback_env="TEST_FALLBACK_TOKEN"))
        profile = Profile(path=variant)
        cfg = self._fresh_cfg()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.cm.set_gpt(cfg, profile)
        self.assertIn("gpt_fallback_env", buf.getvalue())
        self.assertEqual(cfg["env"]["AWS_BEARER_TOKEN_BEDROCK"], "fixture-token-value")

    def test_gpt_fallback_env_abort_points_at_migration(self):
        # Only the legacy token exists in ~/.env: the abort must point the
        # user at moving that value to the shared bedrock_env key.
        with open(os.path.join(self.home, ".env"), "w") as f:
            f.write("TEST_FALLBACK_TOKEN=legacy-token-value\n")
        variant = self._profile_variant(
            lambda d: d["tokens"].update(gpt_fallback_env="TEST_FALLBACK_TOKEN"))
        profile = Profile(path=variant)
        cfg = self._fresh_cfg()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                self.cm.set_gpt(cfg, profile)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("TEST_FALLBACK_TOKEN", buf.getvalue())
        self.assertIn("TEST_BEARER_TOKEN", buf.getvalue())
        self.assertIn(os.path.join(self.home, ".env"), buf.getvalue())

    def test_missing_token_abort_names_both_search_paths(self):
        os.remove(os.path.join(self.home, ".env"))
        cfg = self._fresh_cfg()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                self.cm.set_nexus(cfg, self.profile)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn(os.path.join(self.home, ".claude", ".env"), buf.getvalue())
        self.assertIn(os.path.join(self.home, ".env"), buf.getvalue())


if __name__ == "__main__":
    unittest.main()
