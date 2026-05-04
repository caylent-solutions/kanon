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

"""Unit tests for Bug 5: empty envsubst file list silently ignored.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 5 -- when glob.glob() returns
an empty list (no files match the pattern), Execute() completes silently with
no indication that nothing was processed.

Root cause: subcmds/envsubst.py Execute() -- after glob.glob(), there is no
check for an empty result; the for-loop simply does nothing with no log output.

Fix: After glob.glob(), if the result list is empty, log a WARNING that
includes the glob pattern. Return normally (empty match is not an error).
"""

import logging
from unittest import mock

import pytest

from kanon_cli.repo.subcmds.envsubst import Envsubst


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cmd():
    """Return an Envsubst instance without invoking __init__ parent chain."""
    cmd = Envsubst.__new__(Envsubst)
    cmd.manifest = mock.MagicMock()
    return cmd


# ---------------------------------------------------------------------------
# AC-TEST-001 -- Warning is logged when glob returns empty list
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_warning_logged_when_glob_returns_empty(caplog):
    """AC-TEST-001: Execute() must log a WARNING when glob.glob() returns [].

    When no XML files match the glob pattern, Execute() must emit a warning
    that includes the glob pattern so the user can diagnose misconfigured
    manifest paths.

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
        f"Expected a WARNING log record containing the glob pattern {pattern!r}, "
        f"but none found.\nLog records: {[(r.levelno, r.message) for r in caplog.records]!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- Command returns success (no exception) on empty match
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_command_returns_success_on_empty_glob():
    """AC-TEST-002: Execute() must return normally (not raise) when glob returns [].

    An empty file list is not an error condition. Execute() must complete
    without raising any exception so the caller receives a successful return.

    Arrange: Patch glob.glob to return an empty list.
    Act: Call Execute() and assert no exception propagates.
    Assert: Execute() returns without raising.
    """
    cmd = _make_cmd()

    with mock.patch("glob.glob", return_value=[]):
        with mock.patch("builtins.print"):
            # Must not raise -- empty match is not a failure.
            cmd.Execute(mock.MagicMock(), [])
