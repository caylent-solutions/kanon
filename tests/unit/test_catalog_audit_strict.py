"""Unit tests for kanon catalog audit --strict flag.

Tests that the --strict flag promotes WARN findings to errors for the purpose
of exit-code computation, while leaving finding objects unmodified and printing
a one-line summary to stderr when warnings exist under strict mode.

AC-TEST-001: Parametrized unit tests covering every combination of findings
(none, error-only, warn-only, both) with and without --strict.
"""

from __future__ import annotations

import argparse
import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.commands.catalog import (
    AUDIT_CHECK_REGISTRY,
    AuditFinding,
    audit_command,
)
from kanon_cli.constants import KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE


def _make_strict_args(
    target: str,
    strict: bool,
    check: str = "metadata",
    fmt: str = "text",
) -> argparse.Namespace:
    """Build a minimal Namespace for strict-mode audit_command unit tests."""
    from kanon_cli.commands.catalog import _parse_check_subset

    return argparse.Namespace(
        target=target,
        check=check,
        check_subset=_parse_check_subset(check),
        format=fmt,
        no_color=False,
        strict=strict,
        quiet=False,
        verbose=False,
    )


def _make_findings(
    error_count: int,
    warn_count: int,
) -> list[AuditFinding]:
    """Build a list of AuditFinding objects with the specified error and warn counts."""
    findings: list[AuditFinding] = []
    for i in range(error_count):
        findings.append(AuditFinding(kind="error", code=f"E{i:03d}", message=f"error finding {i}", remediation=""))
    for i in range(warn_count):
        findings.append(AuditFinding(kind="warn", code=f"W{i:03d}", message=f"warn finding {i}", remediation=""))
    return findings


