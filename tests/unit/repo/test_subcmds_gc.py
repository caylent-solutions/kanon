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

"""Unittests for the subcmds/gc.py module."""

import os
import unittest
from unittest import mock

import pytest

from kanon_cli.repo.subcmds import gc


def _make_gc_instance():
    """Create a Gc instance with mocked-out base class dependencies."""
    with mock.patch.object(gc.Gc, "__init__", lambda self: None):
        obj = gc.Gc()
    return obj


@pytest.mark.unit
class TestFindGitToDelete:
    """Tests for Gc._find_git_to_delete."""

    def test_find_git_to_delete_returns_paths_not_in_keep_set(self, tmp_path):
        """Directories ending in .git not in the keep set are returned."""
        gc_obj = _make_gc_instance()

        kept_dir = os.path.join(str(tmp_path), "kept_project.git")
        unused_dir = os.path.join(str(tmp_path), "unused_project.git")
        not_git_dir = os.path.join(str(tmp_path), "some_other_dir")

        os.makedirs(kept_dir)
        os.makedirs(unused_dir)
        os.makedirs(not_git_dir)

        to_keep = {kept_dir}

        with mock.patch("kanon_cli.repo.platform_utils.walk", side_effect=os.walk):
            result = gc_obj._find_git_to_delete(to_keep, str(tmp_path))

        assert unused_dir in result
        assert kept_dir not in result
        assert not_git_dir not in result
        assert len(result) == 1

    def test_find_git_to_delete_empty_dir(self, tmp_path):
        """An empty start directory returns an empty set."""
        gc_obj = _make_gc_instance()

        with mock.patch("kanon_cli.repo.platform_utils.walk", side_effect=os.walk):
            result = gc_obj._find_git_to_delete(set(), str(tmp_path))

        assert result == set()

    def test_find_git_to_delete_all_kept(self, tmp_path):
        """When every .git dir is in the keep set, returns empty set."""
        gc_obj = _make_gc_instance()

        dir_a = os.path.join(str(tmp_path), "a.git")
        dir_b = os.path.join(str(tmp_path), "b.git")
        os.makedirs(dir_a)
        os.makedirs(dir_b)

        to_keep = {dir_a, dir_b}

        with mock.patch("kanon_cli.repo.platform_utils.walk", side_effect=os.walk):
            result = gc_obj._find_git_to_delete(to_keep, str(tmp_path))

        assert result == set()


@pytest.mark.unit
class DeleteUnusedProjectsTest(unittest.TestCase):
    """Tests for Gc.delete_unused_projects."""

    def setUp(self):
        self.gc = _make_gc_instance()
        self.gc.repodir = "/fake/.repo"

    def test_delete_unused_projects_nothing_to_clean(self):
        """Prints 'Nothing to clean up.' when no unused dirs are found."""
        fake_project = mock.MagicMock()
        fake_project.gitdir = "/fake/.repo/projects/foo.git"
        fake_project.objdir = "/fake/.repo/project-objects/foo.git"

        opt = mock.MagicMock()
        opt.dryrun = False
        opt.yes = True
        opt.quiet = False

        with (
            mock.patch.object(self.gc, "_find_git_to_delete", return_value=set()),
            mock.patch("builtins.print") as mock_print,
        ):
            result = self.gc.delete_unused_projects([fake_project], opt)

        self.assertEqual(result, 0)
        mock_print.assert_any_call("Nothing to clean up.")

    def test_delete_unused_projects_dry_run(self):
        """With dryrun=True, prints what would be deleted but does not delete."""
        fake_project = mock.MagicMock()
        fake_project.gitdir = "/fake/.repo/projects/foo.git"
        fake_project.objdir = "/fake/.repo/project-objects/foo.git"

        opt = mock.MagicMock()
        opt.dryrun = True
        opt.yes = True
        opt.quiet = False

        unused_path = "/fake/.repo/projects/old.git"

        with (
            mock.patch.object(
                self.gc,
                "_find_git_to_delete",
                side_effect=[{unused_path}, set()],
            ),
            mock.patch("builtins.print") as mock_print,
            mock.patch("kanon_cli.repo.platform_utils.rename") as mock_rename,
            mock.patch("kanon_cli.repo.platform_utils.rmtree") as mock_rmtree,
            mock.patch("kanon_cli.repo.subcmds.gc.Progress"),
        ):
            result = self.gc.delete_unused_projects([fake_project], opt)

        self.assertEqual(result, 0)
        mock_rename.assert_not_called()
        mock_rmtree.assert_not_called()
        # Verify it printed the dry-run message for the unused path.
        dry_run_calls = [c for c in mock_print.call_args_list if "Would have deleted" in str(c)]
        self.assertTrue(
            len(dry_run_calls) > 0,
            "Expected a 'Would have deleted' message in dry-run mode",
        )


