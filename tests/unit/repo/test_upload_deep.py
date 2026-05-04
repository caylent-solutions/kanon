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

"""Deep unit tests for subcmds/upload.py module."""

from unittest import mock

import pytest

from kanon_cli.repo.error import GitError
from kanon_cli.repo.error import UploadError
from kanon_cli.repo.subcmds.upload import _die
from kanon_cli.repo.subcmds.upload import _SplitEmails
from kanon_cli.repo.subcmds.upload import _VerifyPendingCommits
from kanon_cli.repo.subcmds.upload import Upload
from kanon_cli.repo.subcmds.upload import UploadExitError


@pytest.mark.unit
class TestDieFunction:
    """Tests for _die helper function."""

    def test_die_with_single_arg(self):
        """Test _die raises UploadExitError with single argument."""
        with pytest.raises(UploadExitError, match="simple error"):
            _die("simple error")

    def test_die_with_formatted_args(self):
        """Test _die raises UploadExitError with formatted arguments."""
        with pytest.raises(UploadExitError, match="error: value=42"):
            _die("error: value=%d", 42)

    def test_die_with_multiple_format_args(self):
        """Test _die with multiple format arguments."""
        with pytest.raises(UploadExitError, match="foo bar 123"):
            _die("%s %s %d", "foo", "bar", 123)


@pytest.mark.unit
class TestSplitEmails:
    """Tests for _SplitEmails helper function."""

    def test_split_single_email(self):
        """Test splitting single email."""
        result = _SplitEmails(["test@example.com"])
        assert result == ["test@example.com"]

    def test_split_comma_separated_emails(self):
        """Test splitting comma-separated emails."""
        result = _SplitEmails(["test1@example.com,test2@example.com"])
        assert result == ["test1@example.com", "test2@example.com"]

    def test_split_multiple_values_with_commas(self):
        """Test splitting multiple values with commas."""
        result = _SplitEmails(["a@b.com,c@d.com", "e@f.com"])
        assert result == ["a@b.com", "c@d.com", "e@f.com"]

    def test_split_with_whitespace(self):
        """Test splitting strips whitespace."""
        result = _SplitEmails([" test1@example.com , test2@example.com "])
        assert result == ["test1@example.com", "test2@example.com"]

    def test_split_empty_list(self):
        """Test splitting empty list."""
        result = _SplitEmails([])
        assert result == []


@pytest.mark.unit
class TestVerifyPendingCommits:
    """Tests for _VerifyPendingCommits function."""

    def test_verify_with_no_many_commits(self):
        """Test verification passes when no branches have many commits."""
        branch = mock.Mock()
        branch.commits = ["c1", "c2"]
        branch.name = "test-branch"
        branch.project.GetBranch.return_value.remote.review = "review.example.com"
        branch.project.config.GetInt.return_value = None

        result = _VerifyPendingCommits([branch])
        assert result is True

    def test_verify_with_many_commits_user_confirms(self):
        """Test verification with many commits and user confirms."""
        branch = mock.Mock()
        branch.commits = ["c1", "c2", "c3", "c4", "c5", "c6"]
        branch.name = "test-branch"
        branch.project.GetBranch.return_value.remote.review = "review.example.com"
        branch.project.config.GetInt.return_value = None

        with mock.patch("builtins.input", return_value="yes"):
            result = _VerifyPendingCommits([branch])
        assert result is True

    def test_verify_with_many_commits_user_declines(self):
        """Test verification with many commits and user declines."""
        branch = mock.Mock()
        branch.commits = ["c1", "c2", "c3", "c4", "c5", "c6"]
        branch.name = "test-branch"
        branch.project.GetBranch.return_value.remote.review = "review.example.com"
        branch.project.config.GetInt.return_value = None

        with mock.patch("builtins.input", return_value="no"):
            result = _VerifyPendingCommits([branch])
        assert result is False

    def test_verify_with_custom_threshold(self):
        """Test verification with custom threshold."""
        branch = mock.Mock()
        branch.commits = ["c1", "c2", "c3"]
        branch.name = "test-branch"
        branch.project.GetBranch.return_value.remote.review = "review.example.com"
        branch.project.config.GetInt.return_value = 2

        with mock.patch("builtins.input", return_value="yes"):
            result = _VerifyPendingCommits([branch])
        assert result is True

    def test_verify_multiple_branches_with_many_commits(self):
        """Test verification with multiple branches."""
        branch1 = mock.Mock()
        branch1.commits = ["c1", "c2"]
        branch1.name = "branch1"
        branch1.project.GetBranch.return_value.remote.review = "review.example.com"
        branch1.project.config.GetInt.return_value = None

        branch2 = mock.Mock()
        branch2.commits = ["c1", "c2", "c3", "c4", "c5", "c6"]
        branch2.name = "branch2"
        branch2.project.GetBranch.return_value.remote.review = "review.example.com"
        branch2.project.config.GetInt.return_value = None

        with mock.patch("builtins.input", return_value="yes"):
            result = _VerifyPendingCommits([branch1, branch2])
        assert result is True


