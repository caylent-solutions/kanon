"""Integration tests for kanon catalog audit legacy catalog/ directory detection.

Drives the full CLI as a subprocess against:
  1. A tmp_path git repo mirroring the legacy-catalog-dir fixture structure,
     using --check all (including tag-format which requires a git repo).
  2. The static tests/fixtures/catalog/legacy-catalog-dir/ fixture directly
     using --check metadata to avoid the tag-format git requirement.

AC-TEST-002: Integration test driving the CLI against the legacy-catalog-dir/ fixture.
AC-CYCLE-001: End-to-end cycle: build the legacy-catalog-dir/ fixture with a
  catalog/sample-entry/ subtree; run kanon catalog audit <fixture> with default
  --check all; assert exit 0 (warning only); assert stdout contains the canonical
  legacy-directory WARN.

Spec source: spec Section 4.8.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from kanon_cli import __version__
from kanon_cli.constants import KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE

# Absolute path to the static legacy-catalog-dir fixture.
_FIXTURE_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "catalog" / "legacy-catalog-dir"

_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"

# Minimal marketplace XML for a valid manifest repo fixture.
_FIXTURE_XML = """\
<?xml version="1.0"?>
<manifest>
  <catalog-metadata>
    <name>sample-entry</name>
    <display-name>Sample Entry</display-name>
    <description>A sample catalog entry used by the legacy-catalog-dir audit fixture.</description>
    <version>1.0.0</version>
    <type>plugin</type>
    <owner-name>Test Author</owner-name>
    <owner-email>author@example.com</owner-email>
    <keywords>test,fixture</keywords>
  </catalog-metadata>
