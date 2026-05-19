"""Functional tests for kanon bootstrap --catalog-source deprecation shim behavior.

The 'kanon bootstrap' command is now a deprecation shim. Passing --catalog-source
or KANON_CATALOG_SOURCE does not cause catalog resolution; the shim exits 3
without performing any work.

Covers:
- AC-FUNC-003: Neither invocation reads KANON_CATALOG_SOURCE or calls catalog resolve
- AC-FUNC-005: No filesystem mutation even with --catalog-source supplied
- AC-CHANNEL-001: stdout vs stderr channel discipline verified
"""

import pytest

from tests.functional.conftest import _run_kanon


@pytest.mark.functional
class TestCatalogSourceEnvVar:
    """Verify KANON_CATALOG_SOURCE is never read by the shim (shim exits before catalog resolve)."""

    def test_env_var_catalog_not_resolved_shim_exits_3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The shim exits 3 even when KANON_CATALOG_SOURCE is set to a sentinel URL."""
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://example.com/x.git@main")
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3, (
            f"Expected exit 3 (shim), not a catalog-clone error. Got {result.returncode}.\nstderr: {result.stderr!r}"
        )

    def test_env_var_no_catalog_resolution_in_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No git clone or catalog resolution must appear in stderr."""
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://example.com/x.git@main")
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3
        assert "Cloning" not in result.stderr, f"Unexpected clone attempt in stderr: {result.stderr!r}"
        assert "fatal:" not in result.stderr, f"Unexpected git fatal in stderr: {result.stderr!r}"

    def test_env_var_catalog_no_stderr_leakage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No catalog-resolve errors must appear in stderr (shim never reaches catalog code)."""
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://example.com/x.git@main")
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3
        assert "WARN:" in result.stderr, f"Expected WARN on stderr, got: {result.stderr!r}"
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"


@pytest.mark.functional
class TestCatalogSourceFlagOverridesEnvVar:
    """Verify --catalog-source flag is ignored by the shim (shim exits before catalog resolve)."""

    def test_flag_catalog_source_shim_exits_3(self) -> None:
        """The shim exits 3 even with a sentinel --catalog-source flag."""
        result = _run_kanon(
            "bootstrap",
            "list",
            "--catalog-source",
            "https://example.com/x.git@main",
        )
        assert result.returncode == 3, f"Expected exit 3 (shim). Got {result.returncode}.\nstderr: {result.stderr!r}"

    def test_flag_overrides_env_var_shim_still_exits_3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The shim exits 3 regardless of --catalog-source and KANON_CATALOG_SOURCE combination."""
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://example.com/env.git@main")
        result = _run_kanon(
            "bootstrap",
            "list",
            "--catalog-source",
            "https://example.com/flag.git@main",
        )
        assert result.returncode == 3, f"Expected exit 3 (shim). Got {result.returncode}.\nstderr: {result.stderr!r}"

    def test_flag_overrides_env_var_no_stderr_leakage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No catalog-resolve errors must appear even with both --catalog-source and env set."""
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://example.com/env.git@main")
        result = _run_kanon(
            "bootstrap",
            "list",
            "--catalog-source",
            "https://example.com/flag.git@main",
        )
        assert result.returncode == 3
        assert "WARN:" in result.stderr, f"Expected WARN on stderr, got: {result.stderr!r}"
        assert "Cloning" not in result.stderr, f"Unexpected clone attempt in stderr: {result.stderr!r}"


@pytest.mark.functional
class TestCatalogSourceDefaultBundled:
    """Verify the shim exits 3 even when no catalog source is provided (no bundled catalog used)."""

    def test_bundled_catalog_not_used_shim_exits_3(self) -> None:
        """kanon bootstrap list without any catalog source must exit 3 (shim, no bundled catalog)."""
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3, f"Expected exit 3, got {result.returncode}.\nstderr: {result.stderr!r}"

    def test_no_catalog_package_listing_on_stdout(self) -> None:
        """The shim must not list any packages (no delegation to bundled catalog)."""
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3
        assert "kanon" not in result.stdout, f"Expected no package listing on stdout, got: {result.stdout!r}"

    def test_bundled_catalog_produces_no_stdout(self) -> None:
        """kanon bootstrap list must not produce any stdout output."""
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"
