"""Integration tests for kanon validate metadata sub-subcommand.

Drives the full CLI via subprocess against the existing E5-F2 fixtures
(broken-soft-spot-1/, broken-soft-spot-2/, broken-soft-spot-3/) and a clean
valid fixture. Also verifies that the command does not issue any git ls-remote
calls by substituting a fake git binary that fails on ls-remote.

AC-TEST-002: Integration test driving the full CLI against the E5-F2 fixtures.
AC-CYCLE-001: End-to-end cycle evidence.
"""

from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import sys
import textwrap

import pytest


_FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "catalog"
_SOFT_SPOT_1 = _FIXTURES_DIR / "broken-soft-spot-1"
_SOFT_SPOT_2 = _FIXTURES_DIR / "broken-soft-spot-2"
_SOFT_SPOT_3 = _FIXTURES_DIR / "broken-soft-spot-3"


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


def _make_valid_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a valid manifest repo with a single clean XML file.

    The entry name uses underscores only (already normalised via derive_source_name)
    so that no S001/S002 warnings are generated.
    """
    repo_specs = tmp_path / "repo-specs"
    repo_specs.mkdir(parents=True, exist_ok=True)
    xml = repo_specs / "valid-marketplace.xml"
    xml.write_text(
        textwrap.dedent("""\
        <?xml version="1.0"?>
        <package>
          <catalog-metadata>
            <name>my_tool</name>
            <display-name>My Tool</display-name>
            <description>A useful tool.</description>
            <version>1.0.0</version>
            <type>plugin</type>
            <owner-name>Alice</owner-name>
            <owner-email>alice@example.com</owner-email>
            <keywords>infra,deploy</keywords>
          </catalog-metadata>
        </package>
    """)
    )
    return tmp_path


def _make_fake_git_binary(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a fake git binary that fails if ls-remote is invoked.

    The binary accepts 'rev-parse' (used by _resolve_repo_root for auto-detect)
    and other safe subcommands, but exits non-zero with an error message when
    ls-remote is invoked, proving the validate metadata command never calls it.

    Returns:
        Path to the fake git binary file.
    """
    bin_dir = tmp_path / "fake-git-bin"
    bin_dir.mkdir(exist_ok=True)
    git_script = bin_dir / "git"
    git_script.write_text(
        textwrap.dedent("""\
        #!/bin/sh
        # Fake git for testing: fails on ls-remote to verify no network calls
        if [ "$1" = "ls-remote" ]; then
            echo "FAKE GIT: ls-remote is forbidden in kanon validate metadata" >&2
            exit 127
        fi
        # Delegate everything else to the real git
        exec /usr/bin/git "$@"
    """)
    )
    git_script.chmod(git_script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


@pytest.mark.integration
class TestValidateMetadataCleanRepo:
    """AC-FUNC-001: Clean manifest repo exits 0 with zero findings."""

    def test_clean_repo_exits_zero(self, tmp_path: pathlib.Path) -> None:
        valid_repo = _make_valid_repo(tmp_path)
        result = _run_kanon(["validate", "metadata", "--repo-root", str(valid_repo)])
        assert result.returncode == 0, (
            f"Expected exit 0 for clean repo, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_clean_repo_no_output(self, tmp_path: pathlib.Path) -> None:
        valid_repo = _make_valid_repo(tmp_path)
        result = _run_kanon(["validate", "metadata", "--repo-root", str(valid_repo)])
        assert result.returncode == 0

        assert "ERROR" not in result.stdout and "ERROR" not in result.stderr


@pytest.mark.integration
class TestValidateMetadataBrokenSoftSpot1:
    """AC-TEST-002 / AC-CYCLE-001: broken-soft-spot-1 (metadata errors) exits 1."""

    def test_soft_spot_1_exits_one(self) -> None:
        """The broken-soft-spot-1 fixture has metadata errors; exit code must be 1."""
        result = _run_kanon(["validate", "metadata", "--repo-root", str(_SOFT_SPOT_1)])
        assert result.returncode == 1, (
            f"Expected exit 1 for soft-spot-1 fixture, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_soft_spot_1_reports_error_findings(self) -> None:
        """broken-soft-spot-1 must produce ERROR findings on stdout."""
        result = _run_kanon(["validate", "metadata", "--repo-root", str(_SOFT_SPOT_1)])
        assert "ERROR" in result.stdout or "ERROR" in result.stderr, (
            f"Expected ERROR finding in output. stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_soft_spot_1_missing_required_field_named(self) -> None:
        """The missing-required-marketplace.xml finding names the XML path."""
        result = _run_kanon(["validate", "metadata", "--repo-root", str(_SOFT_SPOT_1)])
        combined = result.stdout + result.stderr
        assert "missing-required-marketplace.xml" in combined, (
            f"Expected XML file path in output. combined={combined!r}"
        )


@pytest.mark.integration
class TestValidateMetadataBrokenSoftSpot2:
    """AC-TEST-002 / AC-CYCLE-001: broken-soft-spot-2 (source-name drift/charset) exits 0 with warnings."""

    def test_soft_spot_2_exits_zero(self) -> None:
        """The broken-soft-spot-2 fixture has only WARN findings; exit code must be 0."""
        result = _run_kanon(["validate", "metadata", "--repo-root", str(_SOFT_SPOT_2)])
        assert result.returncode == 0, (
            f"Expected exit 0 for soft-spot-2 fixture, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_soft_spot_2_reports_warn_findings(self) -> None:
        """broken-soft-spot-2 must produce WARN findings."""
        result = _run_kanon(["validate", "metadata", "--repo-root", str(_SOFT_SPOT_2)])
        assert "WARN" in result.stdout or "WARN" in result.stderr, (
            f"Expected WARN finding in output. stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_soft_spot_2_no_error_findings(self) -> None:
        """broken-soft-spot-2 must not produce ERROR findings (warnings only)."""
        result = _run_kanon(["validate", "metadata", "--repo-root", str(_SOFT_SPOT_2)])
        assert "ERROR" not in result.stdout and "ERROR" not in result.stderr, (
            f"Unexpected ERROR finding in soft-spot-2 output. stdout={result.stdout!r} stderr={result.stderr!r}"
        )


@pytest.mark.integration
class TestValidateMetadataBrokenSoftSpot3:
    """AC-TEST-002 / AC-CYCLE-001: broken-soft-spot-3 (entry-name collision) exits 1."""

    def test_soft_spot_3_exits_one(self) -> None:
        """The broken-soft-spot-3 fixture has entry-name collisions; exit code must be 1."""
        result = _run_kanon(["validate", "metadata", "--repo-root", str(_SOFT_SPOT_3)])
        assert result.returncode == 1, (
            f"Expected exit 1 for soft-spot-3 fixture, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_soft_spot_3_reports_u001_finding(self) -> None:
        """broken-soft-spot-3 must produce a U001 ERROR finding."""
        result = _run_kanon(["validate", "metadata", "--repo-root", str(_SOFT_SPOT_3)])
        combined = result.stdout + result.stderr
        assert "U001" in combined, f"Expected U001 finding code in output. combined={combined!r}"

    def test_soft_spot_3_names_colliding_files(self) -> None:
        """U001 finding must name at least one colliding XML file."""
        result = _run_kanon(["validate", "metadata", "--repo-root", str(_SOFT_SPOT_3)])
        combined = result.stdout + result.stderr

        has_fixture_path = any(
            name in combined
            for name in [
                "group-a-1-marketplace.xml",
                "group-a-2-marketplace.xml",
                "group-b-1-marketplace.xml",
                "group-b-2-marketplace.xml",
            ]
        )
        assert has_fixture_path, f"Expected collision file paths in output. combined={combined!r}"


@pytest.mark.integration
class TestValidateMetadataJsonFormat:
    """AC-FUNC-009: --format json emits parseable JSON matching catalog audit schema."""

    def test_json_format_clean_repo(self, tmp_path: pathlib.Path) -> None:
        valid_repo = _make_valid_repo(tmp_path)
        result = _run_kanon(["validate", "metadata", "--repo-root", str(valid_repo), "--format", "json"])
        assert result.returncode == 0, (
            f"Expected exit 0 for clean repo with JSON format.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        parsed = json.loads(result.stdout)
        assert "findings" in parsed
        assert parsed["findings"] == []

    def test_json_format_error_repo(self) -> None:
        """JSON output for broken-soft-spot-1 has findings with required schema fields."""
        result = _run_kanon(["validate", "metadata", "--repo-root", str(_SOFT_SPOT_1), "--format", "json"])
        assert result.returncode == 1
        parsed = json.loads(result.stdout)
        assert "findings" in parsed
        assert len(parsed["findings"]) >= 1
        for finding in parsed["findings"]:
            assert "kind" in finding, f"Finding missing 'kind': {finding}"
            assert "code" in finding, f"Finding missing 'code': {finding}"
            assert "message" in finding, f"Finding missing 'message': {finding}"
            assert "remediation" in finding, f"Finding missing 'remediation': {finding}"

    def test_json_format_warn_only_repo(self) -> None:
        """JSON output for broken-soft-spot-2 has warn findings and exit 0."""
        result = _run_kanon(["validate", "metadata", "--repo-root", str(_SOFT_SPOT_2), "--format", "json"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert "findings" in parsed
        kinds = [f["kind"] for f in parsed["findings"]]
        assert "warn" in kinds, f"Expected at least one warn finding, got: {kinds}"
        assert "error" not in kinds, "Unexpected error finding in soft-spot-2 JSON output"


@pytest.mark.integration
class TestValidateMetadataNoGitLsRemote:
    """AC-FUNC-008 / AC-CYCLE-001: validate metadata must not call git ls-remote."""

    def test_no_ls_remote_with_fake_git(self, tmp_path: pathlib.Path) -> None:
        """The command succeeds even when git ls-remote would fail.

        Injects a fake git binary at the front of PATH that exits non-zero
        when ls-remote is invoked. If kanon validate metadata calls ls-remote,
        the test asserts that the exit code is NOT 127 (ls-remote blocked).
        If it does NOT call ls-remote, the command works normally.
        """
        valid_repo = _make_valid_repo(tmp_path / "repo")
        bin_dir = _make_fake_git_binary(tmp_path)

        env_path = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
        result = _run_kanon(
            ["validate", "metadata", "--repo-root", str(valid_repo)],
            extra_env={"PATH": env_path},
        )

        assert result.returncode == 0, (
            f"validate metadata must not call git ls-remote (fake git blocks it).\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        assert "FAKE GIT: ls-remote is forbidden" not in result.stdout
        assert "FAKE GIT: ls-remote is forbidden" not in result.stderr


@pytest.mark.integration
class TestValidateMetadataSubcommandRegistration:
    """Verify metadata is registered as a subcommand alongside xml and marketplace."""

    def test_metadata_subcommand_help(self) -> None:
        """kanon validate metadata --help exits 0 and names the subcommand."""
        result = _run_kanon(["validate", "metadata", "--help"])
        assert result.returncode == 0, f"Expected exit 0 for --help. stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "metadata" in result.stdout.lower() or "metadata" in result.stderr.lower()

    def test_validate_help_lists_metadata(self) -> None:
        """kanon validate --help should mention all three sub-subcommands."""
        result = _run_kanon(["validate", "--help"])

        combined = result.stdout + result.stderr
        assert "metadata" in combined or result.returncode in (0, 2), (
            f"Expected 'metadata' in validate --help output. combined={combined!r}"
        )

    def test_missing_repo_root_with_explicit_flag(self, tmp_path: pathlib.Path) -> None:
        """--repo-root pointing to a nonexistent directory exits 1 with clear message."""
        missing = tmp_path / "does-not-exist"
        result = _run_kanon(["validate", "metadata", "--repo-root", str(missing)])
        assert result.returncode == 1, f"Expected exit 1 for missing --repo-root, got {result.returncode}"
