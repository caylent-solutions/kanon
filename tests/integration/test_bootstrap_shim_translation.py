"""Integration tests for bootstrap shim flag translation.

Invokes ``python -m kanon_cli bootstrap ...`` via subprocess and asserts
the stderr WARN body contains the verbatim translated replacement command
for each translation case from spec Section 4.9.

These tests cover AC-TEST-002 and AC-CYCLE-001.
"""

import pathlib
import subprocess
import sys

import pytest

from kanon_cli.commands.bootstrap import (
    _NOTE_OUTPUT_DIR_ADD,
    _NOTE_OUTPUT_DIR_LIST,
)

_CATALOG_SOURCE_URL = "https://example.com/x.git@main"


def _run_bootstrap(*args: str, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    """Invoke ``python -m kanon_cli bootstrap <args>`` as a subprocess.

    Args:
        *args: Additional arguments to pass after ``bootstrap``.
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
class TestBootstrapShimTranslationAddArm:
    """Subprocess tests for flag translation in the 'add' arm."""

    def test_no_flags_warn_shows_bare_add_command(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap kanon (no flags) -> WARN shows 'kanon add kanon' with no extra tail."""
        result = _run_bootstrap("kanon", cwd=tmp_path)
        assert result.returncode == 3
        assert "kanon add kanon" in result.stderr
        # No spurious flags should appear in the replacement line
        assert "--catalog-source" not in result.stderr

    def test_catalog_source_appears_in_warn(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap kanon --catalog-source <url> -> WARN shows translated replacement."""
        result = _run_bootstrap(
            "kanon",
            "--catalog-source",
            _CATALOG_SOURCE_URL,
            cwd=tmp_path,
        )
        assert result.returncode == 3
        assert f"kanon add kanon --catalog-source {_CATALOG_SOURCE_URL}" in result.stderr

    def test_output_dir_triggers_note_add_in_warn(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap kanon --output-dir -> WARN contains the add-arm Note."""
        scratch = tmp_path / "scratch"
        result = _run_bootstrap(
            "kanon",
            "--output-dir",
            str(scratch),
            cwd=tmp_path,
        )
        assert result.returncode == 3
        assert _NOTE_OUTPUT_DIR_ADD in result.stderr

    def test_output_dir_does_not_create_dir(self, tmp_path: pathlib.Path) -> None:
        """The shim must NOT create --output-dir (no filesystem mutation)."""
        scratch = tmp_path / "scratch"
        _run_bootstrap("kanon", "--output-dir", str(scratch), cwd=tmp_path)
        assert not scratch.exists(), f"Expected '{scratch}' to NOT be created by shim, but it exists"

    def test_catalog_source_and_output_dir_combined(self, tmp_path: pathlib.Path) -> None:
        """Both flags together: WARN shows catalog-source line AND note line.

        This is AC-CYCLE-001: the end-to-end translation cycle test.
        """
        scratch = tmp_path / "scratch"
        result = _run_bootstrap(
            "kanon",
            "--catalog-source",
            _CATALOG_SOURCE_URL,
            "--output-dir",
            str(scratch),
            cwd=tmp_path,
        )
        assert result.returncode == 3
        assert f"kanon add kanon --catalog-source {_CATALOG_SOURCE_URL}" in result.stderr
        assert _NOTE_OUTPUT_DIR_ADD in result.stderr
        assert not scratch.exists(), f"Expected '{scratch}' to NOT be created, but it exists"

    def test_stdout_is_empty_add_arm(self, tmp_path: pathlib.Path) -> None:
        """Shim must write nothing to stdout for add arm."""
        result = _run_bootstrap(
            "kanon",
            "--catalog-source",
            _CATALOG_SOURCE_URL,
            cwd=tmp_path,
        )
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"


@pytest.mark.integration
class TestBootstrapShimTranslationListArm:
    """Subprocess tests for flag translation in the 'list' arm."""

    def test_no_flags_warn_shows_bare_list_command(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap list (no flags) -> WARN shows 'kanon list' with no extra tail."""
        result = _run_bootstrap("list", cwd=tmp_path)
        assert result.returncode == 3
        assert "kanon list" in result.stderr
        assert "--catalog-source" not in result.stderr

    def test_catalog_source_appears_in_warn(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap list --catalog-source <url> -> WARN shows translated replacement."""
        result = _run_bootstrap(
            "list",
            "--catalog-source",
            _CATALOG_SOURCE_URL,
            cwd=tmp_path,
        )
        assert result.returncode == 3
        assert f"kanon list --catalog-source {_CATALOG_SOURCE_URL}" in result.stderr

    def test_output_dir_triggers_note_list_in_warn(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap list --output-dir -> WARN contains the list-arm Note."""
        scratch = tmp_path / "scratch"
        result = _run_bootstrap(
            "list",
            "--output-dir",
            str(scratch),
            cwd=tmp_path,
        )
        assert result.returncode == 3
        assert _NOTE_OUTPUT_DIR_LIST in result.stderr

    def test_output_dir_note_differs_from_add_note(self, tmp_path: pathlib.Path) -> None:
        """List-arm note must NOT contain the add-arm text."""
        scratch = tmp_path / "scratch"
        result = _run_bootstrap(
            "list",
            "--output-dir",
            str(scratch),
            cwd=tmp_path,
        )
        assert _NOTE_OUTPUT_DIR_ADD not in result.stderr
        assert _NOTE_OUTPUT_DIR_LIST in result.stderr

    def test_catalog_source_and_output_dir_combined(self, tmp_path: pathlib.Path) -> None:
        """Both flags together for list arm: WARN shows catalog-source AND note."""
        scratch = tmp_path / "scratch"
        result = _run_bootstrap(
            "list",
            "--catalog-source",
            _CATALOG_SOURCE_URL,
            "--output-dir",
            str(scratch),
            cwd=tmp_path,
        )
        assert result.returncode == 3
        assert f"kanon list --catalog-source {_CATALOG_SOURCE_URL}" in result.stderr
        assert _NOTE_OUTPUT_DIR_LIST in result.stderr

    def test_stdout_is_empty_list_arm(self, tmp_path: pathlib.Path) -> None:
        """Shim must write nothing to stdout for list arm."""
        result = _run_bootstrap(
            "list",
            "--catalog-source",
            _CATALOG_SOURCE_URL,
            cwd=tmp_path,
        )
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"
