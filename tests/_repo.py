"""Shared test helpers: locate the repo root, import lib/*, and load
bin/claude-mode (an extensionless script) as a module."""
import importlib.machinery
import importlib.util
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
LIB_DIR = os.path.join(REPO_ROOT, "lib")
BIN_CLAUDE_MODE = os.path.join(REPO_ROOT, "bin", "claude-mode")

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def load_bin_claude_mode():
    """Import bin/claude-mode (no .py extension) as a fresh module object."""
    loader = importlib.machinery.SourceFileLoader("claude_mode_bin", BIN_CLAUDE_MODE)
    spec = importlib.util.spec_from_file_location("claude_mode_bin", BIN_CLAUDE_MODE, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
