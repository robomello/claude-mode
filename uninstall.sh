#!/bin/sh
# uninstall.sh - remove only the symlinks install.sh created for this repo.
# Never deletes a real file, and never touches profile.json or ~/.claude/settings.json.
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

INSTALL_DIR="$(python3 "$REPO_ROOT/lib/platform.py" --install-dir)"
if [ -z "$INSTALL_DIR" ]; then
  echo "uninstall.sh: lib/platform.py --install-dir returned nothing" >&2
  exit 1
fi

for script in "$REPO_ROOT"/bin/*; do
  [ -f "$script" ] || continue
  name="$(basename "$script")"
  dest="$INSTALL_DIR/$name"

  if [ ! -e "$dest" ] && [ ! -L "$dest" ]; then
    continue
  fi

  if [ ! -L "$dest" ]; then
    echo "uninstall.sh: $dest is not a symlink, leaving it alone" >&2
    continue
  fi

  target="$(readlink -f "$dest" 2>/dev/null || true)"
  case "$target" in
    "$REPO_ROOT"/*)
      _run rm -f "$dest"
      echo "uninstall.sh: removed $dest"
      ;;
    *)
      echo "uninstall.sh: $dest does not point into this repo, leaving it alone" >&2
      ;;
  esac
done

echo "uninstall.sh: done (profile.json and ~/.claude/settings.json left untouched)"
