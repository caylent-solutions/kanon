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

"""Deep unit tests for the subcmds/sync.py module to increase coverage."""

import io
import json
import multiprocessing
import os
import time
from unittest import mock

import pytest

from kanon_cli.repo.error import GitError
from kanon_cli.repo.error import SyncError
from kanon_cli.repo.project import Project
from kanon_cli.repo.project import SyncNetworkHalfResult
from kanon_cli.repo.subcmds import sync


def _make_sync_cmd():
    """Create a Sync command object with mocked dependencies."""
    cmd = sync.Sync.__new__(sync.Sync)
    cmd.manifest = mock.MagicMock()
    cmd.manifest.topdir = "/tmp/test"
    cmd.manifest.repodir = "/tmp/test/.repo"
    cmd.manifest.projects = []
    cmd.manifest.IsArchive = False
    cmd.manifest.IsMirror = False
    cmd.manifest.CloneFilter = None
    cmd.manifest.PartialCloneExclude = set()
    cmd.manifest.CloneFilterForDepth = None
    cmd.jobs = 1
    cmd.jobs_net = 1
    cmd.jobs_checkout = 1
    cmd.outer_client = mock.MagicMock()
    cmd.outer_manifest = mock.MagicMock()
    cmd.event_log = mock.MagicMock()
    cmd._fetch_times = mock.MagicMock()
    cmd._fetch_times.Get.return_value = 0.0
    cmd._local_sync_state = mock.MagicMock()
    cmd.git_event_log = mock.MagicMock()
    return cmd


def _make_project(name="test_project", relpath="test"):
    """Create a mock Project object."""
    proj = mock.MagicMock(spec=Project)
    proj.name = name
    proj.relpath = relpath
    proj.gitdir = f"/tmp/test/.repo/projects/{relpath}.git"
    proj.objdir = f"/tmp/test/.repo/project-objects/{name}.git"
    proj.worktree = f"/tmp/test/{relpath}"
    proj.remote = mock.MagicMock()
    proj.remote.url = f"https://example.com/{name}"
    proj.manifest = mock.MagicMock()
    proj.manifest.manifestProject = mock.MagicMock()
    proj.manifest.manifestProject.config = mock.MagicMock()
    proj.manifest.IsArchive = False
    proj.manifest.CloneFilter = None
    proj.manifest.PartialCloneExclude = set()
    proj.manifest.CloneFilterForDepth = None
    proj.config = mock.MagicMock()
    proj.use_git_worktrees = False
    proj.UseAlternates = False
    return proj


@pytest.mark.unit
def test_fetch_one_result_namedtuple():
    """Test _FetchOneResult named tuple structure."""
    result = sync._FetchOneResult(
        success=True,
        errors=[],
        project_idx=0,
        start=1.0,
        finish=2.0,
        remote_fetched=True,
    )
    assert result.success is True
    assert result.errors == []
    assert result.project_idx == 0
    assert result.start == 1.0
    assert result.finish == 2.0
    assert result.remote_fetched is True


@pytest.mark.unit
def test_fetch_result_namedtuple():
    """Test _FetchResult named tuple structure."""
    projects = {"proj1", "proj2"}
    result = sync._FetchResult(success=True, projects=projects)
    assert result.success is True
    assert result.projects == projects


@pytest.mark.unit
def test_fetch_main_result_namedtuple():
    """Test _FetchMainResult named tuple structure."""
    projects = [_make_project("p1"), _make_project("p2")]
    result = sync._FetchMainResult(all_projects=projects)
    assert len(result.all_projects) == 2


@pytest.mark.unit
def test_checkout_one_result_namedtuple():
    """Test _CheckoutOneResult named tuple structure."""
    result = sync._CheckoutOneResult(
        success=True,
        errors=[],
        project_idx=5,
        start=10.0,
        finish=15.0,
    )
    assert result.success is True
    assert result.errors == []
    assert result.project_idx == 5


@pytest.mark.unit
def test_sync_result_namedtuple():
    """Test _SyncResult named tuple with all fields."""
    result = sync._SyncResult(
        project_index=0,
        relpath="test/path",
        remote_fetched=True,
        fetch_success=True,
        fetch_error=None,
        fetch_start=1.0,
        fetch_finish=2.0,
        checkout_success=True,
        checkout_error=None,
        checkout_start=3.0,
        checkout_finish=4.0,
        stderr_text="output",
    )
    assert result.project_index == 0
    assert result.relpath == "test/path"
    assert result.fetch_success is True
    assert result.checkout_success is True


@pytest.mark.unit
def test_interleaved_sync_result_namedtuple():
    """Test _InterleavedSyncResult named tuple."""
    sync_results = []
    result = sync._InterleavedSyncResult(results=sync_results)
    assert result.results == []


@pytest.mark.unit
def test_superproject_error_exception():
    """Test SuperprojectError exception class."""
    err = sync.SuperprojectError("test error")
    assert isinstance(err, SyncError)
    assert str(err) == "test error"


@pytest.mark.unit
def test_sync_fail_fast_error_exception():
    """Test SyncFailFastError exception class."""
    err = sync.SyncFailFastError("fail fast")
    assert isinstance(err, SyncError)
    assert str(err) == "fail fast"


@pytest.mark.unit
def test_smart_sync_error_exception():
    """Test SmartSyncError exception class."""
    err = sync.SmartSyncError("smart sync error")
    assert isinstance(err, SyncError)
    assert str(err) == "smart sync error"


@pytest.mark.unit
def test_manifest_interrupt_error():
    """Test ManifestInterruptError with output."""
    from kanon_cli.repo.error import RepoError

    err = sync.ManifestInterruptError("interrupt output")
    assert isinstance(err, RepoError)
    assert err.output == "interrupt output"
    assert "ManifestInterruptError:interrupt output" in str(err)


@pytest.mark.unit
def test_tee_string_io_write_without_io():
    """Test TeeStringIO write without additional IO destination."""
    tee = sync.TeeStringIO(None)
    written = tee.write("test content")
    assert written == len("test content")
    assert tee.getvalue() == "test content"


@pytest.mark.unit
def test_tee_string_io_write_with_io():
    """Test TeeStringIO write with additional IO destination."""
    dest = io.StringIO()
    tee = sync.TeeStringIO(dest)
    tee.write("hello ")
    tee.write("world")
    assert tee.getvalue() == "hello world"
    assert dest.getvalue() == "hello world"


@pytest.mark.unit
def test_get_branch_extracts_branch_name():
    """Test _GetBranch extracts branch name from R_HEADS."""
    cmd = _make_sync_cmd()
    manifest_project = mock.MagicMock()
    branch_obj = mock.MagicMock()
    branch_obj.merge = "refs/heads/main"
    manifest_project.GetBranch.return_value = branch_obj
    manifest_project.CurrentBranch = "main"

    result = cmd._GetBranch(manifest_project)
    assert result == "main"


@pytest.mark.unit
def test_get_branch_returns_full_ref_when_not_heads():
    """Test _GetBranch returns full ref when not in refs/heads/."""
    cmd = _make_sync_cmd()
    manifest_project = mock.MagicMock()
    branch_obj = mock.MagicMock()
    branch_obj.merge = "refs/tags/v1.0"
    manifest_project.GetBranch.return_value = branch_obj
    manifest_project.CurrentBranch = "main"

    result = cmd._GetBranch(manifest_project)
    assert result == "refs/tags/v1.0"


@pytest.mark.unit
def test_get_current_branch_only_with_superproject():
    """Test _GetCurrentBranchOnly returns True when superproject is used."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.use_superproject = True
    opt.current_branch_only = False
    manifest = mock.MagicMock()

    with mock.patch("kanon_cli.repo.subcmds.sync.git_superproject.UseSuperproject", return_value=True):
        result = cmd._GetCurrentBranchOnly(opt, manifest)
        assert result is True


@pytest.mark.unit
def test_get_current_branch_only_without_superproject():
    """Test _GetCurrentBranchOnly returns option value when no superproject."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.use_superproject = False
    opt.current_branch_only = True
    manifest = mock.MagicMock()

    with mock.patch("kanon_cli.repo.subcmds.sync.git_superproject.UseSuperproject", return_value=False):
        result = cmd._GetCurrentBranchOnly(opt, manifest)
        assert result is True


@pytest.mark.unit
def test_reload_manifest_with_name():
    """Test _ReloadManifest with manifest name calls Override."""
    cmd = _make_sync_cmd()
    manifest = mock.MagicMock()

    cmd._ReloadManifest("new_manifest.xml", manifest)
    manifest.Override.assert_called_once_with("new_manifest.xml")
    manifest.Unload.assert_not_called()


@pytest.mark.unit
def test_reload_manifest_without_name():
    """Test _ReloadManifest without name calls Unload."""
    cmd = _make_sync_cmd()
    manifest = mock.MagicMock()

    cmd._ReloadManifest(None, manifest)
    manifest.Unload.assert_called_once()
    manifest.Override.assert_not_called()


@pytest.mark.unit
def test_get_precious_objects_state_with_git_worktrees():
    """Test _GetPreciousObjectsState returns False for git worktrees."""
    project = _make_project()
    project.use_git_worktrees = True
    opt = mock.MagicMock()

    result = sync.Sync._GetPreciousObjectsState(project, opt)
    assert result is False


@pytest.mark.unit
def test_get_precious_objects_state_single_project():
    """Test _GetPreciousObjectsState returns False for single project."""
    project = _make_project("single")
    project.use_git_worktrees = False
    project.manifest.GetProjectsWithName.return_value = [project]
    opt = mock.MagicMock()

    result = sync.Sync._GetPreciousObjectsState(project, opt)
    assert result is False


