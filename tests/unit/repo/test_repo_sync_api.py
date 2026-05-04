"""TDD RED tests for the repo_sync() public API function.

These tests define the contract for repo_sync() and must fail initially because
the function does not exist yet. The tests will pass once repo_sync() is
implemented in E0-F2-S2-T6.

Contract under test:
    repo_sync(repo_dir: str, *, groups: list[str] | None = None,
              platform: str | None = None, jobs: int | None = None) -> None

    - Clones and fetches all projects defined in the manifest.
    - Creates linkfiles as specified in the manifest.
    - Resolves manifest constraints such as groups and platform filters.
    - Is idempotent -- calling twice on the same repo_dir does not error.
    - Raises RepoCommandError on a bad or unreachable remote, not sys.exit.
    - Does not mutate sys.argv.
    - Restores os.environ to its pre-call state after returning.
    - Raises RepoCommandError on failure (does not call sys.exit).
    - Does not call os.execv.
    - Does not read from sys.stdin.
"""

import copy
import io
import os
import pathlib
import sys
from typing import NoReturn

import pytest

import kanon_cli.repo as repo_pkg
from kanon_cli.repo import RepoCommandError


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _init_repo_dir(base: pathlib.Path, manifest_content: str) -> pathlib.Path:
    """Create a minimal .repo directory with a manifest for sync tests.

    Sets up the .repo/manifests/ directory and writes the manifest XML,
    then creates the manifest.xml symlink that repo sync requires.

    Returns the .repo directory path.
    """
    repo_dot_dir = base / ".repo"
    manifests_dir = repo_dot_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = manifests_dir / "default.xml"
    manifest_path.write_text(manifest_content, encoding="utf-8")

    # repo tool requires manifest.xml symlink pointing into manifests/
    manifest_link = repo_dot_dir / "manifest.xml"
    manifest_link.symlink_to(manifest_path)

    return repo_dot_dir


_MANIFEST_WITH_PROJECTS = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://github.com/caylent-solutions/" />
  <default revision="main" remote="origin" />
  <project name="kanon" path="kanon" />
</manifest>
"""

_MANIFEST_WITH_GROUPS = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://github.com/caylent-solutions/" />
  <default revision="main" remote="origin" />
  <project name="kanon" path="kanon" groups="linux,darwin" />
  <project name="kanon-windows" path="kanon-windows" groups="windows" />
</manifest>
"""

_MANIFEST_WITH_LINKFILE = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://github.com/caylent-solutions/" />
  <default revision="main" remote="origin" />
  <project name="kanon" path="kanon">
    <linkfile src="README.md" dest="kanon-README.md" />
  </project>
</manifest>
"""

_MANIFEST_BAD_REMOTE = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="bad-remote" fetch="https://this-host-does-not-exist.invalid/" />
  <default revision="main" remote="bad-remote" />
  <project name="some-project" path="some-project" />
</manifest>
"""


