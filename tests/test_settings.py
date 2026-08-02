import glob
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from tests._repo import REPO_ROOT  # noqa: F401

from lib import settings as cm_settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="claude-mode-test-home-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.claude_dir = os.path.join(self.home, ".claude")
        os.makedirs(self.claude_dir, exist_ok=True)
        self.path = os.path.join(self.claude_dir, "settings.json")

    def _write_fixture(self, cfg):
        with open(self.path, "w") as f:
            json.dump(cfg, f, indent=2)

    def test_settings_path_honors_home(self):
        p = cm_settings.settings_path(home=self.home)
        self.assertEqual(p, self.path)

    def test_claude_mode_home_override_wins(self):
        with mock.patch.dict(os.environ, {"CLAUDE_MODE_HOME": self.home,
                                          "HOME": os.path.join(self.home, "elsewhere")}):
            self.assertEqual(cm_settings.settings_path(), self.path)

    @unittest.skipUnless(os.name == "nt", "HOME is only ignored on native Windows")
    def test_home_env_var_ignored_on_native_windows(self):
        # claude.exe resolves %USERPROFILE% (ntpath.expanduser ignores
        # $HOME). A stray Cygwin/MobaXterm/Emacs HOME must not make
        # claude-mode edit a settings.json the CLI never reads.
        with mock.patch.dict(os.environ, {"HOME": r"D:\weird\home"}):
            os.environ.pop("CLAUDE_MODE_HOME", None)
            p = cm_settings.settings_path()
        self.assertEqual(
            p, os.path.join(os.path.expanduser("~"), ".claude", "settings.json"))

    @unittest.skipIf(os.name == "nt", "POSIX honors $HOME, matching the CLI")
    def test_home_env_var_honored_on_posix(self):
        with mock.patch.dict(os.environ, {"HOME": self.home}):
            os.environ.pop("CLAUDE_MODE_HOME", None)
            self.assertEqual(cm_settings.settings_path(), self.path)

    def test_load_missing_file_returns_empty_dict(self):
        self.assertEqual(cm_settings.load(os.path.join(self.claude_dir, "nope.json")), {})

    def test_unknown_top_level_keys_survive(self):
        self._write_fixture({
            "someOtherTool": {"keep": "me"},
            "env": {"CUSTOM_UNMANAGED": "keep-me-too"},
        })
        cfg = cm_settings.load(self.path)
        cm_settings.apply_env(cfg, set_env={"CLAUDE_CODE_USE_BEDROCK": "1"})
        cm_settings.save(self.path, cfg)

        reloaded = cm_settings.load(self.path)
        self.assertEqual(reloaded["someOtherTool"], {"keep": "me"})
        self.assertEqual(reloaded["env"]["CUSTOM_UNMANAGED"], "keep-me-too")
        self.assertEqual(reloaded["env"]["CLAUDE_CODE_USE_BEDROCK"], "1")

    def test_unknown_env_keys_survive_removal_of_managed_keys(self):
        self._write_fixture({"env": {"CUSTOM_UNMANAGED": "still-here", "CLAUDE_CODE_USE_BEDROCK": "1"}})
        cfg = cm_settings.load(self.path)
        cm_settings.apply_env(cfg, remove_env=("CLAUDE_CODE_USE_BEDROCK",))
        cm_settings.save(self.path, cfg)

        reloaded = cm_settings.load(self.path)
        self.assertEqual(reloaded["env"]["CUSTOM_UNMANAGED"], "still-here")
        self.assertNotIn("CLAUDE_CODE_USE_BEDROCK", reloaded["env"])

    def test_write_is_atomic_no_leftover_tmp(self):
        self._write_fixture({"env": {}})
        cfg = cm_settings.load(self.path)
        cm_settings.apply_env(cfg, set_env={"X": "1"})
        cm_settings.save(self.path, cfg)
        self.assertFalse(os.path.exists(self.path + ".tmp"))
        with open(self.path) as f:
            self.assertEqual(json.load(f)["env"]["X"], "1")

    def test_backup_created_before_write(self):
        self._write_fixture({"env": {"A": "orig"}})
        cfg = cm_settings.load(self.path)
        cm_settings.apply_env(cfg, set_env={"A": "changed"})
        bak = cm_settings.save(self.path, cfg)
        self.assertIsNotNone(bak)
        self.assertTrue(os.path.isfile(bak))
        with open(bak) as f:
            backed_up = json.load(f)
        self.assertEqual(backed_up["env"]["A"], "orig")

    def test_no_backup_on_first_ever_write(self):
        # settings.json doesn't exist yet - nothing to back up.
        cfg = {"env": {"A": "1"}}
        bak = cm_settings.save(self.path, cfg)
        self.assertIsNone(bak)
        pattern = os.path.join(self.claude_dir, "settings.json.bak.*")
        self.assertEqual(glob.glob(pattern), [])

    def test_backup_pruning_keeps_newest_ten(self):
        self._write_fixture({"env": {"n": 0}})
        for i in range(1, 16):
            cfg = cm_settings.load(self.path)
            cm_settings.apply_env(cfg, set_env={"n": i})
            cm_settings.save(self.path, cfg)
        pattern = os.path.join(self.claude_dir, "settings.json.bak.*")
        backups = glob.glob(pattern)
        self.assertEqual(len(backups), 10)

    def test_non_ascii_content_survives_save_load_round_trip(self):
        # The file on disk must contain literal UTF-8 bytes, written the way
        # Claude Code or another tool writes settings.json (ensure_ascii
        # off) - save() itself emits pure-ASCII escapes, so saving first
        # would never exercise the decoder. cp1252 (the Windows default
        # encoding) silently mangles these bytes; explicit utf-8 in load()
        # is what keeps them intact.
        note = "em dash — and café, unmanaged"
        cfg = {"someOtherTool": {"note": note}, "env": {}}
        with open(self.path, "wb") as f:
            f.write(json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8"))
        loaded = cm_settings.load(self.path)
        self.assertEqual(loaded["someOtherTool"]["note"], note)
        # And a full save/load round trip on top preserves it too.
        cm_settings.save(self.path, loaded)
        reloaded = cm_settings.load(self.path)
        self.assertEqual(reloaded["someOtherTool"]["note"], note)

    def test_never_touches_local_credentials_or_account_files(self):
        for name in ("settings.local.json", ".credentials.json"):
            self.assertFalse(os.path.exists(os.path.join(self.claude_dir, name)))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude.json")))

        self._write_fixture({"env": {}})
        cfg = cm_settings.load(self.path)
        cm_settings.apply_env(cfg, set_env={"X": "1"})
        cm_settings.save(self.path, cfg)

        for name in ("settings.local.json", ".credentials.json"):
            self.assertFalse(os.path.exists(os.path.join(self.claude_dir, name)))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude.json")))


if __name__ == "__main__":
    unittest.main()
