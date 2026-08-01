"""lib.platform - OS detection and install-path helpers for claude-mode.

Site-agnostic: no assumptions about any particular install root beyond the
conventional per-user ~/.local/bin, which is correct on macOS, Linux, and WSL.
"""
import os
import platform as _stdlib_platform
import sys


def detect():
    """Return 'macos', 'wsl', or 'linux'."""
    system = _stdlib_platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        try:
            with open("/proc/version") as f:
                if "microsoft" in f.read().lower():
                    return "wsl"
        except OSError:
            pass
        return "linux"
    # Unknown platforms (e.g. plain Windows without WSL) fall back to "linux"
    # semantics rather than crashing - claude-mode itself doesn't need
    # anything platform-specific beyond this module.
    return "linux"


def install_dir():
    """Per-user install dir for the claude-mode CLI. Same on all platforms."""
    return os.path.expanduser("~/.local/bin")


def is_on_path(directory=None):
    directory = directory if directory is not None else install_dir()
    directory = os.path.abspath(directory)
    path_env = os.environ.get("PATH", "")
    entries = [os.path.abspath(p) for p in path_env.split(os.pathsep) if p]
    return directory in entries


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
    if "--check-path" in argv:
        ok = check_path()
        print("on PATH" if ok else "NOT on PATH", file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    print(detect())
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