@pytest.mark.unit
class TestUploadSingleBranch:
    """Tests for Upload._SingleBranch method."""

    def test_single_branch_autoupload_false(self):
        """Test _SingleBranch with autoupload=false."""
        upload = Upload()
        opt = mock.Mock()
        opt.dest_branch = None
        opt.this_manifest_only = False
        opt.private = False

        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.GetBranch.return_value.remote.review = "review.example.com"
        branch.project.config.GetBoolean.return_value = False

        with pytest.raises(UploadExitError, match="upload blocked"):
            upload._SingleBranch(opt, branch, ([], []))

    def test_single_branch_autoupload_true(self):
        """Test _SingleBranch with autoupload=true."""
        upload = Upload()
        upload._UploadAndReport = mock.Mock()
        opt = mock.Mock()
        opt.dest_branch = None
        opt.this_manifest_only = False
        opt.private = False
        opt.yes = False

        branch = mock.Mock()
        branch.name = "test-branch"
        branch.commits = ["c1", "c2"]
        branch.project.GetBranch.return_value.remote.review = "review.example.com"
        branch.project.config.GetBoolean.return_value = True
        branch.project.config.GetInt.return_value = None

        upload._SingleBranch(opt, branch, ([], []))
        upload._UploadAndReport.assert_called_once()

    def test_single_branch_prompt_yes(self):
        """Test _SingleBranch with user prompt answering yes."""
        upload = Upload()
        upload._UploadAndReport = mock.Mock()
        opt = mock.Mock()
        opt.dest_branch = None
        opt.this_manifest_only = False
        opt.private = False
        opt.yes = False

        branch = mock.Mock()
        branch.name = "test-branch"
        branch.date = "2024-01-01"
        branch.commits = ["commit1", "commit2"]
        branch.project.GetBranch.return_value.remote.review = "review.example.com"
        branch.project.config.GetBoolean.return_value = None
        branch.project.config.GetInt.return_value = None
        branch.project.RelPath.return_value = "project/path"
        branch.project.dest_branch = None
        branch.project.revisionExpr = "main"

        with mock.patch("sys.stdin.readline", return_value="y\n"):
            upload._SingleBranch(opt, branch, ([], []))
        upload._UploadAndReport.assert_called_once()

    def test_single_branch_prompt_no(self):
        """Test _SingleBranch with user prompt answering no."""
        upload = Upload()
        upload._UploadAndReport = mock.Mock()
        opt = mock.Mock()
        opt.dest_branch = None
        opt.this_manifest_only = False
        opt.private = False
        opt.yes = False

        branch = mock.Mock()
        branch.name = "test-branch"
        branch.date = "2024-01-01"
        branch.commits = ["commit1", "commit2"]
        branch.project.GetBranch.return_value.remote.review = "review.example.com"
        branch.project.config.GetBoolean.return_value = None
        branch.project.RelPath.return_value = "project/path"
        branch.project.dest_branch = None
        branch.project.revisionExpr = "main"

        with mock.patch("sys.stdin.readline", return_value="n\n"):
            with pytest.raises(UploadExitError, match="upload aborted"):
                upload._SingleBranch(opt, branch, ([], []))
        upload._UploadAndReport.assert_not_called()

    def test_single_branch_with_yes_flag(self):
        """Test _SingleBranch with --yes flag."""
        upload = Upload()
        upload._UploadAndReport = mock.Mock()
        opt = mock.Mock()
        opt.dest_branch = None
        opt.this_manifest_only = False
        opt.private = False
        opt.yes = True

        branch = mock.Mock()
        branch.name = "test-branch"
        branch.date = "2024-01-01"
        branch.commits = ["commit1"]
        branch.project.GetBranch.return_value.remote.review = "review.example.com"
        branch.project.config.GetBoolean.return_value = None
        branch.project.RelPath.return_value = "project/path"
        branch.project.dest_branch = None
        branch.project.revisionExpr = "main"

        upload._SingleBranch(opt, branch, ([], []))
        upload._UploadAndReport.assert_called_once()


