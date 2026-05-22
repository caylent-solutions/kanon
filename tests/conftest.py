"""Shared fixtures for kanon-cli tests."""

from __future__ import annotations

import os
import pathlib
from collections.abc import Generator

import pytest

# Minimal valid .kanon content used across integration and functional tests.
MINIMAL_KANONENV = (
    "KANON_SOURCE_s_URL=https://example.com/s.git\nKANON_SOURCE_s_REVISION=main\nKANON_SOURCE_s_PATH=m.xml\n"
)

# Default catalog source used by tests that need a catalog source but are not
# exercising catalog-resolution logic. Uses an RFC 2606 reserved example.com
# domain so no real network request is ever attempted.  The autouse
# _scrub_catalog_source_env fixture removes KANON_CATALOG_SOURCE after every
# test; tests that need this value must either:
#   (a) pass it as catalog_source=DEFAULT_CATALOG_SOURCE to install(), or
#   (b) set KANON_CATALOG_SOURCE via monkeypatch.setenv before calling code
#       that reads the env var, or
#   (c) request the opt-in _set_default_catalog_source fixture.
DEFAULT_CATALOG_SOURCE = "https://catalog.example.com/repo.git@main"


def write_kanonenv(directory: pathlib.Path) -> pathlib.Path:
    """Write a minimal valid .kanon file in directory and return its path."""
    kanonenv = directory / ".kanon"
    kanonenv.write_text(MINIMAL_KANONENV)
    return kanonenv


def write_manifest_for_sync(directory: pathlib.Path, sub_path: str = "repo-specs/manifest.xml") -> pathlib.Path:
    """Write a minimal valid XML manifest at the repo-tool layout path inside directory.

    After ``repo init`` + ``repo sync``, manifest files live under
    ``directory/.repo/manifests/<sub_path>``.  This helper creates that directory
    structure and writes the smallest well-formed manifest that satisfies the XML
    include-walker, avoiding per-test duplication of the mkdir + write_text pattern.

    Tests that mock ``repo_init`` or ``repo_sync`` must call this helper so that
    ``install()``'s include-walker can find the manifest at the expected location.

    Args:
        directory: The source workspace directory (the path passed by install() to
            repo_init / repo_sync as ``repo_dir``).
        sub_path: Manifest path relative to the manifests repo root, matching the
            ``KANON_SOURCE_<name>_PATH`` value in the ``.kanon`` file.  Defaults
            to ``"repo-specs/manifest.xml"``.

    Returns:
        Absolute path to the written manifest file.

    Example::

        def fake_repo_init(repo_dir: str, url: str, revision: str,
                           manifest_path: str, repo_rev: str = "") -> None:
            write_manifest_for_sync(pathlib.Path(repo_dir), sub_path=manifest_path)
    """
    manifest = directory / ".repo" / "manifests" / sub_path
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest></manifest>\n"
    )
    return manifest


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


# ---------------------------------------------------------------------------
# Doctor consistency test helpers (shared between unit and integration tests)
# ---------------------------------------------------------------------------

#: Minimal valid .kanon content used by doctor unit tests.
DOCTOR_MINIMAL_KANON_CONTENT = (
    "KANON_SOURCE_src_URL=https://example.com/org/repo.git\n"
    "KANON_SOURCE_src_REVISION=main\n"
    "KANON_SOURCE_src_PATH=repo-specs/meta.xml\n"
    "KANON_MARKETPLACE_INSTALL=false\n"
)


def write_kanon_doctor_unit(
    tmp_path: pathlib.Path,
    content: str = DOCTOR_MINIMAL_KANON_CONTENT,
) -> pathlib.Path:
    """Write a .kanon file for doctor unit tests and chmod 0o644.

    Used by tests/unit/test_doctor_consistency.py to build minimal workspaces
    for subcheck unit tests. The content parameter lets callers supply custom
    source definitions (e.g. SHA-pinned sources for dangling-SHA checks).

    Args:
        tmp_path: Directory in which to create the .kanon file.
        content: Full text of the .kanon file.

    Returns:
        Path to the written .kanon file.
    """
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(content, encoding="utf-8")
    kanon_file.chmod(0o644)
    return kanon_file


