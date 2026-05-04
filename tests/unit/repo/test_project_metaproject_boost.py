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

"""Additional unit tests for project.py to increase code coverage.

This test file focuses on:
- SyncBuffer class methods
- MetaProject property methods
- MetaProject.Sync() method branches
- _ApplyCloneBundle and related methods
- PrintWorkTreeStatus / HasChanges
- _getLogs and getAddedAndRemovedLogs
"""

import os
from unittest import mock

import pytest

from kanon_cli.repo.error import GitError
from kanon_cli.repo.project import MetaProject
from kanon_cli.repo.project import SyncBuffer
from kanon_cli.repo.project import _DirtyError
from kanon_cli.repo.project import _Failure
from kanon_cli.repo.project import _InfoMessage
from kanon_cli.repo.project import _Later
from kanon_cli.repo.project import _PriorSyncFailedError
from kanon_cli.repo.project import _SyncColoring


@pytest.mark.unit
class TestSyncBuffer:
    """Test SyncBuffer class methods."""

    @pytest.mark.unit
    def test_syncbuffer_init_default(self):
        """Test SyncBuffer initialization with defaults."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)

        assert buf.detach_head is False
        assert buf.clean is True
        assert buf.recent_clean is True
        assert buf._messages == []
        assert buf._failures == []
        assert buf._later_queue1 == []
        assert buf._later_queue2 == []
        assert isinstance(buf.out, _SyncColoring)

    @pytest.mark.unit
    def test_syncbuffer_init_detach_head(self):
        """Test SyncBuffer initialization with detach_head=True."""
        config = mock.MagicMock()
        buf = SyncBuffer(config, detach_head=True)

        assert buf.detach_head is True
        assert buf.clean is True
        assert buf.recent_clean is True

    @pytest.mark.unit
    def test_syncbuffer_info(self):
        """Test SyncBuffer.info() method."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)
        project = mock.MagicMock()
        project.RelPath.return_value = "test/project"

        buf.info(project, "test message %s", "arg1")

        assert len(buf._messages) == 1
        assert isinstance(buf._messages[0], _InfoMessage)
        assert buf._messages[0].project == project
        assert buf._messages[0].text == "test message arg1"

    @pytest.mark.unit
    def test_syncbuffer_fail(self):
        """Test SyncBuffer.fail() method."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)
        project = mock.MagicMock()
        err = Exception("test error")

        buf.fail(project, err)

        assert len(buf._failures) == 1
        assert isinstance(buf._failures[0], _Failure)
        assert buf._failures[0].project == project
        assert buf._failures[0].why == err
        assert buf.clean is False
        assert buf.recent_clean is False

    @pytest.mark.unit
    def test_syncbuffer_later1(self):
        """Test SyncBuffer.later1() method."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)
        project = mock.MagicMock()
        action = mock.MagicMock()

        buf.later1(project, action, quiet=True)

        assert len(buf._later_queue1) == 1
        assert isinstance(buf._later_queue1[0], _Later)
        assert buf._later_queue1[0].project == project
        assert buf._later_queue1[0].action == action
        assert buf._later_queue1[0].quiet is True

    @pytest.mark.unit
    def test_syncbuffer_later2(self):
        """Test SyncBuffer.later2() method."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)
        project = mock.MagicMock()
        action = mock.MagicMock()

        buf.later2(project, action, quiet=False)

        assert len(buf._later_queue2) == 1
        assert isinstance(buf._later_queue2[0], _Later)
        assert buf._later_queue2[0].project == project
        assert buf._later_queue2[0].action == action
        assert buf._later_queue2[0].quiet is False

    @pytest.mark.unit
    def test_syncbuffer_recently_true(self):
        """Test SyncBuffer.Recently() when recent_clean is True."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)

        assert buf.recent_clean is True
        result = buf.Recently()

        assert result is True
        assert buf.recent_clean is True

    @pytest.mark.unit
    def test_syncbuffer_recently_false(self):
        """Test SyncBuffer.Recently() when recent_clean is False."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)
        buf.recent_clean = False

        result = buf.Recently()

        assert result is False
        assert buf.recent_clean is True

    @pytest.mark.unit
    def test_syncbuffer_mark_unclean(self):
        """Test SyncBuffer._MarkUnclean() method."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)

        assert buf.clean is True
        assert buf.recent_clean is True

        buf._MarkUnclean()

        assert buf.clean is False
        assert buf.recent_clean is False

    @pytest.mark.unit
    def test_syncbuffer_finish_empty(self):
        """Test SyncBuffer.Finish() with no messages or failures."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)

        with mock.patch.object(buf, "_PrintMessages"):
            with mock.patch.object(buf, "_RunLater"):
                result = buf.Finish()

        assert result is True

    @pytest.mark.unit
    def test_syncbuffer_finish_with_failure(self):
        """Test SyncBuffer.Finish() with failures."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)
        buf.clean = False

        with mock.patch.object(buf, "_PrintMessages"):
            with mock.patch.object(buf, "_RunLater"):
                result = buf.Finish()

        assert result is False

    @pytest.mark.unit
    def test_syncbuffer_runqueue_success(self):
        """Test SyncBuffer._RunQueue() with successful actions."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)

        action1 = mock.MagicMock()
        action2 = mock.MagicMock()
        project = mock.MagicMock()

        later1 = _Later(project, action1, quiet=True)
        later2 = _Later(project, action2, quiet=True)

        buf._later_queue1 = [later1, later2]

        with mock.patch.object(later1, "Run", return_value=True):
            with mock.patch.object(later2, "Run", return_value=True):
                result = buf._RunQueue("_later_queue1")

        assert result is True
        assert buf._later_queue1 == []

    @pytest.mark.unit
    def test_syncbuffer_runqueue_failure(self):
        """Test SyncBuffer._RunQueue() with failed action."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)

        action = mock.MagicMock()
        project = mock.MagicMock()
        later = _Later(project, action, quiet=True)

        buf._later_queue1 = [later]

        with mock.patch.object(later, "Run", return_value=False):
            result = buf._RunQueue("_later_queue1")

        assert result is False
        assert buf.clean is False
        assert buf.recent_clean is False

    @pytest.mark.unit
    def test_syncbuffer_runlater(self):
        """Test SyncBuffer._RunLater() processes both queues."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)

        with mock.patch.object(buf, "_RunQueue", return_value=True) as mock_run:
            buf._RunLater()

        assert mock_run.call_count == 2
        mock_run.assert_any_call("_later_queue1")
        mock_run.assert_any_call("_later_queue2")

    @pytest.mark.unit
    def test_syncbuffer_runlater_stops_on_failure(self):
        """Test SyncBuffer._RunLater() stops when queue1 fails."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)

        with mock.patch.object(buf, "_RunQueue", side_effect=[False, True]) as mock_run:
            buf._RunLater()

        # Should only call once because first returned False
        assert mock_run.call_count == 1

    @pytest.mark.unit
    def test_syncbuffer_printmessages_empty(self):
        """Test SyncBuffer._PrintMessages() with no messages."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)

        with mock.patch("os.isatty", return_value=False):
            buf._PrintMessages()

        # Should not crash with empty messages

    @pytest.mark.unit
    def test_syncbuffer_printmessages_with_messages(self):
        """Test SyncBuffer._PrintMessages() with messages."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)

        project = mock.MagicMock()
        project.RelPath.return_value = "test/project"

        info = _InfoMessage(project, "info message")
        failure = _Failure(project, Exception("error"))

        buf._messages = [info]
        buf._failures = [failure]

        with mock.patch("os.isatty", return_value=True):
            with mock.patch.object(info, "Print"):
                with mock.patch.object(failure, "Print"):
                    buf._PrintMessages()

        assert buf._messages == []
        # Note: _failures is NOT cleared in _PrintMessages