@pytest.mark.unit
class TestUploadAppendAutoList:
    """Tests for Upload._AppendAutoList method."""

    def test_append_auto_reviewers(self):
        """Test _AppendAutoList appends auto reviewers."""
        upload = Upload()
        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.GetBranch.return_value.remote.review = "review.example.com"
        branch.project.config.GetString.side_effect = [
            "user1@example.com,user2@example.com",
            None,
        ]

        people = [[], []]
        upload._AppendAutoList(branch, people)
        assert people[0] == ["user1@example.com", "user2@example.com"]
        assert people[1] == []

    def test_append_auto_cc(self):
        """Test _AppendAutoList appends auto CC."""
        upload = Upload()
        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.GetBranch.return_value.remote.review = "review.example.com"
        branch.project.config.GetString.side_effect = [
            "reviewer@example.com",
            "cc1@example.com,cc2@example.com",
        ]

        people = [[], []]
        upload._AppendAutoList(branch, people)
        assert people[0] == ["reviewer@example.com"]
        assert people[1] == ["cc1@example.com", "cc2@example.com"]

    def test_append_auto_list_no_reviewers_no_cc(self):
        """Test _AppendAutoList with no auto reviewers means no CC."""
        upload = Upload()
        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.GetBranch.return_value.remote.review = "review.example.com"
        branch.project.config.GetString.side_effect = [None, "cc@example.com"]

        people = [[], []]
        upload._AppendAutoList(branch, people)
        assert people[0] == []
        assert people[1] == []


@pytest.mark.unit
class TestUploadFindGerritChange:
    """Tests for Upload._FindGerritChange method."""

    def test_find_gerrit_change_success(self):
        """Test _FindGerritChange returns change ID."""
        upload = Upload()
        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.WasPublished.return_value = "abc123"
        branch.GetPublishedRefs.return_value = {"abc123": "refs/changes/45/12345/1"}

        result = upload._FindGerritChange(branch)
        assert result == "12345"

    def test_find_gerrit_change_no_published(self):
        """Test _FindGerritChange with no published refs."""
        upload = Upload()
        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.WasPublished.return_value = None

        result = upload._FindGerritChange(branch)
        assert result == ""

    def test_find_gerrit_change_attribute_error(self):
        """Test _FindGerritChange with AttributeError."""
        upload = Upload()
        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.WasPublished.return_value = "abc123"
        branch.GetPublishedRefs.return_value = {}

        result = upload._FindGerritChange(branch)
        assert result == ""

    def test_find_gerrit_change_index_error(self):
        """Test _FindGerritChange with IndexError."""
        upload = Upload()
        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.WasPublished.return_value = "abc123"
        branch.GetPublishedRefs.return_value = {"abc123": "short"}

        result = upload._FindGerritChange(branch)
        assert result == ""


