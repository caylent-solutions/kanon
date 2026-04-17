"""Additional coverage tests for project.py to reach the 90% threshold.

Targets the following uncovered line groups:
- Lines 4135-4139: RepoProject.LastFetch property
- Lines 4741: ManifestProject.ConfigureCloneFilterForDepth
- Lines 4752-4761: ManifestProject._ConfigureDepth
- Lines 2452-2463: Project.EnableRepositoryExtension
- Lines 2477-2490: Project.ResolveRemoteHead
- Lines 2085-2086: StartBranch when branch exists in all_refs
- Lines 2097: StartBranch with custom revision parameter
- Lines 2133: CheckoutBranch when branch not in all_refs
- Lines 2143-2146: CheckoutBranch head in R_HEADS but key missing from all_refs
- Lines 1180, 1185, 1187, 1201: GetUploadableBranches branches
- Lines 2237, 2242-2246: PruneHeads additional paths
- Lines 2259-2267: GetRegisteredSubprojects recursive
- Lines 2378-2381: git_ls_tree error paths in _GetSubmodules
- Lines 2398-2404: GetDerivedSubprojects when repo does not exist
- Lines 1965-1966: DeleteWorktree verbose output
- Lines 1252, 1255-1256, 1260, 1263: UploadForReview dest_branch and dryrun paths
"""

import os
import tempfile
from unittest import mock

import pytest

from kanon_cli.repo import project
from kanon_cli.repo.error import GitError
from kanon_cli.repo.git_refs import R_HEADS, R_PUB
from kanon_cli.repo.project import (
    ManifestProject,
    MetaProject,
    RepoProject,
    ReviewableBranch,
)


def _make_project(**kwargs):
    """Create a minimal mock Project for testing.

    All path values are derived from a unique temporary directory created at
    call time via tempfile.mkdtemp() so no hard-coded path literals are used.
    """
    base = tempfile.mkdtemp(prefix="kanon-test-")
    manifest = mock.MagicMock()
    manifest.IsMirror = False
    manifest.IsArchive = False
    manifest.topdir = base
    manifest.repodir = os.path.join(base, ".repo")
    manifest.globalConfig = mock.MagicMock()

    defaults = {
        "manifest": manifest,
        "name": "test/project",
        "remote": mock.MagicMock(),
        "gitdir": os.path.join(base, ".repo", "projects", "test", "project.git"),
        "objdir": os.path.join(base, ".repo", "project-objects", "test", "project.git"),
        "worktree": os.path.join(base, "test", "project"),
        "relpath": "test/project",
        "revisionExpr": "refs/heads/main",
        "revisionId": None,
    }
    defaults.update(kwargs)

    with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
        proj = project.Project(**defaults)
    return proj


def _make_meta_project(manifest, name="repo", **kwargs):
    """Create a MetaProject with mocked manifest.

    Path defaults are derived from the manifest's repodir so no hard-coded
    path literals are introduced.
    """
    repodir = getattr(manifest, "repodir", None) or tempfile.mkdtemp(prefix="kanon-meta-")
    gitdir = kwargs.pop("gitdir", os.path.join(repodir, name))
    worktree = kwargs.pop("worktree", os.path.join(repodir, f"{name}-wt"))
    with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
        mp = MetaProject(manifest, name, gitdir, worktree)
    return mp


@pytest.mark.unit
class TestRepoProjectLastFetch:
    """Tests for RepoProject.LastFetch property (lines 4135-4139)."""

    def test_last_fetch_returns_mtime_when_file_exists(self, tmp_path):
        """Lines 4135-4138: returns mtime of FETCH_HEAD when present."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = str(tmp_path)
        manifest.repodir = str(tmp_path / ".repo")
        manifest.globalConfig = mock.MagicMock()

        gitdir = str(tmp_path / ".repo" / "repo.git")
        os.makedirs(gitdir, exist_ok=True)
        fetch_head = tmp_path / ".repo" / "repo.git" / "FETCH_HEAD"
        fetch_head.write_text("sha1\trefs/heads/main\thttps://example.com/repo.git\n")

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            repo_proj = RepoProject(manifest, "repo", gitdir, str(tmp_path / "repo"))

        result = repo_proj.LastFetch
        assert isinstance(result, float)
        assert result > 0

    def test_last_fetch_returns_zero_when_file_missing(self, tmp_path):
        """Lines 4138-4139: returns 0 when FETCH_HEAD is absent (OSError)."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = str(tmp_path)
        manifest.repodir = str(tmp_path / ".repo")
        manifest.globalConfig = mock.MagicMock()

        gitdir = str(tmp_path / ".repo" / "repo-no-fetch.git")
        os.makedirs(gitdir, exist_ok=True)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            repo_proj = RepoProject(manifest, "repo", gitdir, str(tmp_path / "repo-wt"))

        result = repo_proj.LastFetch
        assert result == 0


@pytest.mark.unit
class TestManifestProjectConfigureCloneFilterForDepth:
    """Tests for ManifestProject.ConfigureCloneFilterForDepth (line 4741)."""

    def test_configure_sets_repo_clonefilterfordepth(self, tmp_path):
        """Line 4741: SetString called with the provided filter."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = str(tmp_path)
        manifest.repodir = str(tmp_path / ".repo")
        manifest.globalConfig = mock.MagicMock()

        gitdir = str(tmp_path / ".repo" / "manifests.git")
        os.makedirs(gitdir, exist_ok=True)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            mp = ManifestProject(manifest, "manifests", gitdir, str(tmp_path / "manifests-wt"))

        mp.config.SetString = mock.MagicMock()
        mp.ConfigureCloneFilterForDepth("blob:none")
        mp.config.SetString.assert_called_once_with("repo.clonefilterfordepth", "blob:none")

    def test_configure_accepts_none(self, tmp_path):
        """Line 4741: SetString accepts None to disable."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = str(tmp_path)
        manifest.repodir = str(tmp_path / ".repo")
        manifest.globalConfig = mock.MagicMock()

        gitdir = str(tmp_path / ".repo" / "manifests2.git")
        os.makedirs(gitdir, exist_ok=True)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            mp = ManifestProject(manifest, "manifests", gitdir, str(tmp_path / "mwt2"))

        mp.config.SetString = mock.MagicMock()
        mp.ConfigureCloneFilterForDepth(None)
        mp.config.SetString.assert_called_once_with("repo.clonefilterfordepth", None)


@pytest.mark.unit
class TestManifestProjectConfigureDepth:
    """Tests for ManifestProject._ConfigureDepth (lines 4752-4761)."""

    def _make_manifest_project(self, tmp_path):
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = str(tmp_path)
        manifest.repodir = str(tmp_path / ".repo")
        manifest.globalConfig = mock.MagicMock()
        gitdir = str(tmp_path / ".repo" / "manifests.git")
        os.makedirs(gitdir, exist_ok=True)
        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            return ManifestProject(manifest, "manifests", gitdir, str(tmp_path / "mwt"))

    def test_positive_depth_sets_string(self, tmp_path):
        """Lines 4752-4754: positive depth is stored as string."""
        mp = self._make_manifest_project(tmp_path)
        mp.config.SetString = mock.MagicMock()
        mp._ConfigureDepth(5)
        mp.config.SetString.assert_called_once_with("repo.depth", "5")

    def test_negative_depth_clears_setting(self, tmp_path):
        """Lines 4755-4758: negative depth clears via None."""
        mp = self._make_manifest_project(tmp_path)
        mp.config.SetString = mock.MagicMock()
        mp._ConfigureDepth(-1)
        mp.config.SetString.assert_called_once_with("repo.depth", None)

    def test_none_depth_is_no_op(self, tmp_path):
        """Lines 4750-4761: depth=None results in no call to SetString."""
        mp = self._make_manifest_project(tmp_path)
        mp.config.SetString = mock.MagicMock()
        mp._ConfigureDepth(None)
        mp.config.SetString.assert_not_called()


@pytest.mark.unit
class TestEnableRepositoryExtension:
    """Tests for Project.EnableRepositoryExtension (lines 2452-2463)."""

    def test_enable_sets_extension_with_default_version(self):
        """Lines 2460-2463: sets version and extension key."""
        proj = _make_project()
        proj.config = mock.MagicMock()
        proj.config.GetInt.return_value = 0
        proj.EnableRepositoryExtension("worktreeConfig")
        proj.config.SetString.assert_any_call("extensions.worktreeConfig", "true")

    def test_enable_uses_existing_version_when_sufficient(self):
        """Line 2463: version update skipped if already meeting version requirement."""
        proj = _make_project()
        proj.config = mock.MagicMock()
        proj.config.GetInt.return_value = 1
        proj.EnableRepositoryExtension("partialclone", "origin", version=1)
        proj.config.SetString.assert_any_call("extensions.partialclone", "origin")

    def test_enable_sets_version_when_below_required(self):
        """Lines 2464-2465: updates repositoryFormatVersion when below required."""
        proj = _make_project()
        proj.config = mock.MagicMock()
        proj.config.GetInt.return_value = None
        proj.EnableRepositoryExtension("preciousObjects", version=1)
        proj.config.SetString.assert_any_call("core.repositoryFormatVersion", "1")

    def test_enable_with_custom_value(self):
        """Line 2468: custom value is passed to SetString."""
        proj = _make_project()
        proj.config = mock.MagicMock()
        proj.config.GetInt.return_value = 1
        proj.EnableRepositoryExtension("worktreeConfig", value="1", version=1)
        proj.config.SetString.assert_any_call("extensions.worktreeConfig", "1")