def write_lockfile_doctor_unit(
    tmp_path: pathlib.Path,
    kanon_hash_val: str = "sha256:" + "a" * 64,
    source_names: list[str] | None = None,
    revision_specs: dict[str, str] | None = None,
    resolved_shas: dict[str, str] | None = None,
    urls: dict[str, str] | None = None,
) -> pathlib.Path:
    """Write a minimal .kanon.lock for doctor unit tests.

    Used by tests/unit/test_doctor_consistency.py. Supports multiple sources
    via the source_names, revision_specs, resolved_shas, and urls parameters.
    Defaults build a single source named 'src' with a branch-pinned revision
    (main) and a fake SHA.

    Args:
        tmp_path: Directory in which to write .kanon.lock.
        kanon_hash_val: Value to embed in the lockfile's kanon_hash field.
        source_names: Names of the sources to include. Defaults to ["src"].
        revision_specs: Per-source revision strings. Defaults to "main" for all.
        resolved_shas: Per-source resolved SHA. Defaults to "a" * 40 for all.
        urls: Per-source URL. Defaults to "https://example.com/org/repo.git" for all.

    Returns:
        Path to the written .kanon.lock file.
    """
    from kanon_cli.core.lockfile import (
        CatalogBlock,
        Lockfile,
        SourceEntry,
        write_lockfile,
    )

    if source_names is None:
        source_names = ["src"]
    if revision_specs is None:
        revision_specs = {name: "main" for name in source_names}
    if resolved_shas is None:
        resolved_shas = {name: "a" * 40 for name in source_names}
    if urls is None:
        urls = {name: "https://example.com/org/repo.git" for name in source_names}

    sources = [
        SourceEntry(
            name=name,
            url=urls[name],
            revision_spec=revision_specs[name],
            resolved_ref=revision_specs[name],
            resolved_sha=resolved_shas[name],
            path="repo-specs/meta.xml",
        )
        for name in source_names
    ]

    lockfile = Lockfile(
        schema_version=1,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash=kanon_hash_val,
        catalog=CatalogBlock(
            source="",
            url="",
            revision_spec="",
            resolved_ref="",
            resolved_sha="",
        ),
        sources=sources,
    )

    lock_path = tmp_path / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return lock_path


def write_kanon_doctor_integration(
    directory: pathlib.Path,
    source_name: str,
    url: str,
    revision: str = "main",
) -> pathlib.Path:
    """Write a .kanon file for doctor integration tests.

    Used by tests/integration/test_doctor_consistency.py. Writes a single-source
    .kanon file suitable for subprocess-driven CLI tests.

    Args:
        directory: Directory in which to create the .kanon file.
        source_name: Name of the source (used in KANON_SOURCE_<name>_* keys).
        url: Git URL for the source.
        revision: Revision spec (branch name or SHA). Defaults to "main".

    Returns:
        Path to the written .kanon file.
    """
    kanon_file = directory / ".kanon"
    kanon_file.write_text(
        f"KANON_SOURCE_{source_name}_URL={url}\n"
        f"KANON_SOURCE_{source_name}_REVISION={revision}\n"
        f"KANON_SOURCE_{source_name}_PATH=repo-specs/meta.xml\n"
        "KANON_MARKETPLACE_INSTALL=false\n",
        encoding="utf-8",
    )
    kanon_file.chmod(0o644)
    return kanon_file


def write_lockfile_doctor_integration_multi_source(
    directory: pathlib.Path,
    kanon_hash_val: str,
    sources: list[dict],
) -> pathlib.Path:
    """Write a minimal .kanon.lock file for multiple sources (doctor integration tests).

    Shared helper used by tests/integration/test_doctor_consistency.py for test
    cases that require more than one source entry (e.g. orphan lock detection).

    Args:
        directory: Directory in which to write .kanon.lock.
        kanon_hash_val: The kanon_hash to embed in the lockfile.
        sources: List of dicts, each with keys: name, url, revision_spec, resolved_sha.

    Returns:
        Path to the written .kanon.lock file.
    """
    from kanon_cli.core.lockfile import (
        CatalogBlock,
        Lockfile,
        SourceEntry,
        write_lockfile,
    )

    source_entries = [
        SourceEntry(
            name=s["name"],
            url=s["url"],
            revision_spec=s["revision_spec"],
            resolved_ref=s["revision_spec"],
            resolved_sha=s["resolved_sha"],
            path="repo-specs/meta.xml",
        )
        for s in sources
    ]

    lockfile = Lockfile(
        schema_version=1,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash=kanon_hash_val,
        catalog=CatalogBlock(
            source="",
            url="",
            revision_spec="",
            resolved_ref="",
            resolved_sha="",
        ),
        sources=source_entries,
    )
    lock_path = directory / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return lock_path


