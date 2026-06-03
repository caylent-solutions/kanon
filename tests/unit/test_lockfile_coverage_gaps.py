"""Unit tests closing coverage gaps in src/kanon_cli/core/lockfile.py.

Gaps targeted (from the E15-F4-S1-T1 coverage-gap analysis):
- Line 320: _validate_kanon_hash raises LockfileValidationError on invalid hash
- Lines 822-824: write_lockfile inner exception handler (fdopen/flush/fsync failure)
- Lines 826-828: write_lockfile outer exception handler (os.replace failure)

All gaps are category "test-needed".
"""

from __future__ import annotations

import pathlib

import pytest

from kanon_cli.core.lockfile import (
    CatalogBlock,
    Lockfile,
    LockfileValidationError,
    read_lockfile,
    write_lockfile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_VALID_SHA40 = "a" * 40
_VALID_KANON_HASH = "sha256:" + "a" * 64

_VALID_CATALOG = CatalogBlock(
    source="https://example.com/catalog.git@main",
    url="https://example.com/catalog.git",
    revision_spec="main",
    resolved_ref="refs/heads/main",
    resolved_sha=_VALID_SHA40,
)


def _make_lockfile(**kwargs) -> Lockfile:
    """Return a minimal valid Lockfile dataclass with optional field overrides.

    Args:
        **kwargs: Field overrides for the Lockfile constructor.

    Returns:
        A Lockfile instance.
    """
    defaults = {
        "schema_version": 1,
        "generated_at": "2026-01-01T00:00:00Z",
        "generator": "kanon-cli/1.0.0",
        "kanon_hash": _VALID_KANON_HASH,
        "catalog": _VALID_CATALOG,
        "sources": [],
    }
    defaults.update(kwargs)
    return Lockfile(**defaults)


def _write_lockfile_toml(path: pathlib.Path, kanon_hash: str) -> None:
    """Write a minimal valid lockfile TOML with the given kanon_hash value.

    Used by _validate_kanon_hash tests: the validator runs inside read_lockfile,
    not during Lockfile dataclass construction.

    Args:
        path: Destination file path.
        kanon_hash: The kanon_hash value to embed in the TOML.
    """
    toml = (
        "schema_version = 1\n"
        'generated_at = "2026-01-01T00:00:00Z"\n'
        'generator = "kanon-cli/1.0.0"\n'
        f'kanon_hash = "{kanon_hash}"\n'
        "\n"
        "[catalog]\n"
        'source = "https://example.com/catalog.git@main"\n'
        'url = "https://example.com/catalog.git"\n'
        'revision_spec = "main"\n'
        'resolved_ref = "refs/heads/main"\n'
        f'resolved_sha = "{_VALID_SHA40}"\n'
    )
    path.write_text(toml, encoding="utf-8")


# ---------------------------------------------------------------------------
# Line 320: _validate_kanon_hash raises LockfileValidationError
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
# Lines 822-824: write_lockfile inner exception handler (fsync failure)
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
# Lines 826-828: write_lockfile outer exception handler (os.replace failure)
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