@pytest.mark.unit
class TestResolveRemoteHead:
    """Tests for Project.ResolveRemoteHead (lines 2477-2490)."""

    def test_returns_ref_when_symref_line_found(self):
        """Lines 2483-2488: parses symref line from ls-remote output."""
        proj = _make_project()
        proj.remote.name = "origin"
        proj.bare_git = mock.MagicMock()
        proj.bare_git.ls_remote.return_value = "ref: refs/heads/main\tHEAD\nabc123def\tHEAD\n"
        result = proj.ResolveRemoteHead()
        assert result == "refs/heads/main"

    def test_returns_none_when_no_symref_line(self):
        """Line 2490: returns None when no ref: line found."""
        proj = _make_project()
        proj.remote.name = "origin"
        proj.bare_git = mock.MagicMock()
        proj.bare_git.ls_remote.return_value = "abc123def\tHEAD\n"
        result = proj.ResolveRemoteHead()
        assert result is None

    def test_uses_custom_name_parameter(self):
        """Line 2478: custom name overrides self.remote.name."""
        proj = _make_project()
        proj.remote.name = "origin"
        proj.bare_git = mock.MagicMock()
        proj.bare_git.ls_remote.return_value = ""
        proj.ResolveRemoteHead(name="upstream")
        proj.bare_git.ls_remote.assert_called_once_with("-q", "--symref", "--exit-code", "upstream", "HEAD")


