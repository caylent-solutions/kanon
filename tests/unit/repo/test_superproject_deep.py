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

"""Deep unit tests for git_superproject.py module."""

from unittest import mock

import pytest

from kanon_cli.repo.git_superproject import _UseSuperprojectFromConfiguration
from kanon_cli.repo.git_superproject import CommitIdsResult
from kanon_cli.repo.git_superproject import PrintMessages
from kanon_cli.repo.git_superproject import Superproject
from kanon_cli.repo.git_superproject import UseSuperproject


@pytest.mark.unit
class TestSuperprojectInit:
    """Tests for Superproject.__init__."""

    def test_init_basic(self):
        """Test Superproject initialization with basic parameters."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/repo/.repo/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")

        assert sp.name == "test-super"
        assert sp.remote == remote
        assert sp.revision == "main"
        assert sp._branch == "main"
        assert sp._remote_url == "https://example.com/superproject"

    def test_init_with_custom_superproject_dir(self):
        """Test Superproject initialization with custom superproject_dir."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/repo/.repo/custom"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main", "custom")

        assert sp._superproject_dir == "custom"


@pytest.mark.unit
class TestSuperprojectProperties:
    """Tests for Superproject properties."""

    def test_commit_id_success(self):
        """Test commit_id property returns commit ID."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/repo/.repo/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")

        with mock.patch("kanon_cli.repo.git_superproject.GitCommand") as mock_git:
            mock_process = mock.Mock()
            mock_process.stdout = "abc123def456"
            mock_process.Wait.return_value = 0
            mock_git.return_value = mock_process

            result = sp.commit_id
            assert result == "abc123def456"

    def test_commit_id_failure(self):
        """Test commit_id property returns None on failure."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/repo/.repo/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._LogWarning = mock.Mock()

        with mock.patch("kanon_cli.repo.git_superproject.GitCommand") as mock_git:
            mock_process = mock.Mock()
            mock_process.Wait.return_value = 1
            mock_process.stderr = "error message"
            mock_git.return_value = mock_process

            result = sp.commit_id
            assert result is None

    def test_manifest_path_exists(self):
        """Test manifest_path property when path exists."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/repo/.repo/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")

        with mock.patch("os.path.exists", return_value=True):
            assert sp.manifest_path is not None

    def test_manifest_path_not_exists(self):
        """Test manifest_path property when path does not exist."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/repo/.repo/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")

        with mock.patch("os.path.exists", return_value=False):
            assert sp.manifest_path is None

    def test_repo_id_with_review_url(self):
        """Test repo_id property with review URL."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/repo/.repo/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"
        remote.review = "https://android-review.googlesource.com/"

        sp = Superproject(manifest, "test-super", remote, "main")

        with mock.patch("kanon_cli.repo.git_superproject.GitRefs") as mock_refs:
            mock_refs.return_value.get.return_value = "commit123"
            result = sp.repo_id
            assert "android" in result
            assert "test-super" in result

    def test_repo_id_without_review_url(self):
        """Test repo_id property without review URL."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/repo/.repo/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"
        remote.review = None

        sp = Superproject(manifest, "test-super", remote, "main")

        result = sp.repo_id
        assert result is None

    def test_project_commit_ids_property(self):
        """Test project_commit_ids property."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/repo/.repo/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._project_commit_ids = {"project1": "abc123"}

        assert sp.project_commit_ids == {"project1": "abc123"}


@pytest.mark.unit
class TestSuperprojectInitMethod:
    """Tests for Superproject._Init method."""

    def test_init_success(self):
        """Test _Init successful initialization."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._quiet = True

        with mock.patch("os.path.exists", return_value=False):
            with mock.patch("os.mkdir"):
                with mock.patch("kanon_cli.repo.git_superproject.GitCommand") as mock_git:
                    mock_process = mock.Mock()
                    mock_process.Wait.return_value = 0
                    mock_git.return_value = mock_process

                    result = sp._Init()
                    assert result is True

    def test_init_failure(self):
        """Test _Init returns False on git init failure."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._quiet = True
        sp._LogWarning = mock.Mock()

        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("kanon_cli.repo.git_superproject.GitCommand") as mock_git:
                mock_process = mock.Mock()
                mock_process.Wait.return_value = 1
                mock_process.stderr = "init failed"
                mock_git.return_value = mock_process

                result = sp._Init()
                assert result is False

    def test_init_directory_already_exists(self):
        """Test _Init when directory already exists."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._quiet = True

        with mock.patch("os.path.exists", side_effect=[True, True]):
            with mock.patch("kanon_cli.repo.git_superproject.GitCommand") as mock_git:
                mock_process = mock.Mock()
                mock_process.Wait.return_value = 0
                mock_git.return_value = mock_process

                result = sp._Init()
                assert result is True