@pytest.mark.unit
def test_get_precious_objects_state_multiple_projects_no_alternates():
    """Test _GetPreciousObjectsState returns True for shared projects without alternates."""
    project = _make_project("shared")
    project.use_git_worktrees = False
    project.UseAlternates = False
    project2 = _make_project("shared")
    project.manifest.GetProjectsWithName.return_value = [project, project2]
    opt = mock.MagicMock()

    result = sync.Sync._GetPreciousObjectsState(project, opt)
    assert result is True


@pytest.mark.unit
def test_get_precious_objects_state_multiple_projects_with_alternates():
    """Test _GetPreciousObjectsState returns False with alternates."""
    project = _make_project("shared")
    project.use_git_worktrees = False
    project.UseAlternates = True
    project2 = _make_project("shared")
    project.manifest.GetProjectsWithName.return_value = [project, project2]
    opt = mock.MagicMock()

    result = sync.Sync._GetPreciousObjectsState(project, opt)
    assert result is False


@pytest.mark.unit
def test_set_precious_objects_state_no_change_needed():
    """Test _SetPreciousObjectsState when state is already correct."""
    cmd = _make_sync_cmd()
    project = _make_project()
    project.config.GetBoolean.return_value = False
    project.RelPath.return_value = "test/path"
    opt = mock.MagicMock()
    opt.this_manifest_only = False
    opt.quiet = False

    with mock.patch.object(sync.Sync, "_GetPreciousObjectsState", return_value=False):
        cmd._SetPreciousObjectsState(project, opt)
        project.config.SetString.assert_not_called()


@pytest.mark.unit
def test_set_precious_objects_state_enable_precious_objects():
    """Test _SetPreciousObjectsState enables preciousObjects when needed."""
    cmd = _make_sync_cmd()
    project = _make_project()
    project.config.GetBoolean.return_value = False
    project.RelPath.return_value = "test/path"
    opt = mock.MagicMock()
    opt.this_manifest_only = False
    opt.quiet = True

    with mock.patch.object(sync.Sync, "_GetPreciousObjectsState", return_value=True):
        with mock.patch("kanon_cli.repo.subcmds.sync.git_require", return_value=True):
            cmd._SetPreciousObjectsState(project, opt)
            project.EnableRepositoryExtension.assert_called_once_with("preciousObjects")


@pytest.mark.unit
def test_set_precious_objects_state_enable_with_old_git():
    """Test _SetPreciousObjectsState with old git version sets gc.pruneExpire."""
    cmd = _make_sync_cmd()
    project = _make_project()
    project.config.GetBoolean.return_value = False
    project.RelPath.return_value = "test/path"
    opt = mock.MagicMock()
    opt.this_manifest_only = False
    opt.quiet = True

    with mock.patch.object(sync.Sync, "_GetPreciousObjectsState", return_value=True):
        with mock.patch("kanon_cli.repo.subcmds.sync.git_require", return_value=False):
            cmd._SetPreciousObjectsState(project, opt)
            project.config.SetString.assert_called_once_with("gc.pruneExpire", "never")


@pytest.mark.unit
def test_set_precious_objects_state_disable_precious_objects():
    """Test _SetPreciousObjectsState disables preciousObjects when needed."""
    cmd = _make_sync_cmd()
    project = _make_project()
    project.config.GetBoolean.return_value = True
    project.RelPath.return_value = "test/path"
    opt = mock.MagicMock()
    opt.this_manifest_only = False
    opt.quiet = True

    with mock.patch.object(sync.Sync, "_GetPreciousObjectsState", return_value=False):
        cmd._SetPreciousObjectsState(project, opt)
        calls = project.config.SetString.call_args_list
        assert len(calls) == 2
        assert calls[0][0] == ("extensions.preciousObjects", None)
        assert calls[1][0] == ("gc.pruneExpire", None)


@pytest.mark.unit
def test_fetch_project_list_calls_fetch_one():
    """Test _FetchProjectList delegates to _FetchOne for each project."""
    opt = mock.MagicMock()
    projects = [0, 1, 2]

    with mock.patch.object(sync.Sync, "_FetchOne") as mock_fetch:
        mock_fetch.return_value = sync._FetchOneResult(
            success=True,
            errors=[],
            project_idx=0,
            start=1.0,
            finish=2.0,
            remote_fetched=True,
        )
        result = sync.Sync._FetchProjectList(opt, projects)
        assert len(result) == 3
        assert mock_fetch.call_count == 3


@pytest.mark.unit
def test_checkout_one_success():
    """Test _CheckoutOne successful checkout."""
    project = _make_project()
    project.Sync_LocalHalf = mock.MagicMock()

    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {"projects": [project]}

        with mock.patch("kanon_cli.repo.subcmds.sync.SyncBuffer") as mock_buffer:
            buffer_instance = mock.MagicMock()
            buffer_instance.Finish.return_value = True
            mock_buffer.return_value = buffer_instance

            result = sync.Sync._CheckoutOne(
                detach_head=False,
                force_sync=False,
                force_checkout=False,
                force_rebase=False,
                verbose=False,
                project_idx=0,
            )

            assert result.success is True
            assert result.project_idx == 0
            assert len(result.errors) == 0


@pytest.mark.unit
def test_checkout_one_failure():
    """Test _CheckoutOne with checkout failure."""
    project = _make_project()
    project.Sync_LocalHalf = mock.MagicMock()

    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {"projects": [project]}

        with mock.patch("kanon_cli.repo.subcmds.sync.SyncBuffer") as mock_buffer:
            buffer_instance = mock.MagicMock()
            buffer_instance.Finish.return_value = False
            mock_buffer.return_value = buffer_instance

            result = sync.Sync._CheckoutOne(
                detach_head=False,
                force_sync=False,
                force_checkout=False,
                force_rebase=False,
                verbose=False,
                project_idx=0,
            )

            assert result.success is False


@pytest.mark.unit
def test_checkout_one_git_error():
    """Test _CheckoutOne handles GitError exception."""
    project = _make_project()
    git_err = GitError("git failed")
    project.Sync_LocalHalf = mock.MagicMock(side_effect=git_err)

    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {"projects": [project]}

        with mock.patch("kanon_cli.repo.subcmds.sync.SyncBuffer") as mock_buffer:
            buffer_instance = mock.MagicMock()
            mock_buffer.return_value = buffer_instance

            result = sync.Sync._CheckoutOne(
                detach_head=False,
                force_sync=False,
                force_checkout=False,
                force_rebase=False,
                verbose=False,
                project_idx=0,
            )

            assert result.success is False
            assert len(result.errors) == 1
            assert result.errors[0] == git_err


@pytest.mark.unit
def test_checkout_one_keyboard_interrupt():
    """Test _CheckoutOne handles KeyboardInterrupt."""
    project = _make_project()
    project.Sync_LocalHalf = mock.MagicMock(side_effect=KeyboardInterrupt())

    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {"projects": [project]}

        with mock.patch("kanon_cli.repo.subcmds.sync.SyncBuffer") as mock_buffer:
            buffer_instance = mock.MagicMock()
            mock_buffer.return_value = buffer_instance

            result = sync.Sync._CheckoutOne(
                detach_head=False,
                force_sync=False,
                force_checkout=False,
                force_rebase=False,
                verbose=False,
                project_idx=0,
            )

            assert result.success is False


@pytest.mark.unit
def test_print_manifest_notices_no_duplicates():
    """Test _PrintManifestNotices prints each unique notice once."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()

    manifest1 = mock.MagicMock()
    manifest1.notice = "Notice 1"
    manifest1.path_prefix = "a"

    manifest2 = mock.MagicMock()
    manifest2.notice = "Notice 1"  # Duplicate
    manifest2.path_prefix = "b"

    manifest3 = mock.MagicMock()
    manifest3.notice = "Notice 2"
    manifest3.path_prefix = "c"

    with mock.patch.object(cmd, "ManifestList", return_value=[manifest1, manifest2, manifest3]):
        with mock.patch("builtins.print") as mock_print:
            cmd._PrintManifestNotices(opt)
            assert mock_print.call_count == 2
            mock_print.assert_any_call("Notice 1")
            mock_print.assert_any_call("Notice 2")


@pytest.mark.unit
def test_print_manifest_notices_sorted_by_prefix():
    """Test _PrintManifestNotices sorts manifests by path_prefix."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()

    manifest1 = mock.MagicMock()
    manifest1.notice = "Notice Z"
    manifest1.path_prefix = "z"

    manifest2 = mock.MagicMock()
    manifest2.notice = "Notice A"
    manifest2.path_prefix = "a"

    with mock.patch.object(cmd, "ManifestList", return_value=[manifest1, manifest2]):
        with mock.patch("builtins.print") as mock_print:
            cmd._PrintManifestNotices(opt)
            calls = [call[0][0] for call in mock_print.call_args_list]
            assert calls == ["Notice A", "Notice Z"]


