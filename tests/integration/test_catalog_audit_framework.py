"""Integration tests for kanon catalog audit framework.

Drives the full CLI via subprocess against a tmp_path manifest-repo skeleton.

AC-TEST-003: Integration test driving the full CLI against a tmp_path empty
manifest-repo; asserts exit 0; asserts argparse usage error for invalid --check.

AC-CYCLE-001: Build a tmp_path empty manifest-repo with repo-specs/ but zero
XML files; run kanon catalog audit . --format json; assert exit 0 and
parseable JSON with findings == [].
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


@pytest.fixture()
def empty_manifest_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal manifest-repo skeleton with repo-specs/ but no XML files.

    Initializes a bare git repository so that kanon catalog audit's tag-format
    check can run git ls-remote --tags against the directory without error.
    """
    repo_specs = tmp_path / "repo-specs"
    repo_specs.mkdir()
    subprocess.run(
        ["git", "init", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return tmp_path


@pytest.mark.integration
class TestCatalogAuditSubprocessEmpty:
    """End-to-end subprocess tests against an empty manifest repo."""

    def test_exit_0_empty_repo(self, empty_manifest_repo: pathlib.Path) -> None:
        """kanon catalog audit . against an empty repo exits 0."""
        result = _run_kanon(["catalog", "audit", str(empty_manifest_repo)])
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_exit_0_explicit_all_check(self, empty_manifest_repo: pathlib.Path) -> None:
        """kanon catalog audit . --check all exits 0."""
        result = _run_kanon(["catalog", "audit", str(empty_manifest_repo), "--check", "all"])
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_exit_0_json_format_empty_findings(self, empty_manifest_repo: pathlib.Path) -> None:
        """AC-CYCLE-001: kanon catalog audit . --format json exits 0 with parseable JSON."""
        result = _run_kanon(["catalog", "audit", str(empty_manifest_repo), "--format", "json"])
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        parsed = json.loads(result.stdout)
        assert "findings" in parsed
        assert parsed["findings"] == []

    def test_json_output_is_parseable(self, empty_manifest_repo: pathlib.Path) -> None:
        """JSON output is a valid JSON object parseable by json.loads."""
        result = _run_kanon(["catalog", "audit", str(empty_manifest_repo), "--format", "json"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, dict)
        assert "findings" in parsed


@pytest.mark.integration
class TestCatalogAuditArgparseErrors:
    """Argparse usage errors yield exit code 2."""

    def test_invalid_check_value_exits_2(self, empty_manifest_repo: pathlib.Path) -> None:
        """--check with an invalid value exits with argparse usage error (exit 2)."""
        result = _run_kanon(["catalog", "audit", str(empty_manifest_repo), "--check", "nonsense"])
        assert result.returncode == 2, (
            f"Expected exit 2 (argparse error), got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_all_mixed_with_other_exits_2(self, empty_manifest_repo: pathlib.Path) -> None:
        """--check all,metadata exits with argparse usage error (exit 2)."""
        result = _run_kanon(["catalog", "audit", str(empty_manifest_repo), "--check", "all,metadata"])
        assert result.returncode == 2, (
            f"Expected exit 2, got {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_empty_check_value_exits_2(self, empty_manifest_repo: pathlib.Path) -> None:
        """--check '' exits with argparse usage error (exit 2)."""
        result = _run_kanon(["catalog", "audit", str(empty_manifest_repo), "--check", ""])
        assert result.returncode == 2, (
            f"Expected exit 2, got {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


@pytest.mark.integration
class TestCatalogAuditHelp:
    """kanon catalog audit --help surface."""

    def test_help_exits_0(self) -> None:
        """kanon catalog audit --help exits 0."""
        result = _run_kanon(["catalog", "audit", "--help"])
        assert result.returncode == 0

    def test_help_lists_metadata_check(self) -> None:
        """kanon catalog audit --help mentions 'metadata' in output."""
        result = _run_kanon(["catalog", "audit", "--help"])
        assert "metadata" in result.stdout

    def test_help_lists_tag_format_check(self) -> None:
        """kanon catalog audit --help mentions 'tag-format' in output."""
        result = _run_kanon(["catalog", "audit", "--help"])
        assert "tag-format" in result.stdout

    def test_help_lists_all_five_checks(self) -> None:
        """AC-FUNC-001: --help lists all five valid check names plus 'all'."""
        result = _run_kanon(["catalog", "audit", "--help"])
        for check_name in (
            "metadata",
            "source-name-derivation",
            "entry-name-uniqueness",
            "remote-url",
            "tag-format",
            "all",
        ):
            assert check_name in result.stdout, f"Expected '{check_name}' in help output.\nstdout: {result.stdout}"


@pytest.mark.integration
class TestCatalogAuditDefaultPositional:
    """kanon catalog audit with no positional defaults to cwd."""

    def test_no_positional_defaults_to_cwd(self, empty_manifest_repo: pathlib.Path) -> None:
        """AC-FUNC-005: invoking without a positional arg defaults to '.' (cwd)."""
        result = _run_kanon(["catalog", "audit"], cwd=empty_manifest_repo)
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
