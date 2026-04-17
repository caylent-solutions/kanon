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

"""Comprehensive unit tests for project.py to boost code coverage."""

import os
from unittest import mock

import pytest

from kanon_cli.repo import project
from kanon_cli.repo.error import GitError
from kanon_cli.repo.error import ManifestInvalidPathError
from kanon_cli.repo.error import ManifestInvalidRevisionError
from kanon_cli.repo.error import NoManifestException
from kanon_cli.repo.project import LocalSyncFail


@pytest.mark.unit
class TestLwrite:
    """Test _lwrite function."""

    def test_lwrite_creates_file(self, tmp_path):
        """Test that _lwrite creates a file with Unix line endings."""
        target = tmp_path / "test.txt"
        content = "line1\nline2\nline3"
        project._lwrite(str(target), content)

        # Read in binary mode to verify line endings
        with open(target, "rb") as f:
            data = f.read()
        assert data == b"line1\nline2\nline3"

    def test_lwrite_overwrites_existing(self, tmp_path):
        """Test that _lwrite overwrites existing files."""
        target = tmp_path / "test.txt"
        target.write_text("old content")

        project._lwrite(str(target), "new content")

        assert target.read_text() == "new content"

    def test_lwrite_removes_lock_on_error(self, tmp_path):
        """Test that lock file is removed on error."""
        target = tmp_path / "test.txt"
        lock_file = tmp_path / "test.txt.lock"

        with mock.patch("kanon_cli.repo.platform_utils.rename") as mock_rename:
            mock_rename.side_effect = OSError("Simulated error")

            with pytest.raises(OSError):
                project._lwrite(str(target), "content")

            # Lock file should be removed
            assert not lock_file.exists()


@pytest.mark.unit
class TestSafeExpandPath:
    """Test _SafeExpandPath function."""

    def test_safe_expand_simple_path(self, tmp_path):
        """Test expanding a simple safe path."""
        result = project._SafeExpandPath(str(tmp_path), "foo/bar")
        expected = os.path.join(str(tmp_path), "foo", "bar")
        assert result == expected

    def test_safe_expand_rejects_dot_dot(self, tmp_path):
        """Test that .. is rejected."""
        with pytest.raises(ManifestInvalidPathError, match=r'"\.\." not allowed'):
            project._SafeExpandPath(str(tmp_path), "foo/../bar")

    def test_safe_expand_rejects_dot(self, tmp_path):
        """Test that . in path is rejected."""
        with pytest.raises(ManifestInvalidPathError, match=r'"\." not allowed'):
            project._SafeExpandPath(str(tmp_path), "foo/./bar")

    def test_safe_expand_skipfinal(self, tmp_path):
        """Test skipfinal parameter."""
        result = project._SafeExpandPath(str(tmp_path), "foo/bar/baz", skipfinal=True)
        expected = os.path.join(str(tmp_path), "foo", "bar", "baz")
        assert result == expected

    def test_safe_expand_rejects_symlink_traversal(self, tmp_path):
        """Test that symlinks in path are rejected."""
        link_dir = tmp_path / "link"
        target_dir = tmp_path / "target"
        target_dir.mkdir()

        if hasattr(os, "symlink"):
            link_dir.symlink_to(target_dir)
            with pytest.raises(ManifestInvalidPathError, match="traversing symlinks"):
                project._SafeExpandPath(str(tmp_path), "link/foo")


@pytest.mark.unit
class TestStatusColoring:
    """Test StatusColoring class."""

    def test_status_coloring_init(self):
        """Test StatusColoring initialization."""
        config = mock.MagicMock()
        coloring = project.StatusColoring(config)

        assert coloring.project is not None
        assert coloring.branch is not None
        assert coloring.nobranch is not None


@pytest.mark.unit
class TestDiffColoring:
    """Test DiffColoring class."""

    def test_diff_coloring_init(self):
        """Test DiffColoring initialization."""
        config = mock.MagicMock()
        coloring = project.DiffColoring(config)

        assert coloring.project is not None
        assert coloring.fail is not None


@pytest.mark.unit
class TestAnnotation:
    """Test Annotation class."""

    def test_annotation_equality(self):
        """Test Annotation equality comparison."""
        ann1 = project.Annotation("name", "value", True)
        ann2 = project.Annotation("name", "value", True)
        ann3 = project.Annotation("name", "value", False)

        assert ann1 == ann2
        assert ann1 != ann3

    def test_annotation_equality_with_non_annotation(self):
        """Test Annotation equality with non-Annotation object."""
        ann = project.Annotation("name", "value", True)
        assert ann != "not an annotation"
        assert ann != 123

    def test_annotation_less_than_by_name(self):
        """Test Annotation less than comparison by name."""
        ann1 = project.Annotation("aaa", "value", True)
        ann2 = project.Annotation("bbb", "value", True)

        assert ann1 < ann2
        assert not ann2 < ann1

    def test_annotation_less_than_by_value(self):
        """Test Annotation less than comparison by value."""
        ann1 = project.Annotation("name", "aaa", True)
        ann2 = project.Annotation("name", "bbb", True)

        assert ann1 < ann2

    def test_annotation_less_than_by_keep(self):
        """Test Annotation less than comparison by keep."""
        ann1 = project.Annotation("name", "value", False)
        ann2 = project.Annotation("name", "value", True)

        assert ann1 < ann2

    def test_annotation_less_than_invalid_type(self):
        """Test Annotation less than with invalid type raises ValueError."""
        ann = project.Annotation("name", "value", True)

        with pytest.raises(ValueError, match="not between two Annotation"):
            ann < "not an annotation"