@pytest.mark.unit
class TestSyncBufferHelpers:
    """Test helper classes for SyncBuffer."""

    @pytest.mark.unit
    def test_infomessage_print(self):
        """Test _InfoMessage.Print() method."""
        project = mock.MagicMock()
        project.RelPath.return_value = "test/project"

        msg = _InfoMessage(project, "test message")
        syncbuf = mock.MagicMock()

        msg.Print(syncbuf)

        syncbuf.out.info.assert_called_once()
        syncbuf.out.nl.assert_called_once()

    @pytest.mark.unit
    def test_failure_print(self):
        """Test _Failure.Print() method."""
        project = mock.MagicMock()
        project.RelPath.return_value = "test/project"

        err = Exception("test error")
        failure = _Failure(project, err)
        syncbuf = mock.MagicMock()

        failure.Print(syncbuf)

        syncbuf.out.fail.assert_called_once()
        syncbuf.out.nl.assert_called_once()

    @pytest.mark.unit
    def test_later_run_success_quiet(self):
        """Test _Later.Run() success with quiet=True."""
        project = mock.MagicMock()
        project.RelPath.return_value = "test/project"
        action = mock.MagicMock()

        later = _Later(project, action, quiet=True)
        syncbuf = mock.MagicMock()

        result = later.Run(syncbuf)

        assert result is True
        action.assert_called_once()
        syncbuf.out.project.assert_not_called()

    @pytest.mark.unit
    def test_later_run_success_verbose(self):
        """Test _Later.Run() success with quiet=False."""
        project = mock.MagicMock()
        project.RelPath.return_value = "test/project"
        action = mock.MagicMock()

        later = _Later(project, action, quiet=False)
        syncbuf = mock.MagicMock()

        result = later.Run(syncbuf)

        assert result is True
        action.assert_called_once()
        syncbuf.out.project.assert_called_once()
        assert syncbuf.out.nl.call_count == 2

    @pytest.mark.unit
    def test_later_run_failure(self):
        """Test _Later.Run() with GitError."""
        project = mock.MagicMock()
        project.RelPath.return_value = "test/project"
        action = mock.MagicMock(side_effect=GitError("test error"))

        later = _Later(project, action, quiet=False)
        syncbuf = mock.MagicMock()

        result = later.Run(syncbuf)

        assert result is False
        action.assert_called_once()


