"""Functional tests for kanon bootstrap error paths.

Covers:
- AC-TEST-001: Missing positional package argument exits 2 with argparse error
- AC-TEST-002: Unknown package name exits 1 with "package not found" or "Unknown" error
- AC-TEST-003: Bad --output-dir parent (uncreateable path) exits 1 with clean diagnostic
- AC-FUNC-001: Error paths produce non-zero exit codes and stderr messages, never silently succeed
- AC-CHANNEL-001: stdout vs stderr discipline verified (no cross-channel leakage)
"""

import pathlib

import pytest

from tests.functional.conftest import _run_kanon


@pytest.mark.functional
class TestBootstrapMissingPackage:
    """AC-TEST-001: kanon bootstrap with no positional package argument must exit 2.

    argparse exits with code 2 when a required positional argument is omitted.
    The error message goes to stderr; stdout must be empty.
    """

    def test_missing_package_exits_2(self) -> None:
        """kanon bootstrap with no package argument must exit with code 2 (argparse error)."""
        result = _run_kanon("bootstrap")
        assert result.returncode == 2, (
            f"Expected exit code 2 for missing positional argument, got {result.returncode}.\nstderr: {result.stderr!r}"
        )

    def test_missing_package_error_on_stderr(self) -> None:
        """kanon bootstrap with no package argument must write an error message to stderr."""
        result = _run_kanon("bootstrap")
        assert result.returncode == 2
        assert result.stderr != "", "Expected argparse error message on stderr when package argument is omitted"

    def test_missing_package_error_contains_required_keyword(self) -> None:
        """argparse error for missing positional argument must mention the argument by name or say 'required'."""
        result = _run_kanon("bootstrap")
        assert result.returncode == 2
        lowered = result.stderr.lower()
        assert "package" in lowered or "required" in lowered, (
            f"Expected 'package' or 'required' in argparse error message, got: {result.stderr!r}"
        )

    def test_missing_package_nothing_on_stdout(self) -> None:
        """kanon bootstrap with no package argument must not write anything to stdout (AC-CHANNEL-001)."""
        result = _run_kanon("bootstrap")
        assert result.returncode == 2
        assert result.stdout == "", f"Expected empty stdout for missing package error, got: {result.stdout!r}"


@pytest.mark.functional
class TestBootstrapUnknownPackage:
    """AC-TEST-002: kanon bootstrap with an unrecognized package name must exit 1.

    The bootstrap command exits 1 (application error) and writes a message
    containing either 'Unknown' or 'not found' to stderr. stdout must be empty.
    """

    @pytest.mark.parametrize("package_name", ["does-not-exist", "no-such-pkg", "totally-unknown-xyz"])
    def test_various_unknown_packages_all_exit_1(self, package_name: str) -> None:
        """kanon bootstrap <unknown> must exit 1 for any unrecognized package name."""
        result = _run_kanon("bootstrap", package_name)
        assert result.returncode == 1, (
            f"Expected exit code 1 for unknown package '{package_name}', got {result.returncode}.\n"
            f"stderr: {result.stderr!r}"
        )

    def test_unknown_package_error_on_stderr(self) -> None:
        """kanon bootstrap <unknown> must write an error message to stderr."""
        result = _run_kanon("bootstrap", "no-such-package-abc")
        assert result.returncode == 1
        assert result.stderr != "", "Expected error message on stderr for unknown package"

    def test_unknown_package_error_message_contains_package_name(self) -> None:
        """The stderr error message must include the unknown package name for diagnostics."""
        result = _run_kanon("bootstrap", "no-such-package-abc")
        assert result.returncode == 1
        assert "no-such-package-abc" in result.stderr, (
            f"Expected package name 'no-such-package-abc' in stderr, got: {result.stderr!r}"
        )

    def test_unknown_package_error_message_contains_unknown_or_not_found(self) -> None:
        """The stderr error must contain 'Unknown' or 'not found' to explain the failure."""
        result = _run_kanon("bootstrap", "no-such-package-abc")
        assert result.returncode == 1
        lowered = result.stderr.lower()
        assert "unknown" in lowered or "not found" in lowered, (
            f"Expected 'Unknown' or 'not found' in error message, got: {result.stderr!r}"
        )

    def test_unknown_package_nothing_on_stdout(self) -> None:
        """kanon bootstrap <unknown> must not write anything to stdout (AC-CHANNEL-001)."""
        result = _run_kanon("bootstrap", "no-such-package-abc")
        assert result.returncode == 1
        assert result.stdout == "", f"Expected empty stdout for unknown package error, got: {result.stdout!r}"

    def test_unknown_package_no_traceback_on_stderr(self) -> None:
        """kanon bootstrap <unknown> must not expose a raw Python traceback on stderr."""
        result = _run_kanon("bootstrap", "no-such-package-abc")
        assert result.returncode == 1
        assert "Traceback" not in result.stderr, (
            f"Expected no raw traceback on stderr for unknown package, got: {result.stderr!r}"
        )


@pytest.mark.functional
class TestBootstrapBadOutputDir:
    """AC-TEST-003: kanon bootstrap with an uncreateable --output-dir parent must exit 1.

    When --output-dir points to a path whose parent directory cannot be created
    (e.g. a subdirectory of a read-only directory), the command must catch this
    and exit 1 with a clean diagnostic rather than printing a raw Python traceback.
    """

    def _make_readonly_parent(self, tmp_path: pathlib.Path) -> pathlib.Path:
        """Create a read-only directory and return a child path that cannot be created.

        Creates a directory under tmp_path, makes it read-only (mode 0o555),
        then returns a path to a subdirectory inside it that cannot be created
        because the parent is not writable.

        Args:
            tmp_path: Pytest-provided temporary directory.

        Returns:
            A path whose parent exists but is read-only, making mkdir fail.
        """
        readonly_parent = tmp_path / "readonly-dir"
        readonly_parent.mkdir()
        readonly_parent.chmod(0o555)
        return readonly_parent / "blocked-subdir"

    def test_bad_output_dir_parent_exits_1(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap with uncreateable --output-dir must exit with code 1.

        The read-only parent prevents mkdir from succeeding. The command must
        catch this and exit 1 rather than printing a raw Python traceback and
        exiting with an unexpected code.
        """
        blocked_path = self._make_readonly_parent(tmp_path)
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(blocked_path))
        assert result.returncode == 1, (
            f"Expected exit code 1 for uncreateable output directory, got {result.returncode}.\n"
            f"stderr: {result.stderr!r}"
        )

    def test_bad_output_dir_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap with bad --output-dir must write a clean diagnostic to stderr."""
        blocked_path = self._make_readonly_parent(tmp_path)
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(blocked_path))
        assert result.returncode == 1
        assert result.stderr != "", "Expected error message on stderr for uncreateable output directory"
        assert "Traceback" not in result.stderr, (
            f"Expected clean error message, not a raw Python traceback.\nstderr: {result.stderr!r}"
        )
        assert "Cannot create output directory" in result.stderr or "output" in result.stderr.lower(), (
            f"Expected output directory error message in stderr, got: {result.stderr!r}"
        )

    def test_bad_output_dir_nothing_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap with bad --output-dir must not write anything to stdout (AC-CHANNEL-001)."""
        blocked_path = self._make_readonly_parent(tmp_path)
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(blocked_path))
        assert result.returncode == 1
        assert result.stdout == "", f"Expected empty stdout for bad output directory error, got: {result.stdout!r}"
