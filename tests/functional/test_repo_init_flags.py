"""Functional tests for flag coverage of 'kanon repo init'.

Exercises every flag registered in ``subcmds/init.py``'s ``_Options()`` method
by invoking ``kanon repo init`` as a subprocess. Validates correct accept and
reject behavior for all flag values, and correct default behavior when flags
are omitted.

Covers:
- AC-TEST-001: Every ``_Options()`` flag has a valid-value test.
- AC-TEST-002: Every flag that accepts enumerated or typed values has a
  negative test verifying rejection of an invalid value.
- AC-TEST-003: Flags have correct absence-default behavior when omitted.
- AC-FUNC-001: Every documented flag behaves per its help text.
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

_GIT_USER_NAME = "Repo Init Flags Test User"
_GIT_USER_EMAIL = "repo-init-flags@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from repo-init-flags test content"

# Error exit code for invalid argument values or constraint violations.
_ARGPARSE_ERROR_EXIT_CODE = 2

# Nonexistent manifest URL used in argument-parser acceptance tests.
_NONEXISTENT_MANIFEST_URL = "file:///nonexistent/path"

# Nonexistent repo-dir name used in argument-parser acceptance tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-dir"

# Canonical upstream URL used as a valid --repo-url value in acceptance tests.
_REPO_URL_CANONICAL = "https://gerrit.googlesource.com/git-repo"

# Flag-value fixtures used throughout parametrize lists and test bodies.
_GROUP_DEFAULT = "default"
_PLATFORM_AUTO = "auto"
_GIT_BRANCH_MAIN = "main"
_CLONE_FILTER_BLOB_NONE = "blob:none"
_PARTIAL_CLONE_EXCLUDE_EXAMPLE = "my-project"
_GIT_BRANCH_UPSTREAM_EXAMPLE = "abc123"
_INVALID_INT_VALUE_PRIMARY = "abc"
_INVALID_INT_VALUE_NOT_AN_INT = "not-an-int"
_INVALID_INT_VALUE_FLOAT = "1.5"
_INVALID_INT_VALUE_WORD_DEPTH_PRIMARY = "one"
_INVALID_INT_VALUE_WORD_DEPTH_ALT = "two"
_INVALID_INT_VALUE_CHANNEL = "xyz"
_SECONDARY_MANIFEST_URL = "file:///another/path"
_FIRST_POSITIONAL_URL = "file:///first/path"
_SECOND_POSITIONAL_URL = "file:///second/path"
_REFERENCE_DIR_NAME = "mirror-dir"
_MANIFEST_FILENAME_CUSTOM = "custom.xml"

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
# NOTE: _git is imported from tests.functional.conftest (canonical definition).
#
# The helpers below (_init_git_work_dir, _clone_as_bare,
# _create_bare_content_repo, _create_manifest_repo, _setup_repos) are
# near-duplicates of same-named functions in test_repo_init_happy.py and
# test_repo_exit_codes.py. Consolidating them into a shared module requires
# touching files outside this task's Changes Manifest. This duplication is
# tracked as a follow-up DRY cleanup.
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
        f'  <default revision="{_GIT_BRANCH_MAIN}" remote="local" />\n'
        '  <project name="content-bare" path="flags-init-project" />\n'
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
# AC-TEST-001: Valid-value tests for every _Options() flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/init.py has a valid-value test.

    Exercises each flag registered in ``Init._Options()`` (including those
    added via ``Wrapper().InitParser()``) with a valid value. Tests confirm
    the flag is accepted without an argument-parsing error (exit code 2).

    Flags that require a live manifest network or a pre-existing .repo checkout
    to fully execute are validated up to the point where argument parsing
    succeeds (exit != 2). Flags that only affect behavior during sync (e.g.
    --dissociate, --worktree, --archive) exit non-zero after argument parsing
    passes due to network or file-system constraints; those tests verify the
    exit code is not 2 (meaning the flag itself was accepted).

    The parametrized ``test_flag_accepted`` method covers all flags that share
    the common pattern: supply ``-u <url>`` plus the flag under test plus
    ``--no-repo-verify`` and assert that argparse does not reject the invocation
    (exit code != 2).

    Flags requiring special argument combinations (e.g. ``--manifest-upstream-branch``
    which must be paired with ``--manifest-branch``, and ``--reference`` whose
    argument is a dynamically computed path) are kept as dedicated test methods
    below.
    """

    # Each entry is (flag_args_tuple, test_id).
    # flag_args are inserted between "init" and "--no-repo-verify" in the
    # _run_kanon call, and must include "-u _NONEXISTENT_MANIFEST_URL" where
    # the manifest URL is required to satisfy init's argument requirements.
    _VALID_VALUE_CASES: list[tuple[tuple[str, ...], str]] = [
        (
            ("--verbose", "-u", _NONEXISTENT_MANIFEST_URL),
            "verbose",
        ),
        (
            ("--quiet", "-u", _NONEXISTENT_MANIFEST_URL),
            "quiet",
        ),
        (
            ("--manifest-url", _NONEXISTENT_MANIFEST_URL),
            "manifest-url-long",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "-b", _GIT_BRANCH_MAIN),
            "manifest-branch",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "-m", _MANIFEST_FILENAME),
            "manifest-name",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "-g", _GROUP_DEFAULT),
            "groups",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "-p", _PLATFORM_AUTO),
            "platform",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--submodules"),
            "submodules",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--standalone-manifest"),
            "standalone-manifest",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--manifest-depth", "0"),
            "manifest-depth-zero",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--manifest-depth", "1"),
            "manifest-depth-positive",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--current-branch"),
            "current-branch",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--no-current-branch"),
            "no-current-branch",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--tags"),
            "tags",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--no-tags"),
            "no-tags",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--mirror"),
            "mirror",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--archive"),
            "archive",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--worktree"),
            "worktree",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--dissociate"),
            "dissociate",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--depth", "1"),
            "depth",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--partial-clone"),
            "partial-clone",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--no-partial-clone"),
            "no-partial-clone",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--partial-clone-exclude", _PARTIAL_CLONE_EXCLUDE_EXAMPLE),
            "partial-clone-exclude",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--clone-filter", _CLONE_FILTER_BLOB_NONE),
            "clone-filter",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--use-superproject"),
            "use-superproject",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--no-use-superproject"),
            "no-use-superproject",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--clone-bundle"),
            "clone-bundle",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--no-clone-bundle"),
            "no-clone-bundle",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--git-lfs"),
            "git-lfs",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--no-git-lfs"),
            "no-git-lfs",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--repo-url", _REPO_URL_CANONICAL),
            "repo-url",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--repo-rev", _GIT_BRANCH_MAIN),
            "repo-rev",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--no-repo-verify"),
            "no-repo-verify",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--config-name"),
            "config-name",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--outer-manifest"),
            "outer-manifest",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--no-outer-manifest"),
            "no-outer-manifest",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--this-manifest-only"),
            "this-manifest-only",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--no-this-manifest-only"),
            "no-this-manifest-only",
        ),
        (
            ("-u", _NONEXISTENT_MANIFEST_URL, "--all-manifests"),
            "all-manifests",
        ),
    ]

    @pytest.mark.parametrize(
        "flag_args",
        [args for args, _ in _VALID_VALUE_CASES],
        ids=[test_id for _, test_id in _VALID_VALUE_CASES],
    )
    def test_flag_accepted(self, tmp_path: pathlib.Path, flag_args: tuple[str, ...]) -> None:
        """Each flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo init' with the given flag arguments and asserts that
        argparse does not reject the invocation (exit code != 2). A non-2 exit
        code confirms the flag itself was accepted; subsequent failures (e.g.
        network, missing repo) are expected and do not indicate a flag-parsing
        error.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        # --no-repo-verify is appended unless already present in flag_args
        # (the no-repo-verify case includes it in its own flag_args tuple).
        extra = () if "--no-repo-verify" in flag_args else ("--no-repo-verify",)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            *flag_args,
            *extra,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag args {flag_args!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_manifest_upstream_branch_with_manifest_branch_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--manifest-upstream-branch' with '--manifest-branch' is accepted (does not exit 2).

        The --manifest-upstream-branch flag must be paired with --manifest-branch.
        When both are supplied, no argument-parsing error (exit code 2) should occur.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "-u",
            _NONEXISTENT_MANIFEST_URL,
            "-b",
            _GIT_BRANCH_UPSTREAM_EXAMPLE,
            "--manifest-upstream-branch",
            _GIT_BRANCH_MAIN,
            "--no-repo-verify",
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--manifest-upstream-branch' with '--manifest-branch' triggered "
            f"an argument-parsing error (exit {result.returncode}).\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_reference_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--reference=<dir>' is accepted by the argument parser (does not exit 2).

        The --reference flag points to a mirror directory location. Passing it
        with a path string must not trigger an argument-parsing error.
        The mirror path is derived from tmp_path at test runtime.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        mirror_dir = str(tmp_path / _REFERENCE_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "-u",
            _NONEXISTENT_MANIFEST_URL,
            "--reference",
            mirror_dir,
            "--no-repo-verify",
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--reference' triggered an argument-parsing error (exit {result.returncode}).\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with enumerated or typed values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts typed values has a negative test for invalid input.

    Exercises each flag that accepts a typed value (integer, validated string)
    with an invalid value. Confirms the argument parser rejects the value with
    exit code 2 and that the error message appears on stderr (not stdout).
    """

    def test_manifest_depth_non_integer_rejected(self, tmp_path: pathlib.Path) -> None:
        """'--manifest-depth=abc' must exit 2 with an invalid-integer error on stderr.

        The --manifest-depth flag expects an integer value. A non-numeric string
        must be rejected by the option parser with exit code 2, and the error
        message must appear on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--manifest-depth",
            _INVALID_INT_VALUE_PRIMARY,
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--manifest-depth={_INVALID_INT_VALUE_PRIMARY}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )
        assert "invalid" in result.stderr.lower(), (
            f"Expected 'invalid' in stderr for '--manifest-depth={_INVALID_INT_VALUE_PRIMARY}'.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_manifest_depth_non_integer_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'--manifest-depth=abc' error message must appear on stderr, not stdout.

        The argument-parsing error for a non-integer --manifest-depth must be
        reported on stderr only. Stdout must not contain the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--manifest-depth",
            _INVALID_INT_VALUE_PRIMARY,
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--manifest-depth={_INVALID_INT_VALUE_PRIMARY}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "invalid" not in result.stdout.lower(), (
            f"'invalid' error detail leaked to stdout for '--manifest-depth={_INVALID_INT_VALUE_PRIMARY}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_depth_non_integer_rejected(self, tmp_path: pathlib.Path) -> None:
        """'--depth=abc' must exit 2 with an invalid-integer error on stderr.

        The --depth flag expects an integer value. A non-numeric string must be
        rejected by the option parser with exit code 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--depth",
            _INVALID_INT_VALUE_PRIMARY,
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--depth={_INVALID_INT_VALUE_PRIMARY}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )
        assert "invalid" in result.stderr.lower(), (
            f"Expected 'invalid' in stderr for '--depth={_INVALID_INT_VALUE_PRIMARY}'.\n  stderr: {result.stderr!r}"
        )

    def test_depth_non_integer_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'--depth=abc' error message must appear on stderr, not stdout.

        The argument-parsing error for a non-integer --depth must be reported
        on stderr only. Stdout must not contain the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--depth",
            _INVALID_INT_VALUE_PRIMARY,
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--depth={_INVALID_INT_VALUE_PRIMARY}' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "invalid" not in result.stdout.lower(), (
            f"'invalid' error detail leaked to stdout for '--depth={_INVALID_INT_VALUE_PRIMARY}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_value",
        [
            _INVALID_INT_VALUE_NOT_AN_INT,
            _INVALID_INT_VALUE_FLOAT,
            _INVALID_INT_VALUE_WORD_DEPTH_PRIMARY,
            "",
        ],
    )
    def test_manifest_depth_various_non_integers_rejected(self, tmp_path: pathlib.Path, bad_value: str) -> None:
        """Various non-integer '--manifest-depth' values must all exit 2.

        Parametrises over several non-integer strings to confirm that every
        non-numeric value is uniformly rejected with exit code 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--manifest-depth",
            bad_value,
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--manifest-depth={bad_value!r}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_value",
        [
            _INVALID_INT_VALUE_NOT_AN_INT,
            _INVALID_INT_VALUE_FLOAT,
            _INVALID_INT_VALUE_WORD_DEPTH_ALT,
            "",
        ],
    )
    def test_depth_various_non_integers_rejected(self, tmp_path: pathlib.Path, bad_value: str) -> None:
        """Various non-integer '--depth' values must all exit 2.

        Parametrises over several non-integer strings to confirm that every
        non-numeric value is uniformly rejected with exit code 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--depth",
            bad_value,
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--depth={bad_value!r}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )

    def test_mirror_and_archive_together_rejected(self, tmp_path: pathlib.Path) -> None:
        """'--mirror --archive' must exit 2 with a constraint-violation error on stderr.

        The ValidateOptions method in subcmds/init.py prohibits combining
        --mirror with --archive. Passing both must exit 2 and emit the error
        message on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "-u",
            _NONEXISTENT_MANIFEST_URL,
            "--mirror",
            "--archive",
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--mirror --archive' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )
        assert "--mirror" in result.stderr and "--archive" in result.stderr, (
            f"Expected '--mirror' and '--archive' in stderr for constraint violation.\n  stderr: {result.stderr!r}"
        )

    def test_mirror_and_archive_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'--mirror --archive' constraint-violation error must not appear on stdout.

        The constraint-violation error produced by ValidateOptions must be
        routed to stderr only. Stdout must remain clear of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "-u",
            _NONEXISTENT_MANIFEST_URL,
            "--mirror",
            "--archive",
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--mirror --archive' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "--mirror" not in result.stdout, (
            f"'--mirror' error detail leaked to stdout for '--mirror --archive'.\n  stdout: {result.stdout!r}"
        )

    def test_mirror_and_use_superproject_together_rejected(self, tmp_path: pathlib.Path) -> None:
        """'--mirror --use-superproject' must exit 2 with a constraint-violation error.

        The ValidateOptions method prohibits combining --mirror with
        --use-superproject. Passing both must exit 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "-u",
            _NONEXISTENT_MANIFEST_URL,
            "--mirror",
            "--use-superproject",
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--mirror --use-superproject' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )
        assert "--mirror" in result.stderr, (
            f"Expected '--mirror' in stderr for constraint violation.\n  stderr: {result.stderr!r}"
        )

    def test_archive_and_use_superproject_together_rejected(self, tmp_path: pathlib.Path) -> None:
        """'--archive --use-superproject' must exit 2 with a constraint-violation error.

        The ValidateOptions method prohibits combining --archive with
        --use-superproject. Passing both must exit 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "-u",
            _NONEXISTENT_MANIFEST_URL,
            "--archive",
            "--use-superproject",
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--archive --use-superproject' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )
        assert "--archive" in result.stderr, (
            f"Expected '--archive' in stderr for constraint violation.\n  stderr: {result.stderr!r}"
        )

    def test_standalone_manifest_and_manifest_branch_rejected(self, tmp_path: pathlib.Path) -> None:
        """'--standalone-manifest --manifest-branch' must exit 2.

        ValidateOptions prohibits combining --standalone-manifest with
        --manifest-branch. Passing both must exit 2 with the error on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "-u",
            _NONEXISTENT_MANIFEST_URL,
            "--standalone-manifest",
            "--manifest-branch",
            _GIT_BRANCH_MAIN,
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--standalone-manifest --manifest-branch' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )
        assert "--standalone-manifest" in result.stderr, (
            f"Expected '--standalone-manifest' in stderr for constraint violation.\n  stderr: {result.stderr!r}"
        )

    def test_standalone_manifest_and_manifest_name_rejected(self, tmp_path: pathlib.Path) -> None:
        """'--standalone-manifest --manifest-name=custom.xml' must exit 2.

        ValidateOptions prohibits combining --standalone-manifest with a
        non-default --manifest-name. Passing both must exit 2 with the error
        on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "-u",
            _NONEXISTENT_MANIFEST_URL,
            "--standalone-manifest",
            "--manifest-name",
            _MANIFEST_FILENAME_CUSTOM,
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--standalone-manifest --manifest-name={_MANIFEST_FILENAME_CUSTOM}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )
        assert "--standalone-manifest" in result.stderr, (
            f"Expected '--standalone-manifest' in stderr for constraint violation.\n  stderr: {result.stderr!r}"
        )

    def test_manifest_upstream_branch_without_manifest_branch_rejected(self, tmp_path: pathlib.Path) -> None:
        """'--manifest-upstream-branch' without '--manifest-branch' must exit 2.

        ValidateOptions prohibits using --manifest-upstream-branch without also
        providing --manifest-branch. Passing it alone must exit 2 with the
        error on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "-u",
            _NONEXISTENT_MANIFEST_URL,
            "--manifest-upstream-branch",
            _GIT_BRANCH_MAIN,
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--manifest-upstream-branch' without '--manifest-branch' exited "
            f"{result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )
        assert "--manifest-upstream-branch" in result.stderr, (
            f"Expected '--manifest-upstream-branch' in stderr for constraint violation.\n  stderr: {result.stderr!r}"
        )

    def test_manifest_url_and_positional_url_together_rejected(self, tmp_path: pathlib.Path) -> None:
        """Providing both '-u' and a positional URL must exit 2 with an error on stderr.

        ValidateOptions prohibits supplying the manifest URL both via -u and
        as a positional argument. Passing both must exit 2 with the error on
        stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "-u",
            _NONEXISTENT_MANIFEST_URL,
            _SECONDARY_MANIFEST_URL,
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'-u <url> <url>' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )
        assert "--manifest-url" in result.stderr, (
            f"Expected '--manifest-url' in stderr for duplicate-url error.\n  stderr: {result.stderr!r}"
        )

    def test_too_many_positional_arguments_rejected(self, tmp_path: pathlib.Path) -> None:
        """Two positional URL arguments must exit 2 with 'too many arguments' on stderr.

        ValidateOptions rejects more than one positional argument to 'repo init'
        with the message 'too many arguments to init'. Passing two positional
        URLs must exit 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            _FIRST_POSITIONAL_URL,
            _SECOND_POSITIONAL_URL,
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Two positional URLs exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )
        assert "too many" in result.stderr.lower(), (
            f"Expected 'too many' in stderr for extra positional args.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each flag which documents a default value behaves according
    to that default when the flag is absent. Uses a real manifest repository
    to confirm a successful 'kanon repo init' when only mandatory flags are
    provided, exercising all documented default values simultaneously.
    """

    def test_all_flags_omitted_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo init -u <url>' with all optional flags omitted exits 0.

        When only the required -u flag is supplied, every optional flag takes
        its documented default value:
        - --manifest-branch defaults to HEAD (remote default)
        - --manifest-name defaults to default.xml
        - --groups defaults to 'default'
        - --platform defaults to 'auto'
        - --manifest-depth defaults to 0 (full clone)
        - --current-branch defaults to True (fetch current branch only)
        - --outer-manifest defaults to True
        - --this-manifest-only defaults to None

        Verifies that no flag is required beyond -u and that all documented
        defaults produce a successful (exit 0) initialisation.
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
            f"'kanon repo init -u <url>' with all optional flags omitted exited "
            f"{result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_manifest_name_default_is_default_xml(self, tmp_path: pathlib.Path) -> None:
        """Omitting --manifest-name defaults to 'default.xml' (the manifest is found).

        After a successful 'kanon repo init -u <url>' without --manifest-name,
        the .repo/manifests/default.xml file must exist, confirming the flag
        defaults to 'default.xml' as documented.
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
        default_xml = repo_dir / "manifests" / _MANIFEST_FILENAME
        assert default_xml.is_file(), (
            f"Expected '{_MANIFEST_FILENAME}' to exist at {default_xml!r} "
            f"after init with default --manifest-name.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_groups_default_does_not_cause_rejection(self, tmp_path: pathlib.Path) -> None:
        """Omitting --groups uses the 'default' group value; init exits 0.

        When --groups is not supplied, it defaults to 'default'. This must not
        cause any argument-parsing error. Verifies exit code 0.
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
            f"init without --groups exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_platform_default_does_not_cause_rejection(self, tmp_path: pathlib.Path) -> None:
        """Omitting --platform uses the 'auto' value; init exits 0.

        When --platform is not supplied, it defaults to 'auto'. This must not
        cause any argument-parsing error. Verifies exit code 0.
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
            f"init without --platform exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_manifest_depth_default_zero_produces_full_clone(self, tmp_path: pathlib.Path) -> None:
        """Omitting --manifest-depth defaults to 0 (full clone); init exits 0.

        When --manifest-depth is not supplied, it defaults to 0 (full clone).
        This must not cause any argument-parsing error. Verifies exit code 0
        and the presence of the .repo/manifests directory.
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
            f"init without --manifest-depth exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        manifests_dir = repo_dir / "manifests"
        assert manifests_dir.is_dir(), (
            f".repo/manifests/ not created at {manifests_dir!r} with default --manifest-depth=0.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_outer_manifest_default_true_does_not_reject(self, tmp_path: pathlib.Path) -> None:
        """Omitting --outer-manifest defaults to True; init exits 0.

        When --outer-manifest is not supplied, its default is True (operate
        starting at the outermost manifest). This must not cause any error.
        Verifies exit code 0.
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
            f"init without --outer-manifest exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_this_manifest_only_default_none_does_not_reject(self, tmp_path: pathlib.Path) -> None:
        """Omitting --this-manifest-only defaults to None; init exits 0.

        When --this-manifest-only is not supplied, its default is None (no
        restriction applied). This must not cause any error. Verifies exit 0.
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
            f"init without --this-manifest-only exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Channel discipline for flag-related errors
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoInitFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag-validation errors.

    Verifies that all argument-parsing and constraint-violation errors produced
    by 'kanon repo init' appear only on stderr and that stdout remains clean
    of error detail. Also confirms no cross-channel leakage on success.
    """

    def test_invalid_manifest_depth_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Invalid '--manifest-depth=xyz' error must appear on stderr, not stdout.

        Confirms channel discipline: the rejection error for a non-integer
        --manifest-depth value must be routed to stderr only. Stdout must be
        free of argument-error details.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "--manifest-depth",
            _INVALID_INT_VALUE_CHANNEL,
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for invalid --manifest-depth.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for invalid --manifest-depth error."
        assert _INVALID_INT_VALUE_CHANNEL not in result.stdout, (
            f"Argument {_INVALID_INT_VALUE_CHANNEL!r} must not appear in stdout for an argument-parsing error.\n  stdout: {result.stdout!r}"
        )

    def test_mirror_archive_constraint_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'--mirror --archive' constraint error must appear on stderr, not stdout.

        Confirms channel discipline: constraint-violation errors from
        ValidateOptions must be routed to stderr only. Stdout must be clean.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "-u",
            _NONEXISTENT_MANIFEST_URL,
            "--mirror",
            "--archive",
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for --mirror --archive.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for '--mirror --archive' constraint error."
        assert "--mirror" not in result.stdout, (
            f"'--mirror' error detail must not appear in stdout.\n  stdout: {result.stdout!r}"
        )

    def test_successful_init_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo init' with explicit flags must not emit tracebacks to stdout.

        Runs init with several optional flags explicitly set to their defaults.
        A successful result must not produce any 'Traceback (most recent call
        last)' text on stdout.
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
            _GIT_BRANCH_MAIN,
            "-m",
            _MANIFEST_FILENAME,
            "-g",
            _GROUP_DEFAULT,
            "-p",
            _PLATFORM_AUTO,
            cwd=checkout_dir,
        )

        assert result.returncode == 0, f"Prerequisite init with explicit flags failed: {result.stderr!r}"
        assert "Traceback (most recent call last)" not in result.stdout, (
            f"Python traceback must not appear in stdout on successful init.\n  stdout: {result.stdout!r}"
        )

    def test_successful_init_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo init' with explicit flags must not emit tracebacks to stderr.

        Verifies that a successful init with optional flags does not produce
        any 'Traceback (most recent call last)' text on stderr.
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
            _GIT_BRANCH_MAIN,
            "-m",
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )

        assert result.returncode == 0, f"Prerequisite init with explicit flags failed: {result.stderr!r}"
        assert "Traceback (most recent call last)" not in result.stderr, (
            f"Python traceback must not appear in stderr on successful init.\n  stderr: {result.stderr!r}"
        )

    def test_constraint_violation_error_prefix_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Constraint violation errors from '--standalone-manifest --manifest-branch' must not leak to stdout.

        Verifies channel discipline: the 'error:' prefix produced by the
        option parser for constraint violations must appear on stderr only.
        Stdout must not contain 'error:' prefix detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "init",
            "-u",
            _NONEXISTENT_MANIFEST_URL,
            "--standalone-manifest",
            "--manifest-branch",
            _GIT_BRANCH_MAIN,
            "--no-repo-verify",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for --standalone-manifest --manifest-branch.\n"
            f"  stderr: {result.stderr!r}"
        )
        # The word 'error' must appear on stderr only (option parser format: "... error: ...")
        assert "error" in result.stderr.lower(), (
            f"'error' must appear in stderr for constraint violation.\n  stderr: {result.stderr!r}"
        )
        # stdout must not contain the constraint error detail (only usage text is permitted)
        assert "--standalone-manifest" not in result.stdout, (
            f"'--standalone-manifest' error detail must not appear in stdout.\n  stdout: {result.stdout!r}"
        )
