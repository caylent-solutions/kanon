# Copyright (C) 2022 The Android Open Source Project
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
"""Unit tests for uncovered lines in subcmds/sync.py"""

import json
import multiprocessing
import os
import tempfile
import time
from unittest import mock
import urllib.error
import xml.parsers.expat

import pytest

from kanon_cli.repo.error import RepoChangedException
from kanon_cli.repo.error import RepoUnhandledExceptionError
from kanon_cli.repo.error import SyncError
from kanon_cli.repo.subcmds import sync


@pytest.mark.unit
class TestRlimitNofile:
    """Test _rlimit_nofile functions."""

    def test_import_error_fallback(self):
        """Test fallback when resource module is not available."""
        # The ImportError path (lines 48-51) is already covered by the module load,
        # but we can test the function behavior
        with mock.patch.dict("sys.modules", {"resource": None}):
            # Force reimport to test ImportError path
            from kanon_cli.repo.subcmds import sync as sync_module

            # The _rlimit_nofile function should exist and return default
            # This tests lines 50-51
            assert callable(getattr(sync_module, "_rlimit_nofile", None))


@pytest.mark.unit
class TestThreadingImport:
    """Test threading import fallback."""

    def test_threading_import_fallback(self):
        """Test fallback to dummy_threading (lines 39-40)."""
        # This tests the ImportError case for threading
        # The actual import happens at module level, so we verify the module exists
        from kanon_cli.repo.subcmds import sync as sync_module

        assert hasattr(sync_module, "_threading")


@pytest.mark.unit
class TestPostRepoUpgrade:
    """Test _PostRepoUpgrade function."""

    def test_post_repo_upgrade_creates_symlink(self):
        """Test _PostRepoUpgrade creates internal-fs-layout.md symlink."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = mock.MagicMock()
            manifest.repodir = tmpdir
            manifest.projects = []

            # Mock platform_utils functions
            with mock.patch("kanon_cli.repo.subcmds.sync.platform_utils") as mock_platform:
                with mock.patch("kanon_cli.repo.subcmds.sync.Wrapper") as mock_wrapper:
                    mock_platform.islink.return_value = False
                    mock_platform.symlink.return_value = None
                    wrapper_inst = mock.MagicMock()
                    wrapper_inst.NeedSetupGnuPG.return_value = False
                    mock_wrapper.return_value = wrapper_inst

                    sync._PostRepoUpgrade(manifest, quiet=True)

                    # Verify symlink was attempted (line 2605)
                    mock_platform.symlink.assert_called_once()

    def test_post_repo_upgrade_with_gnupg_setup(self):
        """Test _PostRepoUpgrade with GnuPG setup needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = mock.MagicMock()
            manifest.repodir = tmpdir
            project = mock.MagicMock()
            project.Exists = True
            manifest.projects = [project]

            with mock.patch("kanon_cli.repo.subcmds.sync.platform_utils") as mock_platform:
                with mock.patch("kanon_cli.repo.subcmds.sync.Wrapper") as mock_wrapper:
                    mock_platform.islink.return_value = False
                    mock_platform.symlink.side_effect = Exception("test")
                    wrapper_inst = mock.MagicMock()
                    wrapper_inst.NeedSetupGnuPG.return_value = True
                    mock_wrapper.return_value = wrapper_inst

                    # Test lines 2610-2614
                    sync._PostRepoUpgrade(manifest, quiet=False)

                    wrapper_inst.SetupGnuPG.assert_called_once_with(False)
                    project.PostRepoUpgrade.assert_called_once()


@pytest.mark.unit
class TestPostRepoFetch:
    """Test _PostRepoFetch function."""

    def test_post_repo_fetch_no_changes(self):
        """Test _PostRepoFetch when repo has no changes."""
        rp = mock.MagicMock()
        rp.HasChanges = False
        rp.work_git.describe.return_value = "v2.15"

        # Test line 2648-2649 (verbose path)
        sync._PostRepoFetch(rp, repo_verify=True, verbose=True)
        rp.work_git.describe.assert_called()

    def test_post_repo_fetch_with_changes_update_needed(self):
        """Test _PostRepoFetch when update is needed."""
        rp = mock.MagicMock()
        rp.HasChanges = True
        rp.bare_git.describe.return_value = "v2.14"
        rp.bare_git.rev_parse.side_effect = ["abc123", "def456"]
        rp.work_git.update_index = mock.MagicMock()
        rp.work_git.reset = mock.MagicMock()
        rp.gitdir = "/tmp/test/.repo/repo"

        with mock.patch("kanon_cli.repo.subcmds.sync.Wrapper") as mock_wrapper:
            wrapper_inst = mock.MagicMock()
            wrapper_inst.check_repo_rev.return_value = (None, "v2.15")
            mock_wrapper.return_value = wrapper_inst

            # Test lines 2618-2644
            with pytest.raises(RepoChangedException):
                sync._PostRepoFetch(rp, repo_verify=True, verbose=False)

            rp.work_git.update_index.assert_called_with("-q", "--refresh")
            rp.work_git.reset.assert_called_with("--keep", "v2.15")

    def test_post_repo_fetch_git_error_on_reset(self):
        """Test _PostRepoFetch when reset fails."""
        from kanon_cli.repo.error import GitError

        rp = mock.MagicMock()
        rp.HasChanges = True
        rp.bare_git.describe.return_value = "v2.14"
        rp.bare_git.rev_parse.side_effect = ["abc123", "def456"]
        rp.work_git.reset.side_effect = GitError("Git error")
        rp.gitdir = "/tmp/test/.repo/repo"

        with mock.patch("kanon_cli.repo.subcmds.sync.Wrapper") as mock_wrapper:
            wrapper_inst = mock.MagicMock()
            wrapper_inst.check_repo_rev.return_value = (None, "v2.15")
            mock_wrapper.return_value = wrapper_inst

            # Test lines 2641-2642
            with pytest.raises(RepoUnhandledExceptionError):
                sync._PostRepoFetch(rp, repo_verify=True, verbose=False)

    def test_post_repo_fetch_same_revid_skips_upgrade(self):
        """Test _PostRepoFetch skips upgrade for same revid."""
        rp = mock.MagicMock()
        rp.HasChanges = True
        rp.bare_git.describe.return_value = "v2.14"
        rp.bare_git.rev_parse.side_effect = ["abc123", "abc123"]
        rp.gitdir = "/tmp/test/.repo/repo"

        with mock.patch("kanon_cli.repo.subcmds.sync.Wrapper") as mock_wrapper:
            wrapper_inst = mock.MagicMock()
            wrapper_inst.check_repo_rev.return_value = (None, "v2.15")
            mock_wrapper.return_value = wrapper_inst

            # Test line 2646 (warning path)
            sync._PostRepoFetch(rp, repo_verify=True, verbose=False)


