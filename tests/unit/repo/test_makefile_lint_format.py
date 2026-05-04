"""Tests for Makefile lint, format, and check targets.

Validates that the rpm-git-repo Makefile lint/format/check targets invoke the
correct tools: ruff for Python linting and formatting.
"""

import os
import re
import subprocess

import pytest


@pytest.mark.unit
@pytest.mark.parametrize(
    "tool",
    ["ruff check", "ruff format"],
    ids=["ruff-check", "ruff-format"],
)
def test_make_lint_calls_tool(repo_root, tool):
    """Validate that make lint invokes expected linting tools.

    Given: The Makefile has a lint target
    When: make lint is dry-run
    Then: The commands include the expected tool
    """
    result = subprocess.run(
        ["make", "-n", "-C", repo_root, "lint"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"make -n lint failed: {result.stderr}"
    assert tool in result.stdout, f"lint target must invoke '{tool}', got: {result.stdout}"


@pytest.mark.unit
def test_make_format_calls_ruff_format(repo_root):
    """Validate that make format invokes ruff format.

    Given: The Makefile has a format target
    When: make format is dry-run
    Then: The commands include 'ruff format' (without --check)
    """
    result = subprocess.run(
        ["make", "-n", "-C", repo_root, "format"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"make -n format failed: {result.stderr}"
    assert "ruff format" in result.stdout, f"format target must invoke 'ruff format', got: {result.stdout}"
    # format target should not use --check (that's format-check)
    format_lines = [line for line in result.stdout.splitlines() if "ruff format" in line]
    for line in format_lines:
        assert "--check" not in line, f"format target must not use --check (use format-check instead): {line}"


@pytest.mark.unit
def test_make_check_is_readonly(repo_root):
    """Validate that make check is read-only (uses --check for format verification).

    Given: The Makefile has check and format-check targets
    When: make format-check is dry-run
    Then: The commands include 'ruff format --check'
    """
    result = subprocess.run(
        ["make", "-n", "-C", repo_root, "format-check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"make -n format-check failed: {result.stderr}"
    assert "ruff format" in result.stdout and "--check" in result.stdout, (
        f"format-check target must invoke 'ruff format --check', got: {result.stdout}"
    )


@pytest.mark.unit
def test_lint_target_has_tool_comments(repo_root):
    """Validate that lint target Makefile comments document which tools are invoked.

    Given: The Makefile has a lint target
    When: We inspect the Makefile
    Then: The lint target's help comment mentions the tools it uses
    """
    makefile_path = os.path.join(repo_root, "Makefile")
    with open(makefile_path) as f:
        content = f.read()
    match = re.search(r"^lint:.*##\s*(.+)", content, re.MULTILINE)
    assert match, "lint target must have a ## help comment"
    comment = match.group(1).lower()
    assert "ruff" in comment, f"lint help comment must mention ruff, got: {comment}"
