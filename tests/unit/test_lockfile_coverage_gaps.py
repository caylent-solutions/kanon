"""Unit tests closing coverage gaps in src/kanon_cli/core/lockfile.py (schema v4).

Gaps targeted (from the E15-F4-S1-T1 coverage-gap analysis):
- _validate_kanon_hash raises LockfileValidationError on invalid hash
- write_lockfile inner exception handler (fdopen/flush/fsync failure)
- write_lockfile outer exception handler (os.replace failure)

Schema v4 (spec Section 5.2 / FLAG-C) removed the global [catalog] block and the
CatalogBlock dataclass, re-keyed each [[sources]] entry by alias, and renamed the
per-entry version-constraint field to ``ref_spec``. The fixtures below build a v4
alias-keyed lock (no [catalog] table); the round-trip / no-catalog / v3-hard-fail
behaviours unique to v4 are asserted directly so the catalog-block removal is
covered by a real, falsifiable test rather than only by the (now-deleted) import.

All gaps are category "test-needed".
"""

from __future__ import annotations

import pathlib

import pytest

from kanon_cli.core.lockfile import (
    CURRENT_SCHEMA_VERSION,
    Lockfile,
    LockfileSchemaError,
    LockfileValidationError,
    SourceEntry,
    read_lockfile,
    write_lockfile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_VALID_SHA40 = "a" * 40
_VALID_KANON_HASH = "sha256:" + "a" * 64


def _make_source(**kwargs) -> SourceEntry:
    """Return a valid alias-keyed v4 SourceEntry with optional overrides."""
    defaults = dict(
        alias="src",
        name="src",
        url="https://example.com/source.git",
        ref_spec="main",
        resolved_ref="refs/heads/main",
        resolved_sha=_VALID_SHA40,
        path="repo-specs/source.xml",
    )
    defaults.update(kwargs)
    return SourceEntry(**defaults)


def _make_lockfile(**kwargs) -> Lockfile:
    """Return a minimal valid schema-v4 Lockfile dataclass with optional overrides.

    Schema v4 has no ``catalog`` field; the lock carries an alias-keyed
    ``[[sources]]`` list and no ``[catalog]`` block.

    Args:
        **kwargs: Field overrides for the Lockfile constructor.

    Returns:
        A Lockfile instance.
    """
    defaults = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "generated_at": "2026-01-01T00:00:00Z",
        "generator": "kanon-cli/2.0.0",
        "kanon_hash": _VALID_KANON_HASH,
        "sources": [_make_source()],
    }
    defaults.update(kwargs)
    return Lockfile(**defaults)


def _write_lockfile_toml(path: pathlib.Path, kanon_hash: str) -> None:
    """Write a minimal valid schema-v4 lockfile TOML with the given kanon_hash value.

    Used by _validate_kanon_hash tests: the validator runs inside read_lockfile,
    not during Lockfile dataclass construction. The fixture is alias-keyed and
    carries no [catalog] block (schema v4).

    Args:
        path: Destination file path.
        kanon_hash: The kanon_hash value to embed in the TOML.
    """
    toml = (
        "schema_version = 4\n"
        'generated_at = "2026-01-01T00:00:00Z"\n'
        'generator = "kanon-cli/2.0.0"\n'
        f'kanon_hash = "{kanon_hash}"\n'
        "marketplace_registered = false\n"
        'marketplace_dir = ""\n'
        "\n"
        "[[sources]]\n"
        'alias = "src"\n'
        'name = "src"\n'
        'url = "https://example.com/source.git"\n'
        'ref_spec = "main"\n'
        'resolved_ref = "refs/heads/main"\n'
        f'resolved_sha = "{_VALID_SHA40}"\n'
        'path = "repo-specs/source.xml"\n'
    )
    path.write_text(toml, encoding="utf-8")


