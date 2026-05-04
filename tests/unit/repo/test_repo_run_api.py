"""TDD RED tests for the repo_run() public API function.

These tests define the contract for repo_run() and must fail initially because
the function does not exist yet. The tests will pass once repo_run() is
implemented in E0-F2-S2-T8.

Contract under test:
    repo_run(argv: list[str], *, repo_dir: str) -> int

    - General-purpose dispatcher that accepts an arbitrary argv list and passes
      it to run_from_args().
    - Returns the integer exit code from the subcommand (0 for success).
    - Raises RepoCommandError on an invalid or unknown subcommand.
    - Does not call os.execv.
    - Catches SystemExit and converts it to a return code (0) or raises
      RepoCommandError (non-zero exit).
    - Does not mutate sys.argv.
"""

import os
import pathlib
import subprocess
import sys
from typing import NoReturn

import pytest

import kanon_cli.repo as repo_pkg
from kanon_cli.repo import RepoCommandError


# ---------------------------------------------------------------------------
# Shared test helper
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _make_repo_dir(tmp_path: pathlib.Path) -> str:
    """Create a minimal .repo directory and return the .repo path as a string.

    The returned path is the .repo subdirectory, matching the convention
    used by run_from_args() which expects repo_dir to be the .repo path.

    Also creates .repo/repo/ as a minimal git repository with one tagged
    commit, which is required by the 'help' subcommand to run git describe.
    """
    repo_dot_dir = tmp_path / ".repo"
    manifests_dir = repo_dot_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    manifest_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://github.com/caylent-solutions/" />
  <default revision="main" remote="origin" />
