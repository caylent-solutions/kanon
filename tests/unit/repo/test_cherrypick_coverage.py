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

"""Unit tests for subcmds/cherry_pick.py coverage."""

from unittest import mock

import pytest

from error import GitError
from subcmds.cherry_pick import CherryPick, CHANGE_ID_RE


def _make_cmd():
    """Create a CherryPick command instance for testing."""
    cmd = CherryPick.__new__(CherryPick)
    cmd.manifest = mock.MagicMock()
    return cmd


class TestChangeIdRe:
    """Test CHANGE_ID_RE pattern."""

    @pytest.mark.unit
    def test_change_id_re_valid(self):
        """Test CHANGE_ID_RE matches valid Change-Id."""
        match = CHANGE_ID_RE.match("    Change-Id: I" + "a" * 40)
        assert match is not None
        assert match.group(1) == "a" * 40

    @pytest.mark.unit
    def test_change_id_re_with_trailing_space(self):
        """Test CHANGE_ID_RE matches with trailing space."""
        match = CHANGE_ID_RE.match("Change-Id: I" + "b" * 40 + "  ")
        assert match is not None

    @pytest.mark.unit
    def test_change_id_re_invalid_length(self):
        """Test CHANGE_ID_RE doesn't match invalid length."""
        assert CHANGE_ID_RE.match("Change-Id: I" + "a" * 39) is None
        assert CHANGE_ID_RE.match("Change-Id: I" + "a" * 41) is None

    @pytest.mark.unit
    def test_change_id_re_no_prefix(self):
        """Test CHANGE_ID_RE doesn't match without Change-Id prefix."""
        assert CHANGE_ID_RE.match("I" + "a" * 40) is None


