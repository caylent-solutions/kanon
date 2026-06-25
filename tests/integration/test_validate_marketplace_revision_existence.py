"""Integration tests for ``validate_revision_existence`` via the real CLI.

Drives ``kanon validate marketplace`` as a subprocess (``python -m kanon_cli``)
against real, network-free git fixtures built with ``git init`` / ``git tag``
so the existence check runs through the production ``git ls-remote`` runner
rather than an injected stub (item 18, spec Section 4.5 / FR-22 / FR-23).

Behaviours exercised end to end:

- Local ``file://`` source, exact tag that EXISTS -> exit 0 (clean).
- Local ``file://`` source, exact tag that does NOT exist -> exit 1 with a
  ``does not exist`` error on stderr.
- Unreachable remote source (a refused ``git://`` port), default policy ->
  exit 0 with an ``existence not verified`` / format-only WARNING on stderr.
- The same unreachable remote with ``KANON_VALIDATE_REQUIRE_EXISTENCE=1`` ->
  exit 1 (existence becomes mandatory).
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from kanon_cli.constants import REVISION_EXISTENCE_REQUIRED_ENV_VAR


_GIT_USER_NAME = "Revision Existence Test User"
_GIT_USER_EMAIL = "revision-existence@example.com"

_PROJECT_NAME = "proj"
_PROJECT_PATH = ".packages/proj"
_TAG_NAME = "example/proj/1.0.0"
_EXISTING_REVISION = "refs/tags/example/proj/1.0.0"
_MISSING_REVISION = "refs/tags/example/proj/9.9.9"

_UNREACHABLE_REMOTE_URL = "git://127.0.0.1:9/proj.git"

_FAST_GIT_ENV = {
    "KANON_GIT_LS_REMOTE_TIMEOUT": "5",
    "KANON_GIT_RETRY_COUNT": "1",
}


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in *cwd*, raising RuntimeError on a non-zero exit.

    Args:
        args: Git subcommand and arguments (without the ``git`` prefix).
        cwd: Working directory for the git command.

    Raises:
        RuntimeError: When git exits with a non-zero code.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _build_local_tagged_bare_repo(base: pathlib.Path) -> pathlib.Path:
    """Create a real bare git repo carrying the exact tag ``example/proj/1.0.0``.

    Initialises a working repo with one commit, tags it, and clones it bare so
    the bare path can serve as a ``file://`` remote that ``git ls-remote``
    resolves offline.

    Args:
        base: Parent directory under which the work and bare repos are created.

    Returns:
        The resolved absolute path to the bare repository.
    """
    base.mkdir(parents=True, exist_ok=True)
    work_dir = base / "content-work"
    work_dir.mkdir()
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)

    (work_dir / "README.md").write_text("content fixture\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)
    _git(["tag", _TAG_NAME], cwd=work_dir)

    bare_dir = base / "proj.git"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)
    return bare_dir.resolve()


def _write_marketplace_manifest(
    repo_root: pathlib.Path,
    fetch_url: str,
    revision: str,
) -> None:
    """Write a single catalog-entry manifest under ``repo_root/repo-specs/``.

    The manifest declares one ``<remote>`` whose ``fetch`` is *fetch_url* and one
    ``<project>`` pinning *revision*, plus the ``<catalog-metadata>`` block that
    marks the file as a discoverable catalog entry.

    Args:
        repo_root: Repository root that will contain ``repo-specs/``.
        fetch_url: The remote fetch URL the project resolves to.
        revision: The exact-tag ``<project revision>`` value to existence-check.
    """
    specs_dir = repo_root / "repo-specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    manifest = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="r" fetch="{fetch_url}" />\n'
        f'  <project name="{_PROJECT_NAME}" path="{_PROJECT_PATH}" remote="r" revision="{revision}">\n'
        '    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />\n'
        "  </project>\n"
        "  <catalog-metadata>\n"
        f"    <name>{_PROJECT_NAME}</name>\n"
        "    <display-name>Proj</display-name>\n"
        "    <description>existence fixture</description>\n"
        "    <version>1.0.0</version>\n"
        "  </catalog-metadata>\n"
        "</manifest>\n"
    )
    (specs_dir / "a-marketplace.xml").write_text(manifest, encoding="utf-8")


def _run_validate_marketplace(
    repo_root: pathlib.Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke ``kanon validate marketplace --repo-root <repo_root>`` as a subprocess.

    Args:
        repo_root: The repository root passed via ``--repo-root``.
        extra_env: Environment variables merged on top of the inherited
            environment for the subprocess.

    Returns:
        The completed subprocess result (text mode, output captured).
    """
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", "validate", "marketplace", "--repo-root", str(repo_root)],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.integration
class TestRevisionExistenceLocalSource:
    """Existence checks against a real local ``file://`` git repo fixture."""

    def test_existing_exact_tag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """An exact tag that exists in the local repo passes with a clean stderr."""
        bare = _build_local_tagged_bare_repo(tmp_path / "repos")
        repo_root = tmp_path / "repo"
        _write_marketplace_manifest(repo_root, f"file://{bare}", _EXISTING_REVISION)

        result = _run_validate_marketplace(repo_root)

        assert result.returncode == 0, (
            f"expected exit 0 for an existing exact tag.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert result.stderr == "", f"expected no stderr on success.\nstderr: {result.stderr!r}"
        assert "passed" in result.stdout.lower(), f"expected a success summary on stdout.\nstdout: {result.stdout!r}"

    def test_missing_exact_tag_exits_one_with_does_not_exist(self, tmp_path: pathlib.Path) -> None:
        """An exact tag absent from the reachable local repo is a hard error."""
        bare = _build_local_tagged_bare_repo(tmp_path / "repos")
        repo_root = tmp_path / "repo"
        _write_marketplace_manifest(repo_root, f"file://{bare}", _MISSING_REVISION)

        result = _run_validate_marketplace(repo_root)

        assert result.returncode == 1, (
            f"expected exit 1 for a missing exact tag.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "does not exist" in result.stderr.lower(), (
            f"expected a 'does not exist' error on stderr.\nstderr: {result.stderr!r}"
        )
        assert _MISSING_REVISION in result.stderr, (
            f"expected the missing revision named in stderr.\nstderr: {result.stderr!r}"
        )
        assert "does not exist" not in result.stdout.lower(), (
            f"existence error must not leak to stdout.\nstdout: {result.stdout!r}"
        )


@pytest.mark.integration
class TestRevisionExistenceUnreachableRemote:
    """Two-tier degrade behaviour against an unreachable (refused) remote."""

    def test_unreachable_remote_default_warns_and_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """By default an unreachable remote degrades to a format-only WARNING."""
        repo_root = tmp_path / "repo"
        _write_marketplace_manifest(repo_root, _UNREACHABLE_REMOTE_URL, _EXISTING_REVISION)

        result = _run_validate_marketplace(repo_root, extra_env=_FAST_GIT_ENV)

        assert result.returncode == 0, (
            f"expected exit 0 when an unreachable remote degrades to format-only.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "existence not verified" in result.stderr.lower(), (
            f"expected an 'existence not verified' WARNING on stderr.\nstderr: {result.stderr!r}"
        )
        assert "warning" in result.stderr.lower(), f"expected a WARNING label on stderr.\nstderr: {result.stderr!r}"
        assert "passed" in result.stdout.lower(), (
            f"expected a success summary on stdout despite the warning.\nstdout: {result.stdout!r}"
        )

    def test_unreachable_remote_required_existence_exits_one(self, tmp_path: pathlib.Path) -> None:
        """With ``KANON_VALIDATE_REQUIRE_EXISTENCE=1`` the unconfirmable tag is fatal."""
        repo_root = tmp_path / "repo"
        _write_marketplace_manifest(repo_root, _UNREACHABLE_REMOTE_URL, _EXISTING_REVISION)

        extra_env = dict(_FAST_GIT_ENV)
        extra_env[REVISION_EXISTENCE_REQUIRED_ENV_VAR] = "1"
        result = _run_validate_marketplace(repo_root, extra_env=extra_env)

        assert result.returncode == 1, (
            f"expected exit 1 when {REVISION_EXISTENCE_REQUIRED_ENV_VAR}=1 forces existence.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "could not be existence-checked" in result.stderr.lower(), (
            f"expected an existence-mandatory error on stderr.\nstderr: {result.stderr!r}"
        )
        assert REVISION_EXISTENCE_REQUIRED_ENV_VAR in result.stderr, (
            f"expected the gate env var named in the error.\nstderr: {result.stderr!r}"
        )