@pytest.mark.unit
class TestStrictFlagExitCodes:
    """audit_command returns correct exit codes with and without --strict.

    AC-FUNC-001: no --strict, zero findings => exit 0.
    AC-FUNC-002: no --strict, ERROR findings => exit 1.
    AC-FUNC-003: no --strict, WARN findings only => exit 0.
    AC-FUNC-004: --strict, zero findings => exit 0.
    AC-FUNC-005: --strict, WARN findings only => exit 1.
    AC-FUNC-006: --strict, both ERROR and WARN => exit 1.
    """

    @pytest.mark.parametrize(
        "error_count, warn_count, strict, expected_exit",
        [
            (0, 0, False, 0),
            (1, 0, False, 1),
            (2, 0, False, 1),
            (0, 1, False, 0),
            (0, 3, False, 0),
            (0, 0, True, 0),
            (0, 1, True, 1),
            (0, 3, True, 1),
            (1, 1, True, 1),
            (2, 3, True, 1),
            (1, 0, True, 1),
        ],
    )
    def test_exit_code_parametrized(
        self,
        tmp_path: pathlib.Path,
        error_count: int,
        warn_count: int,
        strict: bool,
        expected_exit: int,
    ) -> None:
        """Exit code matches expectation for all finding combinations."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        test_findings = _make_findings(error_count, warn_count)

        def findings_check(path: pathlib.Path) -> list[AuditFinding]:
            return test_findings

        args = _make_strict_args(target=str(tmp_path), strict=strict)
        with patch.dict(AUDIT_CHECK_REGISTRY, {"metadata": findings_check}, clear=True):
            result = audit_command(args)

        assert result == expected_exit, (
            f"Expected exit {expected_exit} for error_count={error_count}, "
            f"warn_count={warn_count}, strict={strict}; got {result}"
        )


@pytest.mark.unit
class TestStrictSummaryOutput:
    """audit_command prints the strict-mode summary to stderr when warnings exist under --strict.

    AC-FUNC-005: strict + warnings only => exit 1 + summary printed to stderr.
    AC-FUNC-006: strict + errors and warnings => exit 1 + summary printed to stderr.
    AC-FUNC-007: summary text comes from KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE.
    """

    def test_strict_warn_only_prints_summary_to_stderr(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--strict with warn findings only prints the strict-mode summary to stderr."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        def findings_check(path: pathlib.Path) -> list[AuditFinding]:
            return _make_findings(0, 2)

        args = _make_strict_args(target=str(tmp_path), strict=True)
        with patch.dict(AUDIT_CHECK_REGISTRY, {"metadata": findings_check}, clear=True):
            audit_command(args)

        captured = capsys.readouterr()
        assert "strict mode" in captured.err, f"Expected 'strict mode' in stderr. Got: {captured.err!r}"
        assert "2" in captured.err, f"Expected warning count '2' in strict summary. Got: {captured.err!r}"

    def test_strict_error_and_warn_prints_summary_to_stderr(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--strict with both error and warn findings prints the strict-mode summary to stderr."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        def findings_check(path: pathlib.Path) -> list[AuditFinding]:
            return _make_findings(1, 3)

        args = _make_strict_args(target=str(tmp_path), strict=True)
        with patch.dict(AUDIT_CHECK_REGISTRY, {"metadata": findings_check}, clear=True):
            audit_command(args)

        captured = capsys.readouterr()
        assert "strict mode" in captured.err, f"Expected 'strict mode' in stderr. Got: {captured.err!r}"
        assert "3" in captured.err, f"Expected warning count '3' in strict summary. Got: {captured.err!r}"

    def test_strict_zero_findings_no_summary(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """--strict with zero findings does NOT print the strict-mode summary."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        args = _make_strict_args(target=str(tmp_path), strict=True)
        with patch.dict(AUDIT_CHECK_REGISTRY, {}, clear=True):
            audit_command(args)

        captured = capsys.readouterr()
        assert "strict mode" not in captured.err, f"Expected no strict-mode summary in stderr. Got: {captured.err!r}"

    def test_no_strict_warn_only_no_summary(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Without --strict, no strict-mode summary is printed even with warnings."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        def findings_check(path: pathlib.Path) -> list[AuditFinding]:
            return _make_findings(0, 2)

        args = _make_strict_args(target=str(tmp_path), strict=False)
        with patch.dict(AUDIT_CHECK_REGISTRY, {"metadata": findings_check}, clear=True):
            audit_command(args)

        captured = capsys.readouterr()
        assert "strict mode" not in captured.err, (
            f"Expected no strict-mode summary in stderr without --strict. Got: {captured.err!r}"
        )

    def test_strict_error_only_no_summary(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """--strict with errors only (no warnings) does NOT print the strict-mode summary."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        def findings_check(path: pathlib.Path) -> list[AuditFinding]:
            return _make_findings(1, 0)

        args = _make_strict_args(target=str(tmp_path), strict=True)
        with patch.dict(AUDIT_CHECK_REGISTRY, {"metadata": findings_check}, clear=True):
            audit_command(args)

        captured = capsys.readouterr()
        assert "strict mode" not in captured.err, (
            f"Expected no strict-mode summary in stderr (errors only, no warnings). Got: {captured.err!r}"
        )

    def test_strict_summary_uses_constant_template(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The strict-mode summary message is derived from KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE.

        AC-FUNC-007: no inline string in catalog.py.
        """
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        def findings_check(path: pathlib.Path) -> list[AuditFinding]:
            return _make_findings(0, 4)

        args = _make_strict_args(target=str(tmp_path), strict=True)
        with patch.dict(AUDIT_CHECK_REGISTRY, {"metadata": findings_check}, clear=True):
            audit_command(args)

        captured = capsys.readouterr()
        expected_message = KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE.format(count=4)
        assert expected_message in captured.err, (
            f"Expected exact template message {expected_message!r} in stderr. Got: {captured.err!r}"
        )

    def test_strict_summary_count_reflects_warn_count_only(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The summary count reflects only warnings, not errors."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        def findings_check(path: pathlib.Path) -> list[AuditFinding]:
            return _make_findings(2, 5)

        args = _make_strict_args(target=str(tmp_path), strict=True)
        with patch.dict(AUDIT_CHECK_REGISTRY, {"metadata": findings_check}, clear=True):
            audit_command(args)

        captured = capsys.readouterr()
        expected_message = KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE.format(count=5)
        assert expected_message in captured.err, (
            f"Expected template with count=5 (warnings only). Got: {captured.err!r}"
        )


@pytest.mark.unit
class TestStrictFindingsMutationGuard:
    """Findings are NOT mutated by --strict; WARN: prefix preserved in output.

    AC-FUNC-008: The display still shows WARN: prefixes for warnings.
    """

    def test_warn_findings_still_show_warn_prefix_under_strict(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Under --strict, WARN findings retain their WARN: prefix in stdout output."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        def findings_check(path: pathlib.Path) -> list[AuditFinding]:
            return [AuditFinding(kind="warn", code="W001", message="a warning", remediation="")]

        args = _make_strict_args(target=str(tmp_path), strict=True)
        with patch.dict(AUDIT_CHECK_REGISTRY, {"metadata": findings_check}, clear=True):
            audit_command(args)

        captured = capsys.readouterr()
        assert "WARN:" in captured.out, f"Expected WARN: prefix in stdout output under --strict. Got: {captured.out!r}"
        assert "ERROR:" not in captured.out, (
            f"Expected no ERROR: prefix in stdout for warn finding under --strict. Got: {captured.out!r}"
        )

    def test_finding_objects_not_mutated_by_strict(self, tmp_path: pathlib.Path) -> None:
        """AuditFinding objects retain their original kind after audit_command runs."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        original_findings = [
            AuditFinding(kind="warn", code="W001", message="a warning", remediation=""),
            AuditFinding(kind="error", code="E001", message="an error", remediation=""),
        ]

        def findings_check(path: pathlib.Path) -> list[AuditFinding]:
            return list(original_findings)

        args = _make_strict_args(target=str(tmp_path), strict=True)
        with patch.dict(AUDIT_CHECK_REGISTRY, {"metadata": findings_check}, clear=True):
            audit_command(args)

        assert original_findings[0].kind == "warn", "First finding (warn) should not be mutated by --strict."
        assert original_findings[1].kind == "error", "Second finding (error) should not be mutated by --strict."
