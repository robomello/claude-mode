# lib/python.sh - resolve a real Python interpreter into $PYTHON.
#
# Sourced by every shell entry point (install.sh, uninstall.sh, bin/cc,
# bin/cc-gpt, bin/claude-mode-tunnel). POSIX sh - safe to source from a
# bash script under `set -euo pipefail` as well.
#
# `python3` is preferred (the norm on macOS/Linux), but on Windows Git Bash
# it commonly resolves to the Microsoft Store's app-execution-alias stub:
# present on PATH, so `command -v python3` finds it, but it exits non-zero
# and prints an install nag instead of running. Probing --version is what
# actually tells the two apart. Falling back to `python` there matches what
# claude-mode already does on Windows, where bin/claude-mode is invoked as
# `python` by its .cmd launcher shim.
if python3 --version >/dev/null 2>&1; then
  PYTHON=python3
elif python --version >/dev/null 2>&1; then
  PYTHON=python
else
  echo "claude-mode: no working Python found on PATH (tried python3, python)." >&2
  echo "  Install Python 3, or put it on PATH, then re-run." >&2
  exit 1
fi