</manifest>
"""
    manifest_path = manifests_dir / "default.xml"
    manifest_path.write_text(manifest_content, encoding="utf-8")

    manifest_link = repo_dot_dir / "manifest.xml"
    manifest_link.symlink_to(manifest_path)

    # Some subcommands probe git metadata inside .repo/repo/, so seed the
    # directory as a git repository with at least one tagged commit.
    repo_tool_dir = repo_dot_dir / "repo"
    repo_tool_dir.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], cwd=repo_tool_dir)
    _git(["config", "user.email", "test@example.com"], cwd=repo_tool_dir)
    _git(["config", "user.name", "Test"], cwd=repo_tool_dir)
    (repo_tool_dir / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    _git(["add", "VERSION"], cwd=repo_tool_dir)
    _git(["commit", "-m", "Initial commit"], cwd=repo_tool_dir)
    _git(["tag", "-a", "v1.0.0", "-m", "Version 1.0.0"], cwd=repo_tool_dir)

    return str(repo_dot_dir)


# ---------------------------------------------------------------------------
# AC-TEST-001: repo_run() dispatches a subcommand via the argv list
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_repo_run_dispatches_subcommand_via_argv(tmp_path: pathlib.Path) -> None:
    """AC-TEST-001: repo_run() must be importable and dispatch subcommands.

    The function does not exist yet; this test fails with AttributeError because
    repo_run is not exported from the kanon_cli.repo package.

    Once implemented, repo_run() must accept an argv list and a repo_dir
    keyword argument, then dispatch the given subcommand by passing the argv
    list to run_from_args(). The "help" subcommand is used here because it
    does not require network access or a full .repo checkout.

    The test verifies that repo_run() is exported from the package and callable.
    """
    assert hasattr(repo_pkg, "repo_run"), (
        "repo_run() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )
    assert callable(repo_pkg.repo_run), "repo_pkg.repo_run must be callable"

    repo_dot_dir = _make_repo_dir(tmp_path)

    # "help" subcommand succeeds without network access and exits 0.
    result = repo_pkg.repo_run(["help"], repo_dir=repo_dot_dir)
    assert result == 0, f"repo_run(['help'], repo_dir=...) must return 0 on success, got {result!r}"


# ---------------------------------------------------------------------------
# AC-TEST-002: repo_run() returns the exit code from the subcommand
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_repo_run_returns_exit_code_from_subcommand(tmp_path: pathlib.Path) -> None:
    """AC-TEST-002: repo_run() must return the integer exit code from the subcommand.

    A successful invocation (exit code 0) must return 0. The test verifies that
    the return type is int and the value matches what run_from_args() would
    report for a successful command.

    The test fails in RED phase because repo_run does not exist yet.
    """
    repo_run = getattr(repo_pkg, "repo_run", None)
    assert repo_run is not None, (
        "repo_run() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    import inspect

    sig = inspect.signature(repo_run)
    params = list(sig.parameters.keys())
    assert "argv" in params, f"repo_run() must accept an 'argv' parameter. Actual parameters: {params!r}"
    assert "repo_dir" in params, f"repo_run() must accept a 'repo_dir' parameter. Actual parameters: {params!r}"

    repo_dot_dir = _make_repo_dir(tmp_path)
    exit_code = repo_pkg.repo_run(["help"], repo_dir=repo_dot_dir)

    assert isinstance(exit_code, int), (
        f"repo_run() must return an int exit code. Got {type(exit_code).__name__!r}: {exit_code!r}"
    )
    assert exit_code == 0, f"repo_run(['help'], ...) must return 0 for a successful invocation. Got {exit_code!r}"


# ---------------------------------------------------------------------------
# AC-TEST-003: repo_run() raises on an invalid/unknown subcommand
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_repo_run_raises_on_unknown_subcommand(tmp_path: pathlib.Path) -> None:
    """AC-TEST-003: repo_run() must raise RepoCommandError for an unknown subcommand.

    When the argv list names a subcommand that does not exist in the repo tool
    (e.g. "no-such-subcommand-xyz"), the underlying repo command exits with a
    non-zero code. repo_run() must surface this as a RepoCommandError so that
    library callers can detect and handle the failure programmatically.

    The test fails in RED phase because repo_run does not exist yet.
    """
    repo_run = getattr(repo_pkg, "repo_run", None)
    assert repo_run is not None, (
        "repo_run() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    repo_dot_dir = _make_repo_dir(tmp_path)

    with pytest.raises(RepoCommandError) as exc_info:
        repo_pkg.repo_run(["no-such-subcommand-xyz"], repo_dir=repo_dot_dir)

    assert exc_info.value.exit_code is not None, (
        f"RepoCommandError must carry the exit_code from the underlying failure. Got: {exc_info.value!r}"
    )
    assert exc_info.value.exit_code != 0, (
        f"RepoCommandError.exit_code must be non-zero for an unknown subcommand. "
        f"Got exit_code={exc_info.value.exit_code!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-004: repo_run() does not call os.execv
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_repo_run_does_not_call_os_execv(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-TEST-004: repo_run() must not call os.execv during execution.

    Monkeypatch os.execv with a sentinel that raises AssertionError if invoked.
    Any call to os.execv from within repo_run() would replace the calling
    process -- a critical isolation violation for library code.

    The test fails in RED phase because repo_run does not exist yet.
    """
    repo_run = getattr(repo_pkg, "repo_run", None)
    assert repo_run is not None, (
        "repo_run() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    execv_calls: list[tuple[str, list[str]]] = []

    def _record_execv(path: str, argv: list[str]) -> NoReturn:
        execv_calls.append((path, list(argv)))
        raise AssertionError(f"os.execv was called during repo_run(): path={path!r}, argv={argv!r}")

    monkeypatch.setattr(os, "execv", _record_execv)

    repo_dot_dir = _make_repo_dir(tmp_path)
    try:
        repo_pkg.repo_run(["help"], repo_dir=repo_dot_dir)
    except RepoCommandError:
        pass
    except SystemExit as exc:
        raise AssertionError(
            f"repo_run() raised SystemExit({exc.code!r}) -- library code must not exit the process."
        ) from exc

    assert execv_calls == [], f"os.execv was called {len(execv_calls)} time(s) during repo_run(): {execv_calls!r}"


# ---------------------------------------------------------------------------
# AC-TEST-005: repo_run() catches SystemExit and converts it appropriately
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_repo_run_catches_system_exit_and_converts(tmp_path: pathlib.Path) -> None:
    """AC-TEST-005: repo_run() must catch SystemExit and convert it appropriately.

    repo_run() must not allow SystemExit to escape to the caller. When the
    underlying subcommand exits with code 0 (success), repo_run() must return
    0 rather than letting SystemExit propagate. When the subcommand exits with
    a non-zero code (failure), repo_run() must raise RepoCommandError rather
    than letting SystemExit propagate.

    Library code must never let SystemExit reach the caller -- only CLI entry
    points are permitted to call sys.exit().

    The test fails in RED phase because repo_run does not exist yet.
    """
    repo_run = getattr(repo_pkg, "repo_run", None)
    assert repo_run is not None, (
        "repo_run() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    repo_dot_dir = _make_repo_dir(tmp_path)

    # Successful subcommand -- SystemExit(0) must become return value 0, not propagate.
    raised_system_exit = False
    try:
        result = repo_pkg.repo_run(["help"], repo_dir=repo_dot_dir)
        assert result == 0, (
            f"repo_run(['help'], ...) must return 0 for a successful command, not raise or return {result!r}"
        )
    except SystemExit as exc:
        raised_system_exit = True
        pytest.fail(
            f"repo_run() raised SystemExit({exc.code!r}) on a successful command -- "
            f"library code must catch SystemExit and return 0 instead."
        )

    assert not raised_system_exit, "repo_run() allowed SystemExit(0) to propagate"

    # Failing subcommand -- SystemExit(non-zero) must become RepoCommandError, not propagate.
    try:
        repo_pkg.repo_run(["no-such-subcommand-xyz"], repo_dir=repo_dot_dir)
    except RepoCommandError:
        pass  # Expected -- the correct behaviour.
    except SystemExit as exc:
        pytest.fail(
            f"repo_run() raised SystemExit({exc.code!r}) on a failing command -- "
            f"library code must raise RepoCommandError instead of propagating SystemExit."
        )


# ---------------------------------------------------------------------------
# AC-TEST-006: repo_run() does not mutate sys.argv
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_repo_run_does_not_mutate_sys_argv(tmp_path: pathlib.Path) -> None:
    """AC-TEST-006: repo_run() must not alter sys.argv.

    Snapshot sys.argv before calling repo_run() and assert the list is
    identical after the call returns (same length, same elements, same order),
    regardless of whether the call succeeds or raises RepoCommandError.

    The test fails in RED phase because repo_run does not exist yet.
    """
    repo_run = getattr(repo_pkg, "repo_run", None)
    assert repo_run is not None, (
        "repo_run() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    repo_dot_dir = _make_repo_dir(tmp_path)
    argv_before = list(sys.argv)

    # Successful call -- must not mutate sys.argv.
    try:
        repo_pkg.repo_run(["help"], repo_dir=repo_dot_dir)
    except RepoCommandError:
        pass

    argv_after = list(sys.argv)
    assert argv_after == argv_before, (
        f"repo_run() mutated sys.argv on a successful call.\n  Before: {argv_before!r}\n  After:  {argv_after!r}"
    )

    # Failing call -- must also not mutate sys.argv.
    argv_before_fail = list(sys.argv)
    try:
        repo_pkg.repo_run(["no-such-subcommand-xyz"], repo_dir=repo_dot_dir)
    except RepoCommandError:
        pass

    argv_after_fail = list(sys.argv)
    assert argv_after_fail == argv_before_fail, (
        f"repo_run() mutated sys.argv on a failing call.\n  Before: {argv_before_fail!r}\n  After:  {argv_after_fail!r}"
    )
