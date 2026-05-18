"""Integration tests for kanon catalog audit --check tag-format (soft-spot rule 5).

Drives the full CLI as a subprocess against a real fixture git repo
seeded with mixed PEP 440 and non-PEP-440 tags.

AC-TEST-002: Integration test running against a real fixture git server with mixed tags.
AC-CYCLE-001: End-to-end cycle:
  - Repo tagged with 1.0.0, v1.0.0, subpackage/2.0.0, release-2024.
  - Exit 0 (warnings only, no errors).
  - Exactly two WARN findings: for v1.0.0 and release-2024.
  - Zero findings for 1.0.0 (PEP 440) and subpackage/2.0.0 (monorepo PEP 440).
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest


# ---------------------------------------------------------------------------
# Git helper utilities
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with test user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _create_fixture_git_repo(base: pathlib.Path, tags: list[str]) -> pathlib.Path:
    """Create a local git repo with repo-specs/ and the given tags.

    Creates one marketplace XML file under repo-specs/ (so the audit target
    is a valid manifest repo), commits it, and then creates each tag listed
    in ``tags`` on that commit.

    Args:
        base: Parent directory under which the work dir is created.
        tags: Tag names to create on the initial commit.

    Returns:
        Absolute path to the created git repo directory.
    """
    repo_dir = base / "fixture-repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(repo_dir)

    repo_specs = repo_dir / "repo-specs"
    repo_specs.mkdir()

    # Write a minimal marketplace XML so the directory is a valid audit target.
    xml_content = """\
<?xml version="1.0"?>
<manifest>
  <catalog-metadata>
    <name>fixture-tool</name>
    <display-name>Fixture Tool</display-name>
    <description>Fixture tool for tag-format integration test.</description>
    <version>1.0.0</version>
    <type>plugin</type>
    <owner-name>Test Author</owner-name>
    <owner-email>author@example.com</owner-email>
    <keywords>test,fixture</keywords>
  </catalog-metadata>
