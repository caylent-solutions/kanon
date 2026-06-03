"""Integration tests for the kanon completion subcommand.

Invokes the installed CLI via subprocess and verifies:
  - kanon completion bash: exit 0, stdout non-empty, stderr empty
  - kanon completion zsh:  exit 0, stdout non-empty, stderr empty
  - Generated bash script passes bash -n (syntax check)
  - Generated zsh script passes zsh -n (syntax check)
  - kanon completion fish: non-zero exit, stderr names valid choices

AC-TEST-002: End-to-end subprocess test of the completion subcommand.
AC-FUNC-001, AC-FUNC-002, AC-FUNC-003, AC-FUNC-005, AC-FUNC-006.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import os

import pytest


def _run_kanon(*args: str) -> subprocess.CompletedProcess[str]:
    """Run kanon CLI via the current Python interpreter's entry point."""
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args],
        capture_output=True,
        text=True,
    )


@pytest.mark.integration
def test_completion_bash_exit_zero() -> None:
    """kanon completion bash exits 0."""
    result = _run_kanon("completion", "bash")
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}. stderr: {result.stderr!r}"


@pytest.mark.integration
def test_completion_bash_stdout_non_empty() -> None:
    """kanon completion bash writes a non-empty script to stdout."""
    result = _run_kanon("completion", "bash")
    assert result.stdout.strip(), "stdout must not be empty for bash completion"


@pytest.mark.integration
def test_completion_bash_stderr_empty() -> None:
    """kanon completion bash writes nothing to stderr on success."""
    result = _run_kanon("completion", "bash")
    assert result.stderr == "", f"stderr must be empty, got: {result.stderr!r}"


@pytest.mark.integration
def test_completion_bash_syntax_valid() -> None:
    """Generated bash script passes bash -n (syntax check)."""
    result = _run_kanon("completion", "bash")
    assert result.returncode == 0

    with tempfile.NamedTemporaryFile(mode="w", suffix=".bash", delete=False) as tmp:
        tmp.write(result.stdout)
        tmp_path = tmp.name

    try:
        check = subprocess.run(["bash", "-n", tmp_path], capture_output=True, text=True)
        assert check.returncode == 0, f"bash -n returned {check.returncode}. stderr: {check.stderr!r}"
    finally:
        os.unlink(tmp_path)


@pytest.mark.integration
def test_completion_zsh_exit_zero() -> None:
    """kanon completion zsh exits 0."""
    result = _run_kanon("completion", "zsh")
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}. stderr: {result.stderr!r}"


@pytest.mark.integration
def test_completion_zsh_stdout_non_empty() -> None:
    """kanon completion zsh writes a non-empty script to stdout."""
    result = _run_kanon("completion", "zsh")
    assert result.stdout.strip(), "stdout must not be empty for zsh completion"


@pytest.mark.integration
def test_completion_zsh_stderr_empty() -> None:
    """kanon completion zsh writes nothing to stderr on success."""
    result = _run_kanon("completion", "zsh")
    assert result.stderr == "", f"stderr must be empty, got: {result.stderr!r}"


@pytest.mark.integration
def test_completion_zsh_syntax_valid() -> None:
    """Generated zsh script passes zsh -n (syntax check)."""
    result = _run_kanon("completion", "zsh")
    assert result.returncode == 0

    with tempfile.NamedTemporaryFile(mode="w", suffix=".zsh", delete=False) as tmp:
        tmp.write(result.stdout)
        tmp_path = tmp.name

    try:
        check = subprocess.run(["zsh", "-n", tmp_path], capture_output=True, text=True)
        assert check.returncode == 0, f"zsh -n returned {check.returncode}. stderr: {check.stderr!r}"
    finally:
        os.unlink(tmp_path)


@pytest.mark.integration
def test_completion_fish_exits_nonzero() -> None:
    """kanon completion fish exits non-zero (invalid choice)."""
    result = _run_kanon("completion", "fish")
    assert result.returncode != 0, "Expected non-zero exit for unsupported shell 'fish'"


@pytest.mark.integration
def test_completion_fish_stderr_names_valid_choices() -> None:
    """kanon completion fish names the valid choices {bash, zsh} in stderr."""
    result = _run_kanon("completion", "fish")
    combined = result.stderr + result.stdout
    assert "bash" in combined, "Error output must mention 'bash' as a valid choice"
    assert "zsh" in combined, "Error output must mention 'zsh' as a valid choice"
