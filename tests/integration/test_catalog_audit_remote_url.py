"""Integration tests for kanon catalog audit --check remote-url (soft-spot rule 4).

Drives the full CLI as a subprocess against the
tests/fixtures/catalog/broken-soft-spot-4/ fixture tree.

AC-TEST-002: Integration test driving the CLI against broken-soft-spot-4/.
AC-CYCLE-001: End-to-end cycle:
  - Without KANON_ALLOW_INSECURE_REMOTES: exit code 1, three ERROR findings.
  - With KANON_ALLOW_INSECURE_REMOTES=1: exit code 1 but only two ERRORs remain
    (the file:// finding opts out; unresolvable and query-string still fail).
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap

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
    """Return the path to the broken-soft-spot-4 fixture directory."""
    here = pathlib.Path(__file__).parent
    return here.parent / "fixtures" / "catalog" / "broken-soft-spot-4"


@pytest.mark.integration
class TestCatalogAuditRemoteUrlSubprocess:
    """End-to-end subprocess tests for --check remote-url against broken-soft-spot-4/."""

    def test_fixture_dir_exists(self) -> None:
        """Fixture directory must exist before running audit tests."""
        fixture = _fixture_dir()
        assert fixture.is_dir(), f"Fixture directory not found: {fixture}"

    def test_exit_code_1_on_broken_fixture_without_env(self) -> None:
        """kanon catalog audit --check remote-url against broken fixture exits 1 (no env var)."""
        fixture = _fixture_dir()
        result = _run_kanon(
            ["catalog", "audit", str(fixture), "--check", "remote-url"],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": ""},
        )
        assert result.returncode == 1, (
            f"Expected exit 1 without env var, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_three_errors_without_env(self) -> None:
        """Without KANON_ALLOW_INSECURE_REMOTES, all three fixture files produce ERROR findings."""
        fixture = _fixture_dir()
        result = _run_kanon(
            ["catalog", "audit", str(fixture), "--check", "remote-url"],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": ""},
        )
        error_lines = [line for line in result.stdout.splitlines() if line.startswith("ERROR:")]
        assert len(error_lines) >= 3, (
            f"Expected at least 3 ERROR lines without env var, got {len(error_lines)}.\nstdout:\n{result.stdout}"
        )

    def test_unresolvable_remote_finding_present_without_env(self) -> None:
        """R001 (unresolvable remote) finding appears in the output without env var."""
        fixture = _fixture_dir()
        result = _run_kanon(
            ["catalog", "audit", str(fixture), "--check", "remote-url"],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": ""},
        )
        assert "R001" in result.stdout, f"Expected R001 finding in output, got stdout:\n{result.stdout}"

    def test_file_url_finding_present_without_env(self) -> None:
        """R002 (file:// URL) finding appears in the output without env var."""
        fixture = _fixture_dir()
        result = _run_kanon(
            ["catalog", "audit", str(fixture), "--check", "remote-url"],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": ""},
        )
        assert "R002" in result.stdout, f"Expected R002 finding in output, got stdout:\n{result.stdout}"

    def test_query_string_finding_present_without_env(self) -> None:
        """R003 (query string URL) finding appears in the output without env var."""
        fixture = _fixture_dir()
        result = _run_kanon(
            ["catalog", "audit", str(fixture), "--check", "remote-url"],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": ""},
        )
        assert "R003" in result.stdout, f"Expected R003 finding in output, got stdout:\n{result.stdout}"

    def test_exit_code_1_with_env_var_set(self) -> None:
        """With KANON_ALLOW_INSECURE_REMOTES=1, exit code is still 1 (remaining errors)."""
        fixture = _fixture_dir()
        result = _run_kanon(
            ["catalog", "audit", str(fixture), "--check", "remote-url"],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert result.returncode == 1, (
            f"Expected exit 1 even with env var=1 (unresolvable+query-string remain), "
            f"got {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_file_url_finding_absent_with_env_var_set(self) -> None:
        """With KANON_ALLOW_INSECURE_REMOTES=1, the R002 (file://) finding is absent."""
        fixture = _fixture_dir()
        result = _run_kanon(
            ["catalog", "audit", str(fixture), "--check", "remote-url"],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "R002" not in result.stdout, (
            f"Expected R002 finding to be absent with env var=1, got stdout:\n{result.stdout}"
        )

    def test_r001_and_r003_still_present_with_env_var_set(self) -> None:
        """With KANON_ALLOW_INSECURE_REMOTES=1, R001 and R003 findings still appear."""
        fixture = _fixture_dir()
        result = _run_kanon(
            ["catalog", "audit", str(fixture), "--check", "remote-url"],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "R001" in result.stdout, f"Expected R001 finding with env var=1, got stdout:\n{result.stdout}"
        assert "R003" in result.stdout, f"Expected R003 finding with env var=1, got stdout:\n{result.stdout}"

    def test_fewer_errors_with_env_var_than_without(self) -> None:
        """With KANON_ALLOW_INSECURE_REMOTES=1, fewer ERROR lines than without."""
        fixture = _fixture_dir()
        result_no_env = _run_kanon(
            ["catalog", "audit", str(fixture), "--check", "remote-url"],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": ""},
        )
        result_with_env = _run_kanon(
            ["catalog", "audit", str(fixture), "--check", "remote-url"],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        errors_no_env = [line for line in result_no_env.stdout.splitlines() if line.startswith("ERROR:")]
        errors_with_env = [line for line in result_with_env.stdout.splitlines() if line.startswith("ERROR:")]
        assert len(errors_with_env) < len(errors_no_env), (
            f"Expected fewer errors with env var=1.\n"
            f"Without: {len(errors_no_env)} errors\nWith: {len(errors_with_env)} errors"
        )


@pytest.mark.integration
class TestCatalogAuditPlaceholderFetchUrl:
    """AC-TEST-002: audit-level assertions for ${VAR} placeholder fetch URLs.

    A synthetic manifest containing a <remote fetch="${GITBASE}"> must NOT produce
    an R002 finding when GITBASE is unset. The audit exit code on account of that
    remote alone must be 0 (no non-placeholder errors in the synthetic fixture).
    """

    def _build_placeholder_fixture(self, base: pathlib.Path) -> pathlib.Path:
        """Create a minimal repo-specs tree under base with a ${GITBASE} remote."""
        repo_specs = base / "repo-specs"
        repo_specs.mkdir(parents=True)
        manifest_xml = repo_specs / "placeholder-marketplace.xml"
        manifest_xml.write_text(
            textwrap.dedent("""\
                <?xml version="1.0"?>
                <manifest>
                  <remote name="gitbase" fetch="${GITBASE}" />
                  <project name="proj" remote="gitbase" path="src/proj" />
                </manifest>
            """),
            encoding="utf-8",
        )
        return base

    def test_no_r002_for_unset_gitbase_placeholder(self) -> None:
        """Audit against a ${GITBASE} manifest with GITBASE unset must produce no R002 finding.

        AC-FUNC-005 / AC-TEST-002: the audit command must not emit R002 for
        a fetch URL that is a ${VAR} placeholder when the variable is unset.
        """
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._build_placeholder_fixture(pathlib.Path(tmp))

            env_override: dict[str, str] = {"KANON_ALLOW_INSECURE_REMOTES": ""}

            base_env = {k: v for k, v in os.environ.items() if k != "GITBASE"}
            base_env.update(env_override)
            result = subprocess.run(
                [sys.executable, "-m", "kanon_cli", "catalog", "audit", str(fixture), "--check", "remote-url"],
                capture_output=True,
                text=True,
                env=base_env,
            )

            r002_error_lines = [line for line in result.stdout.splitlines() if "[R002]" in line]
            assert not r002_error_lines, (
                "Expected no [R002] ERROR lines for unset ${GITBASE} placeholder, "
                "but got:\n"
                + "\n".join(r002_error_lines)
                + f"\nFull stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
            assert result.returncode == 0, (
                "Expected exit 0 for synthetic ${GITBASE} placeholder manifest (no errors), "
                f"got {result.returncode}.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
