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

"""Regression guard for E0-F6-S2-T1: empty envsubst file list silent.

Bug reference: E0-F6-S2-T1 / Bug 5 -- when envsubst is invoked and
glob.glob() returns an empty list (no files match the pattern), the command
completed silently with no indication that nothing was processed.

Root cause: subcmds/envsubst.py Execute() -- after glob.glob(), there was no
check for an empty result. The for-loop simply did nothing, leaving the user
with no feedback.

Fix (landed in E0-F6-S2-T1): After glob.glob(), if the result list is empty,
log a WARNING that includes the glob pattern. Return normally since an empty
match is not a failure condition.

This regression guard asserts that:
1. A WARNING log record containing the glob pattern is emitted when glob
   returns an empty list (AC-TEST-001).
2. The exact bug condition from E0-F6-S2-T1 is reproduced: Execute() is
   called with an empty glob result and must not raise or silently pass
   (AC-TEST-002).
3. The test passes against the current fixed code (AC-TEST-003).
4. The structural empty-list guard is present in the source (AC-FUNC-001).
5. The warning goes to the logging channel, not stdout (AC-CHANNEL-001).
"""

import inspect
import logging
from unittest import mock

import pytest

from kanon_cli.repo.subcmds import envsubst as envsubst_module
from kanon_cli.repo.subcmds.envsubst import Envsubst


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cmd() -> Envsubst:
    """Return an Envsubst instance without invoking the parent __init__ chain.

    Bypasses the Command superclass initialiser to avoid requiring a real
    manifest directory, git client, or remote configuration. The manifest
    attribute is set to a MagicMock so any attribute access on it is safe.

    Returns:
        An Envsubst instance whose Execute() can be called directly.
    """
    cmd = Envsubst.__new__(Envsubst)
    cmd.manifest = mock.MagicMock()
    return cmd


