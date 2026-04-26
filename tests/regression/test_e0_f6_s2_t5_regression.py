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

"""Regression guard for E0-F6-S2-T5: constraint resolution called twice.

Bug reference: E0-F6-S2-T5 / Bug 9 -- when a Project has a PEP 440 version
constraint in revisionExpr, the constraint resolution logic (which calls
git ls-remote to match available remote tags) is invoked from two separate call
sites in the sync lifecycle:

  1. Project.Sync_NetworkHalf() calls self._ResolveVersionConstraint() at the
     beginning of the network fetch phase to normalise the revisionExpr into an
     exact tag ref before any git operations.
  2. Project.GetRevisionId() calls self._ResolveVersionConstraint() again
     before resolving the local ref, because revisionExpr must be a concrete
     ref by the time rev-parse is invoked.

Before the fix, each call site independently ran git ls-remote --tags against
the remote URL and repeated the full PEP 440 matching logic, resulting in
unnecessary network round-trips -- one per call site per project per sync cycle.

Fix (landed in E0-F6-S2-T5): Added a _constraint_resolved boolean flag to
Project.__init__() (default False). _ResolveVersionConstraint() returns
immediately when the flag is True. After a successful resolution the flag is
set to True. SetRevision() resets the flag to False so that a changed
revisionExpr is resolved again on the next call.

This regression guard asserts that:
1. When _ResolveVersionConstraint() is called from two separate call sites on
   the same Project instance, git ls-remote is executed exactly once
   (AC-TEST-001).
2. The exact bug condition from E0-F6-S2-T5 is triggered: direct sequential
   calls to _ResolveVersionConstraint() do not make redundant ls-remote network
   calls (AC-TEST-002).
3. The test passes against the current fixed code for multiple constraint
   expressions (AC-TEST-003).
4. The structural guard (the _constraint_resolved flag) is present and
   functional in the source (AC-FUNC-001).
5. Constraint resolution does not produce output on stdout -- it either resolves
   silently or raises an exception that propagates via the exception channel
   (AC-CHANNEL-001).
"""

import inspect
from unittest import mock

import pytest

