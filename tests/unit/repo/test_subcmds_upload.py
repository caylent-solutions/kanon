# Copyright (C) 2023 The Android Open Source Project
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

"""Unittests for the subcmds/upload.py module."""

import optparse
import unittest
from unittest import mock

import pytest

from kanon_cli.repo.error import GitError
from kanon_cli.repo.error import UploadError
from kanon_cli.repo.subcmds import upload


class UnexpectedError(Exception):
    """An exception not expected by upload command."""


class UploadCommand(unittest.TestCase):
    """Check registered all_commands."""

    def setUp(self):
        self.cmd = upload.Upload()
        self.branch = mock.MagicMock()
        self.people = mock.MagicMock()
        self.opt, _ = self.cmd.OptionParser.parse_args([])
        mock.patch.object(self.cmd, "_AppendAutoList", return_value=None).start()
        mock.patch.object(self.cmd, "git_event_log").start()

    def tearDown(self):
        mock.patch.stopall()

    def test_UploadAndReport_UploadError(self):
        """Check UploadExitError raised when UploadError encountered."""
        side_effect = UploadError("upload error")
        with mock.patch.object(self.cmd, "_UploadBranch", side_effect=side_effect):
            with self.assertRaises(upload.UploadExitError):
                self.cmd._UploadAndReport(self.opt, [self.branch], self.people)

    def test_UploadAndReport_GitError(self):
        """Check UploadExitError raised when GitError encountered."""
        side_effect = GitError("some git error")
        with mock.patch.object(self.cmd, "_UploadBranch", side_effect=side_effect):
            with self.assertRaises(upload.UploadExitError):
                self.cmd._UploadAndReport(self.opt, [self.branch], self.people)

    def test_UploadAndReport_UnhandledError(self):
        """Check UnexpectedError passed through."""
        side_effect = UnexpectedError("some os error")
        with mock.patch.object(self.cmd, "_UploadBranch", side_effect=side_effect):
            with self.assertRaises(type(side_effect)):
                self.cmd._UploadAndReport(self.opt, [self.branch], self.people)


@pytest.mark.unit
class TestUploadOptions:
    """Test Upload command options."""

    def test_options_setup(self):
        """Verify Upload command option parser is set up correctly."""
        cmd = upload.Upload()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        # Verify default option values
        assert opts.auto_topic is None
        assert opts.topic is None
        assert opts.hashtags == []
        assert opts.hashtag_branch is None
        assert opts.labels == []
        assert opts.reviewers is None
        assert opts.cc is None
        assert opts.branch is None
        assert opts.current_branch is None
        assert opts.notify is True
        assert opts.private is False
        assert opts.wip is False
        assert opts.ready is False
        assert opts.dest_branch is None
        assert opts.dryrun is False
        assert opts.yes is False
        assert opts.ignore_untracked_files is False
        assert opts.validate_certs is True

    def test_options_with_reviewers(self):
        """Test parsing --reviewers option."""
        cmd = upload.Upload()
        opts, args = cmd.OptionParser.parse_args(["--re", "user@example.com"])
        assert opts.reviewers == ["user@example.com"]

    def test_options_with_cc(self):
        """Test parsing --cc option."""
        cmd = upload.Upload()
        opts, args = cmd.OptionParser.parse_args(["--cc", "team@example.com"])
        assert opts.cc == ["team@example.com"]

    def test_options_current_branch(self):
        """Test parsing --current-branch option."""
        cmd = upload.Upload()
        opts, args = cmd.OptionParser.parse_args(["-c"])
        assert opts.current_branch is True

    def test_options_dry_run(self):
        """Test parsing --dry-run option."""
        cmd = upload.Upload()
        opts, args = cmd.OptionParser.parse_args(["-n"])
        assert opts.dryrun is True

    def test_options_yes(self):
        """Test parsing --yes option."""
        cmd = upload.Upload()
        opts, args = cmd.OptionParser.parse_args(["-y"])
        assert opts.yes is True

    def test_options_topic(self):
        """Test parsing --topic option."""
        cmd = upload.Upload()
        opts, args = cmd.OptionParser.parse_args(["--topic", "my-feature"])
        assert opts.topic == "my-feature"

    def test_options_hashtag(self):
        """Test parsing --hashtag option."""
        cmd = upload.Upload()
        opts, args = cmd.OptionParser.parse_args(["--hashtag", "urgent"])
        assert opts.hashtags == ["urgent"]

    def test_options_label(self):
        """Test parsing --label option."""
        cmd = upload.Upload()
        opts, args = cmd.OptionParser.parse_args(["-l", "Code-Review+1"])
        assert opts.labels == ["Code-Review+1"]

    def test_options_wip(self):
        """Test parsing --wip option."""
        cmd = upload.Upload()
        opts, args = cmd.OptionParser.parse_args(["-w"])
        assert opts.wip is True

    def test_options_ready(self):
        """Test parsing --ready option."""
        cmd = upload.Upload()
        opts, args = cmd.OptionParser.parse_args(["-r"])
        assert opts.ready is True

    def test_options_destination(self):
        """Test parsing --destination option."""
        cmd = upload.Upload()
        opts, args = cmd.OptionParser.parse_args(["-D", "main"])
        assert opts.dest_branch == "main"

    def test_options_no_emails(self):
        """Test parsing --no-emails option."""
        cmd = upload.Upload()
        opts, args = cmd.OptionParser.parse_args(["--ne"])
        assert opts.notify is False


