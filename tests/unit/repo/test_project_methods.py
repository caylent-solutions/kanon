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

"""Additional unit tests for project.py methods - simpler, focused tests."""

from unittest import mock

import pytest

from kanon_cli.repo import error
from kanon_cli.repo import project


def _simple_project(tmp_path):
    """Create a simple mocked Project."""
    manifest = mock.MagicMock()
    manifest.topdir = str(tmp_path)
    manifest.repodir = str(tmp_path / ".repo")

    proj = project.Project.__new__(project.Project)
    proj.manifest = manifest
    proj.name = "test"
    proj.relpath = "test"
    proj.worktree = str(tmp_path / "test")
    proj.gitdir = str(tmp_path / ".repo" / "test.git")
    proj.objdir = proj.gitdir
    proj.bare_git = mock.MagicMock()
    proj.work_git = mock.MagicMock()
    proj.config = mock.MagicMock()
    proj.remote = mock.MagicMock()
    proj.remote.name = "origin"
    proj.revisionExpr = "main"
    proj.revisionId = None
    proj.upstream = None
    proj.copyfiles = []
    proj.linkfiles = []
    proj.annotations = []
    proj.subprojects = []
    proj.groups = []
    return proj


# Simple Property Tests


@pytest.mark.unit
def test_project_name_property(tmp_path):
    """Test project name is accessible."""
    proj = _simple_project(tmp_path)
    assert proj.name == "test"


@pytest.mark.unit
def test_project_relpath_property(tmp_path):
    """Test project relpath is accessible."""
    proj = _simple_project(tmp_path)
    assert proj.relpath == "test"


@pytest.mark.unit
def test_project_worktree_property(tmp_path):
    """Test project worktree is accessible."""
    proj = _simple_project(tmp_path)
    assert "test" in proj.worktree


@pytest.mark.unit
def test_project_gitdir_property(tmp_path):
    """Test project gitdir is accessible."""
    proj = _simple_project(tmp_path)
    assert "test.git" in proj.gitdir


@pytest.mark.unit
def test_project_remote_property(tmp_path):
    """Test project remote is accessible."""
    proj = _simple_project(tmp_path)
    assert proj.remote.name == "origin"


# Simple Revision Tests


@pytest.mark.unit
def test_revision_expr_property(tmp_path):
    """Test revisionExpr is accessible."""
    proj = _simple_project(tmp_path)
    assert proj.revisionExpr == "main"


@pytest.mark.unit
def test_revision_id_initially_none(tmp_path):
    """Test revisionId starts as None."""
    proj = _simple_project(tmp_path)
    assert proj.revisionId is None


@pytest.mark.unit
def test_set_revision_updates_expr(tmp_path):
    """Test SetRevision updates revisionExpr."""
    proj = _simple_project(tmp_path)
    proj.SetRevision("develop")
    assert proj.revisionExpr == "develop"


@pytest.mark.unit
def test_set_revision_with_id_updates_both(tmp_path):
    """Test SetRevision with revisionId updates both."""
    proj = _simple_project(tmp_path)
    proj.SetRevision("develop", revisionId="abc123")
    assert proj.revisionExpr == "develop"
    assert proj.revisionId == "abc123"


# Collection Tests


@pytest.mark.unit
def test_copyfiles_starts_empty(tmp_path):
    """Test copyfiles list starts empty."""
    proj = _simple_project(tmp_path)
    assert proj.copyfiles == []


@pytest.mark.unit
def test_linkfiles_starts_empty(tmp_path):
    """Test linkfiles list starts empty."""
    proj = _simple_project(tmp_path)
    assert proj.linkfiles == []


@pytest.mark.unit
def test_annotations_starts_empty(tmp_path):
    """Test annotations list starts empty."""
    proj = _simple_project(tmp_path)
    assert proj.annotations == []


@pytest.mark.unit
def test_subprojects_starts_empty(tmp_path):
    """Test subprojects list starts empty."""
    proj = _simple_project(tmp_path)
    assert proj.subprojects == []


# AddCopyFile Tests


@pytest.mark.unit
def test_add_copyfile_increases_list(tmp_path):
    """Test AddCopyFile adds to list."""
    proj = _simple_project(tmp_path)
    initial_count = len(proj.copyfiles)

    proj.AddCopyFile("src", "dest", str(tmp_path))

    assert len(proj.copyfiles) == initial_count + 1


@pytest.mark.unit
def test_add_copyfile_creates_copy_file_object(tmp_path):
    """Test AddCopyFile creates _CopyFile object."""
    proj = _simple_project(tmp_path)

    proj.AddCopyFile("src.txt", "dest.txt", str(tmp_path))

    assert isinstance(proj.copyfiles[0], project._CopyFile)


