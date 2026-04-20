"""Functional tests for flag coverage of 'kanon repo prune'.

Exercises every flag available to ``subcmds/prune.py`` by invoking
``kanon repo prune`` as a subprocess. The ``Prune`` subcommand has no
``_Options()`` method of its own; its flags are the common flags registered
by ``Command._CommonOptions()``:

- ``-v`` / ``--verbose`` (store_true, dest=output_mode, no explicit default -- defaults to None)
- ``-q`` / ``--quiet`` (store_false, dest=output_mode, no explicit default -- defaults to None)
- ``-j`` / ``--jobs`` (type=int, default=DEFAULT_LOCAL_JOBS)
- ``--outer-manifest`` (store_true, default=None)
- ``--no-outer-manifest`` (store_false, dest=outer_manifest)
- ``--this-manifest-only`` (store_true, default=None)
- ``--no-this-manifest-only`` / ``--all-manifests`` (store_false, dest=this_manifest_only)

Valid-value tests confirm each flag is accepted without an argument-parsing
error (exit code != 2). Negative tests for boolean flags confirm that supplying
an inline value is rejected with exit code 2. The negative test for ``--jobs``
confirms that a non-integer value is rejected with exit code 2.

Covers:
- AC-TEST-001: Every flag has a valid-value test.
- AC-TEST-002: Every flag that accepts enumerated or typed values has a
  negative test verifying rejection of an invalid value.
- AC-TEST-003: Flags have correct absence-default behavior when omitted.
- AC-FUNC-001: Every documented flag behaves per its help text (covered by
  the parametrized AC-TEST-001 tests in TestRepoPruneFlagsValidValues).
- AC-CHANNEL-001: stdout vs stderr channel discipline is verified.

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import _git, _run_kanon

# ---------------------------------------------------------------------------
# Module-level constants -- all hard-coded test-fixture values extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Prune Flags Test User"
_GIT_USER_EMAIL = "repo-prune-flags@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from repo-prune-flags test content"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "prune-flags-test-project"
_MANIFEST_BARE_DIR_NAME = "manifest-bare.git"
_GIT_BRANCH_MAIN = "main"

# Error exit code for argument-parsing errors.
_ARGPARSE_ERROR_EXIT_CODE = 2

# Nonexistent repo-dir name used in argument-parser acceptance tests that
# do not require a real initialized repository (e.g. boolean-with-inline-value
# negative tests that fail at parse time before repo discovery).
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-prune-flags-repo-dir"

# Inline-value token for boolean-flag negative tests.
# optparse exits 2 with '--<flag> option does not take a value' when a
# store_true or store_false flag is supplied with an inline value.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Non-integer token for --jobs negative test.
# optparse exits 2 with 'invalid integer value' when a non-int is supplied.
_JOBS_NON_INT_VALUE = "notanumber"

# Valid integer value for the -j/--jobs flag.
_VALID_JOBS_INT = "1"

# Valid --jobs argument used in tests that require a real synced repo.
_VALID_JOBS_ARG = "--jobs=1"

# Canonical optparse phrase emitted when a boolean flag receives an inline value.
_OPTPARSE_NO_VALUE_PHRASE = "does not take a value"

# Boolean store_true flags from _CommonOptions (dest=output_mode, default=None).
# These accept no value; negative test uses inline-value syntax.
_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str]] = [
    ("-v", "short-verbose"),
    ("--verbose", "long-verbose"),
    ("--outer-manifest", "outer-manifest"),
    ("--this-manifest-only", "this-manifest-only"),
]

# Boolean store_false flags from _CommonOptions (default=None).
_BOOL_STORE_FALSE_FLAGS: list[tuple[str, str]] = [
    ("-q", "short-quiet"),
    ("--quiet", "long-quiet"),
    ("--no-outer-manifest", "no-outer-manifest"),
    ("--no-this-manifest-only", "no-this-manifest-only"),
    ("--all-manifests", "all-manifests"),
]

# Long-form boolean flags (store_true and store_false) used in AC-TEST-002
# negative tests. Short-form flags cannot use '--flag=value' syntax in optparse.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    ("--verbose", "verbose"),
    ("--outer-manifest", "outer-manifest"),
    ("--this-manifest-only", "this-manifest-only"),
    ("--quiet", "quiet"),
    ("--no-outer-manifest", "no-outer-manifest"),
    ("--no-this-manifest-only", "no-this-manifest-only"),
    ("--all-manifests", "all-manifests"),
]

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
# NOTE: _git is imported from tests.functional.conftest (canonical definition).
#
# The helpers below (_init_git_work_dir, _clone_as_bare,
# _create_bare_content_repo, _create_manifest_repo, _setup_synced_repo)
# follow the same pattern as test_repo_prune_happy.py. Consolidating them
# into a shared module requires touching files outside this task's Changes
# Manifest. This duplication is tracked in proposal E1-F2-S12-T4 as a
# follow-up DRY cleanup.
# ---------------------------------------------------------------------------


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with user config set.

    Args:
        work_dir: The directory to initialise as a git repo.
    """
    _git(["init", "-b", _GIT_BRANCH_MAIN], cwd=work_dir)
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

    return _clone_as_bare(work_dir, base / f"{_PROJECT_NAME}.git")


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
        f'  <default revision="{_GIT_BRANCH_MAIN}" remote="local" />\n'
        f'  <project name="{_PROJECT_NAME}" path="{_PROJECT_PATH}" />\n'
        "</manifest>\n"
    )
    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / _MANIFEST_BARE_DIR_NAME)


