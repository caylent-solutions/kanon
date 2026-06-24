"""Integration tests for kanon catalog audit --check metadata.

Drives the full CLI as a subprocess against the
tests/fixtures/catalog/broken-soft-spot-1/ fixture tree.

AC-TEST-002: Integration test driving the CLI against broken-soft-spot-1/.
AC-CYCLE-001: End-to-end cycle: exit code 1 with every expected finding present.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest


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
    """Return the path to the broken-soft-spot-1 fixture directory."""
    here = pathlib.Path(__file__).parent

    return here.parent / "fixtures" / "catalog" / "broken-soft-spot-1"


@pytest.mark.integration
class TestCatalogAuditMetadataSubprocess:
    """End-to-end subprocess tests for --check metadata against broken-soft-spot-1/."""

    def test_fixture_dir_exists(self) -> None:
        """Fixture directory must exist before running audit tests."""
        fixture = _fixture_dir()
        assert fixture.is_dir(), f"Fixture directory not found: {fixture}"

    def test_exit_code_1_on_broken_fixture(self) -> None:
        """kanon catalog audit --check metadata against broken fixture exits 1."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "metadata"])
        assert result.returncode == 1, (
            f"Expected exit 1, got {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_missing_required_field_error_in_output(self) -> None:
        """The missing-required fixture produces an ERROR finding for 'name'."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "metadata"])
        combined = result.stdout + result.stderr
        assert "name" in combined, (
            f"Expected 'name' in output for missing-required fixture.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "ERROR" in combined, f"Expected ERROR in output.\nstdout: {result.stdout}\nstderr: {result.stderr}"

    def test_duplicate_child_error_in_output(self) -> None:
        """The duplicate-child fixture produces an ERROR finding naming 'name'."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "metadata"])
        combined = result.stdout + result.stderr

        assert "ERROR" in combined

    def test_multiple_blocks_error_in_output(self) -> None:
        """The multiple-blocks fixture produces an ERROR finding."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "metadata"])
        combined = result.stdout + result.stderr
        assert "ERROR" in combined

    def test_missing_recommended_field_warn_in_output(self) -> None:
        """The missing-recommended fixture produces a WARN finding."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "metadata"])
        combined = result.stdout + result.stderr
        assert "WARN" in combined, (
            f"Expected WARN in output for missing-recommended fixture.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_json_format_exit_1_on_broken_fixture(self) -> None:
        """JSON output mode also exits 1 on error findings."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "metadata", "--format", "json"])
        assert result.returncode == 1, (
            f"Expected exit 1 in JSON mode, got {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_json_format_findings_non_empty(self) -> None:
        """JSON output contains at least one finding for the broken fixture."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "metadata", "--format", "json"])
        parsed = json.loads(result.stdout)
        assert "findings" in parsed
        assert len(parsed["findings"]) > 0, "Expected at least one finding in JSON output."

    def test_json_findings_have_expected_fields(self) -> None:
        """Each JSON finding has kind, code, message, and remediation fields."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "metadata", "--format", "json"])
        parsed = json.loads(result.stdout)
        for finding in parsed["findings"]:
            assert "kind" in finding
            assert "code" in finding
            assert "message" in finding
            assert "remediation" in finding

    def test_error_findings_present_in_json(self) -> None:
        """At least one finding in JSON output has kind='error'."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "metadata", "--format", "json"])
        parsed = json.loads(result.stdout)
        error_findings = [f for f in parsed["findings"] if f["kind"] == "error"]
        assert error_findings, "Expected at least one error-kind finding in JSON output."

    def test_warn_findings_present_in_json(self) -> None:
        """At least one finding in JSON output has kind='warn'."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "metadata", "--format", "json"])
        parsed = json.loads(result.stdout)
        warn_findings = [f for f in parsed["findings"] if f["kind"] == "warn"]
        assert warn_findings, "Expected at least one warn-kind finding in JSON output."

    def test_exit_0_on_valid_fixture(self, tmp_path: pathlib.Path) -> None:
        """A fully valid manifest repo exits 0 with no findings."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        (repo_specs / "good-marketplace.xml").write_text(
            '<?xml version="1.0"?>\n'
            "<package>\n"
            "  <catalog-metadata>\n"
            "    <name>good-tool</name>\n"
            "    <display-name>Good Tool</display-name>\n"
            "    <description>A good tool.</description>\n"
            "    <version>1.0.0</version>\n"
            "    <type>plugin</type>\n"
            "    <owner-name>Alice</owner-name>\n"
            "    <owner-email>alice@example.com</owner-email>\n"
            "    <keywords>infra</keywords>\n"
            "  </catalog-metadata>\n"
            "</package>\n",
            encoding="utf-8",
        )
        result = _run_kanon(["catalog", "audit", str(tmp_path), "--check", "metadata"])
        assert result.returncode == 0, (
            f"Expected exit 0 for valid fixture, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