@pytest.mark.unit
def test_update_project_list_creates_new_file():
    """Test UpdateProjectList creates project.list file."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.verbose = False
    opt.force_remove_dirty = False
    manifest = mock.MagicMock()
    manifest.subdir = "/tmp/test/.repo"
    manifest.topdir = "/tmp/test"

    project1 = _make_project("p1", "path1")
    project2 = _make_project("p2", "path2")

    with mock.patch.object(cmd, "GetProjects", return_value=[project1, project2]):
        with mock.patch("os.path.exists", return_value=False):
            with mock.patch("builtins.open", mock.mock_open()) as mock_file:
                result = cmd.UpdateProjectList(opt, manifest)
                assert result == 0
                mock_file.assert_called_once()
                handle = mock_file()
                written = "".join([call[0][0] for call in handle.write.call_args_list])
                assert "path1" in written
                assert "path2" in written


@pytest.mark.unit
def test_update_project_list_removes_old_projects():
    """Test UpdateProjectList removes projects no longer in manifest."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.verbose = False
    opt.force_remove_dirty = False
    manifest = mock.MagicMock()
    manifest.subdir = "/tmp/test/.repo"
    manifest.topdir = "/tmp/test"

    project1 = _make_project("p1", "path1")

    with mock.patch.object(cmd, "GetProjects", return_value=[project1]):
        old_content = "path1\npath2\npath3"

        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("builtins.open", mock.mock_open(read_data=old_content)):
                with mock.patch.object(Project, "DeleteWorktree"):
                    result = cmd.UpdateProjectList(opt, manifest)
                    assert result == 0


@pytest.mark.unit
def test_gc_projects_without_auto_gc():
    """Test _GCProjects only sets precious objects state when auto_gc is disabled."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.auto_gc = False
    err_event = multiprocessing.Event()
    projects = [_make_project("p1"), _make_project("p2")]

    with mock.patch.object(cmd, "_SetPreciousObjectsState") as mock_set_precious:
        cmd._GCProjects(projects, opt, err_event)
        assert mock_set_precious.call_count == 2


@pytest.mark.unit
def test_gc_projects_with_auto_gc_single_job():
    """Test _GCProjects runs gc with single job."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.auto_gc = True
    opt.jobs = 1
    opt.quiet = True
    err_event = multiprocessing.Event()

    project = _make_project("p1")
    project.bare_git = mock.MagicMock()
    project.bare_git._project = project

    with mock.patch.object(cmd, "_SetPreciousObjectsState"):
        cmd._GCProjects([project], opt, err_event)
        project.bare_git.gc.assert_called_once_with("--auto")


@pytest.mark.unit
def test_gc_projects_with_auto_gc_multiple_jobs():
    """Test _GCProjects runs gc with multiple jobs in threads."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.auto_gc = True
    opt.jobs = 4
    opt.quiet = True
    opt.fail_fast = False
    err_event = multiprocessing.Event()

    project1 = _make_project("p1")
    project1.bare_git = mock.MagicMock()
    project1.bare_git._project = project1

    project2 = _make_project("p2")
    project2.bare_git = mock.MagicMock()
    project2.bare_git._project = project2

    with mock.patch.object(cmd, "_SetPreciousObjectsState"):
        with mock.patch("os.cpu_count", return_value=8):
            cmd._GCProjects([project1, project2], opt, err_event)
            # Verify gc was called
            assert project1.bare_git.gc.called or project1.bare_git.pack_refs.called
            assert project2.bare_git.gc.called or project2.bare_git.pack_refs.called


@pytest.mark.unit
def test_gc_projects_handles_git_error():
    """Test _GCProjects sets error event on GitError in threaded mode."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.auto_gc = True
    opt.jobs = 2  # Use multiple jobs to trigger threading
    opt.quiet = True
    opt.fail_fast = False
    err_event = multiprocessing.Event()

    project = _make_project("p1")
    project.bare_git = mock.MagicMock()
    project.bare_git._project = project
    project.bare_git.gc.side_effect = GitError("gc failed")

    with mock.patch.object(cmd, "_SetPreciousObjectsState"):
        with mock.patch("os.cpu_count", return_value=4):
            cmd._GCProjects([project], opt, err_event)
            assert err_event.is_set()


@pytest.mark.unit
def test_update_repo_project_skips_when_local_only():
    """Test _UpdateRepoProject skips when local_only is set."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.local_only = True
    manifest = mock.MagicMock()
    errors = []

    cmd._UpdateRepoProject(opt, manifest, errors)
    # Should return immediately without doing anything


@pytest.mark.unit
def test_update_repo_project_skips_recent_fetch():
    """Test _UpdateRepoProject skips if fetched within last day."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.local_only = False
    manifest = mock.MagicMock()
    manifest.repoProject = mock.MagicMock()
    manifest.repoProject.LastFetch = time.time() - 100  # Less than a day
    errors = []

    cmd._UpdateRepoProject(opt, manifest, errors)
    manifest.repoProject.Sync_NetworkHalf.assert_not_called()


@pytest.mark.unit
def test_update_repo_project_fetches_when_needed():
    """Test _UpdateRepoProject fetches when last fetch is old."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.local_only = False
    opt.quiet = False
    opt.verbose = False
    opt.force_sync = False
    opt.clone_bundle = True
    opt.tags = False
    opt.optimized_fetch = False
    opt.retry_fetches = 0
    opt.prune = True
    opt.repo_verify = True
    opt.use_superproject = False
    opt.current_branch_only = False

    manifest = mock.MagicMock()
    manifest.repoProject = mock.MagicMock()
    manifest.repoProject.LastFetch = time.time() - (24 * 60 * 60 * 2)  # 2 days ago
    manifest.repoProject.name = "repo"
    manifest.IsArchive = False
    manifest.CloneFilter = None
    manifest.PartialCloneExclude = set()
    manifest.CloneFilterForDepth = None

    sync_result = SyncNetworkHalfResult(remote_fetched=True, error=None)
    manifest.repoProject.Sync_NetworkHalf.return_value = sync_result

    errors = []

    with mock.patch("os.path.isdir", return_value=True):
        with mock.patch("kanon_cli.repo.subcmds.sync.multiprocessing.Manager"):
            with mock.patch("kanon_cli.repo.subcmds.sync.ssh.ProxyManager"):
                with mock.patch("kanon_cli.repo.subcmds.sync._PostRepoFetch"):
                    with mock.patch.dict(os.environ, {"REPO_SKIP_SELF_UPDATE": "1"}):
                        cmd._UpdateRepoProject(opt, manifest, errors)
                        manifest.repoProject.Sync_NetworkHalf.assert_called_once()


@pytest.mark.unit
def test_update_repo_project_handles_failure():
    """Test _UpdateRepoProject handles fetch failure."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.local_only = False
    opt.quiet = False
    opt.verbose = False
    opt.force_sync = False
    opt.clone_bundle = True
    opt.tags = False
    opt.optimized_fetch = False
    opt.retry_fetches = 0
    opt.prune = True
    opt.repo_verify = True
    opt.use_superproject = False
    opt.current_branch_only = False

    manifest = mock.MagicMock()
    manifest.repoProject = mock.MagicMock()
    manifest.repoProject.LastFetch = 0
    manifest.repoProject.name = "repo"
    manifest.IsArchive = False
    manifest.CloneFilter = None
    manifest.PartialCloneExclude = set()
    manifest.CloneFilterForDepth = None

    sync_result = SyncNetworkHalfResult(remote_fetched=False, error=GitError("failed"))
    manifest.repoProject.Sync_NetworkHalf.return_value = sync_result

    errors = []

    with mock.patch("os.path.isdir", return_value=True):
        with mock.patch("kanon_cli.repo.subcmds.sync.multiprocessing.Manager"):
            with mock.patch("kanon_cli.repo.subcmds.sync.ssh.ProxyManager"):
                cmd._UpdateRepoProject(opt, manifest, errors)
                assert len(errors) == 1


@pytest.mark.unit
def test_fetch_one_success():
    """Test _FetchOne successful fetch."""
    opt = mock.MagicMock()
    opt.quiet = False
    opt.verbose = False
    opt.force_sync = False
    opt.clone_bundle = True
    opt.tags = False
    opt.optimized_fetch = False
    opt.retry_fetches = 0
    opt.prune = True
    opt.use_superproject = False
    opt.current_branch_only = False

    project = _make_project()
    sync_result = SyncNetworkHalfResult(remote_fetched=True, error=None)
    project.Sync_NetworkHalf.return_value = sync_result

    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {
            "projects": [project],
            "sync_dict": {},
            "ssh_proxy": mock.MagicMock(),
        }

        result = sync.Sync._FetchOne(opt, 0)
        assert result.success is True
        assert result.remote_fetched is True
        assert len(result.errors) == 0


@pytest.mark.unit
def test_fetch_one_failure():
    """Test _FetchOne handles fetch failure."""
    opt = mock.MagicMock()
    opt.quiet = False
    opt.verbose = False
    opt.force_sync = False
    opt.clone_bundle = True
    opt.tags = False
    opt.optimized_fetch = False
    opt.retry_fetches = 0
    opt.prune = True
    opt.use_superproject = False
    opt.current_branch_only = False

    project = _make_project()
    git_err = GitError("fetch failed")
    sync_result = SyncNetworkHalfResult(remote_fetched=False, error=git_err)
    project.Sync_NetworkHalf.return_value = sync_result

    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {
            "projects": [project],
            "sync_dict": {},
            "ssh_proxy": mock.MagicMock(),
        }

        result = sync.Sync._FetchOne(opt, 0)
        assert result.success is False
        assert len(result.errors) == 1


@pytest.mark.unit
def test_fetch_one_keyboard_interrupt():
    """Test _FetchOne handles KeyboardInterrupt."""
    opt = mock.MagicMock()
    opt.quiet = False
    opt.verbose = False
    opt.force_sync = False
    opt.clone_bundle = True
    opt.tags = False
    opt.optimized_fetch = False
    opt.retry_fetches = 0
    opt.prune = True
    opt.use_superproject = False
    opt.current_branch_only = False

    project = _make_project()
    project.Sync_NetworkHalf.side_effect = KeyboardInterrupt()

    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {
            "projects": [project],
            "sync_dict": {},
            "ssh_proxy": mock.MagicMock(),
        }

        result = sync.Sync._FetchOne(opt, 0)
        assert result.success is False


