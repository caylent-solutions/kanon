"""Functional tests for the kanon repo CLI subcommands via subprocess.

Exercises the kanon repo subcommand surface by invoking
``kanon repo <subcommand>`` as a subprocess and verifying exit codes,
stdout, and stderr output. All tests run kanon as a subprocess -- no
direct Python API calls.

Tests are decorated with @pytest.mark.functional.
"""

import os
import pathlib
import subprocess
import sys

import pytest

from kanon_cli.constants import SELFUPDATE_EMBEDDED_MESSAGE

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo CLI Test User"
_GIT_USER_EMAIL = "repo-cli-test@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from repo-cli test content"
_ENVSUBST_VAR = "KANON_CLI_TEST_FETCH_URL"

# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def _run_kanon(
    *args: str,
    cwd: pathlib.Path | None = None,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run the kanon CLI via subprocess and return the completed process.

    Executes 'python -m kanon_cli' with the supplied arguments. The
    subprocess inherits the current process environment so uv-installed
    packages are available; extra_env values are merged on top without
    modifying the parent environment.

    Args:
        *args: CLI arguments passed to kanon_cli.
        cwd: Working directory for the subprocess. Defaults to None.
        extra_env: Additional environment variables merged into the
            subprocess environment.

    Returns:
        The CompletedProcess object from subprocess.run (check=False).
    """
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
    )


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit.

    Args:
        args: Git subcommand and arguments (without the 'git' prefix).
        cwd: Working directory for the git command.

    Raises:
        RuntimeError: When the git command exits with a non-zero exit code.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with user config set.

    Args:
        work_dir: The directory to initialise as a git repo.
    """
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into bare_dir and return bare_dir resolved.

    Args:
        work_dir: The source non-bare working directory.
        bare_dir: The destination path for the bare clone.

    Returns:
        The resolved absolute path to the bare clone.
    """
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def _create_bare_content_repo(base: pathlib.Path) -> pathlib.Path:
    """Create a bare git repo containing one committed file.

    Args:
        base: Parent directory under which repos are created.

    Returns:
        The absolute path to the bare content repository.
    """
    work_dir = base / "content-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    readme = work_dir / _CONTENT_FILE_NAME
    readme.write_text(_CONTENT_FILE_TEXT, encoding="utf-8")
    _git(["add", _CONTENT_FILE_NAME], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / "content-bare.git")


def _create_manifest_repo(base: pathlib.Path, fetch_base: str) -> pathlib.Path:
    """Create a bare manifest git repo pointing at a content repo.

    Args:
        base: Parent directory under which repos are created.
        fetch_base: The fetch base URL for the remote element.

    Returns:
        The absolute path to the bare manifest repository.
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{fetch_base}" />\n'
        '  <default revision="main" remote="local" />\n'
        '  <project name="content-bare" path="cli-test-project" />\n'
        "</manifest>\n"
    )
    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / "manifest-bare.git")


def _create_envsubst_manifest_repo(base: pathlib.Path) -> pathlib.Path:
    """Create a bare manifest git repo with an ${ENV_VAR} placeholder.

    The placeholder ${KANON_CLI_TEST_FETCH_URL} is used as the remote
    fetch attribute so that envsubst can substitute it with the real URL.

    Args:
        base: Parent directory under which repos are created.

    Returns:
        The absolute path to the bare manifest repository.
    """
    work_dir = base / "envsubst-manifest-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="${{{_ENVSUBST_VAR}}}" />\n'
        '  <default revision="main" remote="local" />\n'
        '  <project name="content-bare" path="cli-envsubst-project" />\n'
        "</manifest>\n"
    )
    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add envsubst manifest"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / "envsubst-manifest-bare.git")


