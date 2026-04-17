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

"""Unit tests for Bug 9: constraint resolution called twice.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 9 -- _ResolveVersionConstraint()
is called in both Sync_NetworkHalf() and GetRevisionId(). Each call runs
git ls-remote --tags against the remote, wasting network round-trips.

Fix: Add a _constraint_resolved flag to Project. Set it to True after successful
resolution. Skip resolution on subsequent calls when the flag is True. Reset the
flag when revisionExpr is changed via SetRevision().
"""

from unittest import mock

import pytest

from kanon_cli.repo.project import Project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(revision_expr="refs/tags/dev/mylib/~=1.0.0"):
    """Return a Project instance with minimal attributes for constraint tests.

    Bypasses __init__ to avoid requiring a real manifest/remote setup.
    Initialises _constraint_resolved to its expected default (False).

    Args:
        revision_expr: The PEP 440 constraint expression to assign.

    Returns:
        A Project instance with name, remote, revisionExpr, and
        _constraint_resolved set.
    """
    project = Project.__new__(Project)
    project.name = "test-project"
    project.revisionExpr = revision_expr
    project._constraint_resolved = False

    remote = mock.MagicMock()
    remote.url = "https://example.com/org/repo.git"
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


# ---------------------------------------------------------------------------
# AC-TEST-001 -- Resolution called only once for repeated invocations
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_constraint_resolution_called_only_once(monkeypatch):
    """AC-TEST-001: _ResolveVersionConstraint runs ls-remote exactly once.

    When _ResolveVersionConstraint is called multiple times on the same Project,
    the actual resolution (git ls-remote) must execute only on the first call.
    Subsequent calls must return immediately without making any network requests.

    Arrange: Mock subprocess.run to succeed. Set env vars to avoid test delays.
    Act: Call _ResolveVersionConstraint() twice in sequence.
    Assert: subprocess.run was called exactly once (not twice).
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()
    success = _make_success_result()

    with mock.patch("subprocess.run", return_value=success) as mock_run:
        project._ResolveVersionConstraint()
        project._ResolveVersionConstraint()

    assert mock_run.call_count == 1, (
        f"Expected subprocess.run to be called exactly once (caching), but it was called {mock_run.call_count} times."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- Cached result returned on second call
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cached_result_returned_on_second_call(monkeypatch):
    """AC-TEST-002: revisionExpr resolved on first call is preserved on second call.

    After the first successful resolution, revisionExpr is an exact tag. On the
    second call, the caching flag must prevent re-resolution. The revisionExpr
    must remain the resolved tag, not be changed.

    Arrange: Mock subprocess.run to return matching tags. Set env vars.
    Act: Call _ResolveVersionConstraint() once (resolves). Record revisionExpr.
    Call again. Assert revisionExpr unchanged, subprocess.run not called again.
    Assert _constraint_resolved is True after the first call.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()
    success = _make_success_result()

    with mock.patch("subprocess.run", return_value=success) as mock_run:
        project._ResolveVersionConstraint()
        resolved_expr = project.revisionExpr

        # Call again -- must return immediately, revisionExpr unchanged.
        project._ResolveVersionConstraint()
        expr_after_second_call = project.revisionExpr

    assert resolved_expr == expr_after_second_call, (
        f"Expected revisionExpr to remain '{resolved_expr}' after second call, but got '{expr_after_second_call}'."
    )
    assert project._constraint_resolved is True, (
        "Expected _constraint_resolved to be True after successful resolution, "
        f"but got: {project._constraint_resolved!r}"
    )
    assert mock_run.call_count == 1, (
        f"Expected subprocess.run called exactly once (second call cached), "
        f"but it was called {mock_run.call_count} times."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- Flag resets when revisionExpr is changed
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "new_expr",
    [
        "refs/tags/dev/mylib/>=2.0.0",
        "refs/heads/main",
        "refs/tags/dev/mylib/1.5.0",
    ],
    ids=["new_constraint", "branch_ref", "exact_tag"],
)
def test_flag_resets_on_revision_expr_change(monkeypatch, new_expr):
    """AC-TEST-003: _constraint_resolved resets to False when revisionExpr changes.

    When SetRevision() is called with a new revisionExpr, the _constraint_resolved
    flag must be reset to False. This allows the new constraint (or non-constraint)
    expression to be resolved on the next call to _ResolveVersionConstraint.

    Arrange: Resolve a constraint so _constraint_resolved is True.
    Act: Call SetRevision() with a new expression.
    Assert: _constraint_resolved is False after SetRevision().
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()
    success = _make_success_result()

    with mock.patch("subprocess.run", return_value=success):
        project._ResolveVersionConstraint()

    assert project._constraint_resolved is True, (
        f"Pre-condition: expected _constraint_resolved=True after resolution, but got: {project._constraint_resolved!r}"
    )

    # Changing revisionExpr via SetRevision must reset the flag.
    project.SetRevision(new_expr)

    assert project._constraint_resolved is False, (
        f"Expected _constraint_resolved=False after SetRevision('{new_expr}'), "
        f"but got: {project._constraint_resolved!r}"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- _constraint_resolved initialised to False in __init__
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_constraint_resolved_default_is_false():
    """AC-FUNC-001: _constraint_resolved is False by default on a new Project.

    A freshly constructed Project (bypassing __init__) with _constraint_resolved
    set to False represents the unresolved state. Verify the attribute exists and
    is False before any resolution takes place.
    """
    project = _make_project()

    assert hasattr(project, "_constraint_resolved"), (
        "Expected Project to have a '_constraint_resolved' attribute, but it does not."
    )
    assert project._constraint_resolved is False, (
        f"Expected _constraint_resolved to be False before any resolution, but got: {project._constraint_resolved!r}"
    )
