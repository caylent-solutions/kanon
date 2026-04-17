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

"""Deep unit tests for subcmds/diffmanifests.py module."""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds.diffmanifests import _Coloring
from kanon_cli.repo.subcmds.diffmanifests import Diffmanifests


@pytest.mark.unit
class TestColoringInit:
    """Tests for _Coloring initialization."""

    def test_coloring_init(self):
        """Test _Coloring initialization."""
        config = mock.Mock()
        coloring = _Coloring(config)
        assert coloring is not None


@pytest.mark.unit
class TestDiffmanifestsValidateOptions:
    """Tests for Diffmanifests.ValidateOptions method."""

    def test_validate_options_no_args(self):
        """Test ValidateOptions with no arguments."""
        diffmanifests = Diffmanifests()
        mock_parser = mock.Mock()

        opt = mock.Mock()

        with mock.patch.object(type(diffmanifests), "OptionParser", new_callable=mock.PropertyMock) as mock_op:
            mock_op.return_value = mock_parser
            diffmanifests.ValidateOptions(opt, [])
            mock_parser.error.assert_called()

    def test_validate_options_too_many_args(self):
        """Test ValidateOptions with too many arguments."""
        diffmanifests = Diffmanifests()
        mock_parser = mock.Mock()

        opt = mock.Mock()

        with mock.patch.object(type(diffmanifests), "OptionParser", new_callable=mock.PropertyMock) as mock_op:
            mock_op.return_value = mock_parser
            diffmanifests.ValidateOptions(opt, ["manifest1.xml", "manifest2.xml", "manifest3.xml"])
            mock_parser.error.assert_called()

    def test_validate_options_all_manifests(self):
        """Test ValidateOptions rejects all-manifests."""
        diffmanifests = Diffmanifests()
        mock_parser = mock.Mock()
        mock_parser.error.side_effect = SystemExit(1)

        opt = mock.Mock()
        opt.this_manifest_only = False

        with mock.patch.object(type(diffmanifests), "OptionParser", new_callable=mock.PropertyMock) as mock_op:
            mock_op.return_value = mock_parser
            with pytest.raises(SystemExit):
                diffmanifests.ValidateOptions(opt, ["manifest1.xml"])

    def test_validate_options_valid(self):
        """Test ValidateOptions with valid options."""
        diffmanifests = Diffmanifests()
        mock_parser = mock.Mock()

        opt = mock.Mock()
        opt.this_manifest_only = True

        # Should not raise
        with mock.patch.object(type(diffmanifests), "OptionParser", new_callable=mock.PropertyMock) as mock_op:
            mock_op.return_value = mock_parser
            diffmanifests.ValidateOptions(opt, ["manifest1.xml"])