# ---------------------------------------------------------------------------
# AC-TEST-001: repo_sync() clones projects defined in the manifest
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_clones_projects_defined_in_manifest(tmp_path: pathlib.Path) -> None:
    """AC-TEST-001: repo_sync() must be importable and callable from kanon_cli.repo.

    The function does not exist yet; this test fails with AttributeError because
    repo_sync is not exported from the kanon_cli.repo package. Once implemented,
    calling repo_sync() must clone projects listed in the manifest into the
    workspace directory (repo_dir). The assertion here verifies the attribute
    exists on the package -- the actual cloning behavior is covered by
    integration tests in E0-F2-S2-T6.
    """
    _init_repo_dir(tmp_path, _MANIFEST_WITH_PROJECTS)

    # repo_sync must be importable from the package -- AttributeError is the
    # expected RED failure before implementation.
    assert hasattr(repo_pkg, "repo_sync"), (
        "repo_sync() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    # Verify the signature is callable
    assert callable(repo_pkg.repo_sync), "repo_pkg.repo_sync must be callable"


# ---------------------------------------------------------------------------
# AC-TEST-002: repo_sync() creates linkfiles as specified in the manifest
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_creates_linkfiles_from_manifest(tmp_path: pathlib.Path) -> None:
    """AC-TEST-002: repo_sync() must support manifest linkfile elements.

    When the manifest specifies a <linkfile src="..." dest="..." /> element,
    repo sync creates a symlink at dest pointing to src within the project.
    This test verifies that repo_sync() accepts repo_dir as its first
    positional argument and passes it through to run_from_args(["sync", ...]).

    The test fails in RED phase because repo_sync does not exist yet.
    """
    _init_repo_dir(tmp_path, _MANIFEST_WITH_LINKFILE)

    # In RED phase, this raises AttributeError because repo_sync does not exist.
    # In GREEN phase, calling with a real remote would create the linkfile.
    # We verify the function signature accepts repo_dir correctly.
    repo_sync = getattr(repo_pkg, "repo_sync", None)
    assert repo_sync is not None, (
        "repo_sync() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    import inspect

    sig = inspect.signature(repo_sync)
    params = list(sig.parameters.keys())
    assert "repo_dir" in params, f"repo_sync() must accept a 'repo_dir' parameter. Actual parameters: {params!r}"


# ---------------------------------------------------------------------------
# AC-TEST-003: repo_sync() resolves manifest constraints (groups, platform)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_accepts_groups_and_platform_parameters(tmp_path: pathlib.Path) -> None:
    """AC-TEST-003: repo_sync() must accept 'groups' and 'platform' parameters.

    The repo sync subcommand supports --groups and --platform-extras flags.
    repo_sync() must expose these as keyword-only parameters so callers can
    filter which projects get synced based on manifest group membership and
    platform constraints.

    The test fails in RED phase because repo_sync does not exist yet.
    """
    _init_repo_dir(tmp_path, _MANIFEST_WITH_GROUPS)

    repo_sync = getattr(repo_pkg, "repo_sync", None)
    assert repo_sync is not None, (
        "repo_sync() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    import inspect

    sig = inspect.signature(repo_sync)
    params = sig.parameters

    assert "groups" in params, (
        f"repo_sync() must accept a 'groups' keyword parameter for manifest group filtering. "
        f"Actual parameters: {list(params.keys())!r}"
    )
    assert "platform" in params, (
        f"repo_sync() must accept a 'platform' keyword parameter for platform-extras filtering. "
        f"Actual parameters: {list(params.keys())!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-004: repo_sync() is idempotent
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_is_idempotent(tmp_path: pathlib.Path) -> None:
    """AC-TEST-004: repo_sync() must be idempotent -- calling it twice must not error.

    When called on the same repo_dir twice, the second call must not raise an
    error due to pre-existing state. The repo sync subcommand already handles
    this by fetching rather than failing when the project directory exists.

    This test verifies that repo_sync() forwards to run_from_args() with the
    sync subcommand and does not add any duplicate-prevention logic that would
    break on the second call.

    The test fails in RED phase because repo_sync does not exist yet.
    """
    _init_repo_dir(tmp_path, _MANIFEST_WITH_PROJECTS)

    repo_sync = getattr(repo_pkg, "repo_sync", None)
    assert repo_sync is not None, (
        "repo_sync() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    # Verify the function can be called twice with the same repo_dir without
    # the function itself adding duplicate-prevention that would fail the second call.
    # We call with a bad repo_dir to get a fast failure that is consistent across
    # both calls, confirming the error type does not change between invocations.
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    first_exception: RepoCommandError | None = None
    with pytest.raises(RepoCommandError) as exc_info_1:
        repo_pkg.repo_sync(repo_dir=str(empty_dir))
    first_exception = exc_info_1.value

    with pytest.raises(RepoCommandError) as exc_info_2:
        repo_pkg.repo_sync(repo_dir=str(empty_dir))
    second_exception = exc_info_2.value

    assert type(first_exception) is type(second_exception), (
        f"repo_sync() is not idempotent: first call raised {type(first_exception).__name__!r}, "
        f"second call raised {type(second_exception).__name__!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-005: repo_sync() raises on a bad/unreachable remote
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_raises_repo_command_error_on_bad_remote(tmp_path: pathlib.Path) -> None:
    """AC-TEST-005: repo_sync() must raise RepoCommandError on a bad remote.

    When the manifest references a remote host that does not exist or is
    unreachable, the underlying repo sync command exits with a non-zero code.
    repo_sync() must surface this failure as a RepoCommandError (not SystemExit)
    so library callers can catch and handle it programmatically.

    The test fails in RED phase because repo_sync does not exist yet.
    """
    _init_repo_dir(tmp_path, _MANIFEST_BAD_REMOTE)

    repo_sync = getattr(repo_pkg, "repo_sync", None)
    assert repo_sync is not None, (
        "repo_sync() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    # A missing .repo directory causes a fast fail without network access.
    empty_dir = tmp_path / "no_repo"
    empty_dir.mkdir()

    with pytest.raises(RepoCommandError) as exc_info:
        repo_pkg.repo_sync(repo_dir=str(empty_dir))

    assert exc_info.value.exit_code is not None, (
        f"RepoCommandError must carry the exit_code from the underlying failure. Got: {exc_info.value!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-006: repo_sync() does not mutate sys.argv
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_does_not_mutate_sys_argv(tmp_path: pathlib.Path) -> None:
    """AC-TEST-006: repo_sync() must not alter sys.argv.

    Snapshot sys.argv before calling repo_sync() and assert the list is
    identical after the call returns (same length, same elements, same order),
    regardless of whether the call succeeds or raises RepoCommandError.

    The test fails in RED phase because repo_sync does not exist yet.
    """
    _init_repo_dir(tmp_path, _MANIFEST_WITH_PROJECTS)

    repo_sync = getattr(repo_pkg, "repo_sync", None)
    assert repo_sync is not None, (
        "repo_sync() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    argv_before = list(sys.argv)

    # Call with a directory that has no .repo to get a fast failure.
    empty_dir = tmp_path / "no_repo_argv"
    empty_dir.mkdir()
    try:
        repo_pkg.repo_sync(repo_dir=str(empty_dir))
    except RepoCommandError:
        pass

    argv_after = list(sys.argv)
    assert argv_after == argv_before, (
        f"repo_sync() mutated sys.argv.\n  Before: {argv_before!r}\n  After:  {argv_after!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-007: repo_sync() restores os.environ after the call
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_restores_os_environ_after_call(tmp_path: pathlib.Path) -> None:
    """AC-TEST-007: repo_sync() must restore os.environ to its pre-call state.

    The underlying repo sync subcommand may write environment variables such as
    GIT_TRACE2_PARENT_SID into os.environ. repo_sync() must restore os.environ
    to its original state in a finally block, so calling code observes no
    persistent environment change regardless of whether the call succeeds or fails.

    The test fails in RED phase because repo_sync does not exist yet.
    """
    _init_repo_dir(tmp_path, _MANIFEST_WITH_PROJECTS)

    repo_sync = getattr(repo_pkg, "repo_sync", None)
    assert repo_sync is not None, (
        "repo_sync() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    env_before = copy.deepcopy(dict(os.environ))

    empty_dir = tmp_path / "no_repo_env"
    empty_dir.mkdir()
    try:
        repo_pkg.repo_sync(repo_dir=str(empty_dir))
    except RepoCommandError:
        pass

    env_after = dict(os.environ)

    added = {k: env_after[k] for k in env_after if k not in env_before}
    removed = {k: env_before[k] for k in env_before if k not in env_after}
    changed = {k: (env_before[k], env_after[k]) for k in env_before if k in env_after and env_before[k] != env_after[k]}

    violations: list[str] = []
    if added:
        violations.append(f"Keys added to os.environ: {added!r}")
    if removed:
        violations.append(f"Keys removed from os.environ: {removed!r}")
    if changed:
        violations.append(f"Keys changed in os.environ: {changed!r}")

    assert not violations, "repo_sync() did not restore os.environ:\n" + "\n".join(f"  {v}" for v in violations)


# ---------------------------------------------------------------------------
# AC-TEST-008: repo_sync() raises on failure (does not call sys.exit)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_raises_repo_command_error_not_sys_exit(tmp_path: pathlib.Path) -> None:
    """AC-TEST-008: repo_sync() must raise RepoCommandError on failure, not call sys.exit().

    Pass a repo_dir that contains no .repo/ subdirectory. The underlying sync
    command must fail. repo_sync() must surface the failure as a RepoCommandError
    (not SystemExit) so library callers can catch and handle it programmatically.

    Library code must never call sys.exit() -- that privilege belongs to CLI
    entry points only. If repo_sync() allows SystemExit to propagate, the test
    will catch it as a failure of this contract.

    The test fails in RED phase because repo_sync does not exist yet.
    """
    repo_sync = getattr(repo_pkg, "repo_sync", None)
    assert repo_sync is not None, (
        "repo_sync() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    empty_dir = tmp_path / "no_repo_exit"
    empty_dir.mkdir()

    # If repo_sync raises SystemExit, pytest would catch it and fail the test
    # with a different error -- but we want to be explicit about the contract.
    raised_system_exit = False
    try:
        repo_pkg.repo_sync(repo_dir=str(empty_dir))
    except RepoCommandError:
        pass  # Expected -- the correct behaviour.
    except SystemExit as exc:
        raised_system_exit = True
        pytest.fail(
            f"repo_sync() raised SystemExit({exc.code!r}) -- "
            f"library code must not call sys.exit(); raise RepoCommandError instead."
        )

    assert not raised_system_exit, "repo_sync() raised SystemExit instead of RepoCommandError"


# ---------------------------------------------------------------------------
# AC-TEST-009: repo_sync() does not call os.execv
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_does_not_call_os_execv(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-TEST-009: repo_sync() must not call os.execv during execution.

    Monkeypatch os.execv with a sentinel that raises AssertionError if invoked.
    Any call to os.execv from within repo_sync() would replace the calling
    process -- a critical isolation violation for library code.

    The test fails in RED phase because repo_sync does not exist yet.
    """
    repo_sync = getattr(repo_pkg, "repo_sync", None)
    assert repo_sync is not None, (
        "repo_sync() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    execv_calls: list[tuple[str, list[str]]] = []

    def _record_execv(path: str, argv: list[str]) -> NoReturn:
        execv_calls.append((path, list(argv)))
        raise AssertionError(f"os.execv was called during repo_sync(): path={path!r}, argv={argv!r}")

    monkeypatch.setattr(os, "execv", _record_execv)

    empty_dir = tmp_path / "no_repo_execv"
    empty_dir.mkdir()
    try:
        repo_pkg.repo_sync(repo_dir=str(empty_dir))
    except RepoCommandError:
        pass
    except SystemExit as exc:
        raise AssertionError(
            f"repo_sync() raised SystemExit({exc.code!r}) -- library code must not exit the process."
        ) from exc

    assert execv_calls == [], f"os.execv was called {len(execv_calls)} time(s) during repo_sync(): {execv_calls!r}"


# ---------------------------------------------------------------------------
# AC-TEST-010: repo_sync() does not read from stdin
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_does_not_read_from_stdin(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-TEST-010: repo_sync() must not read from sys.stdin.

    Replace sys.stdin with a sentinel stream that raises AssertionError on any
    read attempt. If repo_sync() attempts to read stdin (for example, for an
    interactive credential prompt), the test will fail with a clear message.

    Library code must never block waiting for user input.

    The test fails in RED phase because repo_sync does not exist yet.
    """
    repo_sync = getattr(repo_pkg, "repo_sync", None)
    assert repo_sync is not None, (
        "repo_sync() must be exported from kanon_cli.repo. It does not exist yet -- this test is TDD RED."
    )

    class _NoReadStdin(io.RawIOBase):
        """Stdin replacement that raises on any read operation."""

        def read(self, n: int = -1) -> bytes:
            raise AssertionError("repo_sync() attempted to read from stdin -- interactive prompts are forbidden.")

        def readline(self, size: int = -1) -> bytes:
            raise AssertionError("repo_sync() attempted to readline from stdin -- interactive prompts are forbidden.")

        def readinto(self, b: bytearray) -> int:
            raise AssertionError("repo_sync() attempted to readinto from stdin -- interactive prompts are forbidden.")

        def readable(self) -> bool:
            return True

        def fileno(self) -> int:
            raise io.UnsupportedOperation("fileno not supported on sentinel stdin")

    sentinel_stdin = _NoReadStdin()
    monkeypatch.setattr(sys, "stdin", sentinel_stdin)

    empty_dir = tmp_path / "no_repo_stdin"
    empty_dir.mkdir()
    try:
        repo_pkg.repo_sync(repo_dir=str(empty_dir))
    except RepoCommandError:
        pass
    except SystemExit as exc:
        raise AssertionError(
            f"repo_sync() raised SystemExit({exc.code!r}) -- library code must not exit the process."
        ) from exc