from kanon_cli.repo.project import Project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(
    remote_url: str = "https://git.example.com/org/library.git",
    constraint: str = "refs/tags/dev/library/~=1.0.0",
) -> Project:
    """Return a Project instance with minimal attributes for constraint tests.

    Bypasses __init__ to avoid requiring a real manifest, git client, or remote
    configuration. Sets only the attributes accessed by _ResolveVersionConstraint:
    - revisionExpr: a PEP 440 constraint expression
    - name: project name (used in error messages)
    - remote.url: the URL passed to git ls-remote
    - _constraint_resolved: caching flag (False -- resolution not yet done)

    Args:
        remote_url: The URL to assign to project.remote.url.
        constraint: The PEP 440 version constraint to assign to revisionExpr.

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


def _make_success_result(
    constraint_prefix: str = "refs/tags/dev/library/",
    matching_tag: str = "refs/tags/dev/library/1.0.1",
    extra_tags: tuple = ("refs/tags/dev/library/0.9.0",),
) -> mock.MagicMock:
    """Return a mock CompletedProcess representing a successful git ls-remote call.

    Produces ls-remote output with at least one tag that satisfies the ~=1.0.0
    constraint (i.e., >=1.0.0, <2.0.0).

    Args:
        constraint_prefix: Tag prefix used to construct the output lines.
        matching_tag: Tag that satisfies the version constraint.
        extra_tags: Additional tags to include in the output.

    Returns:
        Mock with returncode=0 and stdout containing hash-tab-ref lines.
    """
    all_tags = (matching_tag,) + extra_tags
    lines = "\n".join(f"deadbeef{i:08x}\t{tag}" for i, tag in enumerate(all_tags))
    result = mock.MagicMock()
    result.returncode = 0
    result.stdout = lines
    result.stderr = ""
    return result


# ---------------------------------------------------------------------------
# AC-TEST-001 -- resolution is called only once when invoked from two call sites
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_ls_remote_called_once_across_two_call_sites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-001: git ls-remote executes exactly once across two _ResolveVersionConstraint calls.

    This test guards against Bug 9 regressing. The bug was that both
    Sync_NetworkHalf() and GetRevisionId() independently called
    _ResolveVersionConstraint(), which in turn called git ls-remote --tags for
    each invocation. For a manifest with many constrained projects, this doubled
    the network traffic during a sync cycle.

    The fix adds a _constraint_resolved flag that short-circuits subsequent
    calls to _ResolveVersionConstraint() after the first successful resolution.

    If this test fails (subprocess.run call count exceeds 1), the caching flag
    has been removed or is not being checked, and Bug 9 has regressed.

    Arrange: Set KANON_GIT_RETRY_COUNT=1. Mock subprocess.run to succeed.
    Act: Call _ResolveVersionConstraint() twice (simulating Sync_NetworkHalf
         then GetRevisionId).
    Assert: subprocess.run was called exactly once.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()
    success = _make_success_result()

    with mock.patch("subprocess.run", return_value=success) as mock_run:
        # First call -- simulates Sync_NetworkHalf() invoking resolution.
        project._ResolveVersionConstraint()
        # Second call -- simulates GetRevisionId() invoking resolution.
        project._ResolveVersionConstraint()

    assert mock_run.call_count == 1, (
        "E0-F6-S2-T5 regression (Bug 9): git ls-remote (subprocess.run) was called "
        f"{mock_run.call_count} time(s) across two sequential _ResolveVersionConstraint "
        "invocations, but must be called exactly once. "
        "The _constraint_resolved caching flag in Project prevents redundant ls-remote "
        "round-trips. If the flag is missing or not checked, Bug 9 has regressed and "
        "every constrained project will make an extra network call per sync cycle."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- exact bug condition: sequential calls from separate call sites
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "constraint,matching_tag,description",
    [
        (
            "refs/tags/dev/service-a/~=1.0.0",
            "refs/tags/dev/service-a/1.0.5",
            "compatible-release constraint resolved once",
        ),
        (
            "refs/tags/dev/service-b/>=2.0.0",
            "refs/tags/dev/service-b/2.3.1",
            "greater-than-or-equal constraint resolved once",
        ),
        (
            "refs/tags/dev/service-c/==3.1.0",
            "refs/tags/dev/service-c/3.1.0",
            "exact-version constraint resolved once",
        ),
    ],
    ids=[
        "compatible_release",
        "gte_constraint",
        "exact_version",
    ],
)
def test_regression_exact_bug_condition_double_resolution(
    monkeypatch: pytest.MonkeyPatch,
    constraint: str,
    matching_tag: str,
    description: str,
) -> None:
    """AC-TEST-002: Exact Bug 9 condition -- double resolution does not fire for any constraint type.

    This parametrized test reproduces the exact E0-F6-S2-T5 bug scenario across
    multiple PEP 440 constraint operators (compatible release ~=, greater-than-or-
    equal >=, and exact match ==). Before the fix each operator triggered the same
    double-call bug because the guard was absent for all constraint types.

    After the fix the _constraint_resolved flag is set to True after the first
    successful resolution regardless of the operator used. The second call returns
    without invoking subprocess.run.

    If any parametrized case fails, the caching guard does not apply uniformly
    and at least one constraint operator still triggers double resolution.

    Arrange: Set KANON_GIT_RETRY_COUNT=1. Mock subprocess.run to succeed.
    Act: Call _ResolveVersionConstraint() twice for each constraint variant.
    Assert: subprocess.run called exactly once; _constraint_resolved is True.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project(constraint=constraint)
    success = _make_success_result(matching_tag=matching_tag)

    with mock.patch("subprocess.run", return_value=success) as mock_run:
        project._ResolveVersionConstraint()
        project._ResolveVersionConstraint()

    assert mock_run.call_count == 1, (
        f"E0-F6-S2-T5 regression (Bug 9 -- {description}): subprocess.run was called "
        f"{mock_run.call_count} time(s) for constraint {constraint!r}. "
        "Expected exactly 1 call -- the second _ResolveVersionConstraint() invocation "
        "must return immediately via the _constraint_resolved flag."
    )
    assert project._constraint_resolved is True, (
        f"E0-F6-S2-T5 regression (Bug 9 -- {description}): _constraint_resolved is "
        f"{project._constraint_resolved!r} after successful resolution of {constraint!r}. "
        "Expected True -- the flag must be set after the first successful resolution."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- current fixed code prevents double resolution across call sites
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "remote_url,constraint,matching_tag,description",
    [
        (
            "https://git.example.com/org/lib-alpha.git",
            "refs/tags/dev/lib-alpha/~=1.0.0",
            "refs/tags/dev/lib-alpha/1.0.3",
            "first project -- compatible release, ls-remote once",
        ),
        (
            "https://git.internal.example.org/platform/lib-beta.git",
            "refs/tags/dev/lib-beta/>=2.5.0",
            "refs/tags/dev/lib-beta/2.6.0",
            "second project -- gte constraint, ls-remote once",
        ),
        (
            "https://mirrors.example.net/git/lib-gamma.git",
            "refs/tags/dev/lib-gamma/~=4.1.0",
            "refs/tags/dev/lib-gamma/4.1.2",
            "third project -- different host, ls-remote once",
        ),
    ],
    ids=[
        "lib_alpha_once",
        "lib_beta_once",
        "lib_gamma_once",
    ],
)
def test_regression_fixed_code_single_resolution_per_project(
    monkeypatch: pytest.MonkeyPatch,
    remote_url: str,
    constraint: str,
    matching_tag: str,
    description: str,
) -> None:
    """AC-TEST-003: Current fixed code resolves each project's constraint exactly once.

    Verifies the E0-F6-S2-T5 fix across multiple projects and remote URLs.
    For each project, calling _ResolveVersionConstraint() twice must result in
    exactly one git ls-remote call and the _constraint_resolved flag must be True
    after resolution.

    This is the positive-path confirmation that the fix is in place across
    different project configurations. If any parametrized case fails, the fix
    has been partially reverted or a refactor removed the caching guard for
    specific configurations.

    Arrange: Set KANON_GIT_RETRY_COUNT=1. Mock subprocess.run to succeed.
    Act: Call _ResolveVersionConstraint() twice per project.
    Assert: subprocess.run called once; _constraint_resolved is True after first call.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project(remote_url=remote_url, constraint=constraint)
    success = _make_success_result(matching_tag=matching_tag)

    call_count_after_first: list[int] = []

    original_subprocess_run = mock.MagicMock(return_value=success)

    def _tracking_run(*args: object, **kwargs: object) -> mock.MagicMock:
        return original_subprocess_run(*args, **kwargs)

    with mock.patch("subprocess.run", side_effect=_tracking_run) as mock_run:
        project._ResolveVersionConstraint()
        call_count_after_first.append(mock_run.call_count)
        project._ResolveVersionConstraint()

    assert call_count_after_first[0] == 1, (
        f"E0-F6-S2-T5 regression ({description}): subprocess.run was called "
        f"{call_count_after_first[0]} time(s) after the first _ResolveVersionConstraint() "
        f"call for constraint {constraint!r}. Expected exactly 1 call on first resolution."
    )
    assert mock_run.call_count == 1, (
        f"E0-F6-S2-T5 regression ({description}): subprocess.run was called "
        f"{mock_run.call_count} time(s) total across two _ResolveVersionConstraint() "
        f"calls for constraint {constraint!r}. "
        "The _constraint_resolved caching flag must prevent the second call."
    )
    assert project._constraint_resolved is True, (
        f"E0-F6-S2-T5 regression ({description}): _constraint_resolved is "
        f"{project._constraint_resolved!r} after resolving {constraint!r}. "
        "Expected True -- the flag must be set to True after successful resolution."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- structural guard: _constraint_resolved flag present in source
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_constraint_resolved_flag_present_in_source() -> None:
    """AC-FUNC-001: The _constraint_resolved flag is present and used in _ResolveVersionConstraint.

    Inspects the source of Project.__init__ and _ResolveVersionConstraint() to
    confirm:
    - _constraint_resolved is initialised in __init__ (default False).
    - _ResolveVersionConstraint() checks the flag before running ls-remote.
    - _ResolveVersionConstraint() sets the flag to True after successful resolution.

    If any of these structural checks fail, the caching mechanism has been removed
    during a refactor and Bug 9 would silently recur -- every constrained project
    would make redundant ls-remote calls on every sync cycle.

    This guard prevents the fix from disappearing during future refactors without
    a test failure making the regression explicit.
    """
    resolve_source = inspect.getsource(Project._ResolveVersionConstraint)

    assert "_constraint_resolved" in resolve_source, (
        "E0-F6-S2-T5 regression guard (AC-FUNC-001): '_constraint_resolved' is no "
        "longer referenced in _ResolveVersionConstraint(). "
        "This boolean flag is the caching mechanism added by the Bug 9 fix. "
        "Without it, every call to _ResolveVersionConstraint() runs git ls-remote, "
        "causing double network round-trips when both Sync_NetworkHalf() and "
        "GetRevisionId() invoke the method on the same Project. Restore the flag check."
    )

    # The guard check must appear as a conditional return -- verify the source
    # contains the early-return pattern.
    assert "if self._constraint_resolved" in resolve_source or (
        "_constraint_resolved" in resolve_source and "return" in resolve_source
    ), (
        "E0-F6-S2-T5 regression guard (AC-FUNC-001): _ResolveVersionConstraint() "
        "references '_constraint_resolved' but does not appear to use it as an early "
        "return guard. The pattern 'if self._constraint_resolved: return' or equivalent "
        "must be present so that already-resolved projects skip the ls-remote call."
    )

    init_source = inspect.getsource(Project.__init__)

    assert "_constraint_resolved" in init_source, (
        "E0-F6-S2-T5 regression guard (AC-FUNC-001): '_constraint_resolved' is no "
        "longer initialised in Project.__init__(). "
        "The flag must default to False so that new Project instances are always in "
        "the unresolved state. Without the initialisation, the attribute lookup in "
        "_ResolveVersionConstraint() raises AttributeError on the first call."
    )

    set_revision_source = inspect.getsource(Project.SetRevision)

    assert "_constraint_resolved" in set_revision_source, (
        "E0-F6-S2-T5 regression guard (AC-FUNC-001): '_constraint_resolved' is no "
        "longer reset in SetRevision(). "
        "When revisionExpr is changed via SetRevision(), the flag must be reset to "
        "False so that the new expression is resolved on the next call to "
        "_ResolveVersionConstraint(). Without the reset, changing revisionExpr after "
        "resolution leaves the flag True and the new constraint is never resolved."
    )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001 -- resolution produces no stdout output on success
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_successful_resolution_produces_no_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-CHANNEL-001: Successful constraint resolution does not write to stdout.

    stdout is reserved for machine-consumable output in the kanon sync pipeline.
    Diagnostic messages (logging) and error messages (exceptions) must not be
    mixed into stdout. When _ResolveVersionConstraint() succeeds, it must
    resolve silently -- no print() calls, no progress output on stdout.

    This test verifies that two sequential calls to _ResolveVersionConstraint()
    (the Bug 9 scenario) produce no stdout output.

    Arrange: Set KANON_GIT_RETRY_COUNT=1. Mock subprocess.run to succeed.
    Intercept all print() calls during resolution.
    Act: Call _ResolveVersionConstraint() twice.
    Assert: No lines written to stdout via print().
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()
    success = _make_success_result()

    printed_lines: list[str] = []

    def _capture_print(*args: object, **kwargs: object) -> None:
        file_arg = kwargs.get("file")
        import sys

        if file_arg is None or file_arg is sys.stdout:
            printed_lines.extend(str(a) for a in args)

    with mock.patch("subprocess.run", return_value=success):
        with mock.patch("builtins.print", side_effect=_capture_print):
            project._ResolveVersionConstraint()
            project._ResolveVersionConstraint()

    assert not printed_lines, (
        "E0-F6-S2-T5 regression (AC-CHANNEL-001): _ResolveVersionConstraint() "
        "wrote diagnostic content to stdout via print() during successful resolution. "
        f"Captured stdout lines: {printed_lines!r}. "
        "Successful resolution must be silent -- no output on stdout. "
        "Diagnostic messages must go through the logging channel (logger.*) "
        "and error conditions must propagate as exceptions."
    )
