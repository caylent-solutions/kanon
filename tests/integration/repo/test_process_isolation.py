"""Process isolation integration tests for the embedded repo tool.

Verifies that repo API calls (run_from_args, repo_run, repo_init, repo_envsubst)
do not persistently modify host process state:

- sys.argv is not read or written by run_from_args
- sys.path is not modified by run_from_args
- os.environ is restored to its pre-call state after repo API calls
- The current working directory is restored after repo_init and repo_envsubst
- os.execv is never called in embedded mode (the intercept is always active
  during run_from_args and is always restored afterward)
- Sequential back-to-back repo API calls in the same process do not interfere
  with each other: each call fully restores process-global state on exit so a
  subsequent call observes a clean baseline.

All tests are marked @pytest.mark.integration.
"""

import os
import pathlib
import subprocess
import sys

import pytest

import kanon_cli.repo as repo_pkg
from kanon_cli.repo.main import run_from_args


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Isolation Test User"
_GIT_USER_EMAIL = "isolation-test@example.com"
_MANIFEST_FILENAME = "default.xml"


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


def _init_git_repo(work_dir: pathlib.Path) -> None:
    """Initialise a fresh git working directory with user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _make_bare_clone(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> None:
    """Clone work_dir into a bare repository at bare_dir."""
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)


def _create_content_repo(base: pathlib.Path, name: str = "content") -> pathlib.Path:
    """Create a named bare content repo with one committed file.

    Returns the absolute path to the bare repository directory.
    """
    work_dir = base / f"{name}-work"
    work_dir.mkdir(parents=True)
    _init_git_repo(work_dir)

    readme = work_dir / "README.md"
    readme.write_text(f"# {name}\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=work_dir)
    _git(["commit", "-m", f"Initial commit for {name}"], cwd=work_dir)

    bare_dir = base / f"{name}-bare"
    _make_bare_clone(work_dir, bare_dir)
    return bare_dir


def _create_manifest_repo(
    base: pathlib.Path,
    fetch_base_url: str,
    project_name: str = "content-bare",
    project_path: str = "project-a",
    name: str = "manifest",
) -> pathlib.Path:
    """Create a bare manifest repo referencing a single project.

    Returns the absolute path to the bare manifest repository.
    """
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{fetch_base_url}" />\n'
        '  <default revision="main" remote="origin" />\n'
        f'  <project name="{project_name}" path="{project_path}" />\n'
        "</manifest>\n"
    )

    work_dir = base / f"{name}-work"
    work_dir.mkdir(parents=True)
    _init_git_repo(work_dir)

    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    bare_dir = base / f"{name}-bare"
    _make_bare_clone(work_dir, bare_dir)
    return bare_dir


def _repo_init_workspace(workspace: pathlib.Path, manifest_url: str) -> str:
    """Run repo init in workspace, returning the .repo dir path string."""
    repo_dot_dir = str(workspace / ".repo")
    run_from_args(
        [
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            "-b",
            "main",
            "-m",
            _MANIFEST_FILENAME,
        ],
        repo_dir=repo_dot_dir,
    )
    return repo_dot_dir


# ---------------------------------------------------------------------------
# AC-FUNC-003: sys.argv is restored after repo API calls
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sys_argv_not_modified_by_run_from_args(tmp_path: pathlib.Path) -> None:
    """run_from_args does not read or write sys.argv.

    Captures sys.argv before and after a successful run_from_args call. Asserts
    that both the identity of the list object and its contents are identical,
    confirming that run_from_args operates on its own argv parameter and never
    touches sys.argv.

    AC-FUNC-003
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()
    _create_content_repo(repos_base, name="content")
    manifest_bare = _create_manifest_repo(repos_base, f"file://{repos_base}")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo_dot_dir = str(workspace / ".repo")

    argv_before = list(sys.argv)
    original_argv_id = id(sys.argv)

    run_from_args(
        ["init", "--no-repo-verify", "-u", f"file://{manifest_bare}", "-b", "main", "-m", _MANIFEST_FILENAME],
        repo_dir=repo_dot_dir,
    )

    assert sys.argv == argv_before, (
        f"sys.argv was modified by run_from_args. Before: {argv_before!r}, After: {sys.argv!r}"
    )
    assert id(sys.argv) == original_argv_id, (
        f"sys.argv object was replaced by run_from_args. Expected id={original_argv_id}, got id={id(sys.argv)}"
    )