# ---------------------------------------------------------------------------
# AC-TEST-001 -- regression: warning logged when glob returns empty list
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_warning_logged_when_glob_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    """AC-TEST-001: Execute() must log a WARNING when glob.glob() returns [].

    This test reproduces the exact bug condition from E0-F6-S2-T1: Execute()
    is called but glob.glob() finds no files. Before the fix, Execute()
    completed silently. After the fix a WARNING including the glob pattern
    is emitted.

    If this test fails with no WARNING record, the empty-list guard in
    envsubst.py Execute() has been removed and Bug 5 has regressed.

    Arrange: Patch glob.glob to return an empty list.
    Act: Call Execute().
    Assert: At least one WARNING log record contains the glob pattern.
    """
    cmd = _make_cmd()

    with mock.patch("glob.glob", return_value=[]):
        with mock.patch("builtins.print"):
            with caplog.at_level(logging.WARNING):
                cmd.Execute(mock.MagicMock(), [])

    pattern = cmd.path
    matching = [r for r in caplog.records if r.levelno == logging.WARNING and pattern in r.message]
    assert matching, (
        f"E0-F6-S2-T1 regression: expected at least one WARNING log record "
        f"containing the glob pattern {pattern!r} when glob.glob() returns an "
        f"empty list, but none was found.\n"
        f"Captured log records: {[(r.levelno, r.message) for r in caplog.records]!r}\n"
        "The empty-list WARNING guard in envsubst.py Execute() has been removed "
        "or broken. Restore the '_LOG.warning(\"No files matched glob pattern: "
        "%s\", self.path)' call immediately after glob.glob() returns an empty list."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- exact bug condition from E0-F6-S2-T1
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_exact_bug_condition_no_exception_on_empty_glob() -> None:
    """AC-TEST-002: Execute() must not raise when glob.glob() returns [].

    This test reproduces the exact bug condition from E0-F6-S2-T1: the user
    runs the envsubst subcommand but no XML files are found under the expected
    glob pattern. Before the fix the command silently did nothing. The fix adds
    a WARNING and an early return so the caller receives a clean result.

    The test confirms the command does not raise any exception, which would be
    a regression to a different failure mode (crash instead of silent).

    If this test raises, an exception was introduced in Execute() on the empty
    path that did not exist before. If the test passes without a WARNING being
    logged, pair with AC-TEST-001 to detect the silent-pass regression.

    Arrange: Patch glob.glob to return [].
    Act: Call Execute().
    Assert: No exception propagates.
    """
    cmd = _make_cmd()

    with mock.patch("glob.glob", return_value=[]):
        with mock.patch("builtins.print"):
            try:
                cmd.Execute(mock.MagicMock(), [])
            except Exception as exc:
                pytest.fail(
                    f"E0-F6-S2-T1 regression: Execute() raised {type(exc).__name__} "
                    f"when glob.glob() returns an empty list. An empty match must "
                    f"return normally (it is not an error condition). "
                    f"Exception: {exc}"
                )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- passes against the current fixed code
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "glob_return,description",
    [
        ([], "empty list -- no files found"),
        ([""], "list with one empty string path -- degenerate match"),
    ],
)
def test_regression_fixed_code_handles_empty_and_degenerate_glob(
    caplog: pytest.LogCaptureFixture,
    glob_return: list,
    description: str,
) -> None:
    """AC-TEST-003: Current fixed code handles empty and degenerate glob results.

    Verifies the fix from E0-F6-S2-T1 is in place and handles the primary
    regression scenario (empty list) as well as the adjacent degenerate case
    (list containing an empty string path that has zero file size).

    For the empty-list case the WARNING guard must fire. For the degenerate
    case, the file size check (os.path.getsize > 0) skips the empty path and
    the function returns normally without crashing.

    If the empty-list parametrized case fails without a WARNING, Bug 5 has
    regressed. If the degenerate case raises, a secondary regression is present.

    Arrange: Patch glob.glob and os.path.getsize as needed.
    Act: Call Execute().
    Assert: No exception; WARNING logged for the empty-list case.
    """
    cmd = _make_cmd()

    with mock.patch("glob.glob", return_value=glob_return):
        with mock.patch("os.path.getsize", return_value=0):
            with mock.patch("builtins.print"):
                with caplog.at_level(logging.WARNING):
                    try:
                        cmd.Execute(mock.MagicMock(), [])
                    except Exception as exc:
                        pytest.fail(
                            f"E0-F6-S2-T1 regression ({description}): Execute() raised "
                            f"{type(exc).__name__}: {exc}. "
                            "The fixed code must not raise for any empty or degenerate glob result."
                        )

    if not glob_return:
        pattern = cmd.path
        matching = [r for r in caplog.records if r.levelno == logging.WARNING and pattern in r.message]
        assert matching, (
            f"E0-F6-S2-T1 regression ({description}): no WARNING log record "
            f"containing {pattern!r} was found for an empty glob result. "
            "The Bug 5 fix (empty-list guard) is no longer active."
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- structural guard: empty-list check present in source
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_empty_list_guard_present_in_execute_source() -> None:
    """AC-FUNC-001: The empty-list guard is present in Envsubst.Execute() source.

    Inspects the source of Envsubst.Execute() to confirm:
    - The result of glob.glob() is checked for emptiness.
    - A warning is emitted when no files match.

    If either check fails, the guard has been structurally removed and the
    E0-F6-S2-T1 bug would regress silently for any envsubst invocation where
    no manifest XML files are found.
    """
    source = inspect.getsource(Envsubst.Execute)

    assert "not files" in source or "if not files" in source, (
        "E0-F6-S2-T1 regression guard: the empty-list check ('if not files' or "
        "'not files') is no longer present in Envsubst.Execute(). "
        "The guard that triggers a WARNING when glob.glob() returns an empty list "
        "has been removed from src/kanon_cli/repo/subcmds/envsubst.py. "
        "Restore the check and the '_LOG.warning(...)' call."
    )

    assert "_LOG.warning" in source, (
        "E0-F6-S2-T1 regression guard: '_LOG.warning' is no longer called in "
        "Envsubst.Execute(). The empty-list WARNING that informs the user when "
        "no manifest XML files match the glob pattern has been removed from "
        "src/kanon_cli/repo/subcmds/envsubst.py. "
        "Restore the '_LOG.warning(\"No files matched glob pattern: %s\", self.path)' "
        "call in the empty-list branch."
    )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001 -- stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_empty_glob_warning_goes_to_logging_not_stdout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-CHANNEL-001: The empty-glob warning goes to the logging channel, not stdout.

    stdout is reserved for machine-consumable output. Diagnostic messages such
    as the empty-file-list warning must go through the logging subsystem
    (which routes to stderr in production), not via print() to stdout.

    This test verifies:
    1. The WARNING appears in the captured log records (logging channel used).
    2. The WARNING message does not appear in any print() calls to stdout.

    Arrange: Patch glob.glob to return []. Capture print() calls and log records.
    Act: Call Execute().
    Assert: WARNING in log records; warning text not printed to stdout.
    """
    cmd = _make_cmd()
    printed_lines: list[str] = []

    def _capture_print(*args, **kwargs) -> None:
        printed_lines.extend(str(a) for a in args)

    with mock.patch("glob.glob", return_value=[]):
        with mock.patch("builtins.print", side_effect=_capture_print):
            with caplog.at_level(logging.WARNING, logger=envsubst_module._LOG.name):
                cmd.Execute(mock.MagicMock(), [])

    pattern = cmd.path

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING and pattern in r.message]
    assert warning_records, (
        f"E0-F6-S2-T1 regression (channel discipline): expected a WARNING log record "
        f"containing {pattern!r} from the logging channel, but none was captured. "
        f"Captured log records: {[(r.levelno, r.message) for r in caplog.records]!r}"
    )

    stdout_with_pattern = [line for line in printed_lines if pattern in line]
    assert not stdout_with_pattern, (
        f"E0-F6-S2-T1 regression (channel discipline): the empty-glob warning for "
        f"pattern {pattern!r} was written to stdout via print() instead of the "
        f"logging channel. stdout lines containing the pattern: {stdout_with_pattern!r}. "
        "Diagnostic warnings must use _LOG.warning(), not print()."
    )
