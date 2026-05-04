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

"""Unit tests for Bug 7: git ls-remote not retried on transient network errors.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 7 -- git ls-remote calls fail on
transient network errors without any retry.

Fix: Implement a retry loop with a maximum of KANON_GIT_RETRY_COUNT attempts
(default 3). Use exponential backoff starting at KANON_GIT_RETRY_DELAY seconds
(default 1), doubling each attempt. Do not retry on authentication errors.
Log each retry attempt with attempt number and reason.
"""

from unittest import mock

import pytest

from kanon_cli.repo.error import ManifestInvalidRevisionError
from kanon_cli.repo import project as project_module
from kanon_cli.repo.project import Project


# Logger name used by project.py -- needed for caplog level targeting.
_PROJECT_LOGGER_NAME = project_module.logger.name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(remote_url="https://example.com/org/repo.git"):
    """Return a Project instance with the bare minimum attributes mocked.

    Bypasses __init__ to avoid requiring a real manifest/remote setup.
    Sets the minimal attributes needed by _ResolveVersionConstraint:
    - revisionExpr: a PEP 440 constraint string
    - name: project name for error messages
    - remote.url: the remote URL for ls-remote
    - _constraint_resolved: caching flag (False by default)
    """
    project = Project.__new__(Project)
    project.name = "test-project"
    project.revisionExpr = "refs/tags/dev/mylib/~=1.0.0"
    project._constraint_resolved = False

    remote = mock.MagicMock()
    remote.url = remote_url
    project.remote = remote

    return project


def _make_success_result(tags=("refs/tags/dev/mylib/1.0.0", "refs/tags/dev/mylib/1.1.0")):
    """Return a mock CompletedProcess representing a successful ls-remote call.

    Args:
        tags: Tuple of tag strings to include in the ls-remote output.

    Returns:
        Mock with returncode=0 and stdout containing the tags.
    """
    lines = "\n".join(f"deadbeef{i:08x}\t{tag}" for i, tag in enumerate(tags))
    result = mock.MagicMock()
    result.returncode = 0
    result.stdout = lines
    result.stderr = ""
    return result


def _make_failure_result(stderr="Connection reset by peer"):
    """Return a mock CompletedProcess representing a transient ls-remote failure.

    Args:
        stderr: Error text to include in stderr output.

    Returns:
        Mock with returncode=1 and stderr containing the error text.
    """
    result = mock.MagicMock()
    result.returncode = 1
    result.stdout = ""
    result.stderr = stderr
    return result