@pytest.mark.unit
class TestLocalSyncFailErrors:
    """Test LocalSyncFail error classes."""

    @pytest.mark.unit
    def test_priorsyncfailed_error_str(self):
        """Test _PriorSyncFailedError string representation."""
        err = _PriorSyncFailedError()
        assert str(err) == "prior sync failed; rebase still in progress"

    @pytest.mark.unit
    def test_dirty_error_str(self):
        """Test _DirtyError string representation."""
        err = _DirtyError()
        assert str(err) == "contains uncommitted changes"


@pytest.mark.unit
class TestMetaProjectProperties:
    """Test MetaProject property methods."""

    def _create_metaproject(self, tmp_path):
        """Helper to create a MetaProject instance."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = str(tmp_path / "topdir")
        manifest.repodir = str(tmp_path / "topdir/.repo")
        manifest.globalConfig = mock.MagicMock()

        gitdir = str(tmp_path / ".repo/manifests.git")
        worktree = str(tmp_path / ".repo/manifests")

        os.makedirs(gitdir, exist_ok=True)
        os.makedirs(worktree, exist_ok=True)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            meta = MetaProject(
                manifest=manifest,
                name="manifests",
                gitdir=gitdir,
                worktree=worktree,
            )

        return meta

    @pytest.mark.unit
    def test_metaproject_init(self, tmp_path):
        """Test MetaProject initialization."""
        meta = self._create_metaproject(tmp_path)

        assert meta.name == "manifests"
        assert meta.relpath == ".repo/manifests"
        assert meta.revisionExpr == "refs/heads/master"
        assert meta.revisionId is None

    @pytest.mark.unit
    def test_metaproject_presync_no_current_branch(self, tmp_path):
        """Test MetaProject.PreSync() with no current branch."""
        meta = self._create_metaproject(tmp_path)

        with mock.patch.object(
            type(meta),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=True,
        ):
            with mock.patch.object(
                type(meta),
                "CurrentBranch",
                new_callable=mock.PropertyMock,
                return_value=None,
            ):
                meta.PreSync()

        # Should not change revisionExpr
        assert meta.revisionExpr == "refs/heads/master"

    @pytest.mark.unit
    def test_metaproject_presync_with_branch_no_merge(self, tmp_path):
        """Test MetaProject.PreSync() with branch but no merge."""
        meta = self._create_metaproject(tmp_path)

        branch = mock.MagicMock()
        branch.merge = None

        with mock.patch.object(
            type(meta),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=True,
        ):
            with mock.patch.object(
                type(meta),
                "CurrentBranch",
                new_callable=mock.PropertyMock,
                return_value="main",
            ):
                with mock.patch.object(meta, "GetBranch", return_value=branch):
                    meta.PreSync()

        # Should not change revisionExpr
        assert meta.revisionExpr == "refs/heads/master"

    @pytest.mark.unit
    def test_metaproject_presync_with_branch_and_merge(self, tmp_path):
        """Test MetaProject.PreSync() with branch and merge."""
        meta = self._create_metaproject(tmp_path)

        branch = mock.MagicMock()
        branch.merge = "refs/heads/main"

        with mock.patch.object(
            type(meta),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=True,
        ):
            with mock.patch.object(
                type(meta),
                "CurrentBranch",
                new_callable=mock.PropertyMock,
                return_value="main",
            ):
                with mock.patch.object(meta, "GetBranch", return_value=branch):
                    meta.PreSync()

        assert meta.revisionExpr == "refs/heads/main"
        assert meta.revisionId is None

    @pytest.mark.unit
    def test_metaproject_haschanges_no_remote(self, tmp_path):
        """Test MetaProject.HasChanges with no remote."""
        meta = self._create_metaproject(tmp_path)
        meta.remote = None

        assert meta.HasChanges is False

    @pytest.mark.unit
    def test_metaproject_haschanges_no_revision(self, tmp_path):
        """Test MetaProject.HasChanges with no revisionExpr."""
        meta = self._create_metaproject(tmp_path)
        meta.revisionExpr = None

        assert meta.HasChanges is False

    @pytest.mark.unit
    def test_metaproject_haschanges_same_revision(self, tmp_path):
        """Test MetaProject.HasChanges when HEAD matches revision."""
        meta = self._create_metaproject(tmp_path)

        all_refs = {"refs/heads/master": "abc123"}

        with mock.patch.object(meta, "bare_ref") as mock_bare_ref:
            mock_bare_ref.all = all_refs
            with mock.patch.object(meta.work_git, "GetHead", return_value="abc123"):
                with mock.patch.object(meta, "GetRevisionId", return_value="abc123"):
                    result = meta.HasChanges

        assert result is False

    @pytest.mark.unit
    def test_metaproject_haschanges_different_revision_no_revlist(self, tmp_path):
        """Test MetaProject.HasChanges with different revision but no commits."""
        meta = self._create_metaproject(tmp_path)

        all_refs = {"refs/heads/master": "def456"}

        with mock.patch.object(meta, "bare_ref") as mock_bare_ref:
            mock_bare_ref.all = all_refs
            with mock.patch.object(meta.work_git, "GetHead", return_value="abc123"):
                with mock.patch.object(meta, "GetRevisionId", return_value="def456"):
                    with mock.patch.object(meta, "_revlist", return_value=[]):
                        result = meta.HasChanges

        assert result is False

    @pytest.mark.unit
    def test_metaproject_haschanges_different_revision_has_commits(self, tmp_path):
        """Test MetaProject.HasChanges with different revision and commits."""
        meta = self._create_metaproject(tmp_path)

        all_refs = {"refs/heads/master": "def456"}

        with mock.patch.object(meta, "bare_ref") as mock_bare_ref:
            mock_bare_ref.all = all_refs
            with mock.patch.object(meta.work_git, "GetHead", return_value="abc123"):
                with mock.patch.object(meta, "GetRevisionId", return_value="def456"):
                    with mock.patch.object(meta, "_revlist", return_value=["commit1"]):
                        result = meta.HasChanges

        assert result is True

    @pytest.mark.unit
    def test_metaproject_haschanges_head_is_branch(self, tmp_path):
        """Test MetaProject.HasChanges when HEAD is a branch reference."""
        meta = self._create_metaproject(tmp_path)

        all_refs = {"refs/heads/master": "abc123"}

        with mock.patch.object(meta, "bare_ref") as mock_bare_ref:
            mock_bare_ref.all = all_refs
            with mock.patch.object(meta.work_git, "GetHead", return_value="refs/heads/master"):
                with mock.patch.object(meta, "GetRevisionId", return_value="abc123"):
                    result = meta.HasChanges

        assert result is False

    @pytest.mark.unit
    def test_metaproject_haschanges_head_is_missing_branch(self, tmp_path):
        """Test MetaProject.HasChanges when HEAD branch is missing."""
        meta = self._create_metaproject(tmp_path)

        all_refs = {"refs/heads/master": "abc123"}

        with mock.patch.object(meta, "bare_ref") as mock_bare_ref:
            mock_bare_ref.all = all_refs
            with mock.patch.object(meta.work_git, "GetHead", return_value="refs/heads/other"):
                with mock.patch.object(meta, "GetRevisionId", return_value="def456"):
                    with mock.patch.object(meta, "_revlist", return_value=["commit1"]):
                        result = meta.HasChanges

        assert result is True


@pytest.mark.unit
class TestMetaProjectSyncMethod:
    """Test MetaProject.Sync() method branches."""

    def _create_manifest_project(self, tmp_path):
        """Helper to create a ManifestProject instance."""
        from kanon_cli.repo.project import ManifestProject

        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = str(tmp_path / "topdir")
        manifest.repodir = str(tmp_path / "topdir/.repo")
        manifest.globalConfig = mock.MagicMock()
        manifest.GetDefaultGroupsStr.return_value = "default"
        manifest.PartialCloneExclude = None
        manifest.CloneFilterForDepth = None
        manifest.is_submanifest = False

        gitdir = str(tmp_path / ".repo/manifests.git")
        worktree = str(tmp_path / ".repo/manifests")

        os.makedirs(gitdir, exist_ok=True)
        os.makedirs(worktree, exist_ok=True)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            mp = ManifestProject(
                manifest=manifest,
                name="manifests",
                gitdir=gitdir,
                worktree=worktree,
            )

        return mp

    @pytest.mark.unit
    def test_sync_kwargs_only_assertion(self, tmp_path):
        """Test that Sync() raises assertion if positional args provided."""
        mp = self._create_manifest_project(tmp_path)

        with pytest.raises(AssertionError):
            mp.Sync("positional_arg")

    @pytest.mark.unit
    def test_sync_outer_manifest_delegation(self, tmp_path):
        """Test Sync() delegates to outer manifest when is_submanifest."""
        mp = self._create_manifest_project(tmp_path)
        mp.manifest.is_submanifest = True

        outer_mp = mock.MagicMock()
        outer_mp.Sync.return_value = True
        mp.client = mock.MagicMock()
        mp.client.outer_manifest.manifestProject = outer_mp

        result = mp.Sync(
            manifest_url="https://example.com/manifest",
            outer_manifest=True,
        )

        assert result is True
        outer_mp.Sync.assert_called_once()
        # Verify outer_manifest=False is passed to avoid infinite recursion
        assert outer_mp.Sync.call_args[1]["outer_manifest"] is False

    @pytest.mark.unit
    def test_sync_not_exists_no_manifest_url(self, tmp_path):
        """Test Sync() fails when is_new and no manifest_url."""
        mp = self._create_manifest_project(tmp_path)

        with mock.patch.object(
            type(mp),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch("kanon_cli.repo.project.logger") as mock_logger:
                result = mp.Sync()

        assert result is False
        mock_logger.error.assert_called_with("fatal: manifest url is required.")

    @pytest.mark.unit
    def test_sync_standalone_and_no_url_in_existing(self, tmp_path):
        """Test Sync() fails for standalone manifest without URL."""
        mp = self._create_manifest_project(tmp_path)

        with mock.patch.object(
            type(mp),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=True,
        ):
            with mock.patch.object(mp.config, "GetString", return_value="https://old.com"):
                with mock.patch("kanon_cli.repo.project.logger") as mock_logger:
                    result = mp.Sync(manifest_url="")

        assert result is False
        mock_logger.error.assert_called()

    @pytest.mark.unit
    def test_sync_standalone_removes_existing(self, tmp_path):
        """Test Sync() removes existing dirs for standalone manifest."""
        mp = self._create_manifest_project(tmp_path)

        # Create directories
        os.makedirs(mp.gitdir, exist_ok=True)
        os.makedirs(mp.worktree, exist_ok=True)

        with mock.patch.object(
            type(mp),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=True,
        ):
            with mock.patch.object(mp.config, "GetString", return_value=None):
                with mock.patch.object(mp.config, "ClearCache"):
                    with mock.patch("kanon_cli.repo.platform_utils.rmtree") as mock_rmtree:
                        with mock.patch.object(mp, "_InitGitDir"):
                            with mock.patch.object(mp, "GetRemote"):
                                with mock.patch(
                                    "kanon_cli.repo.fetch.fetch_file",
                                    return_value=b"<manifest/>",
                                ):
                                    with mock.patch.object(mp.manifest, "Link"):
                                        mp.Sync(
                                            manifest_url="https://example.com/manifest",
                                            standalone_manifest=True,
                                        )

        assert mock_rmtree.call_count >= 2

    @pytest.mark.unit
    def test_sync_platform_invalid(self, tmp_path):
        """Test Sync() with invalid platform value."""
        mp = self._create_manifest_project(tmp_path)

        with mock.patch.object(
            type(mp),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(mp, "_InitGitDir"):
                with mock.patch.object(mp, "GetRemote"):
                    with mock.patch.object(mp, "ResolveRemoteHead", return_value="refs/heads/main"):
                        with mock.patch("kanon_cli.repo.project.logger"):
                            result = mp.Sync(
                                manifest_url="https://example.com/manifest",
                                platform="invalid",
                            )

        assert result is False

    @pytest.mark.unit
    def test_sync_network_half_failure(self, tmp_path):
        """Test Sync() handles Sync_NetworkHalf failure."""
        mp = self._create_manifest_project(tmp_path)

        with mock.patch.object(
            type(mp),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(mp, "_InitGitDir"):
                with mock.patch.object(mp, "GetRemote") as mock_remote:
                    mock_remote.return_value.url = "https://example.com/manifest"
                    with mock.patch.object(mp, "ResolveRemoteHead", return_value="refs/heads/main"):
                        with mock.patch.object(mp, "Sync_NetworkHalf") as mock_network:
                            mock_network.return_value = mock.MagicMock(success=False)
                            with mock.patch("kanon_cli.repo.platform_utils.rmtree") as mock_rmtree:
                                with mock.patch("kanon_cli.repo.project.logger") as mock_logger:
                                    result = mp.Sync(
                                        manifest_url="https://example.com/manifest",
                                    )

        assert result is False
        mock_logger.error.assert_called()
        mock_rmtree.assert_called_once()

    @pytest.mark.unit
    def test_sync_start_default_branch(self, tmp_path):
        """Test Sync() starts default branch for new repo."""
        mp = self._create_manifest_project(tmp_path)

        with mock.patch.object(
            type(mp),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(mp, "_InitGitDir"):
                with mock.patch.object(mp, "GetRemote"):
                    with mock.patch.object(mp, "ResolveRemoteHead", return_value="refs/heads/main"):
                        with mock.patch.object(mp, "Sync_NetworkHalf") as mock_network:
                            mock_network.return_value = mock.MagicMock(success=True)
                            with mock.patch.object(mp, "Sync_LocalHalf"):
                                with mock.patch("kanon_cli.repo.project.SyncBuffer"):
                                    with mock.patch.object(
                                        type(mp),
                                        "CurrentBranch",
                                        new_callable=mock.PropertyMock,
                                        return_value=None,
                                    ):
                                        with mock.patch.object(mp, "StartBranch") as mock_start:
                                            with mock.patch.object(mp.manifest, "Link"):
                                                mp.Sync(
                                                    manifest_url="https://example.com/manifest",
                                                )

        mock_start.assert_called_once_with("default")

    @pytest.mark.unit
    def test_sync_start_branch_failure(self, tmp_path):
        """Test Sync() handles StartBranch failure."""
        mp = self._create_manifest_project(tmp_path)

        with mock.patch.object(
            type(mp),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(mp, "_InitGitDir"):
                with mock.patch.object(mp, "GetRemote"):
                    with mock.patch.object(mp, "ResolveRemoteHead", return_value="refs/heads/main"):
                        with mock.patch.object(mp, "Sync_NetworkHalf") as mock_network:
                            mock_network.return_value = mock.MagicMock(success=True)
                            with mock.patch.object(mp, "Sync_LocalHalf"):
                                with mock.patch("kanon_cli.repo.project.SyncBuffer"):
                                    with mock.patch.object(
                                        type(mp),
                                        "CurrentBranch",
                                        new_callable=mock.PropertyMock,
                                        return_value=None,
                                    ):
                                        with mock.patch.object(
                                            mp,
                                            "StartBranch",
                                            side_effect=GitError("error"),
                                        ):
                                            with mock.patch("kanon_cli.repo.project.logger"):
                                                result = mp.Sync(
                                                    manifest_url="https://example.com/manifest",
                                                )

        assert result is False


@pytest.mark.unit
class TestProjectApplyCloneBundle:
    """Test Project._ApplyCloneBundle and related methods."""

    def _create_project(self, tmp_path):
        """Helper to create a Project instance."""
        from kanon_cli.repo.project import Project

        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = str(tmp_path / "topdir")
        manifest.repodir = str(tmp_path / "topdir/.repo")
        manifest.globalConfig = mock.MagicMock()
        manifest.manifestProject.depth = None

        gitdir = str(tmp_path / "project.git")
        objdir = str(tmp_path / "project.git")
        worktree = str(tmp_path / "worktree")

        os.makedirs(gitdir, exist_ok=True)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            project = Project(
                manifest=manifest,
                name="test-project",
                gitdir=gitdir,
                objdir=objdir,
                worktree=worktree,
                remote=mock.MagicMock(),
                relpath="test-project",
                revisionExpr="refs/heads/main",
                revisionId=None,
            )

        return project

    @pytest.mark.unit
    def test_applyclonebundle_clone_depth(self, tmp_path):
        """Test _ApplyCloneBundle returns False when clone_depth is set."""
        project = self._create_project(tmp_path)
        project.clone_depth = 1

        result = project._ApplyCloneBundle(initial=True, quiet=True, verbose=False)

        assert result is False

    @pytest.mark.unit
    def test_applyclonebundle_unsupported_scheme(self, tmp_path):
        """Test _ApplyCloneBundle returns False for unsupported URL scheme."""
        project = self._create_project(tmp_path)
        project.clone_depth = None

        remote = mock.MagicMock()
        remote.url = "ssh://example.com/repo.git"

        with mock.patch.object(project, "GetRemote", return_value=remote):
            with mock.patch("kanon_cli.repo.git_config.GitConfig.ForUser") as mock_config:
                mock_config.return_value.UrlInsteadOf.return_value = "ssh://example.com/repo.git"
                result = project._ApplyCloneBundle(initial=True, quiet=True, verbose=False)

        assert result is False

    @pytest.mark.unit
    def test_applyclonebundle_not_initial_no_bundle(self, tmp_path):
        """Test _ApplyCloneBundle returns False when not initial and no bundle exists."""
        project = self._create_project(tmp_path)
        project.clone_depth = None

        remote = mock.MagicMock()
        remote.url = "https://example.com/repo.git"

        with mock.patch.object(project, "GetRemote", return_value=remote):
            with mock.patch("kanon_cli.repo.git_config.GitConfig.ForUser") as mock_config:
                mock_config.return_value.UrlInsteadOf.return_value = "https://example.com/repo.git"
                result = project._ApplyCloneBundle(initial=False, quiet=True, verbose=False)

        assert result is False

    @pytest.mark.unit
    def test_applyclonebundle_fetch_bundle_success(self, tmp_path):
        """Test _ApplyCloneBundle fetches and applies bundle successfully."""
        project = self._create_project(tmp_path)
        project.clone_depth = None

        remote = mock.MagicMock()
        remote.url = "https://example.com/repo.git"
        remote.fetch = []

        with mock.patch.object(project, "GetRemote", return_value=remote):
            with mock.patch("kanon_cli.repo.git_config.GitConfig.ForUser") as mock_config:
                mock_config.return_value.UrlInsteadOf.return_value = "https://example.com/repo.git"
                with mock.patch.object(project, "_FetchBundle", return_value=True):
                    with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
                        mock_git.return_value.Wait.return_value = 0
                        with mock.patch("kanon_cli.repo.platform_utils.remove"):
                            result = project._ApplyCloneBundle(initial=True, quiet=True, verbose=False)

        assert result is True

    @pytest.mark.unit
    def test_applyclonebundle_fetch_fails(self, tmp_path):
        """Test _ApplyCloneBundle returns False when fetch fails."""
        project = self._create_project(tmp_path)
        project.clone_depth = None

        remote = mock.MagicMock()
        remote.url = "https://example.com/repo.git"

        with mock.patch.object(project, "GetRemote", return_value=remote):
            with mock.patch("kanon_cli.repo.git_config.GitConfig.ForUser") as mock_config:
                mock_config.return_value.UrlInsteadOf.return_value = "https://example.com/repo.git"
                with mock.patch.object(project, "_FetchBundle", return_value=False):
                    result = project._ApplyCloneBundle(initial=True, quiet=True, verbose=False)

        assert result is False

    @pytest.mark.unit
    def test_isvalidbundle_valid(self, tmp_path):
        """Test _IsValidBundle with valid bundle."""
        project = self._create_project(tmp_path)

        bundle_path = tmp_path / "test.bundle"
        with open(bundle_path, "wb") as f:
            f.write(b"# v2 git bundle\n")

        result = project._IsValidBundle(str(bundle_path), quiet=True)

        assert result is True

    @pytest.mark.unit
    def test_isvalidbundle_invalid(self, tmp_path):
        """Test _IsValidBundle with invalid bundle."""
        project = self._create_project(tmp_path)

        bundle_path = tmp_path / "test.bundle"
        with open(bundle_path, "wb") as f:
            f.write(b"not a bundle\n")

        result = project._IsValidBundle(str(bundle_path), quiet=True)

        assert result is False

    @pytest.mark.unit
    def test_isvalidbundle_nonexistent(self, tmp_path):
        """Test _IsValidBundle with nonexistent file."""
        project = self._create_project(tmp_path)

        result = project._IsValidBundle("/nonexistent/file", quiet=True)

        assert result is False


@pytest.mark.unit
class TestProjectCheckoutRebaseOperations:
    """Test Project checkout, rebase, and cherry-pick operations."""

    def _create_project(self, tmp_path):
        """Helper to create a Project instance."""
        from kanon_cli.repo.project import Project

        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = str(tmp_path / "topdir")
        manifest.repodir = str(tmp_path / "topdir/.repo")
        manifest.globalConfig = mock.MagicMock()

        gitdir = str(tmp_path / "project.git")
        objdir = str(tmp_path / "project.git")
        worktree = str(tmp_path / "worktree")

        os.makedirs(gitdir, exist_ok=True)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            project = Project(
                manifest=manifest,
                name="test-project",
                gitdir=gitdir,
                objdir=objdir,
                worktree=worktree,
                remote=mock.MagicMock(),
                relpath="test-project",
                revisionExpr="refs/heads/main",
                revisionId=None,
            )

        return project

    @pytest.mark.unit
    def test_checkout_success(self, tmp_path):
        """Test _Checkout succeeds."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            project._Checkout("abc123", quiet=True)

        mock_git.assert_called_once()

    @pytest.mark.unit
    def test_checkout_force(self, tmp_path):
        """Test _Checkout with force_checkout."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            project._Checkout("abc123", force_checkout=True, quiet=False)

        args = mock_git.call_args[0][1]
        assert "-f" in args

    @pytest.mark.unit
    def test_cherrypick_success(self, tmp_path):
        """Test _CherryPick succeeds."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            project._CherryPick("abc123")

        mock_git.assert_called_once()

    @pytest.mark.unit
    def test_cherrypick_with_ffonly(self, tmp_path):
        """Test _CherryPick with ffonly."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            project._CherryPick("abc123", ffonly=True)

        args = mock_git.call_args[0][1]
        assert "--ff" in args

    @pytest.mark.unit
    def test_cherrypick_with_record_origin(self, tmp_path):
        """Test _CherryPick with record_origin."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            project._CherryPick("abc123", record_origin=True)

        args = mock_git.call_args[0][1]
        assert "-x" in args

    @pytest.mark.unit
    def test_rebase_success(self, tmp_path):
        """Test _Rebase succeeds."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            project._Rebase("upstream")

        mock_git.assert_called_once()

    @pytest.mark.unit
    def test_rebase_with_onto(self, tmp_path):
        """Test _Rebase with onto."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            project._Rebase("upstream", onto="target")

        args = mock_git.call_args[0][1]
        assert "--onto" in args
        assert "target" in args

    @pytest.mark.unit
    def test_rebase_failure_raises(self, tmp_path):
        """Test _Rebase raises GitError on failure."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 1
            with pytest.raises(GitError):
                project._Rebase("upstream")

    @pytest.mark.unit
    def test_fastforward_success(self, tmp_path):
        """Test _FastForward succeeds."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            project._FastForward("abc123")

        mock_git.assert_called_once()

    @pytest.mark.unit
    def test_fastforward_ffonly(self, tmp_path):
        """Test _FastForward with ffonly."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            project._FastForward("abc123", ffonly=True)

        args = mock_git.call_args[0][1]
        assert "--ff-only" in args

    @pytest.mark.unit
    def test_resetthard_success(self, tmp_path):
        """Test _ResetHard succeeds."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            project._ResetHard("abc123")

        mock_git.assert_called_once()

    @pytest.mark.unit
    def test_resetthard_failure_raises(self, tmp_path):
        """Test _ResetHard raises GitError on failure."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 1
            with pytest.raises(GitError):
                project._ResetHard("abc123")

    @pytest.mark.unit
    def test_revert_success(self, tmp_path):
        """Test _Revert succeeds."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            project._Revert("abc123")

        args = mock_git.call_args[0][1]
        assert "revert" in args
        assert "--no-edit" in args

    @pytest.mark.unit
    def test_lsremote_success(self, tmp_path):
        """Test _LsRemote returns stdout."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            mock_git.return_value.stdout = "abc123\trefs/heads/main\n"
            result = project._LsRemote("refs/heads/*")

        assert result == "abc123\trefs/heads/main\n"

    @pytest.mark.unit
    def test_lsremote_failure(self, tmp_path):
        """Test _LsRemote returns None on failure."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 1
            result = project._LsRemote("refs/heads/*")

        assert result is None

    @pytest.mark.unit
    def test_syncsubmodules_success(self, tmp_path):
        """Test _SyncSubmodules succeeds."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            project._SyncSubmodules(quiet=False)

        mock_git.assert_called_once()

    @pytest.mark.unit
    def test_initsubmodules_success(self, tmp_path):
        """Test _InitSubmodules succeeds."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            project._InitSubmodules(quiet=True)

        mock_git.assert_called_once()