@pytest.mark.unit
class TestUploadHelperFunctions:
    """Test helper functions in upload module."""

    def test_split_emails_single(self):
        """Test _SplitEmails with single email."""
        result = upload._SplitEmails(["user@example.com"])
        assert result == ["user@example.com"]

    def test_split_emails_comma_separated(self):
        """Test _SplitEmails with comma-separated emails."""
        result = upload._SplitEmails(["user1@example.com,user2@example.com"])
        assert result == ["user1@example.com", "user2@example.com"]

    def test_split_emails_multiple_values(self):
        """Test _SplitEmails with multiple values."""
        result = upload._SplitEmails(["user1@example.com", "user2@example.com,user3@example.com"])
        assert result == [
            "user1@example.com",
            "user2@example.com",
            "user3@example.com",
        ]

    def test_split_emails_with_spaces(self):
        """Test _SplitEmails strips whitespace."""
        result = upload._SplitEmails(["user1@example.com , user2@example.com"])
        assert result == ["user1@example.com", "user2@example.com"]

    def test_verify_pending_commits_under_threshold(self):
        """Test _VerifyPendingCommits with commits under threshold."""
        branch = mock.MagicMock()
        branch.commits = ["commit1", "commit2"]
        branch.name = "test-branch"
        branch.project.GetBranch.return_value.remote.review = "gerrit"
        branch.project.config.GetInt.return_value = None

        result = upload._VerifyPendingCommits([branch])
        assert result is True

    def test_verify_pending_commits_over_threshold(self):
        """Test _VerifyPendingCommits with commits over threshold."""
        branch = mock.MagicMock()
        branch.commits = ["c1", "c2", "c3", "c4", "c5", "c6", "c7"]
        branch.name = "test-branch"
        branch.project.GetBranch.return_value.remote.review = "gerrit"
        branch.project.config.GetInt.return_value = None

        with mock.patch("builtins.input", return_value="yes"):
            result = upload._VerifyPendingCommits([branch])
            assert result is True

    def test_verify_pending_commits_user_aborts(self):
        """Test _VerifyPendingCommits when user aborts."""
        branch = mock.MagicMock()
        branch.commits = ["c1", "c2", "c3", "c4", "c5", "c6"]
        branch.name = "test-branch"
        branch.project.GetBranch.return_value.remote.review = "gerrit"
        branch.project.config.GetInt.return_value = None

        with mock.patch("builtins.input", return_value="no"):
            result = upload._VerifyPendingCommits([branch])
            assert result is False


