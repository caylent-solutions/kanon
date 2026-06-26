"""Functional journey: ``kanon install`` fails fast on a legacy v3 ``.kanon.lock``.

Exercises the schema-bump fail-fast (inventory item 7; spec FR-7 / FR-21 / FR-22,
Section 5.2 / Section 13 FLAG-C) end-to-end as a real CLI black box (subprocess,
no in-process mocks): a v3 lock is NOT silently upgraded to the current schema.

The v3 lockfile written here mirrors, byte-for-byte field shape, the v3 format the
unit suite uses (``tests/unit/test_lockfile.py::TestV3HardFailRegenerate``): a
``schema_version = 3`` header, a global ``[catalog]`` block, and a single
``[[sources]]`` entry keyed by ``name`` (not ``alias``) carrying the old
``revision_spec`` field name and a per-source ``registered_marketplaces`` array.

A matching ``.kanon`` declares the same single source so ``install`` reaches the
lock-read step (rather than failing earlier on a missing source declaration).

Asserted behaviour for ``kanon install`` against the v3 pair:
  - the process exits non-zero (fail-fast, no silent upgrade);
  - the actionable regenerate guidance is present on stderr -- it names the
    offending schema version (v3) and instructs the operator to regenerate the
    lock via ``kanon add`` / ``kanon install``;
  - the on-disk ``.kanon.lock`` is left byte-identical (still ``schema_version =
    3`` with its ``[catalog]`` block) -- the legacy lock is never rewritten to the
    current schema.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.functional.conftest import _run_kanon


_SOURCE_ALIAS = "src"
_SOURCE_NAME = "src"
_SOURCE_URL = "https://example.com/source.git"
_BRANCH_REF = "main"
_MANIFEST_FILENAME = "manifest.xml"
_LOCKFILE_NAME = ".kanon.lock"
_KANON_NAME = ".kanon"

_INSECURE_REMOTES_ENV = "KANON_ALLOW_INSECURE_REMOTES"
_INSECURE_REMOTES_VALUE = "1"
_CATALOG_SOURCES_ENV = "KANON_CATALOG_SOURCES"

_VALID_SHA40 = "a" * 40
_VALID_KANON_HASH = "sha256:" + "a" * 64
_LEGACY_SCHEMA_VERSION_LINE = "schema_version = 3"
_LEGACY_CATALOG_HEADER = "[catalog]"

_TRACEBACK_HEADER = "Traceback (most recent call last)"
_CLEAN_ERROR_PREFIX = "ERROR:"


def _write_kanon(project_dir: pathlib.Path) -> pathlib.Path:
    """Write a single-source committed ``.kanon`` matching the v3 lock's one source."""
    kanon_path = project_dir / _KANON_NAME
    kanon_path.write_text(
        f"CLAUDE_MARKETPLACES_DIR={project_dir}/mktplc\n"
        "KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{_SOURCE_ALIAS}_URL={_SOURCE_URL}\n"
        f"KANON_SOURCE_{_SOURCE_ALIAS}_REF={_BRANCH_REF}\n"
        f"KANON_SOURCE_{_SOURCE_ALIAS}_PATH={_MANIFEST_FILENAME}\n"
        f"KANON_SOURCE_{_SOURCE_ALIAS}_NAME={_SOURCE_NAME}\n"
        f"KANON_SOURCE_{_SOURCE_ALIAS}_GITBASE={_SOURCE_URL}\n",
        encoding="utf-8",
    )
    kanon_path.chmod(0o600)
    return kanon_path


def _legacy_v3_lock_text() -> str:
    """Return a legacy schema-v3 ``.kanon.lock`` body.

    Mirrors the v3 format the unit suite uses
    (``tests/unit/test_lockfile.py::TestV3HardFailRegenerate``): a global
    ``[catalog]`` block and a ``name``-keyed ``[[sources]]`` entry carrying the
    old ``revision_spec`` field name (renamed to ``ref_spec`` in v4, retained in v5).
    """
    return (
        f"{_LEGACY_SCHEMA_VERSION_LINE}\n"
        'generated_at = "2026-01-01T00:00:00Z"\n'
        'generator = "kanon-cli/1.4.0"\n'
        f'kanon_hash = "{_VALID_KANON_HASH}"\n'
        "marketplace_registered = false\n"
        'marketplace_dir = ""\n'
        "\n"
        f"{_LEGACY_CATALOG_HEADER}\n"
        'source = "https://example.com/catalog.git@main"\n'
        'url = "https://example.com/catalog.git"\n'
        f'revision_spec = "{_BRANCH_REF}"\n'
        'resolved_ref = "refs/heads/main"\n'
        f'resolved_sha = "{_VALID_SHA40}"\n'
        "\n"
        "[[sources]]\n"
        f'name = "{_SOURCE_NAME}"\n'
        f'url = "{_SOURCE_URL}"\n'
        f'revision_spec = "{_BRANCH_REF}"\n'
        'resolved_ref = "refs/heads/main"\n'
        f'resolved_sha = "{_VALID_SHA40}"\n'
        f'path = "{_MANIFEST_FILENAME}"\n'
        "registered_marketplaces = []\n"
    )


