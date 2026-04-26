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

"""Regression guard for E0-F6-S3-T1: Bugs 11-15 medium severity fixes.

Bug reference: E0-F6-S3-T1 -- Five medium-severity bugs fixed:
- Bug 11: Race condition on concurrent git ls-remote -- transient failure
  during concurrent access must be retried with logged retry messages.
- Bug 12: Backup file preserved on envsubst rerun -- before the fix, a
  stale .bak was removed before creating a new one, causing the original
  pre-substitution baseline to be overwritten. The fix uses skip-if-exists
  semantics: an existing .bak is left untouched.
- Bug 13: Init reinit warning -- when `repo init` is run in a directory
  already initialized and the manifest URL changes, a warning including
  both old and new URLs must be logged.
- Bug 14: Non-TTY log -- when stdin is not a TTY (e.g., in CI), an
  informational message "skipping interactive prompts: stdin is not a TTY"
  must be logged.
- Bug 15: Pre-release version constraint docs -- version_constraints module
  must document pre-release exclusion behavior and reference PEP 440 or
  semantic versioning.

This regression guard asserts that:
1. Bug 12 skip-if-exists contract: existing .bak is not overwritten.
2. Bug 12 first-run contract: .bak is created when absent.
3. Bug 13 warning is emitted when reinit URL changes.
4. Bug 13 no warning when reinit URL matches.
5. Bug 14 non-TTY message is logged when stdin is not a TTY.
6. Bug 14 no skip message when stdin is a TTY.
7. Bug 15 pre-release note present in version_constraints documentation.
8. Bug 15 PEP 440 or semantic versioning referenced in documentation.
9. Bug 11 transient concurrent failure is retried and succeeds.
10. Bug 11 retry log message is produced on concurrent transient failure.
"""

import inspect
from unittest import mock

import pytest

from kanon_cli.repo import project as project_module
from kanon_cli.repo import version_constraints
from kanon_cli.repo.project import Project
from kanon_cli.repo.subcmds import init
from kanon_cli.repo.subcmds.envsubst import Envsubst


# ---------------------------------------------------------------------------
# Helpers -- Bug 11 (concurrent retry)
# ---------------------------------------------------------------------------


def _make_project(remote_url="https://example.com/org/repo.git"):
    """Return a Project instance with minimum attributes mocked.

    Bypasses __init__ to avoid requiring a real manifest or remote setup.
    Sets the minimal attributes needed by _ResolveVersionConstraint.

    Args:
        remote_url: The URL to use for the project's remote.

    Returns:
        A Project instance ready for _ResolveVersionConstraint() invocation.
    """
    project = Project.__new__(Project)
    project.name = "regression-concurrent-test"
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
# Helpers -- Bug 13 (reinit warning) and Bug 14 (non-TTY log)
# ---------------------------------------------------------------------------


def _make_init_cmd(existing_checkout=True, current_url="https://old.example.com/manifest.git"):
    """Return an Init command instance with the minimum attributes mocked.

    Args:
        existing_checkout: Whether a repo is already initialized.
        current_url: The URL currently configured in the existing checkout.

    Returns:
        Configured Init instance with mocked manifest and git_event_log.
    """
    cmd = init.Init()
    cmd.manifest = mock.MagicMock()
    cmd.manifest.repoProject.worktree = "/nonexistent/.repo/repo"
    cmd.manifest.manifestProject.Exists = existing_checkout
    cmd.manifest.manifestProject.config.GetString.return_value = current_url
    cmd.manifest.IsMirror = False
    cmd.manifest.topdir = "/fake/topdir"
    cmd.git_event_log = mock.MagicMock()
    return cmd


def _make_opt(manifest_url="https://new.example.com/manifest.git", quiet=False):
    """Return a mock options object for Init.Execute.

    Args:
        manifest_url: The manifest URL requested by the user.
        quiet: Whether quiet mode is enabled.

    Returns:
        Mock options object with all required fields set.
    """
    opt = mock.MagicMock()
    opt.manifest_url = manifest_url
    opt.repo_url = None
    opt.repo_rev = None
    opt.repo_verify = True
    opt.quiet = quiet
    opt.worktree = False
    opt.config_name = False
    return opt