@pytest.mark.unit
class TestUploadCommand:
    """Test Upload command execution."""

    def test_append_auto_list(self):
        """Test _AppendAutoList adds reviewers and cc."""
        cmd = upload.Upload()
        branch = mock.MagicMock()
        branch.name = "test-branch"
        branch.project.GetBranch.return_value.remote.review = "gerrit"
        branch.project.config.GetString.side_effect = [
            "reviewer1@example.com,reviewer2@example.com",
            "cc1@example.com",
        ]

        people = [[], []]
        cmd._AppendAutoList(branch, people)

        assert people[0] == ["reviewer1@example.com", "reviewer2@example.com"]
        assert people[1] == ["cc1@example.com"]

    def test_append_auto_list_no_reviewers(self):
        """Test _AppendAutoList with no auto reviewers."""
        cmd = upload.Upload()
        branch = mock.MagicMock()
        branch.name = "test-branch"
        branch.project.GetBranch.return_value.remote.review = "gerrit"
        branch.project.config.GetString.return_value = None

        people = [[], []]
        cmd._AppendAutoList(branch, people)

        assert people[0] == []
        assert people[1] == []

    def test_find_gerrit_change_found(self):
        """Test _FindGerritChange returns change ID."""
        cmd = upload.Upload()
        branch = mock.MagicMock()
        branch.project.WasPublished.return_value = "last_pub_sha"
        branch.GetPublishedRefs.return_value = {"last_pub_sha": "refs/changes/45/12345/1"}

        result = cmd._FindGerritChange(branch)
        assert result == "12345"

    def test_find_gerrit_change_not_found(self):
        """Test _FindGerritChange when no previous publish."""
        cmd = upload.Upload()
        branch = mock.MagicMock()
        branch.project.WasPublished.return_value = None

        result = cmd._FindGerritChange(branch)
        assert result == ""

    def test_get_merge_branch(self):
        """Test _GetMergeBranch retrieves branch merge config."""
        cmd = upload.Upload()
        project = mock.MagicMock()

        with mock.patch("kanon_cli.repo.subcmds.upload.GitCommand") as mock_git:
            mock_git.return_value.stdout = "refs/heads/main"
            mock_git.return_value.Wait.return_value = None

            result = cmd._GetMergeBranch(project, local_branch="feature")
            assert result == "refs/heads/main"

    def test_gather_one_current_branch(self):
        """Test _GatherOne with current branch option."""
        cmd = upload.Upload()
        opt = mock.MagicMock()
        opt.current_branch = True
        opt.branch = None

        project = mock.MagicMock()
        project.CurrentBranch = "test-branch"
        project.GetUploadableBranch.return_value = mock.MagicMock()

        with cmd.ParallelContext():
            cmd.get_parallel_context()["projects"] = [project]
            result = cmd._GatherOne(opt, 0)

        assert result[0] == 0
        assert result[1] is not None

    def test_gather_one_all_branches(self):
        """Test _GatherOne with all branches."""
        cmd = upload.Upload()
        opt = mock.MagicMock()
        opt.current_branch = False
        opt.branch = None

        project = mock.MagicMock()
        project.GetUploadableBranches.return_value = [mock.MagicMock()]

        with cmd.ParallelContext():
            cmd.get_parallel_context()["projects"] = [project]
            result = cmd._GatherOne(opt, 0)

        assert result[0] == 0
        assert len(result[1]) > 0

    def test_die_raises_upload_exit_error(self):
        """Test _die function raises UploadExitError."""
        with pytest.raises(upload.UploadExitError):
            upload._die("test error: %s", "details")

    def test_upload_exit_error_inheritance(self):
        """Test UploadExitError is a SilentRepoExitError."""
        from kanon_cli.repo.error import SilentRepoExitError

        err = upload.UploadExitError("test")
        assert isinstance(err, SilentRepoExitError)
