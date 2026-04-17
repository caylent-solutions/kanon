"""Shared fixtures for functional tests.

Provides session-scoped infrastructure required for end-to-end CLI tests,
including a minimal .repo directory that satisfies the embedded repo tool's
version subcommand requirements.
"""

import os
import subprocess
import pathlib

import pytest


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit.

    Args:
        args: Git subcommand and arguments (without the 'git' prefix).
        cwd: Working directory for the git command.

    Raises:
        RuntimeError: When the git command exits with a non-zero code.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


@pytest.fixture(scope="session", autouse=True)
def functional_repo_dir(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Create a minimal .repo directory for the session and export KANON_REPO_DIR.

    The embedded repo tool's version subcommand requires a .repo/repo/ git
    repository with at least one tagged commit. This fixture creates that
    minimal structure so that 'kanon repo version' exits with code 0 during
    functional tests.

    The fixture sets os.environ[KANON_REPO_DIR] so that subprocess calls made
    by functional tests inherit the configured .repo path without requiring
    an explicit --repo-dir argument on the command line.

    Yields:
        The path to the created .repo directory.
    """
    from kanon_cli.constants import KANON_REPO_DIR_ENV

    base = tmp_path_factory.mktemp("functional_repo")
    repo_dot_dir = base / ".repo"
    manifests_dir = repo_dot_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://github.com/caylent-solutions/" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_path = manifests_dir / "default.xml"
    manifest_path.write_text(manifest_content, encoding="utf-8")

    manifest_link = repo_dot_dir / "manifest.xml"
    manifest_link.symlink_to(manifest_path)

    # The version subcommand calls git describe HEAD inside .repo/repo/,
    # so .repo/repo/ must be a git repository with at least one tagged commit.
    repo_tool_dir = repo_dot_dir / "repo"
    repo_tool_dir.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], cwd=repo_tool_dir)
    _git(["config", "user.email", "test@example.com"], cwd=repo_tool_dir)
    _git(["config", "user.name", "Test"], cwd=repo_tool_dir)
    (repo_tool_dir / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    _git(["add", "VERSION"], cwd=repo_tool_dir)
    _git(["commit", "-m", "Initial commit"], cwd=repo_tool_dir)
    _git(["tag", "-a", "v1.0.0", "-m", "Version 1.0.0"], cwd=repo_tool_dir)

    previous = os.environ.get(KANON_REPO_DIR_ENV)
    os.environ[KANON_REPO_DIR_ENV] = str(repo_dot_dir)
    yield repo_dot_dir
    if previous is None:
        del os.environ[KANON_REPO_DIR_ENV]
    else:
        os.environ[KANON_REPO_DIR_ENV] = previous
