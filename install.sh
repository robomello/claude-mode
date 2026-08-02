#!/bin/sh
# install.sh - symlink claude-mode's bin/* into the platform-chosen install dir.
# Idempotent: safe to re-run. Never clobbers an existing profile.json.
set -eu

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *)
      echo "install.sh: unknown argument '$arg'" >&2
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
  echo "install.sh: lib/platform.py --install-dir returned nothing" >&2
  exit 1
fi

echo "install.sh: install dir is $INSTALL_DIR"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "+ mkdir -p $INSTALL_DIR"
else
  mkdir -p "$INSTALL_DIR"
fi

for script in "$REPO_ROOT"/bin/*; do
  [ -f "$script" ] || continue
  name="$(basename "$script")"
  dest="$INSTALL_DIR/$name"

  if [ -L "$dest" ]; then
    _run rm -f "$dest"
  elif [ -e "$dest" ]; then
    echo "install.sh: WARNING - $dest exists and is not a symlink, skipping" >&2
    continue
  fi

  _run ln -s "$script" "$dest"
  echo "install.sh: linked $dest -> $script"
done

# Profile resolution mirrors lib/profile.py: ~/.claude/claude-mode/ is the
# preferred location (beside the settings.json this tool manages), the XDG
# path is the legacy fallback. Never clobber an existing profile in EITHER.
CLAUDE_PROFILE="$HOME/.claude/claude-mode/profile.json"
XDG_PROFILE="${XDG_CONFIG_HOME:-$HOME/.config}/claude-mode/profile.json"

if [ -f "$CLAUDE_PROFILE" ]; then
  echo "install.sh: $CLAUDE_PROFILE already exists, leaving it alone"
elif [ -f "$XDG_PROFILE" ]; then
  echo "install.sh: $XDG_PROFILE already exists, leaving it alone"
else
  if [ -d "$HOME/.claude" ]; then
    PROFILE_DEST="$CLAUDE_PROFILE"
  else
    PROFILE_DEST="$XDG_PROFILE"
  fi
  CONFIG_DIR="$(dirname "$PROFILE_DEST")"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "+ mkdir -p $CONFIG_DIR"
  else
    mkdir -p "$CONFIG_DIR"
  fi
  _run cp "$REPO_ROOT/profiles/example.json" "$PROFILE_DEST"
  echo "install.sh: wrote default profile to $PROFILE_DEST"
fi

case ":$PATH:" in
  *":$INSTALL_DIR:"*)
    ;;
  *)
    echo "install.sh: WARNING - $INSTALL_DIR is not on your \$PATH. Add it to your shell rc file." >&2
    ;;
esac

echo "install.sh: done"