def _run_init_execute(cmd, opt, isatty_return=False):
    """Helper to run Init.Execute with standard mocks applied.

    Patches out Wrapper, git_require, WrapperDir, _SyncManifest,
    _DisplayResult, os.isatty, and os.path.isdir to avoid real I/O.

    Args:
        cmd: The Init command instance to execute.
        opt: The options mock to pass to Execute.
        isatty_return: Return value for os.isatty (True = TTY, False = non-TTY).

    Returns:
        A dict with keys 'warning_calls' and 'info_calls' listing captured log calls.
    """
    with (
        mock.patch("kanon_cli.repo.subcmds.init.Wrapper") as MockWrapper,
        mock.patch("kanon_cli.repo.subcmds.init.git_require", return_value=True),
        mock.patch("kanon_cli.repo.subcmds.init.WrapperDir", return_value="/fake/dir"),
        mock.patch.object(cmd, "_SyncManifest"),
        mock.patch.object(cmd, "_DisplayResult"),
        mock.patch("os.isatty", return_value=isatty_return),
        mock.patch("os.path.isdir", return_value=False),
        mock.patch.object(init.logger, "warning") as mock_warning,
        mock.patch.object(init.logger, "info") as mock_info,
    ):
        MockWrapper.return_value.Requirements.from_dir.return_value = mock.MagicMock(
            get_hard_ver=mock.MagicMock(return_value=(2, 10, 0)),
            get_soft_ver=mock.MagicMock(return_value=(2, 10, 0)),
        )
        cmd.Execute(opt, [])
        return {
            "warning_calls": mock_warning.call_args_list,
            "info_calls": mock_info.call_args_list,
        }


def _format_log_calls(call_args_list):
    """Format a list of mock call_args into a list of message strings."""
    messages = []
    for call in call_args_list:
        args = call.args
        if args:
            try:
                messages.append(args[0] % args[1:])
            except (TypeError, IndexError):
                messages.append(str(args[0]))
    return messages


# ---------------------------------------------------------------------------
# Bug 12 -- skip-if-exists backup contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_bug12_existing_bak_not_overwritten(tmp_path):
    """AC-TEST-001: Bug 12 regression -- existing .bak must not be overwritten.

    Before the E0-F6-S3-T1 fix, EnvSubst removed an existing .bak before
    creating a new one (remove-then-recreate). This caused the original
    pre-substitution baseline to be lost on every re-run.

    The fix introduced skip-if-exists semantics: if a .bak file already exists
    from a prior run or placed by the user, it is left completely untouched.

    If this test fails with the sentinel content gone, Bug 12 has regressed
    (the remove-then-recreate behavior has been reintroduced).

    Arrange: Create a valid XML manifest and a pre-existing .bak with sentinel.
    Act: Call EnvSubst on the manifest.
    Assert: The .bak content is unchanged (sentinel still present).
    """
    xml_file = tmp_path / "manifest.xml"
    bak_path = tmp_path / "manifest.xml.bak"

    xml_file.write_text('<?xml version="1.0"?><manifest><project name="test"/></manifest>')
    sentinel = b"pre-existing bak -- must not be overwritten by E0-F6-S3-T1 regression"
    bak_path.write_bytes(sentinel)

    cmd = Envsubst()
    cmd.EnvSubst(str(xml_file))

    assert bak_path.read_bytes() == sentinel, (
        "E0-F6-S3-T1 Bug 12 regression: EnvSubst overwrote an existing .bak file. "
        "The skip-if-exists contract (_ensure_backup_once) has been broken and the "
        "remove-then-recreate behavior has regressed. "
        f"Expected {sentinel!r}, got {bak_path.read_bytes()!r}"
    )