@pytest.mark.unit
def test_add_copyfile_stores_paths(tmp_path):
    """Test AddCopyFile stores correct paths."""
    proj = _simple_project(tmp_path)

    proj.AddCopyFile("source.txt", "destination.txt", str(tmp_path))

    cf = proj.copyfiles[0]
    assert cf.src == "source.txt"
    assert cf.dest == "destination.txt"


# AddLinkFile Tests


@pytest.mark.unit
def test_add_linkfile_increases_list(tmp_path):
    """Test AddLinkFile adds to list."""
    proj = _simple_project(tmp_path)
    initial_count = len(proj.linkfiles)

    proj.AddLinkFile("src", "link", str(tmp_path))

    assert len(proj.linkfiles) == initial_count + 1


@pytest.mark.unit
def test_add_linkfile_creates_link_file_object(tmp_path):
    """Test AddLinkFile creates _LinkFile object."""
    proj = _simple_project(tmp_path)

    proj.AddLinkFile("src.txt", "link.txt", str(tmp_path))

    assert isinstance(proj.linkfiles[0], project._LinkFile)


@pytest.mark.unit
def test_add_linkfile_stores_paths(tmp_path):
    """Test AddLinkFile stores correct paths."""
    proj = _simple_project(tmp_path)

    proj.AddLinkFile("source.txt", "link.txt", str(tmp_path))

    lf = proj.linkfiles[0]
    assert lf.src == "source.txt"
    assert lf.dest == "link.txt"


# AddAnnotation Tests


@pytest.mark.unit
def test_add_annotation_increases_list(tmp_path):
    """Test AddAnnotation adds to list."""
    proj = _simple_project(tmp_path)
    initial_count = len(proj.annotations)

    proj.AddAnnotation("key", "value", "true")

    assert len(proj.annotations) == initial_count + 1


@pytest.mark.unit
def test_add_annotation_creates_annotation_object(tmp_path):
    """Test AddAnnotation creates Annotation object."""
    proj = _simple_project(tmp_path)

    proj.AddAnnotation("test-key", "test-value", "false")

    assert isinstance(proj.annotations[0], project.Annotation)


@pytest.mark.unit
def test_add_annotation_stores_values(tmp_path):
    """Test AddAnnotation stores correct values."""
    proj = _simple_project(tmp_path)

    proj.AddAnnotation("my-name", "my-value", "my-keep")

    ann = proj.annotations[0]
    assert ann.name == "my-name"
    assert ann.value == "my-value"
    assert ann.keep == "my-keep"


# _CopyFile Tests


@pytest.mark.unit
def test_copyfile_initialization(tmp_path):
    """Test _CopyFile initializes correctly."""
    git_worktree = str(tmp_path / "worktree")
    topdir = str(tmp_path / "topdir")

    cf = project._CopyFile(git_worktree, "src.txt", topdir, "dest.txt")

    assert cf.git_worktree == git_worktree
    assert cf.src == "src.txt"
    assert cf.topdir == topdir
    assert cf.dest == "dest.txt"


# _LinkFile Tests


@pytest.mark.unit
def test_linkfile_initialization(tmp_path):
    """Test _LinkFile initializes correctly."""
    git_worktree = str(tmp_path / "worktree")
    topdir = str(tmp_path / "topdir")

    lf = project._LinkFile(git_worktree, "src.txt", topdir, "link.txt")

    assert lf.git_worktree == git_worktree
    assert lf.src == "src.txt"
    assert lf.topdir == topdir
    assert lf.dest == "link.txt"


# Helper Function Tests


@pytest.mark.unit
def test_not_rev_function():
    """Test not_rev helper function."""
    assert project.not_rev("abc") == "^abc"
    assert project.not_rev("HEAD") == "^HEAD"
    assert project.not_rev("123") == "^123"


@pytest.mark.unit
def test_sq_function():
    """Test sq helper function."""
    assert project.sq("test") == "'test'"
    assert project.sq("hello") == "'hello'"


@pytest.mark.unit
def test_sq_function_with_quotes():
    """Test sq escapes quotes correctly."""
    result = project.sq("it's")
    assert "'''" in result


# RemoteSpec Tests


@pytest.mark.unit
def test_remote_spec_name_only():
    """Test RemoteSpec with just name."""
    spec = project.RemoteSpec(name="myremote")

    assert spec.name == "myremote"
    assert spec.url is None
    assert spec.pushUrl is None
    assert spec.review is None
    assert spec.revision is None


@pytest.mark.unit
def test_remote_spec_all_fields():
    """Test RemoteSpec with all fields."""
    spec = project.RemoteSpec(
        name="origin",
        url="https://example.com/repo.git",
        pushUrl="https://push.example.com/repo.git",
        review="https://review.example.com",
        revision="refs/heads/main",
        orig_name="upstream",
        fetchUrl="https://fetch.example.com/repo.git",
    )

    assert spec.name == "origin"
    assert spec.url == "https://example.com/repo.git"
    assert spec.pushUrl == "https://push.example.com/repo.git"
    assert spec.review == "https://review.example.com"
    assert spec.revision == "refs/heads/main"
    assert spec.orig_name == "upstream"
    assert spec.fetchUrl == "https://fetch.example.com/repo.git"


