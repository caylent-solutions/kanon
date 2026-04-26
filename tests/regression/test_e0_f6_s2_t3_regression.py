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

"""Regression guard for E0-F6-S2-T3: git ls-remote not retried on transient errors.

Bug reference: E0-F6-S2-T3 / Bug 7 -- git ls-remote calls used by
_ResolveVersionConstraint() to resolve PEP 440 version constraints failed
immediately on transient network errors with no retry. A single dropped
connection or DNS hiccup would cause a sync to fail with no opportunity to
recover.

Root cause: project.py _ResolveVersionConstraint() called subprocess.run with
["git", "ls-remote", "--tags", remote_url] directly, without any retry loop.
If the subprocess returned a non-zero exit code, the function raised
ManifestInvalidRevisionError immediately. No retry was attempted regardless of
the failure type.

Fix (landed in E0-F6-S2-T3): Extracted the subprocess.run call into a new
module-level helper _run_ls_remote_with_retry(). The helper reads
KANON_GIT_RETRY_COUNT (default 3) and KANON_GIT_RETRY_DELAY (default 1) from
the environment and runs up to KANON_GIT_RETRY_COUNT attempts with exponential
backoff between failures. Authentication errors (stderr containing
"Authentication" or "Permission denied") are detected and not retried to avoid
credential lockouts. Each retry attempt is logged with attempt number and
reason.

This regression guard asserts that:
1. A transient failure followed by a success resolves the version constraint
   correctly -- the retry mechanism fires and recovers (AC-TEST-001).
2. The exact bug condition from E0-F6-S2-T3 is reproduced: a single transient
   failure that would have caused an immediate error before the fix is now
   retried and succeeds (AC-TEST-002).
3. The test passes against the current fixed code (AC-TEST-003).
4. The structural retry helper is present in the source (AC-FUNC-001).
5. Retry diagnostic warnings go to the logging channel, not stdout (AC-CHANNEL-001).
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


def _make_project(remote_url="https://git.example.com/org/library.git"):
    """Return a Project instance with minimal attributes mocked.

    Bypasses __init__ to avoid requiring a real manifest, git client, or remote
    configuration. Sets only the attributes accessed by _ResolveVersionConstraint:
    - revisionExpr: a PEP 440 constraint expression
    - name: project name for error message formatting
    - remote.url: the URL passed to git ls-remote
    - _constraint_resolved: caching guard (False means resolution is needed)

    Args:
        remote_url: The URL to assign to project.remote.url.

    Returns:
        A Project instance ready for _ResolveVersionConstraint() invocation.
    """
    project = Project.__new__(Project)
    project.name = "regression-library"
    project.revisionExpr = "refs/tags/dev/regression-library/~=1.0.0"
    project._constraint_resolved = False

    remote = mock.MagicMock()
    remote.url = remote_url
    project.remote = remote

    return project


def _make_transient_failure(stderr="Connection reset by peer"):
    """Return a mock CompletedProcess representing a transient ls-remote failure.

    Args:
        stderr: Error text placed in the mock's stderr attribute.

    Returns:
        Mock with returncode=1 and the given stderr text.
    """
    result = mock.MagicMock()
    result.returncode = 1
    result.stdout = ""
    result.stderr = stderr
    return result


def _make_success(tags=("refs/tags/dev/regression-library/1.0.0",)):
    """Return a mock CompletedProcess representing a successful ls-remote call.

    Args:
        tags: Tuple of tag ref strings to include in stdout.

    Returns:
        Mock with returncode=0 and stdout containing one line per tag.
    """
    lines = "\n".join(f"abc1234{i:07x}\t{tag}" for i, tag in enumerate(tags))
    result = mock.MagicMock()
    result.returncode = 0
    result.stdout = lines
    result.stderr = ""
    return result


# ---------------------------------------------------------------------------
# AC-TEST-001 -- regression: transient failure is retried and recovers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_transient_failure_is_retried_and_recovers(monkeypatch):
    """AC-TEST-001: A transient git ls-remote failure must be retried until success.

    This test reproduces the regression scenario for E0-F6-S2-T3: the first
    ls-remote call fails with a network transient error. Before the fix,
    _ResolveVersionConstraint() raised ManifestInvalidRevisionError immediately.
    After the fix, the retry helper retries and succeeds on the second call.

    If this test fails with ManifestInvalidRevisionError instead of completing
    normally, the _run_ls_remote_with_retry helper has been removed or bypassed
    and Bug 7 has regressed.

    Arrange: Set KANON_GIT_RETRY_COUNT=3, KANON_GIT_RETRY_DELAY=0. Mock
    subprocess.run to fail on the first call with a transient error, then
    succeed with a matching tag on the second call.
    Act: Call _ResolveVersionConstraint().
    Assert: No exception raised. revisionExpr resolved to the matching tag.
    subprocess.run called exactly twice (1 failure + 1 success).
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()
    failure = _make_transient_failure("Connection reset by peer")
    success = _make_success(("refs/tags/dev/regression-library/1.0.0",))

    with mock.patch("subprocess.run", side_effect=[failure, success]) as mock_run:
        with mock.patch("time.sleep"):
            try:
                project._ResolveVersionConstraint()
            except ManifestInvalidRevisionError as exc:
                raise AssertionError(
                    "E0-F6-S2-T3 regression: _ResolveVersionConstraint() raised "
                    f"ManifestInvalidRevisionError after a transient failure. "
                    "Before the fix, the function called subprocess.run directly "
                    "with no retry loop and failed immediately on the first non-zero "
                    "returncode. After the fix, the _run_ls_remote_with_retry() helper "
                    "retries the call and should have succeeded on the second attempt. "
                    f"Exception raised: {exc}"
                ) from exc

    assert project.revisionExpr == "refs/tags/dev/regression-library/1.0.0", (
        "E0-F6-S2-T3 regression: after a transient failure followed by a successful "
        "ls-remote call, revisionExpr must be resolved to the matching tag "
        "'refs/tags/dev/regression-library/1.0.0'. "
        f"Got: {project.revisionExpr!r}. "
        "The _run_ls_remote_with_retry() retry resolved the correct tag but "
        "_ResolveVersionConstraint() did not assign it to revisionExpr."
    )
    assert mock_run.call_count == 2, (
        "E0-F6-S2-T3 regression: expected subprocess.run to be called exactly 2 times "
        "(1 transient failure + 1 successful retry). "
        f"Actual call count: {mock_run.call_count}. "
        "If call count is 1, the retry loop was removed. "
        "If call count is 0, subprocess.run was not called at all."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- exact bug condition from E0-F6-S2-T3
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_exact_bug_condition_single_transient_failure(monkeypatch):
    """AC-TEST-002: The exact E0-F6-S2-T3 bug condition: no retry on transient fail.

    Before the fix, _ResolveVersionConstraint() called subprocess.run directly
    without any retry wrapper. A single transient failure (non-zero returncode,
    no auth-related stderr) immediately raised ManifestInvalidRevisionError.

    This test reproduces that condition: the first subprocess.run call returns
    a non-zero code with a transient error message ("Could not resolve host").
    After the fix, this must NOT raise -- the retry mechanism absorbs the first
    failure and succeeds on the second attempt.

    The bug is confirmed if the test raises ManifestInvalidRevisionError on
    the first failure without giving the retry loop a chance to run.

    Arrange: Set KANON_GIT_RETRY_COUNT=2, KANON_GIT_RETRY_DELAY=0. First call
    fails with DNS resolution error; second call succeeds.
    Act: Call _ResolveVersionConstraint().
    Assert: No exception. subprocess.run called exactly twice.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "2")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project("https://git.example.com/org/constraint-lib.git")
    project.revisionExpr = "refs/tags/dev/constraint-lib/~=2.0.0"

    dns_failure = _make_transient_failure("Could not resolve host: git.example.com")
    tag_success = _make_success(("refs/tags/dev/constraint-lib/2.0.0",))

    with mock.patch("subprocess.run", side_effect=[dns_failure, tag_success]) as mock_run:
        with mock.patch("time.sleep"):
            try:
                project._ResolveVersionConstraint()
            except ManifestInvalidRevisionError as exc:
                raise AssertionError(
                    "E0-F6-S2-T3 regression confirmed: _ResolveVersionConstraint() "
                    "raised ManifestInvalidRevisionError for a recoverable DNS error. "
                    "This is the exact Bug 7 symptom: no retry attempted on a transient "
                    "network failure.\n"
                    "Root cause if failing: the _run_ls_remote_with_retry() wrapper is "
                    "missing or not called from _ResolveVersionConstraint(). The function "
                    "must delegate to _run_ls_remote_with_retry() so transient failures "
                    "are retried up to KANON_GIT_RETRY_COUNT times.\n"
                    f"Exception: {exc}"
                ) from exc

    assert mock_run.call_count == 2, (
        "E0-F6-S2-T3 regression: subprocess.run must be called exactly 2 times "
        "(1 transient failure + 1 success with KANON_GIT_RETRY_COUNT=2). "
        f"Actual: {mock_run.call_count}. "
        "A count of 1 indicates the retry loop was removed (Bug 7 regressed)."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- current fixed code passes multiple retry scenarios
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "transient_stderr,constraint,success_tags,expected_revision,description",
    [
        (
            "Connection timed out",
            "refs/tags/dev/lib/~=1.0.0",
            ("refs/tags/dev/lib/1.0.0", "refs/tags/dev/lib/1.1.0"),
            "refs/tags/dev/lib/1.0.0",
            "timeout error retried; ~=1.0.0 resolves to 1.0.0 (highest 1.0.x)",
        ),
        (
            "Could not resolve host",
            "refs/tags/dev/lib/~=2.5.0",
            ("refs/tags/dev/lib/2.5.0",),
            "refs/tags/dev/lib/2.5.0",
            "DNS error retried; single matching tag resolves correctly",
        ),
        (
            "Connection refused",
            "refs/tags/dev/lib/~=3.0",
            ("refs/tags/dev/lib/3.0.0", "refs/tags/dev/lib/3.1.0"),
            "refs/tags/dev/lib/3.1.0",
            "refused connection retried; ~=3.0 resolves to highest 3.x",
        ),
    ],
    ids=[
        "timeout_resolves_1_0_0",
        "dns_resolves_2_5_0",
        "refused_resolves_highest_3_x",
    ],
)
def test_regression_fixed_code_retries_and_resolves(
    monkeypatch,
    transient_stderr,
    constraint,
    success_tags,
    expected_revision,
    description,
):
    """AC-TEST-003: Current fixed code retries transient failures and resolves correctly.

    Verifies the E0-F6-S2-T3 fix handles multiple transient failure types:
    connection timeouts, DNS resolution failures, and connection refusals. For
    each type a single failure followed by a successful ls-remote call must
    produce a correctly resolved revisionExpr.

    This is the positive-path confirmation that the fix is in place and working.
    If any parametrized case raises, the retry mechanism has been broken. If
    revisionExpr is wrong, the constraint resolution logic is broken.

    Arrange: Set retry vars. Set project.revisionExpr to a matching constraint
    for each tag set. Mock subprocess.run to fail once then succeed.
    Act: Call _ResolveVersionConstraint().
    Assert: No exception. revisionExpr == expected_revision.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()
    project.revisionExpr = constraint

    failure = _make_transient_failure(transient_stderr)
    success = _make_success(success_tags)

    with mock.patch("subprocess.run", side_effect=[failure, success]):
        with mock.patch("time.sleep"):
            try:
                project._ResolveVersionConstraint()
            except ManifestInvalidRevisionError as exc:
                raise AssertionError(
                    f"E0-F6-S2-T3 regression ({description}): "
                    f"_ResolveVersionConstraint() raised ManifestInvalidRevisionError "
                    f"for a recoverable transient failure ('{transient_stderr}'). "
                    "The retry mechanism in _run_ls_remote_with_retry() must absorb "
                    "transient failures and retry. "
                    f"Exception: {exc}"
                ) from exc

    assert project.revisionExpr == expected_revision, (
        f"E0-F6-S2-T3 regression ({description}): revisionExpr not resolved "
        f"to expected tag {expected_revision!r}. "
        f"Got: {project.revisionExpr!r}. "
        "The retry succeeded but the constraint resolution produced the wrong tag."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- structural guard: _run_ls_remote_with_retry present in source
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_ls_remote_retry_helper_present_in_project_source():
    """AC-FUNC-001: The retry helper _run_ls_remote_with_retry is in project.py.

    Inspects project_module to confirm:
    - _run_ls_remote_with_retry is defined at module level.
    - _ResolveVersionConstraint calls _run_ls_remote_with_retry (not subprocess.run).

    If either check fails, the retry helper has been structurally removed or
    bypassed and Bug 7 (no retry on transient ls-remote failure) would recur
    for any version constraint resolution that encounters a transient network error.

    This guard prevents the fix from silently disappearing during refactors.
    """
    assert hasattr(project_module, "_run_ls_remote_with_retry"), (
        "E0-F6-S2-T3 regression guard: '_run_ls_remote_with_retry' is no longer "
        "defined in project.py. This module-level helper wraps the git ls-remote "
        "subprocess call in an exponential backoff retry loop. "
        "Restore the function and ensure _ResolveVersionConstraint() delegates to it."
    )

    resolve_source = inspect.getsource(Project._ResolveVersionConstraint)

    assert "_run_ls_remote_with_retry" in resolve_source, (
        "E0-F6-S2-T3 regression guard: '_run_ls_remote_with_retry' is no longer "
        "called inside Project._ResolveVersionConstraint(). "
        "The call that delegates ls-remote execution to the retry-aware helper "
        "has been removed from project.py. "
        "Restore the '_run_ls_remote_with_retry(remote_url)' call inside "
        "_ResolveVersionConstraint() to prevent Bug 7 from recurring."
    )

    retry_source = inspect.getsource(project_module._run_ls_remote_with_retry)

    assert "for attempt in range" in retry_source or "while" in retry_source, (
        "E0-F6-S2-T3 regression guard: '_run_ls_remote_with_retry' no longer "
        "contains a retry loop. The loop that attempts ls-remote up to "
        "KANON_GIT_RETRY_COUNT times has been removed. "
        "Restore the retry loop in project.py _run_ls_remote_with_retry()."
    )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001 -- stdout vs stderr discipline for retry warnings
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_retry_warning_goes_to_logging_not_stdout(monkeypatch, caplog):
    """AC-CHANNEL-001: Retry attempt warnings go to the logging channel, not stdout.

    stdout is reserved for machine-consumable output. Diagnostic messages such
    as "git ls-remote attempt N/M failed, retrying" must go through the logging
    subsystem (which routes to stderr in production), not via print() to stdout.

    This test verifies:
    1. A WARNING log record is captured when a retry occurs.
    2. The WARNING message does not appear in any print() call to stdout.

    Arrange: Set KANON_GIT_RETRY_COUNT=2, KANON_GIT_RETRY_DELAY=0. Mock
    subprocess.run to fail once then succeed. Capture print() and log records.
    Act: Call _ResolveVersionConstraint().
    Assert: WARNING in log records; warning text not printed to stdout.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "2")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()
    failure = _make_transient_failure("Network unreachable")
    success = _make_success(("refs/tags/dev/regression-library/1.0.0",))

    printed_lines: list = []

    def _capture_print(*args, **kwargs):
        printed_lines.extend(str(a) for a in args)

    with mock.patch("subprocess.run", side_effect=[failure, success]):
        with mock.patch("time.sleep"):
            with mock.patch("builtins.print", side_effect=_capture_print):
                with mock.patch.object(project_module.logger, "warning") as mock_warning:
                    project._ResolveVersionConstraint()

    assert mock_warning.called, (
        "E0-F6-S2-T3 regression (channel discipline): expected logger.warning to be "
        "called at least once during a retry cycle, but it was never called. "
        "The retry log in _run_ls_remote_with_retry() must use logger.warning(), "
        "not print() or any other output channel."
    )

    retry_warning_found_in_stdout = any(
        "retrying" in line.lower() or "attempt" in line.lower() for line in printed_lines
    )
    assert not retry_warning_found_in_stdout, (
        "E0-F6-S2-T3 regression (channel discipline): retry warning text was written "
        "to stdout via print() instead of the logging channel. "
        f"stdout lines captured: {printed_lines!r}. "
        "Retry diagnostic messages must use logger.warning(), not print()."
    )
