"""Shared fixtures for kanon-cli tests."""

import os
import pathlib

import pytest

# Minimal valid .kanon content used across integration and functional tests.
MINIMAL_KANONENV = (
    "KANON_SOURCE_s_URL=https://example.com/s.git\nKANON_SOURCE_s_REVISION=main\nKANON_SOURCE_s_PATH=m.xml\n"
)


def write_kanonenv(directory: pathlib.Path) -> pathlib.Path:
    """Write a minimal valid .kanon file in directory and return its path."""
    kanonenv = directory / ".kanon"
    kanonenv.write_text(MINIMAL_KANONENV)
    return kanonenv


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


def _make_minimal_kanon_file(tmp_path: pathlib.Path, source_name: str = "FOO") -> pathlib.Path:
    """Write a minimal .kanon file with a single source and return its path.

    Shared by unit tests (test_why_ambiguity.py) and integration tests
    (test_why_ambiguous.py) to avoid cross-layer imports.
    """
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(
        f"GITBASE=https://github.com\n"
        f"CLAUDE_MARKETPLACES_DIR=/tmp/mkts\n"
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{source_name}_URL=https://github.com/org/catalog\n"
        f"KANON_SOURCE_{source_name}_REVISION=main\n"
        f"KANON_SOURCE_{source_name}_PATH=./foo\n"
    )
    kanon_file.chmod(0o644)
    return kanon_file


def _write_lockfile(
    tmp_path: pathlib.Path, source_name: str, project_url: str, include_path: str | None = None
) -> pathlib.Path:
    """Write a minimal lockfile with one source, one project, and optionally one include.

    Shared by unit tests (test_why_ambiguity.py) and integration tests
    (test_why_ambiguous.py) to avoid cross-layer imports.
    """
    from kanon_cli.core.lockfile import (
        CatalogBlock,
        IncludeEntry,
        Lockfile,
        ProjectEntry,
        SourceEntry,
        write_lockfile,
    )
    from kanon_cli.core.url import canonicalize_repo_url

    includes = []
    if include_path:
        includes = [
            IncludeEntry(
                name="inc",
                path_in_repo=include_path,
                url="https://github.com/org/catalog",
                resolved_sha="c" * 40,
                includes=[],
            )
        ]

    lockfile = Lockfile(
        schema_version=1,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash="sha256:" + "a" * 64,
        catalog=CatalogBlock(
            source="catalog@HEAD",
            url="https://github.com/org/catalog",
            revision_spec="HEAD",
            resolved_ref="HEAD",
            resolved_sha="f" * 40,
        ),
        sources=[
            SourceEntry(
                name=source_name,
                url="https://github.com/org/catalog",
                revision_spec="main",
                resolved_ref="main",
                resolved_sha="a" * 40,
                path="./foo",
                includes=includes,
                projects=[
                    ProjectEntry(
                        name="proj",
                        url=project_url,
                        canonical_url=canonicalize_repo_url(project_url),
                        revision_spec="main",
                        resolved_ref="main",
                        resolved_sha="b" * 40,
                    )
                ],
            )
        ],
    )

    lock_path = tmp_path / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return lock_path


@pytest.fixture()
def make_install_args():
    """Factory fixture that returns a MagicMock with kanonenv_path set.

    Returns a callable that accepts a kanonenv path and returns a MagicMock
    suitable for passing to the install CLI handler _run(args). This allows
    integration and functional tests to invoke the CLI boundary without
    duplicating the argparse namespace setup inline.

    Args: (none -- use the returned factory)

    Returns:
        A factory function that accepts kanonenv_path (Path) and returns a
        MagicMock with kanonenv_path attribute set to that value.

    Example::

        def test_something(tmp_path, make_install_args):
            from kanon_cli.commands.install import _run
            kanonenv = tmp_path / ".kanon"
            kanonenv.write_text("...")
            args = make_install_args(kanonenv.resolve())
            with pytest.raises(SystemExit) as exc_info:
                _run(args)
            assert exc_info.value.code == 1
    """
    from unittest.mock import MagicMock

    def _factory(kanonenv_path: pathlib.Path) -> MagicMock:
        args = MagicMock()
        args.kanonenv_path = kanonenv_path
        args.lock_file = None
        return args

    return _factory