# Annotation Tests


@pytest.mark.unit
def test_annotation_init():
    """Test Annotation initialization."""
    ann = project.Annotation("test-name", "test-value", "true")

    assert ann.name == "test-name"
    assert ann.value == "test-value"
    assert ann.keep == "true"


@pytest.mark.unit
def test_annotation_equality_same():
    """Test Annotation equality for identical annotations."""
    ann1 = project.Annotation("name", "value", "keep")
    ann2 = project.Annotation("name", "value", "keep")

    assert ann1 == ann2


@pytest.mark.unit
def test_annotation_inequality_different_name():
    """Test Annotation inequality for different names."""
    ann1 = project.Annotation("name1", "value", "keep")
    ann2 = project.Annotation("name2", "value", "keep")

    assert ann1 != ann2


@pytest.mark.unit
def test_annotation_inequality_different_value():
    """Test Annotation inequality for different values."""
    ann1 = project.Annotation("name", "value1", "keep")
    ann2 = project.Annotation("name", "value2", "keep")

    assert ann1 != ann2


@pytest.mark.unit
def test_annotation_inequality_different_keep():
    """Test Annotation inequality for different keep values."""
    ann1 = project.Annotation("name", "value", "true")
    ann2 = project.Annotation("name", "value", "false")

    assert ann1 != ann2


@pytest.mark.unit
def test_annotation_not_equal_to_string():
    """Test Annotation not equal to non-Annotation."""
    ann = project.Annotation("name", "value", "keep")

    assert ann != "string"
    assert ann != 123
    assert ann is not None


@pytest.mark.unit
def test_annotation_sort_by_name():
    """Test Annotation sorting by name."""
    ann1 = project.Annotation("aaa", "value", "keep")
    ann2 = project.Annotation("bbb", "value", "keep")
    ann3 = project.Annotation("ccc", "value", "keep")

    sorted_list = sorted([ann3, ann1, ann2])

    assert sorted_list[0] == ann1
    assert sorted_list[1] == ann2
    assert sorted_list[2] == ann3


@pytest.mark.unit
def test_annotation_sort_by_value():
    """Test Annotation sorting by value when names match."""
    ann1 = project.Annotation("name", "aaa", "keep")
    ann2 = project.Annotation("name", "bbb", "keep")
    ann3 = project.Annotation("name", "ccc", "keep")

    sorted_list = sorted([ann2, ann3, ann1])

    assert sorted_list[0] == ann1
    assert sorted_list[1] == ann2
    assert sorted_list[2] == ann3


@pytest.mark.unit
def test_annotation_sort_by_keep():
    """Test Annotation sorting by keep when name and value match."""
    ann1 = project.Annotation("name", "value", "aaa")
    ann2 = project.Annotation("name", "value", "bbb")

    sorted_list = sorted([ann2, ann1])

    assert sorted_list[0] == ann1
    assert sorted_list[1] == ann2


@pytest.mark.unit
def test_annotation_lt_raises_for_non_annotation():
    """Test Annotation.__lt__ raises ValueError for non-Annotation."""
    ann = project.Annotation("name", "value", "keep")

    with pytest.raises(ValueError):
        ann < "string"


# DownloadedChange Tests


@pytest.mark.unit
def test_downloaded_change_init(tmp_path):
    """Test DownloadedChange initialization."""
    proj = _simple_project(tmp_path)

    dc = project.DownloadedChange(proj, "base_sha", 12345, 2, "commit_sha")

    assert dc.project == proj
    assert dc.base == "base_sha"
    assert dc.change_id == 12345
    assert dc.ps_id == 2
    assert dc.commit == "commit_sha"


@pytest.mark.unit
def test_downloaded_change_commits_calls_rev_list(tmp_path):
    """Test DownloadedChange.commits calls bare_git.rev_list."""
    proj = _simple_project(tmp_path)
    proj.bare_git.rev_list.return_value = "abc123 Test commit\n"

    dc = project.DownloadedChange(proj, "base", 123, 1, "commit")

    commits = dc.commits

    proj.bare_git.rev_list.assert_called_once()
    assert commits == "abc123 Test commit\n"


@pytest.mark.unit
def test_downloaded_change_commits_cached(tmp_path):
    """Test DownloadedChange.commits is cached."""
    proj = _simple_project(tmp_path)
    proj.bare_git.rev_list.return_value = "cached"

    dc = project.DownloadedChange(proj, "base", 123, 1, "commit")

    result1 = dc.commits
    result2 = dc.commits

    # Should only call once due to caching
    assert proj.bare_git.rev_list.call_count == 1
    assert result1 == result2