@pytest.mark.unit
class TestCopyFile:
    """Test _CopyFile class."""

    def test_copyfile_copy_new_file(self, tmp_path):
        """Test copying a new file."""
        git_worktree = tmp_path / "git"
        git_worktree.mkdir()
        src_file = git_worktree / "source.txt"
        src_file.write_text("content")

        topdir = tmp_path / "top"
        topdir.mkdir()

        cf = project._CopyFile(str(git_worktree), "source.txt", str(topdir), "dest.txt")
        cf._Copy()

        dest_file = topdir / "dest.txt"
        assert dest_file.exists()
        assert dest_file.read_text() == "content"

    def test_copyfile_updates_out_of_date(self, tmp_path):
        """Test updating an out-of-date file."""
        git_worktree = tmp_path / "git"
        git_worktree.mkdir()
        src_file = git_worktree / "source.txt"
        src_file.write_text("new content")

        topdir = tmp_path / "top"
        topdir.mkdir()
        dest_file = topdir / "dest.txt"
        dest_file.write_text("old content")

        # Make sure the dest file timestamp is older
        import time

        time.sleep(0.01)
        src_file.write_text("new content")

        cf = project._CopyFile(str(git_worktree), "source.txt", str(topdir), "dest.txt")
        cf._Copy()

        assert dest_file.read_text() == "new content"

    def test_copyfile_creates_dest_dir(self, tmp_path):
        """Test that destination directory is created if needed."""
        git_worktree = tmp_path / "git"
        git_worktree.mkdir()
        src_file = git_worktree / "source.txt"
        src_file.write_text("content")

        topdir = tmp_path / "top"
        topdir.mkdir()

        cf = project._CopyFile(str(git_worktree), "source.txt", str(topdir), "subdir/dest.txt")
        cf._Copy()

        dest_file = topdir / "subdir" / "dest.txt"
        assert dest_file.exists()

    def test_copyfile_rejects_directory_source(self, tmp_path):
        """Test that copying from directory raises error."""
        git_worktree = tmp_path / "git"
        git_worktree.mkdir()
        src_dir = git_worktree / "source"
        src_dir.mkdir()

        topdir = tmp_path / "top"
        topdir.mkdir()

        cf = project._CopyFile(str(git_worktree), "source", str(topdir), "dest")

        with pytest.raises(ManifestInvalidPathError, match="copying from directory"):
            cf._Copy()

    def test_copyfile_rejects_directory_dest(self, tmp_path):
        """Test that copying to directory raises error."""
        git_worktree = tmp_path / "git"
        git_worktree.mkdir()
        src_file = git_worktree / "source.txt"
        src_file.write_text("content")

        topdir = tmp_path / "top"
        topdir.mkdir()
        dest_dir = topdir / "dest"
        dest_dir.mkdir()

        cf = project._CopyFile(str(git_worktree), "source.txt", str(topdir), "dest")

        with pytest.raises(ManifestInvalidPathError, match="copying to directory"):
            cf._Copy()


@pytest.mark.unit
class TestLinkFile:
    """Test _LinkFile class."""

    def test_linkfile_simple_link(self, tmp_path):
        """Test creating a simple symlink."""
        git_worktree = tmp_path / "git"
        git_worktree.mkdir()
        src_file = git_worktree / "source.txt"
        src_file.write_text("content")

        topdir = tmp_path / "top"
        topdir.mkdir()

        lf = project._LinkFile(str(git_worktree), "source.txt", str(topdir), "link.txt")
        lf._Link()

        link_file = topdir / "link.txt"
        assert link_file.is_symlink()

    def test_linkfile_dot_source(self, tmp_path):
        """Test linking with . as source."""
        git_worktree = tmp_path / "git"
        git_worktree.mkdir()

        topdir = tmp_path / "top"
        topdir.mkdir()

        lf = project._LinkFile(str(git_worktree), ".", str(topdir), "link")
        lf._Link()

        link = topdir / "link"
        assert link.is_symlink()

    def test_linkfile_absolute_dest(self, tmp_path):
        """Test linking with absolute destination."""
        git_worktree = tmp_path / "git"
        git_worktree.mkdir()
        src_file = git_worktree / "source.txt"
        src_file.write_text("content")

        topdir = tmp_path / "top"
        topdir.mkdir()
        dest_dir = tmp_path / "absolute"
        dest_dir.mkdir()
        abs_dest = dest_dir / "link.txt"

        lf = project._LinkFile(str(git_worktree), "source.txt", str(topdir), str(abs_dest))
        lf._Link()

        assert abs_dest.is_symlink()

    def test_linkfile_absolute_dest_rejects_dotdot(self, tmp_path):
        """Test that absolute dest with .. is rejected."""
        git_worktree = tmp_path / "git"
        git_worktree.mkdir()

        topdir = tmp_path / "top"
        topdir.mkdir()

        lf = project._LinkFile(str(git_worktree), "source.txt", str(topdir), "/foo/../bar")

        with pytest.raises(ManifestInvalidPathError, match=r'"\.\." not allowed'):
            lf._Link()


@pytest.mark.unit
class TestDownloadedChange:
    """Test DownloadedChange class."""

    def test_downloaded_change_commits_cached(self):
        """Test that commits are cached."""
        mock_project = mock.MagicMock()
        mock_project.bare_git.rev_list.return_value = ["commit1", "commit2"]

        dc = project.DownloadedChange(mock_project, "base", "change_id", "ps_id", "commit")

        # First call
        commits1 = dc.commits
        # Second call should use cache
        commits2 = dc.commits

        assert commits1 == commits2
        mock_project.bare_git.rev_list.assert_called_once()