@pytest.mark.unit
def test_fetch_one_git_error():
    """Test _FetchOne handles GitError exception."""
    opt = mock.MagicMock()
    opt.quiet = False
    opt.verbose = False
    opt.force_sync = False
    opt.clone_bundle = True
    opt.tags = False
    opt.optimized_fetch = False
    opt.retry_fetches = 0
    opt.prune = True
    opt.use_superproject = False
    opt.current_branch_only = False

    project = _make_project()
    git_err = GitError("git error")
    project.Sync_NetworkHalf.side_effect = git_err

    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {
            "projects": [project],
            "sync_dict": {},
            "ssh_proxy": mock.MagicMock(),
        }

        result = sync.Sync._FetchOne(opt, 0)
        assert result.success is False
        assert len(result.errors) == 1


@pytest.mark.unit
def test_sync_one_project_local_only():
    """Test _SyncOneProject with local_only skips fetch."""
    opt = mock.MagicMock()
    opt.local_only = True
    opt.network_only = False
    opt.detach_head = False
    opt.force_sync = False
    opt.force_checkout = False
    opt.rebase = False
    opt.verbose = False

    project = _make_project()

    with mock.patch("kanon_cli.repo.subcmds.sync.SyncBuffer") as mock_buffer:
        buffer_instance = mock.MagicMock()
        buffer_instance.Finish.return_value = True
        mock_buffer.return_value = buffer_instance

        result = sync.Sync._SyncOneProject(opt, 0, project)
        assert result.fetch_success is True
        assert result.checkout_success is True
        assert result.fetch_start is None


@pytest.mark.unit
def test_sync_one_project_network_only():
    """Test _SyncOneProject with network_only skips checkout."""
    opt = mock.MagicMock()
    opt.local_only = False
    opt.network_only = True
    opt.quiet = False
    opt.verbose = False
    opt.force_sync = False
    opt.clone_bundle = True
    opt.tags = False
    opt.optimized_fetch = False
    opt.retry_fetches = 0
    opt.prune = True
    opt.use_superproject = False
    opt.current_branch_only = False

    project = _make_project()
    sync_result = SyncNetworkHalfResult(remote_fetched=True, error=None)
    project.Sync_NetworkHalf.return_value = sync_result

    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {
            "ssh_proxy": mock.MagicMock(),
        }

        result = sync.Sync._SyncOneProject(opt, 0, project)
        assert result.fetch_success is True
        assert result.checkout_success is True
        assert result.checkout_start is None


@pytest.mark.unit
def test_sync_one_project_full_sync():
    """Test _SyncOneProject performs both fetch and checkout."""
    opt = mock.MagicMock()
    opt.local_only = False
    opt.network_only = False
    opt.quiet = False
    opt.verbose = False
    opt.force_sync = False
    opt.clone_bundle = True
    opt.tags = False
    opt.optimized_fetch = False
    opt.retry_fetches = 0
    opt.prune = True
    opt.use_superproject = False
    opt.current_branch_only = False
    opt.detach_head = False
    opt.force_checkout = False
    opt.rebase = False

    project = _make_project()
    sync_result = SyncNetworkHalfResult(remote_fetched=True, error=None)
    project.Sync_NetworkHalf.return_value = sync_result

    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {
            "ssh_proxy": mock.MagicMock(),
        }

        with mock.patch("kanon_cli.repo.subcmds.sync.SyncBuffer") as mock_buffer:
            buffer_instance = mock.MagicMock()
            buffer_instance.Finish.return_value = True
            mock_buffer.return_value = buffer_instance

            result = sync.Sync._SyncOneProject(opt, 0, project)
            assert result.fetch_success is True
            assert result.checkout_success is True
            assert result.fetch_start is not None
            assert result.checkout_start is not None


@pytest.mark.unit
def test_sync_one_project_fetch_fails():
    """Test _SyncOneProject skips checkout when fetch fails."""
    opt = mock.MagicMock()
    opt.local_only = False
    opt.network_only = False
    opt.quiet = False
    opt.verbose = False
    opt.force_sync = False
    opt.clone_bundle = True
    opt.tags = False
    opt.optimized_fetch = False
    opt.retry_fetches = 0
    opt.prune = True
    opt.use_superproject = False
    opt.current_branch_only = False

    project = _make_project()
    sync_result = SyncNetworkHalfResult(remote_fetched=False, error=GitError("failed"))
    project.Sync_NetworkHalf.return_value = sync_result

    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {
            "ssh_proxy": mock.MagicMock(),
        }

        result = sync.Sync._SyncOneProject(opt, 0, project)
        assert result.fetch_success is False
        assert result.checkout_success is False
        assert result.checkout_start is None


@pytest.mark.unit
def test_sync_one_project_checkout_fails():
    """Test _SyncOneProject handles checkout failure."""
    opt = mock.MagicMock()
    opt.local_only = False
    opt.network_only = False
    opt.quiet = False
    opt.verbose = False
    opt.force_sync = False
    opt.clone_bundle = True
    opt.tags = False
    opt.optimized_fetch = False
    opt.retry_fetches = 0
    opt.prune = True
    opt.use_superproject = False
    opt.current_branch_only = False
    opt.detach_head = False
    opt.force_checkout = False
    opt.rebase = False

    project = _make_project()
    sync_result = SyncNetworkHalfResult(remote_fetched=True, error=None)
    project.Sync_NetworkHalf.return_value = sync_result

    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {
            "ssh_proxy": mock.MagicMock(),
        }

        with mock.patch("kanon_cli.repo.subcmds.sync.SyncBuffer") as mock_buffer:
            buffer_instance = mock.MagicMock()
            buffer_instance.Finish.return_value = False
            mock_buffer.return_value = buffer_instance

            result = sync.Sync._SyncOneProject(opt, 0, project)
            assert result.fetch_success is True
            assert result.checkout_success is False


@pytest.mark.unit
def test_sync_project_list_processes_multiple_projects():
    """Test _SyncProjectList processes multiple project indices."""
    opt = mock.MagicMock()
    opt.local_only = True
    opt.network_only = False
    opt.detach_head = False
    opt.force_sync = False
    opt.force_checkout = False
    opt.rebase = False
    opt.verbose = False

    project1 = _make_project("p1", "path1")
    project2 = _make_project("p2", "path2")

    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {
            "projects": [project1, project2],
            "sync_dict": {},
        }

        with mock.patch("kanon_cli.repo.subcmds.sync.SyncBuffer") as mock_buffer:
            buffer_instance = mock.MagicMock()
            buffer_instance.Finish.return_value = True
            mock_buffer.return_value = buffer_instance

            result = sync.Sync._SyncProjectList(opt, [0, 1])
            assert len(result.results) == 2


@pytest.mark.unit
def test_get_sync_progress_message_with_projects():
    """Test _GetSyncProgressMessage returns progress info."""
    cmd = _make_sync_cmd()

    with mock.patch.object(cmd, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {"sync_dict": {"project1 @ path1": time.time() - 5.0}}

        message = cmd._GetSyncProgressMessage()
        assert "project1 @ path1" in message
        assert "1 job" in message or "jobs" in message


@pytest.mark.unit
def test_get_sync_progress_message_empty():
    """Test _GetSyncProgressMessage handles empty sync_dict."""
    cmd = _make_sync_cmd()

    with mock.patch.object(cmd, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {"sync_dict": {}}

        message = cmd._GetSyncProgressMessage()
        assert message == "..working.."


@pytest.mark.unit
def test_init_worker_forces_manager_connection():
    """Test InitWorker forces connection to manager."""
    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {"sync_dict": {}}

        sync.Sync.InitWorker()
        mock_ctx.assert_called()


@pytest.mark.unit
def test_chunksize_calculation():
    """Test _chunksize calculates appropriate chunk size."""
    from kanon_cli.repo.subcmds.sync import _chunksize, WORKER_BATCH_SIZE

    # Small number of projects
    assert _chunksize(10, 5) == 2

    # Large batch should be capped
    assert _chunksize(1000, 2) <= WORKER_BATCH_SIZE

    # Minimum is 1
    assert _chunksize(5, 10) == 1


@pytest.mark.unit
def test_safe_checkout_order_flat_projects():
    """Test _SafeCheckoutOrder with flat project structure."""
    from kanon_cli.repo.subcmds.sync import _SafeCheckoutOrder

    p1 = _make_project("p1", "proj1")
    p2 = _make_project("p2", "proj2")
    p3 = _make_project("p3", "proj3")

    result = _SafeCheckoutOrder([p1, p2, p3])
    assert len(result) == 1
    assert len(result[0]) == 3


@pytest.mark.unit
def test_safe_checkout_order_nested_projects():
    """Test _SafeCheckoutOrder with nested project structure."""
    from kanon_cli.repo.subcmds.sync import _SafeCheckoutOrder

    p1 = _make_project("foo", "foo")
    p2 = _make_project("foo/bar", "foo/bar")
    p3 = _make_project("foo/bar/baz", "foo/bar/baz")

    result = _SafeCheckoutOrder([p1, p2, p3])
    assert len(result) == 3
    assert result[0][0].relpath == "foo"
    assert result[1][0].relpath == "foo/bar"
    assert result[2][0].relpath == "foo/bar/baz"


@pytest.mark.unit
def test_safe_checkout_order_mixed_hierarchy():
    """Test _SafeCheckoutOrder with mixed flat and nested structure."""
    from kanon_cli.repo.subcmds.sync import _SafeCheckoutOrder

    p1 = _make_project("independent", "independent")
    p2 = _make_project("parent", "parent")
    p3 = _make_project("parent/child", "parent/child")

    result = _SafeCheckoutOrder([p1, p2, p3])
    # independent and parent should be in first layer
    first_layer_paths = [p.relpath for p in result[0]]
    assert "independent" in first_layer_paths
    assert "parent" in first_layer_paths
    # parent/child should be in second layer
    assert len(result) == 2
    assert result[1][0].relpath == "parent/child"


@pytest.mark.unit
def test_sync_options_jobs_network():
    """Test Sync options include jobs_network."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--jobs-network=4"])
    assert opts.jobs_network == 4


@pytest.mark.unit
def test_sync_options_jobs_checkout():
    """Test Sync options include jobs_checkout."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--jobs-checkout=8"])
    assert opts.jobs_checkout == 8


