#!/bin/sh
# uninstall.sh - remove only what install.sh created for this repo: the
# symlinks on POSIX, the launcher shim pairs on Windows. Never deletes a real
# file, and never touches profile.json or ~/.claude/settings.json.
set -eu

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *)
      echo "uninstall.sh: unknown argument '$arg'" >&2
      exit 1
      ;;
  esac
done

SELF="$(readlink -f "$0" 2>/dev/null || echo "$0")"
REPO_ROOT="$(cd "$(dirname "$SELF")" && pwd)"

_run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "+ $*"
  else
    "$@"
  fi
}

. "$REPO_ROOT/lib/python.sh"

PLATFORM="$("$PYTHON" "$REPO_ROOT/lib/platform.py")"

if [ "$PLATFORM" = "windows" ] && ! command -v cygpath >/dev/null 2>&1; then
  echo "uninstall.sh: native Windows Python but no cygpath on PATH." >&2
  echo "  Run this from Git Bash or an MSYS2 shell, which ship cygpath." >&2
  exit 1
fi

_to_posix() {
  if [ "$PLATFORM" = "windows" ]; then cygpath -u "$1"; else printf '%s\n' "$1"; fi
}

_to_native() {
  if [ "$PLATFORM" = "windows" ]; then cygpath -m "$1"; else printf '%s\n' "$1"; fi
}

INSTALL_DIR="$(_to_posix "$("$PYTHON" "$REPO_ROOT/lib/platform.py" --install-dir)")"
if [ -z "$INSTALL_DIR" ]; then
  echo "uninstall.sh: lib/platform.py --install-dir returned nothing" >&2
  exit 1
fi

REPO_ROOT_NATIVE="$(_to_native "$REPO_ROOT")"

# Remove $1 only if install.sh is what put it there: a symlink resolving into
# this repo, or a generated shim naming this repo. Anything else is somebody
# else's file and stays.
_remove_if_ours() {
  _path="$1"
  [ -e "$_path" ] || [ -L "$_path" ] || return 0

  if [ -L "$_path" ]; then
    case "$(readlink -f "$_path" 2>/dev/null || true)" in
      "$REPO_ROOT"/*)
        _run rm -f "$_path"
        echo "uninstall.sh: removed $_path"
        ;;
      *)
        echo "uninstall.sh: $_path does not point into this repo, leaving it alone" >&2
        ;;
    esac
    return 0
  fi

  if grep -q "claude-mode-shim" "$_path" 2>/dev/null &&
     grep -qF "$REPO_ROOT_NATIVE" "$_path" 2>/dev/null; then
    _run rm -f "$_path"
    echo "uninstall.sh: removed $_path"
  else
    echo "uninstall.sh: $_path is not a symlink or shim from this repo, leaving it alone" >&2
  fi
}

for script in "$REPO_ROOT"/bin/*; do
  [ -f "$script" ] || continue
  name="$(basename "$script")"
  _remove_if_ours "$INSTALL_DIR/$name"
  if [ "$PLATFORM" = "windows" ]; then
    _remove_if_ours "$INSTALL_DIR/$name.cmd"
  fi
done

echo "uninstall.sh: done (profile.json and ~/.claude/settings.json left untouched)"
