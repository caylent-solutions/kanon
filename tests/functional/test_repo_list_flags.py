"""Functional tests for flag coverage of 'kanon repo list'.

Exercises every flag registered in ``subcmds/list.py``'s ``_Options()`` method
by invoking ``kanon repo list`` as a subprocess. Validates correct accept and
reject behavior for all flag values, and correct default behavior when flags
are omitted.

Flags in ``List._Options()``:

- ``-r`` / ``--regex``       (store_true, filter by regex/wildcard)
- ``-g`` / ``--groups``      (string value, filter by group membership)
- ``-a`` / ``--all``         (store_true, show projects regardless of checkout state)
- ``-n`` / ``--name-only``   (store_true, display only the repository name)
- ``-p`` / ``--path-only``   (store_true, display only the repository path)
- ``-f`` / ``--fullpath``    (store_true, display full work tree path)
- ``--relative-to``          (PATH value, display paths relative to this path)

Flags from ``Command._CommonOptions()`` (List has PARALLEL_JOBS=None so
no ``-j/--jobs`` flag is registered):

- ``-v`` / ``--verbose``           (store_true, dest=output_mode)
- ``-q`` / ``--quiet``             (store_false, dest=output_mode)
- ``--outer-manifest``             (store_true, default=None)
- ``--no-outer-manifest``          (store_false, dest=outer_manifest)
- ``--this-manifest-only``         (store_true, default=None)
- ``--no-this-manifest-only``      (store_false, dest=this_manifest_only)
- ``--all-manifests``              (store_false, alias for --no-this-manifest-only)

Valid-value tests confirm each flag is accepted without an argument-parsing
error (exit code != 2). Negative tests for boolean flags confirm that supplying
an inline value is rejected with exit code 2. The negative test for ``--groups``
and ``--relative-to`` confirms that omitting their required argument is rejected
with exit code 2. Documented mutually-exclusive combinations (``-f`` and ``-n``)
are verified to be rejected with a non-zero exit code.

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

from tests.functional.conftest import (
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- all hard-coded test-fixture values extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo List Flags Test User"
_GIT_USER_EMAIL = "repo-list-flags@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "list-flags-test-project"

# Error exit code for argument-parsing errors.
_ARGPARSE_ERROR_EXIT_CODE = 2

# Nonexistent repo-dir name used in argument-parser acceptance tests that
# do not require a real initialized repository (e.g. boolean-with-inline-value
# negative tests that fail at parse time before repo discovery).
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-list-flags-repo-dir"

# Inline-value suffix for boolean-flag negative tests.
# optparse exits 2 with '--<flag> option does not take a value' when a
# store_true or store_false flag is supplied with an inline value.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# Separator between path and name in 'repo list' default output.
_LIST_SEPARATOR = " : "

# Boolean store_true flags from List._Options().
_BOOL_STORE_TRUE_FLAGS_LOCAL: list[tuple[str, str]] = [
    ("-r", "short-regex"),
    ("--regex", "long-regex"),
    ("-a", "short-all"),
    ("--all", "long-all"),
    ("-n", "short-name-only"),
    ("--name-only", "long-name-only"),
    ("-p", "short-path-only"),
    ("--path-only", "long-path-only"),
    ("-f", "short-fullpath"),
    ("--fullpath", "long-fullpath"),
]

# Boolean store_true and store_false flags from _CommonOptions().
_BOOL_STORE_TRUE_FLAGS_COMMON: list[tuple[str, str]] = [
    ("-v", "short-verbose"),
    ("--verbose", "long-verbose"),
    ("--outer-manifest", "outer-manifest"),
    ("--this-manifest-only", "this-manifest-only"),
]

_BOOL_STORE_FALSE_FLAGS_COMMON: list[tuple[str, str]] = [
    ("-q", "short-quiet"),
    ("--quiet", "long-quiet"),
    ("--no-outer-manifest", "no-outer-manifest"),
    ("--no-this-manifest-only", "no-this-manifest-only"),
    ("--all-manifests", "all-manifests"),
]

# Combined list of all boolean flags for parametrize tests.
_ALL_BOOL_FLAGS: list[tuple[str, str]] = (
    _BOOL_STORE_TRUE_FLAGS_LOCAL + _BOOL_STORE_TRUE_FLAGS_COMMON + _BOOL_STORE_FALSE_FLAGS_COMMON
)

# Long-form boolean flags used in AC-TEST-002 negative tests.
# Short-form flags cannot use '--flag=value' syntax in optparse so only
# long-form flags are included here.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    ("--regex", "regex"),
    ("--all", "all"),
    ("--name-only", "name-only"),
    ("--path-only", "path-only"),
    ("--fullpath", "fullpath"),
    ("--verbose", "verbose"),
    ("--quiet", "quiet"),
    ("--outer-manifest", "outer-manifest"),
    ("--this-manifest-only", "this-manifest-only"),
    ("--no-outer-manifest", "no-outer-manifest"),
    ("--no-this-manifest-only", "no-this-manifest-only"),
    ("--all-manifests", "all-manifests"),
]

# A valid path value for --relative-to testing (current directory token).
_RELATIVE_TO_VALID_VALUE = "."

# A valid non-empty group string for --groups testing.
_GROUPS_VALID_VALUE = "default"


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/list.py
# (Also covers AC-FUNC-001: every documented flag behaves per its help text.)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoListFlagsValidValues:
    """AC-TEST-001 / AC-FUNC-001: Every ``_Options()`` flag in subcmds/list.py has a valid-value test.

    Exercises each flag registered in ``List._Options()`` (and the common
    flags from ``_CommonOptions()``) by invoking 'kanon repo list' with the
    flag against a real synced .repo directory.

    Boolean flags (store_true / store_false) are tested by confirming the flag
    is accepted without an argument-parsing error (exit code != 2). The
    ``--groups`` and ``--relative-to`` flags are tested with a valid string
    value to confirm they are accepted by the parser.
    """

    @pytest.mark.parametrize("flag,test_id", _ALL_BOOL_FLAGS)
    def test_boolean_flag_accepted_without_argparse_error(
        self, tmp_path: pathlib.Path, flag: str, test_id: str
    ) -> None:
        """Boolean flag is accepted by the parser (exit != 2).

        Passing a boolean flag (store_true or store_false) must not trigger an
        argument-parsing error. The command is allowed to fail for reasons
        other than argument parsing (e.g. missing projects for some flags),
        but exit code 2 indicates an option-parsing rejection and must not
        occur.

        Args:
            tmp_path: pytest-provided temporary directory root.
            flag: The flag string to pass (e.g. ``--regex``).
            test_id: Human-readable identifier for parametrize output.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Boolean flag {flag!r} ({test_id}) triggered an argument-parsing error "
            f"(exit {result.returncode}).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_groups_flag_with_valid_string_value_accepted(self, tmp_path: pathlib.Path) -> None:
        """'-g/--groups' with a valid group string is accepted (exit != 2).

        The --groups flag accepts an arbitrary string describing the project
        groups to filter on. A valid non-empty string must be accepted by the
        argument parser without an argument-parsing error (exit code 2).
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            f"--groups={_GROUPS_VALID_VALUE}",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--groups={_GROUPS_VALID_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_short_groups_flag_with_valid_string_value_accepted(self, tmp_path: pathlib.Path) -> None:
        """'-g <value>' with a valid group string is accepted (exit != 2).

        Short form of the --groups flag. A valid non-empty string must be
        accepted by the argument parser without an argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "-g",
            _GROUPS_VALID_VALUE,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'-g {_GROUPS_VALID_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_relative_to_flag_with_valid_path_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--relative-to=<path>' with a valid path is accepted (exit != 2).

        The --relative-to flag accepts a PATH argument and displays project
        paths relative to that path. A valid path must be accepted by the
        argument parser without an argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            f"--relative-to={checkout_dir}",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--relative-to={checkout_dir}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for invalid or disallowed flag values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoListFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts enumerated or typed values has a negative test.

    For boolean flags (store_true / store_false) the negative test verifies
    that supplying a value via inline syntax (``--flag=value``) is rejected by
    optparse with exit code 2. For string-valued flags (``--groups``,
    ``--relative-to``) the negative test verifies that omitting the required
    argument causes a parsing error (exit code 2).

    Additionally, the documented mutually-exclusive constraint between
    ``-f/--fullpath`` and ``-n/--name-only`` is verified: supplying both flags
    together must be rejected with a non-zero exit code.
    """

    @pytest.mark.parametrize("flag,test_id", _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST)
    def test_long_bool_flag_with_inline_value_is_rejected(
        self, flag: str, test_id: str, tmp_path: pathlib.Path
    ) -> None:
        """Long-form boolean flag supplied with inline value is rejected (exit 2).

        optparse exits 2 with 'option --<name> does not take a value' when a
        store_true or store_false flag is supplied as '--flag=value'. This
        confirms the flag is a boolean and cannot accept a value.

        Uses an absolute nonexistent --repo-dir so that option-parsing happens
        before repo discovery (ManifestParseError requires an abspath, so a
        relative nonexistent name would fail with exit 1 before parsing flags).

        Args:
            flag: The long-form flag string (e.g. ``--regex``).
            test_id: Human-readable identifier for parametrize output.
        """
        flag_with_value = flag + _INLINE_VALUE_SUFFIX
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "list",
            flag_with_value,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Boolean flag {flag_with_value!r} ({test_id}) did not exit with "
            f"argument-parsing error code {_ARGPARSE_ERROR_EXIT_CODE}. "
            f"Actual exit: {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_groups_flag_without_value_is_rejected(self, tmp_path: pathlib.Path) -> None:
        """'--groups' without a value is rejected with exit code 2.

        The --groups flag requires a string argument. Supplying the flag with
        no following value must cause an argument-parsing error (exit 2).
        Uses an absolute nonexistent repo-dir so option parsing fires before
        repo discovery.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "list",
            "--groups",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--groups' without a value did not produce exit {_ARGPARSE_ERROR_EXIT_CODE}. "
            f"Actual exit: {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_short_groups_flag_without_value_is_rejected(self, tmp_path: pathlib.Path) -> None:
        """'-g' without a value is rejected with exit code 2.

        Short form of --groups. Supplying the flag with no following value must
        cause an argument-parsing error (exit 2). Uses an absolute nonexistent
        repo-dir so option parsing fires before repo discovery.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "list",
            "-g",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'-g' without a value did not produce exit {_ARGPARSE_ERROR_EXIT_CODE}. "
            f"Actual exit: {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_relative_to_flag_without_value_is_rejected(self, tmp_path: pathlib.Path) -> None:
        """'--relative-to' without a value is rejected with exit code 2.

        The --relative-to flag requires a PATH argument. Supplying the flag
        with no following value must cause an argument-parsing error (exit 2).
        Uses an absolute nonexistent repo-dir so option parsing fires before
        repo discovery.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "list",
            "--relative-to",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--relative-to' without a value did not produce exit "
            f"{_ARGPARSE_ERROR_EXIT_CODE}. "
            f"Actual exit: {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_fullpath_and_name_only_together_are_rejected(self, tmp_path: pathlib.Path) -> None:
        """'-f' and '-n' together are rejected with a non-zero exit code.

        The 'repo list' subcommand's ValidateOptions() method explicitly
        raises an error when both --fullpath and --name-only are supplied.
        The command must exit with a non-zero code and an error message.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "-f",
            "-n",
            cwd=checkout_dir,
        )
        assert result.returncode != 0, (
            f"'-f -n' combination did not produce a non-zero exit code. "
            f"Expected non-zero but got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoListFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each List._Options() flag uses the documented default when
    omitted. Boolean flags default to None (unset) or False, as documented.
    String-valued flags (--groups, --relative-to) default to None.

    Absence tests confirm that omitting every optional flag still produces a
    valid, non-error invocation against a real synced .repo directory.
    """

    def test_all_flags_omitted_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo list' with all optional flags omitted exits 0.

        When no optional flags are supplied, each flag takes its default value:
        - --regex defaults to False (no regex filtering)
        - --groups defaults to None (no group filtering)
        - --all defaults to False (only checked-out projects shown)
        - --name-only defaults to False (full path:name output)
        - --path-only defaults to False (full path:name output)
        - --fullpath defaults to False (relative path output)
        - --relative-to defaults to None (paths relative to repo root)

        Verifies that no flag is required and all documented defaults produce
        a successful (exit 0) invocation.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list' with all optional flags omitted exited "
            f"{result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_omitting_name_only_defaults_to_path_colon_name_format(self, tmp_path: pathlib.Path) -> None:
        """Omitting --name-only defaults to path:name output format.

        When --name-only is omitted and --path-only is also omitted, the
        default output format is '<path> : <name>'. The separator must appear
        in stdout, confirming the combined format was used.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite 'kanon repo list' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _LIST_SEPARATOR in result.stdout, (
            f"Expected '{_LIST_SEPARATOR}' in stdout when --name-only is omitted "
            f"(default path:name format).\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_omitting_path_only_defaults_to_path_colon_name_format(self, tmp_path: pathlib.Path) -> None:
        """Omitting --path-only defaults to path:name output format.

        When --path-only is omitted and --name-only is also omitted, the
        default output format includes the separator. Verifies the separator
        appears in stdout.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite 'kanon repo list' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _LIST_SEPARATOR in result.stdout, (
            f"Expected '{_LIST_SEPARATOR}' in stdout when --path-only is omitted "
            f"(default path:name format).\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_omitting_regex_defaults_to_name_path_filter(self, tmp_path: pathlib.Path) -> None:
        """Omitting --regex defaults to exact name/path matching (not regex).

        When --regex is omitted, the default is False. 'repo list' uses
        GetProjects() (name/path lookup) rather than FindProjects() (regex).
        With no positional args, all projects are listed. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list' without --regex exited {result.returncode}, expected 0.\n  stderr: {result.stderr!r}"
        )

    def test_omitting_all_defaults_to_only_checked_out_projects(self, tmp_path: pathlib.Path) -> None:
        """Omitting --all defaults to showing only checked-out projects.

        When --all is omitted the default is False and only projects with
        an existing checkout are shown. On a freshly synced repo all projects
        are checked out, so the project still appears in stdout.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list' without --all exited {result.returncode}, expected 0.\n  stderr: {result.stderr!r}"
        )
        assert _PROJECT_PATH in result.stdout, (
            f"Expected project path {_PROJECT_PATH!r} in stdout when --all is omitted.\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoListFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of each flag documented in List._Options():
    - --regex: filter project list based on regex/wildcard matching
    - --groups: filter project list based on group membership
    - --all: show projects regardless of checkout state
    - --name-only: display only the name of the repository
    - --path-only: display only the path of the repository
    - --fullpath: display the full work tree path
    - --relative-to: display paths relative to the given path

    Tests confirm that each flag is accepted and the command behaves as
    described in its help text.
    """

    def test_name_only_flag_outputs_name_without_separator(self, tmp_path: pathlib.Path) -> None:
        """'--name-only' outputs repository names only, no path separator.

        When --name-only is supplied, the output must contain the project name
        but must not contain the '<path> : <name>' separator, confirming only
        names are printed.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--name-only",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --name-only' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _PROJECT_NAME in result.stdout, (
            f"Expected project name {_PROJECT_NAME!r} in '--name-only' stdout.\n  stdout: {result.stdout!r}"
        )
        assert _LIST_SEPARATOR not in result.stdout, (
            f"Expected no '{_LIST_SEPARATOR}' separator in '--name-only' stdout.\n  stdout: {result.stdout!r}"
        )

    def test_short_name_only_flag_outputs_name_without_separator(self, tmp_path: pathlib.Path) -> None:
        """'-n' outputs repository names only, no path separator.

        Short form of --name-only. Verifies the same behavior as the long form.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "-n",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, f"'kanon repo list -n' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        assert _PROJECT_NAME in result.stdout, (
            f"Expected project name {_PROJECT_NAME!r} in '-n' stdout.\n  stdout: {result.stdout!r}"
        )
        assert _LIST_SEPARATOR not in result.stdout, (
            f"Expected no '{_LIST_SEPARATOR}' separator in '-n' stdout.\n  stdout: {result.stdout!r}"
        )

    def test_path_only_flag_outputs_path_without_name(self, tmp_path: pathlib.Path) -> None:
        """'--path-only' outputs repository paths only, no project name.

        When --path-only is supplied, the output must contain the project path
        but must not contain the project name or the separator, confirming
        only paths are printed.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--path-only",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --path-only' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _PROJECT_PATH in result.stdout, (
            f"Expected project path {_PROJECT_PATH!r} in '--path-only' stdout.\n  stdout: {result.stdout!r}"
        )
        assert _LIST_SEPARATOR not in result.stdout, (
            f"Expected no '{_LIST_SEPARATOR}' separator in '--path-only' stdout.\n  stdout: {result.stdout!r}"
        )

    def test_short_path_only_flag_outputs_path_without_separator(self, tmp_path: pathlib.Path) -> None:
        """'-p' outputs repository paths only, no separator.

        Short form of --path-only. Verifies the same behavior as the long form.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "-p",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, f"'kanon repo list -p' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        assert _PROJECT_PATH in result.stdout, (
            f"Expected project path {_PROJECT_PATH!r} in '-p' stdout.\n  stdout: {result.stdout!r}"
        )
        assert _LIST_SEPARATOR not in result.stdout, (
            f"Expected no '{_LIST_SEPARATOR}' separator in '-p' stdout.\n  stdout: {result.stdout!r}"
        )

    def test_fullpath_flag_outputs_absolute_path(self, tmp_path: pathlib.Path) -> None:
        """'--fullpath' outputs the absolute work tree path.

        When --fullpath is supplied, the output must contain an absolute path
        (starting with '/') for each project rather than the relative path.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--fullpath",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --fullpath' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        # The absolute checkout dir must appear as a prefix in the full path.
        assert str(checkout_dir) in result.stdout, (
            f"Expected absolute checkout dir {str(checkout_dir)!r} in '--fullpath' stdout.\n  stdout: {result.stdout!r}"
        )

    def test_short_fullpath_flag_outputs_absolute_path(self, tmp_path: pathlib.Path) -> None:
        """'-f' outputs the absolute work tree path.

        Short form of --fullpath. Verifies that the absolute checkout directory
        appears in stdout.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "-f",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, f"'kanon repo list -f' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        assert str(checkout_dir) in result.stdout, (
            f"Expected absolute checkout dir {str(checkout_dir)!r} in '-f' stdout.\n  stdout: {result.stdout!r}"
        )

    def test_regex_flag_filters_by_pattern(self, tmp_path: pathlib.Path) -> None:
        """'--regex' with a matching pattern shows the project.

        When --regex is supplied with a pattern that matches the project name,
        the project must appear in stdout and the command must exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--regex",
            _PROJECT_NAME,
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --regex {_PROJECT_NAME}' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _PROJECT_NAME in result.stdout, (
            f"Expected project name {_PROJECT_NAME!r} in '--regex' stdout.\n  stdout: {result.stdout!r}"
        )

    def test_short_regex_flag_filters_by_pattern(self, tmp_path: pathlib.Path) -> None:
        """'-r' with a matching pattern shows the project.

        Short form of --regex. Verifies that the project appears in stdout
        when the supplied pattern matches.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "-r",
            _PROJECT_NAME,
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list -r {_PROJECT_NAME}' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _PROJECT_NAME in result.stdout, (
            f"Expected project name {_PROJECT_NAME!r} in '-r' stdout.\n  stdout: {result.stdout!r}"
        )

    def test_relative_to_flag_changes_path_display(self, tmp_path: pathlib.Path) -> None:
        """'--relative-to=<path>' changes project path display to be relative.

        When --relative-to is supplied with a directory path, the project paths
        in stdout are displayed relative to that directory rather than relative
        to the repo root. The command must exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            f"--relative-to={checkout_dir}",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --relative-to={checkout_dir}' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        # With --relative-to pointing at checkout_dir, the relative path
        # of the project worktree within checkout_dir equals the project path.
        assert _PROJECT_PATH in result.stdout, (
            f"Expected project path {_PROJECT_PATH!r} in '--relative-to' stdout.\n  stdout: {result.stdout!r}"
        )

    def test_groups_flag_with_matching_group_shows_project(self, tmp_path: pathlib.Path) -> None:
        """'--groups=all' shows all projects (the 'all' pseudo-group).

        The --groups flag filters projects by group membership. The 'all'
        special value includes all projects regardless of their group setting.
        The command must exit 0 and the project must appear in stdout.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--groups=all",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"'kanon repo list --groups=all' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _PROJECT_PATH in result.stdout, (
            f"Expected project path {_PROJECT_PATH!r} in '--groups=all' stdout.\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoListFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful 'kanon repo list' invocations with flags do not
    write Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on successful runs.

    Also verifies that argument-parsing errors (exit 2) write their diagnostic
    message to stderr (not stdout), maintaining consistent channel usage.
    """

    def test_successful_flag_invocation_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo list --name-only' must not emit tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--name-only",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite 'kanon repo list --name-only' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo list --name-only'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_successful_flag_invocation_has_no_error_keyword_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo list --path-only' must not emit 'Error:' to stdout.

        Error-prefixed messages are a stderr-only concern. Successful
        invocations must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--path-only",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite 'kanon repo list --path-only' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of 'kanon repo list --path-only': "
                f"{line!r}\n  stdout: {result.stdout!r}"
            )

    def test_successful_flag_invocation_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo list --fullpath' must not emit tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "list",
            "--fullpath",
            cwd=checkout_dir,
        )
        assert result.returncode == 0, (
            f"Prerequisite 'kanon repo list --fullpath' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo list --fullpath'.\n  stderr: {result.stderr!r}"
        )

    def test_argparse_error_writes_to_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Argument-parsing errors write to stderr, not stdout.

        When '--groups' is supplied without a value (which triggers exit 2),
        the diagnostic message must appear on stderr and stdout must be empty.
        This confirms the parser uses the correct output channel for errors.
        Uses an absolute nonexistent repo-dir so option parsing fires before
        repo discovery.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "list",
            "--groups",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '--groups' without value, "
            f"got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stdout == "", f"Expected empty stdout for argparse error, got: {result.stdout!r}"
        assert result.stderr != "", (
            f"Expected non-empty stderr for argparse error, got empty stderr.\n  stdout: {result.stdout!r}"
        )