@pytest.mark.unit
def test_regression_bug12_bak_created_when_absent(tmp_path):
    """AC-TEST-002: Bug 12 regression -- .bak must be created on first run.

    The skip-if-exists fix must still create a .bak when none exists. This
    test confirms the first-run creation path remains intact.

    Arrange: Create a valid XML manifest with no .bak file.
    Act: Call EnvSubst on the manifest.
    Assert: A .bak file exists after the call and is non-empty.
    """
    xml_file = tmp_path / "manifest.xml"
    bak_path = tmp_path / "manifest.xml.bak"

    xml_file.write_text('<?xml version="1.0"?><manifest><project name="test"/></manifest>')

    cmd = Envsubst()
    cmd.EnvSubst(str(xml_file))

    assert bak_path.exists(), (
        f"E0-F6-S3-T1 Bug 12 regression: EnvSubst did not create a .bak on first run. "
        f"Expected .bak at {bak_path} but it does not exist."
    )
    assert bak_path.stat().st_size > 0, (
        f"E0-F6-S3-T1 Bug 12 regression: .bak file created by EnvSubst is empty at {bak_path}."
    )


# ---------------------------------------------------------------------------
# Bug 13 -- reinit URL warning
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_bug13_warning_logged_when_url_changes(tmp_path):
    """AC-TEST-002 / Bug 13 regression: warning when reinit URL changes.

    When `repo init` is called in a directory already initialized and the
    manifest URL differs from the currently configured URL, a warning including
    both old and new URLs must be logged.

    If this test fails with no warning, the URL-change warning in init.py
    Execute() has been removed and Bug 13 has regressed.

    Arrange: Existing checkout with old_url; Execute with new_url.
    Act: Capture logger.warning calls.
    Assert: Warning contains both old and new URLs.
    """
    old_url = "https://old.example.com/manifest.git"
    new_url = "https://new.example.com/manifest.git"

    cmd = _make_init_cmd(existing_checkout=True, current_url=old_url)
    opt = _make_opt(manifest_url=new_url, quiet=True)

    result = _run_init_execute(cmd, opt, isatty_return=False)
    messages = _format_log_calls(result["warning_calls"])
    combined = " ".join(messages)

    assert old_url in combined, (
        f"E0-F6-S3-T1 Bug 13 regression: warning missing old URL '{old_url}'. "
        f"The URL-change warning in init.py Execute() has been removed or broken. "
        f"Warning messages: {messages!r}"
    )
    assert new_url in combined, (
        f"E0-F6-S3-T1 Bug 13 regression: warning missing new URL '{new_url}'. "
        f"The URL-change warning in init.py Execute() has been removed or broken. "
        f"Warning messages: {messages!r}"
    )


@pytest.mark.unit
def test_regression_bug13_no_warning_when_url_unchanged(tmp_path):
    """Bug 13 regression: no URL-change warning when reinit uses same URL.

    When reinitializing with the same manifest URL, no URL-change warning
    must be emitted. This verifies the condition check (current != requested)
    is correct and not a blanket warning on any reinit.

    Arrange: Existing checkout with same_url; Execute with same_url.
    Act: Capture logger.warning calls.
    Assert: No warning message contains both URL and change-indicator keywords.
    """
    same_url = "https://example.com/manifest.git"

    cmd = _make_init_cmd(existing_checkout=True, current_url=same_url)
    opt = _make_opt(manifest_url=same_url, quiet=True)

    result = _run_init_execute(cmd, opt, isatty_return=False)
    messages = _format_log_calls(result["warning_calls"])

    url_change_warnings = [
        m
        for m in messages
        if same_url in m and any(kw in m.lower() for kw in ("change", "differ", "was", "new url", "old url"))
    ]
    assert len(url_change_warnings) == 0, (
        f"E0-F6-S3-T1 Bug 13 regression: unexpected URL-change warning when reinit URL "
        f"is unchanged. The condition guard in init.py Execute() may be broken. "
        f"Unexpected warnings: {url_change_warnings!r}"
    )