@pytest.mark.unit
class TestDiffmanifestsPrintRawDiff:
    """Tests for Diffmanifests._printRawDiff method."""

    def test_print_raw_diff_added_projects(self):
        """Test _printRawDiff with added projects."""
        diffmanifests = Diffmanifests()
        diffmanifests.out = mock.Mock()
        diffmanifests.out.nl = mock.Mock()
        diffmanifests.printText = mock.Mock()

        project = mock.Mock()
        project.RelPath.return_value = "project/path"
        project.revisionExpr = "main"

        diff = {
            "added": [project],
            "removed": [],
            "changed": [],
            "unreachable": [],
        }

        diffmanifests._printRawDiff(diff, local=False)

        diffmanifests.printText.assert_called()
        call_args = str(diffmanifests.printText.call_args)
        assert "A" in call_args

    def test_print_raw_diff_removed_projects(self):
        """Test _printRawDiff with removed projects."""
        diffmanifests = Diffmanifests()
        diffmanifests.out = mock.Mock()
        diffmanifests.out.nl = mock.Mock()
        diffmanifests.printText = mock.Mock()

        project = mock.Mock()
        project.RelPath.return_value = "project/path"
        project.revisionExpr = "main"

        diff = {
            "added": [],
            "removed": [project],
            "changed": [],
            "unreachable": [],
        }

        diffmanifests._printRawDiff(diff, local=False)

        call_args = str(diffmanifests.printText.call_args)
        assert "R" in call_args

    def test_print_raw_diff_changed_projects(self):
        """Test _printRawDiff with changed projects."""
        diffmanifests = Diffmanifests()
        diffmanifests.out = mock.Mock()
        diffmanifests.out.nl = mock.Mock()
        diffmanifests.printText = mock.Mock()
        diffmanifests._printLogs = mock.Mock()

        project1 = mock.Mock()
        project1.RelPath.return_value = "project/path"
        project1.revisionExpr = "main"

        project2 = mock.Mock()
        project2.RevisionExpr = "develop"

        diff = {
            "added": [],
            "removed": [],
            "changed": [(project1, project2)],
            "unreachable": [],
        }

        diffmanifests._printRawDiff(diff, local=False)

        call_args = str(diffmanifests.printText.call_args)
        assert "C" in call_args
        diffmanifests._printLogs.assert_called_once()

    def test_print_raw_diff_unreachable_projects(self):
        """Test _printRawDiff with unreachable projects."""
        diffmanifests = Diffmanifests()
        diffmanifests.out = mock.Mock()
        diffmanifests.out.nl = mock.Mock()
        diffmanifests.printText = mock.Mock()

        project1 = mock.Mock()
        project1.RelPath.return_value = "project/path"
        project1.revisionExpr = "main"

        project2 = mock.Mock()
        project2.revisionExpr = "develop"

        diff = {
            "added": [],
            "removed": [],
            "changed": [],
            "unreachable": [(project1, project2)],
        }

        diffmanifests._printRawDiff(diff, local=False)

        call_args = str(diffmanifests.printText.call_args)
        assert "U" in call_args


@pytest.mark.unit
class TestDiffmanifestsPrintDiff:
    """Tests for Diffmanifests._printDiff method."""

    def test_print_diff_added_projects(self):
        """Test _printDiff with added projects."""
        diffmanifests = Diffmanifests()
        diffmanifests.out = mock.Mock()
        diffmanifests.out.nl = mock.Mock()
        diffmanifests.printText = mock.Mock()
        diffmanifests.printProject = mock.Mock()
        diffmanifests.printRevision = mock.Mock()

        project = mock.Mock()
        project.RelPath.return_value = "project/path"
        project.revisionExpr = "main"

        diff = {
            "added": [project],
            "removed": [],
            "changed": [],
            "unreachable": [],
            "missing": [],
        }

        diffmanifests._printDiff(diff, color=True, local=False)

        diffmanifests.printText.assert_called()

    def test_print_diff_removed_projects(self):
        """Test _printDiff with removed projects."""
        diffmanifests = Diffmanifests()
        diffmanifests.out = mock.Mock()
        diffmanifests.out.nl = mock.Mock()
        diffmanifests.printText = mock.Mock()
        diffmanifests.printProject = mock.Mock()
        diffmanifests.printRevision = mock.Mock()

        project = mock.Mock()
        project.RelPath.return_value = "project/path"
        project.revisionExpr = "main"

        diff = {
            "added": [],
            "removed": [project],
            "changed": [],
            "unreachable": [],
            "missing": [],
        }

        diffmanifests._printDiff(diff, color=True, local=False)

        diffmanifests.printText.assert_called()

    def test_print_diff_changed_projects(self):
        """Test _printDiff with changed projects."""
        diffmanifests = Diffmanifests()
        diffmanifests.out = mock.Mock()
        diffmanifests.out.nl = mock.Mock()
        diffmanifests.printText = mock.Mock()
        diffmanifests.printProject = mock.Mock()
        diffmanifests.printRevision = mock.Mock()
        diffmanifests._printLogs = mock.Mock()

        project1 = mock.Mock()
        project1.RelPath.return_value = "project/path"
        project1.revisionExpr = "main"

        project2 = mock.Mock()
        project2.revisionExpr = "develop"

        diff = {
            "added": [],
            "removed": [],
            "changed": [(project1, project2)],
            "unreachable": [],
            "missing": [],
        }

        diffmanifests._printDiff(diff, color=True, local=False)

        diffmanifests._printLogs.assert_called()

    def test_print_diff_missing_projects(self):
        """Test _printDiff with missing projects."""
        diffmanifests = Diffmanifests()
        diffmanifests.out = mock.Mock()
        diffmanifests.out.nl = mock.Mock()
        diffmanifests.printText = mock.Mock()
        diffmanifests.printProject = mock.Mock()
        diffmanifests.printRevision = mock.Mock()

        project = mock.Mock()
        project.RelPath.return_value = "project/path"
        project.revisionExpr = "main"

        diff = {
            "added": [],
            "removed": [],
            "changed": [],
            "unreachable": [],
            "missing": [project],
        }

        diffmanifests._printDiff(diff, color=True, local=False)

        diffmanifests.printText.assert_called()


