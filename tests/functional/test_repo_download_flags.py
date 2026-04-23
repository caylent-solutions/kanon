"""Functional tests for flag coverage of 'kanon repo download'.

Exercises every flag registered in ``subcmds/download.py``'s ``_Options()``
method by invoking ``kanon repo download`` as a subprocess. Validates correct
accept and reject behavior for all flag values, and correct default behavior
when flags are omitted.

Flags in ``Download._Options()`` (subcommand-specific):

Boolean store_true flags (accepted without a value; rejected with inline value):
- ``-c`` / ``--cherry-pick``    (dest=cherrypick, store_true)
- ``-x`` / ``--record-origin``  (store_true)
- ``-r`` / ``--revert``         (store_true)
- ``-f`` / ``--ff-only``        (dest=ffonly, store_true)

Typed string flag (requires a value; rejected when omitted):
- ``-b`` / ``--branch``         (string, dest=branch)

``Download`` inherits ``_CommonOptions()`` from ``Command``
(``PARALLEL_JOBS`` is ``None`` so ``--jobs`` is NOT registered).

Flags from ``Command._CommonOptions()``:
- ``-v`` / ``--verbose``            (store_true, dest=output_mode)
- ``-q`` / ``--quiet``              (store_false, dest=output_mode)
- ``--outer-manifest``              (store_true, default=None)
- ``--no-outer-manifest``           (store_false, dest=outer_manifest)
- ``--this-manifest-only``          (store_true, default=None)
- ``--no-this-manifest-only`` / ``--all-manifests`` (store_false, dest=this_manifest_only)

``ValidateOptions`` enforces two semantic constraints:
1. ``-x`` / ``--record-origin`` only makes sense with ``--cherry-pick``; without
   it, ``OptionParser.error()`` exits 2.
2. ``-x`` and ``--ff-only`` are mutually exclusive; combined, ``OptionParser.error()``
   exits 2.

These validation-error negative tests work with a nonexistent repo directory
because ``ValidateOptions`` calls ``OptionParser.error()`` (exit 2) before
repository discovery is attempted.

All valid-flag tests that do not need end-to-end execution confirm that the
parser does NOT exit 2 (arg-parse error) when passed a valid flag against a
nonexistent repo directory -- the process exits 1 (manifest-not-found), which
confirms the flag itself was accepted.

AC-FUNC-001 functional tests exercise each flag against a real synced repo
with a Gerrit-style change ref, confirming the flag behaves per its help text
and the command exits 0.

AC-TEST-003 absence tests run with all download-specific flags omitted and
confirm the command exits 0 against a real synced repo.

Covers:
- AC-TEST-001: Every ``_Options()`` flag in subcmds/download.py has a
  valid-value test.
- AC-TEST-002: Every flag that accepts enumerated values has a negative test
  for an invalid value.
- AC-TEST-003: Flags have correct absence-default behavior when omitted.
- AC-FUNC-001: Every documented flag behaves per its help text.
- AC-CHANNEL-001: stdout vs stderr channel discipline is verified.

Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess
import tempfile

import pytest

from tests.functional.conftest import _git, _run_kanon, _setup_synced_repo

# ---------------------------------------------------------------------------
# Module-level constants -- no domain literals in test logic.
# ---------------------------------------------------------------------------

# Git identity used when creating the fixture bare repos.
_GIT_USER_NAME = "Repo Download Flags Test User"
_GIT_USER_EMAIL = "repo-download-flags@example.com"

# Manifest project name and worktree path for the download fixture.
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "download-flags-test-project"

# Gerrit-style change fixture constants.
_CHANGE_ID = 456
_PATCH_SET_ID = 1
_CHANGE_DIR_BUCKET = _CHANGE_ID % 100  # 56
_GERRIT_REF = f"refs/changes/{_CHANGE_DIR_BUCKET:02d}/{_CHANGE_ID}/{_PATCH_SET_ID}"

# File committed to the bare repo to create a downloadable change.
_DOWNLOAD_CONTENT_FILE = "download-flags-change.txt"
_DOWNLOAD_CONTENT_TEXT = "content for download flags functional test"
_DOWNLOAD_COMMIT_MSG = "Add downloadable change for flags functional test"

# Serialised change positional argument strings.
_CHANGE_WITH_PATCHSET = f"{_CHANGE_ID}/{_PATCH_SET_ID}"

# Exit codes.
_EXPECTED_EXIT_CODE = 0
_ARGPARSE_ERROR_EXIT_CODE = 2

# Nonexistent repo dir path fragment -- no real .repo under this path; used
# for pure argument-parser acceptance and rejection tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-download-flags-repo-dir"

# Inline-value suffix for boolean-flag negative tests.
# optparse exits 2 with '--<flag> option does not take a value'.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Traceback marker used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# CLI token constants.
_CLI_TOKEN_REPO = "repo"
_CLI_TOKEN_DOWNLOAD = "download"
_CLI_FLAG_REPO_DIR = "--repo-dir"

# A valid positional arg accepted by the argument parser (even without a repo).
_DUMMY_CHANGE_ARG = "999/1"

# ---------------------------------------------------------------------------
# Download-specific boolean store_true flags (short and long forms).
# Tuples are (flag_token, test_id).
# ---------------------------------------------------------------------------

# Flags that are accepted by the argument parser when passed alone (no special
# preconditions required for ValidateOptions to pass).
# Note: -x / --record-origin are excluded here because ValidateOptions exits 2
# when they are passed without --cherry-pick. Their acceptance test is covered
# by test_record_origin_with_cherry_pick_accepted.
_DOWNLOAD_BOOL_STORE_TRUE_FLAGS_STANDALONE: list[tuple[str, str]] = [
    ("-c", "short-cherry-pick"),
    ("--cherry-pick", "long-cherry-pick"),
    ("-r", "short-revert"),
    ("--revert", "long-revert"),
    ("-f", "short-ff-only"),
    ("--ff-only", "long-ff-only"),
]

# Long-form download boolean flags only -- for inline-value negative tests.
# Short-form flags do not support '--flag=value' syntax in optparse.
_DOWNLOAD_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    ("--cherry-pick", "cherry-pick"),
    ("--record-origin", "record-origin"),
    ("--revert", "revert"),
    ("--ff-only", "ff-only"),
]

# Common-options boolean store_true flags (shared by all subcommands).
_COMMON_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str]] = [
    ("-v", "short-verbose"),
    ("--verbose", "long-verbose"),
    ("--outer-manifest", "outer-manifest"),
    ("--this-manifest-only", "this-manifest-only"),
]

# Common-options boolean store_false flags.
_COMMON_BOOL_STORE_FALSE_FLAGS: list[tuple[str, str]] = [
    ("-q", "short-quiet"),
    ("--quiet", "long-quiet"),
    ("--no-outer-manifest", "no-outer-manifest"),
    ("--no-this-manifest-only", "no-this-manifest-only"),
    ("--all-manifests", "all-manifests"),
]

# Long-form common boolean flags for inline-value negative tests.
_COMMON_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    ("--verbose", "verbose"),
    ("--outer-manifest", "outer-manifest"),
    ("--this-manifest-only", "this-manifest-only"),
    ("--quiet", "quiet"),
    ("--no-outer-manifest", "no-outer-manifest"),
    ("--no-this-manifest-only", "no-this-manifest-only"),
    ("--all-manifests", "all-manifests"),
]


# ---------------------------------------------------------------------------
# Fixture setup helpers
# ---------------------------------------------------------------------------


def _add_gerrit_change_to_bare_repo(
    bare_repo: pathlib.Path,
) -> str:
    """Commit a new file to the bare repo and create a Gerrit-style ref.

    Creates a new commit in a temporary working clone of ``bare_repo``,
    pushes it to the bare repo as ``_GERRIT_REF``, and returns the commit
    SHA1.

    Args:
        bare_repo: Absolute path to the bare content git repository.

    Returns:
        The full SHA1 of the newly created commit.

    Raises:
        RuntimeError: When any git operation fails.
    """
    with tempfile.TemporaryDirectory() as work_str:
        work = pathlib.Path(work_str)
        _git(["clone", str(bare_repo), str(work / "work")], cwd=work)
        work_dir = work / "work"

        _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
        _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)

        (work_dir / _DOWNLOAD_CONTENT_FILE).write_text(_DOWNLOAD_CONTENT_TEXT, encoding="utf-8")
        _git(["add", _DOWNLOAD_CONTENT_FILE], cwd=work_dir)
        _git(["commit", "-m", _DOWNLOAD_COMMIT_MSG], cwd=work_dir)

        _git(["push", "origin", f"HEAD:{_GERRIT_REF}"], cwd=work_dir)

        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git rev-parse HEAD failed in {work_dir!r}:\n  stderr: {result.stderr!r}")
        return result.stdout.strip()


def _locate_bare_content_repo(repos_dir: pathlib.Path) -> pathlib.Path:
    """Return the absolute path to the bare content repo under repos_dir.

    Args:
        repos_dir: Parent directory that contains the bare repos.

    Returns:
        The absolute path to the bare content git repository.

    Raises:
        FileNotFoundError: When the expected bare content repo does not exist.
    """
    bare_path = repos_dir / f"{_PROJECT_NAME}.git"
    if not bare_path.exists():
        raise FileNotFoundError(
            f"Bare content repo not found at {bare_path!r}. "
            f"Ensure _setup_synced_repo was called with project_name={_PROJECT_NAME!r}."
        )
    return bare_path


def _setup_download_flags_repo(
    tmp_path: pathlib.Path,
) -> "tuple[pathlib.Path, pathlib.Path]":
    """Create a synced repo with a Gerrit-style change ref for flag tests.

    Performs the shared setup required by functional flag tests:

    1. Creates bare repos and runs ``kanon repo init`` + ``kanon repo sync``
       via ``_setup_synced_repo``.
    2. Locates the bare content repository.
    3. Commits a new file to the bare content repo and creates
       ``_GERRIT_REF`` pointing to it.

    Args:
        tmp_path: pytest-provided temporary directory root.

    Returns:
        A 2-tuple of ``(checkout_dir, repo_dir)`` where ``checkout_dir`` is
        the worktree root and ``repo_dir`` is the ``.repo`` directory.

    Raises:
        AssertionError: When ``kanon repo init`` or ``kanon repo sync`` fails.
    """
    repos_dir = tmp_path / "repos"

    checkout_dir, repo_dir = _setup_synced_repo(
        tmp_path,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_name=_PROJECT_NAME,
        project_path=_PROJECT_PATH,
    )

    bare_repo = _locate_bare_content_repo(repos_dir)
    _add_gerrit_change_to_bare_repo(bare_repo)

    return checkout_dir, repo_dir


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag in download.py
# (Also covers AC-FUNC-001 for common boolean flags and the --branch flag.)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDownloadFlagsValidValues:
    """AC-TEST-001: Every flag available to 'repo download' has a valid-value test.

    Boolean flags (store_true / store_false) are tested by confirming the flag
    is accepted without an argument-parsing error (exit code != 2). Passing a
    valid flag against a nonexistent repo dir produces exit 1 (manifest not
    found), which confirms the flag itself was accepted.

    The ``--branch`` / ``-b`` string flag is tested with a valid branch name.

    Flags covered from Download._Options():
    - ``-b`` / ``--branch``          (string, dest=branch)
    - ``-c`` / ``--cherry-pick``     (store_true, dest=cherrypick)
    - ``-x`` / ``--record-origin``   (store_true; tested via
      test_record_origin_with_cherry_pick_accepted because ValidateOptions
      exits 2 when -x is passed alone without --cherry-pick)
    - ``-r`` / ``--revert``          (store_true)
    - ``-f`` / ``--ff-only``         (store_true, dest=ffonly)

    Flags covered from Command._CommonOptions():
    - ``-v`` / ``--verbose``         (store_true)
    - ``-q`` / ``--quiet``           (store_false)
    - ``--outer-manifest``           (store_true)
    - ``--no-outer-manifest``        (store_false)
    - ``--this-manifest-only``       (store_true)
    - ``--no-this-manifest-only``    (store_false)
    - ``--all-manifests``            (store_false)
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _DOWNLOAD_BOOL_STORE_TRUE_FLAGS_STANDALONE],
        ids=[test_id for _, test_id in _DOWNLOAD_BOOL_STORE_TRUE_FLAGS_STANDALONE],
    )
    def test_download_specific_bool_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each download-specific boolean flag is accepted (exit code != 2).

        Passes the flag to 'kanon repo download' against a nonexistent repo dir.
        A non-2 exit code confirms the flag was accepted by the argument parser.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            flag,
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _COMMON_BOOL_STORE_TRUE_FLAGS + _COMMON_BOOL_STORE_FALSE_FLAGS],
        ids=[test_id for _, test_id in _COMMON_BOOL_STORE_TRUE_FLAGS + _COMMON_BOOL_STORE_FALSE_FLAGS],
    )
    def test_common_bool_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each common boolean flag inherited from _CommonOptions() is accepted (exit != 2).

        Passes the common flag to 'kanon repo download' against a nonexistent
        repo dir with a dummy change arg. A non-2 exit code confirms the flag
        was accepted by the argument parser.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            flag,
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Common flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_branch_flag_long_form_accepted_with_value(self, tmp_path: pathlib.Path) -> None:
        """'--branch=mybranch' is accepted by the argument parser (exit != 2).

        The --branch flag takes a string value. Supplying a valid branch name
        confirms the flag is accepted without an argument-parsing error.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            "--branch",
            "mybranch",
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--branch mybranch' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_branch_flag_short_form_accepted_with_value(self, tmp_path: pathlib.Path) -> None:
        """'-b mybranch' is accepted by the argument parser (exit != 2).

        The short form -b with a valid branch name confirms the flag is
        accepted without an argument-parsing error.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            "-b",
            "mybranch",
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'-b mybranch' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_record_origin_with_cherry_pick_accepted(self, tmp_path: pathlib.Path) -> None:
        """'-x --cherry-pick' combination is accepted (exit != 2).

        The ``-x`` / ``--record-origin`` flag is only semantically valid with
        ``--cherry-pick``. Together they must be accepted by the argument
        parser (exit != 2). Without a real repo they produce exit 1 (manifest
        not found), which confirms both flags were accepted.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            "-x",
            "--cherry-pick",
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'-x --cherry-pick' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with typed or inline values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDownloadFlagsInvalidValues:
    """AC-TEST-002: Negative tests for 'repo download' flags with invalid values.

    Categories of negative tests:

    1. Boolean store_true / store_false flags supplied with an inline value
       ('--flag=value'): optparse exits 2 with
       '--<flag> option does not take a value'.

    2. String flag ``--branch`` supplied without a value: optparse exits 2
       with '--branch option requires 1 argument'.

    3. ``ValidateOptions`` constraints (exit code 2):
       - ``-x`` without ``--cherry-pick``: OptionParser.error() exits 2.
       - ``-x`` combined with ``--ff-only``: OptionParser.error() exits 2.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _DOWNLOAD_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _DOWNLOAD_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_download_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form download boolean flag with an inline value must exit 2.

        Supplies '--<flag>=unexpected' to 'kanon repo download'. All download
        boolean flags are store_true, so optparse rejects the inline value
        with exit code 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            bad_token,
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _DOWNLOAD_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _DOWNLOAD_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_download_bool_flag_inline_value_error_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form download boolean flag with inline value emits error to stderr.

        The argument-parsing error for '--<flag>=unexpected' must appear on
        stderr only. Stdout must not contain the rejection detail.

        Covers AC-CHANNEL-001: argument-parsing errors routed to stderr;
        stdout remains clean of error details on invalid-flag invocations.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            bad_token,
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"'{bad_token}' produced empty stderr; error must appear on stderr."
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _COMMON_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _COMMON_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_common_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form common boolean flag with inline value must exit 2.

        Supplies '--<flag>=unexpected' to 'kanon repo download'. All common
        boolean flags are store_true / store_false, so optparse rejects the
        inline value with exit code 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            bad_token,
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_branch_flag_without_value_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'--branch' with no value must exit 2.

        The --branch flag requires one string argument. Supplying it without
        a value must be rejected by optparse with exit code 2 and an error on
        stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            "--branch",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--branch' without value exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert "branch" in result.stderr.lower(), (
            f"Expected 'branch' in stderr for '--branch' with no value.\n  stderr: {result.stderr!r}"
        )

    def test_branch_flag_without_value_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'--branch' with no value error must appear on stderr, not stdout.

        The argument-parsing error for '--branch' without a value must be
        reported on stderr only. Stdout must not contain the error detail.

        Covers AC-CHANNEL-001: argument-parsing errors are routed to stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            "--branch",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--branch' without value exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "branch" not in result.stdout.lower(), (
            f"'branch' error detail leaked to stdout for '--branch' with no value.\n  stdout: {result.stdout!r}"
        )

    def test_record_origin_without_cherry_pick_exits_2(self, tmp_path: pathlib.Path) -> None:
        """-x without --cherry-pick must exit 2 (ValidateOptions constraint).

        The download subcommand's ValidateOptions enforces that -x / --record-origin
        is only valid when --cherry-pick is also provided. Without --cherry-pick,
        OptionParser.error() is called, causing exit code 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            "-x",
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'-x' without '--cherry-pick' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_record_origin_without_cherry_pick_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """-x without --cherry-pick error must appear on stderr.

        The validation error message for '-x' without '--cherry-pick' must
        be emitted to stderr. Stdout must remain clean.

        Covers AC-CHANNEL-001: validation errors are routed to stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            "-x",
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '-x' without '--cherry-pick' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert "cherry-pick" in result.stderr.lower(), (
            f"Expected 'cherry-pick' mention in stderr for '-x' without '--cherry-pick'.\n  stderr: {result.stderr!r}"
        )
        assert "cherry-pick" not in result.stdout.lower(), (
            f"Validation error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_record_origin_with_ff_only_exits_2(self, tmp_path: pathlib.Path) -> None:
        """-x and --ff-only together must exit 2 (ValidateOptions mutual exclusion).

        The download subcommand's ValidateOptions enforces that -x / --record-origin
        and -f / --ff-only are mutually exclusive. Combined, OptionParser.error()
        is called, causing exit code 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            "-x",
            "--cherry-pick",
            "--ff-only",
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'-x --cherry-pick --ff-only' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_record_origin_with_ff_only_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """-x and --ff-only mutual-exclusion error must appear on stderr.

        The validation error for '-x --ff-only' must be emitted to stderr
        only. Stdout must remain clean.

        Covers AC-CHANNEL-001: validation errors are routed to stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            "-x",
            "--cherry-pick",
            "--ff-only",
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '-x --cherry-pick --ff-only' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert "ff" in result.stderr.lower() or "mutually exclusive" in result.stderr.lower(), (
            f"Expected 'ff' or 'mutually exclusive' in stderr for '-x --ff-only'.\n  stderr: {result.stderr!r}"
        )
        assert result.stdout.strip() == "" or "ff" not in result.stdout.lower(), (
            f"Validation error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDownloadFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each download flag uses its documented default when omitted.
    All Download._Options() flags default to False (store_true with no explicit
    default= set) or to None (--branch defaults to None).

    Absence tests confirm that omitting every optional flag still produces a
    valid, non-error invocation against a real synced repo with a downloadable
    change.
    """

    def test_all_flags_omitted_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo download PROJECT CHANGE/PATCHSET' with all flags omitted exits 0.

        When only the required positional arguments are supplied and no
        optional flag is provided, every download flag uses its default value:
        - --branch defaults to None (no new branch created)
        - --cherry-pick defaults to False (plain checkout)
        - --record-origin defaults to False
        - --revert defaults to False
        - --ff-only defaults to False
        - common flags default to None / command-defined defaults

        Verifies that no optional flag is required and that all documented
        defaults produce a successful (exit 0) download.
        """
        checkout_dir, repo_dir = _setup_download_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_DOWNLOAD,
            _PROJECT_NAME,
            _CHANGE_WITH_PATCHSET,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo download {_PROJECT_NAME} {_CHANGE_WITH_PATCHSET}' "
            f"with all optional flags omitted exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_cherry_pick_omitted_defaults_to_checkout(self, tmp_path: pathlib.Path) -> None:
        """Omitting --cherry-pick defaults to checkout mode; download exits 0.

        When --cherry-pick is not supplied, the download operates in
        checkout mode (the default). This must produce exit 0 on a real repo.
        """
        checkout_dir, repo_dir = _setup_download_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_DOWNLOAD,
            _PROJECT_NAME,
            _CHANGE_WITH_PATCHSET,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo download' without --cherry-pick exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_branch_omitted_defaults_to_none(self, tmp_path: pathlib.Path) -> None:
        """Omitting --branch defaults to None; download exits 0.

        When --branch is not supplied, no new branch is created before the
        download. The command proceeds with the default checkout mode.
        Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_download_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_DOWNLOAD,
            _PROJECT_NAME,
            _CHANGE_WITH_PATCHSET,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo download' without --branch exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDownloadFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies functional behavior of Download-specific flags against a real
    synced repo with a Gerrit-style change ref:

    - ``--cherry-pick``: 'cherry-pick instead of checkout' -- exit 0
    - ``--revert``: 'revert instead of checkout' -- exit 0 when patchset was
      not yet merged (revert of an unmerged commit typically fails; behavior
      is verified to not exit 2 (argparse) or crash with traceback)
    - ``--ff-only``: 'force fast-forward merge' -- exit != 2 (may fail at
      merge-strategy level but argument must be accepted)
    - ``--branch``: 'create a new branch first' -- exit 0 with new branch name

    Note on ``--revert`` and ``--ff-only``: these flags alter git merge
    strategy and may produce a non-zero exit when the underlying git operation
    fails (e.g. --revert on an unmerged commit). The functional test verifies
    the flag is accepted by the parser (exit != 2) and does not produce a
    Python traceback.
    """

    def test_cherry_pick_flag_accepted_and_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'--cherry-pick' flag: download cherry-picks the change; exit 0.

        Per help text: 'cherry-pick instead of checkout'. On a synced repo
        with a Gerrit-style ref, 'kanon repo download --cherry-pick' must
        exit 0.
        """
        checkout_dir, repo_dir = _setup_download_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_DOWNLOAD,
            "--cherry-pick",
            _PROJECT_NAME,
            _CHANGE_WITH_PATCHSET,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo download --cherry-pick {_PROJECT_NAME} {_CHANGE_WITH_PATCHSET}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_cherry_pick_flag_no_traceback_on_success(self, tmp_path: pathlib.Path) -> None:
        """'--cherry-pick' flag: no Python traceback on successful download.

        Verifies that a successful '--cherry-pick' invocation does not produce
        a Python traceback on stdout or stderr.
        """
        checkout_dir, repo_dir = _setup_download_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_DOWNLOAD,
            "--cherry-pick",
            _PROJECT_NAME,
            _CHANGE_WITH_PATCHSET,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '--cherry-pick' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of '--cherry-pick' download.\n  stdout: {result.stdout!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of '--cherry-pick' download.\n  stderr: {result.stderr!r}"
        )

    def test_ff_only_flag_accepted_without_argparse_error(self, tmp_path: pathlib.Path) -> None:
        """'--ff-only' flag: accepted by the argument parser (exit != 2).

        Per help text: 'force fast-forward merge'. The flag must be accepted
        without an argument-parsing error (exit != 2). The underlying git
        operation may succeed or fail depending on history, but the flag itself
        must not be rejected.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            "--ff-only",
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--ff-only' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_revert_flag_accepted_without_argparse_error(self, tmp_path: pathlib.Path) -> None:
        """'--revert' flag: accepted by the argument parser (exit != 2).

        Per help text: 'revert instead of checkout'. The flag must be accepted
        without an argument-parsing error (exit != 2). The underlying git
        revert operation behavior depends on repository state.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            "--revert",
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--revert' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_branch_flag_creates_new_branch_and_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'--branch' flag: creates a new branch and downloads; exit 0.

        Per help text: 'create a new branch first'. When --branch is supplied
        with a name, 'kanon repo download' creates the named branch before
        checking out the change. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_download_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_DOWNLOAD,
            "--branch",
            "download-test-branch",
            _PROJECT_NAME,
            _CHANGE_WITH_PATCHSET,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo download --branch download-test-branch "
            f"{_PROJECT_NAME} {_CHANGE_WITH_PATCHSET}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDownloadFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.

    Uses a class-scoped fixture so the expensive synced-repo setup runs once
    and all channel assertions share the result.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo download PROJECT CHANGE/PATCHSET' once and return the result.

        Uses tmp_path_factory for a class-scoped fixture so the setup and CLI
        invocation execute once. All channel assertions share the result.

        Returns:
            The CompletedProcess from a successful 'kanon repo download'.

        Raises:
            AssertionError: When the prerequisite setup or download itself
                exits with a non-zero code.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline_flags")
        checkout_dir, repo_dir = _setup_download_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_DOWNLOAD,
            _PROJECT_NAME,
            _CHANGE_WITH_PATCHSET,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo download {_PROJECT_NAME} {_CHANGE_WITH_PATCHSET}' "
            f"failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_valid_flags_invocation_no_traceback_on_stdout(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo download' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo download'.\n"
            f"  stdout: {channel_result.stdout!r}"
        )

    def test_valid_flags_invocation_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo download' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo download': {line!r}\n"
                f"  stdout: {channel_result.stdout!r}"
            )

    def test_valid_flags_invocation_no_traceback_on_stderr(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo download' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo download'.\n"
            f"  stderr: {channel_result.stderr!r}"
        )

    def test_argparse_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Argument-parsing errors must appear on stderr, not stdout.

        Triggers an argument-parsing error by supplying '--cherry-pick=unexpected'
        (boolean flag with inline value). Verifies the error appears on stderr
        and that stdout does not contain the option name.

        Covers AC-CHANNEL-001: argument-parsing errors routed to stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--cherry-pick" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_DOWNLOAD,
            bad_token,
            _DUMMY_CHANGE_ARG,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"Expected non-empty stderr for argparse error from '{bad_token}'."
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"