def _create_minimal_repo_dot_dir(base: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory sufficient for the embedded repo tool.

    The .repo/repo/ git repository must have at least one tagged commit so
    that the embedded tool's subcommands that require a valid repo dir work.
    The .repo/manifests/ directory must contain a valid manifest XML file.

    Args:
        base: The directory in which to create .repo/.

    Returns:
        The path to the created .repo directory.
    """
    repo_dot_dir = base / ".repo"
    manifests_dir = repo_dot_dir / "manifests"
    manifests_dir.mkdir(parents=True)

    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://github.com/caylent-solutions/" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    (manifests_dir / _MANIFEST_FILENAME).write_text(manifest_content, encoding="utf-8")
    (repo_dot_dir / "manifest.xml").symlink_to(manifests_dir / _MANIFEST_FILENAME)

    repo_tool_dir = repo_dot_dir / "repo"
    repo_tool_dir.mkdir()
    _init_git_work_dir(repo_tool_dir)
    (repo_tool_dir / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    _git(["add", "VERSION"], cwd=repo_tool_dir)
    _git(["commit", "-m", "Initial commit"], cwd=repo_tool_dir)
    _git(["tag", "-a", "v1.0.0", "-m", "Version 1.0.0"], cwd=repo_tool_dir)

    return repo_dot_dir


def _run_repo_init(
    checkout_dir: pathlib.Path,
    repo_dir: pathlib.Path,
    manifest_url: str,
) -> subprocess.CompletedProcess:
    """Run kanon repo init with the given manifest URL.

    Args:
        checkout_dir: The working directory for the subprocess.
        repo_dir: The .repo directory to pass via --repo-dir.
        manifest_url: The manifest repository URL (file:// or https://).

    Returns:
        The CompletedProcess from the init invocation.
    """
    return _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "init",
        "--no-repo-verify",
        "-u",
        manifest_url,
        "-b",
        "main",
        "-m",
        _MANIFEST_FILENAME,
        cwd=checkout_dir,
    )


# ---------------------------------------------------------------------------
# AC-FUNC-003: kanon repo --help lists subcommands
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoHelpOutput:
    """AC-FUNC-003: 'kanon repo --help' output lists all subcommands."""

    def test_repo_help_exits_zero(self) -> None:
        """'kanon repo --help' must exit with code 0."""
        result = _run_kanon("repo", "--help")
        assert result.returncode == 0, (
            f"'kanon repo --help' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_help_lists_known_subcommands(self) -> None:
        """'kanon repo --help' output must mention init and sync example subcommands."""
        result = _run_kanon("repo", "--help")
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        for keyword in ("init", "sync"):
            assert keyword in combined, (
                f"Expected '{keyword}' in 'kanon repo --help' output.\n"
                f"  stdout: {result.stdout!r}\n"
                f"  stderr: {result.stderr!r}"
            )

    def test_repo_help_output_is_non_empty(self) -> None:
        """'kanon repo --help' must produce non-empty output."""
        result = _run_kanon("repo", "--help")
        assert result.returncode == 0
        assert len(result.stdout) > 0, f"'kanon repo --help' produced empty stdout.\n  stderr: {result.stderr!r}"


# ---------------------------------------------------------------------------
# AC-FUNC-004: kanon repo init via subprocess
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitSubprocess:
    """AC-FUNC-004: 'kanon repo init' via subprocess."""

    def test_repo_init_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init' with a real manifest must exit with code 0.

        Creates a bare manifest git repository pointing at a bare content
        repository and runs kanon repo init as a subprocess. Verifies the
        process exits 0.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(repos_dir, fetch_base)
        repo_dir = checkout_dir / ".repo"

        result = _run_repo_init(checkout_dir, repo_dir, f"file://{manifest_bare}")

        assert result.returncode == 0, (
            f"'kanon repo init' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_init_creates_dot_repo_directory(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init' must create the .repo directory on disk.

        After a successful kanon repo init invocation the .repo directory
        must exist in the checkout directory.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(repos_dir, fetch_base)
        repo_dir = checkout_dir / ".repo"

        result = _run_repo_init(checkout_dir, repo_dir, f"file://{manifest_bare}")
        assert result.returncode == 0, f"Prerequisite init failed: {result.stderr!r}"

        assert repo_dir.is_dir(), (
            f".repo directory was not created at {repo_dir!r} after 'kanon repo init'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-005: kanon repo sync via subprocess
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncSubprocess:
    """AC-FUNC-005: 'kanon repo sync' via subprocess."""

    def test_repo_sync_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo sync' after init must exit with code 0.

        Creates bare repos, runs kanon repo init, then runs kanon repo sync
        as a subprocess. Verifies the sync process exits 0.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(repos_dir, fetch_base)
        repo_dir = checkout_dir / ".repo"

        init_result = _run_repo_init(checkout_dir, repo_dir, f"file://{manifest_bare}")
        assert init_result.returncode == 0, f"Prerequisite init failed: {init_result.stderr!r}"

        sync_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )

        assert sync_result.returncode == 0, (
            f"'kanon repo sync' exited {sync_result.returncode}, expected 0.\n"
            f"  stdout: {sync_result.stdout!r}\n"
            f"  stderr: {sync_result.stderr!r}"
        )

    def test_repo_sync_clones_project_to_disk(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo sync' must clone the project defined in the manifest.

        After a successful sync the project directory specified in the manifest
        must exist on disk inside the checkout directory.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(repos_dir, fetch_base)
        repo_dir = checkout_dir / ".repo"

        init_result = _run_repo_init(checkout_dir, repo_dir, f"file://{manifest_bare}")
        assert init_result.returncode == 0, f"Prerequisite init failed: {init_result.stderr!r}"

        _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )

        project_dir = checkout_dir / "cli-test-project"
        assert project_dir.is_dir(), f"Project directory {project_dir!r} was not created after 'kanon repo sync'."


# ---------------------------------------------------------------------------
# AC-FUNC-006: kanon repo envsubst via subprocess
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoEnvsubstSubprocess:
    """AC-FUNC-006: 'kanon repo envsubst' via subprocess."""

    def test_repo_envsubst_exits_zero_and_substitutes_placeholder(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst' must exit 0 and replace ${VAR} in the manifest.

        Creates a manifest with a ${KANON_CLI_TEST_FETCH_URL} placeholder,
        runs kanon repo init followed by kanon repo envsubst with the env var
        set, then verifies the placeholder is replaced in the on-disk manifest.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        real_fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_envsubst_manifest_repo(repos_dir)
        repo_dir = checkout_dir / ".repo"

        init_result = _run_repo_init(checkout_dir, repo_dir, f"file://{manifest_bare}")
        assert init_result.returncode == 0, f"Prerequisite init failed: {init_result.stderr!r}"

        envsubst_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "envsubst",
            cwd=checkout_dir,
            extra_env={_ENVSUBST_VAR: real_fetch_base},
        )

        assert envsubst_result.returncode == 0, (
            f"'kanon repo envsubst' exited {envsubst_result.returncode}, expected 0.\n"
            f"  stdout: {envsubst_result.stdout!r}\n"
            f"  stderr: {envsubst_result.stderr!r}"
        )

        manifest_on_disk = repo_dir / "manifests" / _MANIFEST_FILENAME
        assert manifest_on_disk.is_file(), f"Manifest file {manifest_on_disk!r} not found."
        manifest_text = manifest_on_disk.read_text(encoding="utf-8")
        assert f"${{{_ENVSUBST_VAR}}}" not in manifest_text, (
            f"Placeholder ${{{_ENVSUBST_VAR}}} was not substituted in {manifest_on_disk!r}.\n"
            f"  manifest: {manifest_text!r}"
        )
        assert real_fetch_base in manifest_text, (
            f"Expected {real_fetch_base!r} in manifest after envsubst.\n  manifest: {manifest_text!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-007: kanon repo selfupdate prints embedded mode message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdateEmbeddedMode:
    """AC-FUNC-007: 'kanon repo selfupdate' prints the embedded mode message."""

    def test_repo_selfupdate_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate' in embedded mode must exit with code 0."""
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            "selfupdate",
            cwd=tmp_path,
        )

        assert result.returncode == 0, (
            f"'kanon repo selfupdate' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_selfupdate_prints_embedded_message(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate' must print the SELFUPDATE_EMBEDDED_MESSAGE constant.

        In embedded mode the selfupdate subcommand must print the message
        directing users to use 'pipx upgrade kanon-cli' instead. Verifies
        the full constant value appears in the combined output.
        """
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            "selfupdate",
            cwd=tmp_path,
        )

        combined = result.stdout + result.stderr
        assert SELFUPDATE_EMBEDDED_MESSAGE in combined, (
            f"Expected SELFUPDATE_EMBEDDED_MESSAGE {SELFUPDATE_EMBEDDED_MESSAGE!r} "
            f"in selfupdate output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-008: invalid subcommand error handling
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInvalidSubcommandHandling:
    """AC-FUNC-008: invalid subcommand exits non-zero with an error message."""

    def test_invalid_subcommand_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """An unrecognised repo subcommand must exit with a non-zero exit code."""
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            "totally-invalid-subcommand-xyz",
            cwd=tmp_path,
        )

        assert result.returncode != 0, (
            f"Expected non-zero exit for invalid subcommand, got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_invalid_subcommand_produces_error_output(self, tmp_path: pathlib.Path) -> None:
        """An unrecognised repo subcommand must produce an error message on stderr."""
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            "totally-invalid-subcommand-xyz",
            cwd=tmp_path,
        )

        assert len(result.stderr) > 0, (
            f"Expected non-empty stderr for invalid subcommand.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-009: argument passthrough to repo subcommands
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoArgumentPassthrough:
    """AC-FUNC-009: arguments are forwarded verbatim to repo subcommands."""

    def test_sync_jobs_argument_forwarded(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo sync --jobs=1' must forward --jobs=1 to the repo sync command.

        Creates bare repos, runs init, then runs sync with --jobs=1. Verifies
        the subprocess exits 0, confirming the --jobs argument was accepted by
        the underlying repo tool (not rejected as an unknown kanon option).
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(repos_dir, fetch_base)
        repo_dir = checkout_dir / ".repo"

        init_result = _run_repo_init(checkout_dir, repo_dir, f"file://{manifest_bare}")
        assert init_result.returncode == 0, f"Prerequisite init failed: {init_result.stderr!r}"

        sync_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )

        assert sync_result.returncode == 0, (
            f"'kanon repo sync --jobs=1' exited {sync_result.returncode}, expected 0.\n"
            f"  stdout: {sync_result.stdout!r}\n"
            f"  stderr: {sync_result.stderr!r}"
        )
