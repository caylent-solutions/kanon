"""Functional tests for kanon bootstrap list mode and default target (CWD).

Covers:
- AC-TEST-001: kanon bootstrap list exits 0 and stdout contains "Available packages"
- AC-TEST-002: kanon bootstrap kanon exits 0 and creates .kanon + kanon-readme.md in CWD
- AC-FUNC-001: Default bootstrap target is CWD when --output-dir is omitted
- AC-FUNC-002: list mode does not write any files
- AC-CHANNEL-001: stdout vs stderr discipline (no cross-channel leakage)
"""

import subprocess
import sys

import pytest


def _run_kanon(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Invoke kanon_cli in a subprocess and return the completed process.

    Args:
        args: CLI arguments passed after 'python -m kanon_cli'.
        cwd: Working directory for the subprocess. Defaults to None (inherits caller's cwd).

    Returns:
        CompletedProcess with returncode, stdout, and stderr captured as text.
    """
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


@pytest.mark.functional
class TestBootstrapListMode:
    """AC-TEST-001: bootstrap list exits 0 and stdout contains 'Available packages'.

    Also covers AC-FUNC-002 (list mode does not write files) and
    AC-CHANNEL-001 (stdout vs stderr discipline).
    """

    def test_list_exits_zero(self) -> None:
        """kanon bootstrap list must exit with code 0."""
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 0

    def test_list_stdout_contains_available_packages_header(self) -> None:
        """kanon bootstrap list stdout must contain the 'Available packages' header string."""
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 0
        assert "Available packages" in result.stdout

    def test_list_stdout_contains_kanon_package_name(self) -> None:
        """kanon bootstrap list stdout must include 'kanon' as a listed package."""
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 0
        assert "kanon" in result.stdout

    def test_list_no_cross_channel_leakage_to_stderr(self) -> None:
        """kanon bootstrap list must not write normal output to stderr (AC-CHANNEL-001)."""
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 0
        assert result.stderr == "", f"Expected empty stderr for 'kanon bootstrap list', got: {result.stderr!r}"

    def test_list_does_not_write_files(self, tmp_path) -> None:
        """kanon bootstrap list must not create or modify any files (AC-FUNC-002)."""
        result = _run_kanon("bootstrap", "list", cwd=str(tmp_path))
        assert result.returncode == 0
        created = list(tmp_path.iterdir())
        assert created == [], f"Expected no files written by 'kanon bootstrap list', found: {created!r}"


@pytest.mark.functional
class TestBootstrapDefaultTarget:
    """AC-TEST-002 and AC-FUNC-001: kanon bootstrap kanon uses CWD when --output-dir is omitted.

    Also covers AC-CHANNEL-001 (stdout vs stderr discipline).
    """

    def test_bootstrap_kanon_without_output_dir_exits_zero(self, tmp_path) -> None:
        """kanon bootstrap kanon (no --output-dir) must exit with code 0."""
        result = _run_kanon("bootstrap", "kanon", cwd=str(tmp_path))
        assert result.returncode == 0

    def test_bootstrap_kanon_without_output_dir_creates_kanonenv_in_cwd(self, tmp_path) -> None:
        """kanon bootstrap kanon must create .kanon in CWD when --output-dir is omitted (AC-FUNC-001)."""
        result = _run_kanon("bootstrap", "kanon", cwd=str(tmp_path))
        assert result.returncode == 0
        assert (tmp_path / ".kanon").is_file(), (
            f".kanon not found in CWD {tmp_path} after bootstrap without --output-dir"
        )

    def test_bootstrap_kanon_without_output_dir_creates_readme_in_cwd(self, tmp_path) -> None:
        """kanon bootstrap kanon must create kanon-readme.md in CWD when --output-dir is omitted."""
        result = _run_kanon("bootstrap", "kanon", cwd=str(tmp_path))
        assert result.returncode == 0
        assert (tmp_path / "kanon-readme.md").is_file(), (
            f"kanon-readme.md not found in CWD {tmp_path} after bootstrap without --output-dir"
        )

    def test_bootstrap_kanon_without_output_dir_creates_exactly_expected_files(self, tmp_path) -> None:
        """kanon bootstrap kanon in CWD must create exactly .kanon and kanon-readme.md (AC-TEST-002)."""
        result = _run_kanon("bootstrap", "kanon", cwd=str(tmp_path))
        assert result.returncode == 0
        created_files = sorted(f.name for f in tmp_path.iterdir())
        assert created_files == [".kanon", "kanon-readme.md"], (
            f"Expected ['.kanon', 'kanon-readme.md'], got {created_files!r}"
        )

    def test_bootstrap_kanon_normal_output_goes_to_stdout_not_stderr(self, tmp_path) -> None:
        """kanon bootstrap kanon success output must not appear in stderr (AC-CHANNEL-001)."""
        result = _run_kanon("bootstrap", "kanon", cwd=str(tmp_path))
        assert result.returncode == 0
        assert result.stderr == "", f"Expected empty stderr on success, got: {result.stderr!r}"

    def test_bootstrap_kanon_error_output_goes_to_stderr_not_stdout(self, tmp_path) -> None:
        """kanon bootstrap with unknown package must report error on stderr (AC-CHANNEL-001)."""
        result = _run_kanon("bootstrap", "nonexistent-package-xyz", cwd=str(tmp_path))
        assert result.returncode != 0
        assert result.stderr != "", "Expected error message on stderr for unknown package"
        assert "nonexistent-package-xyz" in result.stderr
        assert "nonexistent-package-xyz" not in result.stdout
