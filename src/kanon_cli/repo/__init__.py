"""Kanon repo subsystem -- manifest-driven sync of git projects.

Public API
----------
EMBEDDED
    Boolean flag that is True while run_from_args() is executing, and False
    at all other times. When True, pager.py skips os.execvp() so the calling
    process is not replaced by the pager, and forall.py saves and restores
    signal handlers around command execution.

run_from_args(argv, *, repo_dir)
    Run a repo subcommand from Python code without persistently modifying
    global process state (sys.argv, os.execv, os.environ). The function
    temporarily replaces os.execv and may temporarily write to os.environ
    during execution, but restores both in a finally block. See
    main.run_from_args for the full contract.

repo_init(repo_dir, url, revision, manifest_path, repo_rev)
    Initialize a repo client checkout in repo_dir. Temporarily changes the
    working directory to repo_dir, delegates to run_from_args() with
    ["--color=never", "init", ...] arguments, and restores the working
    directory in a finally block. Raises RepoCommandError on failure.

repo_envsubst(repo_dir, env_vars)
    Perform environment variable substitution in manifest XML files under
    <repo_dir>/.repo/manifests/. Temporarily injects env_vars into os.environ,
    delegates to run_from_args() with ["envsubst"], and restores os.environ
    in a finally block (even on failure). Raises RepoCommandError on failure.

repo_run(argv, *, repo_dir)
    General-purpose dispatcher that accepts an arbitrary argv list and passes
    it to run_from_args(). Returns the exit code (0 for success). Raises
    RepoCommandError on failure or invalid subcommands. Does not mutate
    sys.argv, os.environ, or signal handlers.

repo_sync(repo_dir, *, groups, platform, jobs)
    Clone and fetch all projects defined in the manifest. Delegates to
    run_from_args() with ["sync", ...] arguments. Raises RepoCommandError if
    .repo/ does not exist in repo_dir or if the underlying command fails.
    Does not mutate sys.argv, os.environ, or signal handlers.

RepoCommandError
    Exception raised when the underlying repo command exits with an error.
    Carries the integer exit_code from the original SystemExit.
"""

import os

from kanon_cli.repo.main import RepoCommandError
from kanon_cli.repo.main import run_from_args
from kanon_cli.repo import pager as _pager_mod

# EMBEDDED is the canonical package-level view of the embedded mode flag.
# It mirrors pager.EMBEDDED so callers can inspect it as kanon_cli.repo.EMBEDDED.
# run_from_args() writes pager.EMBEDDED directly; this property-like alias is
# implemented as a module attribute backed by the pager module's flag.


def __getattr__(name: str) -> object:
    if name == "EMBEDDED":
        return _pager_mod.EMBEDDED
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def repo_init(
    repo_dir: str,
    url: str,
    revision: str,
    manifest_path: str,
    repo_rev: str = "",
) -> None:
    """Initialize a repo client checkout in repo_dir.

    Runs ``repo init`` inside repo_dir to configure the manifest URL,
    branch, and manifest file path. Creates the .repo/ subdirectory in
    repo_dir as a side effect of the underlying ``repo init`` command.

    The function temporarily changes the working directory to repo_dir
    before invoking run_from_args() and restores the original working
    directory in a finally block so the calling process observes no
    persistent directory change regardless of whether the call succeeds
    or fails.

    Args:
        repo_dir: Path to the directory in which ``repo init`` should be
            run. The .repo/ subdirectory will be created inside this directory.
        url: Manifest repository URL (passed to ``repo init -u``).
        revision: Branch or tag to use from the manifest repository
            (passed to ``repo init -b``).
        manifest_path: Relative path to the manifest XML file within the
            manifest repository (passed to ``repo init -m``).
        repo_rev: Optional repo tool version tag (passed to
            ``repo init --repo-rev`` when non-empty).

    Returns:
        None on success (repo init exits with code 0).

    Raises:
        RepoCommandError: When the underlying ``repo init`` command exits
            with a non-zero exit code. The exit_code attribute of the
            exception carries the integer exit code from the underlying
            failure.
    """
    repo_dot_dir = os.path.join(repo_dir, ".repo")
    argv = [
        "--color=never",
        "init",
        "--no-repo-verify",
        "-u",
        url,
        "-b",
        revision,
        "-m",
        manifest_path,
    ]
    if repo_rev:
        argv.extend(["--repo-rev", repo_rev])

    cwd_snapshot = os.getcwd()
    try:
        os.chdir(repo_dir)
        run_from_args(argv, repo_dir=repo_dot_dir)
    finally:
        os.chdir(cwd_snapshot)


