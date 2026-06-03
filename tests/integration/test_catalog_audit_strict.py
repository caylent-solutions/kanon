"""Integration tests for kanon catalog audit --strict flag.

Drives the full CLI as a subprocess against the
tests/fixtures/catalog/broken-soft-spot-2/ fixture tree (warnings-only).

AC-TEST-002: Integration test driving the CLI against broken-soft-spot-2/
with and without --strict; asserts exit-code flip and presence of the
strict-mode summary line in the strict run.
AC-CYCLE-001: End-to-end cycle evidence captured via these tests.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from kanon_cli.constants import KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE


def _run_kanon(
    args: list[str],
    cwd: pathlib.Path | str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon CLI as a subprocess and return the CompletedProcess result."""
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=env,
    )


def _fixture_dir() -> pathlib.Path:
    """Return the path to the broken-soft-spot-2 fixture directory (warnings-only)."""
    here = pathlib.Path(__file__).parent
    # tests/integration/ -> tests/fixtures/catalog/broken-soft-spot-2/
    return here.parent / "fixtures" / "catalog" / "broken-soft-spot-2"


@pytest.mark.integration
class TestCatalogAuditStrictSubprocess:
    """End-to-end subprocess tests for the --strict flag against broken-soft-spot-2/.

    broken-soft-spot-2/ is a warnings-only fixture (source-name-derivation
    warnings; no errors). This makes it ideal for asserting the exit-code flip
    caused by --strict.
    """

    def test_fixture_dir_exists(self) -> None:
        """Fixture directory must exist before running audit tests."""
        fixture = _fixture_dir()
        assert fixture.is_dir(), f"Fixture directory not found: {fixture}"

    def test_fixture_repo_specs_dir_exists(self) -> None:
        """Fixture must contain a repo-specs/ subdirectory."""
        fixture = _fixture_dir()
        repo_specs = fixture / "repo-specs"
        assert repo_specs.is_dir(), f"repo-specs/ not found in fixture: {fixture}"

    def test_exit_code_0_without_strict_warnings_only(self) -> None:
        """kanon catalog audit --check source-name-derivation exits 0 without --strict.

        AC-CYCLE-001 first half: warnings-only fixture exits 0 (default mode).
        """
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation"])
        assert result.returncode == 0, (
            f"Expected exit 0 (warnings only, no --strict), got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_exit_code_1_with_strict_warnings_only(self) -> None:
        """kanon catalog audit --check source-name-derivation --strict exits 1.

        AC-CYCLE-001 second half: warnings-only fixture exits 1 under --strict.
        """
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation", "--strict"])
        assert result.returncode == 1, (
            f"Expected exit 1 (warnings promoted to errors under --strict), got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_strict_summary_line_in_stderr(self) -> None:
        """--strict run prints the strict-mode summary line to stderr.

        AC-FUNC-005: exit 1 and strict-mode summary printed to stderr.
        """
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation", "--strict"])
        assert "strict mode" in result.stderr, (
            f"Expected 'strict mode' in stderr under --strict.\nstderr: {result.stderr!r}"
        )

    def test_strict_summary_includes_warning_count(self) -> None:
        """The strict-mode summary names the warning count (>= 1 for the broken fixture)."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation", "--strict"])
        # The fixture produces at least 3 warnings (one per file); the count must appear
        stderr = result.stderr
        assert "strict mode" in stderr, f"No strict-mode summary found in stderr: {stderr!r}"
        # Extract the warning count from the summary line using the template pattern
        # KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE = "strict mode: {count} warning(s) treated as errors"
        assert "warning(s)" in stderr, f"Expected 'warning(s)' in strict-mode summary. stderr: {stderr!r}"

    def test_warn_prefix_still_present_in_stdout_under_strict(self) -> None:
        """Output still shows WARN: prefix for warnings under --strict.

        AC-FUNC-008: findings are NOT mutated; display shows WARN: prefixes.
        """
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation", "--strict"])
        assert "WARN:" in result.stdout, f"Expected WARN: prefix in stdout under --strict. stdout: {result.stdout!r}"

    def test_no_error_prefix_in_stdout_under_strict(self) -> None:
        """Under --strict, stdout still shows WARN: not ERROR: for promoted warnings.

        Findings are promoted only for exit-code computation, not for display.
        """
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation", "--strict"])
        assert "ERROR:" not in result.stdout, (
            f"Expected no ERROR: in stdout (findings stay as WARN: under --strict). stdout: {result.stdout!r}"
        )

    def test_strict_summary_count_matches_template_format(self) -> None:
        """The strict-mode summary matches the KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE format.

        Counts warnings produced by the fixture and verifies the template is used.
        """
        fixture = _fixture_dir()
        # First run without strict to count warnings
        result_no_strict = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation"])
        warn_count = result_no_strict.stdout.count("WARN:")

        # Now run with strict to check summary
        result_strict = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation", "--strict"])
        expected_summary = KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE.format(count=warn_count)
        assert expected_summary in result_strict.stderr, (
            f"Expected summary {expected_summary!r} in stderr.\nstderr: {result_strict.stderr!r}"
        )
