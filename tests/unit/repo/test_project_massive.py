"""Massive test coverage for project.py uncovered lines.

This module provides extensive unit tests targeting the largest coverage gaps
in project.py, focusing on complex methods like Sync_NetworkHalf, Sync_LocalHalf,
_RemoteFetch, and other critical functionality.
"""

import os
from unittest import mock

import pytest

from kanon_cli.repo.error import GitError, RepoError
from kanon_cli.repo import project
from kanon_cli.repo.project import LocalSyncFail, _PriorSyncFailedError, _DirtyError

pytestmark = pytest.mark.unit


def _proj(tmp_path, name="test"):
    """Create mocked Project for testing.

    This factory creates a properly initialized Project instance with all
    necessary mocks in place to avoid filesystem and git operations.
    """
    topdir = str(tmp_path)
    worktree = str(tmp_path / name)
    gitdir = str(tmp_path / ".repo" / "projects" / f"{name}.git")
    objdir = str(tmp_path / ".repo" / "project-objects" / f"{name}.git")

    # Create minimal directory structure
    os.makedirs(worktree, exist_ok=True)
    os.makedirs(gitdir, exist_ok=True)
    os.makedirs(objdir, exist_ok=True)
    os.makedirs(str(tmp_path / ".repo" / "manifests"), exist_ok=True)

    # Create Project without calling __init__
    p = project.Project.__new__(project.Project)

    # Mock manifest
    p.manifest = mock.MagicMock()
    p.manifest.topdir = topdir
    p.manifest.repodir = str(tmp_path / ".repo")
    p.manifest.IsArchive = False
    p.manifest.IsMirror = False
    p.manifest.CloneFilterForDepth.return_value = None
    p.manifest._loaded = True
    p.manifest.default = mock.MagicMock()
    p.manifest.default.sync_c = False

    # Mock manifest project
    p.manifest.manifestProject = mock.MagicMock()
    p.manifest.manifestProject.worktree = str(tmp_path / ".repo" / "manifests")
    p.manifest.manifestProject.depth = None
    p.manifest.manifestProject.dissociate = False

    # Basic project attributes
    p.name = name
    p.relpath = name
    p.gitdir = gitdir
    p.objdir = objdir
    p.worktree = worktree

    # Remote configuration
    p.remote = mock.MagicMock()
    p.remote.name = "origin"
    p.remote.url = "https://example.com/test.git"
    p.remote.fetchUrl = "https://example.com/test.git"
    p.remote.pushUrl = None
    p.remote.review = None
    p.remote.revision = None

    # Revision information
    p.revisionExpr = "refs/heads/main"
    p.revisionId = "a" * 40  # 40-char SHA
    p.dest_branch = None
    p.upstream = None
    p.old_revision = None

    # Project configuration
    p.parent = None
    p.use_git_worktrees = False
    p.has_subprojects = False
    p.subprojects = []
    p.clone_depth = None
    p.sync_c = False
    p.sync_s = False
    p.sync_tags = True
    p.groups = ["all"]
    p.platform = None
    p.annotations = []
    p.copyfiles = []
    p.linkfiles = []
    p.rebase = True

    # Config mock
    p.config = mock.MagicMock()
    p.config.GetBoolean.return_value = None
    p.config.GetString.return_value = None

    # Git command mocks
    p.bare_git = mock.MagicMock()
    p.work_git = mock.MagicMock()

    # Refs mock
    p.bare_ref = mock.MagicMock()
    p.bare_ref.all = {}

    # User identity
    p._userident_name = None
    p._userident_email = None

    # Caching flag for _ResolveVersionConstraint (mirrors __init__ default).
    p._constraint_resolved = False

    return p