@pytest.mark.unit
def test_sync_options_fail_fast():
    """Test Sync options include fail_fast."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--fail-fast"])
    assert opts.fail_fast is True


@pytest.mark.unit
def test_sync_options_force_sync():
    """Test Sync options include force_sync."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--force-sync"])
    assert opts.force_sync is True


@pytest.mark.unit
def test_sync_options_force_checkout():
    """Test Sync options include force_checkout."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--force-checkout"])
    assert opts.force_checkout is True


@pytest.mark.unit
def test_sync_options_local_only():
    """Test Sync options include local_only."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["-l"])
    assert opts.local_only is True


@pytest.mark.unit
def test_sync_options_network_only():
    """Test Sync options include network_only."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["-n"])
    assert opts.network_only is True


@pytest.mark.unit
def test_sync_options_detach():
    """Test Sync options include detach_head."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["-d"])
    assert opts.detach_head is True


@pytest.mark.unit
def test_sync_options_current_branch():
    """Test Sync options include current_branch_only."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["-c"])
    assert opts.current_branch_only is True


@pytest.mark.unit
def test_sync_options_no_current_branch():
    """Test Sync options include no-current-branch."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--no-current-branch"])
    assert opts.current_branch_only is False


@pytest.mark.unit
def test_sync_options_manifest_name():
    """Test Sync options include manifest_name."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["-m", "test.xml"])
    assert opts.manifest_name == "test.xml"


@pytest.mark.unit
def test_sync_options_no_clone_bundle():
    """Test Sync options include no_clone_bundle."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--no-clone-bundle"])
    assert opts.clone_bundle is False


@pytest.mark.unit
def test_sync_options_fetch_submodules():
    """Test Sync options include fetch_submodules."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--fetch-submodules"])
    assert opts.fetch_submodules is True


@pytest.mark.unit
def test_sync_options_use_superproject():
    """Test Sync options include use_superproject."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--use-superproject"])
    assert opts.use_superproject is True


@pytest.mark.unit
def test_sync_options_no_use_superproject():
    """Test Sync options include no-use-superproject."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--no-use-superproject"])
    assert opts.use_superproject is False


@pytest.mark.unit
def test_sync_options_tags():
    """Test Sync options include tags."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--tags"])
    assert opts.tags is True


@pytest.mark.unit
def test_sync_options_optimized_fetch():
    """Test Sync options include optimized_fetch."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--optimized-fetch"])
    assert opts.optimized_fetch is True


@pytest.mark.unit
def test_sync_options_retry_fetches():
    """Test Sync options include retry_fetches."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--retry-fetches=3"])
    assert opts.retry_fetches == 3


@pytest.mark.unit
def test_sync_options_prune():
    """Test Sync options include prune."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--prune"])
    assert opts.prune is True


@pytest.mark.unit
def test_sync_options_no_prune():
    """Test Sync options include no-prune."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--no-prune"])
    assert opts.prune is False


@pytest.mark.unit
def test_sync_options_auto_gc():
    """Test Sync options include auto_gc."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--auto-gc"])
    assert opts.auto_gc is True


@pytest.mark.unit
def test_sync_options_no_auto_gc():
    """Test Sync options include no-auto-gc."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["--no-auto-gc"])
    assert opts.auto_gc is False


@pytest.mark.unit
def test_sync_options_smart_sync():
    """Test Sync options include smart_sync."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["-s"])
    assert opts.smart_sync is True


@pytest.mark.unit
def test_sync_options_smart_tag():
    """Test Sync options include smart_tag."""
    cmd = sync.Sync()
    parser = cmd.OptionParser
    opts, _ = parser.parse_args(["-t", "release-1.0"])
    assert opts.smart_tag == "release-1.0"


@pytest.mark.unit
def test_sync_class_attributes():
    """Test Sync class has required attributes."""
    assert sync.Sync.COMMON is True
    assert sync.Sync.MULTI_MANIFEST_SUPPORT is True
    assert sync.Sync.helpSummary is not None
    assert sync.Sync.PARALLEL_JOBS == 0


@pytest.mark.unit
def test_sync_inherit_from_command():
    """Test Sync inherits from Command."""
    from kanon_cli.repo.command import Command, MirrorSafeCommand

    assert issubclass(sync.Sync, Command)
    assert issubclass(sync.Sync, MirrorSafeCommand)


@pytest.mark.unit
def test_rlimit_nofile_with_resource():
    """Test _rlimit_nofile returns resource limits when available."""
    with mock.patch("kanon_cli.repo.subcmds.sync.resource") as mock_resource:
        mock_resource.getrlimit.return_value = (1024, 4096)
        from kanon_cli.repo.subcmds.sync import _rlimit_nofile

        result = _rlimit_nofile()
        assert result == (1024, 4096)


@pytest.mark.unit
def test_report_errors_with_network_sync_error():
    """Test _ReportErrors logs network sync errors."""
    cmd = _make_sync_cmd()
    errors = [GitError("network error")]

    with pytest.raises(SyncError):
        cmd._ReportErrors(
            errors,
            err_network_sync=True,
            err_checkout=False,
            failing_checkout_repos=[],
            err_update_projects=False,
            err_update_linkfiles=False,
        )


@pytest.mark.unit
def test_report_errors_with_checkout_error():
    """Test _ReportErrors logs checkout errors."""
    cmd = _make_sync_cmd()
    errors = [GitError("checkout error")]

    with pytest.raises(SyncError):
        cmd._ReportErrors(
            errors,
            err_network_sync=False,
            err_checkout=True,
            failing_checkout_repos=["project1", "project2"],
            err_update_projects=False,
            err_update_linkfiles=False,
        )


@pytest.mark.unit
def test_report_errors_with_update_projects_error():
    """Test _ReportErrors logs update projects errors."""
    cmd = _make_sync_cmd()
    errors = []

    with pytest.raises(SyncError):
        cmd._ReportErrors(
            errors,
            err_network_sync=False,
            err_checkout=False,
            failing_checkout_repos=[],
            err_update_projects=True,
            err_update_linkfiles=False,
        )


@pytest.mark.unit
def test_report_errors_with_update_linkfiles_error():
    """Test _ReportErrors logs update linkfiles errors."""
    cmd = _make_sync_cmd()
    errors = []

    with pytest.raises(SyncError):
        cmd._ReportErrors(
            errors,
            err_network_sync=False,
            err_checkout=False,
            failing_checkout_repos=[],
            err_update_projects=False,
            err_update_linkfiles=True,
        )


@pytest.mark.unit
def test_report_errors_with_multiple_errors():
    """Test _ReportErrors logs multiple error types."""
    cmd = _make_sync_cmd()
    errors = [GitError("error1"), GitError("error2")]

    with pytest.raises(SyncError):
        cmd._ReportErrors(
            errors,
            err_network_sync=True,
            err_checkout=True,
            failing_checkout_repos=["proj1"],
            err_update_projects=True,
            err_update_linkfiles=True,
        )


@pytest.mark.unit
def test_validate_options_force_broken_warning():
    """Test ValidateOptions warns about deprecated force_broken."""
    cmd = sync.Sync()
    opt = mock.MagicMock()
    opt.force_broken = True
    opt.network_only = False
    opt.local_only = False
    opt.detach_head = False
    opt.manifest_name = None
    opt.smart_sync = False
    opt.smart_tag = None
    opt.manifest_server_username = None
    opt.manifest_server_password = None
    opt.prune = None

    cmd.ValidateOptions(opt, [])
    assert opt.prune is True


@pytest.mark.unit
def test_validate_options_network_only_and_detach_head():
    """Test ValidateOptions errors on -n and -d combination."""
    cmd = sync.Sync()
    opt = mock.MagicMock()
    opt.force_broken = False
    opt.network_only = True
    opt.detach_head = True
    opt.local_only = False

    with pytest.raises(SystemExit):
        cmd.ValidateOptions(opt, [])


@pytest.mark.unit
def test_validate_options_network_only_and_local_only():
    """Test ValidateOptions errors on -n and -l combination."""
    cmd = sync.Sync()
    opt = mock.MagicMock()
    opt.force_broken = False
    opt.network_only = True
    opt.local_only = True
    opt.detach_head = False

    with pytest.raises(SystemExit):
        cmd.ValidateOptions(opt, [])


@pytest.mark.unit
def test_validate_options_manifest_name_and_smart_sync():
    """Test ValidateOptions errors on -m and -s combination."""
    cmd = sync.Sync()
    opt = mock.MagicMock()
    opt.force_broken = False
    opt.network_only = False
    opt.local_only = False
    opt.detach_head = False
    opt.manifest_name = "test.xml"
    opt.smart_sync = True
    opt.smart_tag = None

    with pytest.raises(SystemExit):
        cmd.ValidateOptions(opt, [])


@pytest.mark.unit
def test_validate_options_manifest_name_and_smart_tag():
    """Test ValidateOptions errors on -m and -t combination."""
    cmd = sync.Sync()
    opt = mock.MagicMock()
    opt.force_broken = False
    opt.network_only = False
    opt.local_only = False
    opt.detach_head = False
    opt.manifest_name = "test.xml"
    opt.smart_sync = False
    opt.smart_tag = "v1.0"

    with pytest.raises(SystemExit):
        cmd.ValidateOptions(opt, [])


@pytest.mark.unit
def test_validate_options_username_without_smart_sync():
    """Test ValidateOptions errors on -u without -s or -t."""
    cmd = sync.Sync()
    opt = mock.MagicMock()
    opt.force_broken = False
    opt.network_only = False
    opt.local_only = False
    opt.detach_head = False
    opt.manifest_name = None
    opt.smart_sync = False
    opt.smart_tag = None
    opt.manifest_server_username = "user"
    opt.manifest_server_password = "pass"

    with pytest.raises(SystemExit):
        cmd.ValidateOptions(opt, [])


@pytest.mark.unit
def test_validate_options_username_without_password():
    """Test ValidateOptions errors when -u given without -p."""
    cmd = sync.Sync()
    opt = mock.MagicMock()
    opt.force_broken = False
    opt.network_only = False
    opt.local_only = False
    opt.detach_head = False
    opt.manifest_name = None
    opt.smart_sync = True
    opt.smart_tag = None
    opt.manifest_server_username = "user"
    opt.manifest_server_password = None

    with pytest.raises(SystemExit):
        cmd.ValidateOptions(opt, [])


@pytest.mark.unit
def test_validate_options_sets_prune_default():
    """Test ValidateOptions sets prune to True when None."""
    cmd = sync.Sync()
    opt = mock.MagicMock()
    opt.force_broken = False
    opt.network_only = False
    opt.local_only = False
    opt.detach_head = False
    opt.manifest_name = None
    opt.smart_sync = False
    opt.smart_tag = None
    opt.manifest_server_username = None
    opt.manifest_server_password = None
    opt.prune = None

    cmd.ValidateOptions(opt, [])
    assert opt.prune is True


@pytest.mark.unit
def test_validate_options_preserves_prune_false():
    """Test ValidateOptions preserves prune=False."""
    cmd = sync.Sync()
    opt = mock.MagicMock()
    opt.force_broken = False
    opt.network_only = False
    opt.local_only = False
    opt.detach_head = False
    opt.manifest_name = None
    opt.smart_sync = False
    opt.smart_tag = None
    opt.manifest_server_username = None
    opt.manifest_server_password = None
    opt.prune = False

    cmd.ValidateOptions(opt, [])
    assert opt.prune is False


@pytest.mark.unit
def test_smart_sync_setup_no_manifest_server():
    """Test _SmartSyncSetup raises error when no manifest server defined."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    manifest = mock.MagicMock()
    manifest.manifest_server = None

    with pytest.raises(sync.SmartSyncError):
        cmd._SmartSyncSetup(opt, "/path/to/manifest.xml", manifest)