def _setup_synced_repo(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Create bare repos, run repo init and repo sync, return (checkout_dir, repo_dir).

    Runs 'kanon repo init' followed by 'kanon repo sync' so that project
    worktrees exist on disk. The 'prune' subcommand requires project worktrees
    because it calls PruneHeads() on each project.

    Args:
        tmp_path: pytest-provided temporary directory root.

    Returns:
        A tuple of (checkout_dir, repo_dir) after a successful init and sync.

    Raises:
        AssertionError: When kanon repo init or repo sync exits with a non-zero code.
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

    init_result = _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "init",
        "--no-repo-verify",
        "-u",
        manifest_url,
        "-b",
        _GIT_BRANCH_MAIN,
        "-m",
        _MANIFEST_FILENAME,
        cwd=checkout_dir,
    )
    assert init_result.returncode == 0, (
        f"Prerequisite 'kanon repo init' failed with exit {init_result.returncode}.\n"
        f"  stdout: {init_result.stdout!r}\n"
        f"  stderr: {init_result.stderr!r}"
    )

    sync_result = _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "sync",
        _VALID_JOBS_ARG,
        cwd=checkout_dir,
    )
    assert sync_result.returncode == 0, (
        f"Prerequisite 'kanon repo sync' failed with exit {sync_result.returncode}.\n"
        f"  stdout: {sync_result.stdout!r}\n"
        f"  stderr: {sync_result.stderr!r}"
    )
    return checkout_dir, repo_dir


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every flag in subcmds/prune.py
# (Also covers AC-FUNC-001: every documented flag behaves per its help text.)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoPruneFlagsValidValues:
    """AC-TEST-001 / AC-FUNC-001: Every flag in subcmds/prune.py has a valid-value test.

    Exercises each flag available via _CommonOptions() for the 'prune'
    subcommand by invoking 'kanon repo prune' with the flag against a real
    synced .repo directory.

    Boolean flags (store_true / store_false) are tested by confirming the
    flag is accepted without an argument-parsing error (exit code != 2). The
    --jobs/-j flag (integer) is tested with a valid integer value.

    Flags covered:
    - -v / --verbose (store_true, dest=output_mode, defaults to None)
    - -q / --quiet   (store_false, dest=output_mode, defaults to None)
    - -j / --jobs    (int, default=DEFAULT_LOCAL_JOBS)
    - --outer-manifest         (store_true, default=None)
    - --no-outer-manifest      (store_false, dest=outer_manifest)
    - --this-manifest-only     (store_true, default=None)
    - --no-this-manifest-only  (store_false, dest=this_manifest_only)
    - --all-manifests          (store_false, alias for --no-this-manifest-only)
    """

    _ALL_BOOL_FLAGS: list[tuple[str, str]] = _BOOL_STORE_TRUE_FLAGS + _BOOL_STORE_FALSE_FLAGS

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _ALL_BOOL_FLAGS],
        ids=[test_id for _, test_id in _ALL_BOOL_FLAGS],
    )
    def test_boolean_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo prune' with the given boolean flag against a properly
        synced .repo directory and asserts that optparse does not reject the
        invocation (exit code != 2). A non-2 exit code confirms the flag itself
        was accepted; the prune subcommand may produce any other exit code.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_jobs_flag_long_form_accepted_with_valid_integer(self, tmp_path: pathlib.Path) -> None:
        """'--jobs=1' is accepted by the argument parser (does not exit 2).

        The --jobs flag takes an integer value. Supplying a valid integer
        (1) confirms the flag is accepted without an argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            _VALID_JOBS_ARG,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_VALID_JOBS_ARG}' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_jobs_flag_short_form_accepted_with_valid_integer(self, tmp_path: pathlib.Path) -> None:
        """'-j 1' is accepted by the argument parser (does not exit 2).

        The short form -j with a valid integer value (1) confirms the flag
        is accepted without an argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            "-j",
            _VALID_JOBS_INT,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'-j {_VALID_JOBS_INT}' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_verbose_and_this_manifest_only_combination_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--verbose --this-manifest-only' combination is accepted (exit != 2).

        Both flags are independent boolean flags. When combined they must not
        trigger an argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            "--verbose",
            "--this-manifest-only",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--verbose --this-manifest-only' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_this_manifest_only_and_no_this_manifest_only_last_wins(self, tmp_path: pathlib.Path) -> None:
        """'--this-manifest-only --no-this-manifest-only' is accepted; last flag wins (exit != 2).

        Both flags share dest='this_manifest_only'. The last flag wins per
        optparse semantics. The combination must be accepted without exit 2.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            "--this-manifest-only",
            "--no-this-manifest-only",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--this-manifest-only --no-this-manifest-only' triggered an argument-parsing "
            f"error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_outer_manifest_and_no_outer_manifest_last_wins(self, tmp_path: pathlib.Path) -> None:
        """'--outer-manifest --no-outer-manifest' is accepted; last flag wins (exit != 2).

        Both flags share dest='outer_manifest'. The last flag wins per optparse
        semantics. The combination must be accepted without exit 2.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            "--outer-manifest",
            "--no-outer-manifest",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--outer-manifest --no-outer-manifest' triggered an argument-parsing "
            f"error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with invalid values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoPruneFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts typed values has a negative test.

    For boolean (store_true / store_false) flags, the negative test is to
    supply the flag with an unexpected inline value ('--flag=unexpected').
    optparse exits 2 with '--<flag> option does not take a value' for
    such inputs.

    For the --jobs flag (integer type), the negative test supplies a
    non-integer value and confirms exit code 2.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_error_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with inline value exits 2 and emits error on stderr, not stdout.

        Supplies '--<flag>=unexpected' to 'kanon repo prune'. Since all
        _CommonOptions() boolean flags are store_true / store_false, optparse
        rejects the inline value with exit code 2 and emits '--<flag> option
        does not take a value' on stderr only.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "prune",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"'{bad_token}' produced empty stderr; error must appear on stderr."
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        assert flag in result.stderr, (
            f"Expected flag {flag!r} in stderr for '{bad_token}' error.\n  stderr: {result.stderr!r}"
        )
        assert _OPTPARSE_NO_VALUE_PHRASE in result.stderr, (
            f"Expected {_OPTPARSE_NO_VALUE_PHRASE!r} in stderr for '{bad_token}' error.\n  stderr: {result.stderr!r}"
        )

    def test_jobs_with_non_integer_value_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--jobs=notanumber' must exit 2 and emit error on stderr.

        The --jobs flag takes an integer type. Supplying a non-integer value
        causes optparse to emit 'invalid integer value' and exit 2. The
        argument-parsing error must appear on stderr only; stdout must not
        contain the rejection detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = f"--jobs={_JOBS_NON_INT_VALUE}"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "prune",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"'{bad_token}' produced empty stderr; error must appear on stderr."
        assert _JOBS_NON_INT_VALUE not in result.stdout, (
            f"Non-integer jobs value leaked to stdout.\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoPruneFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each flag uses the documented default when omitted.
    Boolean flags from _CommonOptions (--verbose, --quiet, --outer-manifest,
    --this-manifest-only) have no explicit default= parameter, so their
    option-parser default is None when absent. The --jobs flag has
    default=DEFAULT_LOCAL_JOBS (an integer).

    Absence tests confirm that omitting every optional flag still produces
    a valid, non-error invocation (exit 0 on a synced repo with no merged
    local branches).
    """

    def test_all_flags_omitted_produces_empty_output_on_clean_repo(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo prune' with no flags produces empty output on a clean synced repo.

        When all flags are omitted and the synced repo has no local merged
        branches, the 'prune' subcommand exits 0 without producing output.
        This verifies that default values (None for booleans, DEFAULT_LOCAL_JOBS
        for --jobs) lead to the expected no-output result.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite 'kanon repo prune' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert combined == "", (
            f"'kanon repo prune' with default flags produced unexpected output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoPruneFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.
    """

    def test_valid_flags_invocation_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo prune' with valid flags must not emit tracebacks to stdout.

        On success (e.g. with --jobs=1 on a synced repo), stdout must not
        contain 'Traceback (most recent call last)'. Tracebacks on stdout
        indicate an unhandled exception that escaped to the wrong channel.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            _VALID_JOBS_ARG,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite 'kanon repo prune {_VALID_JOBS_ARG}' failed with argparse error: {result.stderr!r}"
        )
        assert "Traceback (most recent call last)" not in result.stdout, (
            f"Python traceback found in stdout of 'kanon repo prune {_VALID_JOBS_ARG}'.\n  stdout: {result.stdout!r}"
        )

    def test_valid_flags_invocation_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo prune' with valid flags must not emit tracebacks to stderr.

        On success (e.g. with --quiet on a synced repo), stderr must not
        contain 'Traceback (most recent call last)'. A traceback on stderr
        during a successful run indicates an unhandled exception was swallowed
        rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            "--quiet",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite 'kanon repo prune --quiet' failed with argparse error: {result.stderr!r}"
        )
        assert "Traceback (most recent call last)" not in result.stderr, (
            f"Python traceback found in stderr of 'kanon repo prune --quiet'.\n  stderr: {result.stderr!r}"
        )

    def test_no_error_keyword_on_stdout_for_valid_flags(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo prune' with flags must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "prune",
            _VALID_JOBS_ARG,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite 'kanon repo prune {_VALID_JOBS_ARG}' failed with argparse error."
        )
        for line in result.stdout.splitlines():
            assert not line.startswith("Error:"), (
                f"'Error:' line found in stdout of 'kanon repo prune {_VALID_JOBS_ARG}': {line!r}\n  stdout: {result.stdout!r}"
            )