@pytest.mark.unit
class TestUploadBranch:
    """Tests for Upload._UploadBranch method."""

    def test_upload_branch_basic(self):
        """Test _UploadBranch with basic configuration."""
        upload = Upload()
        upload._GetMergeBranch = mock.Mock(return_value=None)
        opt = mock.Mock()
        opt.topic = None
        opt.auto_topic = False
        opt.hashtags = []
        opt.hashtag_branch = False
        opt.labels = []
        opt.notify = True
        opt.dest_branch = None
        opt.push_options = []
        opt.dryrun = False
        opt.private = False
        opt.wip = False
        opt.ready = False
        opt.validate_certs = True
        opt.patchset_description = None

        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.remote.review = "review.example.com"
        branch.project.config.GetBoolean.return_value = None
        branch.project.config.GetString.return_value = None
        branch.project.dest_branch = None
        branch.project.manifest.manifestProject.use_superproject = False
        branch.UploadForReview = mock.Mock()

        people = [[], []]
        upload._UploadBranch(opt, branch, people)
        assert branch.uploaded is True
        branch.UploadForReview.assert_called_once()

    def test_upload_branch_with_topic(self):
        """Test _UploadBranch with topic set."""
        upload = Upload()
        upload._GetMergeBranch = mock.Mock(return_value=None)
        opt = mock.Mock()
        opt.topic = "my-topic"
        opt.auto_topic = False
        opt.hashtags = []
        opt.hashtag_branch = False
        opt.labels = []
        opt.notify = True
        opt.dest_branch = None
        opt.push_options = []
        opt.dryrun = False
        opt.private = False
        opt.wip = False
        opt.ready = False
        opt.validate_certs = True
        opt.patchset_description = None

        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.remote.review = "review.example.com"
        branch.project.config.GetBoolean.return_value = None
        branch.project.config.GetString.return_value = None
        branch.project.dest_branch = None
        branch.project.manifest.manifestProject.use_superproject = False
        branch.UploadForReview = mock.Mock()

        people = [[], []]
        upload._UploadBranch(opt, branch, people)
        branch.UploadForReview.assert_called_once()
        call_kwargs = branch.UploadForReview.call_args[1]
        assert call_kwargs["topic"] == "my-topic"

    def test_upload_branch_with_auto_topic(self):
        """Test _UploadBranch with auto_topic enabled."""
        upload = Upload()
        upload._GetMergeBranch = mock.Mock(return_value=None)
        opt = mock.Mock()
        opt.topic = None
        opt.auto_topic = True
        opt.hashtags = []
        opt.hashtag_branch = False
        opt.labels = []
        opt.notify = True
        opt.dest_branch = None
        opt.push_options = []
        opt.dryrun = False
        opt.private = False
        opt.wip = False
        opt.ready = False
        opt.validate_certs = True
        opt.patchset_description = None

        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.remote.review = "review.example.com"
        branch.project.config.GetBoolean.return_value = None
        branch.project.config.GetString.return_value = None
        branch.project.dest_branch = None
        branch.project.manifest.manifestProject.use_superproject = False
        branch.UploadForReview = mock.Mock()

        people = [[], []]
        upload._UploadBranch(opt, branch, people)
        call_kwargs = branch.UploadForReview.call_args[1]
        assert call_kwargs["topic"] == "test-branch"

    def test_upload_branch_with_hashtags(self):
        """Test _UploadBranch with hashtags."""
        upload = Upload()
        upload._GetMergeBranch = mock.Mock(return_value=None)
        opt = mock.Mock()
        opt.topic = None
        opt.auto_topic = False
        opt.hashtags = ["tag1", "tag2,tag3"]
        opt.hashtag_branch = False
        opt.labels = []
        opt.notify = True
        opt.dest_branch = None
        opt.push_options = []
        opt.dryrun = False
        opt.private = False
        opt.wip = False
        opt.ready = False
        opt.validate_certs = True
        opt.patchset_description = None

        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.remote.review = "review.example.com"
        branch.project.config.GetBoolean.return_value = None
        branch.project.config.GetString.return_value = None
        branch.project.dest_branch = None
        branch.project.manifest.manifestProject.use_superproject = False
        branch.UploadForReview = mock.Mock()

        people = [[], []]
        upload._UploadBranch(opt, branch, people)
        call_kwargs = branch.UploadForReview.call_args[1]
        assert "tag1" in call_kwargs["hashtags"]
        assert "tag2" in call_kwargs["hashtags"]
        assert "tag3" in call_kwargs["hashtags"]

    def test_upload_branch_with_hashtag_branch(self):
        """Test _UploadBranch with hashtag_branch enabled."""
        upload = Upload()
        upload._GetMergeBranch = mock.Mock(return_value=None)
        opt = mock.Mock()
        opt.topic = None
        opt.auto_topic = False
        opt.hashtags = []
        opt.hashtag_branch = True
        opt.labels = []
        opt.notify = True
        opt.dest_branch = None
        opt.push_options = []
        opt.dryrun = False
        opt.private = False
        opt.wip = False
        opt.ready = False
        opt.validate_certs = True
        opt.patchset_description = None

        branch = mock.Mock()
        branch.name = "feature-branch"
        branch.project.remote.review = "review.example.com"
        branch.project.config.GetBoolean.return_value = None
        branch.project.config.GetString.return_value = None
        branch.project.dest_branch = None
        branch.project.manifest.manifestProject.use_superproject = False
        branch.UploadForReview = mock.Mock()

        people = [[], []]
        upload._UploadBranch(opt, branch, people)
        call_kwargs = branch.UploadForReview.call_args[1]
        assert "feature-branch" in call_kwargs["hashtags"]

    def test_upload_branch_with_labels(self):
        """Test _UploadBranch with labels."""
        upload = Upload()
        upload._GetMergeBranch = mock.Mock(return_value=None)
        opt = mock.Mock()
        opt.topic = None
        opt.auto_topic = False
        opt.hashtags = []
        opt.hashtag_branch = False
        opt.labels = ["Code-Review+1", "Verified+1"]
        opt.notify = True
        opt.dest_branch = None
        opt.push_options = []
        opt.dryrun = False
        opt.private = False
        opt.wip = False
        opt.ready = False
        opt.validate_certs = True
        opt.patchset_description = None

        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.remote.review = "review.example.com"
        branch.project.config.GetBoolean.return_value = None
        branch.project.config.GetString.return_value = None
        branch.project.dest_branch = None
        branch.project.manifest.manifestProject.use_superproject = False
        branch.UploadForReview = mock.Mock()

        people = [[], []]
        upload._UploadBranch(opt, branch, people)
        call_kwargs = branch.UploadForReview.call_args[1]
        assert "Code-Review+1" in call_kwargs["labels"]
        assert "Verified+1" in call_kwargs["labels"]

    def test_upload_branch_notify_false(self):
        """Test _UploadBranch with notify=False."""
        upload = Upload()
        upload._GetMergeBranch = mock.Mock(return_value=None)
        opt = mock.Mock()
        opt.topic = None
        opt.auto_topic = False
        opt.hashtags = []
        opt.hashtag_branch = False
        opt.labels = []
        opt.notify = False
        opt.dest_branch = None
        opt.push_options = []
        opt.dryrun = False
        opt.private = False
        opt.wip = False
        opt.ready = False
        opt.validate_certs = True
        opt.patchset_description = None

        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.remote.review = "review.example.com"
        branch.project.config.GetBoolean.return_value = None
        branch.project.config.GetString.return_value = None
        branch.project.dest_branch = None
        branch.project.manifest.manifestProject.use_superproject = False
        branch.UploadForReview = mock.Mock()

        people = [[], []]
        upload._UploadBranch(opt, branch, people)
        call_kwargs = branch.UploadForReview.call_args[1]
        assert call_kwargs["notify"] == "NONE"

    def test_upload_branch_skip_due_to_merge_branch_mismatch(self):
        """Test _UploadBranch skips upload due to merge branch mismatch."""
        upload = Upload()
        upload._GetMergeBranch = mock.Mock(return_value="refs/heads/different-branch")
        opt = mock.Mock()
        opt.topic = None
        opt.auto_topic = False
        opt.hashtags = []
        opt.hashtag_branch = False
        opt.labels = []
        opt.notify = True
        opt.dest_branch = None
        opt.push_options = []
        opt.dryrun = False
        opt.private = False
        opt.wip = False
        opt.ready = False
        opt.validate_certs = True
        opt.patchset_description = None

        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.remote.review = "review.example.com"
        branch.project.config.GetBoolean.return_value = None
        branch.project.config.GetString.return_value = None
        branch.project.dest_branch = "main"
        branch.project.revisionExpr = "master"
        branch.project.manifest.manifestProject.use_superproject = False
        branch.UploadForReview = mock.Mock()

        people = [[], []]
        upload._UploadBranch(opt, branch, people)
        assert branch.uploaded is False
        branch.UploadForReview.assert_not_called()

    def test_upload_branch_with_superproject(self):
        """Test _UploadBranch with superproject enabled."""
        upload = Upload()
        upload._GetMergeBranch = mock.Mock(return_value=None)
        opt = mock.Mock()
        opt.topic = None
        opt.auto_topic = False
        opt.hashtags = []
        opt.hashtag_branch = False
        opt.labels = []
        opt.notify = True
        opt.dest_branch = None
        opt.push_options = []
        opt.dryrun = False
        opt.private = False
        opt.wip = False
        opt.ready = False
        opt.validate_certs = True
        opt.patchset_description = None

        branch = mock.Mock()
        branch.name = "test-branch"
        branch.project.remote.review = "review.example.com"
        branch.project.config.GetBoolean.return_value = None
        branch.project.config.GetString.return_value = None
        branch.project.dest_branch = None
        branch.project.manifest.manifestProject.use_superproject = True
        branch.project.manifest.superproject.repo_id = "test-repo-id"
        branch.UploadForReview = mock.Mock()

        people = [[], []]
        upload._UploadBranch(opt, branch, people)
        call_kwargs = branch.UploadForReview.call_args[1]
        assert "custom-keyed-value=rootRepo:test-repo-id" in call_kwargs["push_options"]


