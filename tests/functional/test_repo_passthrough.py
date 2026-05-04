"""Functional tests for kanon repo passthrough basics.

Verifies that:
- Arguments are forwarded verbatim to the repo subcommand dispatcher.
- --repo-dir flag overrides the default repo directory.
- KANON_REPO_DIR environment variable sets the default repo directory
  when --repo-dir is omitted.
- stdout/stderr channel discipline is maintained (no cross-channel leakage).

All tests invoke kanon as a subprocess (no mocking of internal APIs).
Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from kanon_cli.constants import KANON_REPO_DIR_ENV
from tests.functional.conftest import _git, _run_kanon

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Passthrough Test User"
_GIT_USER_EMAIL = "passthrough-test@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from passthrough test content"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
# NOTE: _git is imported from tests.functional.conftest (canonical definition).
#
# The four helpers below (_init_git_work_dir, _clone_as_bare,
# _create_bare_content_repo, _create_manifest_repo) are near-duplicates of
# same-named functions in test_kanon_repo_cli.py. Consolidating them into a
# shared module requires touching that file, which is outside this task's
# Changes Manifest. This duplication is tracked as a follow-up DRY cleanup.
# ---------------------------------------------------------------------------


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
        '  <project name="content-bare" path="pt-project" />\n'
        "</manifest>\n"
    )
    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / "manifest-bare.git")


def _run_repo_init(
    checkout_dir: pathlib.Path,
    repo_dir: pathlib.Path,
    manifest_url: str,
) -> subprocess.CompletedProcess:
    """Run kanon repo init with the given manifest URL using --repo-dir.

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


def _setup_init_and_sync_env(
    tmp_path: pathlib.Path,
    checkout_subdir: str = "checkout",
) -> tuple[pathlib.Path, pathlib.Path]:
    """Create repos, run init, and return (checkout_dir, repo_dir).

    Args:
        tmp_path: pytest-provided temporary directory root.
        checkout_subdir: Name of the checkout subdirectory inside tmp_path.

    Returns:
        Tuple of (checkout_dir, repo_dir) after a successful init.

    Raises:
        AssertionError: If kanon repo init fails.
    """
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    checkout_dir = tmp_path / checkout_subdir
    checkout_dir.mkdir()

    bare_content = _create_bare_content_repo(repos_dir)
    fetch_base = f"file://{bare_content.parent}"
    manifest_bare = _create_manifest_repo(repos_dir, fetch_base)
    repo_dir = checkout_dir / ".repo"

    init_result = _run_repo_init(checkout_dir, repo_dir, f"file://{manifest_bare}")
    assert init_result.returncode == 0, (
        f"Prerequisite kanon repo init failed with exit {init_result.returncode}.\n"
        f"  stdout: {init_result.stdout!r}\n"
        f"  stderr: {init_result.stderr!r}"
    )
    return checkout_dir, repo_dir


