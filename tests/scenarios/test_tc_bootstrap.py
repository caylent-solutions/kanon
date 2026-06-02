"""TC-bootstrap scenarios: deprecation shim verification.

These scenarios verify that 'kanon bootstrap' is now a uniform deprecation shim
that:
- Exits 3 (EXIT_CODE_DEPRECATED) for EVERY invocation (any args/flags, including
  --help).
- Prints the deprecation message to stderr.
- Performs no filesystem mutation.
- Does not resolve the catalog.

Scenarios:
- TC-bootstrap-01: --output-dir=<path> does not create the directory (shim)
- TC-bootstrap-02: --catalog-source flag is accepted but catalog never resolved (shim)
- TC-bootstrap-03: KANON_CATALOG_SOURCE env is accepted but catalog never resolved (shim)
- TC-bootstrap-04: flag and env combination both ignored (shim)
- TC-bootstrap-05: bootstrap into nonexistent parent path exits 3 (shim, not fs error)
"""

from __future__ import annotations

import os
import pathlib

import pytest

from tests.scenarios.conftest import (
    run_kanon,
)


@pytest.mark.scenario
class TestTCBootstrap:
    # ------------------------------------------------------------------
    # TC-bootstrap-01: --output-dir=<path> shim (no filesystem mutation)
    # ------------------------------------------------------------------

    def test_tc_bootstrap_01_output_dir(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-01: kanon bootstrap kanon --output-dir exits 3 and creates no files."""
        output_dir = tmp_path / "tc-bs-01"

        result = run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))

        assert result.returncode == 3, (
            f"Expected exit 3 (shim), got {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert not output_dir.exists(), (
            f"Expected --output-dir '{output_dir}' to NOT be created (shim must not delegate)"
        )
        assert "DEPRECATED" in result.stderr, f"Expected deprecation message on stderr, got: {result.stderr!r}"

    # ------------------------------------------------------------------
    # TC-bootstrap-02: --catalog-source flag accepted, never resolved (shim)
    # ------------------------------------------------------------------

    def test_tc_bootstrap_02_catalog_source_flag(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-02: bootstrap list --catalog-source exits 3 (shim, no clone)."""
        result = run_kanon(
            "bootstrap",
            "list",
            "--catalog-source",
            "https://example.com/sentinel.git@main",
        )

        assert result.returncode == 3, (
            f"Expected exit 3 (shim), got {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "Cloning" not in result.stderr, f"Unexpected clone attempt in stderr: {result.stderr!r}"
        assert "DEPRECATED" in result.stderr, f"Expected deprecation message on stderr, got: {result.stderr!r}"

    # ------------------------------------------------------------------
    # TC-bootstrap-03: KANON_CATALOG_SOURCE env accepted, never resolved (shim)
    # ------------------------------------------------------------------

    def test_tc_bootstrap_03_catalog_source_env(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-03: bootstrap list with KANON_CATALOG_SOURCE env exits 3 (shim)."""
        env = dict(os.environ)
        env["KANON_CATALOG_SOURCE"] = "https://example.com/sentinel-env.git@main"

        result = run_kanon("bootstrap", "list", env=env)

        assert result.returncode == 3, (
            f"Expected exit 3 (shim), got {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "Cloning" not in result.stderr, f"Unexpected clone attempt in stderr: {result.stderr!r}"

    # ------------------------------------------------------------------
    # TC-bootstrap-04: flag and env both ignored (shim)
    # ------------------------------------------------------------------

    def test_tc_bootstrap_04_flag_overrides_env(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-04: --catalog-source flag and KANON_CATALOG_SOURCE env both ignored (shim)."""
        env = dict(os.environ)
        env["KANON_CATALOG_SOURCE"] = "https://example.com/env-sentinel.git@1.0.0"

        result = run_kanon(
            "bootstrap",
            "list",
            "--catalog-source",
            "https://example.com/flag-sentinel.git@main",
            env=env,
        )

        assert result.returncode == 3, (
            f"Expected exit 3 (shim), got {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stdout == "", f"Expected empty stdout (shim must not list packages), got: {result.stdout!r}"

    # ------------------------------------------------------------------
    # TC-bootstrap-05: missing parent exits 3 (shim, not a filesystem error)
    # ------------------------------------------------------------------

    def test_tc_bootstrap_05_nonexistent_parent_errors(self, tmp_path: pathlib.Path) -> None:
        """TC-bootstrap-05: bootstrap with --output-dir whose parent does not exist exits 3."""
        missing_parent = tmp_path / "no" / "such" / "parent" / "dir"

        result = run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))

        assert result.returncode == 3, (
            f"Expected exit 3 (shim), got {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stderr.strip(), "Expected a non-empty deprecation message in stderr"
        assert "DEPRECATED" in result.stderr, f"Expected 'DEPRECATED' in stderr, got: {result.stderr!r}"
