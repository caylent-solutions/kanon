"""Functional tests for kanon bootstrap list and default-target deprecation shim.

The 'kanon bootstrap list' and 'kanon bootstrap <name>' subcommands are deprecated.
Any non-help invocation prints a WARN to stderr and exits with code 3.

Covers:
- AC-FUNC-002: kanon bootstrap list exits 3 with verbatim WARN text
- AC-FUNC-001: kanon bootstrap <name> exits 3 with verbatim WARN text
- AC-CHANNEL-001: stdout vs stderr channel discipline verified
"""

import pytest

from tests.functional.conftest import _run_kanon


@pytest.mark.functional
class TestBootstrapListShim:
    """Verify 'kanon bootstrap list' emits the deprecation WARN and exits 3."""

    def test_bootstrap_list_exits_3(self) -> None:
        """kanon bootstrap list must exit 3 (deprecated invocation)."""
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3, f"Expected exit code 3, got {result.returncode}.\nstderr: {result.stderr!r}"

    def test_bootstrap_list_warn_on_stderr(self) -> None:
        """kanon bootstrap list must write the verbatim WARN text to stderr."""
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3
        assert "WARN: 'kanon bootstrap list' is deprecated. Run instead:" in result.stderr, (
            f"Expected verbatim WARN text in stderr, got: {result.stderr!r}"
        )

    def test_bootstrap_list_replacement_command_on_stderr(self) -> None:
        """The WARN must include the 'kanon list' replacement command."""
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3
        assert "kanon list" in result.stderr, f"Expected 'kanon list' in stderr, got: {result.stderr!r}"

    def test_bootstrap_list_see_docs_on_stderr(self) -> None:
        """The WARN must include the migration docs reference."""
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3
        assert "See docs/migration-bootstrap-to-add.md." in result.stderr, (
            f"Expected 'See docs/migration-bootstrap-to-add.md.' in stderr, got: {result.stderr!r}"
        )

    def test_bootstrap_list_nothing_on_stdout(self) -> None:
        """kanon bootstrap list must not write anything to stdout (AC-CHANNEL-001)."""
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"


@pytest.mark.functional
class TestBootstrapDefaultTarget:
    """Verify 'kanon bootstrap <name>' emits the deprecation WARN and exits 3."""

    def test_bootstrap_kanon_exits_3(self) -> None:
        """kanon bootstrap kanon must exit 3 (deprecated invocation)."""
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3, f"Expected exit code 3, got {result.returncode}.\nstderr: {result.stderr!r}"

    def test_bootstrap_kanon_warn_on_stderr(self) -> None:
        """kanon bootstrap kanon must write the verbatim WARN text to stderr."""
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        assert "WARN: 'kanon bootstrap kanon' is deprecated. Run instead:" in result.stderr, (
            f"Expected verbatim WARN text in stderr, got: {result.stderr!r}"
        )

    def test_bootstrap_kanon_add_replacement_on_stderr(self) -> None:
        """The WARN must include the 'kanon add kanon' replacement command."""
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        assert "kanon add kanon" in result.stderr, f"Expected 'kanon add kanon' in stderr, got: {result.stderr!r}"

    def test_bootstrap_kanon_see_docs_on_stderr(self) -> None:
        """The WARN must include the migration docs reference."""
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        assert "See docs/migration-bootstrap-to-add.md." in result.stderr, (
            f"Expected 'See docs/migration-bootstrap-to-add.md.' in stderr, got: {result.stderr!r}"
        )

    def test_bootstrap_kanon_nothing_on_stdout(self) -> None:
        """kanon bootstrap kanon must not write anything to stdout (AC-CHANNEL-001)."""
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"

    def test_bootstrap_kanon_normal_output_goes_to_stderr_not_stdout(self) -> None:
        """The deprecation WARN must go to stderr, not stdout (AC-CHANNEL-001)."""
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        assert "WARN:" in result.stderr, f"Expected WARN on stderr, got: {result.stderr!r}"
        assert "WARN:" not in result.stdout, f"WARN must not appear on stdout, got: {result.stdout!r}"

    def test_bootstrap_kanon_error_output_goes_to_stderr_not_stdout(self) -> None:
        """No error content must appear on stdout (channel discipline)."""
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        assert result.stdout == "", f"stdout must be empty, got: {result.stdout!r}"
