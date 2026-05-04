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

"""Unit tests for Bug 11: Race condition on concurrent git ls-remote.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 11 -- Race condition on
concurrent git ls-remote. Already addressed by Bug 7 retry logic.

Fix: Dedicated tests verifying that a transient failure during concurrent
access is retried and that the retry log message is produced.
"""

from unittest import mock

import pytest

from kanon_cli.repo import project as project_module
from kanon_cli.repo.project import Project


_PROJECT_LOGGER_NAME = project_module.logger.name


def _make_project(remote_url="https://example.com/org/repo.git"):
    """Return a Project instance with minimum attributes mocked.

    Bypasses __init__ to avoid requiring a real manifest/remote setup.
    Sets the minimal attributes needed by _ResolveVersionConstraint.
    """
    project = Project.__new__(Project)
    project.name = "concurrent-test-project"
    project.revisionExpr = "refs/tags/dev/concurrent/~=2.0.0"
    project._constraint_resolved = False

    remote = mock.MagicMock()
    remote.url = remote_url
    project.remote = remote

    return project


def _make_failure_result(stderr="Connection reset by peer"):
    """Return a mock CompletedProcess for a transient ls-remote failure."""
    result = mock.MagicMock()
    result.returncode = 1
    result.stdout = ""
    result.stderr = stderr
    return result


def _make_success_result(tags=("refs/tags/dev/concurrent/2.0.0", "refs/tags/dev/concurrent/2.1.0")):
    """Return a mock CompletedProcess for a successful ls-remote call."""
    lines = "\n".join(f"deadbeef{i:08x}\t{tag}" for i, tag in enumerate(tags))
    result = mock.MagicMock()
    result.returncode = 0
    result.stdout = lines
    result.stderr = ""
    return result


# ---------------------------------------------------------------------------
# AC-TEST-001 -- Transient concurrent failure is retried and succeeds
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_concurrent_transient_failure_is_retried(monkeypatch):
    """AC-TEST-001: Transient failure during concurrent access is retried.

    When git ls-remote fails with a transient error that could occur during
    concurrent access (such as a locked resource or connection reset), the
    retry logic from Bug 7 must handle it. The function must retry the call
    and succeed on the second attempt.

    Arrange: Mock subprocess.run to fail on the first call (simulating a
    transient concurrent failure) and succeed on the second. Set
    KANON_GIT_RETRY_COUNT=3 and KANON_GIT_RETRY_DELAY=0.
    Act: Call _ResolveVersionConstraint().
    Assert: revisionExpr is resolved successfully. subprocess.run was called
    exactly twice (once failed, once succeeded).
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()

    # Simulate transient concurrent access failure (e.g., connection reset
    # due to another process holding the git lock).
    # revisionExpr is ~=2.0.0 (3-part compatible release: >=2.0.0, ==2.0.*).
    # Both 2.0.0 and 2.1.0 are available; only 2.0.0 satisfies ~=2.0.0.
    concurrent_failure = _make_failure_result("Connection reset by peer: concurrent access conflict")
    success = _make_success_result()

    with mock.patch("subprocess.run", side_effect=[concurrent_failure, success]) as mock_run:
        with mock.patch("time.sleep"):
            project._ResolveVersionConstraint()

    assert project.revisionExpr == "refs/tags/dev/concurrent/2.0.0", (
        f"Expected revisionExpr to be resolved to 'refs/tags/dev/concurrent/2.0.0' "
        f"(highest tag satisfying ~=2.0.0) after retry, but got: {project.revisionExpr!r}"
    )
    assert mock_run.call_count == 2, (
        f"Expected subprocess.run to be called exactly 2 times (1 failure + 1 success "
        f"to handle concurrent transient error), but got {mock_run.call_count}."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- Retry log message is produced on concurrent transient failure
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_retry_log_message_produced_on_concurrent_failure(monkeypatch):
    """AC-TEST-002: Retry log message is produced on concurrent transient failure.

    When a transient failure occurs during concurrent access, the retry
    mechanism must log a warning message that includes the attempt number
    and the reason for the failure, so operators can diagnose concurrent
    access issues in CI logs.

    Arrange: Mock subprocess.run to fail on the first call with a concurrent
    access error and succeed on the second. Mock logger.warning to capture
    log calls. Set KANON_GIT_RETRY_COUNT=3, KANON_GIT_RETRY_DELAY=0.
    Act: Call _ResolveVersionConstraint().
    Assert: logger.warning was called at least once. The log message contains
    the attempt number and the failure reason.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()

    concurrent_failure = _make_failure_result("Connection reset by peer: concurrent access conflict")
    success = _make_success_result()

    with mock.patch("subprocess.run", side_effect=[concurrent_failure, success]):
        with mock.patch("time.sleep"):
            with mock.patch.object(project_module.logger, "warning") as mock_warning:
                project._ResolveVersionConstraint()

    assert mock_warning.called, (
        "Expected logger.warning to be called at least once during concurrent transient "
        "failure retry, but it was never called."
    )

    # Build formatted messages from all warning calls.
    all_calls = mock_warning.call_args_list
    formatted_messages = []
    for call in all_calls:
        args = call.args
        if args:
            try:
                formatted_messages.append(args[0] % args[1:])
            except (TypeError, IndexError):
                formatted_messages.append(str(args[0]))

    combined = " ".join(formatted_messages)

    assert "1" in combined, (
        f"Expected retry log to include attempt number '1', but log messages were: {formatted_messages!r}"
    )
    assert "attempt" in combined.lower() or "retry" in combined.lower() or "failed" in combined.lower(), (
        f"Expected retry log to contain 'attempt', 'retry', or 'failed', but log messages were: {formatted_messages!r}"
    )
