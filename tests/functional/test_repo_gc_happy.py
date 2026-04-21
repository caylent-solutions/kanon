"""Happy-path functional tests for 'kanon repo gc'.

Exercises the happy path of the 'repo gc' subcommand by invoking
``kanon repo gc`` as a subprocess against a real initialized repo directory
created in a temporary directory. No mocking -- these tests use the full CLI
stack against actual git operations.

The 'repo gc' subcommand runs git garbage collection across all projects in
a repo manifest. On a freshly initialized repository with no unused project
directories, it exits 0 and prints 'Nothing to clean up.'

Covers:
- AC-TEST-001: Five shared helper functions exist only in tests/functional/conftest.py
  and are imported here, not re-defined locally.
- AC-CODE-001: 'kanon repo gc' with default args exits 0 in a valid initialized repo.
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import (
    _clone_as_bare,
    _create_bare_content_repo,
    _create_manifest_repo,
    _init_git_work_dir,
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants (no hard-coded values in test logic)
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo GC Happy Test User"
_GIT_USER_EMAIL = "repo-gc-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from repo-gc-happy test content"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "gc-happy-test-project"
_MANIFEST_BARE_DIR_NAME = "manifest-bare.git"

# Expected exit code for all happy-path invocations.
_EXPECTED_EXIT_CODE = 0

# Phrase expected in stdout when gc runs on a fresh repo with no unused projects.
_NOTHING_TO_CLEAN = "Nothing to clean up."

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# ---------------------------------------------------------------------------
# AC-TEST-001: import assertion -- helpers exist only in conftest
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestSharedHelperImportability:
    """AC-TEST-001: Five shared helpers are importable from tests.functional.conftest.

    Each helper (_init_git_work_dir, _clone_as_bare, _create_bare_content_repo,
    _create_manifest_repo, _setup_synced_repo) must be defined in
    tests/functional/conftest.py and importable from there. This file imports
    all five at module level (the import block above), so a collection-time
    ImportError would fail these tests immediately if any helper is missing
    from conftest.

    The tests below assert that the imported names are callable, confirming
    they are real function objects rather than sentinel values.
    """

    def test_init_git_work_dir_importable_from_conftest(self) -> None:
        """_init_git_work_dir must be importable from tests.functional.conftest.

        If _init_git_work_dir is not defined in conftest.py, the module-level
        import at the top of this file raises ImportError and this test fails
        at collection time. The callable check confirms it is a real function.
        """
        assert callable(_init_git_work_dir), "_init_git_work_dir imported from conftest must be callable"

    def test_clone_as_bare_importable_from_conftest(self) -> None:
        """_clone_as_bare must be importable from tests.functional.conftest.

        If _clone_as_bare is not defined in conftest.py, the module-level
        import raises ImportError and this test fails at collection time.
        """
        assert callable(_clone_as_bare), "_clone_as_bare imported from conftest must be callable"

    def test_create_bare_content_repo_importable_from_conftest(self) -> None:
        """_create_bare_content_repo must be importable from tests.functional.conftest.

        If _create_bare_content_repo is not defined in conftest.py, the
        module-level import raises ImportError and this test fails at
        collection time.
        """
        assert callable(_create_bare_content_repo), "_create_bare_content_repo imported from conftest must be callable"

    def test_create_manifest_repo_importable_from_conftest(self) -> None:
        """_create_manifest_repo must be importable from tests.functional.conftest.

        If _create_manifest_repo is not defined in conftest.py, the module-level
        import raises ImportError and this test fails at collection time.
        """
        assert callable(_create_manifest_repo), "_create_manifest_repo imported from conftest must be callable"

    def test_setup_synced_repo_importable_from_conftest(self) -> None:
        """_setup_synced_repo must be importable from tests.functional.conftest.

        If _setup_synced_repo is not defined in conftest.py, the module-level
        import raises ImportError and this test fails at collection time.
        """
        assert callable(_setup_synced_repo), "_setup_synced_repo imported from conftest must be callable"


# ---------------------------------------------------------------------------
# AC-CODE-001: kanon repo gc with default args exits 0 in a valid initialized repo
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGcHappyPathDefaultArgs:
    """AC-CODE-001: 'kanon repo gc' with default args exits 0 in a valid repo.

    Verifies that running 'kanon repo gc' with no additional arguments
    against a properly initialized repo directory exits 0 and prints
    'Nothing to clean up.' when no unused project directories exist.
    """

    def test_repo_gc_with_defaults_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo gc' with no extra args must exit 0.

        After a successful 'kanon repo init' and 'kanon repo sync', invokes
        'kanon repo gc' with no additional arguments. A freshly synced
        repository has no unused project directories, so the command must
        exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "gc",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo gc' exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_gc_prints_nothing_to_clean_up_in_fresh_repo(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo gc' must print 'Nothing to clean up.' in a freshly synced repo.

        When no unused project directories exist after 'repo init' and 'repo
        sync', the 'gc' subcommand exits 0 and emits 'Nothing to clean up.'
        on stdout. This verifies the documented default behavior.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "gc",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo gc' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _NOTHING_TO_CLEAN in result.stdout, (
            f"Expected {_NOTHING_TO_CLEAN!r} in stdout of 'kanon repo gc' on a fresh repo.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_gc_output_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo gc' must produce non-empty combined output in a fresh repo.

        A successful invocation on a fresh repo must produce at least some
        output describing the gc result. An empty output would indicate the
        command ran without performing any work.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "gc",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo gc' failed: {result.stderr!r}"
        combined = result.stdout + result.stderr
        assert len(combined) > 0, (
            f"'kanon repo gc' produced empty combined output.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGcHappyChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo gc'.

    Verifies that successful 'kanon repo gc' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    def test_repo_gc_success_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo gc' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "gc",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo gc' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo gc'.\n  stdout: {result.stdout!r}"
        )

    def test_repo_gc_success_has_no_error_keyword_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo gc' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "gc",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo gc' failed: {result.stderr!r}"
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful 'kanon repo gc': {line!r}\n"
                f"  stdout: {result.stdout!r}"
            )

    def test_repo_gc_success_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo gc' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "gc",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo gc' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo gc'.\n  stderr: {result.stderr!r}"
        )
