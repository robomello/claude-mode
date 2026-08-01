"""lib.settings - all reads/writes of ~/.claude/settings.json.

This module owns exactly one file: settings.json. It must NEVER touch
settings.local.json, .credentials.json, or .claude.json - other tooling
(team re-sync, the CLI itself) writes those, and claude-mode staying out of
them is why it survives a team re-sync in the first place.

Behavior preserved from the original single-file script:
  - deep-merge only the keys we manage (env.* and top-level forceLoginMethod);
    every other top-level key and every other env key is left untouched
  - atomic write via a .tmp file + os.replace
  - a timestamped .bak copy is made before every write
  - unknown top-level keys and unknown env keys survive a switch verbatim

New behavior added during the port:
  - backups are pruned to the newest 10 after each write (70+ had
    accumulated in practice on the original script)
"""
import glob
import json
import os
import time

SETTINGS_BASENAME = "settings.json"
MAX_BACKUPS = 10


def settings_path(home=None):
    home = home if home is not None else os.path.expanduser("~")
    return os.path.join(home, ".claude", SETTINGS_BASENAME)


def load(path):
    """Return the parsed settings dict, or {} if the file doesn't exist yet."""
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _backup(path):
    """Copy `path` to a timestamped .bak sibling. No-op (returns None) if
    `path` doesn't exist yet (first-ever write, nothing to back up)."""
    if not os.path.isfile(path):
        return None
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = f"{path}.bak.{ts}"
    # Guard against two backups landing in the same second.
    suffix = 0
    candidate = bak
    while os.path.exists(candidate):
        suffix += 1
        candidate = f"{bak}.{suffix}"
    with open(path, "rb") as src, open(candidate, "wb") as dst:
        dst.write(src.read())
    return candidate


def _prune_backups(path, keep=MAX_BACKUPS):
    pattern = f"{path}.bak.*"
    backups = sorted(glob.glob(pattern))  # timestamp prefix sorts chronologically
    excess = len(backups) - keep
    if excess <= 0:
        return
    for old in backups[:excess]:
        try:
            os.remove(old)
        except OSError:
            pass


def _atomic_write(path, cfg):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def save(path, cfg, keep_backups=MAX_BACKUPS):
    """Back up the existing file (if any), atomically write `cfg`, then prune
    old backups down to `keep_backups`. Returns the backup path, or None if
    there was nothing to back up."""
    bak = _backup(path)
    _atomic_write(path, cfg)
    _prune_backups(path, keep=keep_backups)
    return bak


def apply_env(cfg, set_env=None, remove_env=None):
    """Deep-merge only the given env keys into cfg["env"]. Every other env
    key, and every other top-level key, is left exactly as-is."""
    env = cfg.setdefault("env", {})
    for key in (remove_env or ()):
        env.pop(key, None)
    env.update(set_env or {})
    return cfg


def apply_top(cfg, set_top=None, remove_top=None):
    """Set/remove specific top-level keys (e.g. forceLoginMethod). Every
    other top-level key is left exactly as-is."""
    for key in (remove_top or ()):
        cfg.pop(key, None)
    cfg.update(set_top or {})
    return cfg