@pytest.mark.unit
class TestReviewableBranch:
    """Test ReviewableBranch class."""

    def test_reviewable_branch_name(self):
        """Test ReviewableBranch name property."""
        mock_project = mock.MagicMock()
        mock_branch = mock.MagicMock()
        mock_branch.name = "test-branch"

        rb = project.ReviewableBranch(mock_project, mock_branch, "base")

        assert rb.name == "test-branch"

    def test_reviewable_branch_commits_no_base(self):
        """Test commits when base doesn't exist."""
        mock_project = mock.MagicMock()
        mock_project.bare_git.rev_list.side_effect = GitError("ref not found")
        mock_project.bare_git.rev_parse.side_effect = GitError("ref not found")

        mock_branch = mock.MagicMock()
        mock_branch.name = "test-branch"

        rb = project.ReviewableBranch(mock_project, mock_branch, "base")

        # Should return empty list when base doesn't exist
        commits = rb.commits
        assert commits == []

    def test_reviewable_branch_commits_with_base(self):
        """Test commits when base exists."""
        mock_project = mock.MagicMock()
        mock_project.bare_git.rev_list.return_value = ["commit1", "commit2"]
        mock_project.bare_git.rev_parse.return_value = "base_sha"

        mock_branch = mock.MagicMock()
        mock_branch.name = "test-branch"

        rb = project.ReviewableBranch(mock_project, mock_branch, "base")

        commits = rb.commits
        assert commits == ["commit1", "commit2"]

    def test_reviewable_branch_unabbrev_commits(self):
        """Test unabbrev_commits property."""
        mock_project = mock.MagicMock()
        mock_project.bare_git.rev_list.return_value = [
            "abcdef1234567890",
            "1234567890abcdef",
        ]

        mock_branch = mock.MagicMock()
        mock_branch.name = "test-branch"

        rb = project.ReviewableBranch(mock_project, mock_branch, "base")

        unabbrev = rb.unabbrev_commits
        assert "abcdef12" in unabbrev
        assert unabbrev["abcdef12"] == "abcdef1234567890"

    def test_reviewable_branch_date(self):
        """Test date property."""
        mock_project = mock.MagicMock()
        mock_project.bare_git.log.return_value = "2024-01-01 12:00:00"

        mock_branch = mock.MagicMock()
        mock_branch.name = "test-branch"

        rb = project.ReviewableBranch(mock_project, mock_branch, "base")

        date = rb.date
        assert date == "2024-01-01 12:00:00"

    def test_reviewable_branch_base_exists_true(self):
        """Test base_exists when base exists."""
        mock_project = mock.MagicMock()
        mock_project.bare_git.rev_parse.return_value = "base_sha"

        mock_branch = mock.MagicMock()
        mock_branch.name = "test-branch"

        rb = project.ReviewableBranch(mock_project, mock_branch, "base")

        assert rb.base_exists is True

    def test_reviewable_branch_base_exists_false(self):
        """Test base_exists when base doesn't exist."""
        mock_project = mock.MagicMock()
        mock_project.bare_git.rev_parse.side_effect = GitError("ref not found")

        mock_branch = mock.MagicMock()
        mock_branch.name = "test-branch"

        rb = project.ReviewableBranch(mock_project, mock_branch, "base")

        assert rb.base_exists is False

    def test_reviewable_branch_upload_for_review(self):
        """Test UploadForReview delegates to project."""
        mock_project = mock.MagicMock()
        mock_branch = mock.MagicMock()
        mock_branch.name = "test-branch"

        rb = project.ReviewableBranch(mock_project, mock_branch, "base")

        rb.UploadForReview(
            people=(["reviewer@example.com"], ["cc@example.com"]),
            dryrun=True,
            topic="test-topic",
        )

        mock_project.UploadForReview.assert_called_once()

    def test_reviewable_branch_get_published_refs(self):
        """Test GetPublishedRefs method."""
        mock_project = mock.MagicMock()
        mock_project.UserEmail = "user@example.com"
        mock_project.bare_git.ls_remote.return_value = "sha1 refs/changes/01/1/1\nsha2 refs/changes/02/2/1\ninvalid\n"

        mock_branch = mock.MagicMock()
        mock_branch.name = "test-branch"
        mock_branch.remote.SshReviewUrl.return_value = "ssh://review.example.com"

        rb = project.ReviewableBranch(mock_project, mock_branch, "base")

        refs = rb.GetPublishedRefs()
        assert refs["sha1"] == "refs/changes/01/1/1"
        assert refs["sha2"] == "refs/changes/02/2/1"
        assert len(refs) == 2


@pytest.mark.unit
class TestProjectInit:
    """Test Project initialization."""

    def test_project_shareable_dirs_with_alternates(self):
        """Test shareable_dirs with UseAlternates."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.is_multimanifest = True
        manifest.globalConfig = mock.MagicMock()

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(
                manifest=manifest,
                name="test/project",
                remote=mock.MagicMock(),
                gitdir="/tmp/test.git",
                objdir="/tmp/test-objects.git",
                worktree="/tmp/test",
                relpath="test",
                revisionExpr="main",
                revisionId=None,
            )

        assert proj.shareable_dirs == ["hooks", "rr-cache"]

    def test_project_shareable_dirs_without_alternates(self):
        """Test shareable_dirs without UseAlternates."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.is_multimanifest = False
        manifest.globalConfig = mock.MagicMock()

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            with mock.patch.dict(os.environ, {"REPO_USE_ALTERNATES": "0"}):
                proj = project.Project(
                    manifest=manifest,
                    name="test/project",
                    remote=mock.MagicMock(),
                    gitdir="/tmp/test.git",
                    objdir="/tmp/test-objects.git",
                    worktree="/tmp/test",
                    relpath="test",
                    revisionExpr="main",
                    revisionId=None,
                )

        assert proj.shareable_dirs == ["hooks", "objects", "rr-cache"]