@pytest.mark.unit
class TestUploadAndReport:
    """Tests for Upload._UploadAndReport method."""

    def test_upload_and_report_success(self):
        """Test _UploadAndReport with successful uploads."""
        upload = Upload()
        upload._UploadBranch = mock.Mock()
        upload.git_event_log = mock.Mock()
        opt = mock.Mock()
        opt.this_manifest_only = False

        branch1 = mock.Mock()
        branch1.uploaded = True
        branch1.name = "branch1"
        branch1.project.RelPath.return_value = "project1"

        branch2 = mock.Mock()
        branch2.uploaded = True
        branch2.name = "branch2"
        branch2.project.RelPath.return_value = "project2"

        upload._UploadAndReport(opt, [branch1, branch2], ([], []))
        assert upload._UploadBranch.call_count == 2

    def test_upload_and_report_with_failures(self):
        """Test _UploadAndReport with upload failures."""
        upload = Upload()
        upload.git_event_log = mock.Mock()

        def upload_side_effect(opt, branch, people):
            if branch.name == "failing-branch":
                raise UploadError("Upload failed")

        upload._UploadBranch = mock.Mock(side_effect=upload_side_effect)
        opt = mock.Mock()
        opt.this_manifest_only = False

        branch1 = mock.Mock()
        branch1.uploaded = False
        branch1.name = "failing-branch"
        branch1.error = None
        branch1.project.RelPath.return_value = "project1"

        branch2 = mock.Mock()
        branch2.uploaded = True
        branch2.name = "success-branch"
        branch2.project.RelPath.return_value = "project2"

        with pytest.raises(UploadExitError):
            upload._UploadAndReport(opt, [branch1, branch2], ([], []))

    def test_upload_and_report_git_error(self):
        """Test _UploadAndReport with GitError."""
        upload = Upload()
        upload.git_event_log = mock.Mock()

        def upload_side_effect(opt, branch, people):
            raise GitError("Git command failed")

        upload._UploadBranch = mock.Mock(side_effect=upload_side_effect)
        opt = mock.Mock()
        opt.this_manifest_only = False

        branch = mock.Mock()
        branch.uploaded = False
        branch.name = "branch"
        branch.error = None
        branch.project.RelPath.return_value = "project"

        with pytest.raises(UploadExitError):
            upload._UploadAndReport(opt, [branch], ([], []))