@pytest.mark.unit
class TestGeneratePromisorFiles:
    """Tests for Gc._generate_promisor_files."""

    def test_generate_promisor_files(self, tmp_path):
        """Creates .promisor files alongside existing .pack files."""
        gc_obj = _make_gc_instance()

        pack_dir = str(tmp_path / "pack")
        os.makedirs(pack_dir)

        pack_file_1 = os.path.join(pack_dir, "pack-abc123.pack")
        pack_file_2 = os.path.join(pack_dir, "pack-def456.pack")
        idx_file = os.path.join(pack_dir, "pack-abc123.idx")

        # Create the pack and idx files.
        for f in (pack_file_1, pack_file_2, idx_file):
            with open(f, "w"):
                pass

        with mock.patch("kanon_cli.repo.platform_utils.walk", side_effect=os.walk):
            gc_obj._generate_promisor_files(pack_dir)

        # Verify .promisor files exist for each .pack file.
        expected_promisor_1 = os.path.join(pack_dir, "pack-abc123.promisor")
        expected_promisor_2 = os.path.join(pack_dir, "pack-def456.promisor")

        assert os.path.isfile(expected_promisor_1), f"Expected promisor file at {expected_promisor_1}"
        assert os.path.isfile(expected_promisor_2), f"Expected promisor file at {expected_promisor_2}"

        # Verify no promisor file was created for the .idx file.
        unexpected_promisor = os.path.join(pack_dir, "pack-abc123.idxomisor")
        assert not os.path.exists(unexpected_promisor)

        # Verify promisor files are empty.
        assert os.path.getsize(expected_promisor_1) == 0
        assert os.path.getsize(expected_promisor_2) == 0


@pytest.mark.unit
class ExecuteTest(unittest.TestCase):
    """Tests for Gc.Execute."""

    def setUp(self):
        self.gc = _make_gc_instance()

    def test_execute_uses_single_projects_list(self):
        """Execute passes the same projects list to delete_unused_projects.

        This verifies the fork simplification: Execute uses a single
        projects list directly (no separate fork/split of projects).
        """
        opt = mock.MagicMock()
        opt.this_manifest_only = False
        opt.repack = False

        sentinel_projects = [mock.MagicMock(), mock.MagicMock()]

        with (
            mock.patch.object(self.gc, "GetProjects", return_value=sentinel_projects) as mock_get_projects,
            mock.patch.object(self.gc, "delete_unused_projects", return_value=0) as mock_delete,
        ):
            self.gc.Execute(opt, [])

        mock_get_projects.assert_called_once_with([], all_manifests=True)
        # The exact same list object must be passed through.
        mock_delete.assert_called_once_with(sentinel_projects, opt)

    def test_execute_returns_early_on_delete_failure(self):
        """If delete_unused_projects returns non-zero, Execute returns it."""
        opt = mock.MagicMock()
        opt.this_manifest_only = False
        opt.repack = True

        with (
            mock.patch.object(self.gc, "GetProjects", return_value=[]),
            mock.patch.object(self.gc, "delete_unused_projects", return_value=1),
            mock.patch.object(self.gc, "repack_projects") as mock_repack,
        ):
            result = self.gc.Execute(opt, [])

        self.assertEqual(result, 1)
        mock_repack.assert_not_called()

    def test_execute_calls_repack_when_option_set(self):
        """When opt.repack is True and delete succeeds, repack is called."""
        opt = mock.MagicMock()
        opt.this_manifest_only = False
        opt.repack = True

        sentinel_projects = [mock.MagicMock()]

        with (
            mock.patch.object(self.gc, "GetProjects", return_value=sentinel_projects),
            mock.patch.object(self.gc, "delete_unused_projects", return_value=0),
            mock.patch.object(self.gc, "repack_projects", return_value=0) as mock_repack,
        ):
            result = self.gc.Execute(opt, [])

        mock_repack.assert_called_once_with(sentinel_projects, opt)
        self.assertEqual(result, 0)

    def test_execute_skips_repack_when_option_not_set(self):
        """When opt.repack is False, repack_projects is not called."""
        opt = mock.MagicMock()
        opt.this_manifest_only = False
        opt.repack = False

        with (
            mock.patch.object(self.gc, "GetProjects", return_value=[]),
            mock.patch.object(self.gc, "delete_unused_projects", return_value=0),
            mock.patch.object(self.gc, "repack_projects") as mock_repack,
        ):
            self.gc.Execute(opt, [])

        mock_repack.assert_not_called()


@pytest.mark.unit
class TestGcOptions:
    """Test Gc command options."""

    def test_options_setup(self):
        """Verify Gc command option parser is set up correctly."""
        import optparse

        cmd = gc.Gc()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        # Verify default option values
        assert opts.dryrun is False
        assert opts.yes is False
        assert opts.repack is False

    def test_options_dryrun(self):
        """Test parsing --dry-run option."""
        cmd = gc.Gc()
        opts, args = cmd.OptionParser.parse_args(["--dry-run"])
        assert opts.dryrun is True

    def test_options_yes(self):
        """Test parsing -y option."""
        cmd = gc.Gc()
        opts, args = cmd.OptionParser.parse_args(["-y"])
        assert opts.yes is True

    def test_options_repack(self):
        """Test parsing --repack option."""
        cmd = gc.Gc()
        opts, args = cmd.OptionParser.parse_args(["--repack"])
        assert opts.repack is True


@pytest.mark.unit
class TestGcRepackProjects:
    """Test Gc repack_projects method."""

    def test_repack_projects_empty_list(self):
        """Test repack_projects with empty project list."""
        gc_obj = _make_gc_instance()

        opt = mock.MagicMock()
        opt.quiet = False

        result = gc_obj.repack_projects([], opt)
        assert result == 0


@pytest.mark.unit
class TestGcCommand:
    """Test Gc command properties."""

    def test_common_flag(self):
        """Test Gc command is marked as COMMON."""
        assert gc.Gc.COMMON is True

    def test_help_summary(self):
        """Test Gc command has help summary."""
        assert gc.Gc.helpSummary is not None
        assert len(gc.Gc.helpSummary) > 0

    def test_parallel_jobs(self):
        """Test Gc command has parallel jobs set."""
        # Gc doesn't set PARALLEL_JOBS, it's None
        assert gc.Gc.PARALLEL_JOBS is None