# ReviewableBranch Tests


@pytest.mark.unit
def test_reviewable_branch_init(tmp_path):
    """Test ReviewableBranch initialization."""
    proj = _simple_project(tmp_path)
    branch = mock.MagicMock()
    branch.name = "feature"

    rb = project.ReviewableBranch(proj, branch, "main")

    assert rb.project == proj
    assert rb.branch == branch
    assert rb.base == "main"


@pytest.mark.unit
def test_reviewable_branch_name(tmp_path):
    """Test ReviewableBranch.name property."""
    proj = _simple_project(tmp_path)
    branch = mock.MagicMock()
    branch.name = "my-feature"

    rb = project.ReviewableBranch(proj, branch, "main")

    assert rb.name == "my-feature"


@pytest.mark.unit
def test_reviewable_branch_commits_calls_rev_list(tmp_path):
    """Test ReviewableBranch.commits calls bare_git.rev_list."""
    proj = _simple_project(tmp_path)
    proj.bare_git.rev_list.return_value = "commit list"
    branch = mock.MagicMock()
    branch.name = "feature"

    rb = project.ReviewableBranch(proj, branch, "main")

    rb.commits

    proj.bare_git.rev_list.assert_called_once()


# Error Class Tests


@pytest.mark.unit
def test_sync_network_half_error():
    """Test SyncNetworkHalfError is a RepoError."""
    err = project.SyncNetworkHalfError("test message")

    assert isinstance(err, error.RepoError)


@pytest.mark.unit
def test_delete_worktree_error_no_aggregates():
    """Test DeleteWorktreeError with no aggregates."""
    err = project.DeleteWorktreeError("test message")

    assert err.aggregate_errors == []


@pytest.mark.unit
def test_delete_worktree_error_with_aggregates():
    """Test DeleteWorktreeError with aggregate errors."""
    sub_err1 = Exception("error1")
    sub_err2 = Exception("error2")

    err = project.DeleteWorktreeError("main error", aggregate_errors=[sub_err1, sub_err2])

    assert len(err.aggregate_errors) == 2
    assert err.aggregate_errors[0] == sub_err1
    assert err.aggregate_errors[1] == sub_err2


@pytest.mark.unit
def test_delete_dirty_worktree_error():
    """Test DeleteDirtyWorktreeError is subclass of DeleteWorktreeError."""
    err = project.DeleteDirtyWorktreeError("test message")

    assert isinstance(err, project.DeleteWorktreeError)
    assert isinstance(err, error.RepoError)


# SyncNetworkHalfResult Tests


@pytest.mark.unit
def test_sync_network_half_result_success_property():
    """Test SyncNetworkHalfResult.success with no error."""
    result = project.SyncNetworkHalfResult(remote_fetched=True)

    assert result.success is True


@pytest.mark.unit
def test_sync_network_half_result_failure_property():
    """Test SyncNetworkHalfResult.success with error."""
    err = Exception("test")
    result = project.SyncNetworkHalfResult(remote_fetched=False, error=err)

    assert result.success is False


@pytest.mark.unit
def test_sync_network_half_result_remote_fetched_true():
    """Test SyncNetworkHalfResult.remote_fetched."""
    result = project.SyncNetworkHalfResult(remote_fetched=True)

    assert result.remote_fetched is True


@pytest.mark.unit
def test_sync_network_half_result_remote_fetched_false():
    """Test SyncNetworkHalfResult.remote_fetched."""
    result = project.SyncNetworkHalfResult(remote_fetched=False)

    assert result.remote_fetched is False


@pytest.mark.unit
def test_sync_network_half_result_error_stored():
    """Test SyncNetworkHalfResult stores error."""
    err = Exception("test error")
    result = project.SyncNetworkHalfResult(remote_fetched=True, error=err)

    assert result.error == err


# Constant Tests


@pytest.mark.unit
def test_maximum_retry_sleep_sec_constant():
    """Test MAXIMUM_RETRY_SLEEP_SEC constant value."""
    assert isinstance(project.MAXIMUM_RETRY_SLEEP_SEC, float)
    assert project.MAXIMUM_RETRY_SLEEP_SEC > 0


@pytest.mark.unit
def test_retry_jitter_percent_constant():
    """Test RETRY_JITTER_PERCENT constant value."""
    assert isinstance(project.RETRY_JITTER_PERCENT, float)
    assert 0 < project.RETRY_JITTER_PERCENT < 1


@pytest.mark.unit
def test_alternates_env_var_is_bool():
    """Test _ALTERNATES is a boolean."""
    assert isinstance(project._ALTERNATES, bool)