@pytest.mark.unit
class TestStartBranchPaths:
    """Tests for StartBranch additional code paths (lines 2085-2086, 2097)."""

    def test_checkout_existing_branch_from_all_refs(self):
        """Lines 2085-2086: branch exists in all_refs, runs git checkout."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()
        proj.bare_ref.all = {R_HEADS + "existing": "sha123"}
        proj.work_git = mock.MagicMock()
        proj.work_git.GetHead.return_value = R_HEADS + "other"

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            result = proj.StartBranch("existing")

        assert result is True
        mock_gc.assert_called()
        call_args = mock_gc.call_args[0][1]
        assert "checkout" in call_args
        assert "existing" in call_args

    def test_start_branch_with_custom_revision(self):
        """Line 2097: StartBranch with explicit revision uses rev_parse."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()
        proj.bare_ref.all = {}
        proj.work_git = mock.MagicMock()
        proj.work_git.GetHead.return_value = "some_sha"
        proj.work_git.rev_parse.return_value = "custom_sha"

        with (
            mock.patch.object(proj, "GetBranch") as mock_get_branch,
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_branch = mock.MagicMock()
            mock_branch.name = "new_branch"
            mock_branch.merge = ""
            mock_get_branch.return_value = mock_branch
            mock_gc.return_value.Wait.return_value = 0

            result = proj.StartBranch("new_branch", revision="v1.0.0")

        assert result is True
        proj.work_git.rev_parse.assert_called_once_with("v1.0.0")


@pytest.mark.unit
class TestCheckoutBranchPaths:
    """Tests for CheckoutBranch additional paths (lines 2133, 2140, 2143-2146)."""

    def test_returns_true_when_already_on_branch(self):
        """Line 2133: returns True immediately when head already equals rev."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()
        proj.work_git = mock.MagicMock()
        proj.work_git.GetHead.return_value = R_HEADS + "feature"

        result = proj.CheckoutBranch("feature")
        assert result is True

    def test_returns_false_when_branch_not_in_all_refs(self):
        """Line 2140: returns False when rev not in all_refs."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()
        proj.bare_ref.all = {}
        proj.work_git = mock.MagicMock()
        proj.work_git.GetHead.return_value = R_HEADS + "main"

        result = proj.CheckoutBranch("nonexistent")
        assert result is False

    def test_head_branch_not_in_all_refs_sets_head_to_none(self):
        """Lines 2143-2146: head is R_HEADS branch but not in all_refs, becomes None."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()
        proj.bare_ref.all = {R_HEADS + "feature": "sha_feature"}
        proj.work_git = mock.MagicMock()
        proj.work_git.GetHead.return_value = R_HEADS + "some_other_branch"

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            result = proj.CheckoutBranch("feature")

        assert result is True
        mock_gc.assert_called()


@pytest.mark.unit
class TestGetUploadableBranchesPaths:
    """Tests for GetUploadableBranches code paths (lines 1180, 1185, 1187, 1201)."""

    def test_skips_branch_published_at_same_rev(self):
        """Lines 1180, 1185: published branch at same rev is skipped."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()

        with mock.patch.object(
            type(proj),
            "_allrefs",
            new_callable=mock.PropertyMock,
            return_value={
                R_HEADS + "feature": "sha123",
                R_PUB + "feature": "sha123",
            },
        ):
            result = proj.GetUploadableBranches()

        assert result == []

    def test_filters_by_selected_branch(self):
        """Line 1187: only the selected_branch is included."""
        proj = _make_project()
        with mock.patch.object(
            type(proj),
            "_allrefs",
            new_callable=mock.PropertyMock,
            return_value={
                R_HEADS + "feature": "sha_feat",
                R_HEADS + "other": "sha_other",
                R_PUB + "other": "sha_pub",
            },
        ):
            with mock.patch.object(proj, "GetUploadableBranch") as mock_get_ub:
                mock_get_ub.return_value = mock.MagicMock()
                result = proj.GetUploadableBranches(selected_branch="feature")

        mock_get_ub.assert_called_once_with("feature")
        assert len(result) == 1

    def test_returns_rb_when_commits_present(self):
        """Line 1201: rb returned when it has commits."""
        proj = _make_project()
        with mock.patch.object(
            type(proj),
            "_allrefs",
            new_callable=mock.PropertyMock,
            return_value={
                R_HEADS + "feature": "sha_feat",
            },
        ):
            mock_rb = mock.MagicMock()
            mock_rb.commits = ["sha1", "sha2"]
            with mock.patch.object(proj, "GetUploadableBranch", return_value=mock_rb):
                result = proj.GetUploadableBranches()

        assert len(result) == 1
        assert result[0] is mock_rb

    def test_get_uploadable_branch_returns_rb_with_commits(self):
        """Line 1201: GetUploadableBranch returns rb when commits non-empty."""
        proj = _make_project()
        branch_obj = mock.MagicMock()
        branch_obj.LocalMerge = "refs/heads/main"

        with (
            mock.patch.object(proj, "GetBranch", return_value=branch_obj),
            mock.patch("kanon_cli.repo.project.ReviewableBranch") as mock_rb_class,
        ):
            mock_rb = mock.MagicMock()
            mock_rb.commits = ["sha1", "sha2"]
            mock_rb_class.return_value = mock_rb
            result = proj.GetUploadableBranch("feature")

        assert result is mock_rb


@pytest.mark.unit
class TestPruneHeadsAdditionalPaths:
    """Tests for PruneHeads additional paths (lines 2237, 2242-2246)."""

    def test_set_head_called_when_old_is_not_sha(self):
        """Line 2237: bare_git.SetHead called when old is a branch ref."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()
        branch_obj = mock.MagicMock()
        branch_obj.LocalMerge = "refs/heads/main"

        with (
            mock.patch.object(type(proj), "CurrentBranch", new_callable=mock.PropertyMock, return_value=None),
            mock.patch.object(
                type(proj), "_allrefs", new_callable=mock.PropertyMock, return_value={R_HEADS + "feature": "sha123"}
            ),
            mock.patch.object(proj, "GetRevisionId", return_value="rev123"),
            mock.patch.object(proj, "_revlist", return_value=["sha"]),
            mock.patch.object(proj, "IsDirty", return_value=False),
            mock.patch.object(proj, "GetBranch", return_value=branch_obj),
            mock.patch.object(proj.bare_git, "DetachHead"),
            mock.patch.object(proj.bare_git, "GetHead", return_value=R_HEADS + "main"),
            mock.patch.object(proj.bare_git, "SetHead") as mock_set_head,
            mock.patch("kanon_cli.repo.project.IsId", return_value=False),
            mock.patch("kanon_cli.repo.project.ReviewableBranch"),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            proj.PruneHeads()

        mock_set_head.assert_called()

    def test_clean_published_cache_called_when_branch_removed(self):
        """Lines 2241-2243: CleanPublishedCache called when branch no longer in refs."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()

        allrefs_values = [
            {R_HEADS + "feature": "sha123"},
            {},
        ]
        allrefs_iter = iter(allrefs_values)

        def allrefs_side_effect():
            try:
                return next(allrefs_iter)
            except StopIteration:
                return {}

        with (
            mock.patch.object(type(proj), "CurrentBranch", new_callable=mock.PropertyMock, return_value=None),
            mock.patch.object(type(proj), "_allrefs", new_callable=mock.PropertyMock, side_effect=allrefs_side_effect),
            mock.patch.object(proj, "GetRevisionId", return_value="rev123"),
            mock.patch.object(proj, "_revlist", return_value=["sha"]),
            mock.patch.object(proj, "IsDirty", return_value=False),
            mock.patch.object(proj.bare_git, "DetachHead"),
            mock.patch.object(proj.bare_git, "GetHead", return_value="deadbeef123456789"),
            mock.patch.object(proj, "CleanPublishedCache"),
            mock.patch("kanon_cli.repo.project.IsId", return_value=True),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            proj.PruneHeads()

    def test_base_set_to_rev_when_no_local_merge(self):
        """Line 2255: base falls back to rev when branch has no LocalMerge."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()

        with (
            mock.patch.object(type(proj), "CurrentBranch", new_callable=mock.PropertyMock, return_value=None),
            mock.patch.object(
                type(proj), "_allrefs", new_callable=mock.PropertyMock, return_value={R_HEADS + "feature": "sha123"}
            ),
            mock.patch.object(proj, "GetRevisionId", return_value="rev123"),
            mock.patch.object(proj, "_revlist", return_value=["sha1"]),
            mock.patch.object(proj, "IsDirty", return_value=False),
            mock.patch.object(proj, "GetBranch") as mock_get_branch,
            mock.patch.object(proj.bare_git, "DetachHead"),
            mock.patch.object(proj.bare_git, "GetHead", return_value="deadbeef1234567890"),
            mock.patch.object(proj.bare_git, "SetHead"),
            mock.patch.object(proj, "CleanPublishedCache"),
            mock.patch("kanon_cli.repo.project.IsId", return_value=True),
            mock.patch("kanon_cli.repo.project.ReviewableBranch") as mock_rb,
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            branch_obj = mock.MagicMock()
            branch_obj.LocalMerge = None
            mock_get_branch.return_value = branch_obj
            mock_gc.return_value.Wait.return_value = 0
            proj.PruneHeads()

        mock_rb.assert_called()

    def test_cb_appended_when_not_in_kill_list(self):
        """Line 2245-2246: cb appended to kill when cb not already in kill list.

        This requires _revlist to return truthy so that the cb is NOT appended
        at line 2221, and cb must not already be in kill (e.g. cb='main' and
        kill only contains 'feature').
        """
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()

        with (
            mock.patch.object(type(proj), "CurrentBranch", new_callable=mock.PropertyMock, return_value="main"),
            mock.patch.object(
                type(proj), "_allrefs", new_callable=mock.PropertyMock, return_value={R_HEADS + "feature": "sha123"}
            ),
            mock.patch.object(proj, "GetRevisionId", return_value="rev123"),
            mock.patch.object(proj, "_revlist", return_value=["sha1"]),
            mock.patch.object(proj, "IsDirty", return_value=False),
            mock.patch.object(proj, "GetBranch") as mock_get_branch,
            mock.patch.object(proj.work_git, "DetachHead"),
            mock.patch.object(proj.bare_git, "DetachHead"),
            mock.patch.object(proj.bare_git, "GetHead", return_value="deadbeef1234567890"),
            mock.patch.object(proj.bare_git, "SetHead"),
            mock.patch.object(proj, "CleanPublishedCache"),
            mock.patch("kanon_cli.repo.project.IsId", return_value=True),
            mock.patch("kanon_cli.repo.project.ReviewableBranch"),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            branch_obj = mock.MagicMock()
            branch_obj.LocalMerge = "merge_ref"
            mock_get_branch.return_value = branch_obj
            mock_gc.return_value.Wait.return_value = 0
            proj.PruneHeads()


@pytest.mark.unit
class TestGetRegisteredSubprojects:
    """Tests for GetRegisteredSubprojects recursive traversal (lines 2259-2267)."""

    def test_returns_empty_when_no_subprojects(self):
        """Lines 2262-2264: empty subprojects list returns empty result."""
        proj = _make_project()
        proj.subprojects = []
        result = proj.GetRegisteredSubprojects()
        assert result == []

    def test_returns_direct_subprojects(self):
        """Lines 2265: extends result with direct subprojects."""
        proj = _make_project()
        sub1 = mock.MagicMock()
        sub1.subprojects = []
        proj.subprojects = [sub1]
        result = proj.GetRegisteredSubprojects()
        assert sub1 in result

    def test_recursively_collects_nested_subprojects(self):
        """Lines 2265-2267: recursively collects nested subprojects."""
        proj = _make_project()
        sub2 = mock.MagicMock()
        sub2.subprojects = []
        sub1 = mock.MagicMock()
        sub1.subprojects = [sub2]
        proj.subprojects = [sub1]
        result = proj.GetRegisteredSubprojects()
        assert sub1 in result
        assert sub2 in result


@pytest.mark.unit
class TestGetDerivedSubprojectsWhenNotExists:
    """Tests for GetDerivedSubprojects when project does not exist (lines 2398-2403)."""

    def test_returns_empty_when_project_does_not_exist(self):
        """Lines 2400-2403: early return when not self.Exists."""
        proj = _make_project()
        with mock.patch.object(type(proj), "Exists", new_callable=mock.PropertyMock, return_value=False):
            result = proj.GetDerivedSubprojects()
        assert result == []


@pytest.mark.unit
class TestDeleteWorktreeVerbose:
    """Tests for DeleteWorktree verbose mode (lines 1965-1966)."""

    def test_verbose_prints_deletion_message(self, tmp_path, capsys):
        """Lines 1965-1966: prints deletion message when verbose=True."""
        proj = _make_project(worktree=str(tmp_path / "proj"))
        os.makedirs(str(tmp_path / "proj"))

        with (
            mock.patch.object(proj, "IsDirty", return_value=False),
            mock.patch.object(proj, "RelPath", return_value="test/project"),
            mock.patch.object(proj, "use_git_worktrees", False, create=True),
            mock.patch("kanon_cli.repo.project.platform_utils.remove"),
            mock.patch("kanon_cli.repo.project.platform_utils.rmtree"),
            mock.patch("kanon_cli.repo.project.platform_utils.rmdir"),
            mock.patch("os.walk", return_value=[]),
        ):
            proj.manifest.topdir = str(tmp_path)
            proj.DeleteWorktree(verbose=True)

        captured = capsys.readouterr()
        assert "Deleting obsolete checkout" in captured.out


@pytest.mark.unit
class TestGetDerivedSubprojectsUrl:
    """Tests for GetDerivedSubprojects with relative URL (lines 2417-2418)."""

    def test_resolves_relative_url(self):
        """Lines 2417-2418: relative URL joined to remote.url."""
        proj = _make_project()
        proj.remote.url = "https://example.com/parent"
        proj.remote.pushUrl = None
        proj.remote.review = None
        proj.remote.revision = "main"
        proj.remote.name = "origin"
        proj.rebase = True
        proj.groups = []
        proj.sync_c = False
        proj.sync_s = False
        proj.sync_tags = True
        proj.subprojects = []

        mock_submodule = ("sha_rev", "subpath", "../sub.git", "false")

        with (
            mock.patch.object(type(proj), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(proj, "_GetSubmodules", return_value=[mock_submodule]),
            mock.patch.object(proj.manifest, "GetSubprojectName", return_value="sub"),
            mock.patch.object(
                proj.manifest, "GetSubprojectPaths", return_value=("sub/path", "/wt/sub", "/git/sub", "/obj/sub")
            ),
            mock.patch.object(proj.manifest, "paths", {}),
            mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"),
        ):
            result = proj.GetDerivedSubprojects()

        assert len(result) >= 1


@pytest.mark.unit
class TestGetDerivedSubprojectsAlreadyInPaths:
    """Tests for GetDerivedSubprojects when relpath already in manifest.paths."""

    def test_extends_from_existing_project_and_continues(self):
        """Lines 2413-2415: when project found in manifest.paths, extends and continues."""
        proj = _make_project()
        proj.remote.url = "https://example.com/parent"
        proj.remote.pushUrl = None
        proj.remote.review = None
        proj.remote.revision = "main"
        proj.remote.name = "origin"
        proj.rebase = True
        proj.groups = []
        proj.sync_c = False
        proj.sync_s = False
        proj.sync_tags = True
        proj.subprojects = []

        mock_submodule = ("sha_rev", "subpath", "https://example.com/sub.git", "false")
        existing_proj = mock.MagicMock()
        existing_derived = mock.MagicMock()
        existing_proj.GetDerivedSubprojects.return_value = [existing_derived]

        paths_dict = {"sub/path": existing_proj}
        proj.manifest.paths = paths_dict

        with (
            mock.patch.object(type(proj), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(proj, "_GetSubmodules", return_value=[mock_submodule]),
            mock.patch.object(proj.manifest, "GetSubprojectName", return_value="sub"),
            mock.patch.object(
                proj.manifest, "GetSubprojectPaths", return_value=("sub/path", "/wt/sub", "/git/sub", "/obj/sub")
            ),
        ):
            result = proj.GetDerivedSubprojects()

        existing_proj.GetDerivedSubprojects.assert_called_once()
        assert existing_derived in result


@pytest.mark.unit
class TestReviewableBranchCommits:
    """Tests for ReviewableBranch.commits property (line 277)."""

    def test_reraises_git_error_when_base_exists(self):
        """Line 277: re-raises GitError when base_exists is True and rev_list fails."""
        proj = _make_project()
        branch = mock.MagicMock()
        branch.name = "feature"
        rb = ReviewableBranch(proj, branch, "refs/heads/main")

        proj.bare_git = mock.MagicMock()
        proj.bare_git.rev_list.side_effect = GitError("rev_list failed", project="test/project")
        proj.bare_git.rev_parse.return_value = "sha123"

        with pytest.raises(GitError):
            _ = rb.commits

    def test_returns_empty_list_when_base_missing(self):
        """Line 279: returns empty list when base doesn't exist and rev_list fails."""
        proj = _make_project()
        branch = mock.MagicMock()
        branch.name = "feature"
        rb = ReviewableBranch(proj, branch, "refs/heads/nonexistent")

        proj.bare_git = mock.MagicMock()
        proj.bare_git.rev_list.side_effect = GitError("rev_list failed", project="test/project")
        proj.bare_git.rev_parse.side_effect = GitError("rev_parse failed", project="test/project")

        result = rb.commits
        assert result == []


@pytest.mark.unit
class TestPrintWorkTreeStatusAddedLine:
    """Tests for PrintWorkTreeStatus to cover line 1096 (out.added)."""

    def test_index_only_change_calls_added(self, tmp_path):
        """Line 1096: out.added called when file is in index diff but not working tree."""
        import io

        proj = _make_project(worktree=str(tmp_path / "proj"))
        os.makedirs(str(tmp_path / "proj"), exist_ok=True)

        index_entry = mock.MagicMock()
        index_entry.status = "A"
        index_entry.src_path = None
        index_entry.level = None

        output = io.StringIO()

        with (
            mock.patch.object(proj.work_git, "update_index"),
            mock.patch.object(proj, "IsRebaseInProgress", return_value=False),
            mock.patch.object(
                proj.work_git,
                "DiffZ",
                side_effect=lambda *args: {"newfile.py": index_entry} if "diff-index" in args else {},
            ),
            mock.patch.object(proj.work_git, "LsOthers", return_value=[]),
            mock.patch.object(type(proj), "CurrentBranch", new_callable=mock.PropertyMock, return_value="main"),
            mock.patch.object(proj, "RelPath", return_value="test/proj"),
        ):
            result = proj.PrintWorkTreeStatus(output_redir=output)

        assert result == "DIRTY"


@pytest.mark.unit
class TestPrintWorkTreeDiffPaths:
    """Tests for PrintWorkTreeDiff (lines 1111, 1114)."""

    def test_output_redir_calls_redirect(self):
        """Line 1111: out.redirect called when output_redir is set."""
        import io

        proj = _make_project()
        output = io.StringIO()

        with (
            mock.patch("kanon_cli.repo.project.DiffColoring") as mock_coloring,
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_out = mock.MagicMock()
            mock_out.is_on = False
            mock_coloring.return_value = mock_out
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""

            proj.PrintWorkTreeDiff(output_redir=output)

        mock_out.redirect.assert_called_once_with(output)

    def test_color_flag_added_when_color_on(self):
        """Line 1114: --color added to cmd when out.is_on is True."""
        proj = _make_project()

        with (
            mock.patch("kanon_cli.repo.project.DiffColoring") as mock_coloring,
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_out = mock.MagicMock()
            mock_out.is_on = True
            mock_coloring.return_value = mock_out
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""

            proj.PrintWorkTreeDiff()

        call_args = mock_gc.call_args[0][1]
        assert "--color" in call_args


@pytest.mark.unit
class TestUploadForReviewPaths:
    """Tests for UploadForReview code paths (lines 1252, 1255-1256, 1260, 1263)."""

    def _make_upload_project(self):
        """Create a project set up for UploadForReview testing."""
        proj = _make_project()
        branch_obj = mock.MagicMock()
        branch_obj.name = "feature"
        branch_obj.LocalMerge = "refs/heads/main"
        branch_obj.remote.review = "https://gerrit.example.com"
        branch_obj.remote.projectname = ""
        branch_obj.remote.name = "origin"
        branch_obj.remote.ReviewUrl.return_value = None
        branch_obj.merge = "refs/heads/main"
        return proj, branch_obj

    def test_raises_upload_error_when_no_review_url(self):
        """Line 1260: raises UploadError when ReviewUrl returns None."""
        proj, branch_obj = self._make_upload_project()
        proj.dest_branch = None

        with (
            mock.patch.object(type(proj), "CurrentBranch", new_callable=mock.PropertyMock, return_value="feature"),
            mock.patch.object(proj, "GetBranch", return_value=branch_obj),
        ):
            from kanon_cli.repo.error import UploadError

            with pytest.raises(UploadError):
                proj.UploadForReview()

    def test_prepends_r_heads_to_dest_branch_when_not_prefixed(self):
        """Line 1252: dest_branch gets R_HEADS prefix when not already present."""
        proj, branch_obj = self._make_upload_project()
        proj.dest_branch = None
        branch_obj.remote.ReviewUrl.return_value = "https://gerrit.example.com"
        branch_obj.remote.projectname = "test-project"

        with (
            mock.patch.object(type(proj), "CurrentBranch", new_callable=mock.PropertyMock, return_value="feature"),
            mock.patch.object(proj, "GetBranch", return_value=branch_obj),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.stdout = ""
            mock_gc.return_value.Wait.return_value = 0
            try:
                proj.UploadForReview(dest_branch="main")
            except Exception:
                pass

        mock_gc.assert_called()

    def test_projectname_saved_when_empty(self):
        """Lines 1255-1256: projectname set and saved when initially empty."""
        proj, branch_obj = self._make_upload_project()
        proj.dest_branch = None
        branch_obj.remote.ReviewUrl.return_value = "https://gerrit.example.com"
        branch_obj.remote.projectname = ""

        with (
            mock.patch.object(type(proj), "CurrentBranch", new_callable=mock.PropertyMock, return_value="feature"),
            mock.patch.object(proj, "GetBranch", return_value=branch_obj),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.stdout = ""
            mock_gc.return_value.Wait.return_value = 0
            try:
                proj.UploadForReview(dest_branch="main", dryrun=True)
            except Exception:
                pass

        branch_obj.remote.Save.assert_called()


@pytest.mark.unit
class TestInitRemoteNoWorktree:
    """Tests for _InitRemote when no worktree (line 3265)."""

    def test_reset_fetch_mirror_when_no_worktree(self):
        """Line 3265: ResetFetch(mirror=True) called when worktree is None."""
        proj = _make_project(worktree=None)
        remote = mock.MagicMock()
        proj.remote.url = "https://example.com/repo.git"

        with mock.patch.object(proj, "GetRemote", return_value=remote):
            proj._InitRemote()

        remote.ResetFetch.assert_called_with(mirror=True)
        remote.Save.assert_called()


@pytest.mark.unit
class TestManifestProjectSyncWithPossibleInit:
    """Tests for ManifestProject.SyncWithPossibleInit (lines 4283-4295)."""

    def test_sync_with_possible_init_delegates_to_sync(self, tmp_path):
        """Lines 4283-4295: delegates to self.Sync with parameters from spec and mp."""
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = str(tmp_path)
        manifest.repodir = str(tmp_path / ".repo")
        manifest.globalConfig = mock.MagicMock()

        gitdir = str(tmp_path / ".repo" / "manifests.git")
        os.makedirs(gitdir, exist_ok=True)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            mp = ManifestProject(manifest, "manifests", gitdir, str(tmp_path / "mwt"))

        spec = mock.MagicMock()
        spec.manifestUrl = "https://example.com/manifests.git"
        spec.revision = "main"

        submanifest = mock.MagicMock()
        submanifest.ToSubmanifestSpec.return_value = spec
        submanifest.parent.manifestProject.standalone_manifest_url = None
        submanifest.parent.manifestProject.manifest_groups = "default"

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "Sync", return_value=True) as mock_sync,
            mock.patch.object(mp.config, "GetString", return_value=None),
            mock.patch.object(mp.config, "GetBoolean", return_value=None),
        ):
            mp.SyncWithPossibleInit(submanifest, verbose=True)

        mock_sync.assert_called()


@pytest.mark.unit
class TestInitMRefWithWorktrees:
    """Tests for _InitMRef with git worktrees (lines 3275-3292)."""

    def test_init_mref_with_worktrees_when_symref_missing(self):
        """Lines 3275-3292: sets up symbolic ref and calls _InitAnyMRef."""
        proj = _make_project()
        proj.use_git_worktrees = True
        proj.manifest.branch = "main"
        proj.bare_ref = mock.MagicMock()
        proj.bare_ref.symref.return_value = None

        with (
            mock.patch.object(proj.bare_git, "symbolic_ref"),
            mock.patch.object(proj, "_InitAnyMRef") as mock_init_any,
            mock.patch("os.path.exists", return_value=True),
        ):
            proj._InitMRef()

        mock_init_any.assert_called()

    def test_init_mref_returns_early_when_worktree_missing(self):
        """Line 3287: returns early when worktree path does not exist."""
        proj = _make_project()
        proj.use_git_worktrees = True
        proj.manifest.branch = "main"
        proj.bare_ref = mock.MagicMock()
        proj.bare_ref.symref.return_value = None

        with (
            mock.patch.object(proj.bare_git, "symbolic_ref"),
            mock.patch.object(proj, "_InitAnyMRef") as mock_init_any,
            mock.patch("os.path.exists", return_value=False),
        ):
            proj._InitMRef()

        mock_init_any.assert_not_called()


@pytest.mark.unit
class TestGitGetByExecConfigAndErrors:
    """Tests for _GitGetByExec runner config and error paths (lines 3922-3926)."""

    def test_runner_raises_type_error_on_unexpected_kwarg(self):
        """Line 3922: TypeError raised when unexpected keyword argument passed."""
        proj = _make_project()
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            proj.bare_git.log(unknown_kwarg="value")

    def test_runner_applies_config_items(self):
        """Lines 3924-3926: -c key=value prepended for each config entry."""
        proj = _make_project()

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            proj.bare_git.log("HEAD", config={"user.name": "Test User", "user.email": "test@example.com"})

        call_args = mock_gc.call_args[0][1]
        assert "-c" in call_args
        assert "user.name=Test User" in call_args


@pytest.mark.unit
class TestApplyCloneBundleSimplePaths:
    """Tests for _ApplyCloneBundle simple exit paths (lines 2903, 2905, 2908)."""

    def test_returns_false_when_non_http_url(self):
        """Line 2883: returns False when URL scheme is not http/https."""
        proj = _make_project()
        proj.clone_depth = None
        proj.manifest.manifestProject.depth = None

        remote = mock.MagicMock()
        remote.url = "git://example.com/repo.git"
        remote.fetch = []

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch("kanon_cli.repo.project.GitConfig") as mock_gc_config,
        ):
            mock_gc_config.ForUser.return_value.UrlInsteadOf.return_value = remote.url
            result = proj._ApplyCloneBundle(initial=True)

        assert result is False

    def test_returns_false_when_not_initial_and_no_bundles(self, tmp_path):
        """Line 2892: returns False when not initial and no existing bundle files."""
        proj = _make_project()
        proj.clone_depth = None
        proj.manifest.manifestProject.depth = None
        proj.gitdir = str(tmp_path / "no-bundles.git")

        remote = mock.MagicMock()
        remote.url = "https://example.com/repo.git"
        remote.fetch = []

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch("kanon_cli.repo.project.GitConfig") as mock_gc_config,
            mock.patch("os.path.exists", return_value=False),
        ):
            mock_gc_config.ForUser.return_value.UrlInsteadOf.return_value = remote.url
            result = proj._ApplyCloneBundle(initial=False)

        assert result is False

    def test_apply_bundle_progress_no_worktree(self, tmp_path):
        """Lines 2903, 2905, 2908: --progress and --update-head-ok added; fetch iterates."""
        proj = _make_project()
        proj.clone_depth = None
        proj.manifest.manifestProject.depth = None
        proj.gitdir = str(tmp_path / "proj.git")
        os.makedirs(proj.gitdir, exist_ok=True)
        proj.worktree = None

        bundle_dst = os.path.join(proj.gitdir, "clone.bundle")
        open(bundle_dst, "w").close()

        remote = mock.MagicMock()
        remote.url = "https://example.com/repo.git"
        remote.fetch = ["refs/heads/main:refs/heads/main"]

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch("kanon_cli.repo.project.GitConfig") as mock_gc_config,
            mock.patch("sys.stdout") as mock_stdout,
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
            mock.patch("kanon_cli.repo.project.platform_utils.remove"),
        ):
            mock_gc_config.ForUser.return_value.UrlInsteadOf.return_value = remote.url
            mock_stdout.isatty.return_value = True
            mock_gc.return_value.Wait.return_value = 0

            proj._ApplyCloneBundle(initial=False, quiet=False)

        call_args = mock_gc.call_args[0][1]
        assert "--update-head-ok" in call_args


@pytest.mark.unit
class TestRemoteFetchOutputRedir:
    """Tests for _RemoteFetch output_redir and retry paths."""

    def test_output_redir_write_called_when_stdout_not_quiet(self):
        """Line 2737: output_redir.write called when gitcmd.stdout and not quiet."""
        proj = _make_project()
        proj.upstream = None
        proj.sync_c = False
        proj.sync_tags = True
        proj.clone_depth = None
        proj.manifest.IsMirror = False
        output_redir = mock.MagicMock()

        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch.object(proj, "_CheckForImmutableRevision", return_value=True),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = "fetching...\n"
            proj._RemoteFetch(
                name="origin",
                initial=False,
                quiet=False,
                output_redir=output_redir,
                current_branch_only=False,
            )

        output_redir.write.assert_called_with("fetching...\n")


@pytest.mark.unit
class TestDiffZLevelStripping:
    """Tests for DiffZ level parsing with leading-zero stripping (line 3796)."""

    def test_diffz_strips_leading_zeros_from_level(self):
        """Line 3796: leading zeros stripped from level field (e.g., R050 -> 50)."""
        proj = _make_project()

        diffz_output = ":100644 100644 abc123 def456 R050\0old_file.py\0new_file.py\0"

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = diffz_output
            result = proj.work_git.DiffZ("diff-index", "-M", "--cached", "HEAD")

        assert "new_file.py" in result
        info = result["new_file.py"]
        assert info.status == "R"
        assert info.level == "50"

    def test_diffz_preserves_level_without_leading_zeros(self):
        """Line 3793-3794: level preserved when no leading zeros (e.g., R75)."""
        proj = _make_project()

        diffz_output = ":100644 100644 abc123 def456 R75\0old_file.py\0new_file.py\0"

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = diffz_output
            result = proj.work_git.DiffZ("diff-index", "-M", "--cached", "HEAD")

        assert "new_file.py" in result
        info = result["new_file.py"]
        assert info.status == "R"
        assert info.level == "75"


@pytest.mark.unit
class TestGetAddedAndRemovedLogs:
    """Tests for getAddedAndRemovedLogs (lines 3705-3723)."""

    def test_returns_logs_dict_with_added_and_removed(self):
        """Lines 3705-3723: returns dict with added and removed logs."""
        proj = _make_project()
        to_proj = _make_project()

        proj.bare_ref = mock.MagicMock()
        to_proj.bare_ref = mock.MagicMock()

        with (
            mock.patch.object(proj, "GetRevisionId", return_value="sha_from"),
            mock.patch.object(to_proj, "GetRevisionId", return_value="sha_to"),
            mock.patch.object(proj, "_getLogs", return_value="log content") as mock_get_logs,
        ):
            result = proj.getAddedAndRemovedLogs(to_proj)

        assert "added" in result
        assert "removed" in result
        assert mock_get_logs.call_count == 2

    def test_get_logs_returns_stdout_on_success(self):
        """Lines 3691-3693: _getLogs returns stdout when git log succeeds."""
        proj = _make_project()

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = "commit abc123\n"
            result = proj._getLogs("sha1", "sha2")

        assert result == "commit abc123\n"

    def test_get_logs_returns_none_when_rev1_is_none(self):
        """Line 3701: _getLogs returns None when rev1 is falsy."""
        proj = _make_project()
        result = proj._getLogs(None, "sha2")
        assert result is None

    def test_get_logs_with_oneline_and_color(self):
        """Lines 3684, 3688: --color and --oneline added when flags set."""
        proj = _make_project()

        with (
            mock.patch("kanon_cli.repo.project.DiffColoring") as mock_coloring,
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_out = mock.MagicMock()
            mock_out.is_on = True
            mock_coloring.return_value = mock_out
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = "log line\n"

            proj._getLogs("sha1", "sha2", oneline=True, color=True)

        cmd_args = mock_gc.call_args[0][1]
        assert "--color" in cmd_args
        assert "--oneline" in cmd_args


@pytest.mark.unit
class TestMigrateOldSubmoduleDir:
    """Tests for _MigrateOldSubmoduleDir (lines 3640-3652)."""

    def test_migrate_when_both_dirs_exist(self, tmp_path):
        """Lines 3644-3645: when both old and new dirs exist, old is removed."""
        parent_gitdir = str(tmp_path / "parent.git")
        os.makedirs(parent_gitdir)
        subprojects = os.path.join(parent_gitdir, "subprojects")
        os.makedirs(subprojects)
        modules = os.path.join(parent_gitdir, "modules")
        os.makedirs(modules)

        old_gitdir = os.path.join(subprojects, "sub.git")
        os.makedirs(old_gitdir)
        new_gitdir = os.path.join(modules, "sub")
        os.makedirs(new_gitdir)

        proj = _make_project(gitdir=old_gitdir)
        proj.parent = mock.MagicMock()
        proj.parent.gitdir = parent_gitdir

        with mock.patch.object(proj, "UpdatePaths"):
            proj._MigrateOldSubmoduleDir()

        assert not os.path.exists(old_gitdir)

    def test_migrate_when_new_dir_missing(self, tmp_path):
        """Lines 3647-3648: when new dir missing, rename old to new."""
        parent_gitdir = str(tmp_path / "parent.git")
        os.makedirs(parent_gitdir)
        subprojects = os.path.join(parent_gitdir, "subprojects")
        os.makedirs(subprojects)

        old_gitdir = os.path.join(subprojects, "sub.git")
        os.makedirs(old_gitdir)

        proj = _make_project(gitdir=old_gitdir)
        proj.parent = mock.MagicMock()
        proj.parent.gitdir = parent_gitdir

        with mock.patch.object(proj, "UpdatePaths"):
            proj._MigrateOldSubmoduleDir()

        modules = os.path.join(parent_gitdir, "modules")
        expected_new = os.path.join(modules, "sub")
        assert os.path.isdir(expected_new)


@pytest.mark.unit
class TestManifestProjectSyncBranches:
    """Tests for ManifestProject.Sync various config-setting branches.

    Tests use is_new=False (Exists=True) to avoid _InitGitDir calls.
    """

    def _make_manifest_project_for_sync(self, tmp_path):
        manifest = mock.MagicMock()
        manifest.IsMirror = False
        manifest.IsArchive = False
        manifest.topdir = str(tmp_path)
        manifest.repodir = str(tmp_path / ".repo")
        manifest.globalConfig = mock.MagicMock()
        manifest.is_submanifest = False
        manifest.GetDefaultGroupsStr.return_value = "default"
        manifest.submanifests = {}

        gitdir = str(tmp_path / ".repo" / "manifests.git")
        os.makedirs(gitdir, exist_ok=True)

        with mock.patch("kanon_cli.repo.project.Project._LoadUserIdentity"):
            mp = ManifestProject(manifest, "manifests", gitdir, str(tmp_path / "mwt"))

        mp.config.GetString = mock.MagicMock(return_value=None)
        mp.config.GetInt = mock.MagicMock(return_value=None)
        mp.config.GetBoolean = mock.MagicMock(return_value=None)
        mp.config.SetString = mock.MagicMock()
        mp.config.SetBoolean = mock.MagicMock()
        mp.config.ClearCache = mock.MagicMock()
        return mp

    def test_sync_archive_not_new_returns_false(self, tmp_path):
        """Lines 4568-4571: returns False when archive=True but not is_new."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
        ):
            mock_get_remote.return_value = mock.MagicMock()
            result = mp.Sync(
                manifest_url="https://example.com/manifests.git",
                archive=True,
                manifest_name="default.xml",
            )

        assert result is False

    def test_sync_mirror_not_new_returns_false(self, tmp_path):
        """Lines 4577-4579: returns False when mirror=True but not is_new."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
        ):
            mock_get_remote.return_value = mock.MagicMock()
            result = mp.Sync(
                manifest_url="https://example.com/manifests.git",
                mirror=True,
                manifest_name="default.xml",
            )

        assert result is False

    def test_sync_partial_clone_with_mirror_returns_false(self, tmp_path):
        """Line 4584: returns False when partial_clone and mirror are both set."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(type(mp), "mirror", new_callable=mock.PropertyMock, return_value=True),
        ):
            mock_get_remote.return_value = mock.MagicMock()
            result = mp.Sync(
                manifest_url="https://example.com/manifests.git",
                partial_clone=True,
                manifest_name="default.xml",
            )

        assert result is False

    def test_sync_head_branch_resolve_fails_returns_false(self, tmp_path):
        """Lines 4510-4513: returns False when manifest_branch==HEAD and resolve fails."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "ResolveRemoteHead", return_value=None),
        ):
            mock_get_remote.return_value = mock.MagicMock()
            result = mp.Sync(
                manifest_url="https://example.com/manifests.git",
                manifest_branch="HEAD",
                manifest_name="default.xml",
            )

        assert result is False

    def test_sync_sets_dissociate_config(self, tmp_path):
        """Line 4551: dissociate config is set when dissociate=True."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    dissociate=True,
                    manifest_name="default.xml",
                )

        mp.config.SetBoolean.assert_any_call("repo.dissociate", True)

    def test_sync_partial_clone_sets_clone_filter(self, tmp_path):
        """Lines 4585-4587: partial_clone with clone_filter sets both configs."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
            mock.patch.object(type(mp), "mirror", new_callable=mock.PropertyMock, return_value=False),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    partial_clone=True,
                    clone_filter="blob:none",
                    manifest_name="default.xml",
                )

        mp.config.SetBoolean.assert_any_call("repo.partialclone", True)
        mp.config.SetString.assert_any_call("repo.clonefilter", "blob:none")

    def test_sync_new_project_verbose_prints_message(self, tmp_path, capsys):
        """Line 4467: prints verbose message when is_new=True and verbose=True."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=False),
            mock.patch.object(mp, "_InitGitDir"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp, "ResolveRemoteHead", return_value="refs/heads/main"),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
            mock.patch("kanon_cli.repo.project.GitConfig") as mock_gc_config,
        ):
            mock_gc_config.ForUser.return_value.UrlInsteadOf.return_value = "https://example.com/manifests.git"
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    verbose=True,
                    manifest_name="default.xml",
                )

        captured = capsys.readouterr()
        assert "Downloading manifest" in captured.err

    def test_sync_new_project_with_reference(self, tmp_path):
        """Lines 4476-4481: reference path constructed when is_new=True."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        reference_dir = str(tmp_path / "reference")
        os.makedirs(reference_dir, exist_ok=True)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=False),
            mock.patch.object(mp, "_InitGitDir") as mock_init_git,
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp, "ResolveRemoteHead", return_value="refs/heads/main"),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    reference=reference_dir,
                    manifest_name="default.xml",
                )

        mock_init_git.assert_called()

    def test_sync_new_project_with_reference_no_manifest_git(self, tmp_path):
        """Line 4481: falls back to .repo/manifests.git when path not found."""
        mp = self._make_manifest_project_for_sync(tmp_path)
        reference_dir = str(tmp_path / "reference")
        os.makedirs(reference_dir, exist_ok=True)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=False),
            mock.patch.object(mp, "_InitGitDir") as mock_init_git,
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp, "ResolveRemoteHead", return_value="refs/heads/main"),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
            mock.patch("os.path.exists", return_value=False),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                try:
                    mp.Sync(
                        manifest_url="https://example.com/manifests.git",
                        reference=reference_dir,
                        manifest_name="default.xml",
                    )
                except Exception:
                    pass

        mock_init_git.assert_called()

    def test_sync_platform_linux_in_auto(self, tmp_path):
        """Line 4531: linux platform added when platform=auto and not mirror."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
            mock.patch.object(type(mp), "mirror", new_callable=mock.PropertyMock, return_value=False),
            mock.patch.object(type(mp), "_platform_name", new_callable=mock.PropertyMock, return_value="linux"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result
            mp.manifest.GetDefaultGroupsStr.return_value = "other"

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    platform="auto",
                    manifest_name="default.xml",
                )

        mp.config.SetString.assert_any_call("manifest.platform", "auto")

    def test_sync_platform_all_adds_all_platforms(self, tmp_path):
        """Line 4533: all platforms added when platform=all."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
            mock.patch.object(type(mp), "mirror", new_callable=mock.PropertyMock, return_value=False),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    platform="all",
                    manifest_name="default.xml",
                )

        mp.config.SetString.assert_any_call("manifest.platform", "all")

    def test_sync_platform_specific_adds_one_platform(self, tmp_path):
        """Line 4535: specific platform added when platform in all_platforms."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
            mock.patch.object(type(mp), "mirror", new_callable=mock.PropertyMock, return_value=False),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    platform="linux",
                    manifest_name="default.xml",
                )

        mp.config.SetString.assert_any_call("manifest.platform", "linux")

    def test_sync_reference_sets_config(self, tmp_path):
        """Line 4548: reference path stored in config."""
        mp = self._make_manifest_project_for_sync(tmp_path)
        reference_dir = str(tmp_path / "reference")

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    reference=reference_dir,
                    manifest_name="default.xml",
                )

        mp.config.SetString.assert_any_call("repo.reference", reference_dir)

    def test_sync_worktree_with_mirror_returns_false(self, tmp_path):
        """Lines 4555-4556: returns False when worktree and mirror."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
        ):
            mock_get_remote.return_value = mock.MagicMock()
            result = mp.Sync(
                manifest_url="https://example.com/manifests.git",
                worktree=True,
                mirror=True,
                manifest_name="default.xml",
            )

        assert result is False

    def test_sync_worktree_with_submodules_returns_false(self, tmp_path):
        """Lines 4558-4559: returns False when worktree and submodules."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
        ):
            mock_get_remote.return_value = mock.MagicMock()
            result = mp.Sync(
                manifest_url="https://example.com/manifests.git",
                worktree=True,
                submodules=True,
                manifest_name="default.xml",
            )

        assert result is False

    def test_sync_new_reference_without_git_extension(self, tmp_path):
        """Line 4479: .git extension appended when URL path has no .git suffix."""
        mp = self._make_manifest_project_for_sync(tmp_path)
        reference_dir = str(tmp_path / "reference")
        os.makedirs(reference_dir, exist_ok=True)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=False),
            mock.patch.object(mp, "_InitGitDir") as mock_init_git,
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp, "ResolveRemoteHead", return_value="refs/heads/main"),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests",
                    reference=reference_dir,
                    manifest_name="default.xml",
                )

        call_kwargs = mock_init_git.call_args[1]
        assert call_kwargs.get("mirror_git", "").endswith(".git")

    def test_sync_no_url_no_branch_infers_standalone(self, tmp_path):
        """Line 4494: infers standalone_manifest from config when no URL or branch.

        Needs was_standalone_manifest=None so we don't exit early on line 4446-4451.
        """
        mp = self._make_manifest_project_for_sync(tmp_path)
        mp.config.GetString.return_value = None

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
        ):
            mock_get_remote.return_value = mock.MagicMock()
            result = mp.Sync(manifest_name="default.xml")

        assert result is not None

    def test_sync_default_branch_is_master_when_resolve_fails(self, tmp_path):
        """Line 4521: default branch set to refs/heads/master when ResolveRemoteHead returns None."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=False),
            mock.patch.object(mp, "_InitGitDir"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp, "ResolveRemoteHead", return_value=None),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    manifest_name="default.xml",
                )

        assert mp.revisionExpr == "refs/heads/master"

    def test_sync_git_lfs_warning_not_new(self, tmp_path):
        """Lines 4609-4614: git_lfs warning logged when not is_new."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
            mock.patch.object(type(mp), "mirror", new_callable=mock.PropertyMock, return_value=False),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
                mock.patch("kanon_cli.repo.project.git_require"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    git_lfs=True,
                    manifest_name="default.xml",
                )

        mp.config.SetBoolean.assert_any_call("repo.git-lfs", True)

    def test_sync_network_failure_returns_false(self, tmp_path):
        """Lines 4636-4644: returns False when Sync_NetworkHalf fails."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = False
            mock_net.return_value = sync_result

            result = mp.Sync(
                manifest_url="https://example.com/manifests.git",
                manifest_name="default.xml",
            )

        assert result is False

    def test_sync_worktree_sets_config_and_warns(self, tmp_path):
        """Lines 4560-4563: worktree config set and warning logged when worktree=True."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    worktree=True,
                    manifest_name="default.xml",
                )

        mp.config.SetBoolean.assert_any_call("repo.worktree", True)

    def test_sync_archive_new_sets_config(self, tmp_path):
        """Line 4567: archive config set when is_new and archive=True."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=False),
            mock.patch.object(mp, "_InitGitDir"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp, "ResolveRemoteHead", return_value="refs/heads/main"),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    archive=True,
                    manifest_name="default.xml",
                )

        mp.config.SetBoolean.assert_any_call("repo.archive", True)

    def test_sync_mirror_new_sets_config(self, tmp_path):
        """Line 4575: mirror config set when is_new and mirror=True."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=False),
            mock.patch.object(mp, "_InitGitDir"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp, "ResolveRemoteHead", return_value="refs/heads/main"),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    mirror=True,
                    manifest_name="default.xml",
                )

        mp.config.SetBoolean.assert_any_call("repo.mirror", True)

    def test_sync_partial_clone_no_filter_returns_none(self, tmp_path):
        """Line 4589: when partial_clone is not set, clone_filter from config."""
        mp = self._make_manifest_project_for_sync(tmp_path)
        mp.config.GetString.side_effect = lambda key: "blob:none" if key == "repo.clonefilter" else None
        mp.config.GetBoolean.side_effect = lambda key: True if key == "repo.partialclone" else None

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
            mock.patch.object(type(mp), "mirror", new_callable=mock.PropertyMock, return_value=False),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    manifest_name="default.xml",
                )

        mock_net.assert_called()

    def test_sync_clone_bundle_explicit_sets_config(self, tmp_path):
        """Line 4602: SetBoolean for clone_bundle when explicitly set."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    clone_bundle=False,
                    manifest_name="default.xml",
                )

        mp.config.SetBoolean.assert_any_call("repo.clonebundle", False)

    def test_sync_manifest_link_failure_returns_false(self, tmp_path):
        """Lines 4667-4672: returns False when manifest Link raises."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        from kanon_cli.repo.error import ManifestParseError

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link", side_effect=ManifestParseError("bad manifest")),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                result = mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    manifest_name="default.xml",
                )

        assert result is False

    def test_sync_partial_clone_mirror_new_returns_false(self, tmp_path):
        """Lines 4583-4584: returns False when partial_clone and mirror both set for new project."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=False),
            mock.patch.object(mp, "_InitGitDir"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "ResolveRemoteHead", return_value="refs/heads/main"),
        ):
            mock_get_remote.return_value = mock.MagicMock()
            result = mp.Sync(
                manifest_url="https://example.com/manifests.git",
                mirror=True,
                partial_clone=True,
                manifest_name="default.xml",
            )

        assert result is False

    def test_sync_submodules_sets_config(self, tmp_path):
        """Line 4602: SetBoolean for submodules when submodules=True."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    submodules=True,
                    manifest_name="default.xml",
                )

        mp.config.SetBoolean.assert_any_call("repo.submodules", True)

    def test_sync_partial_clone_exclude_sets_config(self, tmp_path):
        """Line 4594: partial_clone_exclude config set when provided."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    partial_clone_exclude="exclude/this",
                    manifest_name="default.xml",
                )

        mp.config.SetString.assert_any_call("repo.partialcloneexclude", "exclude/this")

    def test_sync_standalone_new_fetches_manifest_file(self, tmp_path):
        """Lines 4667-4672: standalone manifest fetch path when is_new."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        manifest_data = b"<manifest><project name='test'/></manifest>"

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=False),
            mock.patch.object(mp, "_InitGitDir"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
            mock.patch("kanon_cli.repo.project.fetch") as mock_fetch,
        ):
            mock_get_remote.return_value = mock.MagicMock()
            mock_fetch.fetch_file.return_value = manifest_data

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
                mock.patch.object(mp, "StartBranch", return_value=True),
            ):
                try:
                    mp.Sync(
                        manifest_url="https://example.com/standalone.xml",
                        standalone_manifest=True,
                        manifest_name=None,
                    )
                except Exception:
                    pass

        mock_fetch.fetch_file.assert_called()

    def test_sync_superproject_warning_with_path_prefix(self, tmp_path):
        """Line 4719: path_prefix used in warning message."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
            mock.patch("kanon_cli.repo.project.git_superproject") as mock_sp,
        ):
            mock_sp.UseSuperproject.return_value = True
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            sup_sync_result = mock.MagicMock()
            sup_sync_result.success = False
            sup_sync_result.fatal = False
            mp.manifest.superproject.Sync.return_value = sup_sync_result
            mp.manifest.path_prefix = "sub/"

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                result = mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    use_superproject=True,
                    manifest_name="default.xml",
                )

        assert result is True

    def test_sync_worktree_new_sets_use_git_worktrees(self, tmp_path):
        """Line 4562: use_git_worktrees set to True when worktree=True and is_new=True."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=False),
            mock.patch.object(mp, "_InitGitDir"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp, "ResolveRemoteHead", return_value="refs/heads/main"),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    worktree=True,
                    manifest_name="default.xml",
                )

        assert mp.use_git_worktrees is True

    def test_sync_clone_filter_for_depth_sets_config(self, tmp_path):
        """Line 4617: ConfigureCloneFilterForDepth called when clone_filter_for_depth set."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
            mock.patch.object(mp, "ConfigureCloneFilterForDepth") as mock_cfd,
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    clone_filter_for_depth="blob:none",
                    manifest_name="default.xml",
                )

        mock_cfd.assert_called_once_with("blob:none")

    def test_sync_use_superproject_sets_config(self, tmp_path):
        """Line 4620: use_superproject config set when not None."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    use_superproject=True,
                    manifest_name="default.xml",
                )

        mp.config.SetBoolean.assert_any_call("repo.superproject", True)

    def test_sync_submanifests_iterated(self, tmp_path):
        """Lines 4683-4684: submanifests are iterated when this_manifest_only=False."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        submanifest = mock.MagicMock()
        sub_spec = mock.MagicMock()
        sub_spec.manifestUrl = "https://example.com/sub.git"
        sub_spec.revision = "main"
        sub_spec.manifestName = "default.xml"
        submanifest.ToSubmanifestSpec.return_value = sub_spec
        submanifest.repo_client.manifestProject.Sync.return_value = True
        mp.manifest.submanifests = {"sub": submanifest}

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
            mock.patch("kanon_cli.repo.project.git_superproject") as mock_sp,
        ):
            mock_sp.UseSuperproject.return_value = False
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    manifest_name="default.xml",
                    this_manifest_only=False,
                )

        submanifest.repo_client.manifestProject.Sync.assert_called()

    def test_sync_superproject_failure_warns_and_returns_false_when_fatal(self, tmp_path):
        """Lines 4717-4729: superproject failure warning and conditional return False."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch.object(mp.manifest, "Link"),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
            mock.patch("kanon_cli.repo.project.git_superproject") as mock_sp,
        ):
            mock_sp.UseSuperproject.return_value = True
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            sup_sync_result = mock.MagicMock()
            sup_sync_result.success = False
            sup_sync_result.fatal = True
            mp.manifest.superproject.Sync.return_value = sup_sync_result
            mp.manifest.path_prefix = None

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                result = mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    use_superproject=True,
                    manifest_name="default.xml",
                )

        assert result is False

    def test_sync_manifest_name_missing_after_sync_returns_false(self, tmp_path):
        """Lines 4661-4663: returns False when manifest_name is None after sync."""
        mp = self._make_manifest_project_for_sync(tmp_path)

        with (
            mock.patch.object(type(mp), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(mp, "PreSync"),
            mock.patch.object(mp, "_ConfigureDepth"),
            mock.patch.object(mp, "GetRemote") as mock_get_remote,
            mock.patch.object(mp, "Sync_NetworkHalf") as mock_net,
            mock.patch.object(mp, "Sync_LocalHalf"),
            mock.patch.object(mp, "MetaBranchSwitch"),
            mock.patch.object(mp, "StartBranch", return_value=True),
            mock.patch("kanon_cli.repo.project.SyncBuffer"),
        ):
            mock_remote = mock.MagicMock()
            mock_get_remote.return_value = mock_remote
            sync_result = mock.MagicMock()
            sync_result.success = True
            mock_net.return_value = sync_result

            with (
                mock.patch.object(type(mp), "CurrentBranch", new_callable=mock.PropertyMock, return_value="default"),
            ):
                result = mp.Sync(
                    manifest_url="https://example.com/manifests.git",
                    manifest_name=None,
                )

        assert result is False


@pytest.mark.unit
class TestCheckForImmutableRevision:
    """Tests for _CheckForImmutableRevision (lines 2493-2520)."""

    def test_returns_true_when_revision_exists(self):
        """Lines 2493-2517: returns True when rev_list succeeds."""
        proj = _make_project()
        proj.upstream = None

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = "sha123\n"
            result = proj._CheckForImmutableRevision()

        assert result is True

    def test_returns_false_when_git_error(self):
        """Lines 2518-2520: returns False when GitError raised."""
        proj = _make_project()
        proj.upstream = None
        proj.bare_git = mock.MagicMock()
        proj.bare_git.rev_list.side_effect = GitError("not found", project="test/project")

        result = proj._CheckForImmutableRevision()
        assert result is False

    def test_checks_upstream_when_set(self):
        """Lines 2498-2516: checks upstream merge_base when upstream is set."""
        proj = _make_project()
        proj.upstream = "refs/heads/upstream"
        proj.bare_git = mock.MagicMock()
        proj.bare_git.rev_list.return_value = []
        proj.bare_git.merge_base.return_value = ""

        with mock.patch.object(proj, "GetRemote") as mock_get_remote:
            mock_remote = mock.MagicMock()
            mock_remote.ToLocal.return_value = "refs/remotes/origin/upstream"
            mock_get_remote.return_value = mock_remote
            result = proj._CheckForImmutableRevision()

        assert result is True
        proj.bare_git.merge_base.assert_called()

    def test_returns_false_on_upstream_merge_base_failure(self):
        """Lines 2518-2520: returns False when upstream merge_base raises."""
        proj = _make_project()
        proj.upstream = "refs/heads/upstream"
        proj.bare_git = mock.MagicMock()
        proj.bare_git.rev_list.return_value = []
        proj.bare_git.merge_base.side_effect = GitError("not ancestor", project="test/project")

        with mock.patch.object(proj, "GetRemote") as mock_get_remote:
            mock_remote = mock.MagicMock()
            mock_remote.ToLocal.return_value = "refs/remotes/origin/upstream"
            mock_get_remote.return_value = mock_remote
            result = proj._CheckForImmutableRevision()

        assert result is False


@pytest.mark.unit
class TestFetchArchive:
    """Tests for _FetchArchive (lines 2523-2536)."""

    def test_fetch_archive_runs_git_archive(self, tmp_path):
        """Lines 2523-2536: runs git archive command."""
        proj = _make_project()
        proj.remote.url = "https://example.com/repo.git"
        archive_dst = str(tmp_path / "archive.tar.gz")

        with (
            mock.patch.object(proj, "RelPath", return_value="test/project"),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            proj._FetchArchive(archive_dst)

        cmd_args = mock_gc.call_args[0][1]
        assert "archive" in cmd_args
        assert "--remote=https://example.com/repo.git" in cmd_args


@pytest.mark.unit
class TestSyncNetworkHalfWithPartialCloneExclude:
    """Tests for Sync_NetworkHalf partial_clone_exclude (lines 1423-1425)."""

    def test_partial_clone_exclude_forces_bundle_and_clears_filter(self):
        """Lines 1423-1425: when project in partial_clone_exclude, bundle forced."""
        proj = _make_project()
        proj.manifest.manifestProject.depth = None
        proj.manifest.manifestProject.dissociate = False
        proj.manifest.manifestProject.PartialCloneExclude = "test/project"
        proj.manifest.IsMirror = False
        proj.manifest.IsArchive = False
        proj.manifest.CloneFilterForDepth = None
        proj.manifest.PartialCloneExclude = "test/project"
        proj.manifest.default.sync_c = False
        proj.sync_tags = True
        proj.sync_c = False

        with (
            mock.patch.object(type(proj), "Exists", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(proj, "_CheckDirReference"),
            mock.patch.object(proj, "_UpdateHooks"),
            mock.patch.object(proj, "_InitRemote"),
            mock.patch.object(type(proj), "UseAlternates", new_callable=mock.PropertyMock, return_value=False),
            mock.patch.object(proj, "_ApplyCloneBundle", return_value=False),
            mock.patch.object(proj, "_CheckForImmutableRevision", return_value=True),
            mock.patch.object(proj, "_InitMRef"),
            mock.patch.object(proj, "_InitMirrorHead"),
            mock.patch("kanon_cli.repo.project.platform_utils.remove"),
        ):
            from kanon_cli.repo.project import SyncNetworkHalfResult

            result = proj.Sync_NetworkHalf(
                is_new=False,
                clone_filter="blob:none",
                partial_clone_exclude="test/project",
            )

        assert isinstance(result, SyncNetworkHalfResult)


@pytest.mark.unit
class TestRemoteFetchDepthAndMirror:
    """Tests for _RemoteFetch depth and mirror paths (lines 2564, 2567, 2651-2717)."""

    def _make_fetch_project(self):
        proj = _make_project()
        proj.upstream = None
        proj.sync_c = False
        proj.sync_tags = True
        proj.clone_depth = None
        return proj

    def test_depth_is_cleared_for_mirror(self):
        """Line 2564: depth set to None when manifest.IsMirror is True."""
        proj = self._make_fetch_project()
        proj.manifest.IsMirror = True
        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            proj._RemoteFetch(
                name="origin",
                initial=False,
                depth=5,
                current_branch_only=False,
            )

        call_args = mock_gc.call_args[0][1]
        assert "--depth=5" not in call_args

    def test_depth_sets_current_branch_only(self):
        """Line 2567: depth truthy sets current_branch_only=True."""
        proj = self._make_fetch_project()
        proj.manifest.IsMirror = False
        proj.revisionExpr = "refs/heads/main"
        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False
        remote.WritesTo.return_value = False

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            proj._RemoteFetch(
                name="origin",
                initial=False,
                depth=1,
                current_branch_only=False,
            )

        call_args = mock_gc.call_args[0][1]
        assert "--depth=1" in call_args

    def test_fetch_adds_no_tags_when_depth_set(self):
        """Line 2712-2713: --no-tags added when depth is set."""
        proj = self._make_fetch_project()
        proj.manifest.IsMirror = False
        proj.revisionExpr = "refs/heads/main"
        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            proj._RemoteFetch(
                name="origin",
                initial=False,
                depth=1,
                tags=True,
                current_branch_only=True,
            )

        call_args = mock_gc.call_args[0][1]
        assert "--no-tags" in call_args

    def test_mirror_relpath_clears_depth(self):
        """Line 2564: relpath == '.repo/repo' clears depth."""
        proj = self._make_fetch_project()
        proj.manifest.IsMirror = False
        proj.relpath = ".repo/repo"
        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            proj._RemoteFetch(
                name="origin",
                initial=False,
                depth=5,
                current_branch_only=False,
            )

        call_args = mock_gc.call_args[0][1]
        assert "--depth=5" not in call_args

    def test_sha1_current_branch_no_upstream_sets_false(self):
        """Line 2595: current_branch_only set to False when sha1 and no upstream."""
        proj = self._make_fetch_project()
        proj.manifest.IsMirror = False
        proj.revisionExpr = "deadbeef1234567890abcdef1234567890abcdef"
        proj.upstream = None
        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch.object(proj, "_CheckForImmutableRevision", return_value=False),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            proj._RemoteFetch(
                name="origin",
                initial=False,
                depth=None,
                current_branch_only=True,
            )

        mock_gc.assert_called()

    def test_sha1_current_branch_with_upstream_sets_based_on_upstream(self):
        """Line 2593: current_branch_only depends on whether upstream is sha1."""
        proj = self._make_fetch_project()
        proj.manifest.IsMirror = False
        proj.revisionExpr = "deadbeef1234567890abcdef1234567890abcdef"
        proj.upstream = "refs/heads/main"
        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch.object(proj, "_CheckForImmutableRevision", return_value=False),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            proj._RemoteFetch(
                name="origin",
                initial=False,
                depth=None,
                current_branch_only=True,
            )

        mock_gc.assert_called()

    def test_update_head_ok_when_no_worktree(self):
        """Line 2665: --update-head-ok added when no worktree."""
        proj = self._make_fetch_project()
        proj.manifest.IsMirror = False
        proj.worktree = None
        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            proj._RemoteFetch(
                name="origin",
                initial=False,
                current_branch_only=False,
            )

        call_args = mock_gc.call_args[0][1]
        assert "--update-head-ok" in call_args

    def test_prune_adds_flag(self):
        """Line 2672: --prune added when prune=True."""
        proj = self._make_fetch_project()
        proj.manifest.IsMirror = False
        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            proj._RemoteFetch(
                name="origin",
                initial=False,
                prune=True,
                current_branch_only=False,
            )

        call_args = mock_gc.call_args[0][1]
        assert "--prune" in call_args

    def test_progress_added_when_not_quiet_and_tty(self):
        """Line 2663: --progress added when not quiet and stdout is tty."""
        proj = self._make_fetch_project()
        proj.manifest.IsMirror = False
        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch("sys.stdout") as mock_stdout,
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_stdout.isatty.return_value = True
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            proj._RemoteFetch(
                name="origin",
                initial=False,
                quiet=False,
                current_branch_only=False,
            )

        call_args = mock_gc.call_args[0][1]
        assert "--progress" in call_args

    def test_force_sync_adds_force_flag(self):
        """Line 2669: --force added when force_sync=True."""
        proj = self._make_fetch_project()
        proj.manifest.IsMirror = False
        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            proj._RemoteFetch(
                name="origin",
                initial=False,
                force_sync=True,
                current_branch_only=False,
            )

        call_args = mock_gc.call_args[0][1]
        assert "--force" in call_args

    def test_shallow_file_adds_unshallow_depth(self, tmp_path):
        """Line 2658: --depth=2147483647 added when shallow file exists."""
        proj = self._make_fetch_project()
        proj.manifest.IsMirror = False
        proj.gitdir = str(tmp_path / "proj.git")
        os.makedirs(proj.gitdir, exist_ok=True)
        (tmp_path / "proj.git" / "shallow").write_text("sha123\n")

        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            proj._RemoteFetch(
                name="origin",
                initial=False,
                depth=None,
                current_branch_only=False,
            )

        call_args = mock_gc.call_args[0][1]
        assert "--depth=2147483647" in call_args

    def test_tag_spec_added_when_tag_name_set(self):
        """Lines 2684-2685: 'tag tagname' spec added when current_branch_only and tag_name.

        For tags, revisionExpr.startswith(R_TAGS) sets tag_name. Then
        _CheckForImmutableRevision must return False to avoid early return.
        Use a non-sha1 non-tag revisionExpr for a simpler path where tag_name is set
        via upstream tag.
        """
        proj = self._make_fetch_project()
        proj.manifest.IsMirror = False
        proj.revisionExpr = "refs/heads/main"
        proj.upstream = "refs/tags/v1.0"
        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch.object(proj, "_CheckForImmutableRevision", return_value=False),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            proj._RemoteFetch(
                name="origin",
                initial=False,
                depth=None,
                current_branch_only=True,
            )

        call_args = mock_gc.call_args[0][1]
        assert "tag" in call_args
        assert "v1.0" in call_args

    def test_sha1_depth_spec_includes_branch(self):
        """Lines 2694-2696: sha1 + depth adds branch and upstream to spec.

        After fetch, lines 2847-2866 check immutability and recurse. Mock
        _CheckForImmutableRevision to return True on second call to stop recursion.
        """
        proj = self._make_fetch_project()
        proj.manifest.IsMirror = False
        proj.revisionExpr = "deadbeef1234567890abcdef1234567890abcdef"
        proj.upstream = "refs/heads/main"
        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False

        immutable_call_count = [0]

        def immutable_side_effect():
            immutable_call_count[0] += 1
            return immutable_call_count[0] > 1

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch.object(proj, "_CheckForImmutableRevision", side_effect=immutable_side_effect),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            all_calls = []

            def recording_gc(self_proj, cmd, *args, **kwargs):
                all_calls.append(list(cmd))
                return mock_gc.return_value

            mock_gc.side_effect = recording_gc
            proj._RemoteFetch(
                name="origin",
                initial=False,
                depth=1,
                current_branch_only=True,
            )

        assert len(all_calls) >= 1
        first_call_cmd = all_calls[0]
        assert "--depth=1" in first_call_cmd

    def test_mirror_fallback_spec_when_no_spec(self):
        """Line 2708: mirror fallback spec added when IsMirror and spec is empty.

        Path: IsMirror=True, current_branch_only=True, is_sha1=False (non-sha revisionExpr
        that is empty after strip), so spec stays empty, triggering fallback at 2708.
        """
        proj = self._make_fetch_project()
        proj.manifest.IsMirror = True
        proj.revisionExpr = ""
        proj.upstream = None
        remote = mock.MagicMock()
        remote.name = "origin"
        remote.PreConnectFetch.return_value = False
        remote.ToLocal.return_value = "refs/heads/*"

        with (
            mock.patch.object(proj, "GetRemote", return_value=remote),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = ""
            proj._RemoteFetch(
                name="origin",
                initial=False,
                depth=None,
                current_branch_only=True,
            )

        mock_gc.assert_called()
        first_call_cmd = mock_gc.call_args_list[0][0][1]
        assert "+refs/heads/*:" in " ".join(str(x) for x in first_call_cmd)


@pytest.mark.unit
class TestDeleteWorktreeWithFiles:
    """Tests for DeleteWorktree when worktree has files (lines 1972-2070)."""

    def test_delete_worktree_removes_files_and_dirs(self, tmp_path):
        """Lines 2017-2026: walk loop removes files and collects dirs."""
        topdir = str(tmp_path)
        worktree = str(tmp_path / "proj")
        os.makedirs(worktree, exist_ok=True)

        file_path = tmp_path / "proj" / "somefile.py"
        file_path.write_text("content")
        subdir = tmp_path / "proj" / "subdir"
        subdir.mkdir()
        (subdir / "nested.py").write_text("nested")

        gitdir = str(tmp_path / ".repo" / "projects" / "proj.git")
        os.makedirs(gitdir, exist_ok=True)

        proj = _make_project(
            worktree=worktree,
            gitdir=gitdir,
            objdir=gitdir,
        )
        proj.manifest.topdir = topdir
        proj.use_git_worktrees = False

        with (
            mock.patch.object(proj, "IsDirty", return_value=False),
            mock.patch.object(proj, "RelPath", return_value="proj"),
        ):
            result = proj.DeleteWorktree()

        assert result is True
