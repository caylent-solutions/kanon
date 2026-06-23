"""Integration tests for 'kanon remove --force' scenarios.

Subprocess-invokes 'kanon remove' with --force against real .kanon files
on disk under tmp_path and asserts on process outputs and file state.

Covers:
- unknown_source + --dry-run + --force against a real .kanon file:
  exit 0, no diff output, no ERROR in stderr, file bytes unchanged (AC-TEST-002)

AC-TEST-002
"""

import os
import pathlib
import subprocess
import sys

import pytest


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def _run_kanon(
    args: list[str],
    env: dict[str, str] | None = None,
) -> "subprocess.CompletedProcess[str]":
    """Invoke the kanon CLI via the current Python interpreter.

    Args:
        args: CLI arguments appended after the module invocation.
        env: Environment dict for the subprocess. When None, uses os.environ.

    Returns:
        The completed process object with returncode, stdout, and stderr.
    """
    cmd = [sys.executable, "-m", "kanon_cli"] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env if env is not None else os.environ.copy(),
    )


# ---------------------------------------------------------------------------
# Fixture content
# ---------------------------------------------------------------------------

_HEADER = "GITBASE=https://git.example.com\n"

_KNOWN_A_BLOCK = (
    "KANON_SOURCE_known_a_URL=https://example.com/known_a.git\n"
    "KANON_SOURCE_known_a_REF=refs/tags/1.0.0\n"
    "KANON_SOURCE_known_a_PATH=repo-specs/known_a.xml\n"
    "KANON_SOURCE_known_a_NAME=known_a\n"
    "KANON_SOURCE_known_a_GITBASE=https://example.com\n"
)

_KNOWN_B_BLOCK = (
    "KANON_SOURCE_known_b_URL=https://example.com/known_b.git\n"
    "KANON_SOURCE_known_b_REF=refs/tags/2.0.0\n"
    "KANON_SOURCE_known_b_PATH=repo-specs/known_b.xml\n"
    "KANON_SOURCE_known_b_NAME=known_b\n"
    "KANON_SOURCE_known_b_GITBASE=https://example.com\n"
)

_TWO_KNOWN_CONTENT = _HEADER + _KNOWN_A_BLOCK + _KNOWN_B_BLOCK


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRemoveForceIntegration:
    """End-to-end --force scenarios invoked via subprocess against real .kanon files."""

    def test_dry_run_force_unknown_source_exit_0_file_unchanged(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: kanon remove unknown_source --dry-run --force exits 0.

        Asserts:
        - exit code is 0
        - stdout is empty (no '-' diff lines for the absent source)
        - stderr does not contain "ERROR:"
        - the fixture file bytes are identical before and after invocation

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(_TWO_KNOWN_CONTENT)
        pre_bytes = kanon_file.read_bytes()

        test_env = os.environ.copy()
        test_env["REPO_TRACE"] = "0"

        result = _run_kanon(
            [
                "remove",
                "unknown_source",
                "--dry-run",
                "--force",
                "--kanon-file",
                str(kanon_file),
            ],
            env=test_env,
        )

        assert result.returncode == 0, (
            f"Expected exit code 0 for dry-run + force on unknown source, "
            f"got {result.returncode}. stderr: {result.stderr!r}"
        )
        assert result.stdout == "", f"Expected empty stdout (no diff lines for absent source), got: {result.stdout!r}"
        assert "ERROR:" not in result.stderr, (
            f"Expected no ERROR in stderr for --force scenario, got: {result.stderr!r}"
        )
        post_bytes = kanon_file.read_bytes()
        assert post_bytes == pre_bytes, (
            "File bytes must be identical before and after dry-run + force "
            "when the only requested source is not present in the file"
        )