class TestCherryPickCommand:
    """Test CherryPick command."""

    @pytest.mark.unit
    def test_validate_options_no_args(self):
        """Test ValidateOptions with no arguments."""
        cmd = _make_cmd()
        cmd.Usage = mock.MagicMock(side_effect=SystemExit(1))
        opt = mock.MagicMock()

        with pytest.raises(SystemExit):
            cmd.ValidateOptions(opt, [])

    @pytest.mark.unit
    def test_validate_options_multiple_args(self):
        """Test ValidateOptions with multiple arguments."""
        cmd = _make_cmd()
        cmd.Usage = mock.MagicMock(side_effect=SystemExit(1))
        opt = mock.MagicMock()

        with pytest.raises(SystemExit):
            cmd.ValidateOptions(opt, ["sha1", "sha2"])

    @pytest.mark.unit
    def test_validate_options_one_arg(self):
        """Test ValidateOptions with one argument."""
        cmd = _make_cmd()
        opt = mock.MagicMock()

        cmd.ValidateOptions(opt, ["abc123"])  # Should not raise

    @pytest.mark.unit
    def test_is_change_id_valid(self):
        """Test _IsChangeId with valid Change-Id."""
        cmd = _make_cmd()
        assert cmd._IsChangeId("Change-Id: I" + "a" * 40) is not None

    @pytest.mark.unit
    def test_is_change_id_invalid(self):
        """Test _IsChangeId with invalid line."""
        cmd = _make_cmd()
        assert cmd._IsChangeId("Some other line") is None

    @pytest.mark.unit
    def test_get_reference(self):
        """Test _GetReference."""
        cmd = _make_cmd()
        result = cmd._GetReference("abc123")
        assert result == "(cherry picked from commit abc123)"

    @pytest.mark.unit
    def test_strip_header_basic(self):
        """Test _StripHeader with basic commit message."""
        cmd = _make_cmd()
        commit_msg = "tree abc\nauthor John\n\nCommit message\nMore text"
        result = cmd._StripHeader(commit_msg)
        assert result == "Commit message\nMore text"

    @pytest.mark.unit
    def test_strip_header_no_blank_line(self):
        """Test _StripHeader handles missing blank line."""
        cmd = _make_cmd()
        commit_msg = "tree abc"
        with pytest.raises(ValueError):
            cmd._StripHeader(commit_msg)

    @pytest.mark.unit
    def test_reformat_removes_change_id(self):
        """Test _Reformat removes old Change-Id."""
        cmd = _make_cmd()
        old_msg = "Commit message\n\nChange-Id: I" + "a" * 40
        result = cmd._Reformat(old_msg, "abc123")
        assert "Change-Id" not in result
        assert "(cherry picked from commit abc123)" in result

    @pytest.mark.unit
    def test_reformat_adds_blank_line(self):
        """Test _Reformat adds blank line before reference."""
        cmd = _make_cmd()
        old_msg = "Commit message"
        result = cmd._Reformat(old_msg, "abc123")
        lines = result.split("\n")
        assert lines[-2] == ""
        assert "(cherry picked from commit abc123)" in lines[-1]

    @pytest.mark.unit
    def test_reformat_empty_message(self):
        """Test _Reformat with empty message."""
        cmd = _make_cmd()
        old_msg = ""
        result = cmd._Reformat(old_msg, "abc123")
        assert "(cherry picked from commit abc123)" in result

    @pytest.mark.unit
    @mock.patch("subcmds.cherry_pick.GitCommand")
    def test_execute_rev_parse_failure(self, mock_git_command):
        """Test Execute with rev-parse failure."""
        cmd = _make_cmd()
        opt = mock.MagicMock()

        mock_cmd = mock.MagicMock()
        mock_cmd.Wait.side_effect = GitError("rev-parse failed")
        mock_cmd.stderr = "error message"
        mock_git_command.return_value = mock_cmd

        with pytest.raises(GitError):
            cmd.Execute(opt, ["invalid-ref"])

    @pytest.mark.unit
    @mock.patch("subcmds.cherry_pick.GitCommand")
    def test_execute_cat_file_failure(self, mock_git_command):
        """Test Execute with cat-file failure."""
        cmd = _make_cmd()
        opt = mock.MagicMock()

        mock_rev_parse = mock.MagicMock()
        mock_rev_parse.Wait.return_value = None
        mock_rev_parse.stdout = "abc123def456"

        mock_cat_file = mock.MagicMock()
        mock_cat_file.Wait.side_effect = GitError("cat-file failed")

        mock_git_command.side_effect = [mock_rev_parse, mock_cat_file]

        with pytest.raises(GitError):
            cmd.Execute(opt, ["abc123"])

    @pytest.mark.unit
    @mock.patch("subcmds.cherry_pick.GitCommand")
    def test_execute_cherry_pick_failure(self, mock_git_command):
        """Test Execute with cherry-pick failure."""
        cmd = _make_cmd()
        opt = mock.MagicMock()

        mock_rev_parse = mock.MagicMock()
        mock_rev_parse.Wait.return_value = None
        mock_rev_parse.stdout = "abc123def456"

        mock_cat_file = mock.MagicMock()
        mock_cat_file.Wait.return_value = None
        mock_cat_file.stdout = "tree abc\nauthor\n\nCommit message"

        mock_cherry_pick = mock.MagicMock()
        mock_cherry_pick.Wait.side_effect = GitError("cherry-pick failed")

        mock_git_command.side_effect = [
            mock_rev_parse,
            mock_cat_file,
            mock_cherry_pick,
        ]

        with pytest.raises(GitError):
            cmd.Execute(opt, ["abc123"])

    @pytest.mark.unit
    @mock.patch("subcmds.cherry_pick.GitCommand")
    def test_execute_commit_amend_failure(self, mock_git_command):
        """Test Execute with commit amend failure."""
        cmd = _make_cmd()
        opt = mock.MagicMock()

        mock_rev_parse = mock.MagicMock()
        mock_rev_parse.Wait.return_value = None
        mock_rev_parse.stdout = "abc123def456"

        mock_cat_file = mock.MagicMock()
        mock_cat_file.Wait.return_value = None
        mock_cat_file.stdout = "tree abc\nauthor\n\nCommit message"

        mock_cherry_pick = mock.MagicMock()
        mock_cherry_pick.Wait.return_value = None
        mock_cherry_pick.stdout = "Cherry-pick successful"
        mock_cherry_pick.stderr = ""

        mock_commit = mock.MagicMock()
        mock_commit.Wait.side_effect = GitError("commit failed")

        mock_git_command.side_effect = [
            mock_rev_parse,
            mock_cat_file,
            mock_cherry_pick,
            mock_commit,
        ]

        with pytest.raises(GitError):
            cmd.Execute(opt, ["abc123"])

    @pytest.mark.unit
    @mock.patch("subcmds.cherry_pick.GitCommand")
    def test_execute_success(self, mock_git_command):
        """Test Execute with successful cherry-pick."""
        cmd = _make_cmd()
        opt = mock.MagicMock()

        mock_rev_parse = mock.MagicMock()
        mock_rev_parse.Wait.return_value = None
        mock_rev_parse.stdout = "abc123def456"

        mock_cat_file = mock.MagicMock()
        mock_cat_file.Wait.return_value = None
        mock_cat_file.stdout = "tree abc\nauthor\n\nCommit message"

        mock_cherry_pick = mock.MagicMock()
        mock_cherry_pick.Wait.return_value = None
        mock_cherry_pick.stdout = "Cherry-pick successful"
        mock_cherry_pick.stderr = ""

        mock_commit = mock.MagicMock()
        mock_commit.Wait.return_value = None

        mock_git_command.side_effect = [
            mock_rev_parse,
            mock_cat_file,
            mock_cherry_pick,
            mock_commit,
        ]

        cmd.Execute(opt, ["abc123"])

    @pytest.mark.unit
    @mock.patch("subcmds.cherry_pick.GitCommand")
    def test_execute_with_stderr_output(self, mock_git_command):
        """Test Execute prints stderr output."""
        cmd = _make_cmd()
        opt = mock.MagicMock()

        mock_rev_parse = mock.MagicMock()
        mock_rev_parse.Wait.return_value = None
        mock_rev_parse.stdout = "abc123def456"

        mock_cat_file = mock.MagicMock()
        mock_cat_file.Wait.return_value = None
        mock_cat_file.stdout = "tree abc\nauthor\n\nCommit message"

        mock_cherry_pick = mock.MagicMock()
        mock_cherry_pick.Wait.return_value = None
        mock_cherry_pick.stdout = "Success"
        mock_cherry_pick.stderr = "Warning message"

        mock_commit = mock.MagicMock()
        mock_commit.Wait.return_value = None

        mock_git_command.side_effect = [
            mock_rev_parse,
            mock_cat_file,
            mock_cherry_pick,
            mock_commit,
        ]

        cmd.Execute(opt, ["abc123"])
