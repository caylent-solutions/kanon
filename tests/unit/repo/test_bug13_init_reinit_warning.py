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

"""Unit tests for Bug 13: Init reinit warning.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 13 -- When `repo init` is run
in a directory that already has a repo initialized, read the current remote
URL, compare it to the requested URL. If they differ, log a warning including
both the old and new URLs.
"""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds import init


# ---------------------------------------------------------------------------
# Helpers
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


# ---------------------------------------------------------------------------
# AC-TEST-005 -- Warning logged when URL changes on reinit
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_warning_logged_when_url_changes_on_reinit():
    """AC-TEST-005: Warning is logged when reinitializing with a different URL.

    When `repo init` is called in a directory that already has a repo
    initialized, and the requested manifest URL differs from the currently
    configured URL, a warning must be logged. The warning must include both
    the old URL and the new URL so operators can diagnose unintended URL
    changes.

    Arrange: Create an Init command with an existing checkout using
    current_url. Call Execute with a different manifest_url (new_url).
    Act: Capture logger calls.
    Assert: A warning was logged containing both the old and new URLs.
    """
    old_url = "https://old.example.com/manifest.git"
    new_url = "https://new.example.com/manifest.git"

    cmd = _make_init_cmd(existing_checkout=True, current_url=old_url)
    opt = _make_opt(manifest_url=new_url, quiet=True)

    with (
        mock.patch("kanon_cli.repo.subcmds.init.Wrapper") as MockWrapper,
        mock.patch("kanon_cli.repo.subcmds.init.git_require", return_value=True),
        mock.patch("kanon_cli.repo.subcmds.init.WrapperDir", return_value="/fake/dir"),
        mock.patch.object(cmd, "_SyncManifest"),
        mock.patch.object(cmd, "_DisplayResult"),
        mock.patch("os.isatty", return_value=False),
        mock.patch("os.path.isdir", return_value=False),
        mock.patch.object(init.logger, "warning") as mock_warning,
    ):
        MockWrapper.return_value.Requirements.from_dir.return_value = mock.MagicMock(
            get_hard_ver=mock.MagicMock(return_value=(2, 10, 0)),
            get_soft_ver=mock.MagicMock(return_value=(2, 10, 0)),
        )

        cmd.Execute(opt, [])

    # Gather all warning messages.
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

    assert old_url in combined, (
        f"Expected warning to include old URL '{old_url}', but log messages were: {formatted_messages!r}"
    )
    assert new_url in combined, (
        f"Expected warning to include new URL '{new_url}', but log messages were: {formatted_messages!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-006 -- No warning when URL matches on reinit
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_warning_when_url_matches_on_reinit():
    """AC-TEST-006: No warning is logged when reinitializing with the same URL.

    When `repo init` is called in a directory that already has a repo
    initialized and the requested manifest URL matches the currently
    configured URL, no URL-change warning must be logged. This prevents
    false alarms in normal reinit flows.

    Arrange: Create an Init command with an existing checkout using
    same_url. Call Execute with the same manifest_url.
    Act: Capture logger.warning calls.
    Assert: No warning message was logged containing both URL mentions that
    would indicate a URL-change warning.
    """
    same_url = "https://example.com/manifest.git"

    cmd = _make_init_cmd(existing_checkout=True, current_url=same_url)
    opt = _make_opt(manifest_url=same_url, quiet=True)

    with (
        mock.patch("kanon_cli.repo.subcmds.init.Wrapper") as MockWrapper,
        mock.patch("kanon_cli.repo.subcmds.init.git_require", return_value=True),
        mock.patch("kanon_cli.repo.subcmds.init.WrapperDir", return_value="/fake/dir"),
        mock.patch.object(cmd, "_SyncManifest"),
        mock.patch.object(cmd, "_DisplayResult"),
        mock.patch("os.isatty", return_value=False),
        mock.patch("os.path.isdir", return_value=False),
        mock.patch.object(init.logger, "warning") as mock_warning,
    ):
        MockWrapper.return_value.Requirements.from_dir.return_value = mock.MagicMock(
            get_hard_ver=mock.MagicMock(return_value=(2, 10, 0)),
            get_soft_ver=mock.MagicMock(return_value=(2, 10, 0)),
        )

        cmd.Execute(opt, [])

    # Build all formatted warning messages.
    all_calls = mock_warning.call_args_list
    url_change_warnings = []
    for call in all_calls:
        args = call.args
        if args:
            try:
                msg = args[0] % args[1:]
            except (TypeError, IndexError):
                msg = str(args[0])
            # A URL-change warning would contain both mentions of the URL
            # and signal a change (e.g., "changing" or "differs" or "was").
            if same_url in msg and any(kw in msg.lower() for kw in ("change", "differ", "was", "new url", "old url")):
                url_change_warnings.append(msg)

    assert len(url_change_warnings) == 0, (
        f"Expected no URL-change warning when reinitializing with the same URL, "
        f"but found warnings: {url_change_warnings!r}"
    )