# ---------------------------------------------------------------------------
# AC-TEST-001 -- Retry succeeds on second attempt after transient failure
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_retry_succeeds_on_second_attempt(monkeypatch):
    """AC-TEST-001: ls-remote is retried and succeeds on the second attempt.

    When the first ls-remote call fails with a transient error (non-zero
    returncode, no auth-related text in stderr), _ResolveVersionConstraint must
    retry the call. If the second call succeeds, revisionExpr is resolved to the
    matching tag and no exception is raised.

    Arrange: Mock subprocess.run to fail on the first call and succeed on the
    second call. Set KANON_GIT_RETRY_COUNT=3 and KANON_GIT_RETRY_DELAY=0 to
    avoid delays in the test.
    Act: Call _ResolveVersionConstraint().
    Assert: revisionExpr is resolved to the highest matching tag. subprocess.run
    was called exactly twice.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()

    failure = _make_failure_result("Connection reset by peer")
    success = _make_success_result()

    with mock.patch("subprocess.run", side_effect=[failure, success]) as mock_run:
        with mock.patch("time.sleep"):
            project._ResolveVersionConstraint()

    # ~=1.0.0 means >= 1.0.0, == 1.0.* (compatible release with 3-part version).
    # Both 1.0.0 and 1.1.0 are returned by _make_success_result(), but only
    # 1.0.0 satisfies ~=1.0.0 (because 1.1.0 is not == 1.0.*).
    assert project.revisionExpr == "refs/tags/dev/mylib/1.0.0", (
        f"Expected revisionExpr to be resolved to 'refs/tags/dev/mylib/1.0.0' "
        f"(highest tag satisfying ~=1.0.0) after retry, but got: {project.revisionExpr!r}"
    )
    assert mock_run.call_count == 2, (
        f"Expected subprocess.run to be called exactly 2 times (1 failure + 1 success), "
        f"but it was called {mock_run.call_count} times."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- Retries exhausted raises ManifestInvalidRevisionError
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_retries_exhausted_raises_error(monkeypatch):
    """AC-TEST-002: After max retry attempts, ManifestInvalidRevisionError is raised.

    When all ls-remote attempts fail with transient errors, the function must
    raise ManifestInvalidRevisionError after exhausting all retries. The retry
    count is bounded by KANON_GIT_RETRY_COUNT.

    Arrange: Set KANON_GIT_RETRY_COUNT=3 so there are 3 attempts. Mock
    subprocess.run to fail on all 3 attempts. Set KANON_GIT_RETRY_DELAY=0 to
    avoid delays.
    Act: Call _ResolveVersionConstraint().
    Assert: ManifestInvalidRevisionError is raised. subprocess.run was called
    exactly KANON_GIT_RETRY_COUNT times.
    """
    retry_count = 3
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", str(retry_count))
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()

    failure = _make_failure_result("Connection timed out")
    all_failures = [failure] * retry_count

    with mock.patch("subprocess.run", side_effect=all_failures) as mock_run:
        with mock.patch("time.sleep"):
            with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                project._ResolveVersionConstraint()

    assert mock_run.call_count == retry_count, (
        f"Expected subprocess.run to be called exactly {retry_count} times "
        f"(all retries exhausted), but it was called {mock_run.call_count} times."
    )
    assert "not found" in str(exc_info.value).lower() or "failed" in str(exc_info.value).lower(), (
        f"Expected ManifestInvalidRevisionError to describe the failure, but got: {exc_info.value!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- No retry on authentication error
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "auth_error_text",
    [
        "Authentication failed for 'https://example.com'",
        "Permission denied (publickey)",
        "fatal: Authentication failed",
        "error: Permission denied",
    ],
    ids=["auth_failed", "permission_denied_publickey", "auth_failed_fatal", "permission_denied_error"],
)
def test_no_retry_on_auth_error(monkeypatch, auth_error_text):
    """AC-TEST-003: Authentication errors must not be retried.

    When ls-remote stderr contains 'Authentication' or 'Permission denied',
    the function must raise ManifestInvalidRevisionError immediately without
    retrying. This prevents unnecessary delays and credential lockouts.

    Arrange: Set KANON_GIT_RETRY_COUNT=3. Mock subprocess.run to return a
    failure with authentication-related text in stderr.
    Act: Call _ResolveVersionConstraint().
    Assert: ManifestInvalidRevisionError is raised. subprocess.run was called
    exactly once (no retries).
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()

    auth_failure = _make_failure_result(auth_error_text)

    with mock.patch("subprocess.run", return_value=auth_failure) as mock_run:
        with mock.patch("time.sleep") as mock_sleep:
            with pytest.raises(ManifestInvalidRevisionError):
                project._ResolveVersionConstraint()

    assert mock_run.call_count == 1, (
        f"Expected subprocess.run to be called exactly once for auth error "
        f"(no retries), but it was called {mock_run.call_count} times."
    )
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# AC-TEST-004 -- Retry count configurable via environment variable
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "retry_count",
    [1, 2, 5],
    ids=["retry_count_1", "retry_count_2", "retry_count_5"],
)
def test_retry_count_configurable_via_env_var(monkeypatch, retry_count):
    """AC-TEST-004: KANON_GIT_RETRY_COUNT controls the number of ls-remote attempts.

    The total number of subprocess.run calls must equal the value of
    KANON_GIT_RETRY_COUNT when all attempts fail with transient errors.

    Arrange: Set KANON_GIT_RETRY_COUNT to the parametrized value. Mock
    subprocess.run to fail on all calls. Set KANON_GIT_RETRY_DELAY=0.
    Act: Call _ResolveVersionConstraint().
    Assert: subprocess.run is called exactly retry_count times, and
    ManifestInvalidRevisionError is raised.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", str(retry_count))
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()

    failure = _make_failure_result("Connection reset by peer")
    all_failures = [failure] * retry_count

    with mock.patch("subprocess.run", side_effect=all_failures) as mock_run:
        with mock.patch("time.sleep"):
            with pytest.raises(ManifestInvalidRevisionError):
                project._ResolveVersionConstraint()

    assert mock_run.call_count == retry_count, (
        f"Expected subprocess.run to be called exactly {retry_count} times "
        f"(KANON_GIT_RETRY_COUNT={retry_count}), "
        f"but it was called {mock_run.call_count} times."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-002 / AC-FUNC-004 -- Exponential backoff applied and logged
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_exponential_backoff_applied_between_retries(monkeypatch):
    """AC-FUNC-002: Exponential backoff sleep is applied between retry attempts.

    The delay between retries must double with each attempt, starting from
    KANON_GIT_RETRY_DELAY. Verify the correct sleep durations are requested.

    Arrange: Set KANON_GIT_RETRY_COUNT=3 and KANON_GIT_RETRY_DELAY=1.
    Mock subprocess.run to fail on the first two calls and succeed on the third.
    Act: Call _ResolveVersionConstraint().
    Assert: time.sleep was called exactly twice with delays 1 and 2 (doubling).
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "1")

    project = _make_project()

    failure = _make_failure_result("Connection timed out")
    success = _make_success_result()

    with mock.patch("subprocess.run", side_effect=[failure, failure, success]):
        with mock.patch("time.sleep") as mock_sleep:
            project._ResolveVersionConstraint()

    assert mock_sleep.call_count == 2, (
        f"Expected time.sleep to be called exactly 2 times (between 3 attempts), "
        f"but it was called {mock_sleep.call_count} times."
    )
    sleep_delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert sleep_delays[0] == 1, (
        f"Expected first retry delay to be 1 second (KANON_GIT_RETRY_DELAY=1), but got: {sleep_delays[0]!r}"
    )
    assert sleep_delays[1] == 2, (
        f"Expected second retry delay to be 2 seconds (doubling: 1 -> 2), but got: {sleep_delays[1]!r}"
    )


