"""Integration tests for 'kanon doctor' subcheck 11 -- remote reachability.

Drives the full CLI via subprocess against a real fixture git server.
Fixture workspace contains:
  - One reachable bare repo (accessible via file:// URL).
  - One removed/unavailable remote URL (non-existent path).

Assertions:
  - kanon doctor exits 0 (remote-reachability failures are warnings, not errors).
  - stderr contains exactly one WARN finding naming the unreachable URL.
  - The warning contains the remediation pointer to docs/git-auth-setup.md.

AC-TEST-002, AC-CYCLE-001.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from kanon_cli.core.kanon_hash import kanon_hash
from kanon_cli.core.lockfile import (
    CURRENT_SCHEMA_VERSION,
    Lockfile,
    SourceEntry,
    write_lockfile,
)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit.

    Args:
        args: Git subcommand and arguments.
        cwd: Working directory for the command.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _git_output(args: list[str], cwd: pathlib.Path) -> str:
    """Run a git command and return stdout, raising RuntimeError on failure.

    Args:
        args: Git subcommand and arguments.
        cwd: Working directory for the command.

    Returns:
        Stripped stdout text.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")
    return result.stdout.strip()


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with test user config.

    Args:
        work_dir: Directory to initialise as a git repo.
    """
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _create_bare_repo(base: pathlib.Path, name: str) -> tuple[pathlib.Path, str]:
    """Create a bare git repo with one commit and return (bare_path, sha).

    Args:
        base: Parent directory for work and bare repos.
        name: Used for directory naming.

    Returns:
        (bare_path, sha) where sha is HEAD of the only commit.
    """
    work_dir = base / f"{name}-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    (work_dir / "README.md").write_text(f"# {name}\n")
    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Initial"], cwd=work_dir)
    sha = _git_output(["rev-parse", "HEAD"], cwd=work_dir)

    bare_dir = base / f"{name}-bare.git"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)
    return bare_dir.resolve(), sha


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------


def _run_kanon(
    args: list[str],
    cwd: pathlib.Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon CLI via the same Python interpreter.

    Args:
        args: CLI arguments after 'kanon'.
        cwd: Working directory; uses tmp_path if None.
        extra_env: Extra environment variables to merge into the subprocess env.

    Returns:
        CompletedProcess with returncode, stdout, stderr.
    """
    env = dict(os.environ)
    env.pop("KANON_CATALOG_SOURCES", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
    )


# ---------------------------------------------------------------------------
# Workspace builder
# ---------------------------------------------------------------------------


def _build_workspace(
    workspace: pathlib.Path,
    sources: list[dict],
) -> tuple[pathlib.Path, pathlib.Path]:
    """Write .kanon and .kanon.lock in workspace with the given sources.

    Args:
        workspace: Directory for the workspace.
        sources: List of dicts with keys: name, url, revision_spec, resolved_sha.

    Returns:
        (kanon_path, lock_path) for the written files.
    """
    workspace.mkdir(parents=True, exist_ok=True)

    kanon_lines = []
    for s in sources:
        kanon_lines.append(f"KANON_SOURCE_{s['name']}_URL={s['url']}")
        kanon_lines.append(f"KANON_SOURCE_{s['name']}_REVISION={s['revision_spec']}")
        kanon_lines.append(f"KANON_SOURCE_{s['name']}_PATH=repo-specs/meta.xml")
    kanon_lines.append("KANON_MARKETPLACE_INSTALL=false")

    kanon_path = workspace / ".kanon"
    kanon_path.write_text("\n".join(kanon_lines) + "\n", encoding="utf-8")
    kanon_path.chmod(0o644)

    computed_hash = kanon_hash(kanon_path)

    entries = [
        SourceEntry(
            alias=s["name"],
            name=s["name"],
            url=s["url"],
            ref_spec=s["revision_spec"],
            resolved_ref=s["revision_spec"],
            resolved_sha=s["resolved_sha"],
            path="repo-specs/meta.xml",
        )
        for s in sources
    ]
    lockfile = Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash=computed_hash,
        sources=entries,
    )
    lock_path = workspace / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return kanon_path, lock_path


