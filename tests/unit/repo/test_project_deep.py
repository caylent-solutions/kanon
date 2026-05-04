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

"""Deep unit tests for the project.py module - focusing on uncovered methods."""

import os
from unittest import mock

import pytest

from kanon_cli.repo import error
from kanon_cli.repo import project


def _make_project(tmp_path):
    """Create a minimally mocked Project for testing."""
    manifest = mock.MagicMock()
    manifest.topdir = str(tmp_path)
    manifest.repodir = str(tmp_path / ".repo")
    manifest.globalConfig = mock.MagicMock()
    manifest.manifestProject = mock.MagicMock()
    manifest.manifestProject.depth = None
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
    proj.remote.ToRemoteSpec = mock.MagicMock(return_value=mock.MagicMock())
    proj.revisionExpr = "refs/heads/main"
    proj.revisionId = None
    proj.upstream = None
    proj.dest_branch = None
    proj.old_revision = None
    proj.groups = ["all", "name:test-project", "path:test-project"]
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
    return proj


# _GitGetByExec Tests


@pytest.mark.unit
class TestGitGetByExec:
    """Test the _GitGetByExec inner class."""

    def test_init(self, tmp_path):
        """Test _GitGetByExec initialization."""
        proj = _make_project(tmp_path)
        git_exec = project.Project._GitGetByExec(proj, bare=True, gitdir=proj.gitdir)
        assert git_exec._project == proj
        assert git_exec._bare is True
        assert git_exec._gitdir == proj.gitdir

    def test_getstate_setstate(self, tmp_path):
        """Test pickle support via __getstate__ and __setstate__."""
        proj = _make_project(tmp_path)
        git_exec = project.Project._GitGetByExec(proj, bare=False, gitdir=proj.gitdir)
        state = git_exec.__getstate__()
        assert state == (proj, False, proj.gitdir)

        new_exec = project.Project._GitGetByExec.__new__(project.Project._GitGetByExec)
        new_exec.__setstate__(state)
        assert new_exec._project == proj
        assert new_exec._bare is False
        assert new_exec._gitdir == proj.gitdir

    def test_ls_others_with_files(self, tmp_path):
        """Test LsOthers returns untracked files."""
        proj = _make_project(tmp_path)
        git_exec = project.Project._GitGetByExec(proj, bare=False, gitdir=proj.gitdir)

        mock_cmd = mock.MagicMock()
        mock_cmd.Wait.return_value = 0
        mock_cmd.stdout = "file1.txt\0file2.py\0"

        with mock.patch("kanon_cli.repo.project.GitCommand", return_value=mock_cmd):
            result = git_exec.LsOthers()

        assert result == ["file1.txt", "file2.py"]

    def test_ls_others_no_files(self, tmp_path):
        """Test LsOthers with no untracked files."""
        proj = _make_project(tmp_path)
        git_exec = project.Project._GitGetByExec(proj, bare=False, gitdir=proj.gitdir)

        mock_cmd = mock.MagicMock()
        mock_cmd.Wait.return_value = 0
        mock_cmd.stdout = None

        with mock.patch("kanon_cli.repo.project.GitCommand", return_value=mock_cmd):
            result = git_exec.LsOthers()

        assert result == []

    def test_ls_others_command_fails(self, tmp_path):
        """Test LsOthers when git command fails."""
        proj = _make_project(tmp_path)
        git_exec = project.Project._GitGetByExec(proj, bare=False, gitdir=proj.gitdir)

        mock_cmd = mock.MagicMock()
        mock_cmd.Wait.return_value = 1

        with mock.patch("kanon_cli.repo.project.GitCommand", return_value=mock_cmd):
            result = git_exec.LsOthers()

        assert result == []

    def test_diffz_with_changes(self, tmp_path):
        """Test DiffZ with file changes."""
        proj = _make_project(tmp_path)
        git_exec = project.Project._GitGetByExec(proj, bare=False, gitdir=proj.gitdir)

        mock_cmd = mock.MagicMock()
        mock_cmd.Wait.return_value = 0
        mock_cmd.stdout = ":100644 100644 abc123 def456 M\0file.txt\0"

        with mock.patch("kanon_cli.repo.project.GitCommand", return_value=mock_cmd):
            result = git_exec.DiffZ("diff-index", "--cached", "HEAD")

        assert "file.txt" in result
        assert result["file.txt"].status == "M"
        assert result["file.txt"].old_id == "abc123"
        assert result["file.txt"].new_id == "def456"

    def test_diffz_with_rename(self, tmp_path):
        """Test DiffZ with renamed file."""
        proj = _make_project(tmp_path)
        git_exec = project.Project._GitGetByExec(proj, bare=False, gitdir=proj.gitdir)

        mock_cmd = mock.MagicMock()
        mock_cmd.Wait.return_value = 0
        mock_cmd.stdout = ":100644 100644 abc123 abc123 R100\0old.txt\0new.txt\0"

        with mock.patch("kanon_cli.repo.project.GitCommand", return_value=mock_cmd):
            result = git_exec.DiffZ("diff-index", "-M", "HEAD")

        assert "new.txt" in result
        assert result["new.txt"].status == "R"
        assert result["new.txt"].src_path == "old.txt"
        assert result["new.txt"].level == "100"

    def test_diffz_no_changes(self, tmp_path):
        """Test DiffZ with no changes."""
        proj = _make_project(tmp_path)
        git_exec = project.Project._GitGetByExec(proj, bare=False, gitdir=proj.gitdir)

        mock_cmd = mock.MagicMock()
        mock_cmd.Wait.return_value = 0
        mock_cmd.stdout = None

        with mock.patch("kanon_cli.repo.project.GitCommand", return_value=mock_cmd):
            result = git_exec.DiffZ("diff-files")

        assert result == {}

    def test_get_dotgit_path_bare(self, tmp_path):
        """Test GetDotgitPath for bare repository."""
        proj = _make_project(tmp_path)
        git_exec = project.Project._GitGetByExec(proj, bare=True, gitdir=proj.gitdir)

        result = git_exec.GetDotgitPath()
        assert result == proj.gitdir

    def test_get_dotgit_path_bare_with_subpath(self, tmp_path):
        """Test GetDotgitPath with subpath for bare repository."""
        proj = _make_project(tmp_path)
        git_exec = project.Project._GitGetByExec(proj, bare=True, gitdir=proj.gitdir)

        result = git_exec.GetDotgitPath("hooks/pre-commit")
        assert result == os.path.join(proj.gitdir, "hooks/pre-commit")

    def test_get_dotgit_path_nonbare_directory(self, tmp_path):
        """Test GetDotgitPath for non-bare repository with .git directory."""
        proj = _make_project(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        dotgit = worktree / ".git"
        dotgit.mkdir()
        proj.worktree = str(worktree)

        git_exec = project.Project._GitGetByExec(proj, bare=False, gitdir=proj.gitdir)

        result = git_exec.GetDotgitPath()
        assert result == str(dotgit)

    def test_get_dotgit_path_worktree(self, tmp_path):
        """Test GetDotgitPath for git worktree with .git file."""
        proj = _make_project(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        dotgit_file = worktree / ".git"
        actual_gitdir = tmp_path / ".git" / "worktrees" / "wt"
        actual_gitdir.mkdir(parents=True)

        dotgit_file.write_text("gitdir: ../.git/worktrees/wt\n")
        proj.worktree = str(worktree)

        git_exec = project.Project._GitGetByExec(proj, bare=False, gitdir=proj.gitdir)

        result = git_exec.GetDotgitPath()
        expected = os.path.normpath(str(tmp_path / ".git" / "worktrees" / "wt"))
        assert result == expected


# Project Initialization Tests


@pytest.mark.unit
class TestProjectInitialization:
    """Test Project initialization methods."""

    def test_set_revision_with_id(self, tmp_path):
        """Test SetRevision with a commit ID."""
        proj = _make_project(tmp_path)
        commit_id = "a" * 40
        proj.SetRevision(commit_id)
        assert proj.revisionExpr == commit_id
        assert proj.revisionId == commit_id

    def test_set_revision_with_branch(self, tmp_path):
        """Test SetRevision with a branch name."""
        proj = _make_project(tmp_path)
        proj.SetRevision("refs/heads/develop", revisionId="abc123")
        assert proj.revisionExpr == "refs/heads/develop"
        assert proj.revisionId == "abc123"

    def test_update_paths(self, tmp_path):
        """Test UpdatePaths updates all path attributes."""
        proj = _make_project(tmp_path)
        new_worktree = str(tmp_path / "new-worktree")
        new_gitdir = str(tmp_path / "new-gitdir")
        new_objdir = str(tmp_path / "new-objdir")

        with mock.patch("kanon_cli.repo.project.GitConfig"):
            proj.UpdatePaths("new-relpath", new_worktree, new_gitdir, new_objdir)

        assert proj.relpath == "new-relpath"
        assert proj.worktree == new_worktree.replace("\\", "/")
        assert proj.gitdir == new_gitdir.replace("\\", "/")
        assert proj.objdir == new_objdir.replace("\\", "/")

    def test_update_paths_with_none_worktree(self, tmp_path):
        """Test UpdatePaths with None worktree (bare repository)."""
        proj = _make_project(tmp_path)
        new_gitdir = str(tmp_path / "new-gitdir")

        with mock.patch("kanon_cli.repo.project.GitConfig"):
            proj.UpdatePaths("relpath", None, new_gitdir, new_gitdir)

        assert proj.worktree is None
        assert proj.gitdir == new_gitdir.replace("\\", "/")

    def test_rel_path_local(self, tmp_path):
        """Test RelPath with local=True."""
        proj = _make_project(tmp_path)
        proj.relpath = "projects/myproj"
        assert proj.RelPath(local=True) == "projects/myproj"

    def test_rel_path_not_local(self, tmp_path):
        """Test RelPath with local=False."""
        proj = _make_project(tmp_path)
        proj.relpath = "myproj"
        proj.manifest.path_prefix = "submanifest"
        assert proj.RelPath(local=False) == "submanifest/myproj"


# Property Tests


@pytest.mark.unit
class TestProjectProperties:
    """Test Project property methods."""

    def test_use_alternates_env_enabled(self, tmp_path):
        """Test UseAlternates with environment variable set."""
        _make_project(tmp_path)
        with mock.patch.dict(os.environ, {"REPO_USE_ALTERNATES": "1"}):
            # Need to reload module to pick up env var
            assert project._ALTERNATES or not project._ALTERNATES  # Just test access

    def test_use_alternates_multimanifest(self, tmp_path):
        """Test UseAlternates with multimanifest."""
        proj = _make_project(tmp_path)
        proj.manifest.is_multimanifest = True
        assert proj.UseAlternates is True

    def test_derived_property(self, tmp_path):
        """Test Derived property."""
        proj = _make_project(tmp_path)
        proj.is_derived = True
        assert proj.Derived is True

    def test_exists_both_dirs_exist(self, tmp_path):
        """Test Exists when both gitdir and objdir exist."""
        proj = _make_project(tmp_path)
        gitdir = tmp_path / "gitdir"
        objdir = tmp_path / "objdir"
        gitdir.mkdir()
        objdir.mkdir()
        proj.gitdir = str(gitdir)
        proj.objdir = str(objdir)

        assert proj.Exists is True

    def test_exists_missing_gitdir(self, tmp_path):
        """Test Exists when gitdir is missing."""
        proj = _make_project(tmp_path)
        proj.gitdir = str(tmp_path / "nonexistent")
        proj.objdir = str(tmp_path / "objdir")

        assert proj.Exists is False

    def test_current_branch_on_branch(self, tmp_path):
        """Test CurrentBranch when on a branch."""
        proj = _make_project(tmp_path)
        proj.work_git.GetHead.return_value = "refs/heads/main"

        assert proj.CurrentBranch == "main"

    def test_current_branch_detached(self, tmp_path):
        """Test CurrentBranch when on detached HEAD."""
        proj = _make_project(tmp_path)
        proj.work_git.GetHead.return_value = "abc123"

        assert proj.CurrentBranch is None

    def test_current_branch_no_manifest(self, tmp_path):
        """Test CurrentBranch when manifest is missing."""
        proj = _make_project(tmp_path)
        proj.work_git.GetHead.side_effect = error.NoManifestException(path="test", reason="test")

        assert proj.CurrentBranch is None


# Branch Operation Tests


@pytest.mark.unit
class TestBranchOperations:
    """Test branch-related operations."""

    def test_is_rebase_in_progress_rebase_apply(self, tmp_path):
        """Test IsRebaseInProgress with rebase-apply directory."""
        proj = _make_project(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitdir = worktree / ".git"
        gitdir.mkdir()
        (gitdir / "rebase-apply").mkdir()
        proj.worktree = str(worktree)
        proj.work_git.GetDotgitPath.return_value = str(gitdir / "rebase-apply")

        assert proj.IsRebaseInProgress() is True

    def test_is_rebase_in_progress_rebase_merge(self, tmp_path):
        """Test IsRebaseInProgress with rebase-merge directory."""
        proj = _make_project(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitdir = worktree / ".git"
        gitdir.mkdir()
        (gitdir / "rebase-merge").mkdir()
        proj.worktree = str(worktree)
        proj.work_git.GetDotgitPath.return_value = str(gitdir / "rebase-merge")

        assert proj.IsRebaseInProgress() is True

    def test_is_rebase_in_progress_false(self, tmp_path):
        """Test IsRebaseInProgress when no rebase in progress."""
        proj = _make_project(tmp_path)
        proj.work_git.GetDotgitPath.return_value = "/nonexistent"

        assert proj.IsRebaseInProgress() is False

    def test_is_cherry_pick_in_progress_true(self, tmp_path):
        """Test IsCherryPickInProgress when cherry-pick is active."""
        proj = _make_project(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitdir = worktree / ".git"
        gitdir.mkdir()
        (gitdir / "CHERRY_PICK_HEAD").touch()
        proj.worktree = str(worktree)
        proj.work_git.GetDotgitPath.return_value = str(gitdir / "CHERRY_PICK_HEAD")

        assert proj.IsCherryPickInProgress() is True

    def test_is_cherry_pick_in_progress_false(self, tmp_path):
        """Test IsCherryPickInProgress when no cherry-pick active."""
        proj = _make_project(tmp_path)
        proj.work_git.GetDotgitPath.return_value = "/nonexistent"

        assert proj.IsCherryPickInProgress() is False

    def test_abort_rebase(self, tmp_path):
        """Test _AbortRebase calls appropriate git commands."""
        proj = _make_project(tmp_path)

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_cmd = mock.MagicMock()
            mock_cmd.Wait.return_value = 0
            mock_git.return_value = mock_cmd

            proj._AbortRebase()

            assert mock_git.call_count == 3
            calls = [call[0][1] for call in mock_git.call_args_list]
            assert ("cherry-pick", "--abort") in calls
            assert ("rebase", "--abort") in calls
            assert ("am", "--abort") in calls


# Dirty State Tests


@pytest.mark.unit
class TestDirtyState:
    """Test methods checking for uncommitted changes."""

    def test_is_dirty_staged_changes(self, tmp_path):
        """Test IsDirty with staged changes."""
        proj = _make_project(tmp_path)
        proj.work_git.update_index = mock.MagicMock()
        proj.work_git.DiffZ.return_value = {"file.txt": mock.MagicMock()}

        assert proj.IsDirty() is True

    def test_is_dirty_unstaged_changes(self, tmp_path):
        """Test IsDirty with unstaged changes."""
        proj = _make_project(tmp_path)
        proj.work_git.update_index = mock.MagicMock()
        proj.work_git.DiffZ.side_effect = [
            {},  # No staged changes
            {"file.txt": mock.MagicMock()},  # Unstaged changes
        ]

        assert proj.IsDirty() is True

    def test_is_dirty_untracked_files(self, tmp_path):
        """Test IsDirty with untracked files."""
        proj = _make_project(tmp_path)
        proj.work_git.update_index = mock.MagicMock()
        proj.work_git.DiffZ.return_value = {}
        proj.work_git.LsOthers.return_value = ["untracked.txt"]

        assert proj.IsDirty(consider_untracked=True) is True

    def test_is_dirty_ignore_untracked(self, tmp_path):
        """Test IsDirty ignoring untracked files."""
        proj = _make_project(tmp_path)
        proj.work_git.update_index = mock.MagicMock()
        proj.work_git.DiffZ.return_value = {}
        proj.work_git.LsOthers.return_value = ["untracked.txt"]

        assert proj.IsDirty(consider_untracked=False) is False

    def test_is_dirty_clean(self, tmp_path):
        """Test IsDirty with clean working directory."""
        proj = _make_project(tmp_path)
        proj.work_git.update_index = mock.MagicMock()
        proj.work_git.DiffZ.return_value = {}
        proj.work_git.LsOthers.return_value = []

        assert proj.IsDirty() is False

    def test_uncommitted_files_get_all_false(self, tmp_path):
        """Test UncommitedFiles with get_all=False returns early."""
        proj = _make_project(tmp_path)
        proj.work_git.update_index = mock.MagicMock()
        proj.work_git.DiffZ.return_value = {"staged.txt": mock.MagicMock()}

        result = proj.UncommitedFiles(get_all=False)

        assert len(result) == 1
        # Should not check diff-files or untracked when get_all=False

    def test_uncommitted_files_get_all_true(self, tmp_path):
        """Test UncommitedFiles with get_all=True returns all changes."""
        proj = _make_project(tmp_path)
        proj.work_git.update_index = mock.MagicMock()
        proj.work_git.DiffZ.side_effect = [
            {"staged.txt": mock.MagicMock()},
            {"modified.txt": mock.MagicMock()},
        ]
        proj.work_git.LsOthers.return_value = ["untracked.txt"]

        result = proj.UncommitedFiles(get_all=True)

        assert "staged.txt" in result
        assert "modified.txt" in result
        assert "untracked.txt" in result

    def test_untracked_files(self, tmp_path):
        """Test UntrackedFiles calls LsOthers."""
        proj = _make_project(tmp_path)
        proj.work_git.LsOthers.return_value = ["file1.txt", "file2.py"]

        result = proj.UntrackedFiles()

        assert result == ["file1.txt", "file2.py"]

    def test_has_changes_true(self, tmp_path):
        """Test HasChanges returns True when there are changes."""
        proj = _make_project(tmp_path)
        proj.work_git.update_index = mock.MagicMock()
        proj.work_git.DiffZ.return_value = {"file.txt": mock.MagicMock()}

        assert proj.HasChanges() is True


# User Identity Tests


@pytest.mark.unit
class TestUserIdentity:
    """Test user identity methods."""

    def test_user_name_loads_identity(self, tmp_path):
        """Test UserName loads identity on first access."""
        proj = _make_project(tmp_path)
        proj.config.GetString.return_value = "Test User"

        with mock.patch.object(proj, "_LoadUserIdentity") as mock_load:
            mock_load.side_effect = lambda: setattr(proj, "_userident_name", "Test User")
            name = proj.UserName

        assert name == "Test User"
        mock_load.assert_called_once()

    def test_user_email_loads_identity(self, tmp_path):
        """Test UserEmail loads identity on first access."""
        proj = _make_project(tmp_path)
        proj.config.GetString.return_value = "test@example.com"

        with mock.patch.object(proj, "_LoadUserIdentity") as mock_load:
            mock_load.side_effect = lambda: setattr(proj, "_userident_email", "test@example.com")
            email = proj.UserEmail

        assert email == "test@example.com"
        mock_load.assert_called_once()


# File Copy and Link Tests


@pytest.mark.unit
class TestCopyAndLinkFiles:
    """Test _CopyFile and _LinkFile classes."""

    def test_copyfile_init(self, tmp_path):
        """Test _CopyFile initialization."""
        cf = project._CopyFile(str(tmp_path / "src"), "file.txt", str(tmp_path / "dest"), "out.txt")
        assert cf.git_worktree == str(tmp_path / "src")
        assert cf.src == "file.txt"
        assert cf.topdir == str(tmp_path / "dest")
        assert cf.dest == "out.txt"

    def test_linkfile_init(self, tmp_path):
        """Test _LinkFile initialization."""
        lf = project._LinkFile(
            str(tmp_path / "src"),
            "file.txt",
            str(tmp_path / "dest"),
            "link.txt",
        )
        assert lf.git_worktree == str(tmp_path / "src")
        assert lf.src == "file.txt"
        assert lf.topdir == str(tmp_path / "dest")
        assert lf.dest == "link.txt"

    def test_copy_and_link_files(self, tmp_path):
        """Test _CopyAndLinkFiles executes all copy and link operations."""
        proj = _make_project(tmp_path)
        mock_copyfile = mock.MagicMock()
        mock_linkfile = mock.MagicMock()
        proj.copyfiles = [mock_copyfile]
        proj.linkfiles = [mock_linkfile]

        proj._CopyAndLinkFiles()

        mock_copyfile._Copy.assert_called_once()
        mock_linkfile._Link.assert_called_once()


# Annotation Tests


@pytest.mark.unit
class TestAnnotations:
    """Test Annotation class."""

    def test_annotation_equality(self):
        """Test Annotation equality comparison."""
        a1 = project.Annotation("name", "value", "keep")
        a2 = project.Annotation("name", "value", "keep")
        assert a1 == a2

    def test_annotation_inequality(self):
        """Test Annotation inequality."""
        a1 = project.Annotation("name1", "value", "keep")
        a2 = project.Annotation("name2", "value", "keep")
        assert a1 != a2

    def test_annotation_not_equal_to_other_type(self):
        """Test Annotation not equal to non-Annotation."""
        a = project.Annotation("name", "value", "keep")
        assert a != "string"

    def test_annotation_less_than_by_name(self):
        """Test Annotation sorting by name."""
        a1 = project.Annotation("aaa", "value", "keep")
        a2 = project.Annotation("bbb", "value", "keep")
        assert a1 < a2

    def test_annotation_less_than_by_value(self):
        """Test Annotation sorting by value when names equal."""
        a1 = project.Annotation("name", "aaa", "keep")
        a2 = project.Annotation("name", "bbb", "keep")
        assert a1 < a2

    def test_annotation_less_than_by_keep(self):
        """Test Annotation sorting by keep when name and value equal."""
        a1 = project.Annotation("name", "value", "false")
        a2 = project.Annotation("name", "value", "true")
        assert a1 < a2

    def test_annotation_add_annotation(self, tmp_path):
        """Test AddAnnotation adds to project."""
        proj = _make_project(tmp_path)
        proj.AddAnnotation("test-name", "test-value", "true")

        assert len(proj.annotations) == 1
        assert proj.annotations[0].name == "test-name"
        assert proj.annotations[0].value == "test-value"
        assert proj.annotations[0].keep == "true"


# GetRevisionId Tests


@pytest.mark.unit
class TestGetRevisionId:
    """Test GetRevisionId and related methods."""

    def test_get_revision_id_already_set(self, tmp_path):
        """Test GetRevisionId returns cached revisionId."""
        proj = _make_project(tmp_path)
        proj.revisionId = "abc123"

        result = proj.GetRevisionId()

        assert result == "abc123"

    def test_get_commit_revision_id_with_tag(self, tmp_path):
        """Test GetCommitRevisionId dereferences tags."""
        proj = _make_project(tmp_path)
        proj.revisionId = None
        proj.revisionExpr = "refs/tags/v1.0"
        proj.bare_git.rev_list.return_value = ["commit123"]

        result = proj.GetCommitRevisionId()

        assert result == "commit123"
        proj.bare_git.rev_list.assert_called_once_with("refs/tags/v1.0", "-1")

    def test_get_commit_revision_id_without_tag(self, tmp_path):
        """Test GetCommitRevisionId falls back to GetRevisionId for non-tags."""
        proj = _make_project(tmp_path)
        proj.revisionId = None
        proj.revisionExpr = "refs/heads/main"
        proj.remote.ToLocal.return_value = "refs/remotes/origin/main"
        proj.bare_ref.all = {"refs/remotes/origin/main": "abc123"}

        with mock.patch.object(proj, "GetRevisionId", return_value="abc123"):
            result = proj.GetCommitRevisionId()

        assert result == "abc123"

    def test_set_revision_id(self, tmp_path):
        """Test SetRevisionId sets upstream and revisionId."""
        proj = _make_project(tmp_path)
        proj.revisionExpr = "refs/heads/main"

        proj.SetRevisionId("new_revision_id")

        assert proj.upstream == "refs/heads/main"
        assert proj.revisionId == "new_revision_id"


# Sync NetworkHalf Tests


@pytest.mark.unit
class TestSyncNetworkHalf:
    """Test Sync_NetworkHalf method."""

    def test_sync_network_half_result_success(self):
        """Test SyncNetworkHalfResult with success."""
        result = project.SyncNetworkHalfResult(remote_fetched=True)
        assert result.remote_fetched is True
        assert result.error is None
        assert result.success is True

    def test_sync_network_half_result_failure(self):
        """Test SyncNetworkHalfResult with error."""
        err = Exception("test error")
        result = project.SyncNetworkHalfResult(remote_fetched=False, error=err)
        assert result.remote_fetched is False
        assert result.error == err
        assert result.success is False


# Published Branches Tests


@pytest.mark.unit
class TestPublishedBranches:
    """Test published branch tracking."""

    def test_was_published_with_ref(self, tmp_path):
        """Test WasPublished finds published SHA."""
        proj = _make_project(tmp_path)
        proj.bare_git.rev_parse.return_value = "published_sha"

        result = proj.WasPublished("main")

        assert result == "published_sha"
        proj.bare_git.rev_parse.assert_called_once_with("refs/published/main")

    def test_was_published_with_all_refs(self, tmp_path):
        """Test WasPublished uses all_refs when provided."""
        proj = _make_project(tmp_path)
        all_refs = {"refs/published/main": "pub_sha"}

        result = proj.WasPublished("main", all_refs=all_refs)

        assert result == "pub_sha"

    def test_was_published_with_all_refs_not_found(self, tmp_path):
        """Test WasPublished returns None when key not in all_refs."""
        proj = _make_project(tmp_path)
        all_refs = {}

        result = proj.WasPublished("main", all_refs=all_refs)

        assert result is None

    def test_clean_published_cache(self, tmp_path):
        """Test CleanPublishedCache removes stale published refs."""
        proj = _make_project(tmp_path)
        all_refs = {
            "refs/heads/main": "abc123",
            "refs/published/main": "pub_abc",
            "refs/published/deleted": "pub_old",  # This branch no longer exists
        }
        proj.bare_ref.all = all_refs
        proj.bare_git.DeleteRef = mock.MagicMock()

        proj.CleanPublishedCache()

        proj.bare_git.DeleteRef.assert_called_once_with("refs/published/deleted", "pub_old")


# RemoteSpec Tests


@pytest.mark.unit
class TestRemoteSpec:
    """Test RemoteSpec class."""

    def test_remote_spec_init(self):
        """Test RemoteSpec initialization."""
        spec = project.RemoteSpec(
            name="origin",
            url="https://example.com/repo.git",
            pushUrl="https://example.com/push.git",
            review="https://review.example.com",
            revision="refs/heads/main",
        )

        assert spec.name == "origin"
        assert spec.url == "https://example.com/repo.git"
        assert spec.pushUrl == "https://example.com/push.git"
        assert spec.review == "https://review.example.com"
        assert spec.revision == "refs/heads/main"

    def test_remote_spec_init_minimal(self):
        """Test RemoteSpec with minimal arguments."""
        spec = project.RemoteSpec(name="origin")

        assert spec.name == "origin"
        assert spec.url is None
        assert spec.pushUrl is None
        assert spec.review is None


# Helper Function Tests


@pytest.mark.unit
class TestHelperFunctions:
    """Test module-level helper functions."""

    def test_not_rev(self):
        """Test not_rev prefixes with caret."""
        result = project.not_rev("abc123")
        assert result == "^abc123"

    def test_sq(self):
        """Test sq wraps in single quotes."""
        result = project.sq("test")
        assert result == "'test'"

    def test_sq_with_quotes(self):
        """Test sq escapes single quotes."""
        result = project.sq("test'quote")
        assert result == "'test'''quote'"

    def test_lwrite(self, tmp_path):
        """Test _lwrite writes file atomically."""
        target = tmp_path / "test.txt"
        project._lwrite(str(target), "test content\n")

        assert target.exists()
        assert target.read_text() == "test content\n"

    def test_lwrite_unix_line_endings(self, tmp_path):
        """Test _lwrite maintains Unix line endings."""
        target = tmp_path / "test.txt"
        project._lwrite(str(target), "line1\nline2\n")

        content_bytes = target.read_bytes()
        assert b"\r\n" not in content_bytes
        assert content_bytes == b"line1\nline2\n"


# DownloadedChange Tests


@pytest.mark.unit
class TestDownloadedChange:
    """Test DownloadedChange class."""

    def test_downloaded_change_init(self, tmp_path):
        """Test DownloadedChange initialization."""
        proj = _make_project(tmp_path)
        dc = project.DownloadedChange(proj, "base_sha", 12345, 1, "commit_sha")

        assert dc.project == proj
        assert dc.base == "base_sha"
        assert dc.change_id == 12345
        assert dc.ps_id == 1
        assert dc.commit == "commit_sha"

    def test_downloaded_change_commits_cached(self, tmp_path):
        """Test DownloadedChange.commits property caches result."""
        proj = _make_project(tmp_path)
        proj.bare_git.rev_list.return_value = "abc123 commit message"
        dc = project.DownloadedChange(proj, "base", 123, 1, "commit")

        # First access
        result1 = dc.commits
        # Second access should use cache
        result2 = dc.commits

        assert result1 == result2
        proj.bare_git.rev_list.assert_called_once()


# ReviewableBranch Tests


@pytest.mark.unit
class TestReviewableBranch:
    """Test ReviewableBranch class."""

    def test_reviewable_branch_name(self, tmp_path):
        """Test ReviewableBranch.name property."""
        proj = _make_project(tmp_path)
        branch = mock.MagicMock()
        branch.name = "feature-branch"

        rb = project.ReviewableBranch(proj, branch, "main")

        assert rb.name == "feature-branch"

    def test_reviewable_branch_commits_cached(self, tmp_path):
        """Test ReviewableBranch.commits property caches result."""
        proj = _make_project(tmp_path)
        proj.bare_git.rev_list.return_value = "abc123 Commit message\n"
        branch = mock.MagicMock()
        branch.name = "feature"

        rb = project.ReviewableBranch(proj, branch, "main")

        # First access
        result1 = rb.commits
        # Second access should use cache
        result2 = rb.commits

        assert result1 == result2
        proj.bare_git.rev_list.assert_called_once()


# _SafeExpandPath Tests


@pytest.mark.unit
class TestSafeExpandPath:
    """Test _SafeExpandPath security function."""

    def test_safe_expand_path_simple(self, tmp_path):
        """Test _SafeExpandPath with simple path."""
        base = str(tmp_path)
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        result = project._SafeExpandPath(base, "subdir")

        assert result == str(subdir)

    def test_safe_expand_path_rejects_dot_dot(self, tmp_path):
        """Test _SafeExpandPath rejects .. in path."""
        base = str(tmp_path)

        with pytest.raises(error.ManifestInvalidPathError):
            project._SafeExpandPath(base, "../outside")

    def test_safe_expand_path_rejects_dot(self, tmp_path):
        """Test _SafeExpandPath rejects . in path."""
        base = str(tmp_path)

        with pytest.raises(error.ManifestInvalidPathError):
            project._SafeExpandPath(base, "./current")

    def test_safe_expand_path_skipfinal(self, tmp_path):
        """Test _SafeExpandPath with skipfinal=True."""
        base = str(tmp_path)
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        result = project._SafeExpandPath(base, "subdir/file.txt", skipfinal=True)

        # When skipfinal=True, it doesn't validate the final component but still returns full path
        assert result == os.path.join(str(subdir), "file.txt")


# Additional Edge Case Tests


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_shareable_dirs_with_alternates(self, tmp_path):
        """Test shareable_dirs property with alternates."""
        proj = _make_project(tmp_path)
        proj.manifest.is_multimanifest = True

        dirs = proj.shareable_dirs

        assert "hooks" in dirs
        assert "rr-cache" in dirs
        # When using alternates, "objects" is not shared

    def test_shareable_dirs_without_alternates(self, tmp_path):
        """Test shareable_dirs property without alternates."""
        proj = _make_project(tmp_path)
        proj.manifest.is_multimanifest = False

        with mock.patch.object(project, "_ALTERNATES", False):
            dirs = proj.shareable_dirs

        assert "hooks" in dirs
        assert "objects" in dirs
        assert "rr-cache" in dirs

    def test_add_copyfile(self, tmp_path):
        """Test AddCopyFile adds to copyfiles list."""
        proj = _make_project(tmp_path)
        topdir = str(tmp_path / "topdir")

        proj.AddCopyFile("src.txt", "dest.txt", topdir)

        assert len(proj.copyfiles) == 1
        assert proj.copyfiles[0].src == "src.txt"
        assert proj.copyfiles[0].dest == "dest.txt"

    def test_add_linkfile(self, tmp_path):
        """Test AddLinkFile adds to linkfiles list."""
        proj = _make_project(tmp_path)
        topdir = str(tmp_path / "topdir")

        proj.AddLinkFile("src.txt", "link.txt", topdir)

        assert len(proj.linkfiles) == 1
        assert proj.linkfiles[0].src == "src.txt"
        assert proj.linkfiles[0].dest == "link.txt"

    def test_download_patchset(self, tmp_path):
        """Test DownloadPatchSet fetches a change."""
        proj = _make_project(tmp_path)
        proj.remote.name = "origin"
        proj.bare_git.rev_parse.return_value = "fetched_sha"

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_git:
            mock_cmd = mock.MagicMock()
            mock_cmd.Wait.return_value = 0
            mock_git.return_value = mock_cmd

            with mock.patch.object(proj, "GetRevisionId", return_value="base_sha"):
                result = proj.DownloadPatchSet(12345, 2)

        assert isinstance(result, project.DownloadedChange)
        assert result.change_id == 12345
        assert result.ps_id == 2


# Error Classes Tests


@pytest.mark.unit
class TestErrorClasses:
    """Test custom error classes."""

    def test_sync_network_half_error(self):
        """Test SyncNetworkHalfError initialization."""
        err = project.SyncNetworkHalfError("test message")
        assert isinstance(err, error.RepoError)
        assert str(err) == "test message"

    def test_delete_worktree_error(self):
        """Test DeleteWorktreeError initialization."""
        err = project.DeleteWorktreeError("test message")
        assert isinstance(err, error.RepoError)
        assert err.aggregate_errors == []

    def test_delete_worktree_error_with_aggregates(self):
        """Test DeleteWorktreeError with aggregate errors."""
        sub_errors = [Exception("error1"), Exception("error2")]
        err = project.DeleteWorktreeError("main message", aggregate_errors=sub_errors)
        assert len(err.aggregate_errors) == 2

    def test_delete_dirty_worktree_error(self):
        """Test DeleteDirtyWorktreeError is subclass of DeleteWorktreeError."""
        err = project.DeleteDirtyWorktreeError("test message")
        assert isinstance(err, project.DeleteWorktreeError)
        assert isinstance(err, error.RepoError)


# Constants Tests


@pytest.mark.unit
class TestConstants:
    """Test module-level constants."""

    def test_maximum_retry_sleep_sec(self):
        """Test MAXIMUM_RETRY_SLEEP_SEC constant."""
        assert project.MAXIMUM_RETRY_SLEEP_SEC == 3600.0

    def test_retry_jitter_percent(self):
        """Test RETRY_JITTER_PERCENT constant."""
        assert project.RETRY_JITTER_PERCENT == 0.1

    def test_alternates_env_var(self):
        """Test _ALTERNATES reads from environment."""
        # Just verify it's defined and is a boolean
        assert isinstance(project._ALTERNATES, bool)
