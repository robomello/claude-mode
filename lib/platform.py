"""lib.platform - OS detection and install-path helpers for claude-mode.

Site-agnostic: no assumptions about any particular install root beyond the
conventional per-user ~/.local/bin, which is correct on macOS, Linux, and WSL.
"""
import os
import sys


def detect():
    """Return 'macos', 'windows', 'wsl', or 'linux'.

    Reads sys.platform rather than the stdlib `platform` module on purpose:
    this file is itself named platform.py, and running it as a script
    (`python lib/platform.py`, which install.sh does) puts lib/ first on
    sys.path - so `import platform` would import this module and every
    attribute lookup on it would fail.
    """
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/version") as f:
                if "microsoft" in f.read().lower():
                    return "wsl"
        except OSError:
            pass
        return "linux"
    # Anything else (Cygwin, MSYS2's own python, the BSDs) gets "linux"
    # semantics rather than crashing: a POSIX home, real symlinks, and a
    # $HOME worth honoring - which is all install.sh needs to know.
    return "linux"


def home():
    """The home dir claude-mode's Python side actually reads.

    Must stay in sync with lib/profile.py's _home() and lib/settings.py's
    _home(): CLAUDE_MODE_HOME (test/automation override) first, then $HOME,
    but only on POSIX. On native Windows $HOME is whatever the calling shell
    set - Git Bash and MobaXterm commonly point it at a corporate network
    share - which has nothing to do with the %USERPROFILE% the claude CLI
    reads. install.sh must resolve it the same way this tool does, or it
    writes profile.json somewhere claude-mode will never look for it.
    """
    override = os.environ.get("CLAUDE_MODE_HOME")
    if override:
        return override
    if os.name != "nt":
        home_env = os.environ.get("HOME")
        if home_env:
            return home_env
    return os.path.expanduser("~")


def install_dir():
    """Per-user install dir for the claude-mode CLI. Same on all platforms."""
    return os.path.join(home(), ".local", "bin")


def _canon(path):
    # normcase folds case and unifies separators on Windows, where PATH
    # entries routinely differ from install_dir() in both. It is a no-op on
    # POSIX, so the comparison stays exact there.
    return os.path.normcase(os.path.abspath(path))


def is_on_path(directory=None):
    directory = directory if directory is not None else install_dir()
    path_env = os.environ.get("PATH", "")
    entries = {_canon(p) for p in path_env.split(os.pathsep) if p}
    return _canon(directory) in entries


def check_path(directory=None, out=sys.stderr):
    """Warn (to `out`) if `directory` (default install_dir()) is not on PATH.
    Returns True if on PATH, False otherwise. Never raises."""
    directory = directory if directory is not None else install_dir()
    if is_on_path(directory):
        return True
    print(
        f"warning: {directory} is not on your PATH. "
        f"Add it, e.g.: export PATH=\"{directory}:$PATH\"",
        file=out,
    )
    return False


def _main(argv):
    if "--install-dir" in argv:
        print(install_dir())
        return 0
    if "--home" in argv:
        print(home())
        return 0
    if "--check-path" in argv:
        ok = check_path()
        print("on PATH" if ok else "NOT on PATH", file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    print(detect())
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