@pytest.mark.unit
class TestProjectMethods:
    """Test various Project methods."""

    def _make_project(self, **kwargs):
        """Create a minimal mock Project for testing."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = "/tmp/test-topdir"
        manifest.repodir = "/tmp/test-topdir/.repo"
        manifest.globalConfig = mock.MagicMock()

        defaults = {
            "manifest": manifest,
            "name": "test/project",
            "remote": mock.MagicMock(),
            "gitdir": "/tmp/test-topdir/.repo/projects/test/project.git",
            "objdir": "/tmp/test-topdir/.repo/project-objects/test/project.git",
            "worktree": "/tmp/test-topdir/test/project",
            "relpath": "test/project",
            "revisionExpr": "refs/heads/main",
            "revisionId": None,
        }
        defaults.update(kwargs)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(**defaults)
        return proj

    def test_project_relpath_local(self):
        """Test RelPath with local=True."""
        proj = self._make_project()
        assert proj.RelPath(local=True) == "test/project"

    def test_project_relpath_not_local(self):
        """Test RelPath with local=False."""
        proj = self._make_project()
        proj.manifest.path_prefix = "submanifest"

        result = proj.RelPath(local=False)
        assert result == os.path.join("submanifest", "test/project")

    def test_project_set_revision_with_id(self):
        """Test SetRevision with an ID."""
        proj = self._make_project()

        with mock.patch("kanon_cli.repo.project.IsId", return_value=True):
            proj.SetRevision("abcdef1234567890")
            assert proj.revisionId == "abcdef1234567890"

    def test_project_set_revision_with_branch(self):
        """Test SetRevision with a branch name."""
        proj = self._make_project()

        with mock.patch("kanon_cli.repo.project.IsId", return_value=False):
            proj.SetRevision("feature-branch", revisionId="sha123")

        assert proj.revisionExpr == "feature-branch"
        assert proj.revisionId == "sha123"

    def test_project_get_revision_id_cached(self):
        """Test GetRevisionId returns cached value."""
        proj = self._make_project(revisionId="cached_sha")

        result = proj.GetRevisionId()
        assert result == "cached_sha"

    def test_project_get_revision_id_from_refs(self):
        """Test GetRevisionId from all_refs."""
        proj = self._make_project()
        proj.remote.name = "origin"

        mock_remote = mock.MagicMock()
        mock_remote.ToLocal.return_value = "refs/remotes/origin/main"
        proj.config.GetRemote = mock.MagicMock(return_value=mock_remote)

        all_refs = {"refs/remotes/origin/main": "sha123"}

        result = proj.GetRevisionId(all_refs)
        assert result == "sha123"

    def test_project_get_revision_id_from_git(self):
        """Test GetRevisionId from git rev-parse."""
        proj = self._make_project()
        proj.remote.name = "origin"

        mock_remote = mock.MagicMock()
        mock_remote.ToLocal.return_value = "refs/remotes/origin/main"
        proj.config.GetRemote = mock.MagicMock(return_value=mock_remote)

        proj.bare_git.rev_parse = mock.MagicMock(return_value="sha123")

        result = proj.GetRevisionId()
        assert result == "sha123"

    def test_project_get_revision_id_not_found(self):
        """Test GetRevisionId raises error when revision not found."""
        proj = self._make_project()
        proj.remote.name = "origin"

        mock_remote = mock.MagicMock()
        mock_remote.ToLocal.return_value = "refs/remotes/origin/main"
        proj.config.GetRemote = mock.MagicMock(return_value=mock_remote)

        proj.bare_git.rev_parse = mock.MagicMock(side_effect=GitError("not found"))

        with pytest.raises(ManifestInvalidRevisionError, match="not found"):
            proj.GetRevisionId()

    def test_project_has_changes_true(self):
        """Test HasChanges returns True when there are changes."""
        proj = self._make_project()
        proj.work_git.update_index = mock.MagicMock()
        proj.work_git.DiffZ = mock.MagicMock(return_value={"file.txt": None})

        assert proj.HasChanges() is True

    def test_project_has_changes_false(self):
        """Test HasChanges returns False when there are no changes."""
        proj = self._make_project()
        proj.work_git.update_index = mock.MagicMock()
        proj.work_git.DiffZ = mock.MagicMock(return_value={})
        proj.work_git.LsOthers = mock.MagicMock(return_value=[])

        assert proj.HasChanges() is False

    def test_project_print_work_tree_status_missing(self, capsys):
        """Test PrintWorkTreeStatus when worktree is missing."""
        proj = self._make_project()

        with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=False):
            proj.PrintWorkTreeStatus()

        captured = capsys.readouterr()
        assert "missing" in captured.out

    def test_project_print_work_tree_status_clean(self):
        """Test PrintWorkTreeStatus returns CLEAN on detached HEAD with no changes."""
        proj = self._make_project()
        proj.work_git.update_index = mock.MagicMock()
        proj.work_git.DiffZ = mock.MagicMock(return_value={})
        proj.work_git.LsOthers = mock.MagicMock(return_value=[])
        # Detached HEAD (not refs/heads/...)
        proj.work_git.GetHead = mock.MagicMock(return_value="1234567890abcdef")
        proj.IsRebaseInProgress = mock.MagicMock(return_value=False)

        with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=True):
            result = proj.PrintWorkTreeStatus()

        assert result == "CLEAN"

    def test_project_print_work_tree_status_dirty_quiet(self, capsys):
        """Test PrintWorkTreeStatus in quiet mode."""
        proj = self._make_project()
        proj.work_git.update_index = mock.MagicMock()
        proj.work_git.DiffZ = mock.MagicMock(return_value={"file.txt": mock.MagicMock(status="M")})
        proj.work_git.LsOthers = mock.MagicMock(return_value=[])
        proj.work_git.GetHead = mock.MagicMock(return_value="refs/heads/main")
        proj.IsRebaseInProgress = mock.MagicMock(return_value=False)

        with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=True):
            result = proj.PrintWorkTreeStatus(quiet=True)

        assert result == "DIRTY"

    def test_project_print_work_tree_status_no_branch(self, capsys):
        """Test PrintWorkTreeStatus with no current branch."""
        proj = self._make_project()
        proj.work_git.update_index = mock.MagicMock()

        mock_di = mock.MagicMock()
        mock_di.keys.return_value = []
        proj.work_git.DiffZ = mock.MagicMock(return_value=mock_di)
        proj.work_git.LsOthers = mock.MagicMock(return_value=[])
        proj.work_git.GetHead = mock.MagicMock(return_value="1234567890abcdef")
        proj.IsRebaseInProgress = mock.MagicMock(return_value=False)

        with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=True):
            result = proj.PrintWorkTreeStatus()

        captured = capsys.readouterr()
        assert "NO BRANCH" in captured.out or result == "DIRTY"

    def test_project_print_work_tree_status_rebase_in_progress(self, capsys):
        """Test PrintWorkTreeStatus with rebase in progress."""
        proj = self._make_project()
        proj.work_git.update_index = mock.MagicMock()
        proj.work_git.DiffZ = mock.MagicMock(return_value={})
        proj.work_git.LsOthers = mock.MagicMock(return_value=[])
        proj.work_git.GetHead = mock.MagicMock(return_value="refs/heads/main")
        proj.IsRebaseInProgress = mock.MagicMock(return_value=True)

        with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=True):
            result = proj.PrintWorkTreeStatus()

        captured = capsys.readouterr()
        assert "rebase" in captured.out or result == "DIRTY"

    def test_project_print_work_tree_diff_success(self):
        """Test PrintWorkTreeDiff returns True on success."""
        proj = self._make_project()

        mock_git_cmd = mock.MagicMock()
        mock_git_cmd.Wait.return_value = 0
        mock_git_cmd.stdout = "diff output"

        with mock.patch("kanon_cli.repo.project.GitCommand", return_value=mock_git_cmd):
            result = proj.PrintWorkTreeDiff()

        assert result is True

    def test_project_print_work_tree_diff_failure(self):
        """Test PrintWorkTreeDiff returns False on git error."""
        proj = self._make_project()

        with mock.patch("kanon_cli.repo.project.GitCommand", side_effect=GitError("diff failed")):
            result = proj.PrintWorkTreeDiff()

        assert result is False

    def test_project_print_work_tree_diff_absolute_paths(self):
        """Test PrintWorkTreeDiff with absolute_paths=True."""
        proj = self._make_project()

        mock_git_cmd = mock.MagicMock()
        mock_git_cmd.Wait.return_value = 0
        mock_git_cmd.stdout = None

        with mock.patch("kanon_cli.repo.project.GitCommand", return_value=mock_git_cmd) as mock_cmd:
            proj.PrintWorkTreeDiff(absolute_paths=True)

        # Check that absolute path options were added to command
        call_args = mock_cmd.call_args[0][1]
        assert any("--src-prefix" in arg for arg in call_args)

    def test_project_extract_archive_success(self, tmp_path):
        """Test _ExtractArchive succeeds."""
        proj = self._make_project()

        # Create a simple tar file
        tar_path = tmp_path / "test.tar"
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()

        # Create a file to tar
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        import tarfile

        with tarfile.open(tar_path, "w") as tar:
            tar.add(test_file, arcname="test.txt")

        result = proj._ExtractArchive(str(tar_path), path=str(extract_dir))
        assert result is True

    def test_project_extract_archive_failure(self, tmp_path):
        """Test _ExtractArchive handles errors."""
        proj = self._make_project()

        tar_path = tmp_path / "nonexistent.tar"

        result = proj._ExtractArchive(str(tar_path))
        assert result is False

    def test_project_encode_patchset_description(self):
        """Test _encode_patchset_description."""
        result = project.Project._encode_patchset_description("Test Message")
        assert result == "Test_Message"

        result = project.Project._encode_patchset_description("Test & Message!")
        assert "Test" in result
        assert "_" in result


@pytest.mark.unit
class TestProjectGetCommitRevisionId:
    """Test Project.GetCommitRevisionId method."""

    def _make_project(self, **kwargs):
        """Create a minimal mock Project."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.globalConfig = mock.MagicMock()

        defaults = {
            "manifest": manifest,
            "name": "test/project",
            "remote": mock.MagicMock(),
            "gitdir": "/tmp/test.git",
            "objdir": "/tmp/test-objects.git",
            "worktree": "/tmp/test",
            "relpath": "test",
            "revisionExpr": "main",
            "revisionId": None,
        }
        defaults.update(kwargs)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(**defaults)
        return proj

    def test_get_commit_revision_id_cached(self):
        """Test GetCommitRevisionId with cached revisionId."""
        proj = self._make_project(revisionId="cached_sha")

        result = proj.GetCommitRevisionId()
        assert result == "cached_sha"

    def test_get_commit_revision_id_non_tag(self):
        """Test GetCommitRevisionId with non-tag revision."""
        proj = self._make_project(revisionExpr="refs/heads/main")

        with mock.patch.object(proj, "GetRevisionId", return_value="sha123"):
            with mock.patch.object(
                type(proj),
                "_allrefs",
                new_callable=mock.PropertyMock,
                return_value={},
            ):
                result = proj.GetCommitRevisionId()

        assert result == "sha123"

    def test_get_commit_revision_id_tag(self):
        """Test GetCommitRevisionId with tag revision."""
        proj = self._make_project(revisionExpr="refs/tags/v1.0")
        proj.bare_git.rev_list = mock.MagicMock(return_value=["commit_sha"])

        result = proj.GetCommitRevisionId()
        assert result == "commit_sha"

    def test_get_commit_revision_id_tag_not_found(self):
        """Test GetCommitRevisionId with tag not found."""
        proj = self._make_project(revisionExpr="refs/tags/v1.0")
        proj.bare_git.rev_list = mock.MagicMock(side_effect=GitError("not found"))

        with pytest.raises(ManifestInvalidRevisionError, match="not found"):
            proj.GetCommitRevisionId()


