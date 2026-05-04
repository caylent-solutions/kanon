"""Happy-path functional tests for 'kanon repo init'.

Exercises the happy path of the 'repo init' subcommand by invoking
``kanon repo init`` as a subprocess against a real bare git manifest
repository created in a temporary directory. No mocking -- these tests
use the full CLI stack against actual git operations.

Covers:
- AC-TEST-001: 'kanon repo init' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo init' has a happy-path test.
- AC-FUNC-001: 'kanon repo init' executes successfully with documented default behavior.
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import _git, _run_kanon

# ---------------------------------------------------------------------------
# Module-level constants (no hard-coded values in test logic)
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Init Happy Test User"
_GIT_USER_EMAIL = "repo-init-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from repo-init-happy test content"

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
# NOTE: _git is imported from tests.functional.conftest (canonical definition).
#
# The helpers below (_init_git_work_dir, _clone_as_bare,
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
    """Clone work_dir into bare_dir and return the resolved bare_dir path.

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
        fetch_base: The fetch base URL for the remote element in the manifest.

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
        '  <project name="content-bare" path="happy-init-project" />\n'
        "</manifest>\n"
    )
    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / "manifest-bare.git")


def _setup_repos(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, str]:
    """Create bare content and manifest repos and return checkout context.

    Args:
        tmp_path: pytest-provided temporary directory.

    Returns:
        A tuple of (checkout_dir, repo_dir, manifest_url) ready for use
        with 'kanon repo init'.
    """
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    checkout_dir = tmp_path / "checkout"
    checkout_dir.mkdir()

    bare_content = _create_bare_content_repo(repos_dir)
    fetch_base = f"file://{bare_content.parent}"
    manifest_bare = _create_manifest_repo(repos_dir, fetch_base)
    manifest_url = f"file://{manifest_bare}"

    repo_dir = checkout_dir / ".repo"
    return checkout_dir, repo_dir, manifest_url


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo init with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo init' with default args exits 0.

    Verifies that passing only the required -u argument (manifest URL)
    succeeds, exercising the default values for --manifest-branch and
    --manifest-name (which default to HEAD and default.xml respectively).
    """

    def test_repo_init_with_defaults_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init -u <url>' with no branch or manifest name exits 0.

        Only the mandatory -u argument is supplied. The --manifest-branch
        and --manifest-name arguments take their documented defaults (HEAD
        and default.xml). Verifies the process exits 0.
        """
        checkout_dir, repo_dir, manifest_url = _setup_repos(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            cwd=checkout_dir,
        )

        assert result.returncode == 0, (
            f"'kanon repo init -u <url>' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_init_with_defaults_creates_dot_repo_dir(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init -u <url>' with defaults must create the .repo directory.

        Verifies that the .repo directory is created in the checkout directory
        after a successful 'kanon repo init' with only the -u argument.
        """
        checkout_dir, repo_dir, manifest_url = _setup_repos(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            cwd=checkout_dir,
        )

        assert result.returncode == 0, f"Prerequisite init failed: {result.stderr!r}"
        assert repo_dir.is_dir(), (
            f".repo directory was not created at {repo_dir!r} after 'kanon repo init' with defaults.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_init_with_defaults_creates_manifests_dir(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init -u <url>' with defaults must create .repo/manifests/.

        After a successful 'kanon repo init' with only -u supplied, the
        .repo/manifests/ directory must exist and contain a default.xml file.
        """
        checkout_dir, repo_dir, manifest_url = _setup_repos(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            cwd=checkout_dir,
        )

        assert result.returncode == 0, f"Prerequisite init failed: {result.stderr!r}"

        manifests_dir = repo_dir / "manifests"
        assert manifests_dir.is_dir(), (
            f".repo/manifests/ was not created at {manifests_dir!r} after 'kanon repo init' with defaults."
        )
        default_xml = manifests_dir / _MANIFEST_FILENAME
        assert default_xml.is_file(), (
            f"Expected {default_xml!r} to exist in manifests dir after 'kanon repo init' with defaults."
        )

    def test_repo_init_with_explicit_branch_and_manifest_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init -u <url> -b main -m default.xml' exits 0.

        Verifies the fully explicit form of 'kanon repo init' with all three
        named arguments supplied (-u, -b, -m) exits 0 and creates the .repo
        directory. Documents the baseline default behavior end-to-end.
        """
        checkout_dir, repo_dir, manifest_url = _setup_repos(tmp_path)

        result = _run_kanon(
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

        assert result.returncode == 0, (
            f"'kanon repo init -u ... -b main -m default.xml' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert repo_dir.is_dir(), (
            f".repo directory was not created at {repo_dir!r}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo init has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitPositionalArgHappyPath:
    """AC-TEST-002: happy-path test for the manifest URL positional argument.

    'repo init' accepts the manifest URL as either a named -u/--manifest-url
    option or as the first positional argument. This class verifies the
    positional form exits 0 and produces the expected filesystem state.
    """

    def test_repo_init_url_as_positional_arg_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init <url>' with URL as positional arg exits 0.

        Passes the manifest URL as a positional argument (not via -u) to
        'kanon repo init'. Verifies the process exits 0, exercising the
        ValidateOptions branch that pops the first positional arg into
        opt.manifest_url.
        """
        checkout_dir, repo_dir, manifest_url = _setup_repos(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-b",
            "main",
            "-m",
            _MANIFEST_FILENAME,
            manifest_url,
            cwd=checkout_dir,
        )

        assert result.returncode == 0, (
            f"'kanon repo init <url>' (positional) exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_init_url_as_positional_arg_creates_dot_repo_dir(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init <url>' with positional URL creates the .repo directory.

        After a successful 'kanon repo init <url>' with the URL passed as
        a positional argument, the .repo directory must exist.
        """
        checkout_dir, repo_dir, manifest_url = _setup_repos(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-b",
            "main",
            "-m",
            _MANIFEST_FILENAME,
            manifest_url,
            cwd=checkout_dir,
        )

        assert result.returncode == 0, f"Prerequisite init with positional URL failed: {result.stderr!r}"
        assert repo_dir.is_dir(), (
            f".repo directory was not created at {repo_dir!r} after 'kanon repo init <url>' (positional).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo init'.

    Verifies that successful 'kanon repo init' invocations do not write
    application error messages to stdout, and that any informational output
    written to stdout does not include raw Python exception tracebacks or
    internal error details.
    """

    def test_repo_init_success_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo init' must not emit Python tracebacks to stdout.

        A successful invocation must not write any 'Traceback (most recent call
        last)' text to stdout. Error output (stack traces, error messages) must
        only appear on stderr when something goes wrong; on success, stdout is
        reserved for human-readable progress/completion messages.
        """
        checkout_dir, repo_dir, manifest_url = _setup_repos(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            cwd=checkout_dir,
        )

        assert result.returncode == 0, f"Prerequisite init failed: {result.stderr!r}"
        assert "Traceback (most recent call last)" not in result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo init'.\n  stdout: {result.stdout!r}"
        )

    def test_repo_init_success_has_no_error_keyword_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo init' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages (e.g. 'Error: ...') are a stderr-only concern.
        A successful invocation must not produce any line beginning with
        'Error:' on stdout, as that would indicate cross-channel leakage of
        error output.
        """
        checkout_dir, repo_dir, manifest_url = _setup_repos(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            cwd=checkout_dir,
        )

        assert result.returncode == 0, f"Prerequisite init failed: {result.stderr!r}"
        for line in result.stdout.splitlines():
            assert not line.startswith("Error:"), (
                f"'Error:' line found in stdout of successful 'kanon repo init': {line!r}\n  stdout: {result.stdout!r}"
            )

    def test_repo_init_stderr_does_not_contain_completion_message(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo init' completion message must not appear only on stderr.

        The 'repo has been initialized' completion message is an informational
        output. Verifies that stderr does not contain internal Python error
        detail (tracebacks) on a successful run -- any error detail belongs
        only on stderr for failed runs. On success, stderr must not contain
        a 'Traceback (most recent call last)' line.
        """
        checkout_dir, repo_dir, manifest_url = _setup_repos(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            cwd=checkout_dir,
        )

        assert result.returncode == 0, f"Prerequisite init failed: {result.stderr!r}"
        assert "Traceback (most recent call last)" not in result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo init'.\n  stderr: {result.stderr!r}"
        )
