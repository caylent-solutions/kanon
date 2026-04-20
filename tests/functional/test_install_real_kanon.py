"""Functional tests for kanon install path variants (real subprocess, no mocks).

Exercises the CLI end-to-end via subprocess against real temporary directories
to verify path resolution and error behaviour without any patching.

Covers:
  - AC-TEST-001: auto-discovery finds .kanon in CWD or ancestor
  - AC-TEST-002: relative path .kanon resolved to absolute (regression guard E0-INSTALL-RELATIVE)
  - AC-TEST-003: absolute path accepted unchanged
  - AC-TEST-004: relative subdir path resolved correctly
  - AC-TEST-005: missing .kanon exits 1 with ".kanon file not found" message
  - AC-CHANNEL-001: stdout vs stderr discipline -- errors go to stderr, normal output to stdout
"""

import pathlib

import pytest

from tests.functional.conftest import _run_kanon
from tests.conftest import write_kanonenv


@pytest.mark.functional
class TestInstallAutoDiscoveryFunctional:
    """AC-TEST-001: auto-discovers .kanon in CWD or ancestor via real subprocess."""

    def test_install_no_arg_finds_kanonenv_in_cwd(self, tmp_path: pathlib.Path) -> None:
        """install with no arg discovers .kanon in cwd and attempts to proceed past path resolution."""
        write_kanonenv(tmp_path)
        result = _run_kanon("install", cwd=tmp_path)
        # The CLI finds the file and prints the discovered path to stdout; then
        # it proceeds to the network/repo phase which may fail -- but the file
        # was found and path resolution succeeded.
        assert ".kanon file not found" not in result.stderr, (
            f"Auto-discovery should have found .kanon in cwd. stderr={result.stderr!r}"
        )
        assert "kanon install: found" in result.stdout, (
            f"Expected auto-discovery success message in stdout. stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_install_no_arg_finds_kanonenv_in_ancestor(self, tmp_path: pathlib.Path) -> None:
        """install with no arg discovers .kanon two levels above cwd."""
        write_kanonenv(tmp_path)
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        result = _run_kanon("install", cwd=deep)
        assert ".kanon file not found" not in result.stderr, (
            f"Auto-discovery should have found .kanon in ancestor. stderr={result.stderr!r}"
        )
        assert "kanon install: found" in result.stdout, (
            f"Expected auto-discovery success message in stdout. stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_install_no_arg_missing_kanonenv_exits_1(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-005: install with no arg in directory without .kanon exits 1."""
        empty = tmp_path / "empty"
        empty.mkdir()
        result = _run_kanon("install", cwd=empty)
        assert result.returncode == 1
        assert ".kanon" in result.stderr, f"Expected '.kanon' in stderr when no .kanon found. stderr={result.stderr!r}"


@pytest.mark.functional
class TestInstallRelativePathFunctional:
    """AC-TEST-002: relative path .kanon resolved to absolute."""

    def test_install_relative_path_dot_kanon_succeeds_past_file_resolution(self, tmp_path: pathlib.Path) -> None:
        """install .kanon (relative) finds the file and proceeds past path resolution."""
        write_kanonenv(tmp_path)
        result = _run_kanon("install", ".kanon", cwd=tmp_path)
        # The .kanon exists and should be resolved -- no "file not found" error.
        assert ".kanon file not found" not in result.stderr, (
            f"Relative '.kanon' should resolve to the file in cwd. stderr={result.stderr!r}"
        )

    def test_install_relative_path_missing_exits_1_with_not_found_message(self, tmp_path: pathlib.Path) -> None:
        """install nonexistent relative path exits 1 with '.kanon file not found'."""
        result = _run_kanon("install", ".kanon", cwd=tmp_path)
        assert result.returncode == 1
        assert ".kanon file not found" in result.stderr, (
            f"Expected '.kanon file not found' in stderr. stderr={result.stderr!r}"
        )


@pytest.mark.functional
class TestInstallAbsolutePathFunctional:
    """AC-TEST-003: absolute path accepted unchanged."""

    def test_install_absolute_path_resolves_correctly(self, tmp_path: pathlib.Path) -> None:
        """install /abs/.kanon finds the file and proceeds past path resolution."""
        kanonenv = write_kanonenv(tmp_path)
        result = _run_kanon("install", str(kanonenv))
        assert ".kanon file not found" not in result.stderr, (
            f"Absolute path should resolve the file. stderr={result.stderr!r}"
        )

    def test_install_nonexistent_absolute_path_exits_1_with_not_found(self, tmp_path: pathlib.Path) -> None:
        """install /nonexistent/.kanon exits 1 with '.kanon file not found'."""
        nonexistent = str(tmp_path / "does_not_exist" / ".kanon")
        result = _run_kanon("install", nonexistent)
        assert result.returncode == 1
        assert ".kanon file not found" in result.stderr, (
            f"Expected '.kanon file not found' in stderr for nonexistent absolute path. stderr={result.stderr!r}"
        )


@pytest.mark.functional
class TestInstallRelativeSubdirPathFunctional:
    """AC-TEST-004: relative subdir path resolved correctly."""

    def test_install_relative_subdir_path_resolves_correctly(self, tmp_path: pathlib.Path) -> None:
        """install subdir/.kanon resolves the subdir relative path correctly."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        write_kanonenv(subdir)
        result = _run_kanon("install", "subdir/.kanon", cwd=tmp_path)
        assert ".kanon file not found" not in result.stderr, (
            f"Relative subdir path 'subdir/.kanon' should resolve the file. stderr={result.stderr!r}"
        )

    def test_install_relative_subdir_path_missing_exits_1(self, tmp_path: pathlib.Path) -> None:
        """install subdir/.kanon when file is missing exits 1 with '.kanon file not found'."""
        result = _run_kanon("install", "subdir/.kanon", cwd=tmp_path)
        assert result.returncode == 1
        assert ".kanon file not found" in result.stderr, (
            f"Expected '.kanon file not found' for missing subdir/.kanon. stderr={result.stderr!r}"
        )


@pytest.mark.functional
class TestInstallChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr discipline for CLI install errors."""

    def test_not_found_error_goes_to_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """AC-CHANNEL-001: '.kanon file not found' error must appear on stderr, not stdout."""
        empty = tmp_path / "empty"
        empty.mkdir()
        result = _run_kanon("install", cwd=empty)
        assert result.returncode == 1
        assert ".kanon" in result.stderr, f"Error must be on stderr. stderr={result.stderr!r}"
        assert ".kanon file not found" not in result.stdout, f"Error must NOT leak to stdout. stdout={result.stdout!r}"

    def test_explicit_missing_path_error_goes_to_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """AC-CHANNEL-001: explicit missing .kanon path error goes to stderr, not stdout."""
        nonexistent = str(tmp_path / "ghost" / ".kanon")
        result = _run_kanon("install", nonexistent)
        assert result.returncode == 1
        assert ".kanon file not found" in result.stderr, f"Error must be on stderr. stderr={result.stderr!r}"
        assert ".kanon file not found" not in result.stdout, f"Error must NOT leak to stdout. stdout={result.stdout!r}"

    def test_successful_autodiscovery_prints_found_to_stdout(self, tmp_path: pathlib.Path) -> None:
        """AC-CHANNEL-001: successful auto-discovery prints found path to stdout."""
        write_kanonenv(tmp_path)
        result = _run_kanon("install", cwd=tmp_path)
        # Auto-discovery emits "kanon install: found <path>" to stdout (from commands/install.py:112)
        # The install will then fail in the repo phase but the path-found message must be on stdout.
        # We only check channel discipline -- not that install succeeds end-to-end.
        assert "kanon install: found" in result.stdout, (
            f"Auto-discovery 'found' message must be on stdout not stderr. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