def write_lockfile_doctor_integration(
    directory: pathlib.Path,
    kanon_hash_val: str,
    source_name: str,
    url: str,
    revision_spec: str,
    resolved_sha: str,
) -> pathlib.Path:
    """Write a minimal .kanon.lock for doctor integration tests.

    Used by tests/integration/test_doctor_consistency.py. Writes a single-source
    lockfile suitable for subprocess-driven CLI tests.

    Args:
        directory: Directory in which to write .kanon.lock.
        kanon_hash_val: Value to embed in the lockfile's kanon_hash field.
        source_name: Name of the single source entry.
        url: Git URL for the source.
        revision_spec: Revision spec string (branch name or SHA).
        resolved_sha: The resolved SHA to record for the source.

    Returns:
        Path to the written .kanon.lock file.
    """
    from kanon_cli.core.lockfile import (
        CatalogBlock,
        Lockfile,
        SourceEntry,
        write_lockfile,
    )

    lockfile = Lockfile(
        schema_version=1,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash=kanon_hash_val,
        catalog=CatalogBlock(
            source="",
            url="",
            revision_spec="",
            resolved_ref="",
            resolved_sha="",
        ),
        sources=[
            SourceEntry(
                name=source_name,
                url=url,
                revision_spec=revision_spec,
                resolved_ref=revision_spec,
                resolved_sha=resolved_sha,
                path="repo-specs/meta.xml",
            )
        ],
    )
    lock_path = directory / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return lock_path


@pytest.fixture(autouse=True)
def _scrub_catalog_source_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Clear KANON_CATALOG_SOURCE after every test function.

    Belt-and-suspenders teardown that unconditionally deletes
    KANON_CATALOG_SOURCE from os.environ after every test, regardless of
    whether the test or any of its fixtures set it. Prevents env-var leaks
    between tests when a fixture or test directly mutates os.environ without
    using monkeypatch (which would otherwise undo changes automatically).

    The fixture is function-scoped (the default) and autouse so it runs for
    every test in the suite without per-test opt-in.
    """
    yield
    monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)


@pytest.fixture()
def make_install_args():
    """Factory fixture that returns a MagicMock with kanonenv_path and catalog_source set.

    Returns a callable that accepts a kanonenv path and returns a MagicMock
    suitable for passing to the install CLI handler _run(args). This allows
    integration and functional tests to invoke the CLI boundary without
    duplicating the argparse namespace setup inline.

    The factory sets ``args.catalog_source`` to ``DEFAULT_CATALOG_SOURCE`` so
    that tests which do not exercise catalog-resolution logic do not fail with
    ``MissingCatalogSourceError`` due to the autouse ``_scrub_catalog_source_env``
    fixture clearing ``KANON_CATALOG_SOURCE`` between every test.  Tests that
    intentionally exercise the missing-catalog-source error path must override
    ``args.catalog_source = None`` after calling the factory and must also
    ensure ``KANON_CATALOG_SOURCE`` is absent (the autouse scrubber guarantees
    that at test start).

    Args: (none -- use the returned factory)

    Returns:
        A factory function that accepts kanonenv_path (Path) and returns a
        MagicMock with kanonenv_path, lock_file, and catalog_source attributes set.

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
        args.catalog_source = DEFAULT_CATALOG_SOURCE
        args.refresh_lock = False
        args.refresh_lock_source = None
        args.strict_lock = False
        args.strict_drift = False
        return args

    return _factory


@pytest.fixture()
def _set_default_catalog_source(monkeypatch: pytest.MonkeyPatch) -> str:
    """Opt-in fixture: sets KANON_CATALOG_SOURCE to DEFAULT_CATALOG_SOURCE for one test.

    This fixture is opt-in (no ``autouse=True``).  Tests that invoke code paths
    which read ``KANON_CATALOG_SOURCE`` from the environment (e.g. subprocess-
    based tests, or tests that call ``install()`` without passing the
    ``catalog_source`` keyword argument) can request this fixture by name to
    inject the standard test value for the duration of that test.

    The autouse ``_scrub_catalog_source_env`` fixture clears ``KANON_CATALOG_SOURCE``
    after every test; this fixture sets it fresh via ``monkeypatch.setenv`` so it
    is automatically reverted by pytest's monkeypatch teardown in addition to
    the scrubber's ``delenv`` -- belt-and-suspenders isolation.

    Returns:
        The catalog source string that was set (``DEFAULT_CATALOG_SOURCE``), so
        callers can assert against the expected value if needed.

    Example::

        def test_install_via_env(tmp_path, _set_default_catalog_source):
            from kanon_cli.core.install import install
            kanonenv = tmp_path / ".kanon"
            kanonenv.write_text("KANON_SOURCE_s_URL=https://example.com/s.git\\n...")
            # KANON_CATALOG_SOURCE is already set by the fixture
            install(kanonenv, lock_file_path=kanonenv.parent / ".kanon.lock")
    """
    monkeypatch.setenv("KANON_CATALOG_SOURCE", DEFAULT_CATALOG_SOURCE)
    return DEFAULT_CATALOG_SOURCE
