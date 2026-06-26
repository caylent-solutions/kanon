"""Integration tests for kanon catalog audit --check entry-name-uniqueness.

Drives the full CLI as a subprocess against the
tests/fixtures/catalog/broken-soft-spot-3/ fixture tree.

AC-TEST-002: Integration test driving the CLI against broken-soft-spot-3/.
AC-CYCLE-001: End-to-end cycle: exit code 1 with exactly two ERROR findings,
              each listing the right pair of colliding paths.
"""

from __future__ import annotations

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
    """Return the path to the broken-soft-spot-3 fixture directory."""
    here = pathlib.Path(__file__).parent

    return here.parent / "fixtures" / "catalog" / "broken-soft-spot-3"


@pytest.mark.integration
class TestCatalogAuditEntryUniquenessSubprocess:
    """End-to-end subprocess tests for --check entry-name-uniqueness against broken-soft-spot-3/."""

    def test_fixture_dir_exists(self) -> None:
        """Fixture directory must exist before running audit tests."""
        fixture = _fixture_dir()
        assert fixture.is_dir(), f"Fixture directory not found: {fixture}"

    def test_fixture_repo_specs_dir_exists(self) -> None:
        """Fixture must contain a repo-specs/ subdirectory."""
        fixture = _fixture_dir()
        repo_specs = fixture / "repo-specs"
        assert repo_specs.is_dir(), f"repo-specs/ not found in fixture: {fixture}"

    def test_exit_code_1_on_collision_fixture(self) -> None:
        """kanon catalog audit --check entry-name-uniqueness exits 1 when collisions exist.

        AC-FUNC-008: exits non-zero when any collision exists.
        """
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "entry-name-uniqueness"])
        assert result.returncode == 1, (
            f"Expected exit 1 (collision errors), got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_exactly_two_error_findings_in_output(self) -> None:
        """The fixture contains two collision groups -- exactly two ERROR: lines expected.

        AC-CYCLE-001: two collision groups => two ERROR findings.
        """
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "entry-name-uniqueness"])
        error_lines = [line for line in result.stdout.splitlines() if line.startswith("ERROR:")]
        assert len(error_lines) == 2, (
            f"Expected exactly 2 ERROR: lines, got {len(error_lines)}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_group_a_collision_present_in_output(self) -> None:
        """The group-A collision (group-a-1.xml and group-a-2.xml) appears in output.

        AC-CYCLE-001: each ERROR finding names the right pair of paths.
        """
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "entry-name-uniqueness"])
        stdout = result.stdout
        assert "group-a-1" in stdout, f"Expected 'group-a-1' in output for group-A collision.\nstdout: {stdout}"
        assert "group-a-2" in stdout, f"Expected 'group-a-2' in output for group-A collision.\nstdout: {stdout}"

    def test_group_b_collision_present_in_output(self) -> None:
        """The group-B collision (group-b-1.xml and group-b-2.xml) appears in output.

        AC-CYCLE-001: each ERROR finding names the right pair of paths.
        """
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "entry-name-uniqueness"])
        stdout = result.stdout
        assert "group-b-1" in stdout, f"Expected 'group-b-1' in output for group-B collision.\nstdout: {stdout}"
        assert "group-b-2" in stdout, f"Expected 'group-b-2' in output for group-B collision.\nstdout: {stdout}"

    def test_error_prefix_present_in_output(self) -> None:
        """Output must contain ERROR: prefix lines (collisions are error-level)."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "entry-name-uniqueness"])
        assert "ERROR:" in result.stdout, (
            f"Expected ERROR: lines in stdout.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_group_a_colliding_name_in_output(self) -> None:
        """The colliding name for group A appears in the output."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "entry-name-uniqueness"])

        assert "collision-name-alpha" in result.stdout, (
            f"Expected 'collision-name-alpha' in output.\nstdout: {result.stdout}"
        )

    def test_group_b_colliding_name_in_output(self) -> None:
        """The colliding name for group B appears in the output."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "entry-name-uniqueness"])

        assert "collision-name-beta" in result.stdout, (
            f"Expected 'collision-name-beta' in output.\nstdout: {result.stdout}"
        )

    def test_no_warn_prefix_in_output(self) -> None:
        """No WARN: lines expected -- uniqueness collisions are always ERROR-level."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "entry-name-uniqueness"])
        assert "WARN:" not in result.stdout, f"Expected no WARN: lines in uniqueness output.\nstdout: {result.stdout}"

    def test_check_entry_name_uniqueness_is_isolated_from_metadata_check(self) -> None:
        """Running --check entry-name-uniqueness does not emit metadata finding codes."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "entry-name-uniqueness"])

        assert "M001" not in result.stdout, (
            f"Metadata finding codes must not appear in uniqueness-only output.\nstdout: {result.stdout}"
        )