@pytest.mark.unit
class TestUploadGetMergeBranch:
    """Tests for Upload._GetMergeBranch method."""

    def test_get_merge_branch_with_local_branch(self):
        """Test _GetMergeBranch with local branch specified."""
        upload = Upload()
        project = mock.Mock()

        with mock.patch("kanon_cli.repo.subcmds.upload.GitCommand") as mock_git:
            mock_process = mock.Mock()
            mock_process.stdout = "refs/heads/main"
            mock_process.Wait.return_value = 0
            mock_git.return_value = mock_process

            result = upload._GetMergeBranch(project, "feature-branch")
            assert result == "refs/heads/main"

    def test_get_merge_branch_without_local_branch(self):
        """Test _GetMergeBranch without local branch."""
        upload = Upload()
        project = mock.Mock()

        with mock.patch("kanon_cli.repo.subcmds.upload.GitCommand") as mock_git:
            mock_head_process = mock.Mock()
            mock_head_process.stdout = "current-branch"
            mock_head_process.Wait.return_value = 0

            mock_merge_process = mock.Mock()
            mock_merge_process.stdout = "refs/heads/master"
            mock_merge_process.Wait.return_value = 0

            mock_git.side_effect = [mock_head_process, mock_merge_process]

            result = upload._GetMergeBranch(project, None)
            assert result == "refs/heads/master"


