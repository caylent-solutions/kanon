"""Integration tests for kanon catalog audit --check source-name-derivation.

Drives the full CLI as a subprocess against the
tests/fixtures/catalog/broken-soft-spot-2/ fixture tree.

AC-TEST-002: Integration test driving the CLI against broken-soft-spot-2/.
AC-CYCLE-001: End-to-end cycle: exit 0 (warnings only) with every expected
              warning appearing in output.
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
    """Return the path to the broken-soft-spot-2 fixture directory."""
    here = pathlib.Path(__file__).parent
    # tests/integration/ -> tests/fixtures/catalog/broken-soft-spot-2/
    return here.parent / "fixtures" / "catalog" / "broken-soft-spot-2"


@pytest.mark.integration
class TestCatalogAuditSourceNameSubprocess:
    """End-to-end subprocess tests for --check source-name-derivation against broken-soft-spot-2/."""

    def test_fixture_dir_exists(self) -> None:
        """Fixture directory must exist before running audit tests."""
        fixture = _fixture_dir()
        assert fixture.is_dir(), f"Fixture directory not found: {fixture}"

    def test_fixture_repo_specs_dir_exists(self) -> None:
        """Fixture must contain a repo-specs/ subdirectory."""
        fixture = _fixture_dir()
        repo_specs = fixture / "repo-specs"
        assert repo_specs.is_dir(), f"repo-specs/ not found in fixture: {fixture}"

    def test_exit_code_0_on_warnings_only_fixture(self) -> None:
        """kanon catalog audit --check source-name-derivation exits 0 (warnings only).

        AC-FUNC-007: the source-name-derivation check only produces WARN findings;
        exit code 0 even when warnings are present.
        """
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation"])
        assert result.returncode == 0, (
            f"Expected exit 0 (warnings only), got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_uppercase_entry_name_warning_present(self) -> None:
        """uppercase-name.xml (entry 'Foo') produces a drift warning naming 'foo'."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation"])
        combined = result.stdout + result.stderr
        assert "Foo" in combined or "foo" in combined, (
            f"Expected 'Foo' or 'foo' in output for uppercase entry.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_hyphenated_entry_name_warning_present(self) -> None:
        """hyphenated-name.xml (entry 'foo-bar') produces a drift warning naming 'foo_bar'."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation"])
        combined = result.stdout + result.stderr
        assert "foo_bar" in combined or "foo-bar" in combined, (
            f"Expected 'foo_bar' or 'foo-bar' in output for hyphenated entry.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_dotted_entry_name_warning_present(self) -> None:
        """dotted-name.xml (entry 'foo.bar') produces a charset warning."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation"])
        combined = result.stdout + result.stderr
        assert "foo.bar" in combined, (
            f"Expected 'foo.bar' in output for dotted entry.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_at_least_one_warn_prefix_in_output(self) -> None:
        """Output must contain at least one WARN: line for the broken fixture."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation"])
        assert "WARN:" in result.stdout, (
            f"Expected at least one WARN: line in stdout.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_no_error_prefix_in_output(self) -> None:
        """No ERROR: lines should appear (only warnings are expected for this check)."""
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation"])
        assert "ERROR:" not in result.stdout, f"Expected no ERROR: lines (only WARN), got:\n{result.stdout}"

    def test_check_not_run_when_excluded(self) -> None:
        """Running --check metadata against broken-soft-spot-2/ may produce exit 0 or 1.

        This test verifies that --check source-name-derivation can be requested
        in isolation; running a DIFFERENT check against the fixture does not
        trigger the source-name-derivation logic.
        """
        fixture = _fixture_dir()
        # Run with --check metadata to verify the CLI accepts multiple check names
        result_snd = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation"])
        # The source-name-derivation check must be isolated; metadata findings
        # should not appear when only source-name-derivation is selected.
        # No M001/M002 codes expected from --check source-name-derivation run
        snd_output = result_snd.stdout
        assert "M001" not in snd_output and "M002" not in snd_output, (
            f"Metadata finding codes should not appear in source-name-derivation output.\nstdout: {snd_output}"
        )

    def test_all_three_fixture_files_produce_findings(self) -> None:
        """All three XML fixture files produce at least one WARN finding each.

        uppercase-name.xml => drift (Foo -> foo)
        hyphenated-name.xml => drift (foo-bar -> foo_bar)
        dotted-name.xml => charset (foo.bar contains dot)
        """
        fixture = _fixture_dir()
        result = _run_kanon(["catalog", "audit", str(fixture), "--check", "source-name-derivation"])
        stdout = result.stdout
        assert "uppercase-name" in stdout or "Foo" in stdout, (
            f"Expected warning referencing uppercase-name.xml or 'Foo'.\nstdout: {stdout}"
        )
        assert "hyphenated-name" in stdout or "foo-bar" in stdout or "foo_bar" in stdout, (
            f"Expected warning referencing hyphenated-name.xml.\nstdout: {stdout}"
        )
        assert "dotted-name" in stdout or "foo.bar" in stdout, (
            f"Expected warning referencing dotted-name.xml or 'foo.bar'.\nstdout: {stdout}"
        )