@pytest.mark.unit
class TestDiffmanifestsPrintLogs:
    """Tests for Diffmanifests._printLogs method."""

    def test_print_logs_removed(self):
        """Test _printLogs with removed logs."""
        diffmanifests = Diffmanifests()
        diffmanifests.out = mock.Mock()
        diffmanifests.out.nl = mock.Mock()
        diffmanifests.printText = mock.Mock()
        diffmanifests.printRemoved = mock.Mock()

        project = mock.Mock()
        project.getAddedAndRemovedLogs.return_value = {
            "removed": "commit1 message1\ncommit2 message2",
            "added": "",
        }

        other_project = mock.Mock()

        diffmanifests._printLogs(project, other_project, raw=False, color=True)

        assert diffmanifests.printRemoved.call_count >= 1

    def test_print_logs_added(self):
        """Test _printLogs with added logs."""
        diffmanifests = Diffmanifests()
        diffmanifests.out = mock.Mock()
        diffmanifests.out.nl = mock.Mock()
        diffmanifests.printText = mock.Mock()
        diffmanifests.printAdded = mock.Mock()

        project = mock.Mock()
        project.getAddedAndRemovedLogs.return_value = {
            "removed": "",
            "added": "commit3 message3\ncommit4 message4",
        }

        other_project = mock.Mock()

        diffmanifests._printLogs(project, other_project, raw=False, color=True)

        assert diffmanifests.printAdded.call_count >= 1

    def test_print_logs_raw_format(self):
        """Test _printLogs with raw format."""
        diffmanifests = Diffmanifests()
        diffmanifests.out = mock.Mock()
        diffmanifests.out.nl = mock.Mock()
        diffmanifests.printText = mock.Mock()

        project = mock.Mock()
        project.getAddedAndRemovedLogs.return_value = {
            "removed": "commit1 message1",
            "added": "commit2 message2",
        }

        other_project = mock.Mock()

        diffmanifests._printLogs(project, other_project, raw=True, color=False)

        assert diffmanifests.printText.call_count >= 2