@pytest.mark.unit
def test_smart_sync_setup_with_credentials_in_url():
    """Test _SmartSyncSetup with credentials already in URL."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.quiet = True
    opt.smart_sync = True
    opt.smart_tag = None
    opt.manifest_server_username = None
    opt.manifest_server_password = None

    manifest = mock.MagicMock()
    manifest.manifest_server = "https://user:pass@example.com/manifest"
    manifest.manifestProject = mock.MagicMock()
    manifest.manifestProject.CurrentBranch = "main"
    branch_obj = mock.MagicMock()
    branch_obj.merge = "refs/heads/main"
    manifest.manifestProject.GetBranch.return_value = branch_obj

    with mock.patch("kanon_cli.repo.subcmds.sync.xmlrpc.client.Server") as mock_server:
        server_instance = mock.MagicMock()
        server_instance.GetApprovedManifest.return_value = [True, "<manifest/>"]
        mock_server.return_value = server_instance

        with mock.patch("builtins.open", mock.mock_open()):
            result = cmd._SmartSyncSetup(opt, "/tmp/smart_sync.xml", manifest)
            assert result is not None


@pytest.mark.unit
def test_smart_sync_setup_with_username_password_options():
    """Test _SmartSyncSetup with username and password options."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.quiet = True
    opt.smart_sync = True
    opt.smart_tag = None
    opt.manifest_server_username = "testuser"
    opt.manifest_server_password = "testpass"

    manifest = mock.MagicMock()
    manifest.manifest_server = "https://example.com/manifest"
    manifest.manifestProject = mock.MagicMock()
    manifest.manifestProject.CurrentBranch = "main"
    branch_obj = mock.MagicMock()
    branch_obj.merge = "refs/heads/main"
    manifest.manifestProject.GetBranch.return_value = branch_obj

    with mock.patch("kanon_cli.repo.subcmds.sync.xmlrpc.client.Server") as mock_server:
        server_instance = mock.MagicMock()
        server_instance.GetApprovedManifest.return_value = [True, "<manifest/>"]
        mock_server.return_value = server_instance

        with mock.patch("builtins.open", mock.mock_open()):
            result = cmd._SmartSyncSetup(opt, "/tmp/smart_sync.xml", manifest)
            assert result is not None


@pytest.mark.unit
def test_smart_sync_setup_with_smart_tag():
    """Test _SmartSyncSetup with smart_tag option."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.quiet = True
    opt.smart_sync = False
    opt.smart_tag = "release-1.0"
    opt.manifest_server_username = None
    opt.manifest_server_password = None

    manifest = mock.MagicMock()
    manifest.manifest_server = "https://example.com/manifest"

    with mock.patch("kanon_cli.repo.subcmds.sync.xmlrpc.client.Server") as mock_server:
        server_instance = mock.MagicMock()
        server_instance.GetManifest.return_value = [True, "<manifest/>"]
        mock_server.return_value = server_instance

        with mock.patch("builtins.open", mock.mock_open()):
            result = cmd._SmartSyncSetup(opt, "/tmp/smart_sync.xml", manifest)
            assert result is not None
            server_instance.GetManifest.assert_called_once_with("release-1.0")


@pytest.mark.unit
def test_smart_sync_setup_server_failure():
    """Test _SmartSyncSetup handles server RPC failure."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.quiet = True
    opt.smart_sync = True
    opt.smart_tag = None
    opt.manifest_server_username = None
    opt.manifest_server_password = None

    manifest = mock.MagicMock()
    manifest.manifest_server = "https://example.com/manifest"
    manifest.manifestProject = mock.MagicMock()
    manifest.manifestProject.CurrentBranch = "main"
    branch_obj = mock.MagicMock()
    branch_obj.merge = "refs/heads/main"
    manifest.manifestProject.GetBranch.return_value = branch_obj

    with mock.patch("kanon_cli.repo.subcmds.sync.xmlrpc.client.Server") as mock_server:
        server_instance = mock.MagicMock()
        server_instance.GetApprovedManifest.return_value = [
            False,
            "Server error",
        ]
        mock_server.return_value = server_instance

        with pytest.raises(sync.SmartSyncError):
            cmd._SmartSyncSetup(opt, "/tmp/smart_sync.xml", manifest)


@pytest.mark.unit
def test_smart_sync_setup_connection_error():
    """Test _SmartSyncSetup handles connection error."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.quiet = True
    opt.smart_sync = True
    opt.smart_tag = None
    opt.manifest_server_username = None
    opt.manifest_server_password = None

    manifest = mock.MagicMock()
    manifest.manifest_server = "https://example.com/manifest"
    manifest.manifestProject = mock.MagicMock()
    manifest.manifestProject.CurrentBranch = "main"
    branch_obj = mock.MagicMock()
    branch_obj.merge = "refs/heads/main"
    manifest.manifestProject.GetBranch.return_value = branch_obj

    with mock.patch("kanon_cli.repo.subcmds.sync.xmlrpc.client.Server") as mock_server:
        mock_server.side_effect = OSError("Connection failed")

        with pytest.raises(sync.SmartSyncError):
            cmd._SmartSyncSetup(opt, "/tmp/smart_sync.xml", manifest)


@pytest.mark.unit
def test_update_copy_linkfile_list_creates_new_file():
    """Test UpdateCopyLinkfileList creates new JSON file."""
    cmd = _make_sync_cmd()
    cmd.client = mock.MagicMock()
    cmd.client.topdir = "/tmp/test"
    manifest = mock.MagicMock()
    manifest.subdir = "/tmp/test/.repo"

    project = _make_project()
    linkfile = mock.MagicMock()
    linkfile.dest = "link/file.txt"
    copyfile = mock.MagicMock()
    copyfile.dest = "copy/file.txt"
    project.linkfiles = [linkfile]
    project.copyfiles = [copyfile]

    with mock.patch.object(cmd, "GetProjects", return_value=[project]):
        with mock.patch("os.path.exists", return_value=False):
            with mock.patch("builtins.open", mock.mock_open()):
                result = cmd.UpdateCopyLinkfileList(manifest)
                assert result is True


@pytest.mark.unit
def test_update_copy_linkfile_list_removes_old_files():
    """Test UpdateCopyLinkfileList removes old linkfiles/copyfiles."""
    cmd = _make_sync_cmd()
    cmd.client = mock.MagicMock()
    cmd.client.topdir = "/tmp/test"
    manifest = mock.MagicMock()
    manifest.subdir = "/tmp/test/.repo"

    project = _make_project()
    project.linkfiles = []
    project.copyfiles = []

    old_data = json.dumps({"linkfile": ["old/link.txt"], "copyfile": ["old/copy.txt"]})

    with mock.patch.object(cmd, "GetProjects", return_value=[project]):
        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("builtins.open", mock.mock_open(read_data=old_data)):
                with mock.patch("kanon_cli.repo.subcmds.sync.platform_utils.remove") as mock_remove:
                    result = cmd.UpdateCopyLinkfileList(manifest)
                    assert result is True
                    assert mock_remove.call_count == 2


@pytest.mark.unit
def test_update_all_manifest_projects_calls_update_manifest():
    """Test _UpdateAllManifestProjects updates manifest project."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    mp = mock.MagicMock()
    mp.standalone_manifest_url = None
    mp.manifest.submanifests = {}
    errors = []

    with mock.patch.object(cmd, "_UpdateManifestProject"):
        cmd._UpdateAllManifestProjects(opt, mp, "manifest.xml", errors)
        cmd._UpdateManifestProject.assert_called_once()