@pytest.mark.unit
class TestProjectUploadForReview:
    """Test Project.UploadForReview method."""

    def _make_project(self):
        """Create a project for upload testing."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.globalConfig = mock.MagicMock()

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(
                manifest=manifest,
                name="test/project",
                remote=mock.MagicMock(),
                gitdir="/tmp/test.git",
                objdir="/tmp/test-objects.git",
                worktree="/tmp/test",
                relpath="test",
                revisionExpr="main",
                revisionId=None,
            )
        return proj

    def test_upload_for_review_no_branch(self):
        """Test UploadForReview raises error when no branch."""
        proj = self._make_project()
        proj.work_git.GetHead = mock.MagicMock(return_value="1234567890")

        with pytest.raises(GitError, match="not currently on a branch"):
            proj.UploadForReview()

    def test_upload_for_review_no_tracking(self):
        """Test UploadForReview raises error when branch doesn't track remote."""
        proj = self._make_project()
        proj.work_git.GetHead = mock.MagicMock(return_value="refs/heads/feature")

        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = None
        proj.config.GetBranch = mock.MagicMock(return_value=mock_branch)

        with pytest.raises(GitError, match="does not track a remote"):
            proj.UploadForReview()

    def test_upload_for_review_no_review_url(self):
        """Test UploadForReview raises error when no review URL."""

        proj = self._make_project()
        proj.work_git.GetHead = mock.MagicMock(return_value="refs/heads/feature")

        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = "refs/remotes/origin/main"
        mock_branch.remote.review = None
        proj.config.GetBranch = mock.MagicMock(return_value=mock_branch)

        with pytest.raises(GitError, match="no review url"):
            proj.UploadForReview()

    def test_upload_for_review_invalid_label(self):
        """Test UploadForReview raises error for invalid label syntax."""
        from kanon_cli.repo.error import UploadError

        proj = self._make_project()
        proj.work_git.GetHead = mock.MagicMock(return_value="refs/heads/feature")

        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = "refs/remotes/origin/main"
        mock_branch.remote.review = "https://review.example.com"
        mock_branch.remote.ReviewUrl.return_value = "https://review.example.com"
        proj.config.GetBranch = mock.MagicMock(return_value=mock_branch)

        with pytest.raises(UploadError, match="invalid label syntax"):
            proj.UploadForReview(labels=["InvalidLabel"])


@pytest.mark.unit
class TestProjectSyncMethods:
    """Test Project sync-related methods."""

    def _make_project(self, **kwargs):
        """Create a project for testing."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = "/tmp/test-topdir"
        manifest.repodir = "/tmp/test-topdir/.repo"
        manifest.globalConfig = mock.MagicMock()

        defaults = {
            "manifest": manifest,
            "name": "test/project",
            "remote": mock.MagicMock(),
            "gitdir": "/tmp/test.git",
            "objdir": "/tmp/test-objects.git",
            "worktree": "/tmp/test",
            "relpath": "test",
            "revisionExpr": "main",
            "revisionId": None,
        }
        defaults.update(kwargs)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(**defaults)
        return proj

    def test_post_repo_upgrade(self):
        """Test PostRepoUpgrade calls _InitHooks."""
        proj = self._make_project()

        with mock.patch.object(proj, "_InitHooks") as mock_init_hooks:
            proj.PostRepoUpgrade()

        mock_init_hooks.assert_called_once()

    def test_copy_and_link_files(self):
        """Test _CopyAndLinkFiles calls copy and link."""
        proj = self._make_project()

        mock_copyfile = mock.MagicMock()
        mock_linkfile = mock.MagicMock()
        proj.copyfiles = [mock_copyfile]
        proj.linkfiles = [mock_linkfile]

        proj._CopyAndLinkFiles()

        mock_copyfile._Copy.assert_called_once()
        mock_linkfile._Link.assert_called_once()

    def test_set_revision_id(self):
        """Test SetRevisionId updates upstream."""
        proj = self._make_project(revisionExpr="refs/heads/main")

        proj.SetRevisionId("new_sha")

        assert proj.revisionId == "new_sha"
        assert proj.upstream == "refs/heads/main"


@pytest.mark.unit
class TestProjectRemoteFetch:
    """Test Project._RemoteFetch method."""

    def _make_project(self, **kwargs):
        """Create a project for testing."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = "/tmp/test-topdir"
        manifest.globalConfig = mock.MagicMock()

        defaults = {
            "manifest": manifest,
            "name": "test/project",
            "remote": mock.MagicMock(),
            "gitdir": "/tmp/test.git",
            "objdir": "/tmp/test-objects.git",
            "worktree": "/tmp/test",
            "relpath": "test",
            "revisionExpr": "main",
            "revisionId": None,
        }
        defaults.update(kwargs)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(**defaults)
        return proj

    def test_remote_fetch_retry_on_http_429(self):
        """Test _RemoteFetch retries on HTTP 429 error."""
        proj = self._make_project()
        proj.remote.name = "origin"

        mock_git_cmd = mock.MagicMock()
        mock_git_cmd.Wait.return_value = 1
        mock_git_cmd.stdout = "error: HTTP 429 Too Many Requests"

        with mock.patch("kanon_cli.repo.project.GitCommand", return_value=mock_git_cmd):
            with mock.patch("time.sleep"):
                with mock.patch.object(proj, "GetRemote") as mock_get_remote:
                    mock_remote = mock.MagicMock()
                    mock_remote.PreConnectFetch.return_value = True
                    mock_get_remote.return_value = mock_remote

                    result = proj._RemoteFetch(
                        initial=False,
                        quiet=True,
                        verbose=False,
                        retry_fetches=2,
                    )

        assert result is False


