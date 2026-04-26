# Copyright (C) 2026 Caylent, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Regression guard for E0-F6-S2-T4: ls-remote errors missing stderr.

Bug reference: E0-F6-S2-T4 / Bug 8 -- when git ls-remote fails and raises
ManifestInvalidRevisionError, the error message did not include the stderr
output from the git subprocess, the remote URL, or the constraint that was
being resolved. Operators had no diagnostic information about what went wrong.

Root cause: project.py _ResolveVersionConstraint() called subprocess.run
directly and constructed ManifestInvalidRevisionError without capturing
result.stderr. The error message contained only a generic "revision not found"
string, making it impossible to determine whether the failure was a network
error, authentication error, or other transient condition.

Fix (landed in E0-F6-S2-T3/T4): The retry helper _run_ls_remote_with_retry()
captures result.stderr on every attempt. On final failure it includes the
stderr text, the remote URL, and (via _ResolveVersionConstraint's re-raise)
the constraint expression in the ManifestInvalidRevisionError message.

This regression guard asserts that:
1. The error message includes the stderr text from the failed subprocess
   (AC-TEST-001).
2. The exact bug condition from E0-F6-S2-T4 is reproducible -- a failed
   ls-remote raises ManifestInvalidRevisionError with URL, constraint, and
   stderr in the message (AC-TEST-002).
3. The test passes against the current fixed code for multiple failure types
   (AC-TEST-003).
4. The guard prevents Bug 8 from recurring via a structural source inspection
   (AC-FUNC-001).
5. The error is raised on stderr, not swallowed or printed to stdout
   (AC-CHANNEL-001).
"""

import inspect
from unittest import mock

import pytest

from kanon_cli.repo.error import ManifestInvalidRevisionError
from kanon_cli.repo import project as project_module
from kanon_cli.repo.project import Project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(
    remote_url: str = "https://git.example.com/org/library.git",
    constraint: str = "refs/tags/dev/library/~=1.0.0",
) -> Project:
    """Return a Project instance with minimal attributes mocked.

    Bypasses __init__ to avoid requiring a real manifest, git client, or remote
    configuration. Sets only the attributes accessed by _ResolveVersionConstraint:
    - revisionExpr: a PEP 440 constraint expression
    - name: project name for error message formatting
    - remote.url: the URL passed to git ls-remote
    - _constraint_resolved: caching guard (False means resolution is needed)

    Args:
        remote_url: The URL to assign to project.remote.url.
        constraint: The version constraint to assign to project.revisionExpr.

    Returns:
        A Project instance ready for _ResolveVersionConstraint() invocation.
    """
    project = Project.__new__(Project)
    project.name = "regression-library"
    project.revisionExpr = constraint
    project._constraint_resolved = False

    remote = mock.MagicMock()
    remote.url = remote_url
    project.remote = remote

    return project


def _make_failure(stderr: str = "fatal: repository not found") -> mock.MagicMock:
    """Return a mock CompletedProcess representing a failed git ls-remote call.

    Args:
        stderr: The error text to include in stderr output.

    Returns:
        Mock with returncode=1 and the given stderr text.
    """
    result = mock.MagicMock()
    result.returncode = 1
    result.stdout = ""
    result.stderr = stderr
    return result


# ---------------------------------------------------------------------------
# AC-TEST-001 -- error message includes stderr from failed subprocess
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_error_message_includes_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-TEST-001: ManifestInvalidRevisionError includes stderr from the failed subprocess.

    This test guards against Bug 8 regressing. The bug was that when git ls-remote
    failed, the ManifestInvalidRevisionError message contained only a generic
    "revision not found" string -- it did not include the stderr output from the
    subprocess that would explain the actual failure reason.

    Before the fix, an operator seeing the exception had no way to determine
    whether the failure was a network issue, authentication error, or repository
    not found. After the fix, stderr is captured and included in the message.

    If this test fails (the assertion on stderr content fails), the stderr
    capture in _run_ls_remote_with_retry() has been removed or broken, and
    Bug 8 has regressed.

    Arrange: Set KANON_GIT_RETRY_COUNT=1 to skip the retry loop. Mock
    subprocess.run to fail with a distinctive stderr string.
    Act: Call _ResolveVersionConstraint() and expect ManifestInvalidRevisionError.
    Assert: The raised error message contains the stderr string.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    stderr_text = "fatal: repository 'https://git.example.com/org/library.git' not found"
    project = _make_project()
    failure = _make_failure(stderr_text)

    with mock.patch("subprocess.run", return_value=failure):
        with mock.patch("time.sleep"):
            with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                project._ResolveVersionConstraint()

    error_message = str(exc_info.value)
    assert stderr_text in error_message, (
        "E0-F6-S2-T4 regression (Bug 8): ManifestInvalidRevisionError message does "
        "not contain the stderr text from the failed git ls-remote subprocess. "
        f"Expected to find {stderr_text!r} in the error message, "
        f"but got: {error_message!r}. "
        "The _run_ls_remote_with_retry() function must capture result.stderr and "
        "include it in the ManifestInvalidRevisionError message so operators can "
        "diagnose the root cause of the failure."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- exact bug condition: ls-remote error missing URL and constraint
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "remote_url,constraint,stderr_text,field_name",
    [
        (
            "https://git.internal.example.org/platform/build-tools.git",
            "refs/tags/dev/build-tools/~=2.5.0",
            "fatal: could not read Username for 'https://git.internal.example.org'",
            "remote URL",
        ),
        (
            "https://git.example.com/org/constraint-lib.git",
            "refs/tags/dev/constraint-lib/~=3.1.0",
            "Connection refused",
            "constraint expression",
        ),
        (
            "https://mirrors.example.net/git/infra/deploy.git",
            "refs/tags/dev/deploy/~=1.2.0",
            "Could not resolve host: mirrors.example.net",
            "stderr text",
        ),
    ],
    ids=[
        "url_in_error_message",
        "constraint_in_error_message",
        "stderr_in_error_message",
    ],
)
def test_regression_exact_bug_condition_missing_context(
    monkeypatch: pytest.MonkeyPatch,
    remote_url: str,
    constraint: str,
    stderr_text: str,
    field_name: str,
) -> None:
    """AC-TEST-002: Exact Bug 8 condition -- error message contains URL, constraint, and stderr.

    This parametrized test reproduces the exact E0-F6-S2-T4 bug condition:
    - url_in_error_message: The remote URL must appear in the error message.
    - constraint_in_error_message: The constraint expression must appear.
    - stderr_in_error_message: The subprocess stderr must appear.

    Before the fix, none of these fields appeared in the ManifestInvalidRevisionError.
    An operator had no way to know which URL failed, what constraint was being
    resolved, or what the git subprocess actually reported.

    After the fix, _run_ls_remote_with_retry() includes the URL and stderr in
    its own error message, and _ResolveVersionConstraint() re-raises with the
    constraint and wraps the original message.

    If any parametrized case fails, the corresponding field has been dropped from
    the error message and Bug 8 has partially regressed.

    Arrange: Set KANON_GIT_RETRY_COUNT=1 to exhaust retries in one attempt.
    Mock subprocess.run to fail with the given stderr.
    Act: Call _ResolveVersionConstraint().
    Assert: Error message contains the URL, constraint, and stderr text.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project(remote_url=remote_url, constraint=constraint)
    failure = _make_failure(stderr_text)

    with mock.patch("subprocess.run", return_value=failure):
        with mock.patch("time.sleep"):
            with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                project._ResolveVersionConstraint()

    error_message = str(exc_info.value)

    assert remote_url in error_message, (
        f"E0-F6-S2-T4 regression (Bug 8 -- {field_name}): ManifestInvalidRevisionError "
        f"does not contain the remote URL {remote_url!r}. "
        f"Full error message: {error_message!r}. "
        "The remote URL must be included in the error message from "
        "_run_ls_remote_with_retry() so operators know which repository was unreachable."
    )

    assert constraint in error_message, (
        f"E0-F6-S2-T4 regression (Bug 8 -- {field_name}): ManifestInvalidRevisionError "
        f"does not contain the constraint expression {constraint!r}. "
        f"Full error message: {error_message!r}. "
        "The constraint expression must appear in the error message from "
        "_ResolveVersionConstraint() so operators know which constraint failed."
    )

    assert stderr_text in error_message, (
        f"E0-F6-S2-T4 regression (Bug 8 -- {field_name}): ManifestInvalidRevisionError "
        f"does not contain the subprocess stderr {stderr_text!r}. "
        f"Full error message: {error_message!r}. "
        "The stderr output from git ls-remote must be captured and included in the "
        "error message so operators see the actual failure reason."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- current fixed code includes all three fields for multiple errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "remote_url,constraint,stderr_text,description",
    [
        (
            "https://git.example.com/org/lib-a.git",
            "refs/tags/dev/lib-a/~=1.0.0",
            "fatal: repository not found",
            "repository not found -- all three fields in error",
        ),
        (
            "https://git.example.com/org/lib-b.git",
            "refs/tags/dev/lib-b/~=2.3.0",
            "Could not resolve host: git.example.com",
            "DNS failure -- all three fields in error",
        ),
        (
            "https://git.example.com/org/lib-c.git",
            "refs/tags/dev/lib-c/~=5.1.0",
            "Connection timed out after 30000 milliseconds",
            "timeout -- all three fields in error",
        ),
    ],
    ids=[
        "not_found_all_fields",
        "dns_all_fields",
        "timeout_all_fields",
    ],
)
def test_regression_fixed_code_includes_all_context_in_error(
    monkeypatch: pytest.MonkeyPatch,
    remote_url: str,
    constraint: str,
    stderr_text: str,
    description: str,
) -> None:
    """AC-TEST-003: Current fixed code includes URL, constraint, and stderr in the error.

    Verifies the E0-F6-S2-T4 fix across multiple failure types: repository not
    found, DNS failures, and timeout errors. For each type the raised
    ManifestInvalidRevisionError must contain the remote URL, the constraint
    expression, and the subprocess stderr.

    This is the positive-path confirmation that the fix is in place. If any
    parametrized case fails with a missing field, the fix has been partially
    reverted or a refactor accidentally dropped one of the three context fields.

    Arrange: Set KANON_GIT_RETRY_COUNT=1 to exhaust retries in one attempt.
    Mock subprocess.run to fail with the given error type.
    Act: Call _ResolveVersionConstraint().
    Assert: Error message contains all three: URL, constraint, and stderr.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project(remote_url=remote_url, constraint=constraint)
    failure = _make_failure(stderr_text)

    with mock.patch("subprocess.run", return_value=failure):
        with mock.patch("time.sleep"):
            with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                project._ResolveVersionConstraint()

    error_message = str(exc_info.value)

    assert remote_url in error_message, (
        f"E0-F6-S2-T4 regression ({description}): remote URL {remote_url!r} "
        f"missing from error message {error_message!r}."
    )
    assert constraint in error_message, (
        f"E0-F6-S2-T4 regression ({description}): constraint {constraint!r} "
        f"missing from error message {error_message!r}."
    )
    assert stderr_text in error_message, (
        f"E0-F6-S2-T4 regression ({description}): stderr {stderr_text!r} missing from error message {error_message!r}."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- structural guard: stderr capture is present in source
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_stderr_captured_in_ls_remote_helper() -> None:
    """AC-FUNC-001: _run_ls_remote_with_retry captures stderr in its error message.

    Inspects the source of _run_ls_remote_with_retry() to confirm:
    - result.stderr is accessed (not discarded) after a failed subprocess call.
    - The error message raised by ManifestInvalidRevisionError includes the
      stderr variable.

    If these structural checks fail, the stderr capture was removed during a
    refactor and Bug 8 would recur silently -- callers would see a vague error
    message with no diagnostic information from git.

    This guard prevents the fix from disappearing during future refactors.
    """
    assert hasattr(project_module, "_run_ls_remote_with_retry"), (
        "E0-F6-S2-T4 regression guard: '_run_ls_remote_with_retry' is no longer "
        "defined in project.py. This module-level helper wraps git ls-remote with "
        "retry logic and captures stderr for error messages. Restore the function."
    )

    helper_source = inspect.getsource(project_module._run_ls_remote_with_retry)

    assert "result.stderr" in helper_source or "stderr" in helper_source, (
        "E0-F6-S2-T4 regression guard: '_run_ls_remote_with_retry' no longer "
        "accesses result.stderr. The stderr capture that was added as part of the "
        "Bug 8 fix has been removed. Restore the capture of result.stderr and its "
        "inclusion in the ManifestInvalidRevisionError message."
    )

    assert "ManifestInvalidRevisionError" in helper_source, (
        "E0-F6-S2-T4 regression guard: '_run_ls_remote_with_retry' no longer "
        "raises ManifestInvalidRevisionError. The error-raising path that includes "
        "URL and stderr has been removed or replaced with a generic exception."
    )

    resolve_source = inspect.getsource(Project._ResolveVersionConstraint)

    assert "_run_ls_remote_with_retry" in resolve_source, (
        "E0-F6-S2-T4 regression guard: '_run_ls_remote_with_retry' is no longer "
        "called from _ResolveVersionConstraint(). The delegation to the stderr-capturing "
        "helper has been removed. Restore the call so ls-remote failures include "
        "stderr in the ManifestInvalidRevisionError."
    )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001 -- error is propagated via exception, not swallowed or printed
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_ls_remote_error_propagated_not_printed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-CHANNEL-001: ls-remote failure raises ManifestInvalidRevisionError, not print.

    stdout is reserved for machine-consumable output. When git ls-remote fails,
    the failure must propagate as a ManifestInvalidRevisionError exception so
    callers can handle it and log it to stderr. The error must not be swallowed
    (silent failure) or written directly to stdout via print().

    This test verifies:
    1. ManifestInvalidRevisionError is raised (not silently swallowed).
    2. No error content is written to stdout via print() calls.

    Arrange: Set KANON_GIT_RETRY_COUNT=1. Mock subprocess.run to fail.
    Track all print() calls during _ResolveVersionConstraint().
    Act: Call _ResolveVersionConstraint().
    Assert: ManifestInvalidRevisionError is raised. No error printed to stdout.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    stderr_text = "fatal: repository not found during regression channel test"
    project = _make_project()
    failure = _make_failure(stderr_text)

    printed_lines: list = []

    def _capture_print(*args: object, **kwargs: object) -> None:
        printed_lines.extend(str(a) for a in args)

    raised_exception = None

    with mock.patch("subprocess.run", return_value=failure):
        with mock.patch("time.sleep"):
            with mock.patch("builtins.print", side_effect=_capture_print):
                try:
                    project._ResolveVersionConstraint()
                except ManifestInvalidRevisionError as exc:
                    raised_exception = exc

    assert raised_exception is not None, (
        "E0-F6-S2-T4 regression (AC-CHANNEL-001): _ResolveVersionConstraint() did not "
        "raise ManifestInvalidRevisionError when git ls-remote failed. "
        "The error is either swallowed silently or the retry logic resolved the call "
        "unexpectedly. The function must propagate ManifestInvalidRevisionError on "
        "ls-remote failure so callers receive a diagnostic exception."
    )

    error_text_in_stdout = any("not found" in line or "fatal" in line or stderr_text in line for line in printed_lines)
    assert not error_text_in_stdout, (
        "E0-F6-S2-T4 regression (AC-CHANNEL-001): ls-remote error text was written "
        "to stdout via print() instead of propagated as an exception. "
        f"Captured stdout lines: {printed_lines!r}. "
        "Error information must propagate via ManifestInvalidRevisionError, "
        "not be written to stdout."
    )