# ---------------------------------------------------------------------------
# Schema v4: [catalog] block removed, alias-keyed sources, v3 hard-fail
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSchemaV4CatalogRemoval:
    """The schema-v4 lock has no [catalog] block; CatalogBlock and Lockfile.catalog are gone.

    These tests replace the old CatalogBlock-import-based fixtures with real,
    falsifiable assertions of the v4 behaviour that superseded the global
    [catalog] block (spec Section 5.2 / FLAG-C).
    """

    def test_lockfile_has_no_catalog_field(self) -> None:
        """The v4 Lockfile dataclass exposes no ``catalog`` attribute."""
        lf = _make_lockfile()
        assert not hasattr(lf, "catalog"), "schema v4 removed the global [catalog] block"

    def test_write_emits_no_catalog_block(self, tmp_path: pathlib.Path) -> None:
        """write_lockfile never serialises a [catalog] table on a v4 lock."""
        import tomllib

        lf = _make_lockfile()
        dest = tmp_path / "output.lock"
        write_lockfile(lf, dest)

        text = dest.read_text(encoding="utf-8")
        assert "[catalog]" not in text
        with open(dest, "rb") as f:
            data = tomllib.load(f)
        assert "catalog" not in data

    def test_alias_and_ref_spec_roundtrip(self, tmp_path: pathlib.Path) -> None:
        """A v4 source's alias and ref_spec survive a write/read roundtrip."""
        lf = _make_lockfile(sources=[_make_source(alias="custom-alias", name="src", ref_spec="==1.2.3")])
        dest = tmp_path / "output.lock"
        write_lockfile(lf, dest)

        loaded = read_lockfile(dest)
        assert loaded.sources[0].alias == "custom-alias"
        assert loaded.sources[0].name == "src"
        assert loaded.sources[0].ref_spec == "==1.2.3"

    def test_source_serialised_with_ref_spec_not_revision_spec(self, tmp_path: pathlib.Path) -> None:
        """The on-disk source key is ``ref_spec``; the old ``revision_spec`` key is absent."""
        import tomllib

        lf = _make_lockfile(sources=[_make_source(alias="a", name="src", ref_spec="~=2.0.0")])
        dest = tmp_path / "output.lock"
        write_lockfile(lf, dest)

        with open(dest, "rb") as f:
            data = tomllib.load(f)
        entry = data["sources"][0]
        assert entry["ref_spec"] == "~=2.0.0"
        assert "revision_spec" not in entry

    def test_v3_lock_hard_fails_regenerate(self, tmp_path: pathlib.Path) -> None:
        """A v3 lock (revision_spec-keyed, [catalog] block) fails fast; no silent upgrade."""
        v3_toml = (
            "schema_version = 3\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/1.4.0"\n'
            f'kanon_hash = "{_VALID_KANON_HASH}"\n'
            "marketplace_registered = false\n"
            'marketplace_dir = ""\n'
            "\n"
            "[catalog]\n"
            'source = "https://example.com/catalog.git@main"\n'
            'url = "https://example.com/catalog.git"\n'
            'revision_spec = "main"\n'
            'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{_VALID_SHA40}"\n'
            "\n"
            "[[sources]]\n"
            'name = "src"\n'
            'url = "https://example.com/source.git"\n'
            'revision_spec = "main"\n'
            'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{_VALID_SHA40}"\n'
            'path = "repo-specs/source.xml"\n'
        )
        dest = tmp_path / "v3.lock"
        dest.write_text(v3_toml, encoding="utf-8")

        with pytest.raises(LockfileSchemaError) as exc_info:
            read_lockfile(dest)
        err_msg = str(exc_info.value)
        assert "v3" in err_msg
        assert "kanon add" in err_msg and "kanon install" in err_msg


# ---------------------------------------------------------------------------
# _validate_kanon_hash raises LockfileValidationError
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_hash",
    [
        "a" * 64,  # 64 hex chars without sha256: prefix
        "sha256:" + "a" * 32,  # only 32 hex chars after prefix
        "sha256:" + "A" * 64,  # uppercase hex not allowed
        "sha256:" + "g" * 64,  # 'g' is not a hex char
    ],
    ids=[
        "missing_sha256_prefix",
        "wrong_hex_length",
        "uppercase_hex",
        "non_hex_chars",
    ],
)
def test_validate_kanon_hash_invalid_raises(bad_hash: str, tmp_path: pathlib.Path) -> None:
    """_validate_kanon_hash raises LockfileValidationError for each malformed hash string."""
    lock_file = tmp_path / "test.lock"
    _write_lockfile_toml(lock_file, bad_hash)
    with pytest.raises(LockfileValidationError, match="Invalid kanon_hash"):
        read_lockfile(lock_file)