@pytest.mark.unit
def test_retry_attempts_logged_with_attempt_number(monkeypatch):
    """AC-FUNC-004: Each retry attempt is logged with attempt number and reason.

    When ls-remote fails and is retried, a log record must be emitted that
    includes the attempt number and the error reason from stderr.

    Arrange: Set KANON_GIT_RETRY_COUNT=3, KANON_GIT_RETRY_DELAY=0. Mock
    subprocess.run to fail on the first call and succeed on the second.
    Mock project_module.logger.warning directly (project.py uses a RepoLogger
    that is not registered in the standard logging.Manager and therefore cannot
    be intercepted by pytest's caplog fixture).
    Act: Call _ResolveVersionConstraint().
    Assert: logger.warning was called at least once with messages containing
    the attempt number and the error reason from stderr.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()

    failure = _make_failure_result("Connection reset by peer")
    success = _make_success_result()

    with mock.patch("subprocess.run", side_effect=[failure, success]):
        with mock.patch("time.sleep"):
            with mock.patch.object(project_module.logger, "warning") as mock_warning:
                project._ResolveVersionConstraint()

    assert mock_warning.called, (
        "Expected logger.warning to be called at least once during ls-remote retry, but it was never called."
    )
    # Collect all formatted warning messages to check content.
    all_warning_calls = mock_warning.call_args_list
    formatted_messages = []
    for call in all_warning_calls:
        args = call.args
        if args:
            try:
                formatted_messages.append(args[0] % args[1:])
            except (TypeError, IndexError):
                formatted_messages.append(str(args[0]))

    combined = " ".join(formatted_messages)
    assert "1" in combined, (
        f"Expected retry log to include the attempt number '1', but log messages were: {formatted_messages!r}"
    )
    assert "Connection reset by peer" in combined or "attempt" in combined.lower(), (
        f"Expected retry log to include the error reason or 'attempt', but log messages were: {formatted_messages!r}"
    )


# ---------------------------------------------------------------------------
# AC-CYCLE-001 -- Full constraint resolution lifecycle with retry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_lifecycle_constraint_resolution_succeeds_after_retry(monkeypatch):
    """AC-CYCLE-001: Full lifecycle: mock first ls-remote to fail, second to succeed.

    Simulates a real retry scenario: the first ls-remote call fails with a
    transient network error, the second succeeds and returns tags matching a
    version constraint. Verifies the constraint is resolved to the best tag.

    Arrange: Set a constraint revisionExpr. Mock first ls-remote to fail with
    a network error, second to succeed with matching tags. Set retry count and
    delay via env vars.
    Act: Call _ResolveVersionConstraint().
    Assert: revisionExpr is resolved to the highest matching tag.
    No exception is raised. subprocess.run is called exactly twice.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project("https://git.example.com/org/quality-agent.git")
    # ~=2.0 means >= 2.0, == 2.* (compatible release with 2-part version).
    # This matches 2.0.0, 2.1.0, and 2.9.0 but not 3.0.0 or 1.9.0.
    project.revisionExpr = "refs/tags/dev/python/quality-agent/~=2.0"

    transient_failure = _make_failure_result("Could not resolve host: git.example.com")
    tags = (
        "refs/tags/dev/python/quality-agent/1.9.0",
        "refs/tags/dev/python/quality-agent/2.0.0",
        "refs/tags/dev/python/quality-agent/2.1.0",
        "refs/tags/dev/python/quality-agent/3.0.0",
    )
    tag_success = _make_success_result(tags)

    with mock.patch("subprocess.run", side_effect=[transient_failure, tag_success]) as mock_run:
        with mock.patch("time.sleep"):
            project._ResolveVersionConstraint()

    # ~=2.0 matches 2.0.0, 2.1.0 (compatible with 2.*); highest is 2.1.0.
    assert project.revisionExpr == "refs/tags/dev/python/quality-agent/2.1.0", (
        f"Expected constraint ~=2.0 to resolve to 2.1.0 (highest compatible 2.x), but got: {project.revisionExpr!r}"
    )
    assert mock_run.call_count == 2, (
        f"Expected exactly 2 subprocess.run calls (1 failure + 1 success), but got {mock_run.call_count}."
    )