@pytest.mark.unit
class TestSuperprojectFetch:
    """Tests for Superproject._Fetch method."""

    def test_fetch_success(self):
        """Test _Fetch successful fetch."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")

        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("kanon_cli.repo.git_superproject.git_require", return_value=True):
                with mock.patch("kanon_cli.repo.git_superproject.GitRefs") as mock_refs:
                    mock_refs.return_value.get.return_value = "oldcommit"
                    with mock.patch("kanon_cli.repo.git_superproject.GitCommand") as mock_git:
                        mock_process = mock.Mock()
                        mock_process.Wait.return_value = 0
                        mock_git.return_value = mock_process

                        result = sp._Fetch()
                        assert result is True

    def test_fetch_missing_directory(self):
        """Test _Fetch with missing work_git directory."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._LogWarning = mock.Mock()

        with mock.patch("os.path.exists", return_value=False):
            result = sp._Fetch()
            assert result is False

    def test_fetch_git_version_too_old(self):
        """Test _Fetch with git version too old."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._LogWarning = mock.Mock()

        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("kanon_cli.repo.git_superproject.git_require", return_value=False):
                result = sp._Fetch()
                assert result is False

    def test_fetch_failure(self):
        """Test _Fetch returns False on git fetch failure."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._LogWarning = mock.Mock()

        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("kanon_cli.repo.git_superproject.git_require", return_value=True):
                with mock.patch("kanon_cli.repo.git_superproject.GitRefs") as mock_refs:
                    mock_refs.return_value.get.return_value = None
                    with mock.patch("kanon_cli.repo.git_superproject.GitCommand") as mock_git:
                        mock_process = mock.Mock()
                        mock_process.Wait.return_value = 1
                        mock_process.stderr = "fetch failed"
                        mock_git.return_value = mock_process

                        result = sp._Fetch()
                        assert result is False


@pytest.mark.unit
class TestSuperprojectLsTree:
    """Tests for Superproject._LsTree method."""

    def test_lstree_success(self):
        """Test _LsTree successful execution."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")

        ls_output = "160000 commit abc123\tproject1\x00"

        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("kanon_cli.repo.git_superproject.GitCommand") as mock_git:
                mock_process = mock.Mock()
                mock_process.Wait.return_value = 0
                mock_process.stdout = ls_output
                mock_git.return_value = mock_process

                result = sp._LsTree()
                assert result == ls_output

    def test_lstree_missing_directory(self):
        """Test _LsTree with missing work_git directory."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._LogWarning = mock.Mock()

        with mock.patch("os.path.exists", return_value=False):
            result = sp._LsTree()
            assert result is None

    def test_lstree_failure(self):
        """Test _LsTree returns None on git failure."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._LogWarning = mock.Mock()

        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("kanon_cli.repo.git_superproject.GitCommand") as mock_git:
                mock_process = mock.Mock()
                mock_process.Wait.return_value = 1
                mock_process.stderr = "ls-tree failed"
                mock_git.return_value = mock_process

                result = sp._LsTree()
                assert result is None


@pytest.mark.unit
class TestSuperprojectSync:
    """Tests for Superproject.Sync method."""

    def test_sync_no_superproject_tag(self):
        """Test Sync when manifest has no superproject tag."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"
        manifest.superproject = None
        manifest.manifestFile = "manifest.xml"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._LogWarning = mock.Mock()

        git_event_log = mock.Mock()
        result = sp.Sync(git_event_log)

        assert result.success is False
        assert result.fatal is False

    def test_sync_no_remote_url(self):
        """Test Sync when remote URL is not defined."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"
        manifest.superproject = True
        manifest.manifestFile = "manifest.xml"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = None

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._LogWarning = mock.Mock()
        sp._remote_url = None

        git_event_log = mock.Mock()
        result = sp.Sync(git_event_log)

        assert result.success is False
        assert result.fatal is True

    def test_sync_init_failure(self):
        """Test Sync when _Init fails."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"
        manifest.superproject = True
        manifest.manifestFile = "manifest.xml"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._Init = mock.Mock(return_value=False)

        git_event_log = mock.Mock()
        result = sp.Sync(git_event_log)

        assert result.success is False
        assert result.fatal is True

    def test_sync_fetch_failure(self):
        """Test Sync when _Fetch fails."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"
        manifest.superproject = True
        manifest.manifestFile = "manifest.xml"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._Init = mock.Mock(return_value=True)
        sp._Fetch = mock.Mock(return_value=False)

        git_event_log = mock.Mock()
        result = sp.Sync(git_event_log)

        assert result.success is False
        assert result.fatal is True

    def test_sync_success(self):
        """Test Sync successful sync."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"
        manifest.superproject = True
        manifest.manifestFile = "manifest.xml"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._Init = mock.Mock(return_value=True)
        sp._Fetch = mock.Mock(return_value=True)
        sp._quiet = True

        git_event_log = mock.Mock()
        result = sp.Sync(git_event_log)

        assert result.success is True
        assert result.fatal is False


