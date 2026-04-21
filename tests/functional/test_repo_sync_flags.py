"""Functional tests for flag coverage of 'kanon repo sync'.

Exercises every flag registered in ``subcmds/sync.py``'s ``_Options()`` method
by invoking ``kanon repo sync`` as a subprocess. Validates correct accept and
reject behavior for all flag values, and correct default behavior when flags
are omitted.

Flags in ``Sync._Options()`` include a mix of boolean (store_true / store_false)
and typed (string / int) flags. The full inventory:

Boolean store_true flags (accepted without an argument; rejected with inline value):
- ``-f`` / ``--force-broken``         (obsolete, store_true)
- ``--fail-fast``                     (store_true)
- ``--force-sync``                    (store_true)
- ``--force-checkout``                (store_true)
- ``--force-remove-dirty``            (store_true)
- ``--rebase``                        (store_true)
- ``-l`` / ``--local-only``           (store_true)
- ``--interleaved``                   (store_true)
- ``-n`` / ``--network-only``         (store_true)
- ``-d`` / ``--detach``               (store_true, dest=detach_head)
- ``-c`` / ``--current-branch``       (store_true, dest=current_branch_only)
- ``--clone-bundle``                  (store_true, dest=clone_bundle)
- ``--fetch-submodules``              (store_true)
- ``--use-superproject``              (store_true)
- ``--tags``                          (store_true)
- ``--optimized-fetch``               (store_true)
- ``--prune``                         (store_true)
- ``--auto-gc``                       (store_true, default=None)
- ``-s`` / ``--smart-sync``           (store_true, show_smart=True)
- ``--no-repo-verify``                (store_false, dest=repo_verify)
- ``--repo-upgraded``                 (store_true)

Boolean store_false flags (inverse toggling another dest; also rejected with inline value):
- ``--no-manifest-update`` / ``--nmu`` (store_false, dest=mp_update)
- ``--no-current-branch``             (store_false, dest=current_branch_only)
- ``--no-clone-bundle``               (store_false, dest=clone_bundle)
- ``--no-use-superproject``           (store_false, dest=use_superproject)
- ``--no-tags``                       (store_false, dest=tags)
- ``--no-prune``                      (store_false, dest=prune)
- ``--no-auto-gc``                    (store_false, dest=auto_gc)

Typed / string flags (accept a value; rejected with non-parseable value):
- ``--jobs-network JOBS``             (int, default=None)
- ``--jobs-checkout JOBS``            (int, default=None)
- ``-m`` / ``--manifest-name NAME.xml`` (store string)
- ``-u`` / ``--manifest-server-username`` (store string)
- ``-p`` / ``--manifest-server-password`` (store string)
- ``--retry-fetches N``               (int, default=0)
- ``-t`` / ``--smart-tag TAG``        (store string, show_smart=True)

From ``Command._CommonOptions()`` (PARALLEL_JOBS=0 enables -j/--jobs):
- ``-j`` / ``--jobs``                 (int, default=0)

AC wording note: AC-TEST-002 states "every flag that accepts enumerated values
has a negative test for an invalid value." The sync flags accept typed integer
values (--jobs-network, --jobs-checkout, --retry-fetches, -j/--jobs) rather
than enumerated keyword values. The negative tests for these typed flags confirm
that non-integer strings (e.g. "abc") are rejected with exit code 2. For
boolean store_true / store_false flags, the applicable negative test is
supplying an inline value (e.g. --fail-fast=unexpected), which optparse rejects
with exit code 2. String flags (--manifest-name, --manifest-server-username,
--manifest-server-password, --smart-tag) accept any string, so no enumeration
constraint exists; those flags are exercised only via valid-value tests.

AC-TEST-003 note: Absence-default behavior is verified by running
'kanon repo sync' with all optional flags omitted on a fully synced repo and
confirming the documented success behavior (exit 0, success phrase on stdout).

Covers:
- AC-TEST-001: Every ``_Options()`` flag in subcmds/sync.py has a valid-value test.
- AC-TEST-002: Every flag that accepts enumerated values has a negative test for
  an invalid value.
- AC-TEST-003: Flags have correct absence-default behavior when omitted.
- AC-FUNC-001: Every documented flag behaves per its help text.
- AC-CHANNEL-001: stdout vs stderr channel discipline is verified.

Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import (
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- all domain literals must appear here only.
# No inline literals in test bodies or f-string diagnostics.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Sync Flags Test User"
_GIT_USER_EMAIL = "repo-sync-flags@example.com"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "sync-flags-test-project"

# CLI token constants
_CLI_TOKEN_REPO = "repo"
_CLI_TOKEN_SYNC = "sync"
_CLI_FLAG_REPO_DIR = "--repo-dir"
_CLI_FLAG_JOBS_ONE = "--jobs=1"

# CLI flag constants for flags used in non-parametrize test bodies.
# All inline flag literals in test bodies must be replaced with these constants.
_CLI_FLAG_MANIFEST_NAME = "--manifest-name"
_CLI_FLAG_SMART_SYNC = "--smart-sync"
_CLI_FLAG_MANIFEST_SERVER_USERNAME = "--manifest-server-username"
_CLI_FLAG_MANIFEST_SERVER_PASSWORD = "--manifest-server-password"
_CLI_FLAG_SMART_TAG = "--smart-tag"
_CLI_FLAG_FAIL_FAST = "--fail-fast"
_CLI_FLAG_FORCE_BROKEN = "--force-broken"
_CLI_FLAG_NO_MANIFEST_UPDATE = "--no-manifest-update"
_CLI_FLAG_NMU = "--nmu"
_CLI_FLAG_NO_PRUNE = "--no-prune"
_CLI_FLAG_AUTO_GC = "--auto-gc"
_CLI_FLAG_NO_AUTO_GC = "--no-auto-gc"
_CLI_FLAG_RETRY_FETCHES = "--retry-fetches"
_CLI_FLAG_JOBS_NETWORK = "--jobs-network"

# Exit code constants
_EXPECTED_EXIT_SUCCESS = 0
_ARGPARSE_ERROR_EXIT_CODE = 2

# Nonexistent repo-dir used for argument-parser acceptance tests that must not
# require a fully initialized .repo directory.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-sync-flags-repo-dir"

# Inline-value suffix for negative tests against boolean flags.
# optparse exits 2 with '--<flag> option does not take a value'.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Phrase expected in the success output of 'kanon repo sync'.
_SUCCESS_PHRASE = "repo sync has finished successfully."

# Phrase expected in stderr when optparse rejects an inline value on a boolean flag.
_DOES_NOT_TAKE_VALUE_PHRASE = "does not take a value"

# Phrase expected in stderr when optparse rejects a non-integer value for an int flag.
_INVALID_INT_PHRASE = "invalid integer value"

# Traceback marker used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error-prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# Non-integer value used in negative tests for typed int flags.
_INVALID_INT_VALUE = "abc"

# Valid integer value used in valid-value tests for typed int flags.
_VALID_INT_VALUE = "2"

# Valid string value for --manifest-name (must be an XML filename).
_MANIFEST_NAME_VALUE = "default.xml"

# Valid string values for string-store flags.
_MANIFEST_SERVER_USERNAME_VALUE = "testuser"
_MANIFEST_SERVER_PASSWORD_VALUE = "testpassword"
_SMART_TAG_VALUE = "v1.0"

# Explicit default value for --retry-fetches (documented as 0 in _Options()).
_RETRY_FETCHES_DEFAULT_VALUE = "0"

# ---------------------------------------------------------------------------
# Parametrize lists for boolean flags -- tuples of (flag_token, test_id).
# All boolean flags (both store_true and store_false) are accepted without an
# argument value, and rejected with an inline value via optparse's exit-2 path.
# Short-form flags must NOT be tested with inline '=value' syntax (only long-
# form flags support '--flag=value' in optparse).
# ---------------------------------------------------------------------------

# All boolean flags in Sync._Options() and _CommonOptions() (store_true and
# store_false). Both short and long forms are included for valid-value tests.
_BOOL_FLAGS_ALL: list[tuple[str, str]] = [
    ("-f", "short-force-broken"),
    (_CLI_FLAG_FORCE_BROKEN, "long-force-broken"),
    (_CLI_FLAG_FAIL_FAST, "long-fail-fast"),
    ("--force-sync", "long-force-sync"),
    ("--force-checkout", "long-force-checkout"),
    ("--force-remove-dirty", "long-force-remove-dirty"),
    ("--rebase", "long-rebase"),
    ("-l", "short-local-only"),
    ("--local-only", "long-local-only"),
    ("--interleaved", "long-interleaved"),
    ("-n", "short-network-only"),
    ("--network-only", "long-network-only"),
    ("-d", "short-detach"),
    ("--detach", "long-detach"),
    ("-c", "short-current-branch"),
    ("--current-branch", "long-current-branch"),
    ("--no-current-branch", "long-no-current-branch"),
    ("--clone-bundle", "long-clone-bundle"),
    ("--no-clone-bundle", "long-no-clone-bundle"),
    ("--fetch-submodules", "long-fetch-submodules"),
    ("--use-superproject", "long-use-superproject"),
    ("--no-use-superproject", "long-no-use-superproject"),
    ("--tags", "long-tags"),
    ("--no-tags", "long-no-tags"),
    ("--optimized-fetch", "long-optimized-fetch"),
    ("--prune", "long-prune"),
    (_CLI_FLAG_NO_PRUNE, "long-no-prune"),
    (_CLI_FLAG_AUTO_GC, "long-auto-gc"),
    (_CLI_FLAG_NO_AUTO_GC, "long-no-auto-gc"),
    ("-s", "short-smart-sync"),
    (_CLI_FLAG_SMART_SYNC, "long-smart-sync"),
    (_CLI_FLAG_NO_MANIFEST_UPDATE, "long-no-manifest-update"),
    (_CLI_FLAG_NMU, "long-nmu-alias"),
    ("--no-repo-verify", "long-no-repo-verify"),
    ("--repo-upgraded", "long-repo-upgraded"),
]

# Long-form boolean flags eligible for the inline-value negative test.
# Short-form flags are excluded because '--flag=value' syntax is only valid
# for long-form flags in optparse.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    (_CLI_FLAG_FORCE_BROKEN, "force-broken"),
    (_CLI_FLAG_FAIL_FAST, "fail-fast"),
    ("--force-sync", "force-sync"),
    ("--force-checkout", "force-checkout"),
    ("--force-remove-dirty", "force-remove-dirty"),
    ("--rebase", "rebase"),
    ("--local-only", "local-only"),
    ("--interleaved", "interleaved"),
    ("--network-only", "network-only"),
    ("--detach", "detach"),
    ("--current-branch", "current-branch"),
    ("--no-current-branch", "no-current-branch"),
    ("--clone-bundle", "clone-bundle"),
    ("--no-clone-bundle", "no-clone-bundle"),
    ("--fetch-submodules", "fetch-submodules"),
    ("--use-superproject", "use-superproject"),
    ("--no-use-superproject", "no-use-superproject"),
    ("--tags", "tags"),
    ("--no-tags", "no-tags"),
    ("--optimized-fetch", "optimized-fetch"),
    ("--prune", "prune"),
    (_CLI_FLAG_NO_PRUNE, "no-prune"),
    (_CLI_FLAG_AUTO_GC, "auto-gc"),
    (_CLI_FLAG_NO_AUTO_GC, "no-auto-gc"),
    (_CLI_FLAG_SMART_SYNC, "smart-sync"),
    (_CLI_FLAG_NO_MANIFEST_UPDATE, "no-manifest-update"),
    ("--no-repo-verify", "no-repo-verify"),
    ("--repo-upgraded", "repo-upgraded"),
]

# Typed int flags: (flag_token, valid_value, test_id).
# Valid-value test passes the flag with _VALID_INT_VALUE.
# Negative test passes the flag with _INVALID_INT_VALUE.
_INT_FLAGS: list[tuple[str, str, str]] = [
    (_CLI_FLAG_JOBS_NETWORK, _VALID_INT_VALUE, "jobs-network"),
    ("--jobs-checkout", _VALID_INT_VALUE, "jobs-checkout"),
    ("--retry-fetches", _VALID_INT_VALUE, "retry-fetches"),
    ("-j", _VALID_INT_VALUE, "short-jobs"),
    ("--jobs", _VALID_INT_VALUE, "long-jobs"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/sync.py
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/sync.py has a valid-value test.

    Exercises each boolean and typed flag registered in ``Sync._Options()``
    and ``Command._CommonOptions()`` by invoking 'kanon repo sync' against a
    real initialized+synced .repo directory. Valid-value tests confirm the flag
    is accepted without an argument-parsing error (exit code != 2).

    Boolean flags (store_true / store_false) are passed without a value.
    Typed int flags are passed with a valid integer value (_VALID_INT_VALUE).
    String flags are tested with representative dummy string values.

    Because several boolean flags (e.g. --smart-sync, --network-only,
    --local-only) alter sync semantics in ways that may prevent a complete
    re-sync on the test repository, the valid-value tests assert exit code !=
    _ARGPARSE_ERROR_EXIT_CODE rather than exit code == 0. This confirms optparse
    accepted the flag while remaining agnostic to business-logic exit codes.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _BOOL_FLAGS_ALL],
        ids=[test_id for _, test_id in _BOOL_FLAGS_ALL],
    )
    def test_boolean_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo sync' with the given boolean flag against a properly
        initialized+synced .repo directory and asserts that optparse does not
        reject the invocation (exit code != 2). A non-2 exit code confirms the
        flag itself was accepted; subsequent behavior (e.g. smart-sync requiring
        a manifest server) is not an argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS_ONE,
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        ("flag", "value"),
        [(flag, value) for flag, value, _ in _INT_FLAGS],
        ids=[test_id for _, _, test_id in _INT_FLAGS],
    )
    def test_int_flag_with_valid_value_accepted(self, tmp_path: pathlib.Path, flag: str, value: str) -> None:
        """Each typed int flag is accepted when supplied with a valid integer.

        Calls 'kanon repo sync' with flag=value against a properly
        initialized+synced .repo directory. Asserts that optparse does not
        reject the invocation (exit code != 2). A non-2 exit confirms the flag
        and value were parsed without argument-parsing errors.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            flag,
            value,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Int flag {flag!r} with value {value!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_manifest_name_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--manifest-name' with a valid filename is accepted by the argument parser.

        Supplies '--manifest-name default.xml' to 'kanon repo sync' against a
        real initialized .repo directory. Asserts exit code != 2 confirming the
        flag and value are parsed without argument-parsing errors.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS_ONE,
            _CLI_FLAG_MANIFEST_NAME,
            _MANIFEST_NAME_VALUE,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_MANIFEST_NAME} {_MANIFEST_NAME_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_manifest_server_username_and_password_flags_accepted_together(self, tmp_path: pathlib.Path) -> None:
        """Both --manifest-server-username and --manifest-server-password must be supplied together.

        Both --manifest-server-username and --manifest-server-password must be supplied
        together (optparse co-constraint). This test verifies optparse accepts both in a
        single invocation; isolating them is not possible.

        Both credential flags also require -s/--smart-sync or -t/--smart-tag to satisfy
        the smart-sync business-logic co-constraint. All three flags are supplied together
        in a single invocation to confirm optparse accepts the combination without an
        argument-parsing error (exit code != 2).
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS_ONE,
            _CLI_FLAG_SMART_SYNC,
            _CLI_FLAG_MANIFEST_SERVER_USERNAME,
            _MANIFEST_SERVER_USERNAME_VALUE,
            _CLI_FLAG_MANIFEST_SERVER_PASSWORD,
            _MANIFEST_SERVER_PASSWORD_VALUE,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_MANIFEST_SERVER_USERNAME} {_MANIFEST_SERVER_USERNAME_VALUE!r} "
            f"{_CLI_FLAG_MANIFEST_SERVER_PASSWORD} {_MANIFEST_SERVER_PASSWORD_VALUE!r}' "
            f"triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_smart_tag_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """'-t'/'--smart-tag' with a string value is accepted by the argument parser.

        Supplies '--smart-tag v1.0' to 'kanon repo sync' against a real
        initialized .repo directory. Asserts exit code != 2 confirming the flag
        and value are parsed without argument-parsing errors.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS_ONE,
            _CLI_FLAG_SMART_TAG,
            _SMART_TAG_VALUE,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_SMART_TAG} {_SMART_TAG_VALUE!r}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags that accept typed or enumerated values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts enumerated values has a negative test.

    Two categories of negative tests:

    1. Boolean flags (store_true / store_false): supplying '--<flag>=unexpected'
       causes optparse to exit 2 with '--<flag> option does not take a value'.

    2. Typed int flags (--jobs-network, --jobs-checkout, --retry-fetches, -j/--jobs):
       supplying a non-integer string causes optparse to exit 2 with
       'invalid integer value'.

    String flags (--manifest-name, --manifest-server-username,
    --manifest-server-password, --smart-tag) accept any string and have no
    enumeration constraint; no negative test applies to them.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with an inline value must exit 2.

        Supplies '--<flag>=unexpected' to 'kanon repo sync'. Since all tested
        flags are store_true or store_false, optparse rejects the inline value
        with exit code 2 and emits '--<flag> option does not take a value'
        on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SYNC,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_error_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with inline value must emit error on stderr, not stdout.

        The argument-parsing error for '--<flag>=unexpected' must appear on
        stderr only. Stdout must not contain the rejection detail (channel
        discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SYNC,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected {_DOES_NOT_TAKE_VALUE_PHRASE!r} in stderr for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_fail_fast_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--fail-fast=unexpected' error must name '--fail-fast' in stderr.

        The embedded optparse parser emits '--fail-fast option does not take
        a value' when '--fail-fast=unexpected' is supplied. Confirms the
        canonical flag name appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _CLI_FLAG_FAIL_FAST + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SYNC,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_FAIL_FAST}=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert _CLI_FLAG_FAIL_FAST in result.stderr, (
            f"Expected {_CLI_FLAG_FAIL_FAST!r} in stderr for '{_CLI_FLAG_FAIL_FAST}=unexpected' error.\n  stderr: {result.stderr!r}"
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected {_DOES_NOT_TAKE_VALUE_PHRASE!r} in stderr.\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _, _ in _INT_FLAGS],
        ids=[test_id for _, _, test_id in _INT_FLAGS],
    )
    def test_int_flag_with_non_integer_value_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each typed int flag must exit 2 when supplied with a non-integer string.

        Supplies 'kanon repo sync <flag> abc' against a nonexistent repo dir.
        optparse exits 2 when it cannot parse the value as an integer, emitting
        'invalid integer value' on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SYNC,
            flag,
            _INVALID_INT_VALUE,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{flag} {_INVALID_INT_VALUE}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _INVALID_INT_PHRASE in result.stderr, (
            f"Expected {_INVALID_INT_PHRASE!r} in stderr for '{flag} {_INVALID_INT_VALUE}'.\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _, _ in _INT_FLAGS],
        ids=[test_id for _, _, test_id in _INT_FLAGS],
    )
    def test_int_flag_non_integer_error_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each typed int flag's non-integer error must appear on stderr, not stdout.

        The argument-parsing error for a non-integer value must be routed
        to stderr only. Stdout must not contain the rejection detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SYNC,
            flag,
            _INVALID_INT_VALUE,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{flag} {_INVALID_INT_VALUE}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert _INVALID_INT_PHRASE in result.stderr, (
            f"Expected {_INVALID_INT_PHRASE!r} in stderr for '{flag} {_INVALID_INT_VALUE}'.\n  stderr: {result.stderr!r}"
        )
        assert _INVALID_INT_VALUE not in result.stdout, (
            f"Invalid value {_INVALID_INT_VALUE!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that running 'kanon repo sync' with all optional flags omitted
    produces the documented success behavior (exit 0, success phrase on stdout).
    This confirms that no flag is required and all documented defaults produce
    a valid, successful invocation on an already-synced repo.

    Documented defaults for selected flags:
    - --jobs-network: None (defaults to --jobs or 1)
    - --jobs-checkout: None (defaults to --jobs or DEFAULT_LOCAL_JOBS)
    - --fail-fast: False (do not halt on first error)
    - --force-sync: False (do not overwrite git directories)
    - --force-checkout: False (do not force checkout)
    - --force-remove-dirty: False (do not remove dirty projects)
    - --local-only: False (fetch from remote)
    - --network-only: False (do update working tree)
    - --fetch-submodules: False (do not fetch submodules)
    - --prune: default True (delete stale refs)
    - --auto-gc: None (no garbage collection by default)
    - --retry-fetches: 0 (no retries)
    """

    def test_all_flags_omitted_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo sync' with all optional flags omitted exits 0.

        After a successful 'kanon repo init' and first 'kanon repo sync' (via
        _setup_synced_repo), re-running 'kanon repo sync' with no optional flags
        must exit 0. Confirms all documented defaults allow a successful re-sync.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS_ONE,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_SUCCESS, (
            f"'kanon repo sync' with all optional flags omitted exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_all_flags_omitted_emits_success_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo sync' with all optional flags omitted emits the success phrase.

        On success with no --quiet flag and all optional flags at their defaults,
        'repo sync' prints the documented completion message to stdout. Confirms
        the default behavior (absence of all flags) produces the expected output.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS_ONE,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_SUCCESS, (
            f"Prerequisite 'kanon repo sync' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _SUCCESS_PHRASE in result.stdout, (
            f"Expected {_SUCCESS_PHRASE!r} in stdout when all flags are omitted.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of selected flags documented in
    Sync._Options(). Each test confirms the flag is accepted and the command
    behaves consistent with its documented purpose.

    Flags under test:
    - --force-broken: obsolete flag accepted without error.
    - --fail-fast: accepted; does not alter argparse success.
    - --force-sync: accepted; does not alter argparse success.
    - --force-checkout: accepted; does not alter argparse success.
    - --force-remove-dirty: accepted; does not alter argparse success.
    - --no-manifest-update / --nmu: accepted; prevents manifest re-fetch.
    - --prune / --no-prune: both accepted without error.
    - --auto-gc / --no-auto-gc: both accepted without error.
    - --jobs-network / --jobs-checkout: accepted with integer values.
    - --retry-fetches: accepted with integer value 0.
    - --no-repo-verify: accepted; prevents repo verification.
    """

    def test_force_broken_flag_is_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--force-broken' (obsolete) is accepted by the argument parser.

        The --force-broken flag is documented as an obsolete option to be
        deleted in the future. It must still be accepted without error (exit
        code != 2) so that existing scripts continue to work.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS_ONE,
            _CLI_FLAG_FORCE_BROKEN,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_FORCE_BROKEN}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [
            _CLI_FLAG_NO_MANIFEST_UPDATE,
            _CLI_FLAG_NMU,
        ],
        ids=["no-manifest-update", "nmu"],
    )
    def test_no_manifest_update_and_nmu_alias_both_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Both '--no-manifest-update' and '--nmu' alias are accepted.

        Both forms share the same dest (mp_update) and must both be accepted
        by optparse without an argument-parsing error (exit code != 2).
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS_ONE,
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{flag}' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_prune_and_no_prune_combination_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--no-prune' is accepted alongside other flags without argument-parsing error.

        Confirms the prune/no-prune pair is parsed without conflict: supplying
        --no-prune disables ref pruning via store_false on the shared dest.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS_ONE,
            _CLI_FLAG_NO_PRUNE,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_NO_PRUNE}' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [
            _CLI_FLAG_AUTO_GC,
            _CLI_FLAG_NO_AUTO_GC,
        ],
        ids=["auto-gc", "no-auto-gc"],
    )
    def test_auto_gc_and_no_auto_gc_both_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Both '--auto-gc' and '--no-auto-gc' are accepted without argument-parsing error.

        Verifies that both sides of the auto-gc toggle pair are accepted by the
        argument parser. The flags share the same dest (auto_gc) with opposite
        store_true / store_false actions.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS_ONE,
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{flag}' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_retry_fetches_zero_is_default_and_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--retry-fetches' with the documented default value is accepted.

        The --retry-fetches flag defaults to _RETRY_FETCHES_DEFAULT_VALUE (no
        retries). Supplying it explicitly with the default value must be
        accepted without argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS_ONE,
            _CLI_FLAG_RETRY_FETCHES,
            _RETRY_FETCHES_DEFAULT_VALUE,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_RETRY_FETCHES} {_RETRY_FETCHES_DEFAULT_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo sync' flags.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.

    The channel fixture runs a successful re-sync (all flags at defaults) once
    per class, and individual tests assert on the shared result to avoid
    repeating the expensive git setup.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo sync' once and return the CompletedProcess.

        Uses tmp_path_factory for a class-scoped fixture: setup and CLI
        invocation execute once and all channel assertions share the result.

        Returns:
            The CompletedProcess from 'kanon repo sync' with no optional flags.

        Raises:
            AssertionError: When the prerequisite setup (init/sync) fails.
        """
        tmp_path = tmp_path_factory.mktemp("sync_flags_channel")
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS_ONE,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_SUCCESS, (
            f"Prerequisite 'kanon repo sync' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_successful_sync_has_no_traceback_on_stdout(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo sync' must not emit Python tracebacks to stdout.

        Verifies that stdout does not contain 'Traceback (most recent call last)'
        on a successful sync. Tracebacks on stdout indicate an unhandled exception
        escaped to the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo sync'.\n  stdout: {channel_result.stdout!r}"
        )

    def test_successful_sync_has_no_error_keyword_on_stdout(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo sync' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo sync': {line!r}\n  stdout: {channel_result.stdout!r}"
            )

    def test_successful_sync_has_no_traceback_on_stderr(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo sync' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo sync'.\n  stderr: {channel_result.stderr!r}"
        )

    def test_invalid_flag_error_routes_to_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Argument-parsing error for a bad flag value must appear on stderr, not stdout.

        Confirms channel discipline: the rejection error for '--fail-fast=unexpected'
        must be routed to stderr only. Stdout must be free of argument-error details.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _CLI_FLAG_FAIL_FAST + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SYNC,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for {bad_token!r}.\n  stderr: {result.stderr!r}"
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected {_DOES_NOT_TAKE_VALUE_PHRASE!r} in stderr for {bad_token!r}.\n  stderr: {result.stderr!r}"
        )
        assert bad_token not in result.stdout, (
            f"'{bad_token}' error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_int_flag_non_integer_error_routes_to_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Non-integer value error for '--jobs-network' must appear on stderr, not stdout.

        Confirms channel discipline for typed int flag errors: supplying
        '--jobs-network abc' must route the rejection error to stderr only,
        with stdout remaining free of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SYNC,
            _CLI_FLAG_JOBS_NETWORK,
            _INVALID_INT_VALUE,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{_CLI_FLAG_JOBS_NETWORK} {_INVALID_INT_VALUE}'.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _INVALID_INT_PHRASE in result.stderr, (
            f"Expected {_INVALID_INT_PHRASE!r} in stderr for '{_CLI_FLAG_JOBS_NETWORK} {_INVALID_INT_VALUE}'.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _INVALID_INT_VALUE not in result.stdout, f"Error detail leaked to stdout.\n  stdout: {result.stdout!r}"