# ---------------------------------------------------------------------------
# Bug 14 -- non-TTY informational log
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_bug14_info_logged_when_stdin_not_a_tty():
    """AC-TEST-002 / Bug 14 regression: informational log when stdin is not a TTY.

    When Init.Execute runs in a non-TTY context (e.g., CI where stdin is a
    pipe), an informational message must be logged explaining why interactive
    prompts were skipped.

    If this test fails without the message, the non-TTY log in init.py
    Execute() has been removed and Bug 14 has regressed.

    Arrange: os.isatty returns False (non-TTY context).
    Act: Run Init.Execute and capture logger.info calls.
    Assert: At least one info message contains 'skipping interactive prompts'
    and 'not a tty'.
    """
    cmd = _make_init_cmd(existing_checkout=False)
    opt = _make_opt(quiet=False)

    result = _run_init_execute(cmd, opt, isatty_return=False)
    messages = _format_log_calls(result["info_calls"])
    combined = " ".join(messages).lower()

    assert "skipping interactive prompts" in combined, (
        "E0-F6-S3-T1 Bug 14 regression: info log 'skipping interactive prompts' not found "
        "when stdin is not a TTY. The non-TTY guard in init.py Execute() has been removed. "
        f"Info messages: {messages!r}"
    )
    assert "not a tty" in combined, (
        "E0-F6-S3-T1 Bug 14 regression: info log does not contain 'not a TTY' when stdin "
        "is not a TTY. The message in init.py Execute() has been modified or removed. "
        f"Info messages: {messages!r}"
    )


@pytest.mark.unit
def test_regression_bug14_no_skip_message_when_stdin_is_a_tty():
    """Bug 14 regression: no skip message when stdin is a TTY.

    When running interactively (stdin is a TTY), the 'skipping interactive
    prompts' message must NOT be logged. This confirms the TTY-vs-non-TTY
    distinction is preserved in the condition check.

    Arrange: os.isatty returns True (TTY context).
    Act: Run Init.Execute and capture logger.info calls.
    Assert: No info message contains 'skipping interactive prompts'.
    """
    cmd = _make_init_cmd(existing_checkout=False)
    opt = _make_opt(quiet=True)

    with (
        mock.patch("kanon_cli.repo.subcmds.init.Wrapper") as MockWrapper,
        mock.patch("kanon_cli.repo.subcmds.init.git_require", return_value=True),
        mock.patch("kanon_cli.repo.subcmds.init.WrapperDir", return_value="/fake/dir"),
        mock.patch.object(cmd, "_SyncManifest"),
        mock.patch.object(cmd, "_DisplayResult"),
        mock.patch("os.isatty", return_value=True),
        mock.patch("os.path.isdir", return_value=False),
        mock.patch.object(cmd, "_ShouldConfigureUser", return_value=False),
        mock.patch.object(cmd, "_ConfigureColor"),
        mock.patch.object(init.logger, "info") as mock_info,
    ):
        MockWrapper.return_value.Requirements.from_dir.return_value = mock.MagicMock(
            get_hard_ver=mock.MagicMock(return_value=(2, 10, 0)),
            get_soft_ver=mock.MagicMock(return_value=(2, 10, 0)),
        )
        cmd.Execute(opt, [])

    messages = _format_log_calls(mock_info.call_args_list)
    skip_messages = [m for m in messages if "skipping interactive prompts" in m.lower()]
    assert len(skip_messages) == 0, (
        "E0-F6-S3-T1 Bug 14 regression: 'skipping interactive prompts' info message "
        "was logged when stdin IS a TTY. The isatty() condition in init.py Execute() "
        f"is inverted or missing. Unexpected messages: {skip_messages!r}"
    )


# ---------------------------------------------------------------------------
# Bug 15 -- pre-release version constraint documentation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_bug15_prerelease_note_in_documentation():
    """AC-TEST-002 / Bug 15 regression: pre-release note in version_constraints.

    The version_constraints module must document pre-release exclusion behavior
    in its module-level docstring. Without this, users relying on PEP 440
    constraints would be surprised that pre-release versions (e.g., 1.0.0a1)
    are excluded by default.

    If this test fails, the pre-release documentation added in E0-F6-S3-T1 has
    been removed from version_constraints.py and Bug 15 has regressed.

    Arrange: Import version_constraints.
    Act: Access its __doc__ attribute.
    Assert: Module docstring contains 'pre-release' or 'prerelease'.
    """
    module_doc = version_constraints.__doc__ or ""
    assert "pre-release" in module_doc.lower() or "prerelease" in module_doc.lower(), (
        "E0-F6-S3-T1 Bug 15 regression: 'pre-release' or 'prerelease' not found in "
        "the version_constraints module docstring. The pre-release documentation "
        "added in E0-F6-S3-T1 has been removed from "
        "src/kanon_cli/repo/version_constraints.py. "
        f"Current docstring: {module_doc!r}"
    )


