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

"""Unit tests for Bug 8: ls-remote errors missing stderr.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 8 -- when git ls-remote fails
and raises ManifestInvalidRevisionError, the error message does not include
the stderr output from the git subprocess, the remote URL, or the constraint
that was being resolved.

Fix: Capture result.stderr from the subprocess call and include the URL,
constraint, and stderr text in the ManifestInvalidRevisionError message.
"""

from unittest import mock

import pytest

from kanon_cli.repo.error import ManifestInvalidRevisionError
from kanon_cli.repo.project import Project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(remote_url="https://example.com/org/repo.git", constraint="refs/tags/dev/mylib/~=1.0.0"):
    """Return a Project instance with the bare minimum attributes mocked.

    Bypasses __init__ to avoid requiring a real manifest/remote setup.
    Sets the minimal attributes needed by _ResolveVersionConstraint:
    - revisionExpr: a PEP 440 constraint string
    - name: project name for error messages
    - remote.url: the remote URL for ls-remote
    """
    project = Project.__new__(Project)
    project.name = "test-project"
    project.revisionExpr = constraint

    remote = mock.MagicMock()
    remote.url = remote_url
    project.remote = remote

    return project


def _make_failure_result(stderr="fatal: repository not found"):
    """Return a mock CompletedProcess representing a failed ls-remote call.

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
# AC-TEST-001 -- ManifestInvalidRevisionError includes stderr content
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_message_includes_stderr(monkeypatch):
    """AC-TEST-001: ManifestInvalidRevisionError raised by _ResolveVersionConstraint
    includes the stderr output captured from the git ls-remote subprocess.

    When git ls-remote fails, the stderr from the subprocess must be present in
    the error message so operators can diagnose what went wrong.

    Arrange: Set KANON_GIT_RETRY_COUNT=1 to skip retry loop. Mock subprocess.run
    to fail with a distinctive stderr string.
    Act: Call _ResolveVersionConstraint() and expect ManifestInvalidRevisionError.
    Assert: The raised error message contains the stderr string.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    stderr_text = "fatal: repository 'https://example.com/org/repo.git' not found"
    project = _make_project()

    failure = _make_failure_result(stderr_text)

    with mock.patch("subprocess.run", return_value=failure):
        with mock.patch("time.sleep"):
            with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                project._ResolveVersionConstraint()

    error_message = str(exc_info.value)
    assert stderr_text in error_message, (
        f"Expected ManifestInvalidRevisionError message to contain stderr text "
        f"'{stderr_text}', but got: {error_message!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- ManifestInvalidRevisionError includes remote URL
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_message_includes_url(monkeypatch):
    """AC-TEST-002: ManifestInvalidRevisionError raised by _ResolveVersionConstraint
    includes the remote URL that was queried with git ls-remote.

    When git ls-remote fails, the error message must include the remote URL so
    operators know which repository was unreachable.

    Arrange: Set KANON_GIT_RETRY_COUNT=1 to skip retry loop. Use a distinctive
    remote URL. Mock subprocess.run to fail.
    Act: Call _ResolveVersionConstraint() and expect ManifestInvalidRevisionError.
    Assert: The raised error message contains the remote URL.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    remote_url = "https://git.example.org/special/myproject.git"
    project = _make_project(remote_url=remote_url)

    failure = _make_failure_result("Connection refused")

    with mock.patch("subprocess.run", return_value=failure):
        with mock.patch("time.sleep"):
            with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                project._ResolveVersionConstraint()

    error_message = str(exc_info.value)
    assert remote_url in error_message, (
        f"Expected ManifestInvalidRevisionError message to contain remote URL "
        f"'{remote_url}', but got: {error_message!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- ManifestInvalidRevisionError includes constraint expression
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_message_includes_constraint(monkeypatch):
    """AC-TEST-003: ManifestInvalidRevisionError raised by _ResolveVersionConstraint
    includes the constraint/revision expression that was being resolved.

    When git ls-remote fails, the error message must include the constraint
    so operators know which constraint could not be resolved.

    Arrange: Set KANON_GIT_RETRY_COUNT=1 to skip retry loop. Use a distinctive
    constraint expression. Mock subprocess.run to fail.
    Act: Call _ResolveVersionConstraint() and expect ManifestInvalidRevisionError.
    Assert: The raised error message contains the constraint expression.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    constraint = "refs/tags/dev/myspeciallib/~=3.2.1"
    project = _make_project(constraint=constraint)

    failure = _make_failure_result("fatal: repository not found")

    with mock.patch("subprocess.run", return_value=failure):
        with mock.patch("time.sleep"):
            with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                project._ResolveVersionConstraint()

    error_message = str(exc_info.value)
    assert constraint in error_message, (
        f"Expected ManifestInvalidRevisionError message to contain constraint "
        f"'{constraint}', but got: {error_message!r}"
    )