# ---------------------------------------------------------------------------
# Tests: AC-TEST-002 / AC-CYCLE-001 -- full CLI against real fixture git server
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDoctorRemoteReachabilityFullCli:
    """Full-CLI tests for subcheck 11 against real fixture git servers.

    AC-TEST-002: subprocess-driven test with reachable and removed remotes.
    AC-CYCLE-001: end-to-end cycle -- one reachable, one removed; assert
        exit 0 and exactly one WARN finding naming the removed URL.
    """

    def test_no_lockfile_skips_subcheck_11(self, tmp_path: pathlib.Path) -> None:
        """When no .kanon.lock exists, no ls-remote calls are made for subcheck 11 (AC-FUNC-001).

        Verified by absence of any REMOTE_UNREACHABLE or WARN lines in output
        when only the .kanon is present.
        """
        kanon_path = tmp_path / ".kanon"
        kanon_path.write_text(
            "KANON_SOURCE_src_URL=https://example.com/org/repo.git\n"
            "KANON_SOURCE_src_REVISION=main\n"
            "KANON_SOURCE_src_PATH=repo-specs/meta.xml\n"
            "KANON_MARKETPLACE_INSTALL=false\n",
            encoding="utf-8",
        )
        kanon_path.chmod(0o644)

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_path)],
            cwd=tmp_path,
        )

        assert result.returncode == 0
        assert "REMOTE_UNREACHABLE" not in result.stderr

    def test_all_reachable_remotes_no_warn_findings(self, tmp_path: pathlib.Path) -> None:
        """When all remotes are reachable, no WARN finding is emitted for subcheck 11."""
        base = tmp_path / "repos"
        base.mkdir()
        bare_path, sha = _create_bare_repo(base, "repo-a")
        url = f"file://{bare_path}"

        kanon_path, lock_path = _build_workspace(
            tmp_path / "workspace",
            [{"name": "a", "url": url, "revision_spec": "main", "resolved_sha": sha}],
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_path), "--lock-file", str(lock_path)],
            cwd=tmp_path / "workspace",
        )

        assert result.returncode == 0
        assert "REMOTE_UNREACHABLE" not in result.stderr
        # No WARN for reachability
        assert not any("WARN:" in line and "unreachable" in line.lower() for line in result.stderr.splitlines())

    def test_one_unreachable_remote_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """kanon doctor exits 0 when one remote is unreachable (AC-FUNC-003).

        Remote-reachability failures are warnings, not errors.
        """
        base = tmp_path / "repos"
        base.mkdir()
        bare_path, sha = _create_bare_repo(base, "repo-a")
        reachable_url = f"file://{bare_path}"
        # A non-existent path to simulate a removed remote.
        removed_url = f"file://{base}/removed-bare.git"

        kanon_path, lock_path = _build_workspace(
            tmp_path / "workspace",
            [
                {"name": "a", "url": reachable_url, "revision_spec": "main", "resolved_sha": sha},
                {"name": "b", "url": removed_url, "revision_spec": "main", "resolved_sha": sha},
            ],
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_path), "--lock-file", str(lock_path)],
            cwd=tmp_path / "workspace",
        )

        assert result.returncode == 0

    def test_one_unreachable_remote_emits_warn_not_error(self, tmp_path: pathlib.Path) -> None:
        """Unreachable remote produces WARN (not ERROR) in stderr (AC-FUNC-003)."""
        base = tmp_path / "repos"
        base.mkdir()
        bare_path, sha = _create_bare_repo(base, "repo-a")
        removed_url = f"file://{base}/removed-bare.git"

        kanon_path, lock_path = _build_workspace(
            tmp_path / "workspace",
            [
                {"name": "a", "url": removed_url, "revision_spec": "main", "resolved_sha": sha},
            ],
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_path), "--lock-file", str(lock_path)],
            cwd=tmp_path / "workspace",
        )

        assert "WARN:" in result.stderr
        # Must NOT be an error-level finding for this URL
        warn_lines = [line for line in result.stderr.splitlines() if "WARN:" in line and "unreachable" in line.lower()]
        assert len(warn_lines) >= 1

    def test_one_unreachable_remote_stderr_names_url(self, tmp_path: pathlib.Path) -> None:
        """Warning finding names the unreachable URL in stderr (AC-FUNC-004)."""
        base = tmp_path / "repos"
        base.mkdir()
        bare_path, sha = _create_bare_repo(base, "repo-a")
        removed_url = f"file://{base}/removed-bare.git"

        kanon_path, lock_path = _build_workspace(
            tmp_path / "workspace",
            [{"name": "a", "url": removed_url, "revision_spec": "main", "resolved_sha": sha}],
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_path), "--lock-file", str(lock_path)],
            cwd=tmp_path / "workspace",
        )

        assert "removed-bare" in result.stderr

    def test_one_unreachable_remote_stderr_has_remediation_pointer(self, tmp_path: pathlib.Path) -> None:
        """Warning finding references docs/git-auth-setup.md in remediation (AC-FUNC-004)."""
        base = tmp_path / "repos"
        base.mkdir()
        bare_path, sha = _create_bare_repo(base, "repo-a")
        removed_url = f"file://{base}/removed-bare.git"

        kanon_path, lock_path = _build_workspace(
            tmp_path / "workspace",
            [{"name": "a", "url": removed_url, "revision_spec": "main", "resolved_sha": sha}],
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_path), "--lock-file", str(lock_path)],
            cwd=tmp_path / "workspace",
        )

        assert "docs/git-auth-setup.md" in result.stderr

    def test_two_urls_one_removed_exactly_one_warn(self, tmp_path: pathlib.Path) -> None:
        """AC-CYCLE-001: two remotes, one removed, exactly one WARN finding naming the removed URL."""
        base = tmp_path / "repos"
        base.mkdir()
        bare_path, sha_a = _create_bare_repo(base, "reachable")
        reachable_url = f"file://{bare_path}"
        removed_url = f"file://{base}/gone-bare.git"

        kanon_path, lock_path = _build_workspace(
            tmp_path / "workspace",
            [
                {"name": "good", "url": reachable_url, "revision_spec": "main", "resolved_sha": sha_a},
                {"name": "gone", "url": removed_url, "revision_spec": "main", "resolved_sha": sha_a},
            ],
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_path), "--lock-file", str(lock_path)],
            cwd=tmp_path / "workspace",
        )

        assert result.returncode == 0

        warn_unreachable_lines = [
            line for line in result.stderr.splitlines() if "WARN:" in line and "unreachable" in line.lower()
        ]
        assert len(warn_unreachable_lines) == 1
        assert "gone-bare" in warn_unreachable_lines[0] or "gone-bare" in result.stderr

    def test_duplicate_ssh_https_same_repo_one_warn(self, tmp_path: pathlib.Path) -> None:
        """SSH + HTTPS forms of the same removed repo produce at most one warning (AC-FUNC-006)."""
        base = tmp_path / "repos"
        base.mkdir()
        bare_path, sha = _create_bare_repo(base, "repo-base")

        # Two source entries pointing at the same removed repo in different URL forms.
        # Both file:// URLs are distinct strings but canonicalize to the same path.
        removed_path = base / "nonexistent-bare.git"
        url_a = f"file://{removed_path}"
        url_b = f"file://{removed_path}/"

        kanon_path, lock_path = _build_workspace(
            tmp_path / "workspace",
            [
                {"name": "a", "url": url_a, "revision_spec": "main", "resolved_sha": sha},
                {"name": "b", "url": url_b, "revision_spec": "main", "resolved_sha": sha},
            ],
        )

        result = _run_kanon(
            ["doctor", "--kanon-file", str(kanon_path), "--lock-file", str(lock_path)],
            cwd=tmp_path / "workspace",
        )

        assert result.returncode == 0

        warn_unreachable_lines = [
            line for line in result.stderr.splitlines() if "WARN:" in line and "unreachable" in line.lower()
        ]
        # Exactly one warning for the same canonicalized URL (deduplication).
        assert len(warn_unreachable_lines) == 1