@pytest.mark.unit
def test_update_all_manifest_projects_with_submanifests():
    """Test _UpdateAllManifestProjects processes submanifests recursively."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.verbose = False
    opt.tags = False
    opt.use_superproject = False
    opt.current_branch_only = False

    mp = mock.MagicMock()
    mp.standalone_manifest_url = None

    # Create submanifest
    submanifest = mock.MagicMock()
    child_manifest = mock.MagicMock()
    child_manifest.manifestProject = mock.MagicMock()
    child_manifest.submanifests = {}
    submanifest.repo_client.manifest = child_manifest

    mp.manifest.submanifests = {"sub": submanifest}

    errors = []

    with mock.patch.object(cmd, "_UpdateManifestProject"):
        with mock.patch("kanon_cli.repo.subcmds.sync.git_superproject.UseSuperproject", return_value=False):
            cmd._UpdateAllManifestProjects(opt, mp, "manifest.xml", errors)


@pytest.mark.unit
def test_update_manifest_project_skips_when_local_only():
    """Test _UpdateManifestProject skips network fetch when local_only."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.local_only = True
    mp = mock.MagicMock()
    mp.HasChanges = False
    errors = []

    cmd._UpdateManifestProject(opt, mp, "manifest.xml", errors)
    mp.Sync_NetworkHalf.assert_not_called()


@pytest.mark.unit
def test_update_manifest_project_handles_keyboard_interrupt():
    """Test _UpdateManifestProject handles KeyboardInterrupt."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.local_only = False
    opt.verbose = False
    opt.force_sync = False
    opt.tags = False
    opt.optimized_fetch = False
    opt.retry_fetches = 0
    opt.use_superproject = False
    opt.current_branch_only = False

    mp = mock.MagicMock()
    mp.name = "manifest"
    mp.manifest = mock.MagicMock()
    mp.manifest.HasSubmodules = False
    mp.manifest.CloneFilter = None
    mp.manifest.PartialCloneExclude = set()
    mp.manifest.CloneFilterForDepth = None
    mp.Sync_NetworkHalf.side_effect = KeyboardInterrupt()

    errors = []

    with pytest.raises(KeyboardInterrupt):
        cmd._UpdateManifestProject(opt, mp, "manifest.xml", errors)
    assert len(errors) == 1
    assert isinstance(errors[0], sync.ManifestInterruptError)


@pytest.mark.unit
def test_update_manifest_project_reloads_on_changes():
    """Test _UpdateManifestProject reloads manifest when changes detected."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.local_only = False
    opt.verbose = False
    opt.force_sync = False
    opt.tags = False
    opt.optimized_fetch = False
    opt.retry_fetches = 0
    opt.use_superproject = False
    opt.current_branch_only = False

    mp = mock.MagicMock()
    mp.name = "manifest"
    mp.manifest = mock.MagicMock()
    mp.manifest.HasSubmodules = False
    mp.manifest.CloneFilter = None
    mp.manifest.PartialCloneExclude = set()
    mp.manifest.CloneFilterForDepth = None
    mp.HasChanges = True

    sync_result = SyncNetworkHalfResult(remote_fetched=True, error=None)
    mp.Sync_NetworkHalf.return_value = sync_result

    errors = []

    with mock.patch("kanon_cli.repo.subcmds.sync.SyncBuffer") as mock_buffer:
        buffer_instance = mock.MagicMock()
        buffer_instance.Finish.return_value = True
        mock_buffer.return_value = buffer_instance

        with mock.patch.object(cmd, "_ReloadManifest"):
            with mock.patch(
                "kanon_cli.repo.subcmds.sync.git_superproject.UseSuperproject",
                return_value=False,
            ):
                cmd._UpdateManifestProject(opt, mp, "manifest.xml", errors)
                cmd._ReloadManifest.assert_called_once()