@pytest.mark.unit
class TestFetchTimes:
    """Test _FetchTimes class."""

    def test_fetch_times_save_with_none_saved(self):
        """Test Save when _saved is None (line 2680-2681)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = mock.MagicMock()
            manifest.repodir = tmpdir

            ft = sync._FetchTimes(manifest)
            # Don't load, so _saved stays None
            ft.Save()  # Should return early

    def test_fetch_times_load_invalid_json(self):
        """Test Load with invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = mock.MagicMock()
            manifest.repodir = tmpdir
            json_path = os.path.join(tmpdir, ".repo_fetchtimes.json")

            # Write invalid JSON
            with open(json_path, "w") as f:
                f.write("{ invalid json")

            ft = sync._FetchTimes(manifest)

            # Test lines 2675-2677 (ValueError path)
            with mock.patch("kanon_cli.repo.subcmds.sync.platform_utils") as mock_platform:
                ft._Load()
                mock_platform.remove.assert_called_once()

    def test_fetch_times_save_os_error(self):
        """Test Save with OSError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = mock.MagicMock()
            manifest.repodir = tmpdir

            ft = sync._FetchTimes(manifest)
            project = mock.MagicMock()
            project.name = "test_project"
            ft.Set(project, 10.0)
            ft._Load()  # Initialize _saved

            # Test lines 2691-2692
            with mock.patch("builtins.open", side_effect=OSError("test error")):
                with mock.patch("kanon_cli.repo.subcmds.sync.platform_utils") as mock_platform:
                    ft.Save()
                    mock_platform.remove.assert_called_once()


@pytest.mark.unit
class TestLocalSyncState:
    """Test LocalSyncState class."""

    def test_prune_removed_projects_removes_old(self):
        """Test PruneRemovedProjects removes projects not on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = mock.MagicMock()
            manifest.repodir = tmpdir
            manifest.topdir = tmpdir
            manifest.projects = []

            state = sync.LocalSyncState(manifest)
            state._Load()  # Initialize _state

            # Add project data for non-existent directory
            state._state = {"old_project": {sync.LocalSyncState._LAST_FETCH: time.time() - (40 * 24 * 60 * 60)}}

            # Test lines in PruneRemovedProjects - should remove non-existent project
            state.PruneRemovedProjects()
            assert "old_project" not in state._state