@pytest.fixture()
def v3_lock_project(tmp_path: pathlib.Path) -> pathlib.Path:
    """Build a project dir with a matching ``.kanon`` and a legacy v3 ``.kanon.lock``.

    Returns the project directory containing both committed files (the explicit
    ``.kanon`` path is passed to the subprocess install invocations).
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _write_kanon(project_dir)
    (project_dir / _LOCKFILE_NAME).write_text(_legacy_v3_lock_text(), encoding="utf-8")
    return project_dir


@pytest.mark.functional
class TestInstallV3LockFailFastJourney:
    """A legacy v3 ``.kanon.lock`` makes ``kanon install`` fail fast with no silent upgrade."""

    def test_install_exits_non_zero_on_v3_lock(
        self, v3_lock_project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``kanon install`` against a v3 lock exits non-zero (fail-fast)."""
        monkeypatch.delenv(_CATALOG_SOURCES_ENV, raising=False)
        result = _run_kanon(
            "install",
            str(v3_lock_project / _KANON_NAME),
            extra_env={_INSECURE_REMOTES_ENV: _INSECURE_REMOTES_VALUE},
        )
        assert result.returncode != 0, (
            "install must reject a legacy v3 .kanon.lock with a non-zero exit.\n"
            f"  returncode={result.returncode}\n  stdout={result.stdout!r}\n  stderr={result.stderr!r}"
        )

    def test_install_emits_actionable_regenerate_message_on_stderr(
        self, v3_lock_project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The v3-lock failure surfaces the actionable regenerate guidance on stderr."""
        monkeypatch.delenv(_CATALOG_SOURCES_ENV, raising=False)
        result = _run_kanon(
            "install",
            str(v3_lock_project / _KANON_NAME),
            extra_env={_INSECURE_REMOTES_ENV: _INSECURE_REMOTES_VALUE},
        )
        assert result.returncode != 0, f"precondition: install must fail. stderr={result.stderr!r}"

        assert "v3" in result.stderr, f"stderr must name the offending schema version v3.\n  stderr={result.stderr!r}"
        assert "regenerate" in result.stderr.lower(), (
            f"stderr must instruct the operator to regenerate the lock.\n  stderr={result.stderr!r}"
        )
        assert "kanon add" in result.stderr and "kanon install" in result.stderr, (
            f"stderr must name the 'kanon add' / 'kanon install' regenerate path.\n  stderr={result.stderr!r}"
        )

    def test_install_v3_lock_emits_no_python_traceback(
        self, v3_lock_project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The v3-lock failure is a clean diagnostic, never a raw Python traceback.

        The ``LockfileSchemaError`` raised while reading the legacy lock must be
        caught at the CLI boundary and surfaced as a single actionable
        ``ERROR:`` line on stderr (spec fail-fast: clean, actionable error). A
        leaked multi-frame traceback would satisfy the weaker exit-code and
        message-present checks, so this asserts the absence of the traceback
        header and the presence of the clean ``ERROR:`` prefix explicitly.
        """
        monkeypatch.delenv(_CATALOG_SOURCES_ENV, raising=False)
        result = _run_kanon(
            "install",
            str(v3_lock_project / _KANON_NAME),
            extra_env={_INSECURE_REMOTES_ENV: _INSECURE_REMOTES_VALUE},
        )
        assert result.returncode == 1, (
            f"a v3 lock must fail fast with exit 1.\n  returncode={result.returncode}\n  stderr={result.stderr!r}"
        )
        assert _TRACEBACK_HEADER not in result.stderr, (
            f"the v3-lock failure must surface a clean diagnostic, not a Python traceback.\n  stderr={result.stderr!r}"
        )
        assert _TRACEBACK_HEADER not in result.stdout, (
            f"no Python traceback may leak to stdout either.\n  stdout={result.stdout!r}"
        )
        assert result.stderr.startswith(_CLEAN_ERROR_PREFIX), (
            f"stderr must be the clean single 'ERROR:' diagnostic line.\n  stderr={result.stderr!r}"
        )
        assert "kanon_cli.core.lockfile.LockfileSchemaError" not in result.stderr, (
            f"the raw exception class path must not leak to stderr.\n  stderr={result.stderr!r}"
        )

    def test_no_v3_regenerate_guidance_leaks_to_stdout(
        self, v3_lock_project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regenerate guidance is a diagnostic: it goes to stderr, not stdout."""
        monkeypatch.delenv(_CATALOG_SOURCES_ENV, raising=False)
        result = _run_kanon(
            "install",
            str(v3_lock_project / _KANON_NAME),
            extra_env={_INSECURE_REMOTES_ENV: _INSECURE_REMOTES_VALUE},
        )
        assert result.returncode != 0, f"precondition: install must fail. stderr={result.stderr!r}"
        assert "regenerate" not in result.stdout.lower(), (
            f"the v3 regenerate diagnostic must not be written to stdout.\n  stdout={result.stdout!r}"
        )

    def test_v3_lock_left_unupgraded_on_disk(
        self, v3_lock_project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failed install never rewrites the legacy lock to the current schema (no silent upgrade)."""
        monkeypatch.delenv(_CATALOG_SOURCES_ENV, raising=False)
        lock_path = v3_lock_project / _LOCKFILE_NAME
        original = lock_path.read_text(encoding="utf-8")

        result = _run_kanon(
            "install",
            str(v3_lock_project / _KANON_NAME),
            extra_env={_INSECURE_REMOTES_ENV: _INSECURE_REMOTES_VALUE},
        )
        assert result.returncode != 0, f"precondition: install must fail. stderr={result.stderr!r}"

        after = lock_path.read_text(encoding="utf-8")
        assert after == original, "a failed v3-lock install must leave .kanon.lock byte-identical (no silent rewrite)"
        assert _LEGACY_SCHEMA_VERSION_LINE in after, "the on-disk lock must remain schema_version = 3"
        assert _LEGACY_CATALOG_HEADER in after, "the on-disk lock must retain its legacy [catalog] block"
