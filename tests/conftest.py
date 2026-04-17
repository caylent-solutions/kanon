"""Shared fixtures for kanon-cli tests."""

import os
import pathlib

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"

# Disable kanon_cli.repo tracing for all tests. Tracing defaults to ON and
# writes to <cwd>/TRACE_FILE, which races across tests, grows unbounded, and
# breaks any test whose cwd is the repo root. Tests never need tracing; setting
# REPO_TRACE=0 at conftest import time (before any kanon_cli.repo import) turns
# it off at the module level so every Trace() call short-circuits.
os.environ.setdefault("REPO_TRACE", "0")


@pytest.fixture(scope="session", autouse=True)
def _subprocess_pythonpath_points_at_source_tree() -> None:
    """Ensure subprocesses spawned by tests import kanon_cli from the current source tree.

    Several test helpers invoke the CLI in a subprocess via
    ``[sys.executable, "-m", "kanon_cli", ...]``. The child Python resolves
    ``import kanon_cli`` against its own site-packages, which in some
    development environments contains a stale ``kanon_cli`` version. Prepending
    the source tree to ``PYTHONPATH`` makes ``import kanon_cli`` in the child
    resolve to the current source regardless of which venv pytest runs in.

    The fixture is session-scoped and autouse so every spawned subprocess
    inherits the modified environment without per-test opt-in.
    """
    existing = os.environ.get("PYTHONPATH", "")
    src_str = str(_SRC_DIR)
    entries = [src_str] + [p for p in existing.split(os.pathsep) if p and p != src_str]
    os.environ["PYTHONPATH"] = os.pathsep.join(entries)


@pytest.fixture()
def sample_kanonenv(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a sample two-source .kanon file."""
    kanonenv = tmp_path / ".kanon"
    kanonenv.write_text(
        "REPO_URL=https://example.com/org/repo-tool.git\n"
        "REPO_REV=v2.0.0\n"
        "GITBASE=https://example.com/org/\n"
        "CLAUDE_MARKETPLACES_DIR=.claude-marketplaces\n"
        "KANON_MARKETPLACE_INSTALL=false\n"
        "KANON_SOURCE_build_URL=https://example.com/org/build-repo.git\n"
        "KANON_SOURCE_build_REVISION=main\n"
        "KANON_SOURCE_build_PATH=repo-specs/common/meta.xml\n"
        "KANON_SOURCE_marketplaces_URL=https://example.com/org/mp-repo.git\n"
        "KANON_SOURCE_marketplaces_REVISION=main\n"
        "KANON_SOURCE_marketplaces_PATH=repo-specs/common/marketplaces.xml\n"
    )
    return kanonenv


@pytest.fixture()
def mock_git_ls_remote_output() -> str:
    """Sample git ls-remote --tags output."""
    return (
        "abc123\trefs/tags/1.0.0\n"
        "def456\trefs/tags/1.0.1\n"
        "ghi789\trefs/tags/1.1.0\n"
        "jkl012\trefs/tags/2.0.0\n"
        "mno345\trefs/tags/2.0.0^{}\n"
    )
