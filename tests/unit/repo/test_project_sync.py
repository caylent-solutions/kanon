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

"""Unit tests for sync-related methods in project.py module."""

from unittest import mock

import pytest

from kanon_cli.repo import project


def _make_project(tmp_path):
    """Create a minimally mocked Project for testing."""
    manifest = mock.MagicMock()
    manifest.topdir = str(tmp_path)
    manifest.repodir = str(tmp_path / ".repo")
    manifest.globalConfig = mock.MagicMock()
    manifest.manifestProject = mock.MagicMock()
    manifest.manifestProject.depth = None
    manifest.manifestProject.dissociate = False
    manifest.IsMirror = False
    manifest._loaded = True
    manifest.default = mock.MagicMock()
    manifest.default.sync_c = False
    manifest.path_prefix = ""
    manifest.is_multimanifest = False

    proj = project.Project.__new__(project.Project)
    proj.manifest = manifest
    proj.client = manifest
    proj.name = "test-project"
    proj.relpath = "test-project"
    proj.worktree = str(tmp_path / "test-project")
    proj.gitdir = str(tmp_path / ".repo" / "projects" / "test-project.git")
    proj.objdir = proj.gitdir
    proj.bare_git = mock.MagicMock()
    proj.work_git = mock.MagicMock()
    proj.bare_ref = mock.MagicMock()
    proj.bare_objdir = mock.MagicMock()
    proj.config = mock.MagicMock()
    proj.remote = mock.MagicMock()
    proj.remote.name = "origin"
    proj.remote.url = "https://example.com/test.git"
    proj.remote.pushUrl = None
    proj.remote.review = None
    proj.remote.revision = None
    proj.revisionExpr = "refs/heads/main"
    proj.revisionId = None
    proj.upstream = None
    proj.dest_branch = None
    proj.old_revision = None
    proj.groups = ["all"]
    proj.copyfiles = []
    proj.linkfiles = []
    proj.annotations = []
    proj.clone_depth = None
    proj.parent = None
    proj.use_git_worktrees = False
    proj.has_subprojects = False
    proj.is_derived = False
    proj.optimized_fetch = False
    proj.retry_fetches = 0
    proj.rebase = True
    proj.sync_c = False
    proj.sync_s = False
    proj.sync_tags = True
    proj.subprojects = []
    proj.snapshots = {}
    proj.enabled_repo_hooks = []
    proj._userident_name = None
    proj._userident_email = None
    proj.bare_ref.all = {}

    # Caching flag for _ResolveVersionConstraint (mirrors __init__ default).
    proj._constraint_resolved = False

    return proj


@pytest.mark.unit
class TestInitGitDir:
    """Test _InitGitDir method."""

    def test_init_git_dir_creates_directory(self, tmp_path):
        """Test _InitGitDir creates git directory."""
        proj = _make_project(tmp_path)
        gitdir = tmp_path / "new_gitdir"
        proj.gitdir = str(gitdir)
        proj.objdir = str(gitdir)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_cmd = mock.MagicMock()
            mock_cmd.Wait.return_value = 0
            mock_git.return_value = mock_cmd

            with mock.patch.object(proj, "_UpdateHooks"):
                proj._InitGitDir()

        assert gitdir.exists()


@pytest.mark.unit
class TestBranchManagement:
    """Test branch creation and management."""

    def test_start_branch_success(self, tmp_path):
        """Test StartBranch creates new branch."""
        proj = _make_project(tmp_path)

        with mock.patch.object(proj.bare_git, "rev_parse", return_value="abc123"):
            with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
                mock_cmd = mock.MagicMock()
                mock_cmd.Wait.return_value = 0
                mock_git.return_value = mock_cmd

                result = proj.StartBranch("new-branch")

        assert result is not None

    def test_start_branch_already_exists(self, tmp_path):
        """Test StartBranch when branch already exists."""
        proj = _make_project(tmp_path)
        proj.work_git.GetHead.return_value = "refs/heads/existing"

        result = proj.StartBranch("existing")

        # Should return existing branch
        assert result is not None


# GetUploadableBranches Tests


@pytest.mark.unit
class TestDeleteWorktree:
    """Test DeleteWorktree method."""

    def test_delete_worktree_dirty_without_force(self, tmp_path):
        """Test DeleteWorktree fails on dirty worktree without force."""
        proj = _make_project(tmp_path)

        with mock.patch.object(proj, "IsDirty", return_value=True):
            with pytest.raises(project.DeleteDirtyWorktreeError):
                proj.DeleteWorktree(force=False)

    def test_delete_worktree_dirty_with_force(self, tmp_path):
        """Test DeleteWorktree proceeds with dirty worktree when forced."""
        proj = _make_project(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        proj.worktree = str(worktree)

        with mock.patch.object(proj, "IsDirty", return_value=True):
            with mock.patch("shutil.rmtree"):
                with mock.patch("os.path.exists", return_value=False):
                    result = proj.DeleteWorktree(force=True)

        # Should succeed with warning
        assert result is True

    def test_delete_worktree_clean(self, tmp_path):
        """Test DeleteWorktree with clean worktree."""
        proj = _make_project(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        proj.worktree = str(worktree)

        with mock.patch.object(proj, "IsDirty", return_value=False):
            with mock.patch("shutil.rmtree"):
                with mock.patch("os.path.exists", return_value=False):
                    result = proj.DeleteWorktree()

        assert result is True


@pytest.mark.unit
class TestSubmodules:
    """Test submodule-related methods."""

    def test_get_derived_subprojects(self, tmp_path):
        """Test GetDerivedSubprojects."""
        proj = _make_project(tmp_path)

        with mock.patch.object(proj, "_GetSubmodules", return_value=[]):
            result = proj.GetDerivedSubprojects()

        assert result == []

    def test_has_subprojects_false(self, tmp_path):
        """Test project without subprojects."""
        proj = _make_project(tmp_path)
        proj.has_subprojects = False

        assert proj.has_subprojects is False