@pytest.mark.unit
class TestProjectGetUploadableBranches:
    """Test Project.GetUploadableBranches method."""

    def _make_project(self):
        """Create a project for testing."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.globalConfig = mock.MagicMock()

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(
                manifest=manifest,
                name="test/project",
                remote=mock.MagicMock(),
                gitdir="/tmp/test.git",
                objdir="/tmp/test-objects.git",
                worktree="/tmp/test",
                relpath="test",
                revisionExpr="main",
                revisionId=None,
            )
        return proj

    def test_get_uploadable_branches_none_ready(self):
        """Test GetUploadableBranches when no branches are ready."""
        proj = self._make_project()

        # Mock GetBranch to return a branch with LocalMerge=None
        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = None
        proj.config.GetBranch = mock.MagicMock(return_value=mock_branch)

        with mock.patch.object(
            type(proj),
            "_allrefs",
            new_callable=mock.PropertyMock,
            return_value={
                "refs/heads/main": "sha123",
                "refs/pub/main": "sha123",
            },
        ):
            result = proj.GetUploadableBranches()

        assert result == []

    def test_get_uploadable_branches_with_changes(self):
        """Test GetUploadableBranches returns branches with changes."""
        proj = self._make_project()

        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = "refs/remotes/origin/main"
        proj.config.GetBranch = mock.MagicMock(return_value=mock_branch)

        with mock.patch.object(
            type(proj),
            "_allrefs",
            new_callable=mock.PropertyMock,
            return_value={
                "refs/heads/feature": "sha456",
                "refs/pub/feature": "sha123",
            },
        ):
            with mock.patch.object(proj, "GetUploadableBranch") as mock_get:
                mock_rb = mock.MagicMock()
                mock_get.return_value = mock_rb

                result = proj.GetUploadableBranches()

        assert len(result) == 1

    def test_get_uploadable_branch_no_merge(self):
        """Test GetUploadableBranch returns None when no LocalMerge."""
        proj = self._make_project()

        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = None
        proj.config.GetBranch = mock.MagicMock(return_value=mock_branch)

        result = proj.GetUploadableBranch("feature")
        assert result is None

    def test_get_uploadable_branch_no_commits(self):
        """Test GetUploadableBranch returns None when no commits."""
        proj = self._make_project()

        mock_branch = mock.MagicMock()
        mock_branch.LocalMerge = "refs/remotes/origin/main"
        proj.config.GetBranch = mock.MagicMock(return_value=mock_branch)

        with mock.patch("kanon_cli.repo.project.ReviewableBranch") as mock_rb_class:
            mock_rb = mock.MagicMock()
            mock_rb.commits = []
            mock_rb_class.return_value = mock_rb

            result = proj.GetUploadableBranch("feature")

        assert result is None


@pytest.mark.unit
class TestProjectVersionConstraints:
    """Test Project version constraint handling."""

    def _make_project(self, **kwargs):
        """Create a project for testing."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.globalConfig = mock.MagicMock()

        defaults = {
            "manifest": manifest,
            "name": "test/project",
            "remote": mock.MagicMock(),
            "gitdir": "/tmp/test.git",
            "objdir": "/tmp/test-objects.git",
            "worktree": "/tmp/test",
            "relpath": "test",
            "revisionExpr": "main",
            "revisionId": None,
        }
        defaults.update(kwargs)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(**defaults)
        return proj

    def test_resolve_version_constraint_ls_remote_fails(self):
        """_ResolveVersionConstraint raises when ls-remote fails."""
        proj = self._make_project(revisionExpr="refs/tags/dev/python/quality-agent/>=1.0.0")

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=1, stdout="", stderr="error")
            with pytest.raises(
                ManifestInvalidRevisionError,
                match="failed to list remote tags",
            ):
                proj._ResolveVersionConstraint()

    def test_resolve_version_constraint_no_matching_tags(self):
        """_ResolveVersionConstraint raises when no tags match."""
        proj = self._make_project(revisionExpr="refs/tags/dev/python/quality-agent/>=99.0.0")

        ls_output = (
            "0000000000000000000000000000000000000000\t"
            "refs/tags/dev/python/quality-agent/1.0.0\n"
            "0000000000000000000000000000000000000001\t"
            "refs/tags/dev/python/quality-agent/1.5.0"
        )

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout=ls_output, stderr="")
            with pytest.raises(ManifestInvalidRevisionError):
                proj._ResolveVersionConstraint()

    def test_resolve_version_constraint_resolved(self):
        """_ResolveVersionConstraint mutates revisionExpr to resolved tag."""
        proj = self._make_project(revisionExpr="refs/tags/dev/python/quality-agent/>=1.0.0")

        ls_output = (
            "0000000000000000000000000000000000000000\t"
            "refs/tags/dev/python/quality-agent/1.0.0\n"
            "0000000000000000000000000000000000000001\t"
            "refs/tags/dev/python/quality-agent/1.5.0"
        )

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout=ls_output, stderr="")
            proj._ResolveVersionConstraint()

        assert proj.revisionExpr == ("refs/tags/dev/python/quality-agent/1.5.0")