@pytest.mark.unit
def test_fetch_one_with_verbose_output():
    """Test _FetchOne with verbose mode outputs to stdout."""
    opt = mock.MagicMock()
    opt.quiet = False
    opt.verbose = True
    opt.force_sync = False
    opt.clone_bundle = True
    opt.tags = False
    opt.optimized_fetch = False
    opt.retry_fetches = 0
    opt.prune = True
    opt.use_superproject = False
    opt.current_branch_only = False

    project = _make_project()
    sync_result = SyncNetworkHalfResult(remote_fetched=True, error=None)
    project.Sync_NetworkHalf.return_value = sync_result

    with mock.patch.object(sync.Sync, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {
            "projects": [project],
            "sync_dict": {},
            "ssh_proxy": mock.MagicMock(),
        }

        result = sync.Sync._FetchOne(opt, 0)
        assert result.success is True


@pytest.mark.unit
def test_fetch_times_get_default():
    """Test _FetchTimes.Get returns default for unknown project."""
    manifest = mock.MagicMock()
    manifest.repodir = "/tmp/test/.repo"

    with mock.patch("os.path.exists", return_value=False):
        fetch_times = sync._FetchTimes(manifest)
        project = _make_project()
        result = fetch_times.Get(project)
        assert result == sync._ONE_DAY_S


@pytest.mark.unit
def test_fetch_times_set_and_save():
    """Test _FetchTimes.Set records time and Save persists it."""
    manifest = mock.MagicMock()
    manifest.repodir = "/tmp/test/.repo"

    with mock.patch("os.path.exists", return_value=False):
        fetch_times = sync._FetchTimes(manifest)
        project = _make_project("proj1")

        fetch_times.Set(project, 10.5)
        assert "proj1" in fetch_times._seen

        with mock.patch("builtins.open", mock.mock_open()):
            fetch_times.Save()


@pytest.mark.unit
def test_fetch_times_load_existing():
    """Test _FetchTimes loads existing times from file."""
    manifest = mock.MagicMock()
    manifest.repodir = "/tmp/test/.repo"

    existing_data = json.dumps({"proj1": 15.0})

    with mock.patch("os.path.exists", return_value=True):
        with mock.patch("builtins.open", mock.mock_open(read_data=existing_data)):
            fetch_times = sync._FetchTimes(manifest)
            project = _make_project("proj1")
            result = fetch_times.Get(project)
            assert result == 15.0


@pytest.mark.unit
def test_local_sync_state_set_and_get_fetch_time():
    """Test LocalSyncState tracks fetch times."""
    manifest = mock.MagicMock()
    manifest.repodir = "/tmp/test/.repo"

    with mock.patch("os.path.exists", return_value=False):
        state = sync.LocalSyncState(manifest)
        project = _make_project("proj1", "path1")

        state.SetFetchTime(project)
        fetch_time = state.GetFetchTime(project)
        assert fetch_time is not None


@pytest.mark.unit
def test_local_sync_state_set_and_get_checkout_time():
    """Test LocalSyncState tracks checkout times."""
    manifest = mock.MagicMock()
    manifest.repodir = "/tmp/test/.repo"

    with mock.patch("os.path.exists", return_value=False):
        state = sync.LocalSyncState(manifest)
        project = _make_project("proj1", "path1")

        state.SetCheckoutTime(project)
        checkout_time = state.GetCheckoutTime(project)
        assert checkout_time is not None


@pytest.mark.unit
def test_local_sync_state_save():
    """Test LocalSyncState.Save persists state."""
    manifest = mock.MagicMock()
    manifest.repodir = "/tmp/test/.repo"

    with mock.patch("os.path.exists", return_value=False):
        state = sync.LocalSyncState(manifest)
        project = _make_project("proj1", "path1")
        state.SetFetchTime(project)

        with mock.patch("builtins.open", mock.mock_open()):
            state.Save()


@pytest.mark.unit
def test_local_sync_state_prune_removed_projects():
    """Test LocalSyncState.PruneRemovedProjects removes missing projects."""
    manifest = mock.MagicMock()
    manifest.repodir = "/tmp/test/.repo"
    manifest.topdir = "/tmp/test"

    existing_data = json.dumps({"path1": {"last_fetch": 123.0}})

    def exists_side_effect(path):
        # Return False for the gitdir check to trigger pruning
        if ".git" in path:
            return False
        # True for the JSON file
        return True

    with mock.patch("os.path.exists", side_effect=exists_side_effect):
        with mock.patch("builtins.open", mock.mock_open(read_data=existing_data)):
            state = sync.LocalSyncState(manifest)

            with mock.patch("builtins.open", mock.mock_open()):
                state.PruneRemovedProjects()
                assert "path1" not in state._state


@pytest.mark.unit
def test_local_sync_state_is_partially_synced_empty():
    """Test LocalSyncState.IsPartiallySynced returns False for empty state."""
    manifest = mock.MagicMock()
    manifest.repodir = "/tmp/test/.repo"
    manifest.repoProject = mock.MagicMock()
    manifest.repoProject.relpath = ".repo/manifests"

    with mock.patch("os.path.exists", return_value=False):
        state = sync.LocalSyncState(manifest)
        assert state.IsPartiallySynced() is False


@pytest.mark.unit
def test_local_sync_state_is_partially_synced_missing_checkout():
    """Test LocalSyncState.IsPartiallySynced detects missing checkout."""
    manifest = mock.MagicMock()
    manifest.repodir = "/tmp/test/.repo"
    manifest.repoProject = mock.MagicMock()
    manifest.repoProject.relpath = ".repo/manifests"

    existing_data = json.dumps({"path1": {"last_fetch": 123.0}})

    with mock.patch("os.path.exists", return_value=True):
        with mock.patch("builtins.open", mock.mock_open(read_data=existing_data)):
            state = sync.LocalSyncState(manifest)
            assert state.IsPartiallySynced() is True


@pytest.mark.unit
def test_local_sync_state_is_partially_synced_different_times():
    """Test LocalSyncState.IsPartiallySynced detects different checkout times."""
    manifest = mock.MagicMock()
    manifest.repodir = "/tmp/test/.repo"
    manifest.repoProject = mock.MagicMock()
    manifest.repoProject.relpath = ".repo/manifests"

    existing_data = json.dumps({"path1": {"last_checkout": 100.0}, "path2": {"last_checkout": 200.0}})

    with mock.patch("os.path.exists", return_value=True):
        with mock.patch("builtins.open", mock.mock_open(read_data=existing_data)):
            state = sync.LocalSyncState(manifest)
            assert state.IsPartiallySynced() is True


@pytest.mark.unit
def test_persistent_transport_init():
    """Test PersistentTransport initialization."""
    transport = sync.PersistentTransport("https://example.com")
    assert transport.orig_host == "https://example.com"


@pytest.mark.unit
def test_persistent_transport_request():
    """Test PersistentTransport.request makes HTTP request."""
    transport = sync.PersistentTransport("https://example.com")

    with mock.patch("kanon_cli.repo.subcmds.sync.GetUrlCookieFile") as mock_cookie:
        mock_cookie.return_value.__enter__.return_value = (None, None)

        with mock.patch("urllib.request.build_opener") as mock_opener:
            opener_instance = mock.MagicMock()
            response = mock.MagicMock()
            response.read.return_value = b'<?xml version="1.0"?><methodResponse><params><param><value><string>test</string></value></param></params></methodResponse>'
            opener_instance.open.return_value = response
            mock_opener.return_value = opener_instance

            transport.request(
                "example.com",
                "/RPC2",
                b"<methodCall></methodCall>",
                verbose=False,
            )


@pytest.mark.unit
def test_persistent_transport_close():
    """Test PersistentTransport.close is a no-op."""
    transport = sync.PersistentTransport("https://example.com")
    transport.close()  # Should not raise


@pytest.mark.unit
def test_post_repo_upgrade_creates_symlink():
    """Test _PostRepoUpgrade creates internal-fs-layout.md symlink."""
    manifest = mock.MagicMock()
    manifest.repodir = "/tmp/test/.repo"
    manifest.projects = []

    with mock.patch("kanon_cli.repo.subcmds.sync.platform_utils.islink", return_value=False):
        with mock.patch("kanon_cli.repo.subcmds.sync.platform_utils.symlink"):
            with mock.patch("kanon_cli.repo.subcmds.sync.Wrapper"):
                sync._PostRepoUpgrade(manifest)


@pytest.mark.unit
def test_post_repo_fetch_no_changes():
    """Test _PostRepoFetch when repo has no changes."""
    rp = mock.MagicMock()
    rp.HasChanges = False
    rp.work_git.describe.return_value = "v2.0"

    with mock.patch("kanon_cli.repo.subcmds.sync.HEAD", "HEAD"):
        sync._PostRepoFetch(rp, repo_verify=True, verbose=True)


@pytest.mark.unit
def test_post_repo_fetch_with_changes_same_rev():
    """Test _PostRepoFetch with changes but same revision."""
    rp = mock.MagicMock()
    rp.HasChanges = True
    rp.gitdir = "/tmp/test/.repo/repo"
    rp.bare_git.describe.return_value = "v2.0"
    rp.bare_git.rev_parse.return_value = "abc123"

    with mock.patch("kanon_cli.repo.subcmds.sync.Wrapper") as mock_wrapper:
        wrapper_instance = mock.MagicMock()
        wrapper_instance.check_repo_rev.return_value = (None, "v2.0")
        mock_wrapper.return_value = wrapper_instance

        sync._PostRepoFetch(rp, repo_verify=True, verbose=False)


@pytest.mark.unit
def test_one_day_constant():
    """Test _ONE_DAY_S constant is defined."""
    assert sync._ONE_DAY_S == 24 * 60 * 60


@pytest.mark.unit
def test_update_projects_revision_id_no_superproject():
    """Test _UpdateProjectsRevisionId returns early when no superproject."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.local_only = False
    args = []
    superproject_logging_data = {}
    manifest = mock.MagicMock()
    manifest.superproject = None
    manifest.all_children = []

    cmd._UpdateProjectsRevisionId(opt, args, superproject_logging_data, manifest)
    # Should return early without doing anything


@pytest.mark.unit
def test_update_projects_revision_id_with_local_only():
    """Test _UpdateProjectsRevisionId with local_only option."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.local_only = True
    args = []
    superproject_logging_data = {}
    manifest = mock.MagicMock()
    manifest.superproject = mock.MagicMock()
    manifest.superproject.manifest_path = "/tmp/manifest.xml"
    manifest.all_children = []

    with mock.patch.object(cmd, "_ReloadManifest"):
        cmd._UpdateProjectsRevisionId(opt, args, superproject_logging_data, manifest)
        cmd._ReloadManifest.assert_called_once()


@pytest.mark.unit
def test_create_sync_progress_thread():
    """Test _CreateSyncProgressThread creates and returns thread."""
    cmd = _make_sync_cmd()
    pm = mock.MagicMock()
    event = mock.MagicMock()

    with mock.patch.object(cmd, "_GetSyncProgressMessage", return_value="progress"):
        thread = cmd._CreateSyncProgressThread(pm, event)
        assert thread is not None


@pytest.mark.unit
def test_process_sync_interleaved_results_success():
    """Test _ProcessSyncInterleavedResults with successful results."""
    cmd = _make_sync_cmd()
    synced_relpaths = set()
    err_event = multiprocessing.Event()
    errors = []
    opt = mock.MagicMock()
    opt.fail_fast = False
    opt.verbose = False
    pool = None
    pm = mock.MagicMock()

    project1 = _make_project("p1", "path1")

    result1 = sync._SyncResult(
        project_index=0,
        relpath="path1",
        remote_fetched=True,
        fetch_success=True,
        fetch_error=None,
        fetch_start=1.0,
        fetch_finish=2.0,
        checkout_success=True,
        checkout_error=None,
        checkout_start=3.0,
        checkout_finish=4.0,
        stderr_text="",
    )

    interleaved_result = sync._InterleavedSyncResult(results=[result1])

    with mock.patch.object(cmd, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {"projects": [project1]}

        result = cmd._ProcessSyncInterleavedResults(
            synced_relpaths,
            err_event,
            errors,
            opt,
            pool,
            pm,
            [interleaved_result],
        )

        assert result is True
        assert "path1" in synced_relpaths


@pytest.mark.unit
def test_process_sync_interleaved_results_failure():
    """Test _ProcessSyncInterleavedResults with failed results."""
    cmd = _make_sync_cmd()
    cmd._interleaved_err_network = False
    cmd._interleaved_err_network_results = []
    cmd._interleaved_err_checkout = False
    cmd._interleaved_err_checkout_results = []

    synced_relpaths = set()
    err_event = multiprocessing.Event()
    errors = []
    opt = mock.MagicMock()
    opt.fail_fast = False
    opt.verbose = False
    pool = None
    pm = mock.MagicMock()

    project1 = _make_project("p1", "path1")

    result1 = sync._SyncResult(
        project_index=0,
        relpath="path1",
        remote_fetched=False,
        fetch_success=False,
        fetch_error=GitError("fetch failed"),
        fetch_start=1.0,
        fetch_finish=2.0,
        checkout_success=False,
        checkout_error=None,
        checkout_start=None,
        checkout_finish=None,
        stderr_text="",
    )

    interleaved_result = sync._InterleavedSyncResult(results=[result1])

    with mock.patch.object(cmd, "get_parallel_context") as mock_ctx:
        mock_ctx.return_value = {"projects": [project1]}

        result = cmd._ProcessSyncInterleavedResults(
            synced_relpaths,
            err_event,
            errors,
            opt,
            pool,
            pm,
            [interleaved_result],
        )

        assert result is False
        assert err_event.is_set()
        assert len(errors) == 1


@pytest.mark.unit
def test_validate_options_with_manifest_sets_jobs():
    """Test _ValidateOptionsWithManifest sets jobs from manifest."""
    cmd = _make_sync_cmd()
    opt = mock.MagicMock()
    opt.jobs = 0
    opt.jobs_network = None
    opt.jobs_checkout = None
    mp = mock.MagicMock()
    mp.manifest.default.sync_j = 4

    cmd._ValidateOptionsWithManifest(opt, mp)
    assert opt.jobs == 4