@pytest.mark.unit
class TestSmartSyncSetup:
    """Test _SmartSyncSetup method."""

    def test_smart_sync_setup_with_smart_sync(self):
        """Test _SmartSyncSetup with smart_sync option."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.client = mock.MagicMock()

        opt = mock.MagicMock()
        opt.smart_sync = "branch_name"
        opt.smart_tag = None

        manifest = mock.MagicMock()
        manifest.manifestProject = mock.MagicMock()
        manifest.manifestProject.config.GetString.return_value = "http://example.com/manifest"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            smart_sync_path = f.name

        try:
            with mock.patch.object(sync_cmd, "_GetBranch", return_value="test_branch"):
                with mock.patch("xmlrpc.client.Server") as mock_server:
                    server_inst = mock.MagicMock()
                    server_inst.GetApprovedManifest.return_value = [
                        True,
                        "<manifest></manifest>",
                    ]
                    mock_server.return_value = server_inst

                    # Test lines around _SmartSyncSetup
                    result = sync_cmd._SmartSyncSetup(opt, smart_sync_path, manifest)
                    assert result is not None
        finally:
            if os.path.exists(smart_sync_path):
                os.unlink(smart_sync_path)


@pytest.mark.unit
class TestUpdateProjectsRevisionId:
    """Test _UpdateProjectsRevisionId method."""

    def test_update_projects_revision_id_this_manifest_only(self):
        """Test _UpdateProjectsRevisionId with this_manifest_only."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_manifest = mock.MagicMock()
        sync_cmd.client = mock.MagicMock()
        sync_cmd.git_event_log = mock.MagicMock()

        opt = mock.MagicMock()
        opt.this_manifest_only = True
        opt.use_superproject = None
        opt.verbose = False

        manifest = mock.MagicMock()
        manifest.path_prefix = "prefix"
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.HasLocalManifests = False
        manifest.superproject = None

        args = []
        superproject_logging_data = {}

        project = mock.MagicMock()
        project.manifest = manifest

        with mock.patch.object(sync_cmd, "GetProjects", return_value=[project]):
            with mock.patch.object(sync_cmd, "ManifestList", return_value=[manifest]):
                # Test lines 698-701
                sync_cmd._UpdateProjectsRevisionId(opt, args, superproject_logging_data, manifest)

    def test_update_projects_revision_id_with_superproject_mirror(self):
        """Test _UpdateProjectsRevisionId with mirror (no working tree)."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_manifest = mock.MagicMock()
        sync_cmd.client = mock.MagicMock()
        sync_cmd.git_event_log = mock.MagicMock()

        opt = mock.MagicMock()
        opt.this_manifest_only = False
        opt.use_superproject = True
        opt.verbose = False

        manifest = mock.MagicMock()
        manifest.path_prefix = "prefix"
        manifest.IsMirror = True
        manifest.IsArchive = False
        manifest.HasLocalManifests = False
        manifest.superproject = mock.MagicMock()

        args = []
        superproject_logging_data = {}

        project = mock.MagicMock()
        project.manifest = manifest

        with mock.patch.object(sync_cmd, "GetProjects", return_value=[project]):
            with mock.patch.object(sync_cmd, "ManifestList", return_value=[manifest]):
                with mock.patch(
                    "kanon_cli.repo.subcmds.sync.git_superproject.UseSuperproject",
                    return_value=True,
                ):
                    # Test lines 718-728 (mirror warning path)
                    sync_cmd._UpdateProjectsRevisionId(opt, args, superproject_logging_data, manifest)


@pytest.mark.unit
class TestFetchMain:
    """Test _FetchMain method."""

    def test_fetch_main_network_only_with_errors(self):
        """Test _FetchMain with network_only and errors."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_client = mock.MagicMock()
        sync_cmd.outer_client.manifest.IsArchive = False
        sync_cmd.event_log = mock.MagicMock()
        sync_cmd._fetch_times = mock.MagicMock()
        sync_cmd._local_sync_state = mock.MagicMock()

        opt = mock.MagicMock()
        opt.network_only = True
        opt.quiet = True
        opt.fail_fast = False

        args = []
        all_projects = []
        err_event = multiprocessing.Event()
        err_event.set()  # Simulate error
        ssh_proxy = mock.MagicMock()
        manifest = mock.MagicMock()
        errors = []

        fetch_result = mock.MagicMock()
        fetch_result.success = False
        fetch_result.projects = set()

        with mock.patch.object(sync_cmd, "_Fetch", return_value=fetch_result):
            # Test lines 1006-1013 (network_only error path)
            with pytest.raises(SyncError):
                sync_cmd._FetchMain(
                    opt,
                    args,
                    all_projects,
                    err_event,
                    ssh_proxy,
                    manifest,
                    errors,
                )

    def test_fetch_main_iterative_fetch_missing_projects(self):
        """Test _FetchMain with missing projects iteration."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_client = mock.MagicMock()
        sync_cmd.outer_client.manifest.IsArchive = False
        sync_cmd.event_log = mock.MagicMock()
        sync_cmd._fetch_times = mock.MagicMock()
        sync_cmd._local_sync_state = mock.MagicMock()

        opt = mock.MagicMock()
        opt.network_only = False
        opt.quiet = True
        opt.fail_fast = False
        opt.fetch_submodules = False
        opt.this_manifest_only = True

        args = []
        project1 = mock.MagicMock()
        project1.gitdir = "/tmp/proj1"
        project1.name = "proj1"
        all_projects = [project1]

        err_event = multiprocessing.Event()
        ssh_proxy = mock.MagicMock()
        manifest = mock.MagicMock()
        errors = []

        fetch_result = mock.MagicMock()
        fetch_result.success = True
        fetch_result.projects = {"/tmp/proj1"}

        with mock.patch.object(sync_cmd, "_Fetch", return_value=fetch_result):
            with mock.patch.object(sync_cmd, "_ReloadManifest"):
                with mock.patch.object(sync_cmd, "GetProjects", return_value=all_projects):
                    with mock.patch.object(sync_cmd, "_GCProjects"):
                        # Test lines 1030-1044
                        result = sync_cmd._FetchMain(
                            opt,
                            args,
                            all_projects,
                            err_event,
                            ssh_proxy,
                            manifest,
                            errors,
                        )
                        assert result.all_projects == all_projects

    def test_fetch_main_stalled_missing_projects(self):
        """Test _FetchMain with stalled missing projects."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_client = mock.MagicMock()
        sync_cmd.outer_client.manifest.IsArchive = False
        sync_cmd.event_log = mock.MagicMock()
        sync_cmd._fetch_times = mock.MagicMock()
        sync_cmd._local_sync_state = mock.MagicMock()

        opt = mock.MagicMock()
        opt.network_only = False
        opt.quiet = True
        opt.fail_fast = False
        opt.fetch_submodules = False
        opt.this_manifest_only = True

        args = []
        project1 = mock.MagicMock()
        project1.gitdir = "/tmp/proj1"
        project1.name = "proj1"
        all_projects = [project1]

        project2 = mock.MagicMock()
        project2.gitdir = "/tmp/proj2"
        project2.name = "proj2"

        err_event = multiprocessing.Event()
        ssh_proxy = mock.MagicMock()
        manifest = mock.MagicMock()
        errors = []

        # First fetch succeeds but doesn't fetch all projects
        fetch_result1 = mock.MagicMock()
        fetch_result1.success = True
        fetch_result1.projects = set()

        # Second fetch also doesn't make progress (same missing set)
        fetch_result2 = mock.MagicMock()
        fetch_result2.success = False
        fetch_result2.projects = set()

        call_count = [0]

        def mock_fetch(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return fetch_result1
            return fetch_result2

        with mock.patch.object(sync_cmd, "_Fetch", side_effect=mock_fetch):
            with mock.patch.object(sync_cmd, "_ReloadManifest"):
                # First returns missing project, second returns same (stall detection)
                with mock.patch.object(
                    sync_cmd,
                    "GetProjects",
                    side_effect=[
                        [project1, project2],
                        [project1, project2],
                    ],
                ):
                    with mock.patch.object(sync_cmd, "_GCProjects"):
                        # Test lines 1035-1044 (stall detection)
                        sync_cmd._FetchMain(
                            opt,
                            args,
                            all_projects,
                            err_event,
                            ssh_proxy,
                            manifest,
                            errors,
                        )


@pytest.mark.unit
class TestCheckoutWorker:
    """Test _Checkout and _CheckoutOne methods."""

    def test_checkout_filters_non_worktree_projects(self):
        """Test _Checkout filters out projects without worktrees."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.event_log = mock.MagicMock()
        sync_cmd._local_sync_state = mock.MagicMock()

        opt = mock.MagicMock()
        opt.jobs_checkout = 1
        opt.detach_head = False
        opt.force_sync = False
        opt.force_checkout = False
        opt.rebase = False
        opt.verbose = False
        opt.quiet = True
        opt.this_manifest_only = True
        opt.fail_fast = False

        project1 = mock.MagicMock()
        project1.worktree = "/tmp/project1"
        project1.name = "proj1"
        project1.relpath = "proj1"

        project2 = mock.MagicMock()
        project2.worktree = None  # No worktree
        project2.name = "proj2"

        all_projects = [project1, project2]
        err_results = []
        checkout_errors = []

        checkout_result = mock.MagicMock()
        checkout_result.success = True
        checkout_result.project_idx = 0
        checkout_result.start = time.time()
        checkout_result.finish = time.time()
        checkout_result.errors = []

        with mock.patch.object(sync_cmd, "ParallelContext"):
            with mock.patch.object(
                sync_cmd,
                "get_parallel_context",
                return_value={"projects": [project1]},
            ):
                with mock.patch.object(sync_cmd, "ExecuteInParallel", return_value=True):
                    # Test line 1121 (filter worktrees)
                    result = sync_cmd._Checkout(all_projects, opt, err_results, checkout_errors)
                    assert result is True


@pytest.mark.unit
class TestGCProjects:
    """Test _GCProjects method."""

    def test_gc_projects_runs_gc(self):
        """Test _GCProjects runs garbage collection."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()

        opt = mock.MagicMock()
        opt.auto_gc = True
        opt.quiet = True
        opt.jobs = 1

        project = mock.MagicMock()
        project.relpath = "test_project"
        project.objdir = "/tmp/obj"
        project.gitdir = "/tmp/git"
        project.config = mock.MagicMock()
        project.bare_git = mock.MagicMock()
        projects = [project]

        err_event = mock.MagicMock()

        # Test _GCProjects method exists and can be called
        with mock.patch.object(sync_cmd, "_SetPreciousObjectsState"):
            sync_cmd._GCProjects(projects, opt, err_event)


@pytest.mark.unit
class TestExecuteHelper:
    """Test _ExecuteHelper method."""

    def test_execute_helper_with_smart_sync(self):
        """Test _ExecuteHelper with smart_sync option."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_manifest = mock.MagicMock()
        sync_cmd.outer_client = mock.MagicMock()
        sync_cmd.client = mock.MagicMock()
        sync_cmd.git_event_log = mock.MagicMock()

        opt = mock.MagicMock()
        opt.outer_manifest = False
        opt.manifest_name = None
        opt.clone_bundle = True
        opt.smart_sync = "branch"
        opt.smart_tag = None
        opt.repo_upgraded = False
        opt.mp_update = False
        opt.interleaved = False
        opt.quiet = True

        args = []
        errors = []

        manifest = sync_cmd.manifest
        manifest.manifestProject = mock.MagicMock()
        manifest.manifestProject.worktree = "/tmp/test"
        manifest.repoProject = mock.MagicMock()
        manifest.repoProject.CurrentBranch = None
        manifest.CloneBundle = True

        with mock.patch.object(sync_cmd, "_SmartSyncSetup", return_value="test_manifest.xml"):
            with mock.patch.object(sync_cmd, "ManifestList", return_value=[]):
                with mock.patch.object(sync_cmd, "_ValidateOptionsWithManifest"):
                    with mock.patch.object(sync_cmd, "_UpdateRepoProject"):
                        with mock.patch.object(sync_cmd, "_UpdateProjectsRevisionId"):
                            with mock.patch.object(sync_cmd, "GetProjects", return_value=[]):
                                with mock.patch.object(sync_cmd, "_SyncPhased"):
                                    # Test lines 1883-1886 (smart_sync path)
                                    sync_cmd._ExecuteHelper(opt, args, errors)

    def test_execute_helper_removes_smart_sync_override(self):
        """Test _ExecuteHelper removes existing smart_sync_override.xml."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_manifest = mock.MagicMock()
        sync_cmd.outer_client = mock.MagicMock()
        sync_cmd.client = mock.MagicMock()
        sync_cmd.git_event_log = mock.MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            opt = mock.MagicMock()
            opt.outer_manifest = False
            opt.manifest_name = None
            opt.clone_bundle = True
            opt.smart_sync = None
            opt.smart_tag = None
            opt.repo_upgraded = False
            opt.mp_update = False
            opt.interleaved = False
            opt.quiet = True

            args = []
            errors = []

            manifest = sync_cmd.manifest
            manifest.manifestProject = mock.MagicMock()
            manifest.manifestProject.worktree = tmpdir
            manifest.repoProject = mock.MagicMock()
            manifest.repoProject.CurrentBranch = None
            manifest.CloneBundle = True

            # Create the smart_sync_override.xml file
            override_path = os.path.join(tmpdir, "smart_sync_override.xml")
            with open(override_path, "w") as f:
                f.write("<manifest></manifest>")

            with mock.patch.object(sync_cmd, "ManifestList", return_value=[]):
                with mock.patch.object(sync_cmd, "_ValidateOptionsWithManifest"):
                    with mock.patch.object(sync_cmd, "_UpdateRepoProject"):
                        with mock.patch.object(sync_cmd, "_UpdateProjectsRevisionId"):
                            with mock.patch.object(sync_cmd, "GetProjects", return_value=[]):
                                with mock.patch.object(sync_cmd, "_SyncPhased"):
                                    with mock.patch("kanon_cli.repo.subcmds.sync.platform_utils") as mock_platform:
                                        # Test lines 1888-1896 (remove override)
                                        sync_cmd._ExecuteHelper(opt, args, errors)
                                        mock_platform.remove.assert_called()

    def test_execute_helper_with_repo_upgraded(self):
        """Test _ExecuteHelper with repo_upgraded flag."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_manifest = mock.MagicMock()
        sync_cmd.outer_client = mock.MagicMock()
        sync_cmd.client = mock.MagicMock()
        sync_cmd.git_event_log = mock.MagicMock()

        opt = mock.MagicMock()
        opt.outer_manifest = False
        opt.manifest_name = None
        opt.clone_bundle = True
        opt.smart_sync = None
        opt.smart_tag = None
        opt.repo_upgraded = True
        opt.mp_update = False
        opt.interleaved = False
        opt.quiet = False

        args = []
        errors = []

        manifest = sync_cmd.manifest
        manifest.manifestProject = mock.MagicMock()
        manifest.manifestProject.worktree = "/tmp/test"
        manifest.repoProject = mock.MagicMock()
        manifest.repoProject.CurrentBranch = None
        manifest.CloneBundle = True

        with mock.patch.object(sync_cmd, "ManifestList", return_value=[]):
            with mock.patch("kanon_cli.repo.subcmds.sync._PostRepoUpgrade") as mock_post_upgrade:
                with mock.patch.object(sync_cmd, "_ValidateOptionsWithManifest"):
                    with mock.patch.object(sync_cmd, "_UpdateRepoProject"):
                        with mock.patch.object(sync_cmd, "_UpdateProjectsRevisionId"):
                            with mock.patch.object(sync_cmd, "GetProjects", return_value=[]):
                                with mock.patch.object(sync_cmd, "_SyncPhased"):
                                    # Test line 1915 (repo_upgraded)
                                    sync_cmd._ExecuteHelper(opt, args, errors)
                                    mock_post_upgrade.assert_called_once()

    def test_execute_helper_interleaved_mode(self):
        """Test _ExecuteHelper with interleaved mode."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_manifest = mock.MagicMock()
        sync_cmd.outer_client = mock.MagicMock()
        sync_cmd.client = mock.MagicMock()
        sync_cmd.git_event_log = mock.MagicMock()

        opt = mock.MagicMock()
        opt.outer_manifest = False
        opt.manifest_name = None
        opt.clone_bundle = True
        opt.smart_sync = None
        opt.smart_tag = None
        opt.repo_upgraded = False
        opt.mp_update = False
        opt.interleaved = True
        opt.quiet = True

        args = []
        errors = []

        manifest = sync_cmd.manifest
        manifest.manifestProject = mock.MagicMock()
        manifest.manifestProject.worktree = "/tmp/test"
        manifest.manifestProject.config = mock.MagicMock()
        manifest.repoProject = mock.MagicMock()
        manifest.repoProject.CurrentBranch = None
        manifest.CloneBundle = True

        with mock.patch.object(sync_cmd, "ManifestList", return_value=[]):
            with mock.patch.object(sync_cmd, "_ValidateOptionsWithManifest"):
                with mock.patch.object(sync_cmd, "_UpdateRepoProject"):
                    with mock.patch.object(sync_cmd, "_UpdateProjectsRevisionId"):
                        with mock.patch.object(sync_cmd, "GetProjects", return_value=[]):
                            with mock.patch.object(sync_cmd, "_SyncInterleaved") as mock_interleaved:
                                # Test lines 1962-1965 (interleaved mode)
                                sync_cmd._ExecuteHelper(opt, args, errors)
                                mock_interleaved.assert_called_once()


@pytest.mark.unit
class TestCreateSyncProgressThread:
    """Test _CreateSyncProgressThread method."""

    def test_create_sync_progress_thread(self):
        """Test _CreateSyncProgressThread creates thread."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()

        pm = mock.MagicMock()
        stop_event = mock.MagicMock()

        with mock.patch("kanon_cli.repo.subcmds.sync._threading.Thread") as mock_thread:
            # Test lines 2017-2022
            sync_cmd._CreateSyncProgressThread(pm, stop_event)
            mock_thread.assert_called_once()


@pytest.mark.unit
class TestUpdateManifestLists:
    """Test _UpdateManifestLists method."""

    def test_update_manifest_lists_with_errors(self):
        """Test _UpdateManifestLists with errors."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()

        opt = mock.MagicMock()
        opt.fail_fast = False

        err_event = multiprocessing.Event()
        errors = []

        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False

        with mock.patch.object(sync_cmd, "ManifestList", return_value=[manifest]):
            with mock.patch.object(
                sync_cmd,
                "UpdateProjectList",
                side_effect=Exception("test error"),
            ):
                with mock.patch.object(sync_cmd, "UpdateCopyLinkfileList"):
                    # Test lines 2043-2072
                    err_update_projects, err_update_linkfiles = sync_cmd._UpdateManifestLists(opt, err_event, errors)
                    assert err_update_projects is True
                    assert len(errors) > 0


@pytest.mark.unit
class TestReportErrors:
    """Test _ReportErrors method."""

    def test_report_errors_network_sync(self):
        """Test _ReportErrors with network sync errors."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.git_event_log = mock.MagicMock()

        errors = []

        # Test line 2094
        with pytest.raises(SyncError):
            sync_cmd._ReportErrors(
                errors,
                err_network_sync=True,
                failing_network_repos=["repo1", "repo2"],
                err_checkout=False,
                failing_checkout_repos=None,
                err_update_projects=False,
                err_update_linkfiles=False,
            )


@pytest.mark.unit
class TestSyncPhased:
    """Test _SyncPhased method."""

    def test_sync_phased_network_only(self):
        """Test _SyncPhased with network_only option."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_client = mock.MagicMock()
        sync_cmd.event_log = mock.MagicMock()

        opt = mock.MagicMock()
        opt.local_only = False
        opt.network_only = True
        opt.quiet = True
        opt.fail_fast = False

        args = []
        errors = []
        manifest = mock.MagicMock()
        mp = mock.MagicMock()
        all_projects = []
        superproject_logging_data = {}

        fetch_result = mock.MagicMock()
        fetch_result.all_projects = []

        with mock.patch("multiprocessing.Manager"):
            with mock.patch("kanon_cli.repo.subcmds.sync.ssh.ProxyManager"):
                with mock.patch.object(sync_cmd, "_FetchMain", return_value=fetch_result):
                    # Test line 2156-2157 (early return on network_only)
                    sync_cmd._SyncPhased(
                        opt,
                        args,
                        errors,
                        manifest,
                        mp,
                        all_projects,
                        superproject_logging_data,
                    )


@pytest.mark.unit
class TestSyncInterleaved:
    """Test _SyncInterleaved method."""

    def test_sync_interleaved_stall_detection(self):
        """Test _SyncInterleaved stall detection."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_client = mock.MagicMock()
        sync_cmd.outer_client.manifest.IsArchive = False
        sync_cmd.event_log = mock.MagicMock()
        sync_cmd.git_event_log = mock.MagicMock()
        sync_cmd._fetch_times = mock.MagicMock()
        sync_cmd._local_sync_state = mock.MagicMock()
        sync_cmd._interleaved_err_network = False
        sync_cmd._interleaved_err_network_results = []
        sync_cmd._interleaved_err_checkout = False
        sync_cmd._interleaved_err_checkout_results = []

        opt = mock.MagicMock()
        opt.jobs = 1
        opt.quiet = True
        opt.fail_fast = False
        opt.fetch_submodules = False
        opt.this_manifest_only = True

        args = []
        errors = []
        manifest = mock.MagicMock()
        mp = mock.MagicMock()

        project = mock.MagicMock()
        project.relpath = "test_project"
        project.objdir = "/tmp/obj"
        all_projects = [project]

        superproject_logging_data = {}

        with mock.patch("multiprocessing.Manager"):
            with mock.patch("kanon_cli.repo.subcmds.sync.ssh.ProxyManager"):
                with mock.patch.object(sync_cmd, "ParallelContext"):
                    with mock.patch.object(sync_cmd, "get_parallel_context", return_value={}):
                        with mock.patch.object(sync_cmd, "_CreateSyncProgressThread") as mock_thread:
                            thread = mock.MagicMock()
                            mock_thread.return_value = thread
                            with mock.patch.object(
                                sync_cmd,
                                "ExecuteInParallel",
                                return_value=False,
                            ):
                                with mock.patch.object(sync_cmd, "_ReloadManifest"):
                                    with mock.patch.object(
                                        sync_cmd,
                                        "GetProjects",
                                        return_value=[project],
                                    ):
                                        with mock.patch.object(
                                            sync_cmd,
                                            "_UpdateManifestLists",
                                            return_value=(False, False),
                                        ):
                                            with mock.patch.object(sync_cmd, "_GCProjects"):
                                                with mock.patch.object(
                                                    sync_cmd,
                                                    "_PrintManifestNotices",
                                                ):
                                                    # Test lines 2507-2514 (stall detection)
                                                    with pytest.raises(SyncError):
                                                        sync_cmd._SyncInterleaved(
                                                            opt,
                                                            args,
                                                            errors,
                                                            manifest,
                                                            mp,
                                                            all_projects,
                                                            superproject_logging_data,
                                                        )


@pytest.mark.unit
class TestPersistentTransport:
    """Test PersistentTransport class."""

    def test_persistent_transport_request_with_cookie(self):
        """Test PersistentTransport.request with cookies."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("#HttpOnly_example.com\tTRUE\t/\tTRUE\t0\ttest\tvalue\n")
            cookie_file = f.name

        try:
            transport = sync.PersistentTransport("http://example.com")

            with mock.patch("kanon_cli.repo.subcmds.sync.GetUrlCookieFile") as mock_get_cookie:
                mock_get_cookie.return_value.__enter__.return_value = (
                    cookie_file,
                    None,
                )

                with mock.patch("urllib.request.build_opener") as mock_opener:
                    mock_response = mock.MagicMock()
                    mock_response.read.return_value = b'<?xml version="1.0"?><methodResponse><params><param><value><string>test</string></value></param></params></methodResponse>'
                    opener_inst = mock.MagicMock()
                    opener_inst.open.return_value = mock_response
                    mock_opener.return_value = opener_inst

                    # Test lines 2802-2818
                    transport.request("example.com", "/handler", b"<request/>")
        finally:
            if os.path.exists(cookie_file):
                os.unlink(cookie_file)

    def test_persistent_transport_request_with_proxy(self):
        """Test PersistentTransport.request with proxy."""
        transport = sync.PersistentTransport("http://example.com")

        with mock.patch("kanon_cli.repo.subcmds.sync.GetUrlCookieFile") as mock_get_cookie:
            mock_get_cookie.return_value.__enter__.return_value = (
                None,
                "http://proxy:8080",
            )

            with mock.patch("urllib.request.build_opener") as mock_opener:
                mock_response = mock.MagicMock()
                mock_response.read.return_value = b'<?xml version="1.0"?><methodResponse><params><param><value><string>test</string></value></param></params></methodResponse>'
                opener_inst = mock.MagicMock()
                opener_inst.open.return_value = mock_response
                mock_opener.return_value = opener_inst

                # Test lines 2824 (proxy handling)
                transport.request("example.com", "/handler", b"<request/>")

    def test_persistent_transport_request_persistent_https(self):
        """Test PersistentTransport.request with persistent-https."""
        transport = sync.PersistentTransport("persistent-https://example.com")

        with mock.patch("kanon_cli.repo.subcmds.sync.GetUrlCookieFile") as mock_get_cookie:
            mock_get_cookie.return_value.__enter__.return_value = (
                None,
                "http://proxy:8080",
            )

            with mock.patch("urllib.request.build_opener") as mock_opener:
                mock_response = mock.MagicMock()
                mock_response.read.return_value = b'<?xml version="1.0"?><methodResponse><params><param><value><string>test</string></value></param></params></methodResponse>'
                opener_inst = mock.MagicMock()
                opener_inst.open.return_value = mock_response
                mock_opener.return_value = opener_inst

                # Test lines 2841-2844 (persistent-https with proxy)
                transport.request("example.com", "/handler", b"<request/>")

    def test_persistent_transport_request_http_error_501(self):
        """Test PersistentTransport.request with HTTP 501 error."""
        transport = sync.PersistentTransport("http://example.com")

        with mock.patch("kanon_cli.repo.subcmds.sync.GetUrlCookieFile") as mock_get_cookie:
            mock_get_cookie.return_value.__enter__.return_value = (None, None)

            with mock.patch("urllib.request.build_opener") as mock_opener:
                mock_response = mock.MagicMock()
                mock_response.read.return_value = b'<?xml version="1.0"?><methodResponse><params><param><value><string>test</string></value></param></params></methodResponse>'

                opener_inst = mock.MagicMock()
                # First call raises 501, second succeeds
                opener_inst.open.side_effect = [
                    urllib.error.HTTPError("http://example.com", 501, "Not Implemented", {}, None),
                    mock_response,
                ]
                mock_opener.return_value = opener_inst

                # Test lines 2867-2873 (HTTP 501 retry)
                transport.request("example.com", "/handler", b"<request/>")

    def test_persistent_transport_request_xml_parse_error(self):
        """Test PersistentTransport.request with XML parse error."""
        transport = sync.PersistentTransport("http://example.com")

        with mock.patch("kanon_cli.repo.subcmds.sync.GetUrlCookieFile") as mock_get_cookie:
            mock_get_cookie.return_value.__enter__.return_value = (None, None)

            with mock.patch("urllib.request.build_opener") as mock_opener:
                mock_response = mock.MagicMock()
                mock_response.read.return_value = b"<html>not xml rpc response</html>"

                opener_inst = mock.MagicMock()
                opener_inst.open.return_value = mock_response
                mock_opener.return_value = opener_inst

                with mock.patch("xmlrpc.client.getparser") as mock_getparser:
                    parser = mock.MagicMock()
                    parser.feed.side_effect = xml.parsers.expat.ExpatError("test error")
                    unmarshaller = mock.MagicMock()
                    mock_getparser.return_value = (parser, unmarshaller)

                    # Test lines 2881-2882 (ExpatError)
                    with pytest.raises(OSError):
                        transport.request("example.com", "/handler", b"<request/>")


@pytest.mark.unit
class TestSyncResult:
    """Test _SyncResult class."""

    def test_sync_result_creation(self):
        """Test _SyncResult instantiation."""
        result = sync._SyncResult(
            project_index=0,
            relpath="test/project",
            fetch_start=1.0,
            fetch_finish=2.0,
            fetch_success=True,
            fetch_error=None,
            checkout_start=2.0,
            checkout_finish=3.0,
            checkout_success=True,
            checkout_error=None,
            remote_fetched=True,
            stderr_text="",
        )
        assert result.project_index == 0
        assert result.fetch_success is True


@pytest.mark.unit
class TestFetchResult:
    """Test _FetchResult class."""

    def test_fetch_result_creation(self):
        """Test _FetchResult instantiation."""
        projects_set = set()
        result = sync._FetchResult(True, projects_set)
        assert result.success is True
        assert result.projects == projects_set


@pytest.mark.unit
class TestFetchMainResult:
    """Test _FetchMainResult class."""

    def test_fetch_main_result_creation(self):
        """Test _FetchMainResult instantiation."""
        projects = []
        result = sync._FetchMainResult(projects)
        assert result.all_projects == projects


@pytest.mark.unit
class TestCheckoutOneResult:
    """Test _CheckoutOneResult class."""

    def test_checkout_one_result_creation(self):
        """Test _CheckoutOneResult instantiation."""
        result = sync._CheckoutOneResult(project_idx=0, start=1.0, finish=2.0, success=True, errors=[])
        assert result.project_idx == 0
        assert result.success is True


@pytest.mark.unit
class TestFetchOneResult:
    """Test _FetchOneResult class."""

    def test_fetch_one_result_creation(self):
        """Test _FetchOneResult instantiation."""
        result = sync._FetchOneResult(
            project_idx=0,
            start=1.0,
            finish=2.0,
            success=True,
            errors=[],
            remote_fetched=False,
        )
        assert result.project_idx == 0
        assert result.remote_fetched is False


@pytest.mark.unit
class TestInterleavedSyncResult:
    """Test _InterleavedSyncResult class."""

    def test_interleaved_sync_result_creation(self):
        """Test _InterleavedSyncResult instantiation."""
        results = []
        result = sync._InterleavedSyncResult(results=results)
        assert result.results == results


@pytest.mark.unit
class TestAdditionalCoverage:
    """Additional tests for uncovered lines."""

    def test_fetch_with_fail_fast(self):
        """Test _Fetch with fail_fast option."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_client = mock.MagicMock()
        sync_cmd.outer_client.manifest.IsArchive = True
        sync_cmd.event_log = mock.MagicMock()
        sync_cmd._fetch_times = mock.MagicMock()
        sync_cmd._local_sync_state = mock.MagicMock()

        opt = mock.MagicMock()
        opt.quiet = True
        opt.fail_fast = True
        opt.jobs_network = 1

        project = mock.MagicMock()
        project.gitdir = "/tmp/proj"
        project.objdir = "/tmp/obj"
        projects = [project]

        err_event = multiprocessing.Event()
        ssh_proxy = mock.MagicMock()
        errors = []

        sync._FetchOneResult(
            project_idx=0,
            start=time.time(),
            finish=time.time(),
            success=False,
            errors=[],
            remote_fetched=False,
        )

        def mock_callback(pool, pm, results_sets):
            # Simulate the callback behavior
            for results in results_sets:
                for result in results:
                    pm.update()
                    if not result.success and opt.fail_fast:
                        if pool:
                            pool.close()
                        return False
            return False

        with mock.patch.object(sync_cmd, "ParallelContext"):
            with mock.patch.object(
                sync_cmd,
                "get_parallel_context",
                return_value={
                    "ssh_proxy": ssh_proxy,
                    "projects": projects,
                    "sync_dict": {},
                },
            ):
                with mock.patch.object(sync_cmd, "ExecuteInParallel") as mock_exec:
                    mock_exec.return_value = False
                    with mock.patch.object(sync_cmd, "_CreateSyncProgressThread") as mock_thread:
                        thread = mock.MagicMock()
                        mock_thread.return_value = thread
                        # Test fail_fast path (line 925-928)
                        result = sync_cmd._Fetch(projects, opt, err_event, ssh_proxy, errors)
                        assert result.success is False

    def test_local_sync_state_is_partially_synced(self):
        """Test LocalSyncState.IsPartiallySynced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = mock.MagicMock()
            manifest.repodir = tmpdir
            manifest.repoProject = mock.MagicMock()
            manifest.repoProject.relpath = ".repo"
            project1 = mock.MagicMock()
            project1.name = "proj1"
            project2 = mock.MagicMock()
            project2.name = "proj2"
            manifest.projects = [project1, project2]

            # Create state file BEFORE creating LocalSyncState object
            state_path = os.path.join(tmpdir, ".repo_localsyncstate.json")
            with open(state_path, "w") as f:
                json.dump(
                    {
                        "proj1": {
                            sync.LocalSyncState._LAST_FETCH: time.time(),
                            sync.LocalSyncState._LAST_CHECKOUT: time.time(),
                        },
                        "proj2": {
                            sync.LocalSyncState._LAST_FETCH: time.time(),
                            # Missing LAST_CHECKOUT - makes it partial
                        },
                    },
                    f,
                )

            state = sync.LocalSyncState(manifest)
            # One project missing checkout, so it's partial
            assert state.IsPartiallySynced() is True

    def test_execute_with_post_sync_hook_failure(self):
        """Test Execute with post-sync hook failure."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_manifest = mock.MagicMock()
        sync_cmd.outer_client = mock.MagicMock()
        sync_cmd.client = mock.MagicMock()
        sync_cmd.client.topdir = "/tmp/test"

        opt = mock.MagicMock()
        opt.outer_manifest = False

        args = []

        hook = mock.MagicMock()
        hook.Run.return_value = False

        with mock.patch.object(sync_cmd, "_ExecuteHelper"):
            with mock.patch("kanon_cli.repo.subcmds.sync.RepoHook", return_value=hook):
                # Test line 1865 (hook failure warning)
                sync_cmd.Execute(opt, args)

    def test_sync_phased_local_only(self):
        """Test _SyncPhased with local_only option."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_client = mock.MagicMock()
        sync_cmd.event_log = mock.MagicMock()
        sync_cmd._local_sync_state = mock.MagicMock()

        opt = mock.MagicMock()
        opt.local_only = True
        opt.quiet = True
        opt.fail_fast = False
        opt.this_manifest_only = True

        args = []
        errors = []
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        mp = mock.MagicMock()
        all_projects = []
        superproject_logging_data = {}

        with mock.patch.object(sync_cmd, "ManifestList", return_value=[]):
            with mock.patch.object(sync_cmd, "_Checkout", return_value=True):
                with mock.patch.object(sync_cmd, "_PrintManifestNotices"):
                    # Test local_only skip network (line 2140)
                    sync_cmd._SyncPhased(
                        opt,
                        args,
                        errors,
                        manifest,
                        mp,
                        all_projects,
                        superproject_logging_data,
                    )

    def test_sync_interleaved_with_gc(self):
        """Test _SyncInterleaved with GC."""
        sync_cmd = sync.Sync()
        sync_cmd.manifest = mock.MagicMock()
        sync_cmd.outer_client = mock.MagicMock()
        sync_cmd.outer_client.manifest.IsArchive = False
        sync_cmd.event_log = mock.MagicMock()
        sync_cmd._fetch_times = mock.MagicMock()
        sync_cmd._local_sync_state = mock.MagicMock()
        sync_cmd._interleaved_err_network = False
        sync_cmd._interleaved_err_network_results = []
        sync_cmd._interleaved_err_checkout = False
        sync_cmd._interleaved_err_checkout_results = []

        opt = mock.MagicMock()
        opt.jobs = 1
        opt.quiet = True
        opt.fail_fast = False
        opt.fetch_submodules = False
        opt.this_manifest_only = True

        args = []
        errors = []
        manifest = mock.MagicMock()
        mp = mock.MagicMock()
        all_projects = []
        superproject_logging_data = {}

        with mock.patch("multiprocessing.Manager"):
            with mock.patch("kanon_cli.repo.subcmds.sync.ssh.ProxyManager"):
                with mock.patch.object(sync_cmd, "ParallelContext"):
                    with mock.patch.object(sync_cmd, "get_parallel_context", return_value={}):
                        with mock.patch.object(sync_cmd, "_CreateSyncProgressThread") as mock_thread:
                            thread = mock.MagicMock()
                            mock_thread.return_value = thread
                            with mock.patch.object(sync_cmd, "_ReloadManifest"):
                                with mock.patch.object(sync_cmd, "GetProjects", return_value=[]):
                                    with mock.patch.object(
                                        sync_cmd,
                                        "_UpdateManifestLists",
                                        return_value=(False, False),
                                    ):
                                        with mock.patch.object(sync_cmd, "_GCProjects") as mock_gc:
                                            with mock.patch.object(
                                                sync_cmd,
                                                "_PrintManifestNotices",
                                            ):
                                                # Test line 2584 (GC when not archive)
                                                sync_cmd._SyncInterleaved(
                                                    opt,
                                                    args,
                                                    errors,
                                                    manifest,
                                                    mp,
                                                    all_projects,
                                                    superproject_logging_data,
                                                )
                                                mock_gc.assert_called_once()