@pytest.mark.unit
class TestProjectGetLogs:
    """Test Project._getLogs and getAddedAndRemovedLogs methods."""

    def _create_project(self, tmp_path):
        """Helper to create a Project instance."""
        from kanon_cli.repo.project import Project

        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = str(tmp_path / "topdir")
        manifest.repodir = str(tmp_path / "topdir/.repo")
        manifest.globalConfig = mock.MagicMock()

        gitdir = str(tmp_path / "project.git")
        objdir = str(tmp_path / "project.git")
        worktree = str(tmp_path / "worktree")

        os.makedirs(gitdir, exist_ok=True)
        os.makedirs(worktree, exist_ok=True)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            project = Project(
                manifest=manifest,
                name="test-project",
                gitdir=gitdir,
                objdir=objdir,
                worktree=worktree,
                remote=mock.MagicMock(),
                relpath="test-project",
                revisionExpr="refs/heads/main",
                revisionId=None,
            )

        return project

    @pytest.mark.unit
    def test_getlogs_no_rev1(self, tmp_path):
        """Test _getLogs returns None when rev1 is None."""
        project = self._create_project(tmp_path)

        result = project._getLogs(None, "abc123")

        assert result is None

    @pytest.mark.unit
    def test_getlogs_success(self, tmp_path):
        """Test _getLogs returns log output."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            mock_git.return_value.stdout = "commit abc123\n"
            result = project._getLogs("abc123", "def456")

        assert result == "commit abc123\n"

    @pytest.mark.unit
    def test_getlogs_with_oneline(self, tmp_path):
        """Test _getLogs with oneline option."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            mock_git.return_value.stdout = "abc123 commit message\n"
            project._getLogs("abc123", "def456", oneline=True)

        mock_git.assert_called_once()
        args = mock_git.call_args[0][1]
        assert "--oneline" in args

    @pytest.mark.unit
    def test_getlogs_with_color(self, tmp_path):
        """Test _getLogs with color option."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            mock_git.return_value.stdout = "commit abc123\n"
            with mock.patch("kanon_cli.repo.project.DiffColoring") as mock_coloring:
                mock_coloring.return_value.is_on = True
                project._getLogs("abc123", "def456", color=True)

        args = mock_git.call_args[0][1]
        assert "--color" in args

    @pytest.mark.unit
    def test_getlogs_with_pretty_format(self, tmp_path):
        """Test _getLogs with pretty_format option."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_git.return_value.Wait.return_value = 0
            mock_git.return_value.stdout = "abc123|message\n"
            project._getLogs("abc123", "def456", pretty_format="%h|%s")

        args = mock_git.call_args[0][1]
        assert any("--pretty=format:" in arg for arg in args)

    @pytest.mark.unit
    def test_getlogs_worktree_missing_fallback(self, tmp_path):
        """Test _getLogs falls back to bare_git when worktree missing."""
        project = self._create_project(tmp_path)

        # Remove worktree
        os.rmdir(project.worktree)

        with mock.patch("kanon_cli.repo.project.GitCommand", side_effect=GitError("error")):
            with mock.patch.object(project.bare_git, "log", return_value="log output") as mock_log:
                project._getLogs("abc123", "def456")

        mock_log.assert_called_once()

    @pytest.mark.unit
    def test_getlogs_worktree_exists_reraises(self, tmp_path):
        """Test _getLogs re-raises GitError when worktree exists."""
        project = self._create_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand", side_effect=GitError("error")):
            with pytest.raises(GitError):
                project._getLogs("abc123", "def456")