@pytest.mark.unit
def test_regression_bug15_pep440_or_semver_referenced():
    """Bug 15 regression: PEP 440 or semantic versioning referenced in docs.

    The version_constraints documentation must reference PEP 440 or semantic
    versioning so users understand the standard governing constraint evaluation.

    If this test fails, the PEP 440 / semantic versioning reference has been
    removed and Bug 15 has regressed.

    Arrange: Import version_constraints.
    Act: Examine module, resolve_version_constraint, and is_version_constraint docs.
    Assert: At least one doc contains 'pep 440' or 'semantic versioning'.
    """
    module_doc = version_constraints.__doc__ or ""
    resolve_doc = version_constraints.resolve_version_constraint.__doc__ or ""
    is_constraint_doc = version_constraints.is_version_constraint.__doc__ or ""

    combined = (module_doc + resolve_doc + is_constraint_doc).lower()

    has_pep440 = "pep 440" in combined or "pep440" in combined
    has_semver = "semantic versioning" in combined or "semver" in combined

    assert has_pep440 or has_semver, (
        "E0-F6-S3-T1 Bug 15 regression: neither 'PEP 440' nor 'semantic versioning' "
        "found in version_constraints documentation. The standard reference added in "
        "E0-F6-S3-T1 has been removed from "
        "src/kanon_cli/repo/version_constraints.py. "
        f"Module doc: {module_doc!r}"
    )


