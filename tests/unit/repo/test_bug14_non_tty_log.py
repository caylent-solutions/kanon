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

"""Unit tests for Bug 14: Non-TTY log.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 14 -- When stdin is not a TTY
(e.g., running in CI), log an informational message
'skipping interactive prompts: stdin is not a TTY' so users understand
why prompts are not shown.
"""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds import init


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_init_cmd():
    """Return an Init command instance with the minimum attributes mocked."""
    cmd = init.Init()
    cmd.manifest = mock.MagicMock()
    cmd.manifest.repoProject.worktree = "/nonexistent/.repo/repo"
    cmd.manifest.manifestProject.Exists = False
    cmd.manifest.IsMirror = False
    cmd.manifest.topdir = "/fake/topdir"
    cmd.git_event_log = mock.MagicMock()
    return cmd


def _make_opt():
    """Return a mock options object for Init.Execute."""
    opt = mock.MagicMock()
    opt.manifest_url = "https://example.com/manifest.git"
    opt.repo_url = None
    opt.repo_rev = None
    opt.repo_verify = True
    opt.quiet = False
    opt.worktree = False
    opt.config_name = False
    return opt


# ---------------------------------------------------------------------------
# AC-TEST-007 -- Informational message logged when stdin is not a TTY
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_info_logged_when_stdin_not_a_tty():
    """AC-TEST-007: Informational message logged when stdin is not a TTY.

    When Init.Execute runs in a non-TTY context (e.g., CI environment where
    stdin is a pipe), an informational message must be logged explaining why
    interactive prompts were skipped. This prevents user confusion in CI
    environments where no prompt output is visible.

    Arrange: Mock os.isatty to return False for both stdin (fd 0) and
    stdout (fd 1), simulating a non-TTY environment.
    Act: Call Init.Execute and capture logger.info calls.
    Assert: At least one info message was logged containing the text
    'skipping interactive prompts' and 'not a TTY' (case insensitive).
    """
    cmd = _make_init_cmd()
    opt = _make_opt()

    with (
        mock.patch("kanon_cli.repo.subcmds.init.Wrapper") as MockWrapper,
        mock.patch("kanon_cli.repo.subcmds.init.git_require", return_value=True),
        mock.patch("kanon_cli.repo.subcmds.init.WrapperDir", return_value="/fake/dir"),
        mock.patch.object(cmd, "_SyncManifest"),
        mock.patch.object(cmd, "_DisplayResult"),
        mock.patch("os.isatty", return_value=False),
        mock.patch("os.path.isdir", return_value=False),
        mock.patch.object(init.logger, "info") as mock_info,
    ):
        MockWrapper.return_value.Requirements.from_dir.return_value = mock.MagicMock(
            get_hard_ver=mock.MagicMock(return_value=(2, 10, 0)),
            get_soft_ver=mock.MagicMock(return_value=(2, 10, 0)),
        )

        cmd.Execute(opt, [])

    # Gather all info messages.
    all_calls = mock_info.call_args_list
    formatted_messages = []
    for call in all_calls:
        args = call.args
        if args:
            try:
                formatted_messages.append(args[0] % args[1:])
            except (TypeError, IndexError):
                formatted_messages.append(str(args[0]))

    combined = " ".join(formatted_messages).lower()

    assert "skipping interactive prompts" in combined, (
        f"Expected info log to contain 'skipping interactive prompts', but log messages were: {formatted_messages!r}"
    )
    assert "not a tty" in combined, (
        f"Expected info log to contain 'not a TTY', but log messages were: {formatted_messages!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-008 -- No skip message logged when stdin is a TTY
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_skip_message_when_stdin_is_a_tty():
    """AC-TEST-008: No skip message logged when stdin is a TTY.

    When Init.Execute runs in a TTY context, the informational message about
    skipping interactive prompts must NOT be logged. This avoids confusing
    users who are running interactively.

    Arrange: Mock os.isatty to return True for both stdin (fd 0) and
    stdout (fd 1), simulating a TTY environment.
    Act: Call Init.Execute and capture logger.info calls.
    Assert: No info message was logged containing the text
    'skipping interactive prompts'.
    """
    cmd = _make_init_cmd()
    opt = _make_opt()

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

    # Gather all info messages.
    all_calls = mock_info.call_args_list
    formatted_messages = []
    for call in all_calls:
        args = call.args
        if args:
            try:
                formatted_messages.append(args[0] % args[1:])
            except (TypeError, IndexError):
                formatted_messages.append(str(args[0]))

    skip_messages = [m for m in formatted_messages if "skipping interactive prompts" in m.lower()]
    assert len(skip_messages) == 0, (
        f"Expected no 'skipping interactive prompts' message when stdin is a TTY, but found: {skip_messages!r}"
    )