@pytest.mark.unit
class TestUploadMultipleBranches:
    """Tests for Upload._MultipleBranches method."""

    def test_multiple_branches_no_selection(self):
        """Test _MultipleBranches with no branches selected."""
        upload = Upload()
        opt = mock.Mock()
        opt.this_manifest_only = False
        opt.yes = False

        project = mock.Mock()
        project.RelPath.return_value = "project1"
        branch = mock.Mock()
        branch.name = "branch1"
        branch.date = "2024-01-01"
        branch.commits = ["c1"]

        with mock.patch("kanon_cli.repo.subcmds.upload.Editor") as mock_editor:
            mock_editor.EditString.return_value = "# No branches uncommented"
            with pytest.raises(UploadExitError, match="nothing uncommented"):
                upload._MultipleBranches(opt, [(project, [branch])], ([], []))

    def test_multiple_branches_invalid_project(self):
        """Test _MultipleBranches with invalid project."""
        upload = Upload()
        opt = mock.Mock()
        opt.this_manifest_only = False
        opt.yes = False

        project = mock.Mock()
        project.RelPath.return_value = "project1"
        branch = mock.Mock()
        branch.name = "branch1"
        branch.date = "2024-01-01"
        branch.commits = ["c1"]

        with mock.patch("kanon_cli.repo.subcmds.upload.Editor") as mock_editor:
            mock_editor.EditString.return_value = "project invalid-project/:"
            with pytest.raises(UploadExitError, match="not available"):
                upload._MultipleBranches(opt, [(project, [branch])], ([], []))


@pytest.mark.unit
class TestUploadValidateOptions:
    """Tests for Upload.ValidateOptions method."""

    def test_validate_options_valid(self):
        """Test ValidateOptions with valid options."""
        upload = Upload()
        opt = mock.Mock()
        opt.reviewers = ["user@example.com"]
        opt.cc = ["cc@example.com"]
        args = []

        # Should not raise any exception
        upload.ValidateOptions(opt, args)


@pytest.mark.unit
class TestUploadGatherOne:
    """Tests for Upload._GatherOne classmethod."""

    def test_gather_one_with_current_branch(self):
        """Test _GatherOne with current_branch option."""
        opt = mock.Mock()
        opt.current_branch = True
        opt.branch = None

        project = mock.Mock()
        project.CurrentBranch = "main"
        up_branch = mock.Mock()
        project.GetUploadableBranch.return_value = up_branch

        with mock.patch.object(Upload, "get_parallel_context") as mock_context:
            mock_context.return_value = {"projects": [project]}
            result = Upload._GatherOne(opt, 0)

        assert result == (0, [up_branch])

    def test_gather_one_without_current_branch(self):
        """Test _GatherOne without current_branch option."""
        opt = mock.Mock()
        opt.current_branch = False
        opt.branch = None

        project = mock.Mock()
        branches = [mock.Mock(), mock.Mock()]
        project.GetUploadableBranches.return_value = branches

        with mock.patch.object(Upload, "get_parallel_context") as mock_context:
            mock_context.return_value = {"projects": [project]}
            result = Upload._GatherOne(opt, 0)

        assert result == (0, branches)

    def test_gather_one_no_uploadable_branch(self):
        """Test _GatherOne with no uploadable branches."""
        opt = mock.Mock()
        opt.current_branch = True

        project = mock.Mock()
        project.CurrentBranch = "main"
        project.GetUploadableBranch.return_value = None

        with mock.patch.object(Upload, "get_parallel_context") as mock_context:
            mock_context.return_value = {"projects": [project]}
            result = Upload._GatherOne(opt, 0)

        assert result == (0, None)


@pytest.mark.unit
class TestUploadExecute:
    """Tests for Upload.Execute method."""

    def test_execute_no_pending_branches(self):
        """Test Execute with no pending branches."""
        upload = Upload()
        upload.GetProjects = mock.Mock(return_value=[])

        # Mock ParallelContext as a context manager
        mock_context = mock.MagicMock()
        mock_context.__enter__ = mock.Mock(return_value=None)
        mock_context.__exit__ = mock.Mock(return_value=None)
        upload.ParallelContext = mock.Mock(return_value=mock_context)

        upload.get_parallel_context = mock.Mock(return_value={})
        upload.ExecuteInParallel = mock.Mock(return_value=[])

        opt = mock.Mock()
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.branch = None

        result = upload.Execute(opt, [])
        assert result == 1
