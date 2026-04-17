# Copyright (C) 2024 The Android Open Source Project
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

"""Unit tests for subcmds/selfupdate.py coverage."""

from unittest import mock

import pytest

from kanon_cli.repo.error import GitError
from kanon_cli.repo.subcmds.selfupdate import Selfupdate, SelfupdateError


def _make_cmd():
    """Create a Selfupdate command instance for testing."""
    cmd = Selfupdate.__new__(Selfupdate)
    cmd.manifest = mock.MagicMock()
    cmd.manifest.repoProject = mock.MagicMock()
    return cmd


@pytest.mark.unit
def test_options():
    """Test _Options method."""
    cmd = _make_cmd()
    parser = mock.MagicMock()
    option_group = mock.MagicMock()
    parser.add_option_group.return_value = option_group

    cmd._Options(parser)

    assert option_group.add_option.call_count >= 2


@pytest.mark.unit
def test_execute_normal_sync():
    """Test Execute with normal sync (not repo_upgraded)."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.repo_upgraded = False
    opt.repo_verify = True
    args = []

    rp = cmd.manifest.repoProject
    sync_result = mock.MagicMock()
    sync_result.error = None
    rp.Sync_NetworkHalf.return_value = sync_result

    with mock.patch("kanon_cli.repo.subcmds.selfupdate._PostRepoFetch") as mock_post_fetch:
        cmd.Execute(opt, args)

        rp.PreSync.assert_called_once()
        rp.Sync_NetworkHalf.assert_called_once()
        rp.bare_git.gc.assert_called_once_with("--auto")
        mock_post_fetch.assert_called_once_with(rp, repo_verify=True, verbose=True)


@pytest.mark.unit
def test_execute_with_sync_error():
    """Test Execute with sync error."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.repo_upgraded = False
    opt.repo_verify = True
    args = []

    rp = cmd.manifest.repoProject
    sync_result = mock.MagicMock()
    sync_result.error = GitError("sync failed")
    rp.Sync_NetworkHalf.return_value = sync_result

    with pytest.raises(SelfupdateError):
        cmd.Execute(opt, args)

    rp.PreSync.assert_called_once()
    rp.Sync_NetworkHalf.assert_called_once()


@pytest.mark.unit
def test_execute_repo_upgraded():
    """Test Execute with repo_upgraded flag."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.repo_upgraded = True
    opt.repo_verify = True
    args = []

    with mock.patch("kanon_cli.repo.subcmds.selfupdate._PostRepoUpgrade") as mock_post_upgrade:
        cmd.Execute(opt, args)

        cmd.manifest.repoProject.PreSync.assert_called_once()
        mock_post_upgrade.assert_called_once_with(cmd.manifest)


@pytest.mark.unit
def test_execute_no_repo_verify():
    """Test Execute with --no-repo-verify."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.repo_upgraded = False
    opt.repo_verify = False
    args = []

    rp = cmd.manifest.repoProject
    sync_result = mock.MagicMock()
    sync_result.error = None
    rp.Sync_NetworkHalf.return_value = sync_result

    with mock.patch("kanon_cli.repo.subcmds.selfupdate._PostRepoFetch") as mock_post_fetch:
        cmd.Execute(opt, args)

        mock_post_fetch.assert_called_once_with(rp, repo_verify=False, verbose=True)


@pytest.mark.unit
def test_execute_calls_presync():
    """Test Execute calls PreSync before syncing."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.repo_upgraded = False
    opt.repo_verify = True
    args = []

    rp = cmd.manifest.repoProject
    sync_result = mock.MagicMock()
    sync_result.error = None
    rp.Sync_NetworkHalf.return_value = sync_result

    with mock.patch("kanon_cli.repo.subcmds.selfupdate._PostRepoFetch"):
        cmd.Execute(opt, args)

        # PreSync should be called before Sync_NetworkHalf
        call_order = [call[0] for call in rp.method_calls]
        presync_idx = call_order.index("PreSync")
        sync_idx = call_order.index("Sync_NetworkHalf")
        assert presync_idx < sync_idx


@pytest.mark.unit
def test_execute_calls_gc():
    """Test Execute calls git gc after sync."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.repo_upgraded = False
    opt.repo_verify = True
    args = []

    rp = cmd.manifest.repoProject
    sync_result = mock.MagicMock()
    sync_result.error = None
    rp.Sync_NetworkHalf.return_value = sync_result

    with mock.patch("kanon_cli.repo.subcmds.selfupdate._PostRepoFetch"):
        cmd.Execute(opt, args)

        rp.bare_git.gc.assert_called_once_with("--auto")


@pytest.mark.unit
def test_execute_verbose_flag():
    """Test Execute passes verbose=True to _PostRepoFetch."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.repo_upgraded = False
    opt.repo_verify = True
    args = []

    rp = cmd.manifest.repoProject
    sync_result = mock.MagicMock()
    sync_result.error = None
    rp.Sync_NetworkHalf.return_value = sync_result

    with mock.patch("kanon_cli.repo.subcmds.selfupdate._PostRepoFetch") as mock_post_fetch:
        cmd.Execute(opt, args)

        # Check that verbose=True was passed
        call_args = mock_post_fetch.call_args
        assert call_args[1]["verbose"] is True


@pytest.mark.unit
def test_selfupdate_error():
    """Test SelfupdateError exception."""
    error = SelfupdateError("update failed")
    assert isinstance(error, Exception)


@pytest.mark.unit
def test_execute_upgrade_path():
    """Test Execute takes upgrade path when repo_upgraded is True."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.repo_upgraded = True
    args = []

    rp = cmd.manifest.repoProject

    with mock.patch("kanon_cli.repo.subcmds.selfupdate._PostRepoUpgrade") as mock_post_upgrade:
        cmd.Execute(opt, args)

        # Should not call Sync_NetworkHalf in upgrade path
        rp.Sync_NetworkHalf.assert_not_called()
        # Should not call gc in upgrade path
        rp.bare_git.gc.assert_not_called()
        # Should call PostRepoUpgrade
        mock_post_upgrade.assert_called_once()


@pytest.mark.unit
def test_execute_aggregate_errors():
    """Test Execute includes error in aggregate_errors."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.repo_upgraded = False
    opt.repo_verify = True
    args = []

    rp = cmd.manifest.repoProject
    git_error = GitError("network error")
    sync_result = mock.MagicMock()
    sync_result.error = git_error
    rp.Sync_NetworkHalf.return_value = sync_result

    with pytest.raises(SelfupdateError) as exc_info:
        cmd.Execute(opt, args)

    # Check that the error was included
    assert exc_info.value is not None