@pytest.mark.unit
class TestMetaProject:
    """Test MetaProject class."""

    def test_meta_project_initialization(self):
        """Test MetaProject can be initialized."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = "/tmp/test"
        manifest.repodir = "/tmp/test/.repo"
        manifest.globalConfig = mock.MagicMock()

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            meta = project.MetaProject(
                manifest=manifest,
                name="manifests",
                gitdir="/tmp/test/.repo/manifests.git",
                worktree="/tmp/test/.repo/manifests",
            )

        assert meta.name == "manifests"


@pytest.mark.unit
class TestProjectPrintWorkTreeStatusDetailed:
    """Test PrintWorkTreeStatus with various file states."""

    def _make_project(self):
        """Create a project for testing."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.globalConfig = mock.MagicMock()

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(
                manifest=manifest,
                name="test/project",
                remote=mock.MagicMock(),
                gitdir="/tmp/test.git",
                objdir="/tmp/test-objects.git",
                worktree="/tmp/test",
                relpath="test",
                revisionExpr="main",
                revisionId=None,
            )
        return proj

    def test_print_work_tree_status_with_renamed_file(self, capsys):
        """Test PrintWorkTreeStatus with renamed file."""
        proj = self._make_project()
        proj.work_git.update_index = mock.MagicMock()

        # Mock a renamed file in diff-index
        mock_file_info = mock.MagicMock()
        mock_file_info.status = "R"
        mock_file_info.src_path = "old_file.txt"
        mock_file_info.level = "100"

        mock_di = {"new_file.txt": mock_file_info}
        proj.work_git.DiffZ = mock.MagicMock(return_value=mock_di)
        proj.work_git.LsOthers = mock.MagicMock(return_value=[])
        proj.work_git.GetHead = mock.MagicMock(return_value="refs/heads/main")
        proj.IsRebaseInProgress = mock.MagicMock(return_value=False)

        with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=True):
            result = proj.PrintWorkTreeStatus()

        captured = capsys.readouterr()
        assert result == "DIRTY"
        assert "old_file.txt => new_file.txt" in captured.out

    def test_print_work_tree_status_with_both_staged_and_modified(self, capsys):
        """Test PrintWorkTreeStatus with file both staged and modified."""
        proj = self._make_project()
        proj.work_git.update_index = mock.MagicMock()

        # File is both in index and has working tree changes
        mock_index_info = mock.MagicMock()
        mock_index_info.status = "M"
        mock_index_info.src_path = None

        mock_working_info = mock.MagicMock()
        mock_working_info.status = "m"

        def mock_diffz(cmd, *args):
            if "diff-index" in cmd:
                return {"file.txt": mock_index_info}
            else:  # diff-files
                return {"file.txt": mock_working_info}

        proj.work_git.DiffZ = mock.MagicMock(side_effect=mock_diffz)
        proj.work_git.LsOthers = mock.MagicMock(return_value=[])
        proj.work_git.GetHead = mock.MagicMock(return_value="refs/heads/main")
        proj.IsRebaseInProgress = mock.MagicMock(return_value=False)

        with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=True):
            result = proj.PrintWorkTreeStatus()

        captured = capsys.readouterr()
        assert result == "DIRTY"
        assert "Mm" in captured.out

    def test_print_work_tree_status_with_untracked_file(self, capsys):
        """Test PrintWorkTreeStatus with untracked file only."""
        proj = self._make_project()
        proj.work_git.update_index = mock.MagicMock()

        proj.work_git.DiffZ = mock.MagicMock(return_value={})
        proj.work_git.LsOthers = mock.MagicMock(return_value=["untracked.txt"])
        proj.work_git.GetHead = mock.MagicMock(return_value="refs/heads/main")
        proj.IsRebaseInProgress = mock.MagicMock(return_value=False)

        with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=True):
            result = proj.PrintWorkTreeStatus()

        captured = capsys.readouterr()
        assert result == "DIRTY"
        assert "--" in captured.out


@pytest.mark.unit
class TestProjectSyncLocalHalf:
    """Test Project.Sync_LocalHalf scenarios."""

    def _make_project(self):
        """Create a project for testing."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = "/tmp/test-topdir"
        manifest.globalConfig = mock.MagicMock()

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(
                manifest=manifest,
                name="test/project",
                remote=mock.MagicMock(),
                gitdir="/tmp/test.git",
                objdir="/tmp/test-objects.git",
                worktree="/tmp/test",
                relpath="test",
                revisionExpr="main",
                revisionId=None,
            )
        return proj

    def test_sync_local_half_missing_gitdir(self):
        """Test Sync_LocalHalf fails when gitdir doesn't exist."""
        proj = self._make_project()
        mock_syncbuf = mock.MagicMock()
        errors = []

        with mock.patch("os.path.exists", return_value=False):
            proj.Sync_LocalHalf(mock_syncbuf, errors=errors)

        assert len(errors) == 1
        assert isinstance(errors[0], LocalSyncFail)


@pytest.mark.unit
class TestProjectWorktreeMethods:
    """Test Project worktree-related methods."""

    def _make_project(self):
        """Create a project for testing."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = "/tmp/test-topdir"
        manifest.globalConfig = mock.MagicMock()

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(
                manifest=manifest,
                name="test/project",
                remote=mock.MagicMock(),
                gitdir="/tmp/test.git",
                objdir="/tmp/test-objects.git",
                worktree="/tmp/test",
                relpath="test",
                revisionExpr="main",
                revisionId=None,
            )
        return proj

    def test_project_exists_property(self):
        """Test Exists property."""
        proj = self._make_project()

        with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=True):
            assert proj.Exists is True

        with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=False):
            assert proj.Exists is False

    def test_project_current_branch_none(self):
        """Test CurrentBranch returns None on detached HEAD."""
        proj = self._make_project()
        proj.work_git.GetHead = mock.MagicMock(return_value="1234567890abcdef")

        assert proj.CurrentBranch is None

    def test_project_current_branch_with_branch(self):
        """Test CurrentBranch returns branch name."""
        proj = self._make_project()
        proj.work_git.GetHead = mock.MagicMock(return_value="refs/heads/feature")

        assert proj.CurrentBranch == "feature"

    def test_project_current_branch_no_manifest_exception(self):
        """Test CurrentBranch handles NoManifestException."""
        proj = self._make_project()
        proj.work_git.GetHead = mock.MagicMock(side_effect=NoManifestException("path", "reason"))

        assert proj.CurrentBranch is None

    def test_is_rebase_in_progress_true(self):
        """Test IsRebaseInProgress returns True."""
        proj = self._make_project()

        with mock.patch("os.path.exists", return_value=True):
            assert proj.IsRebaseInProgress() is True

    def test_is_rebase_in_progress_false(self):
        """Test IsRebaseInProgress returns False."""
        proj = self._make_project()

        with mock.patch("os.path.exists", return_value=False):
            assert proj.IsRebaseInProgress() is False

    def test_is_cherry_pick_in_progress(self):
        """Test IsCherryPickInProgress."""
        proj = self._make_project()

        with mock.patch("os.path.exists", return_value=True):
            assert proj.IsCherryPickInProgress() is True

        with mock.patch("os.path.exists", return_value=False):
            assert proj.IsCherryPickInProgress() is False


@pytest.mark.unit
class TestProjectGetBranches:
    """Test Project.GetBranches method."""

    def _make_project(self):
        """Create a project for testing."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.globalConfig = mock.MagicMock()

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(
                manifest=manifest,
                name="test/project",
                remote=mock.MagicMock(),
                gitdir="/tmp/test.git",
                objdir="/tmp/test-objects.git",
                worktree="/tmp/test",
                relpath="test",
                revisionExpr="main",
                revisionId=None,
            )
        return proj