@pytest.mark.unit
class TestValidateKanonHash:
    """Additional _validate_kanon_hash tests for error-message content and valid-hash baseline."""

    def test_invalid_hash_error_message_contains_value(self, tmp_path: pathlib.Path) -> None:
        """LockfileValidationError message includes the invalid value."""
        bad_hash = "sha256:badvalue"
        lock_file = tmp_path / "test.lock"
        _write_lockfile_toml(lock_file, bad_hash)
        with pytest.raises(LockfileValidationError) as exc_info:
            read_lockfile(lock_file)
        assert "badvalue" in str(exc_info.value)

    def test_valid_hash_does_not_raise(self, tmp_path: pathlib.Path) -> None:
        """A correctly formatted kanon_hash does not raise."""
        valid_hash = "sha256:" + "a" * 64
        lock_file = tmp_path / "test.lock"
        _write_lockfile_toml(lock_file, valid_hash)
        lf = read_lockfile(lock_file)
        assert lf.kanon_hash == valid_hash

    def test_invalid_hash_error_message_mentions_sha256(self, tmp_path: pathlib.Path) -> None:
        """LockfileValidationError message mentions the expected 'sha256:' prefix."""
        bad_hash = "md5:abc"
        lock_file = tmp_path / "test.lock"
        _write_lockfile_toml(lock_file, bad_hash)
        with pytest.raises(LockfileValidationError) as exc_info:
            read_lockfile(lock_file)
        assert "sha256" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# write_lockfile inner exception handler (fsync failure)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWriteLockfileInnerExceptionHandler:
    """write_lockfile cleans up temp file and re-raises when fdopen/fsync fails."""

    def test_fsync_failure_re_raises_exception(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When os.fsync raises OSError, write_lockfile re-raises it."""
        import kanon_cli.core.lockfile as lockfile_mod

        def _failing_fsync(fd: int) -> None:
            raise OSError("simulated fsync failure")

        monkeypatch.setattr(lockfile_mod.os, "fsync", _failing_fsync)

        lockfile = _make_lockfile()
        dest = tmp_path / "output.lock"

        with pytest.raises(OSError, match="simulated fsync failure"):
            write_lockfile(lockfile, dest)

    def test_fsync_failure_temp_file_cleaned_up(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When os.fsync raises, the temp file is removed before re-raise."""
        import kanon_cli.core.lockfile as lockfile_mod

        created_tmp_files: list[pathlib.Path] = []
        original_mkstemp = lockfile_mod.tempfile.mkstemp

        def _recording_mkstemp(**kwargs):
            fd, path = original_mkstemp(**kwargs)
            created_tmp_files.append(pathlib.Path(path))
            return fd, path

        def _failing_fsync(fd: int) -> None:
            raise OSError("simulated fsync failure")

        monkeypatch.setattr(lockfile_mod.tempfile, "mkstemp", _recording_mkstemp)
        monkeypatch.setattr(lockfile_mod.os, "fsync", _failing_fsync)

        lockfile = _make_lockfile()
        dest = tmp_path / "output.lock"

        with pytest.raises(OSError):
            write_lockfile(lockfile, dest)

        # Verify all temp files created during the call were cleaned up
        for tmp_path_item in created_tmp_files:
            assert not tmp_path_item.exists(), f"Temp file {tmp_path_item} should have been removed on fsync failure"

    def test_dest_not_written_on_fsync_failure(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When os.fsync fails, the destination file is not written."""
        import kanon_cli.core.lockfile as lockfile_mod

        def _failing_fsync(fd: int) -> None:
            raise OSError("simulated fsync failure")

        monkeypatch.setattr(lockfile_mod.os, "fsync", _failing_fsync)

        lockfile = _make_lockfile()
        dest = tmp_path / "output.lock"

        with pytest.raises(OSError):
            write_lockfile(lockfile, dest)

        assert not dest.exists()


# ---------------------------------------------------------------------------
# write_lockfile outer exception handler (os.replace failure)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWriteLockfileOuterExceptionHandler:
    """write_lockfile cleans up temp file and re-raises when os.replace fails."""

    def test_replace_failure_re_raises_exception(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When os.replace raises OSError, write_lockfile re-raises it."""
        import kanon_cli.core.lockfile as lockfile_mod

        def _failing_replace(src: str, dst: str) -> None:
            raise OSError("simulated replace failure")

        monkeypatch.setattr(lockfile_mod.os, "replace", _failing_replace)

        lockfile = _make_lockfile()
        dest = tmp_path / "output.lock"

        with pytest.raises(OSError, match="simulated replace failure"):
            write_lockfile(lockfile, dest)

    def test_replace_failure_temp_file_cleaned_up(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When os.replace raises, the temp file is cleaned up before re-raise."""
        import kanon_cli.core.lockfile as lockfile_mod

        created_tmp_files: list[pathlib.Path] = []
        original_mkstemp = lockfile_mod.tempfile.mkstemp

        def _recording_mkstemp(**kwargs):
            fd, path = original_mkstemp(**kwargs)
            created_tmp_files.append(pathlib.Path(path))
            return fd, path

        def _failing_replace(src: str, dst: str) -> None:
            raise OSError("simulated replace failure")

        monkeypatch.setattr(lockfile_mod.tempfile, "mkstemp", _recording_mkstemp)
        monkeypatch.setattr(lockfile_mod.os, "replace", _failing_replace)

        lockfile = _make_lockfile()
        dest = tmp_path / "output.lock"

        with pytest.raises(OSError):
            write_lockfile(lockfile, dest)

        for tmp_file in created_tmp_files:
            assert not tmp_file.exists(), f"Temp file {tmp_file} should have been removed on os.replace failure"

    def test_dest_not_written_on_replace_failure(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When os.replace fails, the destination file is not written."""
        import kanon_cli.core.lockfile as lockfile_mod

        def _failing_replace(src: str, dst: str) -> None:
            raise OSError("simulated replace failure")

        monkeypatch.setattr(lockfile_mod.os, "replace", _failing_replace)

        lockfile = _make_lockfile()
        dest = tmp_path / "output.lock"

        with pytest.raises(OSError):
            write_lockfile(lockfile, dest)

        assert not dest.exists()

    def test_successful_write_creates_destination(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Confirming baseline: a successful write_lockfile creates the destination file."""
        lockfile = _make_lockfile()
        dest = tmp_path / "output.lock"

        write_lockfile(lockfile, dest)

        assert dest.exists()
        content = dest.read_text(encoding="utf-8")
        assert "schema_version" in content
