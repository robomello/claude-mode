"""lib.profile - load and validate the claude-mode site profile.

Resolution order for any dotted key:
  1. value from profile.json (if present)
  2. built-in generic default (if the key exists in DEFAULTS)
  3. hard error naming the exact missing dotted key

Profile location, in order:
  1. $CLAUDE_MODE_PROFILE (explicit file path override, used by tests)
  2. ~/.claude/claude-mode/profile.json, if that file exists (preferred:
     claude-mode's whole job is managing ~/.claude/settings.json, so its
     profile belongs beside it)
  3. $XDG_CONFIG_HOME/claude-mode/profile.json or
     ~/.config/claude-mode/profile.json, if that file exists (legacy)
When neither file exists, the ~/.claude path is returned as the canonical
place to create one.

No site-specific values live here. Defaults exist only for keys with a sane
generic value; keys that need a real site value (model ids under models.*)
have no default and raise when unresolved. Real values only ever come from
the profile.json a site installs.
"""
import copy
import json
import os
from urllib.parse import urlparse

# Generic, non-site-specific defaults. Every dotted key resolvable here needs
# no profile entry to work. Keys with no sane generic value - the real model
# ids under models.* - are deliberately ABSENT: resolving them without a
# profile entry must raise ProfileError ("missing required profile key")
# rather than silently write placeholder ids into settings.json.
DEFAULTS = {
    "bedrock": {
        "base_url": "http://localhost:8104",
        "port": 8104,
    },
    "local": {
        "base_url": "http://localhost:8901",
        "port": 8901,
        # How the CLI reaches the local model. "bedrock" (the default, and
        # the only behavior before this key existed) routes it through the
        # Bedrock-compatible proxy like the nexus modes. "direct" points
        # ANTHROPIC_BASE_URL straight at local.base_url, for a server that
        # already speaks the Anthropic Messages API natively (e.g. Ollama).
        "transport": "bedrock",
    },
    "claude_model": {
        "oauth": None,
        "nexus": None,
        "gpt": None,
        "local": None,
    },
    "tokens": {
        "bedrock_env": "AWS_BEARER_TOKEN_BEDROCK",
        "env_file": None,
    },
    "test": {
        "timeout_seconds": 20,
    },
    "tunnel": {
        "host": None,
        "user": None,
        "jump": None,
    },
    "toggle_cycle": ["oauth", "nexus", "gpt", "local"],
}

# Dotted keys whose value must parse as an http/https URL with a host.
# bedrock.<mode>_base_url overrides are optional (see bin/claude-mode's
# _bedrock_base_url) and have no default - only validated when a site sets one.
_URL_KEYS = (
    "bedrock.base_url", "local.base_url",
    "bedrock.nexus_base_url", "bedrock.gpt_base_url", "bedrock.local_base_url",
)
# Dotted keys whose value must be an integer port in 1-65535.
_PORT_KEYS = ("bedrock.port", "local.port")
# Dotted keys restricted to a fixed set of values.
_ENUM_KEYS = {"local.transport": ("bedrock", "direct")}


class ProfileError(Exception):
    """Raised for a missing or invalid profile value. str(e) is user-facing."""


def _home():
    # Same resolution as lib/settings.py's _home(): CLAUDE_MODE_HOME
    # (test/automation override) first; then $HOME, but only on POSIX,
    # where the claude CLI itself honors it. On native Windows the CLI
    # resolves %USERPROFILE% (ntpath.expanduser ignores $HOME), so
    # following a stray Cygwin/MobaXterm $HOME there would point this tool
    # at a different ~/.claude than the one the CLI actually reads.
    override = os.environ.get("CLAUDE_MODE_HOME")
    if override:
        return override
    if os.name != "nt":
        home = os.environ.get("HOME")
        if home:
            return home
    return os.path.expanduser("~")


def _profile_path():
    override = os.environ.get("CLAUDE_MODE_PROFILE")
    if override:
        return override
    claude_path = os.path.join(_home(), ".claude", "claude-mode", "profile.json")
    if os.path.isfile(claude_path):
        return claude_path
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = xdg if xdg else os.path.join(_home(), ".config")
    xdg_path = os.path.join(base, "claude-mode", "profile.json")
    if os.path.isfile(xdg_path):
        return xdg_path
    # Neither file exists yet: report the ~/.claude path as the canonical
    # place to create one.
    return claude_path


def _deep_merge(base, override):
    """Recursively overlay `override` onto a copy of `base`. dict values merge
    key-by-key; any other type (including lists) is replaced wholesale."""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return copy.deepcopy(override)
    merged = copy.deepcopy(base)
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = copy.deepcopy(val)
    return merged


def _get_path(d, dotted_key):
    """Walk dotted_key through nested dicts in d. Returns (found, value)."""
    parts = dotted_key.split(".")
    cur = d
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _validate_url(dotted_key, value):
    if not isinstance(value, str) or not value:
        raise ProfileError(
            f"invalid value for '{dotted_key}': expected an http/https URL, got {value!r}"
        )
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ProfileError(
            f"invalid value for '{dotted_key}': URL must use http or https, got {value!r}"
        )
    if not parsed.hostname:
        raise ProfileError(
            f"invalid value for '{dotted_key}': URL is missing a host, got {value!r}"
        )


def _validate_enum(dotted_key, value, allowed):
    if value not in allowed:
        raise ProfileError(
            f"invalid value for '{dotted_key}': expected one of "
            + ", ".join(repr(a) for a in allowed)
            + f", got {value!r}"
        )


def _validate_port(dotted_key, value):
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ProfileError(
            f"invalid value for '{dotted_key}': expected an integer port, got {value!r}"
        )
    if not (1 <= port <= 65535):
        raise ProfileError(
            f"invalid value for '{dotted_key}': port must be 1-65535, got {value!r}"
        )


class Profile:
    """Resolved, validated view of profile.json overlaid on DEFAULTS."""

    def __init__(self, path=None):
        self.path = path if path is not None else _profile_path()
        raw = {}
        if os.path.isfile(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    raw = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                raise ProfileError(f"could not read profile at {self.path}: {e}")
            if not isinstance(raw, dict):
                raise ProfileError(f"profile at {self.path} must be a JSON object")
        self._merged = _deep_merge(DEFAULTS, raw)
        self._validate()

    def _validate(self):
        for key in _URL_KEYS:
            found, val = _get_path(self._merged, key)
            if found:
                _validate_url(key, val)
        for key in _PORT_KEYS:
            found, val = _get_path(self._merged, key)
            if found:
                _validate_port(key, val)
        for key, allowed in _ENUM_KEYS.items():
            found, val = _get_path(self._merged, key)
            if found:
                _validate_enum(key, val, allowed)

    def get(self, dotted_key):
        """Return the resolved value for dotted_key, or raise ProfileError
        naming the exact missing key."""
        found, val = _get_path(self._merged, dotted_key)
        if not found:
            raise ProfileError(f"missing required profile key: '{dotted_key}'")
        return val

    def get_or(self, dotted_key, fallback):
        try:
            return self.get(dotted_key)
        except ProfileError:
            return fallback


def load_profile(path=None):
    return Profile(path=path)


def _main(argv):
    import sys

    if len(argv) >= 2 and argv[0] == "--get":
        dotted_key = argv[1]
        try:
            prof = load_profile()
            val = prof.get(dotted_key)
        except ProfileError as e:
            print(str(e), file=sys.stderr)
            return 1
        if val is None:
            print("")
        else:
            print(val)
        return 0
    print("usage: profile.py --get <dotted.key>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    import sys

    sys.exit(_main(sys.argv[1:]))