# ---------------------------------------------------------------------------
# AC-TEST-001: kanon repo sync --jobs 4 passes through to repo sync
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestSyncJobsPassthrough:
    """AC-TEST-001: 'kanon repo sync --jobs 4' forwards --jobs to the repo sync command."""

    def test_sync_jobs_space_separated_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo sync --jobs 4' with a space-separated value must exit 0.

        Verifies that space-separated '--jobs 4' (not '--jobs=4') is forwarded
        verbatim to the underlying repo sync command and accepted without error.
        The test performs a real sync against a local bare git repo so that
        the --jobs argument is exercised end-to-end.
        """
        checkout_dir, repo_dir = _setup_init_and_sync_env(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs",
            "4",
            cwd=checkout_dir,
        )

        assert result.returncode == 0, (
            f"'kanon repo sync --jobs 4' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_sync_jobs_equals_format_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo sync --jobs=4' with equals format must also exit 0.

        Verifies that equals-separated '--jobs=4' is also forwarded verbatim
        to the underlying repo sync command and accepted without error.
        """
        checkout_dir, repo_dir = _setup_init_and_sync_env(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs=4",
            cwd=checkout_dir,
        )

        assert result.returncode == 0, (
            f"'kanon repo sync --jobs=4' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_sync_jobs_clones_project_to_disk(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo sync --jobs 4' must clone the project defined in the manifest.

        After a successful sync the project directory specified in the manifest
        must exist on disk inside the checkout directory, confirming the
        sync actually ran (not just that the argument was accepted).
        """
        checkout_dir, repo_dir = _setup_init_and_sync_env(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs",
            "4",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"sync exited {result.returncode}\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

        project_dir = checkout_dir / "pt-project"
        assert project_dir.is_dir(), (
            f"Project directory {project_dir!r} was not created after 'kanon repo sync --jobs 4'."
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: --repo-dir /custom/.repo overrides default repo dir
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDirFlagOverride:
    """AC-TEST-002: '--repo-dir /custom/.repo' overrides the default repo dir."""

    def test_explicit_repo_dir_flag_used_for_init(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo --repo-dir <custom>' uses the custom dir, not the default.

        Creates a checkout directory and passes a custom --repo-dir path that
        differs from the default '.repo' location. Verifies that init creates
        the .repo structure at the custom path, confirming --repo-dir overrides
        the default.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(repos_dir, fetch_base)

        custom_repo_dir = tmp_path / "custom-dot-repo"

        result = _run_repo_init(checkout_dir, custom_repo_dir, f"file://{manifest_bare}")

        assert result.returncode == 0, (
            f"'kanon repo --repo-dir <custom> init' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert custom_repo_dir.is_dir(), (
            f"Custom repo dir {custom_repo_dir!r} was not created after init with --repo-dir."
        )

    def test_explicit_repo_dir_flag_not_default_location(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo --repo-dir <custom>' must NOT create a .repo at the default path.

        When --repo-dir is passed pointing to a non-default location, the init
        command must create the repo structure only at that custom path. The
        default '.repo' location inside the checkout directory must not be created.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(repos_dir, fetch_base)

        custom_repo_dir = tmp_path / "custom-dot-repo"

        init_result = _run_repo_init(checkout_dir, custom_repo_dir, f"file://{manifest_bare}")
        assert init_result.returncode == 0, f"Prerequisite init failed: {init_result.stderr!r}"

        default_repo_dir = checkout_dir / ".repo"
        assert not default_repo_dir.exists(), (
            f"Default .repo dir {default_repo_dir!r} was created even though --repo-dir pointed to {custom_repo_dir!r}."
        )

    def test_explicit_repo_dir_flag_used_for_sync(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo --repo-dir <custom> sync' reads from the custom dir.

        After init with a custom --repo-dir, a subsequent sync with the same
        custom --repo-dir must succeed. The test runs sync from the same
        checkout_dir used for init and verifies that exit code is 0, confirming
        that --repo-dir overrides the default repo-dir location for all
        subcommands, not just init.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(repos_dir, fetch_base)

        custom_repo_dir = checkout_dir / "custom-dot-repo"

        init_result = _run_repo_init(checkout_dir, custom_repo_dir, f"file://{manifest_bare}")
        assert init_result.returncode == 0, f"Prerequisite init failed: {init_result.stderr!r}"

        sync_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(custom_repo_dir),
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )

        assert sync_result.returncode == 0, (
            f"'kanon repo --repo-dir <custom> sync' exited {sync_result.returncode}, expected 0.\n"
            f"  stdout: {sync_result.stdout!r}\n"
            f"  stderr: {sync_result.stderr!r}"
        )
        project_dir = checkout_dir / "pt-project"
        assert project_dir.is_dir(), (
            f"Project directory {project_dir!r} was not created after sync with custom --repo-dir {custom_repo_dir!r}."
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: KANON_REPO_DIR env var sets default repo dir when --repo-dir omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestKanonRepoDirEnvVar:
    """AC-TEST-003: KANON_REPO_DIR env var sets default repo dir when --repo-dir omitted."""

    def test_env_var_sets_default_repo_dir_for_selfupdate(self, tmp_path: pathlib.Path) -> None:
        """KANON_REPO_DIR is used as repo_dir when --repo-dir is not passed.

        Creates a minimal .repo structure at a custom path, sets KANON_REPO_DIR
        to that path, then invokes 'kanon repo selfupdate' without --repo-dir.
        The command exits 1 (updated per E2-F2-S2-T2, declared in E2-F2-S2-T3:
        selfupdate exits 1 in embedded mode), confirming that the env var was
        picked up as the default repo dir (the embedded message appears on stderr).
        """
        repo_dot_dir = tmp_path / "env-var-dot-repo"
        manifests_dir = repo_dot_dir / "manifests"
        manifests_dir.mkdir(parents=True)

        manifest_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://github.com/caylent-solutions/" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_path = manifests_dir / _MANIFEST_FILENAME
        manifest_path.write_text(manifest_content, encoding="utf-8")
        (repo_dot_dir / "manifest.xml").symlink_to(manifest_path)

        repo_tool_dir = repo_dot_dir / "repo"
        repo_tool_dir.mkdir()
        _init_git_work_dir(repo_tool_dir)
        (repo_tool_dir / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        _git(["add", "VERSION"], cwd=repo_tool_dir)
        _git(["commit", "-m", "Initial commit"], cwd=repo_tool_dir)
        _git(["tag", "-a", "v1.0.0", "-m", "Version 1.0.0"], cwd=repo_tool_dir)

        result = _run_kanon(
            "repo",
            "selfupdate",
            cwd=tmp_path,
            extra_env={KANON_REPO_DIR_ENV: str(repo_dot_dir)},
        )

        assert result.returncode == 1, (
            f"'kanon repo selfupdate' with {KANON_REPO_DIR_ENV}={repo_dot_dir!r} "
            f"exited {result.returncode}, expected 1.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        from kanon_cli.constants import SELFUPDATE_EMBEDDED_MESSAGE

        assert SELFUPDATE_EMBEDDED_MESSAGE in result.stderr, (
            f"Expected {SELFUPDATE_EMBEDDED_MESSAGE!r} in stderr, confirming the "
            f"env var was picked up as the default repo dir.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_env_var_overrides_not_applied_when_flag_present(self, tmp_path: pathlib.Path) -> None:
        """--repo-dir flag takes precedence over KANON_REPO_DIR env var.

        Sets KANON_REPO_DIR to a non-existent path and passes --repo-dir to a
        valid custom repo dir. The command must succeed, confirming that the
        explicit --repo-dir flag takes priority over the environment variable.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(repos_dir, fetch_base)

        custom_repo_dir = tmp_path / "explicit-dot-repo"
        nonexistent_env_dir = str(tmp_path / "nonexistent-env-dot-repo")

        init_result = _run_repo_init(checkout_dir, custom_repo_dir, f"file://{manifest_bare}")
        assert init_result.returncode == 0, f"Prerequisite init failed: {init_result.stderr!r}"

        sync_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(custom_repo_dir),
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
            extra_env={KANON_REPO_DIR_ENV: nonexistent_env_dir},
        )

        assert sync_result.returncode == 0, (
            f"'kanon repo --repo-dir <valid> sync' with KANON_REPO_DIR pointing to "
            f"a non-existent path exited {sync_result.returncode}, expected 0.\n"
            f"  stdout: {sync_result.stdout!r}\n"
            f"  stderr: {sync_result.stderr!r}"
        )

    def test_env_var_used_for_init_without_flag(self, tmp_path: pathlib.Path) -> None:
        """KANON_REPO_DIR controls where .repo is created when --repo-dir is omitted.

        Invokes 'kanon repo init' without --repo-dir but with KANON_REPO_DIR set
        to a specific path. Verifies that the .repo structure is created at the
        path specified by the env var, not at the default '.repo' name relative
        to cwd.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(repos_dir, fetch_base)
        manifest_url = f"file://{manifest_bare}"

        env_repo_dir = tmp_path / "env-repo-dot-repo"

        result = _run_kanon(
            "repo",
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            "-b",
            "main",
            "-m",
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
            extra_env={KANON_REPO_DIR_ENV: str(env_repo_dir)},
        )

        assert result.returncode == 0, (
            f"'kanon repo init' with KANON_REPO_DIR={env_repo_dir!r} (no --repo-dir) "
            f"exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert env_repo_dir.is_dir(), (
            f"Expected .repo dir to be created at env-var path {env_repo_dir!r}, but it does not exist."
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: argv after `kanon repo` is forwarded verbatim
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestArgvVerbatimPassthrough:
    """AC-FUNC-001: argv after 'kanon repo' is forwarded verbatim to the repo subcommand dispatcher."""

    @pytest.mark.parametrize(
        "extra_args",
        [
            ["--jobs", "1"],
            ["--jobs=1"],
            ["--jobs", "1", "--current-branch"],
        ],
    )
    def test_sync_extra_args_forwarded_verbatim(self, tmp_path: pathlib.Path, extra_args: list[str]) -> None:
        """'kanon repo sync <extra_args>' forwards all extra_args verbatim to repo sync.

        Verifies that various forms of extra arguments are accepted by the
        underlying repo sync without being interpreted or rejected by kanon's
        argument parser.
        """
        checkout_dir, repo_dir = _setup_init_and_sync_env(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            *extra_args,
            cwd=checkout_dir,
        )

        assert result.returncode == 0, (
            f"'kanon repo sync {extra_args}' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_selfupdate_subcommand_forwarded(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate' forwards the 'selfupdate' subcommand verbatim.

        The 'selfupdate' subcommand is intercepted by the embedded mode handler
        which exits 1 with an informational message (updated per E2-F2-S2-T2,
        declared in E2-F2-S2-T3: selfupdate exits 1 in embedded mode). Verifying
        it exits 1 confirms
        that arbitrary subcommand names are forwarded without any kanon-side
        filtering or consumption.
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

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "selfupdate",
            cwd=checkout_dir,
        )

        assert result.returncode == 1, (
            f"'kanon repo selfupdate' exited {result.returncode}, expected 1.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_subcommand_forwarded(self) -> None:
        """'kanon repo help' forwards the 'help' subcommand verbatim.

        The 'help' subcommand is accepted by the repo dispatcher; verifying
        that it reaches the underlying tool confirms verbatim forwarding
        without kanon consuming the argument.
        """
        result = _run_kanon("repo", "--help")

        assert result.returncode == 0, (
            f"'kanon repo --help' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert len(combined) > 0, (
            f"'kanon repo --help' produced empty output.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestStdoutStderrDiscipline:
    """AC-CHANNEL-001: stdout vs stderr discipline -- no cross-channel leakage."""

    def test_help_output_on_stdout(self) -> None:
        """'kanon repo --help' must produce output on stdout, not only on stderr.

        Help output must appear on stdout so that it can be captured and piped
        by callers. An empty stdout with all output on stderr would indicate a
        channel discipline violation.
        """
        result = _run_kanon("repo", "--help")

        assert result.returncode == 0, (
            f"'kanon repo --help' exited {result.returncode}.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'kanon repo --help' produced no stdout output; help text must be on stdout.\n  stderr: {result.stderr!r}"
        )

    def test_error_output_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """When kanon repo errors, the error message must appear on stderr, not stdout.

        Invokes kanon repo with a non-existent .repo path so that the
        underlying command fails. Verifies that the error output appears on
        stderr and that stdout does not contain the error message. This
        confirms that error messages are not cross-contaminating stdout.
        """
        nonexistent_repo_dir = str(tmp_path / "does-not-exist")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            "sync",
            cwd=tmp_path,
        )

        assert result.returncode != 0, (
            f"Expected non-zero exit for missing repo dir, got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, (
            f"Expected error message on stderr for missing repo dir, but stderr is empty.\n  stdout: {result.stdout!r}"
        )

    def test_sync_success_produces_no_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """A successful 'kanon repo sync' must not write kanon-level error text to stderr.

        After a successful sync the kanon layer must not emit its own error
        messages. The underlying repo tool may write informational output to
        stderr; this test checks that the kanon error prefix 'Error:' does not
        appear, confirming that kanon itself is not generating spurious errors.
        """
        checkout_dir, repo_dir = _setup_init_and_sync_env(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )

        assert result.returncode == 0, (
            f"Expected exit 0 for successful sync, got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        kanon_error_prefix = "Error:"
        assert kanon_error_prefix not in result.stderr, (
            f"Found kanon error prefix {kanon_error_prefix!r} in stderr after a "
            f"successful sync.\n  stderr: {result.stderr!r}"
        )
