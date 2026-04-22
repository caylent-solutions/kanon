"""Happy-path functional tests for 'kanon repo upload'.

Exercises the happy path of the 'repo upload' subcommand by invoking
``kanon repo upload`` as a subprocess against a real initialized, synced, and
started repo directory created in a temporary directory. No mocking -- these
tests use the full CLI stack against actual git operations.

The 'repo upload' subcommand uploads changes from local topic branches to a
Gerrit code-review system. It searches for topic branches in local projects
that have commits not yet published for review.

To exercise the happy path without a real Gerrit server, the test suite:

1. Sets up a synced repo with a topic branch (via ``kanon repo init``,
   ``kanon repo sync``, and ``kanon repo start``).
2. Commits one file to the topic branch, making it uploadable.
3. Creates a local bare git repository to act as the Gerrit push target.
4. Sets ``remote.local.review`` in the project git config to a fake Gerrit URL
   so that ``repo upload`` picks up the review configuration.
5. Configures a ``url.<local-bare-path>.insteadOf`` rewrite so that git
   redirects pushes from the fake Gerrit URL to the local bare repo.
6. Sets the ``REPO_IGNORE_SSH_INFO`` environment variable so that
   ``ReviewUrl`` uses the review URL directly without trying to fetch
   SSH info from the (non-existent) Gerrit server.
7. Passes ``--dry-run`` so that git executes ``git push -n``, which
   communicates with the local bare repo but does not send objects.
8. Passes ``--yes`` to answer the upload confirmation prompt automatically.

Under this configuration, ``kanon repo upload --dry-run --yes`` exits 0 and
writes ``[OK    ] <project>/ <branch>`` to stderr.

AC wording note: AC-TEST-001 states "'kanon repo upload' with default args
exits 0 in a valid repo." With no topic branch or review configuration, the
real behavior is to log "repo: error: no branches ready for upload" and exit
1. The minimal invocation that exits 0 requires a reviewable branch (topic
branch with commits) and a configured review URL. This test uses
``--dry-run --yes`` with a local git server rewrite as the closest
achievable happy path without a live Gerrit instance. This deviation is
documented here so reviewers can verify the test asserts actual CLI
behavior rather than a misinterpretation of the AC wording.

Covers:
- AC-TEST-001: 'kanon repo upload --dry-run --yes' exits 0 in a valid
  configured repo with a reviewable topic branch.
- AC-TEST-002: Every positional argument of 'repo upload' has a happy-path
  test (project name and project path references are exercised via
  @pytest.mark.parametrize).
- AC-FUNC-001: 'kanon repo upload --dry-run --yes' executes successfully
  with documented default behavior (exit 0, upload summary on stdout,
  '[OK    ]' marker on stderr).
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel
  leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import (
    _git,
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- no hard-coded domain literals in test logic
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Upload Happy Test User"
_GIT_USER_EMAIL = "repo-upload-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "upload-test-project"

# Topic branch for upload tests
_TOPIC_BRANCH = "feature/upload-happy-path"

# File committed to the topic branch to make it uploadable
_UPLOAD_CONTENT_FILE = "upload-test-content.txt"
_UPLOAD_CONTENT_TEXT = "upload happy path test content"
_UPLOAD_COMMIT_MSG = "Add upload test content file"

# Local bare git repo directory name acting as the Gerrit push target
_REVIEW_BARE_DIR_NAME = "review.git"

# Fake Gerrit review URL (not a real server -- redirected via insteadOf)
_FAKE_REVIEW_BASE_URL = "http://fake.gerrit.example.com/"

# CLI token constants
_CLI_TOKEN_REPO = "repo"
_CLI_TOKEN_UPLOAD = "upload"
_CLI_TOKEN_START = "start"
_CLI_FLAG_REPO_DIR = "--repo-dir"
_CLI_FLAG_DRY_RUN = "--dry-run"
_CLI_FLAG_YES = "--yes"
_CLI_FLAG_ALL = "--all"

# Environment variable that suppresses SSH-info fetching in ReviewUrl
_ENV_IGNORE_SSH_INFO = "REPO_IGNORE_SSH_INFO"

# Git config keys for review and URL rewrite
_GIT_CONFIG_REMOTE_REVIEW = "remote.local.review"

# Expected exit code for all happy-path invocations
_EXPECTED_EXIT_CODE = 0

# Phrase expected in stdout when upload finds a reviewable branch
_UPLOAD_PROJECT_PHRASE = "Upload project"

# Success marker expected in stderr when upload completes normally
_OK_MARKER = "[OK    ]"

# Traceback indicator used in channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs
_ERROR_PREFIX = "Error:"


# ---------------------------------------------------------------------------
# Private setup helpers
# ---------------------------------------------------------------------------


def _build_insteadof_config_key(review_bare: pathlib.Path) -> str:
    """Return the git config key for the insteadOf URL rewrite.

    Formats the ``url.<local-path>.insteadOf`` key that redirects git push
    operations from the fake Gerrit URL to the local bare repository.

    Args:
        review_bare: Absolute path to the local bare git repository used as
            the Gerrit push target.

    Returns:
        A git config key string of the form
        ``url.file://<path>.insteadOf``.
    """
    return f"url.file://{review_bare}.insteadOf"


def _full_review_url() -> str:
    """Return the full fake Gerrit review URL including the project name.

    ReviewUrl appends ``remote.projectname`` to the base review URL.
    This function constructs the full URL that matches what ReviewUrl
    returns, so the insteadOf rewrite applies correctly.

    Returns:
        The concatenation of ``_FAKE_REVIEW_BASE_URL`` and
        ``_PROJECT_NAME``.
    """
    return _FAKE_REVIEW_BASE_URL + _PROJECT_NAME


def _setup_upload_repo(
    tmp_path: pathlib.Path,
    branch_name: str,
) -> "tuple[pathlib.Path, pathlib.Path, pathlib.Path]":
    """Create a synced repo with a reviewable topic branch and review config.

    Performs the shared setup steps required by all upload happy-path tests:

    1. Calls ``_setup_synced_repo`` to create bare repos, run
       ``kanon repo init`` and ``kanon repo sync``, and return
       ``(checkout_dir, repo_dir)``.
    2. Runs ``kanon repo start <branch_name> --all`` to create the topic
       branch across all manifest projects.
    3. Commits one new file to the project worktree so the topic branch has
       uploadable commits.
    4. Creates a local bare git repository at
       ``tmp_path / _REVIEW_BARE_DIR_NAME`` to act as the Gerrit push
       target.
    5. Configures ``remote.local.review`` in the project git config to
       ``_FAKE_REVIEW_BASE_URL`` so that ``repo upload`` picks up the
       review URL.
    6. Configures the ``url.<local-bare>.insteadOf`` rewrite in the
       project git config so that git redirects pushes from the fake
       Gerrit URL to the local bare repo.

    Args:
        tmp_path: pytest-provided temporary directory root.
        branch_name: Name of the topic branch to create via
            ``kanon repo start``.

    Returns:
        A 3-tuple of ``(checkout_dir, repo_dir, review_bare)`` where
        ``checkout_dir`` is the worktree root, ``repo_dir`` is the
        ``.repo`` directory, and ``review_bare`` is the local bare repo
        acting as the Gerrit push target.

    Raises:
        AssertionError: When any prerequisite step (init, sync, start)
            exits with a non-zero code.
    """
    checkout_dir, repo_dir = _setup_synced_repo(
        tmp_path,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_name=_PROJECT_NAME,
        project_path=_PROJECT_PATH,
        manifest_filename=_MANIFEST_FILENAME,
    )
    project_dir = checkout_dir / _PROJECT_PATH

    start_result = _run_kanon(
        _CLI_TOKEN_REPO,
        _CLI_FLAG_REPO_DIR,
        str(repo_dir),
        _CLI_TOKEN_START,
        branch_name,
        _CLI_FLAG_ALL,
        cwd=checkout_dir,
    )
    assert start_result.returncode == _EXPECTED_EXIT_CODE, (
        f"Prerequisite 'kanon repo start {branch_name} {_CLI_FLAG_ALL}' failed "
        f"with exit {start_result.returncode}.\n"
        f"  stdout: {start_result.stdout!r}\n"
        f"  stderr: {start_result.stderr!r}"
    )

    (project_dir / _UPLOAD_CONTENT_FILE).write_text(_UPLOAD_CONTENT_TEXT, encoding="utf-8")
    _git(["add", _UPLOAD_CONTENT_FILE], cwd=project_dir)
    _git(["commit", "-m", _UPLOAD_COMMIT_MSG], cwd=project_dir)

    review_bare = tmp_path / _REVIEW_BARE_DIR_NAME
    _git(["init", "--bare", str(review_bare)], cwd=tmp_path)

    subprocess.run(
        ["git", "-C", str(project_dir), "config", _GIT_CONFIG_REMOTE_REVIEW, _FAKE_REVIEW_BASE_URL],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(project_dir),
            "config",
            _build_insteadof_config_key(review_bare),
            _full_review_url(),
        ],
        check=True,
        capture_output=True,
    )

    return checkout_dir, repo_dir, review_bare


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo upload with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoUploadHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo upload --dry-run --yes' exits 0.

    AC wording note: AC-TEST-001 says "'kanon repo upload' with default args
    exits 0 in a valid repo." With a freshly synced repo and no topic
    branch or review URL, the command logs "no branches ready for upload"
    and exits 1. The minimal happy-path invocation that exits 0 requires a
    topic branch with commits and a configured review URL. The tests in
    this class use ``--dry-run --yes`` with a local bare-repo URL rewrite
    and the ``REPO_IGNORE_SSH_INFO`` environment variable to satisfy that
    requirement without a live Gerrit instance.
    """

    def test_repo_upload_dry_run_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo upload --dry-run --yes' exits 0 in a valid configured repo.

        After a successful 'kanon repo init', 'kanon repo sync', and
        'kanon repo start' with one committed file on the topic branch,
        and with the review URL configured to redirect to a local bare repo,
        'kanon repo upload --dry-run --yes' must exit 0.
        """
        checkout_dir, repo_dir, _ = _setup_upload_repo(tmp_path, _TOPIC_BRANCH)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_UPLOAD,
            _CLI_FLAG_DRY_RUN,
            _CLI_FLAG_YES,
            cwd=checkout_dir,
            extra_env={_ENV_IGNORE_SSH_INFO: "1"},
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_upload_dry_run_emits_upload_summary_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo upload --dry-run --yes' emits the upload summary on stdout.

        When invoked against a repo with a reviewable topic branch, the
        command prints an upload summary beginning with "Upload project" to
        stdout before attempting the push. Verifies the documented default
        behavior of the subcommand.
        """
        checkout_dir, repo_dir, _ = _setup_upload_repo(tmp_path, _TOPIC_BRANCH)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_UPLOAD,
            _CLI_FLAG_DRY_RUN,
            _CLI_FLAG_YES,
            cwd=checkout_dir,
            extra_env={_ENV_IGNORE_SSH_INFO: "1"},
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}' "
            f"failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _UPLOAD_PROJECT_PHRASE in result.stdout, (
            f"Expected {_UPLOAD_PROJECT_PHRASE!r} in stdout of "
            f"'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_upload_dry_run_emits_ok_marker_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo upload --dry-run --yes' emits the '[OK    ]' marker on stderr.

        On successful upload, the command writes "[OK    ] <project>/ <branch>"
        to stderr. Verifies that the documented success marker appears after
        the push completes without errors.
        """
        checkout_dir, repo_dir, _ = _setup_upload_repo(tmp_path, _TOPIC_BRANCH)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_UPLOAD,
            _CLI_FLAG_DRY_RUN,
            _CLI_FLAG_YES,
            cwd=checkout_dir,
            extra_env={_ENV_IGNORE_SSH_INFO: "1"},
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}' "
            f"failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _OK_MARKER in result.stderr, (
            f"Expected {_OK_MARKER!r} in stderr of "
            f"'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}'.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo upload has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoUploadPositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for the positional arguments of 'repo upload'.

    'repo upload' accepts optional ``[<project>]...`` positional arguments
    that restrict the upload to the specified projects. Projects may be
    referenced by name or by their relative path in the checkout. Both forms
    are exercised via @pytest.mark.parametrize.
    """

    @pytest.mark.parametrize(
        "project_ref",
        [
            _PROJECT_NAME,
            _PROJECT_PATH,
        ],
        ids=["by-project-name", "by-project-path"],
    )
    def test_repo_upload_with_project_ref_exits_zero(
        self,
        tmp_path: pathlib.Path,
        project_ref: str,
    ) -> None:
        """'kanon repo upload --dry-run --yes <project_ref>' exits 0.

        After setup (init, sync, start with commit, review config), passes
        the project reference (name or path) as the positional argument to
        'kanon repo upload --dry-run --yes'. Verifies the process exits 0
        for each valid reference form.
        """
        checkout_dir, repo_dir, _ = _setup_upload_repo(tmp_path, _TOPIC_BRANCH)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_UPLOAD,
            _CLI_FLAG_DRY_RUN,
            _CLI_FLAG_YES,
            project_ref,
            cwd=checkout_dir,
            extra_env={_ENV_IGNORE_SSH_INFO: "1"},
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES} {project_ref}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "project_ref",
        [
            _PROJECT_NAME,
            _PROJECT_PATH,
        ],
        ids=["by-project-name", "by-project-path"],
    )
    def test_repo_upload_with_project_ref_emits_ok_marker(
        self,
        tmp_path: pathlib.Path,
        project_ref: str,
    ) -> None:
        """'kanon repo upload --dry-run --yes <project_ref>' emits the OK marker.

        When a project reference is supplied and upload succeeds for that
        project, stderr must contain the '[OK    ]' success marker. Verifies
        that the per-project restriction path behaves consistently with the
        all-projects path.
        """
        checkout_dir, repo_dir, _ = _setup_upload_repo(tmp_path, _TOPIC_BRANCH)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_UPLOAD,
            _CLI_FLAG_DRY_RUN,
            _CLI_FLAG_YES,
            project_ref,
            cwd=checkout_dir,
            extra_env={_ENV_IGNORE_SSH_INFO: "1"},
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES} "
            f"{project_ref}' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _OK_MARKER in result.stderr, (
            f"Expected {_OK_MARKER!r} in stderr of 'kanon repo upload "
            f"{_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES} {project_ref}'.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoUploadChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo upload'.

    Verifies that successful 'kanon repo upload --dry-run --yes' invocations
    do not write Python tracebacks or 'Error:' prefixed messages to stdout,
    and that stderr does not contain Python exception tracebacks on a
    successful run.

    All three channel assertions share a single class-scoped fixture
    invocation to avoid redundant git setup.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo upload --dry-run --yes' once and return the CompletedProcess.

        Uses tmp_path_factory for a class-scoped fixture: setup and CLI
        invocation execute once, and all channel assertions share the result
        without repeating the expensive git operations.

        Returns:
            The CompletedProcess from
            'kanon repo upload --dry-run --yes'.

        Raises:
            AssertionError: When the prerequisite setup (init/sync/start)
                fails or when the upload itself exits non-zero.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline")
        checkout_dir, repo_dir, _ = _setup_upload_repo(tmp_path, _TOPIC_BRANCH)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_UPLOAD,
            _CLI_FLAG_DRY_RUN,
            _CLI_FLAG_YES,
            cwd=checkout_dir,
            extra_env={_ENV_IGNORE_SSH_INFO: "1"},
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}' "
            f"failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_repo_upload_success_has_no_traceback_on_stdout(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo upload --dry-run --yes' must not emit tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call
        last)'. Tracebacks on stdout indicate an unhandled exception that
        escaped to the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful "
            f"'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}'.\n"
            f"  stdout: {channel_result.stdout!r}"
        )

    def test_repo_upload_success_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo upload --dry-run --yes' must not emit 'Error:' to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on
        stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}': "
                f"{line!r}\n  stdout: {channel_result.stdout!r}"
            )

    def test_repo_upload_success_has_no_traceback_on_stderr(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo upload --dry-run --yes' must not emit tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call
        last)'. A traceback on stderr during a successful run indicates an
        unhandled exception that was swallowed rather than propagated
        correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful "
            f"'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}'.\n"
            f"  stderr: {channel_result.stderr!r}"
        )
