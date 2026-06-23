"""Functional black-box test for ``kanon validate lockfile`` (AC-T4S5-1).

Drives the real CLI as a subprocess (``python -m kanon_cli validate lockfile``)
against on-disk ``.kanon`` and ``.kanon.lock`` fixtures, asserting:

  - exit 0 on a consistent ``.kanon`` <-> ``.kanon.lock`` pair,
  - a non-zero exit and an actionable message on alias-set drift,
  - a non-zero exit and an actionable message on per-alias ref-spec drift,
  - a non-zero exit on a duplicate ``.kanon`` alias.

The lock fixture is produced by the real ``write_lockfile`` serializer so the
test exercises the production read path; no resolver / git ls-remote is invoked
because ``validate lockfile`` only reads the two files (spec Section 4.5 / FR-24).
"""

import pytest

from kanon_cli.core.lockfile import Lockfile, SourceEntry, write_lockfile

from tests.functional.conftest import _run_kanon

# -- Fixture field constants (no inline magic literals in the test bodies) --
_VALID_SHA40 = "a" * 40
_VALID_KANON_HASH = "sha256:" + "a" * 64
_KANONENV_FILENAME = ".kanon"
_LOCK_FILENAME = ".kanon.lock"
_VALIDATE_TOKEN = "validate"
_LOCKFILE_TOKEN = "lockfile"

# Aliases and ref-specs reused across the consistent / drift scenarios.
_ALPHA = "alpha"
_BETA = "beta"
_REF_BRANCH = "main"
_REF_PINNED = "==1.2.3"
_REF_DRIFTED = "==9.9.9"


def _write_kanon(directory, sources):
    """Write a minimal ``.kanon`` declaring the given source triples; return its path.

    Args:
        directory: Directory the ``.kanon`` file is written into.
        sources: Mapping of alias to a dict carrying ``url``, ``revision`` and
            ``path`` for that source.

    Returns:
        The path to the written ``.kanon`` file.
    """
    lines = []
    for alias, data in sources.items():
        lines.append(f"KANON_SOURCE_{alias}_URL={data['url']}")
        lines.append(f"KANON_SOURCE_{alias}_REF={data['revision']}")
        lines.append(f"KANON_SOURCE_{alias}_PATH={data['path']}")
        lines.append(f"KANON_SOURCE_{alias}_NAME={alias}")
        lines.append(f"KANON_SOURCE_{alias}_GITBASE={data['url']}")
    path = directory / _KANONENV_FILENAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _source_entry(alias, ref_spec):
    """Return a v4 SourceEntry for the given alias and ref-spec with valid scalar fields."""
    return SourceEntry(
        alias=alias,
        name=alias,
        url=f"https://example.com/{alias}.git",
        ref_spec=ref_spec,
        resolved_ref="refs/heads/main",
        resolved_sha=_VALID_SHA40,
        path=f"repo-specs/{alias}.xml",
    )


def _write_lock(directory, sources):
    """Write a v4 ``.kanon.lock`` carrying the given source entries; return its path.

    Args:
        directory: Directory the ``.kanon.lock`` file is written into.
        sources: The list of alias-keyed SourceEntry objects to serialise.

    Returns:
        The path to the written ``.kanon.lock`` file.
    """
    lockfile = Lockfile(
        schema_version=4,
        generated_at="2026-01-01T00:00:00Z",
        generator="kanon-cli/3.0.0",
        kanon_hash=_VALID_KANON_HASH,
        sources=sources,
    )
    path = directory / _LOCK_FILENAME
    write_lockfile(lockfile, path)
    return path


@pytest.mark.functional
def test_validate_lockfile_consistent_pair_exits_0(tmp_path):
    """A consistent .kanon / .kanon.lock pair exits 0 with a confirmation message."""
    _write_kanon(
        tmp_path,
        {
            _ALPHA: {"url": "https://example.com/alpha.git", "revision": _REF_BRANCH, "path": "p1"},
            _BETA: {"url": "https://example.com/beta.git", "revision": _REF_PINNED, "path": "p2"},
        },
    )
    _write_lock(tmp_path, [_source_entry(_ALPHA, _REF_BRANCH), _source_entry(_BETA, _REF_PINNED)])

    result = _run_kanon(_VALIDATE_TOKEN, _LOCKFILE_TOKEN, cwd=tmp_path)

    assert result.returncode == 0, (
        f"'kanon validate lockfile' must exit 0 on a consistent pair.\n"
        f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
    )
    assert "are consistent" in result.stdout


@pytest.mark.functional
def test_validate_lockfile_alias_set_drift_exits_nonzero(tmp_path):
    """A .kanon declaring an alias missing from the lock exits non-zero with a clear message."""
    _write_kanon(
        tmp_path,
        {
            _ALPHA: {"url": "https://example.com/alpha.git", "revision": _REF_BRANCH, "path": "p1"},
            _BETA: {"url": "https://example.com/beta.git", "revision": _REF_BRANCH, "path": "p2"},
        },
    )
    _write_lock(tmp_path, [_source_entry(_ALPHA, _REF_BRANCH)])

    result = _run_kanon(_VALIDATE_TOKEN, _LOCKFILE_TOKEN, cwd=tmp_path)

    assert result.returncode != 0, (
        f"'kanon validate lockfile' must exit non-zero on alias-set drift.\n"
        f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
    )
    assert "alias sets differ" in result.stderr
    assert _BETA in result.stderr


@pytest.mark.functional
def test_validate_lockfile_ref_spec_drift_exits_nonzero(tmp_path):
    """A per-alias ref-spec that differs between .kanon and the lock exits non-zero."""
    _write_kanon(
        tmp_path,
        {_ALPHA: {"url": "https://example.com/alpha.git", "revision": _REF_DRIFTED, "path": "p1"}},
    )
    _write_lock(tmp_path, [_source_entry(_ALPHA, _REF_BRANCH)])

    result = _run_kanon(_VALIDATE_TOKEN, _LOCKFILE_TOKEN, cwd=tmp_path)

    assert result.returncode != 0, (
        f"'kanon validate lockfile' must exit non-zero on ref-spec drift.\n"
        f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
    )
    assert "ref-specs differ" in result.stderr
    assert _REF_DRIFTED in result.stderr


@pytest.mark.functional
def test_validate_lockfile_duplicate_alias_exits_nonzero(tmp_path):
    """A duplicate KANON_SOURCE_<alias>_* key in .kanon exits non-zero (duplicate alias)."""
    kanon_path = tmp_path / _KANONENV_FILENAME
    kanon_path.write_text(
        "KANON_SOURCE_alpha_URL=https://example.com/alpha.git\n"
        "KANON_SOURCE_alpha_REF=main\n"
        "KANON_SOURCE_alpha_PATH=p1\n"
        "KANON_SOURCE_alpha_URL=https://example.com/dup.git\n",
        encoding="utf-8",
    )
    _write_lock(tmp_path, [_source_entry(_ALPHA, _REF_BRANCH)])

    result = _run_kanon(_VALIDATE_TOKEN, _LOCKFILE_TOKEN, cwd=tmp_path)

    assert result.returncode != 0, (
        f"'kanon validate lockfile' must exit non-zero on a duplicate .kanon alias.\n"
        f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
    )
    assert "Duplicate key" in result.stderr