# ---------------------------------------------------------------------------
# Bug 11 -- concurrent git ls-remote retry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_bug11_concurrent_failure_is_retried(monkeypatch):
    """AC-TEST-002 / Bug 11 regression: transient concurrent failure is retried.

    The retry logic from Bug 7 must handle transient failures that occur during
    concurrent git ls-remote access (e.g., connection reset while another
    process holds a git lock). When a transient failure occurs, _ResolveVersion-
    Constraint must retry and succeed on the next attempt.

    If this test fails with no retry (subprocess.run called only once or
    revisionExpr not resolved), the Bug 7 retry logic that Bug 11 depends on
    has been removed and Bug 11 has regressed.

    Arrange: subprocess.run fails on the first call, succeeds on the second.
    KANON_GIT_RETRY_COUNT=3, KANON_GIT_RETRY_DELAY=0.
    Act: Call _ResolveVersionConstraint().
    Assert: revisionExpr is resolved; subprocess.run called exactly twice.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()
    concurrent_failure = _make_failure_result("Connection reset by peer: concurrent lock conflict")
    success = _make_success_result()

    with mock.patch("subprocess.run", side_effect=[concurrent_failure, success]) as mock_run:
        with mock.patch("time.sleep"):
            project._ResolveVersionConstraint()

    assert project.revisionExpr == "refs/tags/dev/concurrent/2.0.0", (
        "E0-F6-S3-T1 Bug 11 regression: _ResolveVersionConstraint() did not resolve "
        "revisionExpr after retrying a concurrent transient failure. "
        "The retry logic (Bug 7) that Bug 11 depends on has been broken. "
        f"Got: {project.revisionExpr!r}"
    )
    assert mock_run.call_count == 2, (
        "E0-F6-S3-T1 Bug 11 regression: subprocess.run was not called twice "
        f"(expected 1 failure + 1 success), got call count: {mock_run.call_count}. "
        "The concurrent-access retry path in _ResolveVersionConstraint is broken."
    )


@pytest.mark.unit
def test_regression_bug11_retry_log_message_produced(monkeypatch):
    """Bug 11 regression: retry log message produced on concurrent transient failure.

    When a transient concurrent failure occurs, the retry mechanism must log a
    warning including the attempt number and failure reason. This allows
    operators to diagnose concurrent access issues in CI logs.

    If this test fails with no warning logged, the retry log message has been
    removed from the retry path and Bug 11 has regressed.

    Arrange: subprocess.run fails once then succeeds. Capture logger.warning.
    Act: Call _ResolveVersionConstraint().
    Assert: At least one warning was logged containing an attempt indicator.
    """
    monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
    monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

    project = _make_project()
    concurrent_failure = _make_failure_result("Connection reset by peer: concurrent lock conflict")
    success = _make_success_result()

    with mock.patch("subprocess.run", side_effect=[concurrent_failure, success]):
        with mock.patch("time.sleep"):
            with mock.patch.object(project_module.logger, "warning") as mock_warning:
                project._ResolveVersionConstraint()

    assert mock_warning.called, (
        "E0-F6-S3-T1 Bug 11 regression: logger.warning was never called during "
        "concurrent transient failure retry. The retry log message in "
        "_ResolveVersionConstraint has been removed."
    )

    messages = _format_log_calls(mock_warning.call_args_list)
    combined = " ".join(messages)

    assert "1" in combined, (
        f"E0-F6-S3-T1 Bug 11 regression: retry log message does not contain attempt number '1'. Messages: {messages!r}"
    )
    assert any(kw in combined.lower() for kw in ("attempt", "retry", "failed")), (
        "E0-F6-S3-T1 Bug 11 regression: retry log message does not contain 'attempt', "
        f"'retry', or 'failed'. Messages: {messages!r}"
    )


# ---------------------------------------------------------------------------
# Structural guards -- source code inspection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_bug12_skip_if_exists_guard_in_source():
    """Bug 12 structural guard: skip-if-exists logic present in envsubst.py.

    Inspects _ensure_backup_once() source to confirm the bak_path.exists()
    check is present. If this test fails, the skip-if-exists guard has been
    removed and remove-then-recreate behavior has likely regressed.
    """
    from kanon_cli.repo.subcmds import envsubst as envsubst_module

    source = inspect.getsource(envsubst_module._ensure_backup_once)
    assert "exists" in source, (
        "E0-F6-S3-T1 Bug 12 structural regression: the bak_path.exists() check "
        "is no longer present in _ensure_backup_once(). The skip-if-exists guard "
        "that prevents overwriting an existing .bak has been removed from "
        "src/kanon_cli/repo/subcmds/envsubst.py."
    )


@pytest.mark.unit
def test_regression_bug13_url_comparison_in_init_source():
    """Bug 13 structural guard: URL comparison guard present in init.py.

    Inspects Init.Execute() source to confirm the current_url != opt.manifest_url
    comparison is present. If this test fails, the URL-change warning logic has
    been removed and Bug 13 has regressed.
    """
    source = inspect.getsource(init.Init.Execute)
    assert "current_url" in source, (
        "E0-F6-S3-T1 Bug 13 structural regression: 'current_url' variable is no "
        "longer present in Init.Execute(). The URL-change warning added in "
        "E0-F6-S3-T1 has been removed from src/kanon_cli/repo/subcmds/init.py."
    )


@pytest.mark.unit
def test_regression_bug14_isatty_guard_in_init_source():
    """Bug 14 structural guard: isatty check and non-TTY log present in init.py.

    Inspects Init.Execute() source to confirm os.isatty() is checked and
    the 'skipping interactive prompts' message is present. If this test fails,
    the non-TTY log has been removed and Bug 14 has regressed.
    """
    source = inspect.getsource(init.Init.Execute)
    assert "isatty" in source, (
        "E0-F6-S3-T1 Bug 14 structural regression: 'isatty' is no longer present "
        "in Init.Execute(). The TTY check added in E0-F6-S3-T1 has been removed "
        "from src/kanon_cli/repo/subcmds/init.py."
    )
    assert "skipping interactive prompts" in source, (
        "E0-F6-S3-T1 Bug 14 structural regression: 'skipping interactive prompts' "
        "message is no longer present in Init.Execute(). The non-TTY informational "
        "log added in E0-F6-S3-T1 has been removed from "
        "src/kanon_cli/repo/subcmds/init.py."
    )
