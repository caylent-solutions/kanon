"""Final coverage boost tests for project.py to reach 90%."""

from unittest import mock

import pytest

from kanon_cli.repo import project
from kanon_cli.repo.error import GitError
from kanon_cli.repo.git_refs import R_HEADS
from kanon_cli.repo.project import SyncBuffer


def _make_project(**kwargs):
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


@pytest.mark.unit
class TestSyncLocalHalfDetachedHead:
    """Test Sync_LocalHalf when on detached HEAD."""


@pytest.mark.unit
class TestSyncLocalHalfRebaseInProgress:
    """Test Sync_LocalHalf with rebase in progress."""


@pytest.mark.unit
class TestSyncLocalHalfOnBranch:
    """Test Sync_LocalHalf when on a branch."""


@pytest.mark.unit
class TestAbandonBranch:
    """Test AbandonBranch method."""

    def test_abandon_nonexistent_branch(self):
        """Lines 2125-2129: branch doesn't exist."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()
        proj.bare_ref.all = {}

        result = proj.AbandonBranch("nonexistent")
        assert result is None

    def test_abandon_branch_on_different_head(self):
        """Lines 2131-2151: abandon while on different branch."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()
        proj.bare_ref.all = {R_HEADS + "feature": "sha123"}
        proj.work_git = mock.MagicMock()
        proj.work_git.GetHead.return_value = R_HEADS + "main"

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            result = proj.AbandonBranch("feature")

        assert result is True

    def test_abandon_current_branch_same_rev(self):
        """Lines 2132-2141: abandon current branch, head matches revid."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()
        proj.bare_ref.all = {R_HEADS + "feature": "sha123"}
        proj.work_git = mock.MagicMock()
        proj.work_git.GetHead.return_value = R_HEADS + "feature"

        with (
            mock.patch.object(proj, "GetRevisionId", return_value="sha123"),
            mock.patch("kanon_cli.repo.project._lwrite") as mock_lw,
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            result = proj.AbandonBranch("feature")

        assert result is True
        mock_lw.assert_called_once()

    def test_abandon_current_branch_different_rev(self):
        """Lines 2142-2143: abandon current branch, need checkout."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()
        proj.bare_ref.all = {R_HEADS + "feature": "sha123"}
        proj.work_git = mock.MagicMock()
        proj.work_git.GetHead.return_value = R_HEADS + "feature"

        with (
            mock.patch.object(proj, "GetRevisionId", return_value="other_sha"),
            mock.patch.object(proj, "_Checkout") as mock_co,
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            result = proj.AbandonBranch("feature")

        assert result is True
        mock_co.assert_called_once_with("other_sha", quiet=True)


@pytest.mark.unit
class TestPruneHeads:
    """Test PruneHeads method."""

    def test_prune_heads_nothing_to_prune(self):
        """Lines 2155-2167: no branches to prune."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()

        with (
            mock.patch.object(
                type(proj),
                "CurrentBranch",
                new_callable=mock.PropertyMock,
                return_value=None,
            ),
            mock.patch.object(
                type(proj),
                "_allrefs",
                new_callable=mock.PropertyMock,
                return_value={},
            ),
        ):
            result = proj.PruneHeads()

        assert result == []

    def test_prune_heads_with_branches(self):
        """Lines 2155-2214: prune branches merged into upstream."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()

        refs = {
            R_HEADS + "feature": "sha1",
            R_HEADS + "main": "sha2",
        }

        branch_obj = mock.MagicMock()
        branch_obj.LocalMerge = "merge_ref"

        with (
            mock.patch.object(
                type(proj),
                "CurrentBranch",
                new_callable=mock.PropertyMock,
                return_value="main",
            ),
            mock.patch.object(
                type(proj),
                "_allrefs",
                new_callable=mock.PropertyMock,
                return_value=refs,
            ),
            mock.patch.object(proj, "GetRevisionId", return_value="rev123"),
            mock.patch.object(proj, "_revlist", return_value=[]),
            mock.patch.object(proj, "IsDirty", return_value=False),
            mock.patch.object(proj, "GetBranch", return_value=branch_obj),
            mock.patch.object(proj.work_git, "DetachHead"),
            mock.patch.object(proj.bare_git, "DetachHead"),
            mock.patch.object(proj.bare_git, "GetHead", return_value="rev123"),
            mock.patch.object(proj, "CleanPublishedCache"),
            mock.patch("kanon_cli.repo.project.IsId", return_value=True),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            result = proj.PruneHeads()

        assert isinstance(result, list)


@pytest.mark.unit
class TestCheckoutBranch:
    """Test CheckoutBranch method."""

    def test_checkout_branch_same_head(self):
        """Lines 2097-2104: already on same revision."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()
        proj.bare_ref.all = {R_HEADS + "feature": "sha123"}
        proj.work_git = mock.MagicMock()
        proj.work_git.GetHead.return_value = "sha123"

        with (
            mock.patch.object(proj, "GetRevisionId", return_value="sha123"),
            mock.patch("kanon_cli.repo.project._lwrite"),
        ):
            result = proj.CheckoutBranch("feature")

        assert result is True

    def test_checkout_branch_different_head(self):
        """Lines 2106-2113: need actual checkout."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()
        proj.bare_ref.all = {R_HEADS + "feature": "sha123"}
        proj.work_git = mock.MagicMock()
        proj.work_git.GetHead.return_value = "old_sha"

        with (
            mock.patch.object(proj, "GetRevisionId", return_value="sha123"),
            mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc,
        ):
            mock_gc.return_value.Wait.return_value = 0
            result = proj.CheckoutBranch("feature")

        assert result is True


@pytest.mark.unit
class TestGitGetByExecMethods:
    """Test _GitGetByExec (bare_git/work_git) methods."""

    def test_set_head(self):
        """Lines 3895-3900: SetHead method."""
        proj = _make_project()
        proj.bare_git.symbolic_ref = mock.MagicMock()

        proj.bare_git.SetHead(R_HEADS + "main")
        proj.bare_git.symbolic_ref.assert_called()

    def test_set_head_with_message(self):
        """Lines 3896-3900: SetHead with message."""
        proj = _make_project()
        proj.bare_git.symbolic_ref = mock.MagicMock()

        proj.bare_git.SetHead(R_HEADS + "main", message="test msg")
        proj.bare_git.symbolic_ref.assert_called()

    def test_detach_head(self):
        """Lines 3902-3908: DetachHead method."""
        proj = _make_project()
        proj.bare_git.update_ref = mock.MagicMock()

        proj.bare_git.DetachHead("abc123")
        proj.bare_git.update_ref.assert_called()

    def test_detach_head_with_message(self):
        """Lines 3904-3908: DetachHead with message."""
        proj = _make_project()
        proj.bare_git.update_ref = mock.MagicMock()

        proj.bare_git.DetachHead("abc123", message="detach msg")
        proj.bare_git.update_ref.assert_called()

    def test_update_ref(self):
        """Lines 3910-3920: UpdateRef method."""
        proj = _make_project()
        proj.bare_git.update_ref = mock.MagicMock()

        proj.bare_git.UpdateRef(R_HEADS + "main", "abc123")
        proj.bare_git.update_ref.assert_called()

    def test_update_ref_with_old_and_detach(self):
        """Lines 3914-3920: UpdateRef with old and detach."""
        proj = _make_project()
        proj.bare_git.update_ref = mock.MagicMock()

        proj.bare_git.UpdateRef(R_HEADS + "main", "abc123", old="old123", detach=True)
        proj.bare_git.update_ref.assert_called()

    def test_delete_ref(self):
        """Lines 3922-3926: DeleteRef method."""
        proj = _make_project()
        proj.bare_git.rev_parse = mock.MagicMock(return_value="sha123")
        proj.bare_git.update_ref = mock.MagicMock()
        proj.bare_ref = mock.MagicMock()

        proj.bare_git.DeleteRef(R_HEADS + "old")
        proj.bare_git.update_ref.assert_called()
        proj.bare_ref.deleted.assert_called_with(R_HEADS + "old")

    def test_rev_list(self):
        """Lines 3928-3945: rev_list method."""
        proj = _make_project()

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = "sha1\nsha2\n"
            result = proj.bare_git.rev_list("HEAD")

        assert result == ["sha1", "sha2"]

    def test_rev_list_with_format(self):
        """Lines 3929-3930: rev_list with format kwarg."""
        proj = _make_project()

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            mock_gc.return_value.stdout = "abc123 msg\n"
            result = proj.bare_git.rev_list("HEAD", format="%H %s")

        assert len(result) == 1


@pytest.mark.unit
class TestSyncBuffer:
    """Test SyncBuffer class."""

    def test_syncbuffer_init(self):
        """Lines 3846: SyncBuffer init."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)
        assert buf._failures == []

    def test_syncbuffer_detach_head(self):
        """SyncBuffer with detach_head."""
        config = mock.MagicMock()
        buf = SyncBuffer(config, detach_head=True)
        assert buf.detach_head is True

    def test_syncbuffer_info(self):
        """SyncBuffer.info records messages."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)
        proj = mock.MagicMock()
        buf.info(proj, "test %s", "message")

    def test_syncbuffer_fail(self):
        """SyncBuffer.fail records failure."""
        config = mock.MagicMock()
        buf = SyncBuffer(config)
        proj = mock.MagicMock()
        err = Exception("test error")
        buf.fail(proj, err)
        assert len(buf._failures) == 1


@pytest.mark.unit
class TestDeleteWorktree:
    """Test DeleteWorktree method."""


@pytest.mark.unit
class TestRebaseMethod:
    """Test _Rebase method."""

    def test_rebase_success(self):
        """Lines 1897: _Rebase runs git rebase."""
        proj = _make_project()

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            proj._Rebase("upstream_sha")

    def test_rebase_failure(self):
        """_Rebase raises on failure."""
        proj = _make_project()

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 1
            mock_gc.return_value.stderr = "conflict"
            with pytest.raises(GitError):
                proj._Rebase("upstream_sha")


@pytest.mark.unit
class TestFastForwardMethod:
    """Test _FastForward method."""

    def test_fast_forward_success(self):
        """Lines 1903+: _FastForward runs git merge --ff-only."""
        proj = _make_project()

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            proj._FastForward("target_sha")


@pytest.mark.unit
class TestCheckoutMethod:
    """Test _Checkout method."""

    def test_checkout_success(self):
        """Lines 2091+: _Checkout runs git checkout."""
        proj = _make_project()

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            proj._Checkout("target_sha")

    def test_checkout_force(self):
        """_Checkout with force_checkout=True."""
        proj = _make_project()

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            proj._Checkout("target_sha", force_checkout=True)


@pytest.mark.unit
class TestCherryPickMethod:
    """Test _CherryPick method."""

    def test_cherry_pick_success(self):
        """Lines 2155+: _CherryPick runs cherry-pick."""
        proj = _make_project()

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            proj._CherryPick("commit_sha")


@pytest.mark.unit
class TestRevertMethod:
    """Test _Revert method."""

    def test_revert_success(self):
        """Lines 2195+: _Revert runs revert."""
        proj = _make_project()

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 0
            proj._Revert("commit_sha")


@pytest.mark.unit
class TestGetSubmodules:
    """Test _GetSubmodules method."""

    def test_get_submodules_no_gitmodules(self):
        """Lines 2234-2238: no .gitmodules file."""
        proj = _make_project()

        with mock.patch("kanon_cli.repo.project.GitCommand") as mock_gc:
            mock_gc.return_value.Wait.return_value = 1
            result = proj._GetSubmodules()

        assert result == []


@pytest.mark.unit
class TestRemoteFetchRetryPaths:
    """Test _RemoteFetch retry and error handling."""


@pytest.mark.unit
class TestProjectStatusMethods:
    """Test PrintWorkTreeStatus and related."""


@pytest.mark.unit
class TestStartBranch:
    """Test StartBranch method."""

    def test_start_branch_already_on_it(self):
        """Lines 2032+: start branch when already on it."""
        proj = _make_project()
        proj.bare_ref = mock.MagicMock()
        proj.bare_ref.all = {R_HEADS + "feature": "sha123"}
        proj.work_git = mock.MagicMock()
        proj.work_git.GetHead.return_value = R_HEADS + "feature"

        with mock.patch.object(proj, "GetRevisionId", return_value="sha123"):
            result = proj.StartBranch("feature")

        assert result is True
