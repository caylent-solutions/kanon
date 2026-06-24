"""TC-bootstrap scenarios: removed-command verification.

``kanon bootstrap`` was removed entirely in the 3.0.0 major release. It is no
longer registered or intercepted, so argparse rejects every ``bootstrap``
invocation (any args/flags) as an unknown command:
- Exits 2 (the argparse usage-error code) for EVERY invocation.
- Prints an ``invalid choice: 'bootstrap'`` usage error to stderr.
- Performs no filesystem mutation.
- Does not resolve the catalog (no clone is attempted).

Scenarios:
- TC-bootstrap-01: --output-dir=<path> does not create the directory
- TC-bootstrap-02: --catalog-source flag never resolves the catalog
- TC-bootstrap-03: KANON_CATALOG_SOURCES env never resolves the catalog
- TC-bootstrap-04: flag and env combination both ignored
- TC-bootstrap-05: bootstrap into a nonexistent parent path exits 2 (not a fs error)
"""

from __future__ import annotations

import os
import pathlib

import pytest

from tests.scenarios.conftest import (
    run_kanon,
)

# argparse exit code for an unrecognised command (the removed-bootstrap contract).
_ARGPARSE_USAGE_EXIT = 2


def _assert_bootstrap_rejected(result) -> None:
    """Assert a bootstrap invocation was rejected as an unknown command (exit 2)."""
    assert result.returncode == _ARGPARSE_USAGE_EXIT, (
        f"removed 'bootstrap' must exit {_ARGPARSE_USAGE_EXIT} (argparse unknown command), "
        f"got {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "invalid choice: 'bootstrap'" in result.stderr, (
        f"stderr must name 'bootstrap' as an invalid choice: {result.stderr!r}"
    )


@pytest.mark.scenario
class TestTCBootstrap:
    # ------------------------------------------------------------------
    # TC-bootstrap-01: --output-dir=<path> (no filesystem mutation)
    # ------------------------------------------------------------------

    def test_tc_bootstrap_01_output_dir(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-01: kanon bootstrap kanon --output-dir exits 2 and creates no files."""
        output_dir = tmp_path / "tc-bs-01"

        result = run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))

        _assert_bootstrap_rejected(result)
        assert not output_dir.exists(), (
            f"Expected --output-dir '{output_dir}' to NOT be created (bootstrap is rejected before any work)"
        )

    # ------------------------------------------------------------------
    # TC-bootstrap-02: --catalog-source flag never resolves the catalog
    # ------------------------------------------------------------------

    def test_tc_bootstrap_02_catalog_source_flag(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-02: bootstrap list --catalog-source exits 2 (rejected, no clone)."""
        result = run_kanon(
            "bootstrap",
            "list",
            "--catalog-source",
            "https://example.com/sentinel.git@main",
        )

        _assert_bootstrap_rejected(result)
        assert "Cloning" not in result.stderr, f"Unexpected clone attempt in stderr: {result.stderr!r}"

    # ------------------------------------------------------------------
    # TC-bootstrap-03: KANON_CATALOG_SOURCES env never resolves the catalog
    # ------------------------------------------------------------------

    def test_tc_bootstrap_03_catalog_source_env(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-03: bootstrap list with KANON_CATALOG_SOURCES env exits 2 (rejected)."""
        env = dict(os.environ)
        env["KANON_CATALOG_SOURCES"] = "https://example.com/sentinel-env.git@main"

        result = run_kanon("bootstrap", "list", env=env)

        _assert_bootstrap_rejected(result)
        assert "Cloning" not in result.stderr, f"Unexpected clone attempt in stderr: {result.stderr!r}"

    # ------------------------------------------------------------------
    # TC-bootstrap-04: flag and env both ignored (rejected before reading either)
    # ------------------------------------------------------------------

    def test_tc_bootstrap_04_flag_overrides_env(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-04: --catalog-source flag and KANON_CATALOG_SOURCES env both ignored (rejected)."""
        env = dict(os.environ)
        env["KANON_CATALOG_SOURCES"] = "https://example.com/env-sentinel.git@1.0.0"

        result = run_kanon(
            "bootstrap",
            "list",
            "--catalog-source",
            "https://example.com/flag-sentinel.git@main",
            env=env,
        )

        _assert_bootstrap_rejected(result)
        assert result.stdout == "", f"Expected empty stdout (no package listing), got: {result.stdout!r}"

    # ------------------------------------------------------------------
    # TC-bootstrap-05: missing parent exits 2 (rejected, not a filesystem error)
    # ------------------------------------------------------------------

    def test_tc_bootstrap_05_nonexistent_parent_errors(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-05: bootstrap with --output-dir whose parent does not exist exits 2."""
        missing_parent = tmp_path / "no" / "such" / "parent" / "dir"

        result = run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))

        _assert_bootstrap_rejected(result)
        assert not missing_parent.exists(), "no output directory may be created when bootstrap is rejected"