</manifest>
"""
    (repo_specs / "fixture-marketplace.xml").write_text(xml_content, encoding="utf-8")

    _git(["add", "."], cwd=repo_dir)
    _git(["commit", "-m", "initial commit"], cwd=repo_dir)

    for tag in tags:
        _git(["tag", tag], cwd=repo_dir)

    return repo_dir


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


# ---------------------------------------------------------------------------
# Integration test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCatalogAuditTagFormatSubprocess:
    """End-to-end subprocess tests for --check tag-format against a real fixture git repo."""

    def test_exit_code_0_for_mixed_tag_repo(self, tmp_path: pathlib.Path) -> None:
        """kanon catalog audit --check tag-format exits 0 (warnings only, no errors).

        AC-CYCLE-001 and AC-FUNC-010.
        """
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "v1.0.0", "subpackage/2.0.0", "release-2024"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert result.returncode == 0, (
            f"Expected exit 0 (warnings only), got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_v1_0_0_warn_appears(self, tmp_path: pathlib.Path) -> None:
        """The WARN finding for v1.0.0 appears in output. AC-CYCLE-001."""
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "v1.0.0", "subpackage/2.0.0", "release-2024"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert "v1.0.0" in result.stdout, f"Expected 'v1.0.0' in stdout WARN finding.\nstdout: {result.stdout}"

    def test_release_2024_warn_appears(self, tmp_path: pathlib.Path) -> None:
        """The WARN finding for release-2024 appears in output. AC-CYCLE-001."""
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "v1.0.0", "subpackage/2.0.0", "release-2024"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert "release-2024" in result.stdout, (
            f"Expected 'release-2024' in stdout WARN finding.\nstdout: {result.stdout}"
        )

    def test_exactly_two_warn_findings_for_ac_cycle_001_fixture(self, tmp_path: pathlib.Path) -> None:
        """AC-CYCLE-001: exactly two WARN lines for the given fixture tags.

        Tags 1.0.0 and subpackage/2.0.0 are PEP 440 => zero findings.
        Tags v1.0.0 and release-2024 are non-PEP-440 canonical => two WARNs.
        """
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "v1.0.0", "subpackage/2.0.0", "release-2024"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        warn_lines = [line for line in result.stdout.splitlines() if line.startswith("WARN:")]
        assert len(warn_lines) == 2, (
            f"AC-CYCLE-001: expected exactly 2 WARN lines, got {len(warn_lines)}.\nstdout:\n{result.stdout}"
        )

    def test_no_error_prefix_in_output(self, tmp_path: pathlib.Path) -> None:
        """No ERROR: lines appear (tag-format check is warnings-only per spec 0.4)."""
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "v1.0.0", "subpackage/2.0.0", "release-2024"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert "ERROR:" not in result.stdout, f"Expected no ERROR: lines (only WARNs), got:\n{result.stdout}"

    def test_pep440_only_repo_produces_no_output(self, tmp_path: pathlib.Path) -> None:
        """A repo with only PEP 440 tags produces no findings and no stdout output."""
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "2.10.1", "2026.4.1"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert result.returncode == 0, (
            f"Expected exit 0 for PEP 440-only repo, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert result.stdout.strip() == "", f"Expected empty stdout for PEP 440-only repo, got:\n{result.stdout}"

    def test_no_tag_repo_produces_no_output(self, tmp_path: pathlib.Path) -> None:
        """A repo with no tags produces no findings."""
        repo = _create_fixture_git_repo(tmp_path, tags=[])
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert result.returncode == 0, (
            f"Expected exit 0 for no-tag repo, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert result.stdout.strip() == "", f"Expected empty stdout for no-tag repo, got:\n{result.stdout}"

    def test_1_0_0_tag_produces_no_warn(self, tmp_path: pathlib.Path) -> None:
        """PEP 440 tag 1.0.0 does not appear in WARN findings. AC-FUNC-001."""
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "v1.0.0", "subpackage/2.0.0", "release-2024"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        # 1.0.0 should NOT appear in a "WARN" line -- only WARN for non-PEP-440 tags.
        warn_lines = [line for line in result.stdout.splitlines() if line.startswith("WARN:")]
        for line in warn_lines:
            # Check that '1.0.0' is only referenced as part of 'v1.0.0' or
            # 'subpackage/2.0.0', not as the plain PEP 440 tag itself.
            assert "WARN:" not in line or "v1.0.0" in line or "release-2024" in line, (
                f"Unexpected WARN line content: {line!r}"
            )

    def test_subpackage_2_0_0_tag_produces_no_warn(self, tmp_path: pathlib.Path) -> None:
        """Monorepo-prefixed PEP 440 tag subpackage/2.0.0 produces no finding. AC-FUNC-004."""
        repo = _create_fixture_git_repo(tmp_path, tags=["subpackage/2.0.0"])
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert result.returncode == 0
        assert result.stdout.strip() == "", f"Expected empty stdout for monorepo PEP 440 tag, got:\n{result.stdout}"

    def test_warn_prefix_present_for_non_pep440_tag(self, tmp_path: pathlib.Path) -> None:
        """At least one WARN: line appears for a repo with non-PEP-440 tags."""
        repo = _create_fixture_git_repo(tmp_path, tags=["v1.0.0"])
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "tag-format"])
        assert "WARN:" in result.stdout, (
            f"Expected at least one WARN: line.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_check_not_run_when_different_check_selected(self, tmp_path: pathlib.Path) -> None:
        """Running --check metadata does not run tag-format logic (no T001 codes)."""
        repo = _create_fixture_git_repo(
            tmp_path,
            tags=["1.0.0", "v1.0.0"],
        )
        result = _run_kanon(["catalog", "audit", str(repo), "--check", "metadata"])
        assert "T001" not in result.stdout, (
            f"Expected no T001 code when --check metadata is used.\nstdout: {result.stdout}"
        )