@pytest.mark.unit
class TestProjectMatchesGroups:
    """Test Project.MatchesGroups method."""

    def _make_project(self, groups=None):
        """Create a project for testing."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.default_groups = ["default"]
        manifest.globalConfig = mock.MagicMock()

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(
                manifest=manifest,
                name="test/project",
                remote=mock.MagicMock(),
                gitdir="/tmp/test.git",
                objdir="/tmp/test-objects.git",
                worktree="/tmp/test",
                relpath="test",
                revisionExpr="main",
                revisionId=None,
                groups=groups,
            )
        return proj

    def test_matches_groups_default(self):
        """Test MatchesGroups with default group."""
        proj = self._make_project()

        assert proj.MatchesGroups(["default"]) is True

    def test_matches_groups_explicit_match(self):
        """Test MatchesGroups with explicit group match."""
        proj = self._make_project(groups=["feature"])

        assert proj.MatchesGroups(["feature"]) is True

    def test_matches_groups_negation(self):
        """Test MatchesGroups with group negation."""
        proj = self._make_project(groups=["feature"])

        assert proj.MatchesGroups(["-feature"]) is False

    def test_matches_groups_notdefault(self):
        """Test MatchesGroups with notdefault."""
        proj = self._make_project(groups=["notdefault"])

        assert proj.MatchesGroups(["default"]) is False


@pytest.mark.unit
class TestProjectUncommitedFiles:
    """Test Project.UncommitedFiles method."""

    def _make_project(self):
        """Create a project for testing."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.globalConfig = mock.MagicMock()

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(
                manifest=manifest,
                name="test/project",
                remote=mock.MagicMock(),
                gitdir="/tmp/test.git",
                objdir="/tmp/test-objects.git",
                worktree="/tmp/test",
                relpath="test",
                revisionExpr="main",
                revisionId=None,
            )
        return proj

    def test_uncommited_files_with_rebase(self):
        """Test UncommitedFiles detects rebase in progress."""
        proj = self._make_project()
        proj.work_git.update_index = mock.MagicMock()
        proj.IsRebaseInProgress = mock.MagicMock(return_value=True)
        proj.work_git.DiffZ = mock.MagicMock(return_value={})
        proj.work_git.LsOthers = mock.MagicMock(return_value=[])

        files = proj.UncommitedFiles()

        assert "rebase in progress" in files

    def test_uncommited_files_get_all_false(self):
        """Test UncommitedFiles returns early when get_all=False."""
        proj = self._make_project()
        proj.work_git.update_index = mock.MagicMock()
        proj.IsRebaseInProgress = mock.MagicMock(return_value=True)

        files = proj.UncommitedFiles(get_all=False)

        assert len(files) == 1
        assert "rebase in progress" in files

    def test_uncommited_files_staged_changes(self):
        """Test UncommitedFiles detects staged changes."""
        proj = self._make_project()
        proj.work_git.update_index = mock.MagicMock()
        proj.IsRebaseInProgress = mock.MagicMock(return_value=False)

        def mock_diffz(cmd, *args):
            if "diff-index" in cmd:
                return {"staged.txt": None}
            else:
                return {}

        proj.work_git.DiffZ = mock.MagicMock(side_effect=mock_diffz)
        proj.work_git.LsOthers = mock.MagicMock(return_value=[])

        files = proj.UncommitedFiles()

        assert "staged.txt" in files


@pytest.mark.unit
class TestProjectWasPublished:
    """Test Project.WasPublished method."""

    def _make_project(self):
        """Create a project for testing."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.globalConfig = mock.MagicMock()

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(
                manifest=manifest,
                name="test/project",
                remote=mock.MagicMock(),
                gitdir="/tmp/test.git",
                objdir="/tmp/test-objects.git",
                worktree="/tmp/test",
                relpath="test",
                revisionExpr="main",
                revisionId=None,
            )
        return proj

    def test_was_published_from_git(self):
        """Test WasPublished from git."""
        proj = self._make_project()
        proj.bare_git.rev_parse = mock.MagicMock(return_value="published_sha")

        result = proj.WasPublished("feature")

        assert result == "published_sha"

    def test_was_published_not_found(self):
        """Test WasPublished returns None when not found."""
        proj = self._make_project()
        proj.bare_git.rev_parse = mock.MagicMock(side_effect=GitError("not found"))

        result = proj.WasPublished("feature")

        assert result is None

    def test_was_published_from_all_refs_not_found(self):
        """Test WasPublished from all_refs returns None."""
        proj = self._make_project()

        all_refs = {}

        result = proj.WasPublished("feature", all_refs=all_refs)

        assert result is None


@pytest.mark.unit
class TestProjectCleanPublishedCache:
    """Test Project.CleanPublishedCache method."""

    def _make_project(self):
        """Create a project for testing."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.globalConfig = mock.MagicMock()

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            proj = project.Project(
                manifest=manifest,
                name="test/project",
                remote=mock.MagicMock(),
                gitdir="/tmp/test.git",
                objdir="/tmp/test-objects.git",
                worktree="/tmp/test",
                relpath="test",
                revisionExpr="main",
                revisionId=None,
            )
        return proj

    def test_clean_published_cache_removes_stale(self):
        """Test CleanPublishedCache removes stale published refs."""
        proj = self._make_project()
        proj.bare_git.DeleteRef = mock.MagicMock()

        all_refs = {
            "refs/heads/main": "sha123",
            "refs/published/feature": "sha456",  # Stale - no corresponding head
        }

        with mock.patch.object(
            type(proj),
            "_allrefs",
            new_callable=mock.PropertyMock,
            return_value=all_refs,
        ):
            proj.CleanPublishedCache(all_refs)

        proj.bare_git.DeleteRef.assert_called_once_with("refs/published/feature", "sha456")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
