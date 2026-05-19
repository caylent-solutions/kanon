"""Integration tests for the bootstrap deprecation shim.

Invokes `python -m kanon_cli bootstrap ...` via subprocess and verifies:
- stderr contains the verbatim WARN text.
- stdout is empty.
- Exit code is 3.
- No filesystem mutation occurs under --output-dir (shim never delegates).
"""

import pathlib
import subprocess
import sys

import pytest


def _run_bootstrap(*args: str, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    """Invoke `python -m kanon_cli bootstrap <args>` as a subprocess.

    Args:
        *args: Additional arguments to pass after `bootstrap`.
        cwd: Working directory for the subprocess. Defaults to None (inherit).

    Returns:
        CompletedProcess with returncode, stdout, and stderr as strings.
    """
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", "bootstrap", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


@pytest.mark.integration
class TestBootstrapShimKanonPackage:
    """Verify `kanon bootstrap kanon` emits the deprecation WARN and exits 3."""

    def test_exit_code_is_3(self, tmp_path: pathlib.Path) -> None:
        result = _run_bootstrap("kanon", "--output-dir", str(tmp_path / "scratch"))
        assert result.returncode == 3, f"Expected exit code 3, got {result.returncode}.\nstderr: {result.stderr!r}"

    def test_stderr_contains_warn_prefix(self, tmp_path: pathlib.Path) -> None:
        result = _run_bootstrap("kanon", "--output-dir", str(tmp_path / "scratch"))
        assert "WARN: 'kanon bootstrap kanon' is deprecated. Run instead:" in result.stderr, (
            f"Expected verbatim WARN text in stderr, got: {result.stderr!r}"
        )

    def test_stderr_contains_add_kanon(self, tmp_path: pathlib.Path) -> None:
        result = _run_bootstrap("kanon", "--output-dir", str(tmp_path / "scratch"))
        assert "kanon add kanon" in result.stderr, f"Expected 'kanon add kanon' in stderr, got: {result.stderr!r}"

    def test_stderr_contains_see_docs(self, tmp_path: pathlib.Path) -> None:
        result = _run_bootstrap("kanon", "--output-dir", str(tmp_path / "scratch"))
        assert "See docs/migration-bootstrap-to-add.md." in result.stderr, (
            f"Expected 'See docs/migration-bootstrap-to-add.md.' in stderr, got: {result.stderr!r}"
        )

    def test_stdout_is_empty(self, tmp_path: pathlib.Path) -> None:
        result = _run_bootstrap("kanon", "--output-dir", str(tmp_path / "scratch"))
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"

    def test_output_dir_not_created(self, tmp_path: pathlib.Path) -> None:
        scratch = tmp_path / "scratch"
        _run_bootstrap("kanon", "--output-dir", str(scratch))
        assert not scratch.exists(), (
            f"Expected --output-dir '{scratch}' to NOT be created (shim must not delegate), but it exists."
        )

    def test_no_files_in_tmp_path(self, tmp_path: pathlib.Path) -> None:
        scratch = tmp_path / "scratch"
        _run_bootstrap("kanon", "--output-dir", str(scratch))
        assert list(tmp_path.iterdir()) == [], (
            f"Expected tmp_path to be empty after shim run, but found: {list(tmp_path.iterdir())}"
        )


@pytest.mark.integration
class TestBootstrapShimListSubcommand:
    """Verify `kanon bootstrap list` emits the deprecation WARN and exits 3."""

    def test_exit_code_is_3(self) -> None:
        result = _run_bootstrap("list")
        assert result.returncode == 3, f"Expected exit code 3, got {result.returncode}.\nstderr: {result.stderr!r}"

    def test_stderr_contains_warn_prefix(self) -> None:
        result = _run_bootstrap("list")
        assert "WARN: 'kanon bootstrap list' is deprecated. Run instead:" in result.stderr, (
            f"Expected verbatim WARN text in stderr, got: {result.stderr!r}"
        )

    def test_stderr_contains_kanon_list(self) -> None:
        result = _run_bootstrap("list")
        assert "kanon list" in result.stderr, f"Expected 'kanon list' in stderr, got: {result.stderr!r}"

    def test_stderr_contains_see_docs(self) -> None:
        result = _run_bootstrap("list")
        assert "See docs/migration-bootstrap-to-add.md." in result.stderr, (
            f"Expected 'See docs/migration-bootstrap-to-add.md.' in stderr, got: {result.stderr!r}"
        )

    def test_stdout_is_empty(self) -> None:
        result = _run_bootstrap("list")
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"


@pytest.mark.integration
class TestBootstrapShimSentinelCatalogSource:
    """Verify the shim never reaches catalog-resolve code even with a sentinel --catalog-source."""

    def test_sentinel_catalog_source_exits_3_not_clone_error(self, tmp_path: pathlib.Path) -> None:
        """A sentinel --catalog-source that would trigger a real clone must not be reached.

        If the shim mistakenly delegated, git would fail trying to clone the
        sentinel URL. The shim must exit 3 without touching the catalog.
        """
        result = _run_bootstrap(
            "list",
            "--catalog-source",
            "https://example.com/x.git@main",
            "--output-dir",
            str(tmp_path / "scratch"),
        )
        assert result.returncode == 3, (
            f"Expected exit code 3 (shim, not clone error), got {result.returncode}.\nstderr: {result.stderr!r}"
        )

    def test_sentinel_catalog_source_no_clone_attempt_on_stderr(self, tmp_path: pathlib.Path) -> None:
        result = _run_bootstrap(
            "list",
            "--catalog-source",
            "https://example.com/x.git@main",
            "--output-dir",
            str(tmp_path / "scratch"),
        )
        # If clone was attempted, stderr would mention "git clone", "Cloning",
        # "fatal:", or similar git diagnostic output.
        assert "Cloning" not in result.stderr, f"Unexpected clone attempt in stderr: {result.stderr!r}"
        assert "fatal:" not in result.stderr, f"Unexpected git fatal in stderr: {result.stderr!r}"
        assert "ERROR: " not in result.stderr, (
            f"Unexpected ERROR prefix in stderr (shim should only emit WARN): {result.stderr!r}"
        )