def repo_envsubst(repo_dir: str, env_vars: dict[str, str]) -> None:
    """Perform environment variable substitution in manifest XML files.

    Substitutes ${VAR} placeholders in all XML files under
    <repo_dir>/.repo/manifests/ using the supplied env_vars dict. The
    substitution is delegated to the ``envsubst`` repo subcommand.

    Fails fast if repo_dir does not contain a .repo/ subdirectory -- this
    indicates repo init has not been run in repo_dir and the envsubst command
    cannot locate any manifest XML files to process.

    The function temporarily injects env_vars into os.environ before invoking
    run_from_args() and restores os.environ to its original state in a finally
    block, so the calling process observes no persistent environment change
    regardless of whether the call succeeds or fails.

    The function also temporarily changes the working directory to repo_dir so
    that the envsubst subcommand can locate manifest XML files using relative
    paths. The original working directory is restored in a finally block.

    Args:
        repo_dir: Path to the repository root directory that contains the
            .repo/ subdirectory. Must be a directory in which ``repo init``
            has already been run.
        env_vars: Mapping of environment variable names to values to inject
            before running ``repo envsubst``. These variables are removed from
            os.environ (or restored to their pre-call values) after the call
            completes.

    Returns:
        None on success (repo envsubst exits with code 0).

    Raises:
        RepoCommandError: When repo_dir does not contain a .repo/ subdirectory,
            indicating that repo init has not been run in that directory.
        RepoCommandError: When the underlying ``repo envsubst`` command exits
            with a non-zero exit code. The exit_code attribute of the exception
            carries the integer exit code from the underlying failure.
    """
    repo_dot_dir = os.path.join(repo_dir, ".repo")
    if not os.path.isdir(repo_dot_dir):
        raise RepoCommandError(
            exit_code=1,
            message=(
                f"repo envsubst requires a repo checkout: {repo_dot_dir!r} does not exist. "
                f"Run 'repo init' in {repo_dir!r} before calling repo_envsubst()."
            ),
        )

    environ_snapshot = dict(os.environ)
    cwd_snapshot = os.getcwd()
    try:
        for key, value in env_vars.items():
            os.environ[key] = value
        os.chdir(repo_dir)
        run_from_args(["envsubst"], repo_dir=repo_dot_dir)
    finally:
        os.chdir(cwd_snapshot)
        keys_to_remove = [k for k in list(os.environ) if k not in environ_snapshot]
        for k in keys_to_remove:
            del os.environ[k]
        for k, v in environ_snapshot.items():
            if os.environ.get(k) != v:
                os.environ[k] = v


def repo_run(argv: list[str], *, repo_dir: str) -> int:
    """Dispatch an arbitrary repo subcommand from Python code.

    A general-purpose dispatcher that accepts an arbitrary argv list and
    passes it directly to run_from_args(). Returns the integer exit code
    from the subcommand. Raises RepoCommandError when the subcommand fails
    or the argv names an invalid subcommand.

    The function does not mutate sys.argv, os.environ, or signal handlers.
    run_from_args() intercepts os.execv and restores os.environ in a finally
    block, so the calling process observes no persistent state change
    regardless of whether the call succeeds or fails.

    Args:
        argv: The repo subcommand and its arguments (e.g., ["version"] or
            ["sync", "--jobs=4"]). Must not include "repo" itself as the
            leading element.
        repo_dir: Path to the .repo directory for this invocation. Passed
            directly to run_from_args(), which uses it to locate the manifest
            without scanning the filesystem.

    Returns:
        0 when the repo command exits with code 0 (success).

    Raises:
        RepoCommandError: When the repo command exits with a non-zero exit
            code or names an invalid subcommand. The exit_code attribute
            contains the integer code from the underlying failure.
    """
    run_from_args(argv, repo_dir=repo_dir)
    return 0


def repo_sync(
    repo_dir: str,
    *,
    groups: list[str] | None = None,
    platform: str | None = None,
    jobs: int | None = None,
) -> None:
    """Clone and fetch all projects defined in the manifest.

    Runs ``repo sync`` inside repo_dir to clone or fetch all projects listed
    in the manifest. The manifest's group and platform constraints are resolved
    based on the state stored by a prior ``repo init`` invocation.

    Fails fast if repo_dir does not contain a .repo/ subdirectory -- this
    indicates repo init has not been run in repo_dir and the sync command
    cannot locate any manifest to process.

    The function does not mutate sys.argv, os.environ, or signal handlers.
    Any environment changes made by the underlying repo command are restored
    in a finally block inside run_from_args(), so the calling process observes
    no persistent state change regardless of whether the call succeeds or fails.

    Args:
        repo_dir: Path to the repository root directory that contains the
            .repo/ subdirectory. Must be a directory in which ``repo init``
            has already been run.
        groups: Optional list of manifest group names to restrict which
            projects are synced. These groups are recorded at ``repo init``
            time and stored in the .repo/ directory; this parameter is
            accepted for API completeness but sync itself uses the stored
            group configuration.
        platform: Optional platform filter (e.g., ``"linux"``, ``"darwin"``,
            ``"all"``, ``"none"``) to restrict which projects are synced.
            Accepted for API completeness; sync uses the stored platform
            configuration from the prior ``repo init`` invocation.
        jobs: Optional number of parallel jobs for network fetching and local
            checkout. When None, the sync command uses the default derived
            from the manifest's ``sync-j`` attribute or the CPU count.

    Returns:
        None on success (repo sync exits with code 0).

    Raises:
        RepoCommandError: When repo_dir does not contain a .repo/ subdirectory,
            indicating that repo init has not been run in that directory.
        RepoCommandError: When the underlying ``repo sync`` command exits with
            a non-zero exit code. The exit_code attribute of the exception
            carries the integer exit code from the underlying failure.
    """
    repo_dot_dir = os.path.join(repo_dir, ".repo")
    if not os.path.isdir(repo_dot_dir):
        raise RepoCommandError(
            exit_code=1,
            message=(
                f"repo sync requires a repo checkout: {repo_dot_dir!r} does not exist. "
                f"Run 'repo init' in {repo_dir!r} before calling repo_sync()."
            ),
        )

    argv: list[str] = ["sync"]
    if jobs is not None:
        argv.append(f"--jobs={jobs}")

    run_from_args(argv, repo_dir=repo_dot_dir)


__all__ = ["EMBEDDED", "RepoCommandError", "repo_envsubst", "repo_init", "repo_run", "repo_sync", "run_from_args"]
