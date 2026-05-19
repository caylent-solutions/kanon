"""Integration tests for bootstrap --help snapshot (spec Section 4.9 + Section 14).

Runs `python -m kanon_cli bootstrap --help` via subprocess and verifies:
- Exit code is 0.
- stdout matches tests/fixtures/help/bootstrap-help.txt byte-for-byte.
- stderr is empty.

This satisfies AC-TEST-002 and AC-CYCLE-001.
"""

import pathlib
import subprocess
import sys

import pytest

_FIXTURE_PATH = pathlib.Path(__file__).parent.parent / "fixtures" / "help" / "bootstrap-help.txt"


@pytest.mark.integration
class TestBootstrapHelpSnapshot:
    """Integration snapshot tests for `kanon bootstrap --help`."""

    def test_exit_code_is_zero(self) -> None:
        """kanon bootstrap --help must exit 0 (help is informational, AC-FUNC-001)."""
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "bootstrap", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Expected exit code 0 for --help, got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_stderr_is_empty(self) -> None:
        """kanon bootstrap --help must produce no output on stderr (AC-TEST-002)."""
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "bootstrap", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.stderr == "", f"Expected empty stderr for --help, got: {result.stderr!r}"

    def test_stdout_matches_fixture_byte_for_byte(self) -> None:
        """stdout must exactly match bootstrap-help.txt fixture (AC-TEST-002, AC-FUNC-007)."""
        fixture_text = _FIXTURE_PATH.read_text(encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "bootstrap", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.stdout == fixture_text, (
            f"Help output does not match fixture.\n"
            f"--- fixture ({_FIXTURE_PATH}) ---\n{fixture_text!r}\n"
            f"--- actual stdout ---\n{result.stdout!r}"
        )

    def test_deprecated_notice_is_first_non_empty_line(self) -> None:
        """DEPRECATED notice must be the first non-empty line of stdout (AC-FUNC-002)."""
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "bootstrap", "--help"],
            capture_output=True,
            text=True,
        )
        non_empty_lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert len(non_empty_lines) > 0, "Help stdout must not be empty"
        expected_first = (
            "DEPRECATED: 'kanon bootstrap' is replaced by 'kanon add' and 'kanon list'. "
            "See docs/migration-bootstrap-to-add.md."
        )
        assert non_empty_lines[0] == expected_first, (
            f"Expected first non-empty line to be the DEPRECATED notice, got: {non_empty_lines[0]!r}"
        )

    def test_flag_translation_table_in_stdout(self) -> None:
        """stdout must include the pipe-delimited flag translation table (AC-FUNC-003)."""
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "bootstrap", "--help"],
            capture_output=True,
            text=True,
        )
        assert "|" in result.stdout, "Flag translation table (pipe-delimited) must appear in --help stdout"
        assert "--catalog-source" in result.stdout
        assert "--output-dir" in result.stdout

    def test_exit_codes_section_in_stdout(self) -> None:
        """stdout must include an Exit codes section listing 0 and 3 (AC-FUNC-004)."""
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "bootstrap", "--help"],
            capture_output=True,
            text=True,
        )
        assert "Exit codes" in result.stdout, "Exit codes section must appear in --help stdout"
        assert "0" in result.stdout
        assert "3" in result.stdout
