"""Functional tests for kanon bootstrap deprecation shim error paths.

Covers:
- AC-TEST-001: Missing positional package argument exits 2 with argparse error
- AC-FUNC-001: The shim exits 3 for any non-help invocation
- AC-CHANNEL-001: stdout vs stderr channel discipline verified (no cross-channel leakage)

Note: 'unknown package' and 'bad --output-dir' errors are now unreachable because
the shim exits 3 before performing any work. The tests that verified those error
paths have been removed as the underlying behavior no longer exists.
"""

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
class TestBootstrapShimAnyPackageExits3:
    """AC-FUNC-001: any non-help, non-empty invocation exits 3 with a WARN to stderr.

    The shim replaces all delegating behavior. Exit code 3 signals deprecated
    invocation. No filesystem mutation or catalog resolution occurs.
    """

    @pytest.mark.parametrize("package_name", ["kanon", "does-not-exist", "no-such-pkg"])
    def test_any_package_name_exits_3(self, package_name: str) -> None:
        """kanon bootstrap <package> must exit 3 regardless of whether the package exists."""
        result = _run_kanon("bootstrap", package_name)
        assert result.returncode == 3, (
            f"Expected exit code 3 for 'kanon bootstrap {package_name}', "
            f"got {result.returncode}.\nstderr: {result.stderr!r}"
        )

    def test_any_package_name_warn_on_stderr(self) -> None:
        """kanon bootstrap <package> must write a WARN to stderr."""
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        assert "WARN:" in result.stderr, f"Expected 'WARN:' in stderr, got: {result.stderr!r}"

    def test_any_package_name_nothing_on_stdout(self) -> None:
        """kanon bootstrap <package> must not write anything to stdout (AC-CHANNEL-001)."""
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"

    def test_list_subcommand_exits_3(self) -> None:
        """kanon bootstrap list must exit 3 (shim path)."""
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3, (
            f"Expected exit code 3 for 'kanon bootstrap list', got {result.returncode}.\nstderr: {result.stderr!r}"
        )

    def test_warn_contains_see_docs_link(self) -> None:
        """The WARN message must include the migration docs link."""
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        assert "docs/migration-bootstrap-to-add.md" in result.stderr, (
            f"Expected migration docs link in stderr, got: {result.stderr!r}"
        )

    def test_warn_no_traceback(self) -> None:
        """The shim must not emit a Python traceback."""
        result = _run_kanon("bootstrap", "kanon")
        assert "Traceback" not in result.stderr, f"Unexpected traceback in stderr: {result.stderr!r}"