@pytest.mark.unit
class TestDiffmanifestsExecute:
    """Tests for Diffmanifests.Execute method."""

    def test_execute_one_manifest(self):
        """Test Execute with one manifest."""
        diffmanifests = Diffmanifests()
        diffmanifests.client = mock.Mock()
        diffmanifests.client.globalConfig = mock.Mock()
        diffmanifests.repodir = "/repo"
        diffmanifests.manifest = mock.Mock()
        diffmanifests.out = mock.Mock()
        diffmanifests.printText = mock.Mock()
        diffmanifests.printProject = mock.Mock()
        diffmanifests.printAdded = mock.Mock()
        diffmanifests.printRemoved = mock.Mock()
        diffmanifests.printRevision = mock.Mock()
        diffmanifests._printDiff = mock.Mock()

        opt = mock.Mock()
        opt.color = True
        opt.raw = False
        opt.pretty_format = None
        opt.this_manifest_only = True

        manifest1 = mock.Mock()
        manifest1.projectsDiff.return_value = {
            "added": [],
            "removed": [],
            "changed": [],
            "unreachable": [],
            "missing": [],
        }

        with mock.patch("kanon_cli.repo.subcmds.diffmanifests.RepoClient", return_value=manifest1):
            diffmanifests.Execute(opt, ["manifest1.xml"])

            diffmanifests._printDiff.assert_called_once()

    def test_execute_two_manifests(self):
        """Test Execute with two manifests."""
        diffmanifests = Diffmanifests()
        diffmanifests.client = mock.Mock()
        diffmanifests.client.globalConfig = mock.Mock()
        diffmanifests.repodir = "/repo"
        diffmanifests.manifest = mock.Mock()
        diffmanifests.out = mock.Mock()
        diffmanifests.printText = mock.Mock()
        diffmanifests.printProject = mock.Mock()
        diffmanifests.printAdded = mock.Mock()
        diffmanifests.printRemoved = mock.Mock()
        diffmanifests.printRevision = mock.Mock()
        diffmanifests._printDiff = mock.Mock()

        opt = mock.Mock()
        opt.color = True
        opt.raw = False
        opt.pretty_format = None
        opt.this_manifest_only = True

        manifest = mock.Mock()
        manifest.projectsDiff.return_value = {
            "added": [],
            "removed": [],
            "changed": [],
            "unreachable": [],
            "missing": [],
        }

        with mock.patch("kanon_cli.repo.subcmds.diffmanifests.RepoClient", return_value=manifest):
            diffmanifests.Execute(opt, ["manifest1.xml", "manifest2.xml"])

            diffmanifests._printDiff.assert_called_once()

    def test_execute_raw_mode(self):
        """Test Execute with raw mode."""
        diffmanifests = Diffmanifests()
        diffmanifests.client = mock.Mock()
        diffmanifests.client.globalConfig = mock.Mock()
        diffmanifests.repodir = "/repo"
        diffmanifests.manifest = mock.Mock()
        diffmanifests.out = mock.Mock()
        diffmanifests.printText = mock.Mock()
        diffmanifests.printProject = mock.Mock()
        diffmanifests.printAdded = mock.Mock()
        diffmanifests.printRemoved = mock.Mock()
        diffmanifests.printRevision = mock.Mock()
        diffmanifests._printRawDiff = mock.Mock()

        opt = mock.Mock()
        opt.color = True
        opt.raw = True
        opt.pretty_format = None
        opt.this_manifest_only = True

        manifest = mock.Mock()
        manifest.projectsDiff.return_value = {
            "added": [],
            "removed": [],
            "changed": [],
            "unreachable": [],
        }

        with mock.patch("kanon_cli.repo.subcmds.diffmanifests.RepoClient", return_value=manifest):
            diffmanifests.Execute(opt, ["manifest1.xml"])

            diffmanifests._printRawDiff.assert_called_once()

    def test_execute_no_color(self):
        """Test Execute with color disabled."""
        diffmanifests = Diffmanifests()
        diffmanifests.client = mock.Mock()
        diffmanifests.client.globalConfig = mock.Mock()
        diffmanifests.repodir = "/repo"
        diffmanifests.manifest = mock.Mock()
        diffmanifests.out = mock.Mock()
        diffmanifests.printText = mock.Mock()
        diffmanifests._printDiff = mock.Mock()

        opt = mock.Mock()
        opt.color = False
        opt.raw = False
        opt.pretty_format = None
        opt.this_manifest_only = True

        manifest = mock.Mock()
        manifest.projectsDiff.return_value = {
            "added": [],
            "removed": [],
            "changed": [],
            "unreachable": [],
            "missing": [],
        }

        with mock.patch("kanon_cli.repo.subcmds.diffmanifests.RepoClient", return_value=manifest):
            diffmanifests.Execute(opt, ["manifest1.xml"])

            # When color is False, all printers should be set to printText
            assert diffmanifests.printProject == diffmanifests.printText