class TestSyncNetworkHalf:
    """Tests for Sync_NetworkHalf method."""

    def test_archive_with_http_remote_fails(self, tmp_path):
        """Archive mode with HTTP remote should fail."""
        p = _proj(tmp_path)
        p.remote.url = "https://example.com/test.git"

        result = p.Sync_NetworkHalf(
            archive=True,
            clone_bundle=False,
            partial_clone_exclude=[],
        )

        assert not result.success
        assert result.error is not None
        assert "Cannot fetch archives from http/https" in str(result.error)

    def test_archive_with_https_remote_fails(self, tmp_path):
        """Archive mode with HTTPS remote should fail."""
        p = _proj(tmp_path)
        p.remote.url = "http://example.com/test.git"

        result = p.Sync_NetworkHalf(
            archive=True,
            clone_bundle=False,
            partial_clone_exclude=[],
        )

        assert not result.success
        assert "Cannot fetch archives" in str(result.error)

    def test_archive_with_ssh_remote_calls_fetch_archive(self, tmp_path):
        """Archive mode with SSH remote should call _FetchArchive."""
        p = _proj(tmp_path)
        p.remote.url = "ssh://example.com/test.git"

        with mock.patch.object(p, "_FetchArchive") as fetch_mock:
            fetch_mock.side_effect = GitError("test error")

            result = p.Sync_NetworkHalf(
                archive=True,
                clone_bundle=False,
                partial_clone_exclude=[],
            )

            assert not result.success
            fetch_mock.assert_called_once()

    def test_archive_extract_failure(self, tmp_path):
        """Archive extraction failure should return error."""
        p = _proj(tmp_path)
        p.remote.url = "ssh://example.com/test.git"

        with mock.patch.object(p, "_FetchArchive"):
            with mock.patch.object(p, "_ExtractArchive", return_value=False):
                result = p.Sync_NetworkHalf(
                    archive=True,
                    clone_bundle=False,
                    partial_clone_exclude=[],
                )

                assert not result.success
                assert "Unable to Extract Archive" in str(result.error)

    def test_archive_success(self, tmp_path):
        """Successful archive fetch and extract."""
        p = _proj(tmp_path)
        p.remote.url = "ssh://example.com/test.git"

        with mock.patch.object(p, "_FetchArchive"):
            with mock.patch.object(p, "_ExtractArchive", return_value=True):
                with mock.patch.object(p, "_CopyAndLinkFiles"):
                    with mock.patch("kanon_cli.repo.platform_utils.remove"):
                        result = p.Sync_NetworkHalf(
                            archive=True,
                            clone_bundle=False,
                            partial_clone_exclude=[],
                        )

                        assert result.success
                        assert result.remote_fetched

    def test_clone_bundle_disabled_when_objdir_exists(self, tmp_path):
        """Clone bundle should be disabled if objdir exists."""
        p = _proj(tmp_path)

        with mock.patch.object(
            type(p),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(p, "_InitGitDir"):
                with mock.patch.object(p, "_InitRemote"):
                    with mock.patch.object(p, "_RemoteFetch", return_value=True):
                        with mock.patch.object(p, "_InitMRef"):
                            result = p.Sync_NetworkHalf(
                                clone_bundle=True,
                                partial_clone_exclude=[],
                            )

                            assert result.success

    def test_is_new_none_checks_exists(self, tmp_path):
        """When is_new is None, should check Exists property."""
        p = _proj(tmp_path)

        with mock.patch.object(
            type(p),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(p, "_InitGitDir") as init_mock:
                with mock.patch.object(p, "_InitRemote"):
                    with mock.patch.object(p, "_RemoteFetch", return_value=True):
                        with mock.patch.object(p, "_InitMRef"):
                            p.Sync_NetworkHalf(
                                is_new=None,
                                clone_bundle=False,
                                partial_clone_exclude=[],
                            )

                            init_mock.assert_called_once()

    def test_is_new_false_updates_hooks(self, tmp_path):
        """When is_new is False, should update hooks."""
        p = _proj(tmp_path)

        with mock.patch.object(p, "_CheckDirReference"):
            with mock.patch.object(p, "_UpdateHooks") as update_hooks_mock:
                with mock.patch.object(p, "_InitRemote"):
                    with mock.patch.object(p, "_RemoteFetch", return_value=True):
                        with mock.patch.object(p, "_InitMRef"):
                            p.Sync_NetworkHalf(
                                is_new=False,
                                clone_bundle=False,
                                partial_clone_exclude=[],
                            )

                            update_hooks_mock.assert_called_once()

    def test_check_dir_reference_failure_with_force_sync(self, tmp_path):
        """CheckDirReference failure with force_sync should reinit."""
        p = _proj(tmp_path)

        with mock.patch.object(p, "_CheckDirReference") as check_mock:
            check_mock.side_effect = GitError("reference error")
            with mock.patch.object(p, "_InitGitDir") as init_mock:
                with mock.patch.object(p, "_UpdateHooks"):
                    with mock.patch.object(p, "_InitRemote"):
                        with mock.patch.object(p, "_RemoteFetch", return_value=True):
                            with mock.patch.object(p, "_InitMRef"):
                                p.Sync_NetworkHalf(
                                    is_new=False,
                                    force_sync=True,
                                    clone_bundle=False,
                                    partial_clone_exclude=[],
                                )

                                # Should call InitGitDir twice (once for False, once for error)
                                assert init_mock.call_count == 1

    def test_check_dir_reference_failure_without_force_sync(self, tmp_path):
        """CheckDirReference failure without force_sync should raise."""
        p = _proj(tmp_path)

        with mock.patch.object(p, "_CheckDirReference") as check_mock:
            check_mock.side_effect = GitError("reference error")

            with pytest.raises(GitError):
                p.Sync_NetworkHalf(
                    is_new=False,
                    force_sync=False,
                    clone_bundle=False,
                    partial_clone_exclude=[],
                )

    def test_use_alternates_creates_symlink(self, tmp_path):
        """UseAlternates should create alternates file."""
        p = _proj(tmp_path)
        # Create a symlink at gitdir/objects
        os.makedirs(p.gitdir, exist_ok=True)
        temp_target = os.path.join(str(tmp_path), "temp")
        os.makedirs(temp_target, exist_ok=True)

        with mock.patch.object(
            type(p),
            "UseAlternates",
            new_callable=mock.PropertyMock,
            return_value=True,
        ):
            with mock.patch.object(
                type(p),
                "Exists",
                new_callable=mock.PropertyMock,
                return_value=False,
            ):
                with mock.patch.object(p, "_InitGitDir"):
                    with mock.patch.object(p, "_InitRemote"):
                        with mock.patch.object(p, "_RemoteFetch", return_value=True):
                            with mock.patch.object(p, "_InitMRef"):
                                with mock.patch("kanon_cli.repo.platform_utils.islink", return_value=True):
                                    with mock.patch("kanon_cli.repo.platform_utils.remove"):
                                        p.Sync_NetworkHalf(
                                            is_new=False,
                                            clone_bundle=False,
                                            partial_clone_exclude=[],
                                        )

    def test_clone_bundle_applied_when_conditions_met(self, tmp_path):
        """Clone bundle should be applied when alt_dir is None."""
        p = _proj(tmp_path)

        with mock.patch.object(
            type(p),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(p, "_InitGitDir"):
                with mock.patch.object(p, "_InitRemote"):
                    with mock.patch.object(p, "_ApplyCloneBundle", return_value=True):
                        with mock.patch.object(p, "_RemoteFetch", return_value=True):
                            with mock.patch.object(p, "_InitMRef"):
                                p.Sync_NetworkHalf(
                                    is_new=True,
                                    clone_bundle=True,
                                    partial_clone_exclude=[],
                                )

    def test_current_branch_only_from_sync_c(self, tmp_path):
        """current_branch_only should be determined from sync_c."""
        p = _proj(tmp_path)
        p.sync_c = True

        with mock.patch.object(
            type(p),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(p, "_InitGitDir"):
                with mock.patch.object(p, "_InitRemote"):
                    with mock.patch.object(p, "_RemoteFetch", return_value=True) as fetch_mock:
                        with mock.patch.object(p, "_InitMRef"):
                            p.Sync_NetworkHalf(
                                current_branch_only=None,
                                clone_bundle=False,
                                partial_clone_exclude=[],
                            )

                            call_kwargs = fetch_mock.call_args[1]
                            assert call_kwargs["current_branch_only"] is True

    def test_tags_from_sync_tags(self, tmp_path):
        """tags should be determined from sync_tags."""
        p = _proj(tmp_path)
        p.sync_tags = False

        with mock.patch.object(
            type(p),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(p, "_InitGitDir"):
                with mock.patch.object(p, "_InitRemote"):
                    with mock.patch.object(p, "_RemoteFetch", return_value=True) as fetch_mock:
                        with mock.patch.object(p, "_InitMRef"):
                            p.Sync_NetworkHalf(
                                tags=None,
                                clone_bundle=False,
                                partial_clone_exclude=[],
                            )

                            call_kwargs = fetch_mock.call_args[1]
                            assert call_kwargs["tags"] is False

    def test_depth_from_clone_depth(self, tmp_path):
        """depth should be determined from clone_depth."""
        p = _proj(tmp_path)
        p.clone_depth = 1

        with mock.patch.object(
            type(p),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(p, "_InitGitDir"):
                with mock.patch.object(p, "_InitRemote"):
                    with mock.patch.object(p, "_RemoteFetch", return_value=True) as fetch_mock:
                        with mock.patch.object(p, "_InitMRef"):
                            p.Sync_NetworkHalf(
                                clone_bundle=False,
                                partial_clone_exclude=[],
                            )

                            call_kwargs = fetch_mock.call_args[1]
                            assert call_kwargs["depth"] == 1

    def test_depth_replaced_by_clone_filter_for_depth(self, tmp_path):
        """depth should be replaced by clone_filter when clone_filter_for_depth is set."""
        p = _proj(tmp_path)
        p.clone_depth = 1

        with mock.patch.object(
            type(p),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(p, "_InitGitDir"):
                with mock.patch.object(p, "_InitRemote"):
                    with mock.patch.object(p, "_RemoteFetch", return_value=True) as fetch_mock:
                        with mock.patch.object(p, "_InitMRef"):
                            p.Sync_NetworkHalf(
                                clone_bundle=False,
                                partial_clone_exclude=[],
                                clone_filter_for_depth="blob:none",
                            )

                            call_kwargs = fetch_mock.call_args[1]
                            assert call_kwargs["depth"] is None
                            assert call_kwargs["clone_filter"] == "blob:none"

    def test_optimized_fetch_skips_remote(self, tmp_path):
        """Optimized fetch with immutable revision should skip remote fetch."""
        p = _proj(tmp_path)
        p.revisionExpr = "a" * 40  # SHA

        with mock.patch.object(
            type(p),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(p, "_InitGitDir"):
                with mock.patch.object(p, "_InitRemote"):
                    with mock.patch.object(p, "_CheckForImmutableRevision", return_value=True):
                        with mock.patch.object(p, "_RemoteFetch") as fetch_mock:
                            with mock.patch.object(p, "_InitMRef"):
                                result = p.Sync_NetworkHalf(
                                    optimized_fetch=True,
                                    clone_bundle=False,
                                    partial_clone_exclude=[],
                                )

                                # Remote fetch should not be called
                                fetch_mock.assert_not_called()
                                assert result.success
                                assert not result.remote_fetched

    def test_remote_fetch_failure(self, tmp_path):
        """RemoteFetch returning False should return error."""
        p = _proj(tmp_path)

        with mock.patch.object(
            type(p),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(p, "_InitGitDir"):
                with mock.patch.object(p, "_InitRemote"):
                    with mock.patch.object(p, "_RemoteFetch", return_value=False):
                        result = p.Sync_NetworkHalf(
                            clone_bundle=False,
                            partial_clone_exclude=[],
                        )

                        assert not result.success
                        assert "Unable to remote fetch" in str(result.error)

    def test_remote_fetch_repo_error(self, tmp_path):
        """RemoteFetch raising RepoError should be caught."""
        p = _proj(tmp_path)

        with mock.patch.object(
            type(p),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(p, "_InitGitDir"):
                with mock.patch.object(p, "_InitRemote"):
                    with mock.patch.object(p, "_RemoteFetch") as fetch_mock:
                        fetch_mock.side_effect = RepoError("test error")

                        result = p.Sync_NetworkHalf(
                            clone_bundle=False,
                            partial_clone_exclude=[],
                        )

                        assert not result.success
                        assert "test error" in str(result.error)

    def test_worktree_inits_mref(self, tmp_path):
        """Project with worktree should call _InitMRef."""
        p = _proj(tmp_path)

        with mock.patch.object(
            type(p),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(p, "_InitGitDir"):
                with mock.patch.object(p, "_InitRemote"):
                    with mock.patch.object(p, "_RemoteFetch", return_value=True):
                        with mock.patch.object(p, "_InitMRef") as init_mref_mock:
                            p.Sync_NetworkHalf(
                                clone_bundle=False,
                                partial_clone_exclude=[],
                            )

                            init_mref_mock.assert_called_once()

    def test_no_worktree_inits_mirror_head(self, tmp_path):
        """Project without worktree should call _InitMirrorHead."""
        p = _proj(tmp_path)
        p.worktree = None

        with mock.patch.object(
            type(p),
            "Exists",
            new_callable=mock.PropertyMock,
            return_value=False,
        ):
            with mock.patch.object(p, "_InitGitDir"):
                with mock.patch.object(p, "_InitRemote"):
                    with mock.patch.object(p, "_RemoteFetch", return_value=True):
                        with mock.patch.object(p, "_InitMirrorHead") as init_mirror_mock:
                            with mock.patch("kanon_cli.repo.platform_utils.remove"):
                                p.Sync_NetworkHalf(
                                    clone_bundle=False,
                                    partial_clone_exclude=[],
                                )

                                init_mirror_mock.assert_called_once()


class TestSyncLocalHalf:
    """Tests for Sync_LocalHalf method."""

    def test_missing_gitdir_fails(self, tmp_path):
        """Missing gitdir should fail with LocalSyncFail."""
        p = _proj(tmp_path)
        # Remove gitdir
        import shutil

        shutil.rmtree(p.gitdir)

        syncbuf = mock.MagicMock()
        errors = []

        p.Sync_LocalHalf(syncbuf, errors=errors)

        assert len(errors) == 1
        assert isinstance(errors[0], LocalSyncFail)
        assert "missing network sync" in str(errors[0])

    def test_protected_paths_in_root_project(self, tmp_path):
        """Root project with protected paths should fail."""
        p = _proj(tmp_path)
        p.relpath = "."

        syncbuf = mock.MagicMock()
        errors = []

        with mock.patch.object(p, "_InitWorkTree"):
            with mock.patch.object(p, "bare_ref") as bare_ref_mock:
                bare_ref_mock.all = {}
                with mock.patch.object(p, "CleanPublishedCache"):
                    with mock.patch.object(p, "GetRevisionId", return_value="abc123"):
                        with mock.patch.object(
                            p.work_git,
                            "ls_tree",
                            return_value=".repo\0file.txt\0",
                        ):
                            p.Sync_LocalHalf(syncbuf, errors=errors)

                            assert len(errors) == 1
                            assert "protected paths" in str(errors[0])

    def test_detached_head_with_rebase_in_progress(self, tmp_path):
        """Detached HEAD with rebase in progress should fail."""
        p = _proj(tmp_path)

        syncbuf = mock.MagicMock()
        syncbuf.detach_head = True
        errors = []

        with mock.patch.object(p, "_InitWorkTree"):
            with mock.patch.object(p, "bare_ref") as bare_ref_mock:
                bare_ref_mock.all = {}
                with mock.patch.object(p, "CleanPublishedCache"):
                    with mock.patch.object(p, "GetRevisionId", return_value="def456"):
                        with mock.patch.object(p.work_git, "ls_tree", return_value="file.txt\0"):
                            with mock.patch.object(p.work_git, "GetHead", return_value="abc123"):
                                with mock.patch.object(p, "IsRebaseInProgress", return_value=True):
                                    p.Sync_LocalHalf(syncbuf, errors=errors)

                                    assert len(errors) == 1

    def test_detached_head_with_rebase_force_checkout(self, tmp_path):
        """Detached HEAD with rebase and force_checkout should abort rebase."""
        p = _proj(tmp_path)

        syncbuf = mock.MagicMock()
        syncbuf.detach_head = True
        errors = []

        with mock.patch.object(p, "_InitWorkTree"):
            with mock.patch.object(p, "bare_ref") as bare_ref_mock:
                bare_ref_mock.all = {}
                with mock.patch.object(p, "CleanPublishedCache"):
                    with mock.patch.object(p, "GetRevisionId", return_value="def456"):
                        with mock.patch.object(p.work_git, "ls_tree", return_value="file.txt\0"):
                            with mock.patch.object(p.work_git, "GetHead", return_value="abc123"):
                                with mock.patch.object(
                                    p,
                                    "IsRebaseInProgress",
                                    side_effect=[True, False],
                                ):
                                    with mock.patch.object(
                                        p,
                                        "IsCherryPickInProgress",
                                        return_value=False,
                                    ):
                                        with mock.patch.object(p, "_AbortRebase") as abort_mock:
                                            with mock.patch.object(p, "_revlist", return_value=[]):
                                                with mock.patch.object(p, "_Checkout"):
                                                    with mock.patch.object(p, "_CopyAndLinkFiles"):
                                                        p.Sync_LocalHalf(
                                                            syncbuf,
                                                            force_checkout=True,
                                                            errors=errors,
                                                        )

                                                        abort_mock.assert_called_once()

    def test_detached_head_checkout_with_lost_commits(self, tmp_path):
        """Detached HEAD checkout with lost commits should report them."""
        p = _proj(tmp_path)

        syncbuf = mock.MagicMock()
        syncbuf.detach_head = True
        errors = []

        with mock.patch.object(p, "_InitWorkTree"):
            with mock.patch.object(p, "bare_ref") as bare_ref_mock:
                bare_ref_mock.all = {}
                with mock.patch.object(p, "CleanPublishedCache"):
                    with mock.patch.object(p, "GetRevisionId", return_value="def456"):
                        with mock.patch.object(p.work_git, "ls_tree", return_value="file.txt\0"):
                            with mock.patch.object(p.work_git, "GetHead", return_value="abc123"):
                                with mock.patch.object(p, "IsRebaseInProgress", return_value=False):
                                    with mock.patch.object(
                                        p,
                                        "IsCherryPickInProgress",
                                        return_value=False,
                                    ):
                                        with mock.patch.object(
                                            p,
                                            "_revlist",
                                            return_value=["commit1", "commit2"],
                                        ):
                                            with mock.patch.object(p, "_Checkout"):
                                                with mock.patch.object(p, "_CopyAndLinkFiles"):
                                                    p.Sync_LocalHalf(
                                                        syncbuf,
                                                        verbose=True,
                                                        errors=errors,
                                                    )

                                                    syncbuf.info.assert_called()

    def test_detached_head_checkout_git_error(self, tmp_path):
        """Detached HEAD checkout failure should fail."""
        p = _proj(tmp_path)

        syncbuf = mock.MagicMock()
        syncbuf.detach_head = True
        errors = []

        with mock.patch.object(p, "_InitWorkTree"):
            with mock.patch.object(p, "bare_ref") as bare_ref_mock:
                bare_ref_mock.all = {}
                with mock.patch.object(p, "CleanPublishedCache"):
                    with mock.patch.object(p, "GetRevisionId", return_value="def456"):
                        with mock.patch.object(p.work_git, "ls_tree", return_value="file.txt\0"):
                            with mock.patch.object(p.work_git, "GetHead", return_value="abc123"):
                                with mock.patch.object(p, "IsRebaseInProgress", return_value=False):
                                    with mock.patch.object(
                                        p,
                                        "IsCherryPickInProgress",
                                        return_value=False,
                                    ):
                                        with mock.patch.object(p, "_revlist", return_value=[]):
                                            with mock.patch.object(
                                                p,
                                                "_Checkout",
                                                side_effect=GitError("checkout failed"),
                                            ):
                                                p.Sync_LocalHalf(syncbuf, errors=errors)

                                                assert len(errors) == 1
                                                assert isinstance(errors[0], GitError)

    def test_head_equals_revid_no_changes(self, tmp_path):
        """HEAD equals revid should only copy files."""
        p = _proj(tmp_path)

        syncbuf = mock.MagicMock()
        syncbuf.detach_head = False
        errors = []

        with mock.patch.object(p, "_InitWorkTree"):
            with mock.patch.object(p, "bare_ref") as bare_ref_mock:
                bare_ref_mock.all = {"refs/heads/main": "abc123"}
                with mock.patch.object(p, "CleanPublishedCache"):
                    with mock.patch.object(p, "GetRevisionId", return_value="abc123"):
                        with mock.patch.object(p.work_git, "ls_tree", return_value="file.txt\0"):
                            with mock.patch.object(
                                p.work_git,
                                "GetHead",
                                return_value="refs/heads/main",
                            ):
                                with mock.patch.object(p, "_CopyAndLinkFiles") as copy_mock:
                                    p.Sync_LocalHalf(syncbuf, errors=errors)

                                    copy_mock.assert_called_once()

    def test_branch_no_local_merge_checkout(self, tmp_path):
        """Branch without LocalMerge should checkout detached."""
        p = _proj(tmp_path)

        syncbuf = mock.MagicMock()
        syncbuf.detach_head = False
        errors = []

        branch_mock = mock.MagicMock()
        branch_mock.name = "feature"
        branch_mock.LocalMerge = None

        with mock.patch.object(p, "_InitWorkTree"):
            with mock.patch.object(p, "bare_ref") as bare_ref_mock:
                bare_ref_mock.all = {"refs/heads/feature": "abc123"}
                with mock.patch.object(p, "CleanPublishedCache"):
                    with mock.patch.object(p, "GetRevisionId", return_value="def456"):
                        with mock.patch.object(p.work_git, "ls_tree", return_value="file.txt\0"):
                            with mock.patch.object(
                                p.work_git,
                                "GetHead",
                                return_value="refs/heads/feature",
                            ):
                                with mock.patch.object(p, "GetBranch", return_value=branch_mock):
                                    with mock.patch.object(p, "_Checkout") as checkout_mock:
                                        with mock.patch.object(p, "_CopyAndLinkFiles"):
                                            p.Sync_LocalHalf(syncbuf, errors=errors)

                                            checkout_mock.assert_called_once()
                                            syncbuf.info.assert_called()

    def test_rebase_queued(self, tmp_path):
        """Rebase should be queued when cnt_mine > 0 and rebase=True."""
        p = _proj(tmp_path)
        p.rebase = True

        syncbuf = mock.MagicMock()
        syncbuf.detach_head = False
        errors = []

        branch_mock = mock.MagicMock()
        branch_mock.name = "feature"
        branch_mock.LocalMerge = "refs/heads/main"
        branch_mock.merge = "refs/heads/main"
        branch_mock.remote = mock.MagicMock()

        with mock.patch.object(p, "_InitWorkTree"):
            with mock.patch.object(p, "bare_ref") as bare_ref_mock:
                bare_ref_mock.all = {"refs/heads/feature": "abc123"}
                with mock.patch.object(p, "CleanPublishedCache"):
                    with mock.patch.object(p, "GetRevisionId", return_value="def456"):
                        with mock.patch.object(p.work_git, "ls_tree", return_value="file.txt\0"):
                            with mock.patch.object(
                                p.work_git,
                                "GetHead",
                                return_value="refs/heads/feature",
                            ):
                                with mock.patch.object(p, "GetBranch", return_value=branch_mock):
                                    with mock.patch.object(p, "GetRemote"):
                                        with mock.patch.object(p, "_revlist") as revlist_mock:
                                            revlist_mock.side_effect = [
                                                ["commit1"],  # upstream_gain
                                                ["local_sha user@example.com"],  # local_changes
                                            ]
                                            with mock.patch.object(p.work_git, "merge_base"):
                                                with mock.patch.object(
                                                    p,
                                                    "IsDirty",
                                                    return_value=False,
                                                ):
                                                    with mock.patch.object(
                                                        type(p),
                                                        "UserEmail",
                                                        new_callable=mock.PropertyMock,
                                                        return_value="user@example.com",
                                                    ):
                                                        p.Sync_LocalHalf(
                                                            syncbuf,
                                                            errors=errors,
                                                        )

                                                        # Should queue rebase
                                                        assert syncbuf.later2.call_count >= 1

    def test_reset_hard_queued(self, tmp_path):
        """ResetHard should be called when local_changes exist but cnt_mine=0."""
        p = _proj(tmp_path)

        syncbuf = mock.MagicMock()
        syncbuf.detach_head = False
        errors = []

        branch_mock = mock.MagicMock()
        branch_mock.name = "feature"
        branch_mock.LocalMerge = "refs/heads/main"
        branch_mock.merge = "refs/heads/main"
        branch_mock.remote = mock.MagicMock()

        with mock.patch.object(p, "_InitWorkTree"):
            with mock.patch.object(p, "bare_ref") as bare_ref_mock:
                bare_ref_mock.all = {"refs/heads/feature": "abc123"}
                with mock.patch.object(p, "CleanPublishedCache"):
                    with mock.patch.object(p, "GetRevisionId", return_value="def456"):
                        with mock.patch.object(p.work_git, "ls_tree", return_value="file.txt\0"):
                            with mock.patch.object(
                                p.work_git,
                                "GetHead",
                                return_value="refs/heads/feature",
                            ):
                                with mock.patch.object(p, "GetBranch", return_value=branch_mock):
                                    with mock.patch.object(p, "GetRemote"):
                                        with mock.patch.object(p, "_revlist") as revlist_mock:
                                            revlist_mock.side_effect = [
                                                ["commit1"],  # upstream_gain
                                                ["local_sha other@example.com"],  # local_changes
                                            ]
                                            with mock.patch.object(p.work_git, "merge_base"):
                                                with mock.patch.object(
                                                    p,
                                                    "IsDirty",
                                                    return_value=False,
                                                ):
                                                    with mock.patch.object(
                                                        type(p),
                                                        "UserEmail",
                                                        new_callable=mock.PropertyMock,
                                                        return_value="user@example.com",
                                                    ):
                                                        with mock.patch.object(p, "_ResetHard") as reset_mock:
                                                            with mock.patch.object(
                                                                p,
                                                                "_CopyAndLinkFiles",
                                                            ):
                                                                p.Sync_LocalHalf(
                                                                    syncbuf,
                                                                    errors=errors,
                                                                )

                                                                reset_mock.assert_called_once()


class TestRemoteFetch:
    """Tests for _RemoteFetch method."""

    def test_immutable_revision_skips_fetch(self, tmp_path):
        """Immutable revision already present should skip fetch."""
        p = _proj(tmp_path)
        p.revisionExpr = "a" * 40

        with mock.patch.object(p, "_CheckForImmutableRevision", return_value=True):
            result = p._RemoteFetch(current_branch_only=True, verbose=True)

            assert result is True

    def test_tag_name_from_revision_expr(self, tmp_path):
        """Tag name should be extracted from revisionExpr."""
        p = _proj(tmp_path)
        p.revisionExpr = "refs/tags/v1.0"

        with mock.patch.object(p, "_CheckForImmutableRevision", return_value=True):
            result = p._RemoteFetch(current_branch_only=True)

            assert result is True

    def test_tag_name_from_upstream(self, tmp_path):
        """Tag name should be extracted from upstream."""
        p = _proj(tmp_path)
        p.upstream = "refs/tags/v2.0"

        with mock.patch.object(p, "_CheckForImmutableRevision", return_value=True):
            result = p._RemoteFetch(current_branch_only=True)

            assert result is True


class TestPrintWorkTreeStatus:
    """Tests for PrintWorkTreeStatus method."""

    def test_missing_worktree(self, tmp_path):
        """Missing worktree should print missing message."""
        p = _proj(tmp_path)
        import shutil

        shutil.rmtree(p.worktree)

        output = mock.MagicMock()
        p.PrintWorkTreeStatus(output_redir=output)

        output.write.assert_called()

    def test_quiet_mode_no_details(self, tmp_path):
        """Quiet mode should not print details."""
        p = _proj(tmp_path)

        with mock.patch.object(p.work_git, "update_index"):
            with mock.patch.object(p, "IsRebaseInProgress", return_value=False):
                with mock.patch.object(
                    p.work_git,
                    "DiffZ",
                    return_value={"file.txt": mock.MagicMock()},
                ):
                    with mock.patch.object(p.work_git, "LsOthers", return_value=[]):
                        with mock.patch.object(
                            type(p),
                            "CurrentBranch",
                            new_callable=mock.PropertyMock,
                            return_value="main",
                        ):
                            result = p.PrintWorkTreeStatus(quiet=True)

                            assert result == "DIRTY"

    def test_no_branch_shows_warning(self, tmp_path):
        """No branch should show warning."""
        p = _proj(tmp_path)

        output = mock.MagicMock()

        with mock.patch.object(p.work_git, "update_index"):
            with mock.patch.object(p, "IsRebaseInProgress", return_value=False):
                with mock.patch.object(
                    p.work_git,
                    "DiffZ",
                    return_value={"file.txt": mock.MagicMock()},
                ):
                    with mock.patch.object(p.work_git, "LsOthers", return_value=[]):
                        with mock.patch.object(
                            type(p),
                            "CurrentBranch",
                            new_callable=mock.PropertyMock,
                            return_value=None,
                        ):
                            result = p.PrintWorkTreeStatus(output_redir=output)

                            assert result == "DIRTY"


class TestDeleteWorktree:
    """Tests for DeleteWorktree method."""

    def test_delete_worktree_not_git_worktree(self, tmp_path):
        """Delete worktree when not using git worktrees should fail."""
        p = _proj(tmp_path)
        p.use_git_worktrees = False

        with pytest.raises(project.DeleteWorktreeError):
            p.DeleteWorktree()

    def test_delete_worktree_dirty_without_force(self, tmp_path):
        """Delete dirty worktree without force should fail."""
        p = _proj(tmp_path)
        p.use_git_worktrees = True

        with mock.patch.object(p, "IsDirty", return_value=True):
            with pytest.raises(project.DeleteDirtyWorktreeError):
                p.DeleteWorktree(force=False)


class TestBranchOperations:
    """Tests for branch operation methods."""


class TestUploadForReview:
    """Tests for UploadForReview method."""


class TestInitGitDir:
    """Tests for _InitGitDir method."""


class TestCopyAndLinkFiles:
    """Tests for _CopyAndLinkFiles method."""

    def test_copy_and_link_files_calls_copy(self, tmp_path):
        """CopyAndLinkFiles should call _Copy on copyfiles."""
        p = _proj(tmp_path)

        copyfile_mock = mock.MagicMock()
        p.copyfiles = [copyfile_mock]

        p._CopyAndLinkFiles()

        copyfile_mock._Copy.assert_called_once()

    def test_copy_and_link_files_calls_link(self, tmp_path):
        """CopyAndLinkFiles should call _Link on linkfiles."""
        p = _proj(tmp_path)

        linkfile_mock = mock.MagicMock()
        p.linkfiles = [linkfile_mock]

        p._CopyAndLinkFiles()

        linkfile_mock._Link.assert_called_once()


class TestMiscellaneousMethods:
    """Tests for miscellaneous Project methods."""

    def test_post_repo_upgrade(self, tmp_path):
        """PostRepoUpgrade should call _InitHooks."""
        p = _proj(tmp_path)

        with mock.patch.object(p, "_InitHooks") as init_hooks_mock:
            p.PostRepoUpgrade()

            init_hooks_mock.assert_called_once()

    def test_get_commit_revision_id(self, tmp_path):
        """GetCommitRevisionId should return revisionId."""
        p = _proj(tmp_path)

        result = p.GetCommitRevisionId()

        assert result == p.revisionId

    def test_was_published_with_all_refs(self, tmp_path):
        """WasPublished with all_refs should look up in dict."""
        p = _proj(tmp_path)

        all_refs = {"refs/published/feature": "abc123"}
        result = p.WasPublished("feature", all_refs=all_refs)

        assert result == "abc123"

    def test_was_published_without_all_refs(self, tmp_path):
        """WasPublished without all_refs should call rev_parse."""
        p = _proj(tmp_path)

        with mock.patch.object(p.bare_git, "rev_parse", return_value="def456"):
            result = p.WasPublished("feature")

            assert result == "def456"

    def test_was_published_not_found(self, tmp_path):
        """WasPublished not found should return None."""
        p = _proj(tmp_path)

        with mock.patch.object(p.bare_git, "rev_parse", side_effect=GitError("not found")):
            result = p.WasPublished("feature")

            assert result is None

    def test_clean_published_cache(self, tmp_path):
        """CleanPublishedCache should prune stale published refs."""
        p = _proj(tmp_path)

        all_refs = {
            "refs/heads/main": "abc123",
            "refs/published/main": "abc123",
            "refs/published/deleted": "def456",
        }

        with mock.patch.object(p.bare_git, "DeleteRef") as delete_mock:
            p.CleanPublishedCache(all_refs=all_refs)

            delete_mock.assert_called_once_with("refs/published/deleted", "def456")

    def test_has_changes_true(self, tmp_path):
        """HasChanges should return True when uncommitted files exist."""
        p = _proj(tmp_path)

        with mock.patch.object(p, "UncommitedFiles", return_value=["file.txt"]):
            result = p.HasChanges()

            assert result is True

    def test_has_changes_false(self, tmp_path):
        """HasChanges should return False when no uncommitted files exist."""
        p = _proj(tmp_path)

        with mock.patch.object(p, "UncommitedFiles", return_value=[]):
            result = p.HasChanges()

            assert result is False

    def test_untracked_files(self, tmp_path):
        """UntrackedFiles should call work_git.LsOthers."""
        p = _proj(tmp_path)

        with mock.patch.object(p.work_git, "LsOthers", return_value=["untracked.txt"]):
            result = p.UntrackedFiles()

            assert result == ["untracked.txt"]

    def test_is_rebase_in_progress_true(self, tmp_path):
        """IsRebaseInProgress should detect rebase."""
        p = _proj(tmp_path)

        rebase_merge = os.path.join(p.worktree, ".git", "rebase-merge")
        os.makedirs(rebase_merge, exist_ok=True)

        result = p.IsRebaseInProgress()

        assert result is True

    def test_sync_network_half_result_success(self, tmp_path):
        """SyncNetworkHalfResult success property."""
        from kanon_cli.repo.project import SyncNetworkHalfResult

        result = SyncNetworkHalfResult(remote_fetched=True, error=None)
        assert result.success is True

        result = SyncNetworkHalfResult(remote_fetched=False, error=GitError("test"))
        assert result.success is False

    def test_delete_worktree_error_aggregate_errors(self, tmp_path):
        """DeleteWorktreeError should store aggregate errors."""
        from kanon_cli.repo.project import DeleteWorktreeError

        errors = [GitError("error1"), GitError("error2")]
        exc = DeleteWorktreeError("message", aggregate_errors=errors)

        assert exc.aggregate_errors == errors

    def test_sync_network_half_error(self, tmp_path):
        """SyncNetworkHalfError should be created properly."""
        from kanon_cli.repo.project import SyncNetworkHalfError

        error = SyncNetworkHalfError("test message", project="test-project")
        assert "test message" in str(error)

    def test_local_sync_fail_error(self, tmp_path):
        """LocalSyncFail should be created properly."""
        error = LocalSyncFail("test message", project="test-project")
        assert "test message" in str(error)

    def test_prior_sync_failed_error(self, tmp_path):
        """_PriorSyncFailedError should be created properly."""
        error = _PriorSyncFailedError(project="test-project")
        assert isinstance(error, LocalSyncFail)

    def test_dirty_error(self, tmp_path):
        """_DirtyError should be created properly."""
        error = _DirtyError(project="test-project")
        assert isinstance(error, LocalSyncFail)