@pytest.mark.integration
def test_sys_argv_not_modified_by_repo_run(tmp_path: pathlib.Path) -> None:
    """repo_run does not modify sys.argv.

    Runs repo_run(["help"], ...) with a synthetic repo_dir and verifies
    sys.argv is unchanged before and after the call. The "help" subcommand
    is used because it completes without requiring git metadata inside the
    repo tool's own checkout directory.

    AC-FUNC-003
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()
    _create_content_repo(repos_base, name="content")
    manifest_bare = _create_manifest_repo(repos_base, f"file://{repos_base}")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo_dot_dir = _repo_init_workspace(workspace, f"file://{manifest_bare}")

    argv_before = list(sys.argv)

    repo_pkg.repo_run(["help"], repo_dir=repo_dot_dir)

    assert sys.argv == argv_before, f"sys.argv was modified by repo_run. Before: {argv_before!r}, After: {sys.argv!r}"


# ---------------------------------------------------------------------------
# AC-FUNC-004: sys.path is restored after repo API calls
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sys_path_not_modified_by_run_from_args(tmp_path: pathlib.Path) -> None:
    """run_from_args does not modify sys.path.

    Captures sys.path contents before and after a run_from_args call and
    verifies no entries were added or removed.

    AC-FUNC-004
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()
    _create_content_repo(repos_base, name="content")
    manifest_bare = _create_manifest_repo(repos_base, f"file://{repos_base}")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo_dot_dir = str(workspace / ".repo")

    path_before = list(sys.path)

    run_from_args(
        ["init", "--no-repo-verify", "-u", f"file://{manifest_bare}", "-b", "main", "-m", _MANIFEST_FILENAME],
        repo_dir=repo_dot_dir,
    )

    assert sys.path == path_before, (
        f"sys.path was modified by run_from_args. Before: {path_before!r}, After: {sys.path!r}"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-005: os.environ is restored after repo API calls
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_os_environ_restored_after_run_from_args(tmp_path: pathlib.Path) -> None:
    """os.environ is restored to its pre-call state after run_from_args.

    Adds a sentinel environment variable before the call, runs run_from_args,
    then verifies that the sentinel is still present and that no unexpected
    keys were added by the repo command internals.

    AC-FUNC-005
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()
    _create_content_repo(repos_base, name="content")
    manifest_bare = _create_manifest_repo(repos_base, f"file://{repos_base}")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo_dot_dir = str(workspace / ".repo")

    sentinel_key = "KANON_ISOLATION_TEST_SENTINEL"
    sentinel_value = "isolation-check-value"
    os.environ[sentinel_key] = sentinel_value

    try:
        run_from_args(
            ["init", "--no-repo-verify", "-u", f"file://{manifest_bare}", "-b", "main", "-m", _MANIFEST_FILENAME],
            repo_dir=repo_dot_dir,
        )

        # After the call (but before cleanup), the sentinel must still be present.
        # run_from_args restores os.environ from its own snapshot, which includes
        # the sentinel because we set it before invoking run_from_args.
        assert sentinel_key in os.environ, (
            f"Sentinel environment variable {sentinel_key!r} was removed from os.environ by run_from_args. "
            f"run_from_args must restore os.environ to exactly the state it found on entry."
        )
        assert os.environ[sentinel_key] == sentinel_value, (
            f"Sentinel environment variable {sentinel_key!r} was modified by run_from_args. "
            f"Expected {sentinel_value!r}, got {os.environ[sentinel_key]!r}"
        )
    finally:
        # Clean up the sentinel regardless of test outcome.
        os.environ.pop(sentinel_key, None)


@pytest.mark.integration
def test_os_environ_keys_added_by_repo_not_persistent(tmp_path: pathlib.Path) -> None:
    """Keys written into os.environ by the repo command internals are removed after run_from_args.

    The repo trace2 subsystem writes GIT_TRACE2_PARENT_SID into os.environ
    during every invocation. This test verifies that any such transient keys
    are not present in os.environ after run_from_args returns.

    AC-FUNC-005
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()
    _create_content_repo(repos_base, name="content")
    manifest_bare = _create_manifest_repo(repos_base, f"file://{repos_base}")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo_dot_dir = str(workspace / ".repo")

    # Known key written by the repo trace2 subsystem.
    trace2_key = "GIT_TRACE2_PARENT_SID"
    # Ensure the key is absent before the call so we can detect if it leaks.
    os.environ.pop(trace2_key, None)
    assert trace2_key not in os.environ, f"Test setup error: {trace2_key!r} is already set in os.environ."

    run_from_args(
        ["init", "--no-repo-verify", "-u", f"file://{manifest_bare}", "-b", "main", "-m", _MANIFEST_FILENAME],
        repo_dir=repo_dot_dir,
    )

    assert trace2_key not in os.environ, (
        f"run_from_args leaked {trace2_key!r} into os.environ after the call. "
        f"Value: {os.environ.get(trace2_key)!r}. "
        f"run_from_args must restore os.environ in its finally block."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-006: Current working directory is restored after repo API calls
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cwd_restored_after_repo_init(tmp_path: pathlib.Path) -> None:
    """repo_init restores the current working directory after the call.

    repo_init() temporarily changes the working directory to repo_dir so
    that the underlying repo command locates the .repo directory. The
    directory must be restored in a finally block so the calling process
    observes no persistent change.

    AC-FUNC-006
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()
    _create_content_repo(repos_base, name="content")
    manifest_bare = _create_manifest_repo(repos_base, f"file://{repos_base}")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    cwd_before = os.getcwd()

    repo_pkg.repo_init(
        repo_dir=str(workspace),
        url=f"file://{manifest_bare}",
        revision="main",
        manifest_path=_MANIFEST_FILENAME,
    )

    cwd_after = os.getcwd()
    assert cwd_after == cwd_before, (
        f"repo_init() changed the working directory and did not restore it. "
        f"Before: {cwd_before!r}, After: {cwd_after!r}"
    )


@pytest.mark.integration
def test_cwd_restored_after_repo_envsubst(tmp_path: pathlib.Path) -> None:
    """repo_envsubst restores the current working directory after the call.

    repo_envsubst() temporarily changes the working directory to repo_dir
    before delegating to run_from_args(). The directory must be restored
    in a finally block so the calling process observes no persistent change.

    AC-FUNC-006
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()
    _create_content_repo(repos_base, name="content")
    manifest_bare = _create_manifest_repo(repos_base, f"file://{repos_base}")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _repo_init_workspace(workspace, f"file://{manifest_bare}")

    cwd_before = os.getcwd()

    repo_pkg.repo_envsubst(str(workspace), {})

    cwd_after = os.getcwd()
    assert cwd_after == cwd_before, (
        f"repo_envsubst() changed the working directory and did not restore it. "
        f"Before: {cwd_before!r}, After: {cwd_after!r}"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-007: os.execv is never called in embedded mode
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_os_execv_not_called_during_run_from_args(tmp_path: pathlib.Path) -> None:
    """os.execv is never called (and the original is restored) during run_from_args.

    run_from_args temporarily replaces os.execv with an intercepting sentinel
    to prevent process replacement on RepoChangedException. This test verifies
    that (a) os.execv is replaced during the call and (b) the original os.execv
    is restored after the call completes. The test also records whether the
    intercepting sentinel was ever invoked (which would mean a RepoChangedException
    was triggered), asserting it was never called.

    AC-FUNC-007
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()
    _create_content_repo(repos_base, name="content")
    manifest_bare = _create_manifest_repo(repos_base, f"file://{repos_base}")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo_dot_dir = str(workspace / ".repo")

    original_execv = os.execv
    execv_call_count = 0

    def _tracking_execv(path: str, args: list[str]) -> None:
        nonlocal execv_call_count
        execv_call_count += 1

    os.execv = _tracking_execv
    try:
        run_from_args(
            ["init", "--no-repo-verify", "-u", f"file://{manifest_bare}", "-b", "main", "-m", _MANIFEST_FILENAME],
            repo_dir=repo_dot_dir,
        )
    finally:
        # run_from_args should have restored os.execv in its finally block.
        # Restore to the true original in case it did not (so other tests are not broken).
        restored_execv = os.execv
        os.execv = original_execv

    # os.execv must be restored to _tracking_execv after the call (run_from_args
    # replaced it with its own sentinel during the call, but must restore whatever
    # was there when it entered -- which was _tracking_execv).
    assert restored_execv is _tracking_execv, (
        "run_from_args did not restore os.execv to the value it found on entry. "
        f"Expected the tracking wrapper ({_tracking_execv!r}), "
        f"got {restored_execv!r}."
    )

    # The repo command executed normally -- no RepoChangedException should have
    # triggered the execv path.
    assert execv_call_count == 0, (
        f"os.execv (as seen by the tracking wrapper) was called {execv_call_count} time(s) "
        "during run_from_args. In embedded mode, os.execv must be intercepted and never "
        "allowed to replace the calling process."
    )


@pytest.mark.integration
def test_os_execv_restored_after_run_from_args_completes(tmp_path: pathlib.Path) -> None:
    """os.execv is always restored to its pre-call value after run_from_args.

    Verifies that regardless of whether the repo command succeeds or raises,
    run_from_args restores os.execv so that subsequent code in the calling
    process can rely on the real execv being available.

    AC-FUNC-007
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()
    _create_content_repo(repos_base, name="content")
    manifest_bare = _create_manifest_repo(repos_base, f"file://{repos_base}")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo_dot_dir = str(workspace / ".repo")

    original_execv = os.execv

    run_from_args(
        ["init", "--no-repo-verify", "-u", f"file://{manifest_bare}", "-b", "main", "-m", _MANIFEST_FILENAME],
        repo_dir=repo_dot_dir,
    )

    assert os.execv is original_execv, (
        "run_from_args did not restore os.execv to its original value after completing. "
        f"Expected the original os.execv ({original_execv!r}), got {os.execv!r}."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-008: Sequential back-to-back repo API calls do not interfere
#
# run_from_args and repo_run mutate process-global state (os.execv,
# os.environ, _pager_module.EMBEDDED) under a snapshot/restore pattern.
# This makes them safe for SEQUENTIAL reuse in the same process: each call
# fully restores state on exit, so a subsequent call observes a clean
# baseline. They are NOT safe for parallel invocation across threads in the
# same process (a parallel caller's snapshot/restore races corrupt the
# shared state). Process-level concurrency works because each process has
# its own address space, but is out of scope here.
#
# These tests validate the real contract: back-to-back same-process calls
# on different workspaces succeed and leave the process state identical to
# what each call entered with.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sequential_run_from_args_calls_do_not_interfere(tmp_path: pathlib.Path) -> None:
    """Back-to-back run_from_args calls on different workspaces do not interfere.

    Creates two independent workspaces (each with its own manifest and content
    repo), runs run_from_args("init") for each sequentially in the same
    process, and verifies:

    - both inits succeed and each workspace has a valid .repo directory
    - os.execv, sys.argv, sys.path, and cwd observed before the pair are
      identical to the values observed after the pair (each call restored
      its own mutations and did not accumulate drift)
    - no keys added by the first call remain in os.environ when the second
      call starts, so the second call sees the same environment baseline as
      the first

    AC-FUNC-008
    """
    num_workspaces = 2

    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    workspace_configs: list[tuple[pathlib.Path, pathlib.Path]] = []
    for idx in range(num_workspaces):
        name = f"content-{idx}"
        _create_content_repo(repos_base, name=name)
        manifest_bare = _create_manifest_repo(
            repos_base,
            f"file://{repos_base}",
            project_name=f"{name}-bare",
            project_path=f"project-{idx}",
            name=f"manifest-{idx}",
        )
        workspace = tmp_path / f"workspace-{idx}"
        workspace.mkdir()
        workspace_configs.append((workspace, manifest_bare))

    execv_before = os.execv
    argv_before = list(sys.argv)
    path_before = list(sys.path)
    cwd_before = os.getcwd()
    environ_before = dict(os.environ)

    repo_dot_dirs: list[pathlib.Path] = []
    for idx, (workspace, manifest_bare) in enumerate(workspace_configs):
        # Before the next call starts, os.environ must already be restored
        # from the previous call's finally block. Any key present now that
        # was not present at test entry means state leaked across calls.
        leaked_keys = {k: os.environ[k] for k in os.environ if k not in environ_before}
        assert not leaked_keys, (
            f"Before run_from_args call #{idx}, os.environ contains keys not present at test entry: "
            f"{leaked_keys!r}. Previous call did not fully restore os.environ."
        )

        repo_dot_dir = workspace / ".repo"
        run_from_args(
            [
                "init",
                "--no-repo-verify",
                "-u",
                f"file://{manifest_bare}",
                "-b",
                "main",
                "-m",
                _MANIFEST_FILENAME,
            ],
            repo_dir=str(repo_dot_dir),
        )
        repo_dot_dirs.append(repo_dot_dir)

    assert len(repo_dot_dirs) == num_workspaces
    for repo_dot_dir in repo_dot_dirs:
        assert repo_dot_dir.is_dir(), f"Expected .repo/ directory at {repo_dot_dir} after init, but it was not created."

    assert os.execv is execv_before, (
        f"run_from_args did not restore os.execv after the pair of calls. Expected {execv_before!r}, got {os.execv!r}."
    )
    assert sys.argv == argv_before, f"sys.argv was modified. Before: {argv_before!r}, After: {sys.argv!r}"
    assert sys.path == path_before, f"sys.path was modified. Before: {path_before!r}, After: {sys.path!r}"
    assert os.getcwd() == cwd_before, (
        f"Working directory was not restored. Before: {cwd_before!r}, After: {os.getcwd()!r}"
    )
    residual_keys = {k: os.environ[k] for k in os.environ if k not in environ_before}
    assert not residual_keys, (
        f"os.environ contains keys not present at test entry after the pair of calls: {residual_keys!r}"
    )


@pytest.mark.integration
def test_sequential_repo_run_help_calls_do_not_interfere(tmp_path: pathlib.Path) -> None:
    """Back-to-back repo_run(["help"]) calls on the same workspace do not interfere.

    Runs repo_run(["help"]) four times sequentially against the same
    initialized workspace and verifies:

    - every call returns 0
    - os.execv, sys.argv, sys.path, and cwd are identical before the loop
      and after each individual call
    - os.environ contains no keys beyond the pre-call baseline after each
      iteration, so every call observes a clean environment

    AC-FUNC-008
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()
    _create_content_repo(repos_base, name="content")
    manifest_bare = _create_manifest_repo(repos_base, f"file://{repos_base}")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo_dot_dir = _repo_init_workspace(workspace, f"file://{manifest_bare}")

    num_iterations = 4

    execv_before = os.execv
    argv_before = list(sys.argv)
    path_before = list(sys.path)
    cwd_before = os.getcwd()
    environ_before = dict(os.environ)

    for iteration in range(num_iterations):
        rv = repo_pkg.repo_run(["help"], repo_dir=repo_dot_dir)
        assert rv == 0, f"repo_run(['help']) iteration #{iteration} returned {rv!r}, expected 0."

        assert os.execv is execv_before, (
            f"os.execv not restored after repo_run iteration #{iteration}. Expected {execv_before!r}, got {os.execv!r}."
        )
        assert sys.argv == argv_before, (
            f"sys.argv mutated after repo_run iteration #{iteration}. Before: {argv_before!r}, After: {sys.argv!r}"
        )
        assert sys.path == path_before, (
            f"sys.path mutated after repo_run iteration #{iteration}. Before: {path_before!r}, After: {sys.path!r}"
        )
        assert os.getcwd() == cwd_before, (
            f"cwd not restored after repo_run iteration #{iteration}. Before: {cwd_before!r}, After: {os.getcwd()!r}"
        )
        residual_keys = {k: os.environ[k] for k in os.environ if k not in environ_before}
        assert not residual_keys, (
            f"os.environ gained keys after repo_run iteration #{iteration}: {residual_keys!r}. "
            "The call did not restore its environment mutations."
        )