</manifest>
"""


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


def _create_legacy_catalog_git_repo(base: pathlib.Path) -> pathlib.Path:
    """Create a local git repo with repo-specs/ and a legacy catalog/ subtree.

    Initialises the repo, adds a marketplace XML under repo-specs/,
    and creates a catalog/sample-entry/.kanon file that triggers the WARN.

    Args:
        base: Parent directory under which the repo dir is created.

    Returns:
        Absolute path to the created git repo directory.
    """
    repo_dir = base / "legacy-catalog-repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    _git(["init", "-b", "main"], cwd=repo_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=repo_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=repo_dir)

    # Create repo-specs/ with a valid marketplace XML.
    repo_specs = repo_dir / "repo-specs"
    repo_specs.mkdir()
    (repo_specs / "sample-marketplace.xml").write_text(_FIXTURE_XML, encoding="utf-8")

    # Create the legacy catalog/sample-entry/.kanon tree.
    legacy_entry = repo_dir / "catalog" / "sample-entry"
    legacy_entry.mkdir(parents=True)
    (legacy_entry / ".kanon").write_text(
        "GITBASE=https://example.com/org\n",
        encoding="utf-8",
    )

    _git(["add", "."], cwd=repo_dir)
    _git(["commit", "-m", "initial commit"], cwd=repo_dir)

    return repo_dir


def _run_kanon(
    args: list[str],
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
        env=env,
    )


@pytest.mark.integration
class TestCatalogAuditLegacyDirGitRepo:
    """End-to-end subprocess tests using a real tmp git repo (supports --check all)."""

    def test_exit_code_0_with_check_all(self, tmp_path: pathlib.Path) -> None:
        """kanon catalog audit exits 0 when only legacy-dir WARN is present. AC-FUNC-007."""
        repo = _create_legacy_catalog_git_repo(tmp_path)
        result = _run_kanon(
            ["catalog", "audit", str(repo), "--check", "all"],
        )
        assert result.returncode == 0, (
            f"Expected exit 0 (WARN only, no ERROR), got {result.returncode}.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_legacy_dir_warn_present_in_stdout(self, tmp_path: pathlib.Path) -> None:
        """The canonical legacy-directory WARN message appears in stdout. AC-CYCLE-001."""
        repo = _create_legacy_catalog_git_repo(tmp_path)
        result = _run_kanon(
            ["catalog", "audit", str(repo), "--check", "all"],
        )
        expected_msg = KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE.format(version=__version__)
        assert expected_msg in result.stdout, (
            f"Expected legacy-dir WARN message in stdout.\n"
            f"Expected substring: {expected_msg!r}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_warn_prefix_present(self, tmp_path: pathlib.Path) -> None:
        """The output contains a WARN: line mentioning 'catalog/'. AC-CYCLE-001."""
        repo = _create_legacy_catalog_git_repo(tmp_path)
        result = _run_kanon(
            ["catalog", "audit", str(repo), "--check", "all"],
        )
        warn_lines = [line for line in result.stdout.splitlines() if line.startswith("WARN:")]
        legacy_warns = [line for line in warn_lines if "catalog/" in line]
        assert len(legacy_warns) >= 1, (
            f"Expected at least one WARN: line mentioning 'catalog/'.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_version_string_in_warn_message(self, tmp_path: pathlib.Path) -> None:
        """The running kanon CLI version appears in the WARN message. AC-FUNC-004."""
        repo = _create_legacy_catalog_git_repo(tmp_path)
        result = _run_kanon(
            ["catalog", "audit", str(repo), "--check", "all"],
        )
        assert __version__ in result.stdout, (
            f"Expected kanon version {__version__!r} in stdout WARN message.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_migration_doc_reference_in_warn_message(self, tmp_path: pathlib.Path) -> None:
        """The WARN message references docs/migration-to-add.md. AC-FUNC-004."""
        repo = _create_legacy_catalog_git_repo(tmp_path)
        result = _run_kanon(
            ["catalog", "audit", str(repo), "--check", "all"],
        )
        assert "docs/migration-to-add.md" in result.stdout, (
            f"Expected docs/migration-to-add.md reference in stdout.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_no_error_level_findings_from_fixture(self, tmp_path: pathlib.Path) -> None:
        """The legacy-catalog-dir fixture produces no ERROR-level findings. AC-FUNC-007."""
        repo = _create_legacy_catalog_git_repo(tmp_path)
        result = _run_kanon(
            ["catalog", "audit", str(repo), "--check", "all"],
        )
        error_lines = [line for line in result.stdout.splitlines() if line.startswith("ERROR:")]
        assert error_lines == [], (
            "Expected no ERROR: lines from the legacy-catalog-dir fixture.\n"
            "ERROR lines found:\n" + "\n".join(error_lines) + f"\nstderr:\n{result.stderr}"
        )


@pytest.mark.integration
class TestCatalogAuditLegacyDirStaticFixture:
    """Tests using the static tests/fixtures/catalog/legacy-catalog-dir/ fixture."""

    def test_fixture_dir_exists(self) -> None:
        """The static legacy-catalog-dir fixture directory is present on disk."""
        assert _FIXTURE_DIR.is_dir(), (
            f"Fixture directory missing: {_FIXTURE_DIR}. "
            "Create tests/fixtures/catalog/legacy-catalog-dir/ with a valid layout."
        )

    def test_fixture_has_legacy_catalog_subdir(self) -> None:
        """The static fixture has a catalog/ directory with at least one subdirectory."""
        catalog_dir = _FIXTURE_DIR / "catalog"
        assert catalog_dir.is_dir(), f"Expected catalog/ inside {_FIXTURE_DIR}, but it is missing."
        children = [p for p in catalog_dir.iterdir() if p.is_dir()]
        assert len(children) >= 1, f"Expected at least one subdirectory under {catalog_dir}, found none."

    def test_legacy_dir_warn_present_with_check_metadata(self) -> None:
        """Legacy-dir WARN appears even when --check metadata is used. AC-FUNC-005."""
        result = _run_kanon(
            ["catalog", "audit", str(_FIXTURE_DIR), "--check", "metadata"],
        )
        expected_msg = KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE.format(version=__version__)
        assert expected_msg in result.stdout, (
            f"Expected legacy-dir WARN with --check metadata.\n"
            f"Expected: {expected_msg!r}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_check_runs_unconditionally_with_specific_check(self) -> None:
        """Legacy-dir check runs even when --check entry-name-uniqueness is passed. AC-FUNC-005."""
        result = _run_kanon(
            ["catalog", "audit", str(_FIXTURE_DIR), "--check", "entry-name-uniqueness"],
        )
        expected_msg = KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE.format(version=__version__)
        assert expected_msg in result.stdout, (
            f"Expected legacy-dir WARN even when --check entry-name-uniqueness is used.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_legacy_dir_not_a_valid_check_name(self) -> None:
        """'legacy-catalog-dir' is not a valid --check name (rejected by argparse). AC-FUNC-005."""
        result = _run_kanon(
            ["catalog", "audit", str(_FIXTURE_DIR), "--check", "legacy-catalog-dir"],
        )
        assert result.returncode == 2, (
            f"Expected exit 2 for unknown --check value 'legacy-catalog-dir', "
            f"got {result.returncode}.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_exit_code_0_with_check_metadata(self) -> None:
        """kanon catalog audit exits 0 when only legacy-dir WARN is present. AC-FUNC-007."""
        result = _run_kanon(
            ["catalog", "audit", str(_FIXTURE_DIR), "--check", "metadata"],
        )
        assert result.returncode == 0, (
            f"Expected exit 0 (WARN only, no ERROR) with --check metadata, "
            f"got {result.returncode}.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