@pytest.mark.unit
class TestSuperprojectGetAllProjectsCommitIds:
    """Tests for Superproject._GetAllProjectsCommitIds method."""

    def test_get_all_projects_commit_ids_sync_failure(self):
        """Test _GetAllProjectsCommitIds when Sync fails."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"
        manifest.superproject = None

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._git_event_log = mock.Mock()
        sp._LogWarning = mock.Mock()

        result = sp._GetAllProjectsCommitIds()

        assert result.commit_ids is None
        assert result.fatal is False

    def test_get_all_projects_commit_ids_lstree_failure(self):
        """Test _GetAllProjectsCommitIds when _LsTree fails."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"
        manifest.superproject = True
        manifest.manifestFile = "manifest.xml"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._git_event_log = mock.Mock()
        sp._LogWarning = mock.Mock()
        sp._Init = mock.Mock(return_value=True)
        sp._Fetch = mock.Mock(return_value=True)
        sp._quiet = True
        sp._LsTree = mock.Mock(return_value=None)

        result = sp._GetAllProjectsCommitIds()

        assert result.commit_ids is None
        assert result.fatal is True

    def test_get_all_projects_commit_ids_success(self):
        """Test _GetAllProjectsCommitIds successful parsing."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"
        manifest.superproject = True
        manifest.manifestFile = "manifest.xml"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._git_event_log = mock.Mock()
        sp._Init = mock.Mock(return_value=True)
        sp._Fetch = mock.Mock(return_value=True)
        sp._quiet = True

        ls_output = (
            "160000 commit abc123\tproject1\x00160000 commit def456\tproject2\x00120000 blob xyz789\tbootstrap.bash\x00"
        )
        sp._LsTree = mock.Mock(return_value=ls_output)

        result = sp._GetAllProjectsCommitIds()

        assert result.commit_ids == {"project1": "abc123", "project2": "def456"}
        assert result.fatal is False


@pytest.mark.unit
class TestSuperprojectSkipUpdatingProjectRevisionId:
    """Tests for Superproject._SkipUpdatingProjectRevisionId method."""

    def test_skip_project_with_no_relpath(self):
        """Test _SkipUpdatingProjectRevisionId skips project with no relpath."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")

        project = mock.Mock()
        project.relpath = None

        result = sp._SkipUpdatingProjectRevisionId(project)
        assert result is True

    def test_skip_project_with_revision_id(self):
        """Test _SkipUpdatingProjectRevisionId skips project with revisionId."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")

        project = mock.Mock()
        project.relpath = "project/path"
        project.revisionId = "abc123"

        result = sp._SkipUpdatingProjectRevisionId(project)
        assert result is True

    def test_skip_project_from_local_manifest(self):
        """Test _SkipUpdatingProjectRevisionId skips project from local manifest."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")

        project = mock.Mock()
        project.relpath = "project/path"
        project.revisionId = None
        project.manifest.IsFromLocalManifest.return_value = True

        result = sp._SkipUpdatingProjectRevisionId(project)
        assert result is True

    def test_dont_skip_normal_project(self):
        """Test _SkipUpdatingProjectRevisionId doesn't skip normal project."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")

        project = mock.Mock()
        project.relpath = "project/path"
        project.revisionId = None
        project.manifest.IsFromLocalManifest.return_value = False

        result = sp._SkipUpdatingProjectRevisionId(project)
        assert result is False


@pytest.mark.unit
class TestSuperprojectUpdateProjectsRevisionId:
    """Tests for Superproject.UpdateProjectsRevisionId method."""

    def test_update_projects_no_commit_ids(self):
        """Test UpdateProjectsRevisionId when getting commit IDs fails."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"
        manifest.superproject = None

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._LogWarning = mock.Mock()

        git_event_log = mock.Mock()
        result = sp.UpdateProjectsRevisionId([], git_event_log)

        assert result.manifest_path is None
        assert result.fatal is False

    def test_update_projects_missing_commit_ids(self):
        """Test UpdateProjectsRevisionId with projects missing commit IDs."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"
        manifest.superproject = True
        manifest.manifestFile = "manifest.xml"
        manifest.contactinfo.bugurl = "https://bugs.example.com"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._git_event_log = mock.Mock()
        sp._LogWarning = mock.Mock()
        sp._GetAllProjectsCommitIds = mock.Mock(return_value=CommitIdsResult({"project1": "abc123"}, False))

        project1 = mock.Mock()
        project1.relpath = "project1"
        project1.revisionId = None
        project1.manifest.IsFromLocalManifest.return_value = False

        project2 = mock.Mock()
        project2.relpath = "project2"
        project2.revisionId = None
        project2.manifest.IsFromLocalManifest.return_value = False

        git_event_log = mock.Mock()
        result = sp.UpdateProjectsRevisionId([project1, project2], git_event_log)

        assert result.manifest_path is None
        assert result.fatal is False

    def test_update_projects_success(self):
        """Test UpdateProjectsRevisionId successful update."""
        manifest = mock.Mock()
        manifest.repodir = "/repo"
        manifest.path_prefix = "prefix"
        manifest.SubmanifestInfoDir.return_value = "/tmp/superproject"
        manifest.superproject = True
        manifest.manifestFile = "manifest.xml"
        manifest.GetGroupsStr.return_value = "default"
        manifest.ToXml.return_value.toxml.return_value = "<manifest/>"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/superproject"

        sp = Superproject(manifest, "test-super", remote, "main")
        sp._git_event_log = mock.Mock()
        sp._GetAllProjectsCommitIds = mock.Mock(return_value=CommitIdsResult({"project1": "abc123"}, False))

        project1 = mock.Mock()
        project1.relpath = "project1"
        project1.revisionId = None
        project1.manifest.IsFromLocalManifest.return_value = False
        project1.SetRevisionId = mock.Mock()

        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("builtins.open", mock.mock_open()):
                git_event_log = mock.Mock()
                result = sp.UpdateProjectsRevisionId([project1], git_event_log)

                assert result.manifest_path is not None
                assert result.fatal is False
                project1.SetRevisionId.assert_called_once_with("abc123")


@pytest.mark.unit
class TestUseSuperprojectFromConfiguration:
    """Tests for _UseSuperprojectFromConfiguration function."""

    def test_user_value_not_expired(self):
        """Test with user value that is not expired."""
        with mock.patch("kanon_cli.repo.git_superproject.RepoConfig") as mock_config:
            user_cfg = mock.Mock()
            user_cfg.GetBoolean.return_value = True
            user_cfg.GetInt.return_value = 9999999999
            mock_config.ForUser.return_value = user_cfg

            # Clear cache
            _UseSuperprojectFromConfiguration.cache_clear()

            result = _UseSuperprojectFromConfiguration()
            assert result is True

    def test_system_value_true(self):
        """Test with system value set to true."""
        with mock.patch("kanon_cli.repo.git_superproject.RepoConfig") as mock_config:
            user_cfg = mock.Mock()
            user_cfg.GetBoolean.return_value = None
            user_cfg.SetString = mock.Mock()
            user_cfg.SetBoolean = mock.Mock()

            system_cfg = mock.Mock()
            system_cfg.GetBoolean.return_value = True

            mock_config.ForUser.return_value = user_cfg
            mock_config.ForSystem.return_value = system_cfg

            # Clear cache
            _UseSuperprojectFromConfiguration.cache_clear()

            result = _UseSuperprojectFromConfiguration()
            assert result is True


@pytest.mark.unit
class TestPrintMessages:
    """Tests for PrintMessages function."""

    def test_print_messages_use_superproject_not_none(self):
        """Test PrintMessages when use_superproject is not None."""
        manifest = mock.Mock()
        result = PrintMessages(True, manifest)
        assert result is True

    def test_print_messages_manifest_has_superproject(self):
        """Test PrintMessages when manifest has superproject."""
        manifest = mock.Mock()
        manifest.superproject = True
        result = PrintMessages(None, manifest)
        assert result is True

    def test_print_messages_both_none(self):
        """Test PrintMessages when both are None/False."""
        manifest = mock.Mock()
        manifest.superproject = None
        result = PrintMessages(None, manifest)
        assert result is False


@pytest.mark.unit
class TestUseSuperproject:
    """Tests for UseSuperproject function."""

    def test_use_superproject_no_manifest_superproject(self):
        """Test UseSuperproject when manifest has no superproject."""
        manifest = mock.Mock()
        manifest.superproject = None

        result = UseSuperproject(None, manifest)
        assert result is False

    def test_use_superproject_option_set(self):
        """Test UseSuperproject when use_superproject option is set."""
        manifest = mock.Mock()
        manifest.superproject = True

        result = UseSuperproject(True, manifest)
        assert result is True

    def test_use_superproject_client_value(self):
        """Test UseSuperproject uses client value."""
        manifest = mock.Mock()
        manifest.superproject = True
        manifest.manifestProject.use_superproject = False

        result = UseSuperproject(None, manifest)
        assert result is False

    def test_use_superproject_from_configuration(self):
        """Test UseSuperproject falls back to configuration."""
        manifest = mock.Mock()
        manifest.superproject = True
        manifest.manifestProject.use_superproject = None

        with mock.patch(
            "kanon_cli.repo.git_superproject._UseSuperprojectFromConfiguration",
            return_value=True,
        ):
            result = UseSuperproject(None, manifest)
            assert result is True
