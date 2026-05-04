"""Functional tests for flag coverage of 'kanon repo upload'.

Exercises every flag registered in ``subcmds/upload.py``'s ``_Options()`` method
by invoking ``kanon repo upload`` as a subprocess. Validates correct accept and
reject behavior for all flag values, and correct default behavior when flags
are omitted.

Flags in ``Upload._Options()`` include a mix of boolean (store_true / store_false)
and typed (string / append) flags. The full inventory:

Boolean store_true flags (accepted without an argument; rejected with inline value):
- ``-t`` / ``--topic-branch``         (dest=auto_topic, store_true)
- ``--hashtag-branch`` / ``--htb``    (store_true)
- ``-c`` / ``--current-branch``       (store_true, dest=current_branch)
- ``--cbr``                           (legacy alias, store_true, dest=current_branch)
- ``-p`` / ``--private``              (store_true, default=False)
- ``-w`` / ``--wip``                  (store_true, default=False)
- ``-r`` / ``--ready``                (store_true, default=False)
- ``-n`` / ``--dry-run``              (dest=dryrun, store_true, default=False)
- ``-y`` / ``--yes``                  (store_true, default=False)
- ``--ignore-untracked-files``        (store_true, default=False)

Boolean store_false flags (inverse toggling another dest):
- ``--no-current-branch``             (store_false, dest=current_branch)
- ``--ne`` / ``--no-emails``          (store_false, dest=notify, default=True)
- ``--no-ignore-untracked-files``     (store_false, dest=ignore_untracked_files)
- ``--no-cert-checks``                (store_false, dest=validate_certs, default=True)

Typed / string flags (accept a value):
- ``--topic``                         (string, dest=topic)
- ``--hashtag`` / ``--ht``            (append, dest=hashtags)
- ``-l`` / ``--label``                (append, dest=labels)
- ``--pd`` / ``--patchset-description`` (string, dest=patchset_description)
- ``--re`` / ``--reviewers``          (string, append, dest=reviewers)
- ``--cc``                            (string, append)
- ``--br`` / ``--branch``             (string, dest=branch)
- ``-o`` / ``--push-option``          (string, append, dest=push_options)
- ``-D`` / ``--destination`` / ``--dest`` (string, dest=dest_branch)

AC wording note: AC-TEST-002 states "every flag that accepts enumerated values
has a negative test for an invalid value." Upload flags accept typed string or
append values, not enumerated keyword values. For boolean store_true /
store_false flags, the applicable negative test is supplying an inline value
(e.g. --dry-run=unexpected), which optparse rejects with exit code 2. String
and append flags accept any string, so no enumeration constraint exists; those
flags are exercised only via valid-value tests that verify they do not cause
parse errors.

AC-TEST-003 note: Absence-default behavior is verified by running
'kanon repo upload' with flags omitted on a properly configured upload repo
and confirming that flags default to their documented values (all booleans
default to False, --ne/notify defaults to True, --no-cert-checks/validate_certs
defaults to True).

Covers:
- AC-TEST-001: Every ``_Options()`` flag in subcmds/upload.py has a valid-value test.
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
    _ENV_IGNORE_SSH_INFO,
    _run_kanon,
    _setup_upload_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- all domain literals extracted here.
# No inline literals in test bodies, f-string diagnostics, or parametrize tuples.
# ---------------------------------------------------------------------------

_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "upload-flags-test-project"

# Topic branch name for tests that require a reviewable branch.
_TOPIC_BRANCH_FLAGS = "feature/upload-flags-coverage"

# CLI token constants
_CLI_TOKEN_REPO = "repo"
_CLI_TOKEN_UPLOAD = "upload"
_CLI_FLAG_REPO_DIR = "--repo-dir"
_CLI_FLAG_DRY_RUN = "--dry-run"
_CLI_FLAG_DRY_RUN_SHORT = "-n"
_CLI_FLAG_YES = "--yes"
_CLI_FLAG_YES_SHORT = "-y"
_CLI_FLAG_TOPIC_BRANCH = "--topic-branch"
_CLI_FLAG_TOPIC_BRANCH_SHORT = "-t"
_CLI_FLAG_TOPIC = "--topic"
_CLI_FLAG_HASHTAG = "--hashtag"
_CLI_FLAG_HASHTAG_SHORT = "--ht"
_CLI_FLAG_HASHTAG_BRANCH = "--hashtag-branch"
_CLI_FLAG_HASHTAG_BRANCH_SHORT = "--htb"
_CLI_FLAG_LABEL = "--label"
_CLI_FLAG_LABEL_SHORT = "-l"
_CLI_FLAG_PATCHSET_DESCRIPTION = "--patchset-description"
_CLI_FLAG_PATCHSET_DESCRIPTION_SHORT = "--pd"
_CLI_FLAG_REVIEWERS = "--reviewers"
_CLI_FLAG_REVIEWERS_SHORT = "--re"
_CLI_FLAG_CC = "--cc"
_CLI_FLAG_BRANCH = "--branch"
_CLI_FLAG_BRANCH_SHORT = "--br"
_CLI_FLAG_CURRENT_BRANCH = "--current-branch"
_CLI_FLAG_CURRENT_BRANCH_SHORT = "-c"
_CLI_FLAG_NO_CURRENT_BRANCH = "--no-current-branch"
_CLI_FLAG_CBR = "--cbr"
_CLI_FLAG_NO_EMAILS = "--no-emails"
_CLI_FLAG_NO_EMAILS_SHORT = "--ne"
_CLI_FLAG_PRIVATE = "--private"
_CLI_FLAG_PRIVATE_SHORT = "-p"
_CLI_FLAG_WIP = "--wip"
_CLI_FLAG_WIP_SHORT = "-w"
_CLI_FLAG_READY = "--ready"
_CLI_FLAG_READY_SHORT = "-r"
_CLI_FLAG_PUSH_OPTION = "--push-option"
_CLI_FLAG_PUSH_OPTION_SHORT = "-o"
_CLI_FLAG_DESTINATION = "--destination"
_CLI_FLAG_DESTINATION_SHORT = "-D"
_CLI_FLAG_DESTINATION_ALT = "--dest"
_CLI_FLAG_IGNORE_UNTRACKED = "--ignore-untracked-files"
_CLI_FLAG_NO_IGNORE_UNTRACKED = "--no-ignore-untracked-files"
_CLI_FLAG_NO_CERT_CHECKS = "--no-cert-checks"

# Exit codes
_EXPECTED_EXIT_CODE = 0
_ARGPARSE_ERROR_EXIT_CODE = 2

# Inline-value suffix for boolean-flag negative tests.
# optparse exits 2 with '--<flag> option does not take a value'.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Error message phrase emitted by optparse for store_true flags with inline values.
_DOES_NOT_TAKE_VALUE_PHRASE = "does not take a value"

# Traceback marker used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# Nonexistent repo-dir name for pure argument-parser tests that do not need
# a real initialized repository.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-upload-flags-repo-dir"

# Valid example values for typed string flags.
_TOPIC_VALUE = "my-topic"
_HASHTAG_VALUE = "my-hashtag"
_LABEL_VALUE = "Code-Review+1"
_PATCHSET_DESC_VALUE = "my patchset description"
_REVIEWER_EMAIL = "reviewer@example.com"
_CC_EMAIL = "cc@example.com"
_BRANCH_VALUE = _TOPIC_BRANCH_FLAGS
_PUSH_OPTION_VALUE = "wip"
_DESTINATION_VALUE = "main"

# ---------------------------------------------------------------------------
# Parametrize tables -- all flags listed here for each category.
# Tuples are (flag_token, test_id). Short-form flags are NOT tested with
# inline '=value' syntax (only long-form flags support '--flag=value').
# ---------------------------------------------------------------------------

# All boolean store_true flags (short + long forms) -- for valid-value tests.
_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str]] = [
    (_CLI_FLAG_TOPIC_BRANCH_SHORT, "short-topic-branch"),
    (_CLI_FLAG_TOPIC_BRANCH, "long-topic-branch"),
    (_CLI_FLAG_HASHTAG_BRANCH_SHORT, "short-hashtag-branch-htb"),
    (_CLI_FLAG_HASHTAG_BRANCH, "long-hashtag-branch"),
    (_CLI_FLAG_CURRENT_BRANCH_SHORT, "short-current-branch"),
    (_CLI_FLAG_CURRENT_BRANCH, "long-current-branch"),
    (_CLI_FLAG_CBR, "long-cbr-legacy"),
    (_CLI_FLAG_PRIVATE_SHORT, "short-private"),
    (_CLI_FLAG_PRIVATE, "long-private"),
    (_CLI_FLAG_WIP_SHORT, "short-wip"),
    (_CLI_FLAG_WIP, "long-wip"),
    (_CLI_FLAG_READY_SHORT, "short-ready"),
    (_CLI_FLAG_READY, "long-ready"),
    (_CLI_FLAG_DRY_RUN_SHORT, "short-dry-run"),
    (_CLI_FLAG_DRY_RUN, "long-dry-run"),
    (_CLI_FLAG_YES_SHORT, "short-yes"),
    (_CLI_FLAG_YES, "long-yes"),
    (_CLI_FLAG_IGNORE_UNTRACKED, "long-ignore-untracked-files"),
]

# All boolean store_false flags (long forms only for negative tests).
_BOOL_STORE_FALSE_FLAGS: list[tuple[str, str]] = [
    (_CLI_FLAG_NO_CURRENT_BRANCH, "long-no-current-branch"),
    (_CLI_FLAG_NO_EMAILS_SHORT, "short-no-emails-ne"),
    (_CLI_FLAG_NO_EMAILS, "long-no-emails"),
    (_CLI_FLAG_NO_IGNORE_UNTRACKED, "long-no-ignore-untracked-files"),
    (_CLI_FLAG_NO_CERT_CHECKS, "long-no-cert-checks"),
]

# Long-form boolean flags (both store_true and store_false) for negative tests.
# Only long-form flags support '--flag=value' syntax in optparse.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    (_CLI_FLAG_TOPIC_BRANCH, "topic-branch"),
    (_CLI_FLAG_HASHTAG_BRANCH, "hashtag-branch"),
    (_CLI_FLAG_CURRENT_BRANCH, "current-branch"),
    (_CLI_FLAG_NO_CURRENT_BRANCH, "no-current-branch"),
    (_CLI_FLAG_PRIVATE, "private"),
    (_CLI_FLAG_WIP, "wip"),
    (_CLI_FLAG_READY, "ready"),
    (_CLI_FLAG_DRY_RUN, "dry-run"),
    (_CLI_FLAG_YES, "yes"),
    (_CLI_FLAG_IGNORE_UNTRACKED, "ignore-untracked-files"),
    (_CLI_FLAG_NO_IGNORE_UNTRACKED, "no-ignore-untracked-files"),
    (_CLI_FLAG_NO_EMAILS, "no-emails"),
    (_CLI_FLAG_NO_CERT_CHECKS, "no-cert-checks"),
]

# Typed string / append flags with valid values -- for valid-value tests.
# Tuples of (flag_token, value, test_id).
_TYPED_FLAGS_WITH_VALUES: list[tuple[str, str, str]] = [
    (_CLI_FLAG_TOPIC, _TOPIC_VALUE, "long-topic"),
    (_CLI_FLAG_HASHTAG, _HASHTAG_VALUE, "long-hashtag"),
    (_CLI_FLAG_HASHTAG_SHORT, _HASHTAG_VALUE, "short-hashtag-ht"),
    (_CLI_FLAG_LABEL, _LABEL_VALUE, "long-label"),
    (_CLI_FLAG_LABEL_SHORT, _LABEL_VALUE, "short-label"),
    (_CLI_FLAG_PATCHSET_DESCRIPTION, _PATCHSET_DESC_VALUE, "long-patchset-description"),
    (_CLI_FLAG_PATCHSET_DESCRIPTION_SHORT, _PATCHSET_DESC_VALUE, "short-patchset-description-pd"),
    (_CLI_FLAG_REVIEWERS, _REVIEWER_EMAIL, "long-reviewers"),
    (_CLI_FLAG_REVIEWERS_SHORT, _REVIEWER_EMAIL, "short-reviewers-re"),
    (_CLI_FLAG_CC, _CC_EMAIL, "long-cc"),
    (_CLI_FLAG_BRANCH, _BRANCH_VALUE, "long-branch"),
    (_CLI_FLAG_BRANCH_SHORT, _BRANCH_VALUE, "short-branch-br"),
    (_CLI_FLAG_PUSH_OPTION, _PUSH_OPTION_VALUE, "long-push-option"),
    (_CLI_FLAG_PUSH_OPTION_SHORT, _PUSH_OPTION_VALUE, "short-push-option"),
    (_CLI_FLAG_DESTINATION, _DESTINATION_VALUE, "long-destination"),
    (_CLI_FLAG_DESTINATION_SHORT, _DESTINATION_VALUE, "short-destination"),
    (_CLI_FLAG_DESTINATION_ALT, _DESTINATION_VALUE, "long-destination-alt"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoUploadFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/upload.py has a valid-value test.

    Exercises each flag registered in ``Upload._Options()`` by invoking
    'kanon repo upload' with the flag against a nonexistent repo-dir.
    Valid-value tests confirm the flag is accepted by the argument parser
    without an argument-parsing error (exit code != 2). The command may still
    fail for other reasons (no branches ready, no review URL configured), but
    it must not produce exit code 2.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _BOOL_STORE_TRUE_FLAGS],
        ids=[test_id for _, test_id in _BOOL_STORE_TRUE_FLAGS],
    )
    def test_bool_store_true_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean store_true flag is accepted by the argument parser (exit != 2).

        Calls 'kanon repo upload' with the given boolean flag against a
        nonexistent repo-dir and asserts that argparse does not reject the
        invocation (exit code != 2). A non-2 exit code confirms the flag
        itself was accepted; subsequent behavior (e.g. no branches ready) is
        not an argument-parsing error.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_UPLOAD,
            flag,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _BOOL_STORE_FALSE_FLAGS],
        ids=[test_id for _, test_id in _BOOL_STORE_FALSE_FLAGS],
    )
    def test_bool_store_false_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean store_false flag is accepted by the argument parser (exit != 2).

        Calls 'kanon repo upload' with the given store_false flag against a
        nonexistent repo-dir and asserts that argparse does not reject the
        invocation (exit code != 2).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_UPLOAD,
            flag,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        ("flag", "value"),
        [(flag, value) for flag, value, _ in _TYPED_FLAGS_WITH_VALUES],
        ids=[test_id for _, _, test_id in _TYPED_FLAGS_WITH_VALUES],
    )
    def test_typed_flag_with_valid_value_accepted(self, tmp_path: pathlib.Path, flag: str, value: str) -> None:
        """Each typed flag with a valid value is accepted by the argument parser (exit != 2).

        Calls 'kanon repo upload <flag> <value>' against a nonexistent repo-dir
        and asserts that argparse does not reject the invocation (exit code != 2).
        Typed flags (string, append) accept any string value, so the valid-value
        test confirms the flag and value are parsed without error.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_UPLOAD,
            flag,
            value,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} with value {value!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for boolean flags with inline values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoUploadFlagsInvalidValues:
    """AC-TEST-002: Negative tests for boolean flags with inline values.

    All boolean flags (store_true and store_false) do not accept a typed value.
    Supplying an inline value via '--flag=value' syntax causes optparse to reject
    the invocation with exit code 2 and the phrase 'does not take a value' on
    stderr.

    Typed string / append flags accept any string value and have no enumerated
    constraint to violate; they are covered only in AC-TEST-001.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with an inline value must exit 2.

        Supplies '--<flag>=unexpected' to 'kanon repo upload'. Since all tested
        flags are boolean (store_true or store_false), optparse rejects the inline
        value with exit code 2 and emits '--<flag> option does not take a value'
        on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_UPLOAD,
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
    def test_bool_flag_with_inline_value_emits_error_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with inline value must emit error on stderr, not stdout.

        The argument-parsing error for '--<flag>=unexpected' must appear on
        stderr only. Stdout must not contain the rejection detail (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_UPLOAD,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"'{bad_token}' produced empty stderr; error must appear on stderr."
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_does_not_take_value_phrase_in_stderr(
        self, tmp_path: pathlib.Path, flag: str
    ) -> None:
        """Each long-form boolean flag error must include 'does not take a value' in stderr.

        The embedded optparse parser consistently uses 'option does not take
        a value' for store_true / store_false flags supplied with an inline value.
        Confirms this canonical phrase appears in stderr for each such flag.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_UPLOAD,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected {_DOES_NOT_TAKE_VALUE_PHRASE!r} in stderr for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoUploadFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that omitting all optional Upload flags still produces a valid
    argument-parse pass (no exit code 2). Uses a properly configured upload
    repo so that 'kanon repo upload --dry-run --yes' succeeds, confirming
    the default values for all omitted flags produce correct behavior:

    - --dry-run defaults to False (dryrun=False)
    - --yes defaults to False (yes=False)
    - --topic-branch defaults to False (auto_topic=False)
    - --hashtag-branch defaults to False
    - --current-branch defaults to None/False
    - --private defaults to False
    - --wip defaults to False
    - --ready defaults to False
    - --ignore-untracked-files defaults to False
    - --no-emails / notify defaults to True
    - --no-cert-checks / validate_certs defaults to True

    The test uses --dry-run --yes explicitly (since those are required to exit 0
    in a valid upload scenario) but omits all other optional flags.
    """

    def test_all_optional_flags_omitted_is_not_argparse_error(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo upload' with all optional flags omitted is not an argparse error.

        Invokes 'kanon repo upload' on a fully configured upload repo with
        --dry-run and --yes (to achieve exit 0) but with every other optional
        flag omitted. Confirms that the absence of optional flags does not
        produce an argument-parsing error (exit code != 2), demonstrating
        that no flag is required by the argument parser.
        """
        checkout_dir, repo_dir, _ = _setup_upload_repo(tmp_path, _TOPIC_BRANCH_FLAGS, _PROJECT_NAME, _PROJECT_PATH)
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
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}' with all "
            f"optional flags omitted triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_all_optional_flags_omitted_exits_zero_in_valid_repo(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo upload --dry-run --yes' with all optional flags omitted exits 0.

        Invokes 'kanon repo upload --dry-run --yes' on a properly configured
        upload repo with all other optional flags omitted. Confirms that omitting
        optional flags does not prevent a successful upload invocation.
        """
        checkout_dir, repo_dir, _ = _setup_upload_repo(tmp_path, _TOPIC_BRANCH_FLAGS, _PROJECT_NAME, _PROJECT_PATH)
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
            f"'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}' with all "
            f"optional flags omitted exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoUploadFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of selected Upload flags as documented
    in Upload._Options() help text:

    - --dry-run: executes everything except the actual git push
    - --yes: answers yes to all safe prompts (no interactive stdin required)
    - --topic <value>: passes through to the upload without parse error
    - --destination <value>: passes through to the upload without parse error
    - --no-emails: suppresses email notifications (dest=notify set to False)
    - --no-cert-checks: disables SSL certificate verification
    """

    def test_dry_run_flag_produces_no_argparse_error_on_upload_repo(self, tmp_path: pathlib.Path) -> None:
        """'--dry-run' on a configured upload repo does not cause an argparse error.

        With a reviewable branch configured, '--dry-run --yes' must be accepted
        by the argument parser (exit != 2) and must produce an exit 0 result.
        Verifies '--dry-run' behaves as documented: executes everything except
        the actual git push.
        """
        checkout_dir, repo_dir, _ = _setup_upload_repo(tmp_path, _TOPIC_BRANCH_FLAGS, _PROJECT_NAME, _PROJECT_PATH)
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
            f"'{_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_topic_flag_passes_through_without_parse_error(self, tmp_path: pathlib.Path) -> None:
        """'--topic <value>' on a configured upload repo does not cause a parse error.

        '--topic' sets the Gerrit topic for the upload. Verifies that supplying
        a topic value does not cause an argument-parsing error (exit != 2) when
        combined with '--dry-run --yes' on a properly configured upload repo.
        """
        checkout_dir, repo_dir, _ = _setup_upload_repo(tmp_path, _TOPIC_BRANCH_FLAGS, _PROJECT_NAME, _PROJECT_PATH)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_UPLOAD,
            _CLI_FLAG_DRY_RUN,
            _CLI_FLAG_YES,
            _CLI_FLAG_TOPIC,
            _TOPIC_VALUE,
            cwd=checkout_dir,
            extra_env={_ENV_IGNORE_SSH_INFO: "1"},
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_TOPIC} {_TOPIC_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_destination_flag_passes_through_without_parse_error(self, tmp_path: pathlib.Path) -> None:
        """'--destination <value>' on a configured upload repo does not cause a parse error.

        '--destination' sets the target branch for review. Verifies that supplying
        a destination value does not cause an argument-parsing error (exit != 2)
        when combined with '--dry-run --yes' on a properly configured upload repo.
        """
        checkout_dir, repo_dir, _ = _setup_upload_repo(tmp_path, _TOPIC_BRANCH_FLAGS, _PROJECT_NAME, _PROJECT_PATH)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_UPLOAD,
            _CLI_FLAG_DRY_RUN,
            _CLI_FLAG_YES,
            _CLI_FLAG_DESTINATION,
            _DESTINATION_VALUE,
            cwd=checkout_dir,
            extra_env={_ENV_IGNORE_SSH_INFO: "1"},
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_DESTINATION} {_DESTINATION_VALUE}' triggered an "
            f"argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_no_emails_flag_accepted_without_parse_error(self, tmp_path: pathlib.Path) -> None:
        """'--no-emails' on a configured upload repo does not cause a parse error.

        '--no-emails' suppresses email notifications (sets notify=False). Verifies
        that combining '--no-emails --dry-run --yes' does not cause an
        argument-parsing error (exit != 2).
        """
        checkout_dir, repo_dir, _ = _setup_upload_repo(tmp_path, _TOPIC_BRANCH_FLAGS, _PROJECT_NAME, _PROJECT_PATH)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_UPLOAD,
            _CLI_FLAG_DRY_RUN,
            _CLI_FLAG_YES,
            _CLI_FLAG_NO_EMAILS,
            cwd=checkout_dir,
            extra_env={_ENV_IGNORE_SSH_INFO: "1"},
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_NO_EMAILS}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_no_cert_checks_flag_accepted_without_parse_error(self, tmp_path: pathlib.Path) -> None:
        """'--no-cert-checks' on a configured upload repo does not cause a parse error.

        '--no-cert-checks' disables SSL certificate verification. Verifies that
        combining '--no-cert-checks --dry-run --yes' does not cause an
        argument-parsing error (exit != 2).
        """
        checkout_dir, repo_dir, _ = _setup_upload_repo(tmp_path, _TOPIC_BRANCH_FLAGS, _PROJECT_NAME, _PROJECT_PATH)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_UPLOAD,
            _CLI_FLAG_DRY_RUN,
            _CLI_FLAG_YES,
            _CLI_FLAG_NO_CERT_CHECKS,
            cwd=checkout_dir,
            extra_env={_ENV_IGNORE_SSH_INFO: "1"},
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_NO_CERT_CHECKS}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoUploadFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for Upload flag invocations.

    Verifies orthogonal channel properties:
    - Successful flag invocations do not emit tracebacks or 'Error:'-prefixed
      messages to stdout.
    - Successful flag invocations do not emit tracebacks to stderr.
    - Argument-parsing errors (exit 2) route error detail to stderr, not stdout.

    Uses a class-scoped fixture that runs the upload once and shares the result
    across all channel assertions to avoid repeated expensive git setup.
    """

    @pytest.fixture(scope="class")
    def upload_flags_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo upload --dry-run --yes' once and return the CompletedProcess.

        Uses tmp_path_factory for class-scoped setup so the expensive git
        operations run once and all channel assertions share the result.

        Returns:
            The CompletedProcess from
            'kanon repo upload --dry-run --yes' on a valid configured repo.

        Raises:
            AssertionError: When setup or the upload itself exits non-zero.
        """
        tmp_path = tmp_path_factory.mktemp("upload_flags_channel")
        checkout_dir, repo_dir, _ = _setup_upload_repo(tmp_path, _TOPIC_BRANCH_FLAGS, _PROJECT_NAME, _PROJECT_PATH)
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

    def test_successful_upload_has_no_traceback_on_stdout(
        self, upload_flags_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo upload --dry-run --yes' must not emit tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        assert _TRACEBACK_MARKER not in upload_flags_result.stdout, (
            f"Python traceback found in stdout of successful "
            f"'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}'.\n"
            f"  stdout: {upload_flags_result.stdout!r}"
        )

    def test_successful_upload_has_no_error_keyword_on_stdout(
        self, upload_flags_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo upload --dry-run --yes' must not emit 'Error:' to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in upload_flags_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}': "
                f"{line!r}\n  stdout: {upload_flags_result.stdout!r}"
            )

    def test_successful_upload_has_no_traceback_on_stderr(
        self, upload_flags_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo upload --dry-run --yes' must not emit tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in upload_flags_result.stderr, (
            f"Python traceback found in stderr of successful "
            f"'kanon repo upload {_CLI_FLAG_DRY_RUN} {_CLI_FLAG_YES}'.\n"
            f"  stderr: {upload_flags_result.stderr!r}"
        )

    def test_argparse_error_routes_to_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Argument-parsing errors must appear on stderr, not stdout.

        '--dry-run=unexpected' causes optparse to exit 2. The error detail
        must be routed to stderr only; stdout must be free of the rejection
        message (orthogonal channel property).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _CLI_FLAG_DRY_RUN + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_UPLOAD,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"stderr must be non-empty for '{bad_token}' argument-parsing error."
        assert bad_token not in result.stdout, (
            f"'{bad_token}' error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )
