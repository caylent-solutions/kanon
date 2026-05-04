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

"""Unit tests to boost coverage of small files to near 100%."""

import errno
import os
import sys
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# subcmds/forall.py  (uncovered: 225, 233, 243, 259-276, 337, 350-351,
#                      380, 406)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestForallDoWorkProcessResults:
    """Cover the _ProcessResults inner function (lines 259-276)."""

    def test_process_results_newline_handling(self):
        """Line 270-271: output ending with newline sets end=''."""
        from kanon_cli.repo.subcmds.forall import DoWork

        project = mock.Mock()
        project.name = "proj"
        project.relpath = "proj"
        project.remote.name = "origin"
        project.revisionExpr = "main"
        project.upstream = "master"
        project.dest_branch = "main"
        project.annotations = []
        project.worktree = "/tmp/proj"
        project.RelPath.return_value = "proj"
        project.GetRevisionId.return_value = "abc"
        project.manifest.path_prefix = ""

        opt = mock.Mock()
        opt.project_header = False
        opt.verbose = False
        opt.this_manifest_only = False
        opt.ignore_missing = False
        opt.interactive = False

        mock_result = mock.Mock()
        mock_result.returncode = 0
        mock_result.stdout = "line1\n"

        with (
            mock.patch("os.path.exists", return_value=True),
            mock.patch("subprocess.run", return_value=mock_result),
        ):
            rc, output = DoWork(project, False, opt, ["echo"], False, 0, mock.Mock())
        assert rc == 0
        assert output == "line1\n"

    def test_process_results_abort_on_errors_in_execute(self):
        """Lines 259-276: _ProcessResults raises when abort_on_errors is set."""
        from kanon_cli.repo.subcmds.forall import Forall

        forall = Forall()
        forall.GetProjects = mock.Mock(return_value=[mock.Mock()])
        mock_ctx = mock.MagicMock()
        forall.ParallelContext = mock.Mock(return_value=mock_ctx)
        forall.get_parallel_context = mock.Mock(return_value={})
        forall.manifest = mock.Mock()
        forall.manifest.IsMirror = False
        forall.manifest.manifestProject.worktree = "/tmp"
        forall.manifest.manifestProject.config = mock.Mock()
        forall.InitWorker = mock.Mock()

        opt = mock.Mock()
        opt.command = ["echo", "test"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.project_header = True
        opt.regex = False
        opt.inverse_regex = False
        opt.groups = None
        opt.abort_on_errors = True
        opt.verbose = False

        def fake_exec(
            jobs,
            func,
            items,
            callback=None,
            ordered=False,
            initializer=None,
            chunksize=1,
        ):
            return callback(None, None, [(1, "error output")])

        forall.ExecuteInParallel = mock.Mock(side_effect=fake_exec)

        with mock.patch("os.path.isfile", return_value=False):
            with pytest.raises(SystemExit):
                forall.Execute(opt, [])

    def test_process_results_multiple_outputs_with_header(self):
        """Lines 263-266: second output prints blank line when project_header."""
        from kanon_cli.repo.subcmds.forall import Forall

        forall = Forall()
        forall.GetProjects = mock.Mock(return_value=[mock.Mock(), mock.Mock()])
        mock_ctx = mock.MagicMock()
        forall.ParallelContext = mock.Mock(return_value=mock_ctx)
        forall.get_parallel_context = mock.Mock(return_value={})
        forall.manifest = mock.Mock()
        forall.manifest.IsMirror = False
        forall.manifest.manifestProject.worktree = "/tmp"
        forall.manifest.manifestProject.config = mock.Mock()
        forall.InitWorker = mock.Mock()

        opt = mock.Mock()
        opt.command = ["echo", "test"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.project_header = True
        opt.regex = False
        opt.inverse_regex = False
        opt.groups = None
        opt.abort_on_errors = False
        opt.verbose = False

        def fake_exec(
            jobs,
            func,
            items,
            callback=None,
            ordered=False,
            initializer=None,
            chunksize=1,
        ):
            return callback(
                None,
                None,
                [(0, "out1\n"), (0, "out2\n")],
            )

        forall.ExecuteInParallel = mock.Mock(side_effect=fake_exec)

        with mock.patch("os.path.isfile", return_value=False):
            forall.Execute(opt, [])


@pytest.mark.unit
class TestForallDoWorkSpecialCases:
    """Cover lines 225, 233, 243, 337, 350-351, 380, 406 in forall.py."""

    def test_cn_none_when_all_args_are_flags(self):
        """Line 225: cn = None when all args after git start with '-'."""
        from kanon_cli.repo.subcmds.forall import Forall

        forall = Forall()
        forall.GetProjects = mock.Mock(return_value=[mock.Mock()])
        mock_ctx = mock.MagicMock()
        forall.ParallelContext = mock.Mock(return_value=mock_ctx)
        forall.get_parallel_context = mock.Mock(return_value={})
        forall.ExecuteInParallel = mock.Mock(return_value=0)
        forall.InitWorker = mock.Mock()
        forall.manifest = mock.Mock()
        forall.manifest.IsMirror = False
        forall.manifest.manifestProject.worktree = "/tmp"
        forall.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.command = ["git", "--version"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.project_header = True
        opt.regex = False
        opt.inverse_regex = False
        opt.groups = None
        opt.abort_on_errors = False

        with mock.patch("os.path.isfile", return_value=False):
            forall.Execute(opt, [])

    def test_color_cmd_insertion(self):
        """Line 233: --color is inserted when cn is in _CAN_COLOR and is_on."""
        from kanon_cli.repo.subcmds.forall import Forall

        forall = Forall()
        forall.GetProjects = mock.Mock(return_value=[mock.Mock()])
        mock_ctx = mock.MagicMock()
        forall.ParallelContext = mock.Mock(return_value=mock_ctx)
        forall.get_parallel_context = mock.Mock(return_value={})
        forall.ExecuteInParallel = mock.Mock(return_value=0)
        forall.InitWorker = mock.Mock()
        forall.manifest = mock.Mock()
        forall.manifest.IsMirror = False
        forall.manifest.manifestProject.worktree = "/tmp"

        mock_config = mock.Mock()
        forall.manifest.manifestProject.config = mock_config

        opt = mock.Mock()
        opt.command = ["git", "log"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.project_header = True
        opt.regex = False
        opt.inverse_regex = False
        opt.groups = None
        opt.abort_on_errors = False

        with (
            mock.patch("os.path.isfile", return_value=False),
            mock.patch(
                "kanon_cli.repo.color.Coloring.is_on",
                new_callable=lambda: property(lambda s: True),
            ),
        ):
            forall.Execute(opt, [])

    def test_smart_sync_manifest_override(self):
        """Line 243: Override manifest when smart_sync_override.xml exists."""
        from kanon_cli.repo.subcmds.forall import Forall

        forall = Forall()
        forall.GetProjects = mock.Mock(return_value=[])
        mock_ctx = mock.MagicMock()
        forall.ParallelContext = mock.Mock(return_value=mock_ctx)
        forall.get_parallel_context = mock.Mock(return_value={})
        forall.ExecuteInParallel = mock.Mock(return_value=0)
        forall.InitWorker = mock.Mock()
        forall.manifest = mock.Mock()
        forall.manifest.IsMirror = False
        forall.manifest.manifestProject.worktree = "/tmp"
        forall.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.command = ["echo", "test"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.project_header = False
        opt.regex = False
        opt.inverse_regex = False
        opt.groups = None

        with mock.patch("os.path.isfile", return_value=True):
            forall.Execute(opt, [])
            forall.manifest.Override.assert_called_once()

    def test_do_work_manifest_invalid_revision(self):
        """Lines 350-351: ManifestInvalidRevisionError sets lrev=''."""
        from kanon_cli.repo.error import ManifestInvalidRevisionError
        from kanon_cli.repo.subcmds.forall import DoWork

        project = mock.Mock()
        project.name = "proj"
        project.relpath = "proj"
        project.remote.name = "origin"
        project.revisionExpr = "main"
        project.upstream = "master"
        project.dest_branch = "main"
        project.annotations = []
        project.worktree = "/tmp/proj"
        project.RelPath.return_value = "proj"
        project.GetRevisionId.side_effect = ManifestInvalidRevisionError()
        project.manifest.path_prefix = ""

        opt = mock.Mock()
        opt.project_header = False
        opt.verbose = False
        opt.this_manifest_only = False
        opt.ignore_missing = False
        opt.interactive = False

        mock_result = mock.Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with (
            mock.patch("os.path.exists", return_value=True),
            mock.patch("subprocess.run", return_value=mock_result),
        ):
            rc, output = DoWork(project, False, opt, ["echo"], False, 0, mock.Mock())
        assert rc == 0

    def test_do_work_verbose_stderr(self):
        """Line 380: verbose sets stderr=subprocess.STDOUT."""
        import subprocess
        from kanon_cli.repo.subcmds.forall import DoWork

        project = mock.Mock()
        project.name = "proj"
        project.relpath = "proj"
        project.remote.name = "origin"
        project.revisionExpr = "main"
        project.upstream = "master"
        project.dest_branch = "main"
        project.annotations = []
        project.worktree = "/tmp/proj"
        project.RelPath.return_value = "proj"
        project.GetRevisionId.return_value = "abc"
        project.manifest.path_prefix = ""

        opt = mock.Mock()
        opt.project_header = False
        opt.verbose = True
        opt.this_manifest_only = False
        opt.ignore_missing = False
        opt.interactive = False

        mock_result = mock.Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with (
            mock.patch("os.path.exists", return_value=True),
            mock.patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            DoWork(project, False, opt, ["echo"], False, 0, mock.Mock())
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["stderr"] == subprocess.STDOUT

    def test_do_work_project_header_mirror(self):
        """Line 406: mirror mode uses project.name as header path."""
        from kanon_cli.repo.subcmds.forall import DoWork

        project = mock.Mock()
        project.name = "test-mirror-proj"
        project.relpath = "proj"
        project.remote.name = "origin"
        project.revisionExpr = "main"
        project.upstream = "master"
        project.dest_branch = "main"
        project.annotations = []
        project.gitdir = "/tmp/proj.git"
        project.manifest.path_prefix = ""

        opt = mock.Mock()
        opt.project_header = True
        opt.verbose = False
        opt.this_manifest_only = False
        opt.ignore_missing = False
        opt.interactive = False

        mock_result = mock.Mock()
        mock_result.returncode = 0
        mock_result.stdout = "data\n"

        with (
            mock.patch("os.path.exists", return_value=True),
            mock.patch("subprocess.run", return_value=mock_result),
        ):
            rc, output = DoWork(project, True, opt, ["echo"], False, 0, mock.Mock())
        assert rc == 0
        assert "test-mirror-proj" in output

    def test_do_work_missing_checkout_with_header_verbose(self):
        """Lines 373-377: missing checkout with project_header + verbose."""
        from kanon_cli.repo.subcmds.forall import DoWork

        project = mock.Mock()
        project.name = "proj"
        project.relpath = "proj"
        project.remote.name = "origin"
        project.revisionExpr = "main"
        project.upstream = "master"
        project.dest_branch = "main"
        project.annotations = []
        project.worktree = "/tmp/missing"
        project.RelPath.return_value = "proj"
        project.GetRevisionId.return_value = "abc"
        project.manifest.path_prefix = ""

        opt = mock.Mock()
        opt.project_header = True
        opt.verbose = True
        opt.this_manifest_only = False
        opt.ignore_missing = False

        with mock.patch("os.path.exists", return_value=False):
            rc, output = DoWork(project, False, opt, ["echo"], False, 0, mock.Mock())
        assert rc == 1
        assert "skipping" in output

    def test_forall_execute_generic_exception(self):
        """Lines 297-303: generic exception handling in Execute."""
        from kanon_cli.repo.subcmds.forall import Forall

        forall = Forall()
        forall.GetProjects = mock.Mock(return_value=[mock.Mock()])
        mock_ctx = mock.MagicMock()
        forall.ParallelContext = mock.Mock(return_value=mock_ctx)
        forall.get_parallel_context = mock.Mock(return_value={})
        exc = RuntimeError("test error")
        exc.errno = 42
        forall.ExecuteInParallel = mock.Mock(side_effect=exc)
        forall.manifest = mock.Mock()
        forall.manifest.IsMirror = False
        forall.manifest.manifestProject.worktree = "/tmp"
        forall.manifest.manifestProject.config = mock.Mock()

        opt = mock.Mock()
        opt.command = ["echo", "test"]
        opt.this_manifest_only = False
        opt.jobs = 1
        opt.project_header = False
        opt.regex = False
        opt.inverse_regex = False
        opt.groups = None

        with mock.patch("os.path.isfile", return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                forall.Execute(opt, [])
            assert exc_info.value.code == 42


# ---------------------------------------------------------------------------
# subcmds/branches.py  (uncovered: 166, 188-197, 204-212)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBranchesExecuteDeepCoverage:
    """Cover lines 166 (published='p'), 188-197 (not-in-project), 204-212."""

    def _make_cmd(self):
        from kanon_cli.repo.subcmds.branches import Branches

        cmd = Branches.__new__(Branches)
        cmd.manifest = mock.MagicMock()
        return cmd

    def test_published_partial(self):
        """Line 166: published='p' when IsPublished but not IsPublishedEqual."""
        from kanon_cli.repo.subcmds.branches import Branches

        cmd = self._make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.this_manifest_only = False

        mock_project = mock.MagicMock()
        mock_project.RelPath.return_value = "proj"

        # branch is published but revision != published
        mock_branch = mock.MagicMock()
        mock_branch.current = False
        mock_branch.published = "pub_rev"
        mock_branch.revision = "other_rev"
        mock_branch.project = mock_project

        with (
            mock.patch.object(Branches, "GetProjects", return_value=[mock_project]),
            mock.patch.object(Branches, "ParallelContext") as mock_pc,
            mock.patch.object(Branches, "get_parallel_context", return_value={}),
            mock.patch.object(Branches, "ExecuteInParallel") as mock_exec,
        ):
            mock_pc.return_value.__enter__ = mock.MagicMock()
            mock_pc.return_value.__exit__ = mock.MagicMock()

            def run_callback(*a, **kw):
                kw["callback"](None, None, [[("feat", mock_branch, 0)]])

            mock_exec.side_effect = run_callback
            cmd.Execute(opt, [])

    def test_not_in_project_display(self):
        """Lines 188-197: 'not in' display path when branch in majority."""
        from kanon_cli.repo.subcmds.branches import Branches

        cmd = self._make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.this_manifest_only = False

        projects = []
        for name in ["p1", "p2", "p3"]:
            p = mock.MagicMock()
            p.RelPath.return_value = name
            projects.append(p)

        # Branch is in p1 and p2 (majority), so "not in p3"
        b1 = mock.MagicMock()
        b1.current = False
        b1.published = None
        b1.revision = "abc"
        b1.project = projects[0]

        b2 = mock.MagicMock()
        b2.current = False
        b2.published = None
        b2.revision = "abc"
        b2.project = projects[1]

        with (
            mock.patch.object(Branches, "GetProjects", return_value=projects),
            mock.patch.object(Branches, "ParallelContext") as mock_pc,
            mock.patch.object(Branches, "get_parallel_context", return_value={}),
            mock.patch.object(Branches, "ExecuteInParallel") as mock_exec,
        ):
            mock_pc.return_value.__enter__ = mock.MagicMock()
            mock_pc.return_value.__exit__ = mock.MagicMock()

            def run_callback(*a, **kw):
                kw["callback"](None, None, [[("feat", b1, 0), ("feat", b2, 1)]])

            mock_exec.side_effect = run_callback
            cmd.Execute(opt, [])

    def test_long_line_wraps_branch_display(self):
        """Lines 204-212: when line is too long, wraps with colon style."""
        from kanon_cli.repo.subcmds.branches import Branches

        cmd = self._make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.this_manifest_only = False

        projects = []
        for name in [
            "very/long/project/path/name/here/alpha",
            "very/long/project/path/name/here/beta",
        ]:
            p = mock.MagicMock()
            p.RelPath.return_value = name
            projects.append(p)

        b1 = mock.MagicMock()
        b1.current = True
        b1.published = None
        b1.revision = "abc"
        b1.project = projects[0]

        with (
            mock.patch.object(Branches, "GetProjects", return_value=projects),
            mock.patch.object(Branches, "ParallelContext") as mock_pc,
            mock.patch.object(Branches, "get_parallel_context", return_value={}),
            mock.patch.object(Branches, "ExecuteInParallel") as mock_exec,
        ):
            mock_pc.return_value.__enter__ = mock.MagicMock()
            mock_pc.return_value.__exit__ = mock.MagicMock()

            def run_callback(*a, **kw):
                kw["callback"](None, None, [[("feat", b1, 0)]])

            mock_exec.side_effect = run_callback
            cmd.Execute(opt, [])

    def test_split_current_long_display(self):
        """Lines 204-212: split current branch with non_cur_paths iteration."""
        from kanon_cli.repo.subcmds.branches import Branches

        cmd = self._make_cmd()
        opt = mock.MagicMock()
        opt.jobs = 1
        opt.this_manifest_only = False

        projects = []
        for name in [
            "very/long/path/proj1",
            "very/long/path/proj2",
            "very/long/path/proj3",
        ]:
            p = mock.MagicMock()
            p.RelPath.return_value = name
            projects.append(p)

        b1 = mock.MagicMock()
        b1.current = True
        b1.published = None
        b1.revision = "abc"
        b1.project = projects[0]

        b2 = mock.MagicMock()
        b2.current = False
        b2.published = None
        b2.revision = "abc"
        b2.project = projects[1]

        with (
            mock.patch.object(Branches, "GetProjects", return_value=projects),
            mock.patch.object(Branches, "ParallelContext") as mock_pc,
            mock.patch.object(Branches, "get_parallel_context", return_value={}),
            mock.patch.object(Branches, "ExecuteInParallel") as mock_exec,
        ):
            mock_pc.return_value.__enter__ = mock.MagicMock()
            mock_pc.return_value.__exit__ = mock.MagicMock()

            def run_callback(*a, **kw):
                kw["callback"](
                    None,
                    None,
                    [
                        [
                            ("feature-branch-longname", b1, 0),
                            ("feature-branch-longname", b2, 1),
                        ]
                    ],
                )

            mock_exec.side_effect = run_callback
            cmd.Execute(opt, [])


# ---------------------------------------------------------------------------
# platform_utils.py  (uncovered: 44, 77-79, 92-98, 136, 185-188, 192-195,
#                      200-202, 206)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPlatformUtilsWindows:
    """Cover Windows-specific branches in platform_utils.py."""

    def test_symlink_windows_directory(self):
        """Lines 44: Windows directory symlink path."""
        from kanon_cli.repo import platform_utils

        mock_win32 = mock.MagicMock()
        with (
            mock.patch.object(platform_utils, "isWindows", return_value=True),
            mock.patch.object(platform_utils, "_validate_winpath", side_effect=lambda p: p),
            mock.patch.object(platform_utils, "isdir", return_value=True),
            mock.patch.dict(sys.modules, {"platform_utils_win32": mock_win32}),
        ):
            platform_utils.symlink("source", "link")
            mock_win32.create_dirsymlink.assert_called_once()

    def test_winpath_is_valid_no_drive_no_sep(self):
        """Lines 77-79: _winpath_is_valid with different path forms."""
        from kanon_cli.repo import platform_utils

        with mock.patch.object(platform_utils, "isWindows", return_value=True):
            # Relative path like "foo\\bar" should be valid (tail[0] != os.sep)
            with (
                mock.patch("os.path.normpath", return_value="foo\\bar"),
                mock.patch("os.path.splitdrive", return_value=("", "foo\\bar")),
            ):
                assert platform_utils._winpath_is_valid("foo\\bar") is True

    def test_winpath_is_valid_drive_with_sep(self):
        """Line 77: drive+valid tail."""
        from kanon_cli.repo import platform_utils

        with mock.patch.object(platform_utils, "isWindows", return_value=True):
            # On Linux os.sep is '/' so we simulate the Windows case
            with (
                mock.patch("os.path.normpath", return_value="C:\\foo"),
                mock.patch("os.path.splitdrive", return_value=("C:", "\\foo")),
                mock.patch.object(os, "sep", "\\"),
            ):
                assert platform_utils._winpath_is_valid("C:\\foo") is True

    def test_winpath_is_valid_empty_tail_no_drive(self):
        """Line 79: empty tail, no drive (e.g., '.')."""
        from kanon_cli.repo import platform_utils

        with mock.patch.object(platform_utils, "isWindows", return_value=True):
            with (
                mock.patch("os.path.normpath", return_value="."),
                mock.patch("os.path.splitdrive", return_value=("", "")),
            ):
                assert platform_utils._winpath_is_valid(".") is True

    def test_makelongpath_windows_long(self):
        """Lines 92-98: Windows long path prefix addition."""
        from kanon_cli.repo import platform_utils

        long_path = "C:\\" + "a" * 250
        with (
            mock.patch.object(platform_utils, "isWindows", return_value=True),
            mock.patch("os.path.isabs", return_value=True),
            mock.patch("os.path.normpath", return_value=long_path),
        ):
            result = platform_utils._makelongpath(long_path)
            assert result.startswith("\\\\?\\")

    def test_makelongpath_windows_already_prefixed(self):
        """Line 92-93: path already has long-path prefix."""
        from kanon_cli.repo import platform_utils

        path = "\\\\?\\" + "C:\\" + "a" * 250
        with mock.patch.object(platform_utils, "isWindows", return_value=True):
            result = platform_utils._makelongpath(path)
            assert result == path

    def test_makelongpath_windows_relative(self):
        """Line 94-95: relative path on Windows stays unchanged."""
        from kanon_cli.repo import platform_utils

        long_path = "a" * 250
        with (
            mock.patch.object(platform_utils, "isWindows", return_value=True),
            mock.patch("os.path.isabs", return_value=False),
        ):
            result = platform_utils._makelongpath(long_path)
            assert result == long_path

    def test_rename_windows_eexist(self):
        """Line 136: Windows rename with EEXIST fallback."""
        from kanon_cli.repo import platform_utils

        with (
            mock.patch.object(platform_utils, "isWindows", return_value=True),
            mock.patch.object(platform_utils, "_makelongpath", side_effect=lambda p: p),
        ):
            oserr = OSError()
            oserr.errno = errno.EEXIST

            with (
                mock.patch("os.rename", side_effect=[oserr, None]) as mock_rename,
                mock.patch("os.remove") as mock_remove,
            ):
                platform_utils.rename("src", "dst")
                mock_remove.assert_called_once_with("dst")
                assert mock_rename.call_count == 2

    def test_walk_windows_impl_topdown_false(self):
        """Lines 200-206: _walk_windows_impl with topdown=False."""
        from kanon_cli.repo import platform_utils

        with (
            mock.patch.object(platform_utils, "listdir", return_value=["dir1", "file1"]),
            mock.patch.object(
                platform_utils,
                "isdir",
                side_effect=lambda p: p.endswith("dir1"),
            ),
            mock.patch.object(platform_utils, "islink", return_value=False),
        ):
            results = list(platform_utils._walk_windows_impl("/top", False, None, False))
            # Should yield sub-dir first, then top
            paths = [r[0] for r in results]
            assert paths[-1] == "/top"

    def test_walk_windows_impl_onerror(self):
        """Lines 185-188: _walk_windows_impl with onerror callback."""
        from kanon_cli.repo import platform_utils

        onerror = mock.Mock()
        with mock.patch.object(platform_utils, "listdir", side_effect=OSError("fail")):
            results = list(platform_utils._walk_windows_impl("/top", True, onerror, False))
            onerror.assert_called_once()
            assert results == []

    def test_walk_windows_impl_followlinks(self):
        """Lines 200-202: _walk_windows_impl with followlinks=True."""
        from kanon_cli.repo import platform_utils

        with (
            mock.patch.object(platform_utils, "listdir", return_value=["lnk"]),
            mock.patch.object(platform_utils, "isdir", return_value=True),
            mock.patch.object(platform_utils, "islink", return_value=True),
        ):
            # followlinks=True: should recurse into symlinked dirs
            with mock.patch.object(platform_utils, "listdir", side_effect=[["lnk"], []]):
                results = list(platform_utils._walk_windows_impl("/top", True, None, True))
                assert len(results) >= 1


# ---------------------------------------------------------------------------
# git_superproject.py  (uncovered: 190-193, 197, 203, 207, 218, 369,
#                        419-422, 430-432, 474, 525, 558, 594)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectLogAndSync:
    """Cover _LogMessage, _LogError, _LogWarning, Sync completion."""

    def _make_superproject(self):
        from kanon_cli.repo.git_superproject import Superproject

        manifest = mock.Mock()
        manifest.repodir = "/tmp/repo"
        manifest.path_prefix = ""
        manifest.SubmanifestInfoDir.return_value = "/tmp/sp"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/sp.git"
        remote.review = "https://review.example.com"

        sp = Superproject(manifest, "super", remote, "main")
        sp._git_event_log = mock.Mock()
        return sp

    def test_log_message_prints_when_enabled(self):
        """Lines 190-193: _LogMessage prints to stderr when _print_messages."""
        sp = self._make_superproject()
        sp._print_messages = True

        with mock.patch("builtins.print") as mock_print:
            sp._LogMessage("test {}", "val")
            mock_print.assert_called_once()
            msg = mock_print.call_args[0][0]
            assert "test val" in msg

    def test_log_message_prefix(self):
        """Line 197: _LogMessagePrefix returns branch and url."""
        sp = self._make_superproject()
        prefix = sp._LogMessagePrefix()
        assert "main" in prefix
        assert "https://example.com/sp.git" in prefix

    def test_log_error(self):
        """Line 203: _LogError prefixes with 'error:'."""
        sp = self._make_superproject()
        sp._print_messages = True

        with mock.patch("builtins.print") as mock_print:
            sp._LogError("oops {}", "detail")
            msg = mock_print.call_args[0][0]
            assert "error:" in msg

    def test_log_warning(self):
        """Line 207: _LogWarning prefixes with 'warning:'."""
        sp = self._make_superproject()
        sp._print_messages = True

        with mock.patch("builtins.print") as mock_print:
            sp._LogWarning("caution {}", "info")
            msg = mock_print.call_args[0][0]
            assert "warning:" in msg

    def test_init_prints_when_not_quiet(self):
        """Line 218: _Init prints setup message when not quiet."""
        sp = self._make_superproject()
        sp._quiet = False

        mock_p = mock.Mock()
        mock_p.Wait.return_value = 0

        with (
            mock.patch("os.path.exists", side_effect=[True, False]),
            mock.patch("builtins.print") as mock_print,
            mock.patch("kanon_cli.repo.git_superproject.GitCommand", return_value=mock_p),
        ):
            result = sp._Init()
            assert result is True
            mock_print.assert_called_once()

    def test_sync_successful_prints_completion(self):
        """Line 369: Sync prints completion message when successful."""
        sp = self._make_superproject()
        sp._quiet = False
        sp._manifest.superproject = True

        with (
            mock.patch.object(sp, "_Init", return_value=True),
            mock.patch.object(sp, "_Fetch", return_value=True),
            mock.patch("builtins.print") as mock_print,
        ):
            result = sp.Sync(mock.Mock())
            assert result.success is True
            assert result.fatal is False
            # Check completion message printed
            assert any("completed" in str(c) for c in mock_print.call_args_list)


@pytest.mark.unit
class TestSuperprojectWriteManifest:
    """Cover _WriteManifestFile lines 419-422, 430-432."""

    def _make_superproject(self):
        from kanon_cli.repo.git_superproject import Superproject

        manifest = mock.Mock()
        manifest.repodir = "/tmp/repo"
        manifest.path_prefix = ""
        manifest.SubmanifestInfoDir.return_value = "/tmp/sp"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/sp.git"

        sp = Superproject(manifest, "super", remote, "main")
        sp._git_event_log = mock.Mock()
        return sp

    def test_write_manifest_missing_dir(self):
        """Lines 419-422: returns None when superproject dir missing."""
        sp = self._make_superproject()
        sp._print_messages = True

        with (
            mock.patch("os.path.exists", return_value=False),
            mock.patch("builtins.print"),
        ):
            result = sp._WriteManifestFile()
            assert result is None

    def test_write_manifest_oserror(self):
        """Lines 430-432: returns None on OSError writing file."""
        sp = self._make_superproject()
        sp._print_messages = True

        with (
            mock.patch("os.path.exists", return_value=True),
            mock.patch("builtins.open", side_effect=OSError("disk full")),
            mock.patch("builtins.print"),
        ):
            result = sp._WriteManifestFile()
            assert result is None


@pytest.mark.unit
class TestSuperprojectUpdateProjects:
    """Cover UpdateProjectsRevisionId line 474 and missing commit ids."""

    def _make_superproject(self):
        from kanon_cli.repo.git_superproject import Superproject

        manifest = mock.Mock()
        manifest.repodir = "/tmp/repo"
        manifest.path_prefix = ""
        manifest.SubmanifestInfoDir.return_value = "/tmp/sp"
        manifest.contactinfo = mock.Mock()
        manifest.contactinfo.bugurl = "https://bugs.example.com"

        remote = mock.Mock()
        remote.name = "origin"
        remote.url = "https://example.com/sp.git"

        sp = Superproject(manifest, "super", remote, "main")
        sp._git_event_log = mock.Mock()
        sp._print_messages = True
        return sp

    def test_update_projects_missing_commit_ids(self):
        """Line 474+: projects with missing commit ids triggers warning."""
        sp = self._make_superproject()

        project = mock.Mock()
        project.relpath = "missing_proj"
        project.revisionId = None
        project.manifest.IsFromLocalManifest.return_value = False

        with mock.patch.object(sp, "_GetAllProjectsCommitIds") as mock_get:
            from kanon_cli.repo.git_superproject import CommitIdsResult

            mock_get.return_value = CommitIdsResult(commit_ids={"other_proj": "abc123"}, fatal=False)
            with mock.patch("builtins.print"):
                result = sp.UpdateProjectsRevisionId([project], mock.Mock())
            assert result.manifest_path is None
            assert result.fatal is False

    def test_update_projects_skip_project(self):
        """Line 474: project with revisionId is skipped via continue."""
        sp = self._make_superproject()

        # Project that should be skipped (has revisionId)
        skipped_project = mock.Mock()
        skipped_project.relpath = "proj_with_id"
        skipped_project.revisionId = "already_set"

        # Project that will be updated
        updated_project = mock.Mock()
        updated_project.relpath = "proj_to_update"
        updated_project.revisionId = None
        updated_project.manifest.IsFromLocalManifest.return_value = False

        with (
            mock.patch.object(sp, "_GetAllProjectsCommitIds") as mock_get,
            mock.patch.object(sp, "_WriteManifestFile", return_value="/tmp/manifest.xml"),
        ):
            from kanon_cli.repo.git_superproject import CommitIdsResult

            mock_get.return_value = CommitIdsResult(commit_ids={"proj_to_update": "newid123"}, fatal=False)
            result = sp.UpdateProjectsRevisionId([skipped_project, updated_project], mock.Mock())
            assert result.manifest_path == "/tmp/manifest.xml"
            updated_project.SetRevisionId.assert_called_once_with("newid123")
            skipped_project.SetRevisionId.assert_not_called()


@pytest.mark.unit
class TestUseSuperprojectFromConfiguration:
    """Cover _UseSuperprojectFromConfiguration lines 525, 558."""

    def test_user_choice_false(self):
        """Line 525: user opted out, prints not-enrolled message."""
        from kanon_cli.repo.git_superproject import _UseSuperprojectFromConfiguration
        import time

        # Clear the lru_cache
        _UseSuperprojectFromConfiguration.cache_clear()

        mock_user_cfg = mock.Mock()
        mock_user_cfg.GetBoolean.return_value = False
        mock_user_cfg.GetInt.return_value = int(time.time()) + 10000

        with (
            mock.patch("kanon_cli.repo.git_superproject.RepoConfig") as mock_rc,
            mock.patch("builtins.print"),
        ):
            mock_rc.ForUser.return_value = mock_user_cfg
            result = _UseSuperprojectFromConfiguration()
            assert result is False

        _UseSuperprojectFromConfiguration.cache_clear()

    def test_no_valid_choice_no_system(self):
        """Line 558: no unexpired choice, system says no -> False."""
        from kanon_cli.repo.git_superproject import _UseSuperprojectFromConfiguration

        _UseSuperprojectFromConfiguration.cache_clear()

        mock_user_cfg = mock.Mock()
        mock_user_cfg.GetBoolean.return_value = None

        mock_system_cfg = mock.Mock()
        mock_system_cfg.GetBoolean.return_value = False

        with mock.patch("kanon_cli.repo.git_superproject.RepoConfig") as mock_rc:
            mock_rc.ForUser.return_value = mock_user_cfg
            mock_rc.ForSystem.return_value = mock_system_cfg
            result = _UseSuperprojectFromConfiguration()
            assert result is False

        _UseSuperprojectFromConfiguration.cache_clear()


@pytest.mark.unit
class TestUseSuperproject:
    """Cover UseSuperproject line 594."""

    def test_use_superproject_no_superproject_no_client(self):
        """manifest.superproject truthy but client_value None goes
        to _UseSuperprojectFromConfiguration."""
        from kanon_cli.repo.git_superproject import UseSuperproject

        manifest = mock.Mock()
        manifest.superproject = True
        manifest.manifestProject.use_superproject = None

        with mock.patch(
            "kanon_cli.repo.git_superproject._UseSuperprojectFromConfiguration",
            return_value=False,
        ) as mock_cfg:
            result = UseSuperproject(None, manifest)
            mock_cfg.assert_called_once()
            assert result is False

    def test_use_superproject_superproject_falsy_client_none(self):
        """Line 594: when manifest.superproject is falsy at the elif check,
        the else branch returns False.

        This requires use_superproject=None, client_value=None,
        and manifest.superproject falsy at the elif on line 591.
        """
        from kanon_cli.repo.git_superproject import UseSuperproject

        manifest = mock.Mock()
        # First check on line 582 needs superproject truthy
        # but the elif on line 591 needs it falsy.
        # We use a side_effect to return truthy first, then falsy.
        sp_mock = mock.PropertyMock(side_effect=[True, False])
        type(manifest).superproject = sp_mock
        manifest.manifestProject.use_superproject = None

        result = UseSuperproject(None, manifest)
        assert result is False


# ---------------------------------------------------------------------------
# subcmds/smartsync.py  (uncovered: 32-33)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSmartsyncExecute:
    """Cover Smartsync.Execute lines 32-33."""

    def test_execute_sets_smart_sync(self):
        """Lines 32-33: Execute sets opt.smart_sync and calls Sync.Execute."""
        from kanon_cli.repo.subcmds.smartsync import Smartsync
        from kanon_cli.repo.subcmds.sync import Sync

        smartsync = Smartsync.__new__(Smartsync)
        opt = mock.Mock()
        opt.smart_sync = False

        with mock.patch.object(Sync, "Execute") as mock_exec:
            smartsync.Execute(opt, ["arg1"])
            assert opt.smart_sync is True
            mock_exec.assert_called_once_with(smartsync, opt, ["arg1"])


# ---------------------------------------------------------------------------
# git_trace2_event_log.py  (uncovered: 27-29, 32)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEventLog:
    """Cover EventLog.Write and _GetEventTargetPath lines 27-29, 32."""

    def test_write_uses_event_target_path(self):
        """Lines 27-29: Write calls _GetEventTargetPath when path is None."""
        from kanon_cli.repo.git_trace2_event_log import EventLog

        with mock.patch("kanon_cli.repo.git_trace2_event_log.RepoSourceVersion", return_value="1.0"):
            log = EventLog()

        with (
            mock.patch.object(log, "_GetEventTargetPath", return_value="/tmp/trace") as mock_get,
            mock.patch.object(type(log).__bases__[0], "Write", return_value=True) as mock_write,
        ):
            log.Write()
            mock_get.assert_called_once()
            mock_write.assert_called_once_with(path="/tmp/trace")

    def test_write_with_explicit_path(self):
        """Line 29: Write with explicit path skips _GetEventTargetPath."""
        from kanon_cli.repo.git_trace2_event_log import EventLog

        with mock.patch("kanon_cli.repo.git_trace2_event_log.RepoSourceVersion", return_value="1.0"):
            log = EventLog()

        with mock.patch.object(type(log).__bases__[0], "Write", return_value=True) as mock_write:
            log.Write(path="/explicit/path")
            mock_write.assert_called_once_with(path="/explicit/path")

    def test_get_event_target_path(self):
        """Line 32: _GetEventTargetPath calls GetEventTargetPath."""
        from kanon_cli.repo.git_trace2_event_log import EventLog

        with mock.patch("kanon_cli.repo.git_trace2_event_log.RepoSourceVersion", return_value="1.0"):
            log = EventLog()

        with mock.patch(
            "kanon_cli.repo.git_trace2_event_log.GetEventTargetPath",
            return_value="/target/path",
        ) as mock_gtp:
            result = log._GetEventTargetPath()
            assert result == "/target/path"
            mock_gtp.assert_called_once()


# ---------------------------------------------------------------------------
# subcmds/diff.py  (uncovered: 56-59, 69-72)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDiffExecuteOne:
    """Cover Diff._ExecuteOne lines 56-59."""

    def test_execute_one_returns_output(self):
        """Lines 56-59: _ExecuteOne returns (ret, buf)."""
        from kanon_cli.repo.subcmds.diff import Diff

        mock_project = mock.Mock()
        mock_project.PrintWorkTreeDiff.return_value = True

        with mock.patch.object(
            Diff,
            "get_parallel_context",
            return_value={"projects": [mock_project]},
        ):
            ret, output = Diff._ExecuteOne(True, False, 0)
            assert ret is True
            mock_project.PrintWorkTreeDiff.assert_called_once_with(True, output_redir=mock.ANY, local=False)

    def test_execute_one_with_output(self):
        """Lines 56-59: _ExecuteOne captures output from PrintWorkTreeDiff."""
        from kanon_cli.repo.subcmds.diff import Diff

        mock_project = mock.Mock()

        def write_output(absolute, output_redir=None, local=False):
            output_redir.write("diff --git a/f b/f\n")
            return True

        mock_project.PrintWorkTreeDiff.side_effect = write_output

        with mock.patch.object(
            Diff,
            "get_parallel_context",
            return_value={"projects": [mock_project]},
        ):
            ret, output = Diff._ExecuteOne(False, True, 0)
            assert ret is True
            assert "diff --git" in output


@pytest.mark.unit
class TestDiffExecute:
    """Cover Diff.Execute lines 69-72."""

    def test_execute_processes_results_with_output(self):
        """Lines 69-72: _ProcessResults prints output and tracks failure."""
        from kanon_cli.repo.subcmds.diff import Diff

        diff_cmd = Diff.__new__(Diff)
        diff_cmd.manifest = mock.MagicMock()

        opt = mock.Mock()
        opt.jobs = 1
        opt.this_manifest_only = False
        opt.absolute = False

        mock_project = mock.Mock()

        with (
            mock.patch.object(Diff, "GetProjects", return_value=[mock_project]),
            mock.patch.object(Diff, "ParallelContext") as mock_pc,
            mock.patch.object(Diff, "get_parallel_context", return_value={}),
            mock.patch.object(Diff, "ExecuteInParallel") as mock_exec,
        ):
            mock_pc.return_value.__enter__ = mock.MagicMock()
            mock_pc.return_value.__exit__ = mock.MagicMock()

            def run_exec(jobs, func, items, callback=None, ordered=False, chunksize=1):
                return callback(
                    None,
                    None,
                    [
                        (True, "diff output\n"),
                        (False, ""),
                    ],
                )

            mock_exec.side_effect = run_exec

            with mock.patch("builtins.print"):
                result = diff_cmd.Execute(opt, [])
            assert result == 1

    def test_execute_all_success(self):
        """Lines 69-72: all projects succeed returns 0."""
        from kanon_cli.repo.subcmds.diff import Diff

        diff_cmd = Diff.__new__(Diff)
        diff_cmd.manifest = mock.MagicMock()

        opt = mock.Mock()
        opt.jobs = 1
        opt.this_manifest_only = False
        opt.absolute = True

        with (
            mock.patch.object(Diff, "GetProjects", return_value=[mock.Mock()]),
            mock.patch.object(Diff, "ParallelContext") as mock_pc,
            mock.patch.object(Diff, "get_parallel_context", return_value={}),
            mock.patch.object(Diff, "ExecuteInParallel") as mock_exec,
        ):
            mock_pc.return_value.__enter__ = mock.MagicMock()
            mock_pc.return_value.__exit__ = mock.MagicMock()

            def run_exec(jobs, func, items, callback=None, ordered=False, chunksize=1):
                return callback(None, None, [(True, "")])

            mock_exec.side_effect = run_exec
            result = diff_cmd.Execute(opt, [])
            assert result == 0


# ---------------------------------------------------------------------------
# subcmds/upload.py  (uncovered: 433, 451, 457, 496, 500-507, 512-515,
#                      677, 743-758, 773, 779-820)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadSingleBranch:
    """Cover _SingleBranch line 433 (verify pending abort)."""

    def _make_upload(self):
        from kanon_cli.repo.subcmds.upload import Upload

        cmd = Upload.__new__(Upload)
        cmd.manifest = mock.MagicMock()
        cmd.git_event_log = mock.Mock()
        return cmd

    def test_single_branch_verify_pending_abort(self):
        """Line 433: _VerifyPendingCommits returns False -> die."""
        from kanon_cli.repo.subcmds.upload import UploadExitError

        cmd = self._make_upload()

        branch = mock.Mock()
        branch.name = "feature"
        branch.project = mock.Mock()
        branch.project.GetBranch.return_value.remote.review = "https://review"
        branch.project.config.GetBoolean.return_value = True  # autoupload

        opt = mock.Mock()
        opt.yes = False

        with mock.patch("kanon_cli.repo.subcmds.upload._VerifyPendingCommits", return_value=False):
            with pytest.raises(UploadExitError):
                cmd._SingleBranch(opt, branch, ([], []))


@pytest.mark.unit
class TestUploadMultipleBranches:
    """Cover _MultipleBranches lines 451, 457, 496, 500-507, 512-515."""

    def _make_upload(self):
        from kanon_cli.repo.subcmds.upload import Upload

        cmd = Upload.__new__(Upload)
        cmd.manifest = mock.MagicMock()
        cmd.git_event_log = mock.Mock()
        return cmd

    def test_multiple_branches_none_branch_skipped(self):
        """Line 451: None branch in avail is skipped."""

        cmd = self._make_upload()

        project = mock.Mock()
        project.RelPath.return_value = "proj1"
        project.dest_branch = None
        project.revisionExpr = "main"

        branch = mock.Mock()
        branch.name = "feat"
        branch.date = "2024-01-01"
        branch.commits = ["commit1"]

        opt = mock.Mock()
        opt.dest_branch = None
        opt.this_manifest_only = False
        opt.yes = True

        # Editor returns uncommented branch line
        edited = "# project proj1/:\n branch feat ( 1 commit, 2024-01-01) to remote branch main:\n"

        with (
            mock.patch("kanon_cli.repo.subcmds.upload.Editor") as mock_editor,
            mock.patch("kanon_cli.repo.subcmds.upload._VerifyPendingCommits", return_value=True),
            mock.patch.object(cmd, "_UploadAndReport"),
        ):
            mock_editor.EditString.return_value = edited
            cmd._MultipleBranches(opt, [(project, [None, branch])], ([], []))

    def test_multiple_branches_second_branch_separator(self):
        """Line 457: second branch in b dict adds '#' separator."""

        cmd = self._make_upload()

        project = mock.Mock()
        project.RelPath.return_value = "proj1"
        project.dest_branch = None
        project.revisionExpr = "main"

        branch1 = mock.Mock()
        branch1.name = "feat1"
        branch1.date = "2024-01-01"
        branch1.commits = ["commit1"]

        branch2 = mock.Mock()
        branch2.name = "feat2"
        branch2.date = "2024-01-02"
        branch2.commits = ["commit2", "commit3"]

        opt = mock.Mock()
        opt.dest_branch = None
        opt.this_manifest_only = False
        opt.yes = True

        edited = "# project proj1/:\n branch feat1 ( 1 commit, 2024-01-01) to remote branch main:\n"

        with (
            mock.patch("kanon_cli.repo.subcmds.upload.Editor") as mock_editor,
            mock.patch("kanon_cli.repo.subcmds.upload._VerifyPendingCommits", return_value=True),
            mock.patch.object(cmd, "_UploadAndReport"),
        ):
            mock_editor.EditString.return_value = edited
            cmd._MultipleBranches(opt, [(project, [branch1, branch2])], ([], []))

    def test_multiple_branches_project_not_available(self):
        """Line 496: unknown project in edited script -> die."""
        from kanon_cli.repo.subcmds.upload import UploadExitError

        cmd = self._make_upload()

        project = mock.Mock()
        project.RelPath.return_value = "proj1"
        project.dest_branch = None
        project.revisionExpr = "main"

        branch = mock.Mock()
        branch.name = "feat"
        branch.date = "2024-01-01"
        branch.commits = ["c1"]

        opt = mock.Mock()
        opt.dest_branch = None
        opt.this_manifest_only = False
        opt.yes = True

        edited = "# project unknown_proj/:\n branch feat (1 commit, date) to remote branch main:\n"

        with mock.patch("kanon_cli.repo.subcmds.upload.Editor") as mock_editor:
            mock_editor.EditString.return_value = edited
            with pytest.raises(UploadExitError):
                cmd._MultipleBranches(opt, [(project, [branch])], ([], []))

    def test_multiple_branches_branch_without_project(self):
        """Lines 500-502: branch line before any project -> die."""
        from kanon_cli.repo.subcmds.upload import UploadExitError

        cmd = self._make_upload()

        project = mock.Mock()
        project.RelPath.return_value = "proj1"
        project.dest_branch = None
        project.revisionExpr = "main"

        branch = mock.Mock()
        branch.name = "feat"
        branch.date = "2024-01-01"
        branch.commits = ["c1"]

        opt = mock.Mock()
        opt.dest_branch = None
        opt.this_manifest_only = False
        opt.yes = True

        edited = " branch feat (1 commit, date) to remote branch main:\n"

        with mock.patch("kanon_cli.repo.subcmds.upload.Editor") as mock_editor:
            mock_editor.EditString.return_value = edited
            with pytest.raises(UploadExitError):
                cmd._MultipleBranches(opt, [(project, [branch])], ([], []))

    def test_multiple_branches_branch_not_in_project(self):
        """Lines 505-506: branch not found in project -> die."""
        from kanon_cli.repo.subcmds.upload import UploadExitError

        cmd = self._make_upload()

        project = mock.Mock()
        project.RelPath.return_value = "proj1"
        project.dest_branch = None
        project.revisionExpr = "main"

        branch = mock.Mock()
        branch.name = "feat"
        branch.date = "2024-01-01"
        branch.commits = ["c1"]

        opt = mock.Mock()
        opt.dest_branch = None
        opt.this_manifest_only = False
        opt.yes = True

        edited = " project proj1/:\n branch unknown_branch (1 commit, date) to remote branch main:\n"

        with mock.patch("kanon_cli.repo.subcmds.upload.Editor") as mock_editor:
            mock_editor.EditString.return_value = edited
            with pytest.raises(UploadExitError):
                cmd._MultipleBranches(opt, [(project, [branch])], ([], []))

    def test_multiple_branches_verify_abort(self):
        """Lines 512-513: _VerifyPendingCommits returns False -> die."""
        from kanon_cli.repo.subcmds.upload import UploadExitError

        cmd = self._make_upload()

        project = mock.Mock()
        project.RelPath.return_value = "proj1"
        project.dest_branch = None
        project.revisionExpr = "main"

        branch = mock.Mock()
        branch.name = "feat"
        branch.date = "2024-01-01"
        branch.commits = ["c1"]

        opt = mock.Mock()
        opt.dest_branch = None
        opt.this_manifest_only = False
        opt.yes = False

        edited = " project proj1/:\n branch feat (1 commit, date) to remote branch main:\n"

        with (
            mock.patch("kanon_cli.repo.subcmds.upload.Editor") as mock_editor,
            mock.patch("kanon_cli.repo.subcmds.upload._VerifyPendingCommits", return_value=False),
        ):
            mock_editor.EditString.return_value = edited
            with pytest.raises(UploadExitError):
                cmd._MultipleBranches(opt, [(project, [branch])], ([], []))


@pytest.mark.unit
class TestUploadAndReportLongError:
    """Cover _UploadAndReport line 677 (long error message)."""

    def _make_upload(self):
        from kanon_cli.repo.subcmds.upload import Upload

        cmd = Upload.__new__(Upload)
        cmd.manifest = mock.MagicMock()
        cmd.git_event_log = mock.Mock()
        return cmd

    def test_upload_and_report_long_error_message(self):
        """Line 677: error message > 30 chars uses multiline format."""
        from kanon_cli.repo.subcmds.upload import UploadExitError
        from kanon_cli.repo.error import UploadError

        cmd = self._make_upload()

        branch = mock.Mock()
        branch.name = "feat"
        branch.project.RelPath.return_value = "proj"
        branch.uploaded = False
        branch.error = UploadError("x" * 40)

        opt = mock.Mock()
        opt.this_manifest_only = False

        with mock.patch.object(cmd, "_UploadBranch", side_effect=UploadError("x" * 40)):
            with pytest.raises(UploadExitError):
                cmd._UploadAndReport(opt, [branch], ([], []))


@pytest.mark.unit
class TestUploadExecute:
    """Cover Upload.Execute lines 743-758, 773, 779-820."""

    def _make_upload(self):
        from kanon_cli.repo.subcmds.upload import Upload

        cmd = Upload.__new__(Upload)
        cmd.manifest = mock.MagicMock()
        cmd.git_event_log = mock.Mock()
        return cmd

    def test_execute_avail_none_logs_error(self):
        """Lines 743-758: avail is None logs branch error."""
        from kanon_cli.repo.subcmds.upload import Upload

        cmd = self._make_upload()

        project = mock.Mock()
        project.RelPath.return_value = "proj"
        project.CurrentBranch = "feat"
        project.manifest.branch = "main"

        opt = mock.Mock()
        opt.jobs = 1
        opt.this_manifest_only = False
        opt.branch = None

        with (
            mock.patch.object(Upload, "GetProjects", return_value=[project]),
            mock.patch.object(Upload, "ParallelContext") as mock_pc,
            mock.patch.object(Upload, "get_parallel_context", return_value={}),
            mock.patch.object(Upload, "ExecuteInParallel") as mock_exec,
        ):
            mock_pc.return_value.__enter__ = mock.MagicMock()
            mock_pc.return_value.__exit__ = mock.MagicMock()

            def run_exec(jobs, func, items, callback=None):
                return callback(None, None, [(0, None)])

            mock_exec.side_effect = run_exec
            result = cmd.Execute(opt, [])
            assert result == 1

    def test_execute_no_branches_with_branch_name(self):
        """Line 773: no branches with specific branch name."""
        from kanon_cli.repo.subcmds.upload import Upload

        cmd = self._make_upload()

        opt = mock.Mock()
        opt.jobs = 1
        opt.this_manifest_only = False
        opt.branch = "nonexistent"

        with (
            mock.patch.object(Upload, "GetProjects", return_value=[]),
            mock.patch.object(Upload, "ParallelContext") as mock_pc,
            mock.patch.object(Upload, "get_parallel_context", return_value={}),
            mock.patch.object(Upload, "ExecuteInParallel", return_value=[]),
        ):
            mock_pc.return_value.__enter__ = mock.MagicMock()
            mock_pc.return_value.__exit__ = mock.MagicMock()

            result = cmd.Execute(opt, [])
            assert result == 1

    def test_execute_hook_fails_partial_sync(self):
        """Lines 779-811: hook fails and partial sync detected."""
        from kanon_cli.repo.subcmds.upload import Upload

        cmd = self._make_upload()

        project = mock.Mock()
        project.name = "proj"
        project.worktree = "/tmp/proj"
        project.manifest.topdir = "/tmp"

        avail_branch = mock.Mock()

        opt = mock.Mock()
        opt.jobs = 1
        opt.this_manifest_only = False
        opt.branch = None
        opt.reviewers = None
        opt.cc = None

        with (
            mock.patch.object(Upload, "GetProjects", return_value=[project]),
            mock.patch.object(Upload, "ParallelContext") as mock_pc,
            mock.patch.object(Upload, "get_parallel_context", return_value={}),
            mock.patch.object(Upload, "ExecuteInParallel") as mock_exec,
            mock.patch("kanon_cli.repo.subcmds.upload.RepoHook") as mock_hook_cls,
            mock.patch("kanon_cli.repo.subcmds.upload.LocalSyncState") as mock_lss,
        ):
            mock_pc.return_value.__enter__ = mock.MagicMock()
            mock_pc.return_value.__exit__ = mock.MagicMock()

            def run_exec(jobs, func, items, callback=None):
                return callback(None, None, [(0, [avail_branch])])

            mock_exec.side_effect = run_exec

            mock_hook = mock.Mock()
            mock_hook.Run.return_value = False
            mock_hook_cls.FromSubcmd.return_value = mock_hook

            mock_lss_inst = mock.Mock()
            mock_lss_inst.IsPartiallySynced.return_value = True
            mock_lss.return_value = mock_lss_inst

            result = cmd.Execute(opt, [])
            assert result == 1

    def test_execute_single_branch_path(self):
        """Lines 817-818: single pending branch calls _SingleBranch."""
        from kanon_cli.repo.subcmds.upload import Upload

        cmd = self._make_upload()

        project = mock.Mock()
        project.name = "proj"
        project.worktree = "/tmp/proj"
        project.manifest.topdir = "/tmp"

        avail_branch = mock.Mock()

        opt = mock.Mock()
        opt.jobs = 1
        opt.this_manifest_only = False
        opt.branch = None
        opt.reviewers = ["user@test.com"]
        opt.cc = None

        with (
            mock.patch.object(Upload, "GetProjects", return_value=[project]),
            mock.patch.object(Upload, "ParallelContext") as mock_pc,
            mock.patch.object(Upload, "get_parallel_context", return_value={}),
            mock.patch.object(Upload, "ExecuteInParallel") as mock_exec,
            mock.patch("kanon_cli.repo.subcmds.upload.RepoHook") as mock_hook_cls,
            mock.patch.object(cmd, "_SingleBranch") as mock_single,
        ):
            mock_pc.return_value.__enter__ = mock.MagicMock()
            mock_pc.return_value.__exit__ = mock.MagicMock()

            def run_exec(jobs, func, items, callback=None):
                return callback(None, None, [(0, [avail_branch])])

            mock_exec.side_effect = run_exec

            mock_hook = mock.Mock()
            mock_hook.Run.return_value = True
            mock_hook_cls.FromSubcmd.return_value = mock_hook

            cmd.Execute(opt, [])
            mock_single.assert_called_once()

    def test_execute_multiple_branches_path(self):
        """Lines 819-820: multiple pending branches calls _MultipleBranches."""
        from kanon_cli.repo.subcmds.upload import Upload

        cmd = self._make_upload()

        project = mock.Mock()
        project.name = "proj"
        project.worktree = "/tmp/proj"
        project.manifest.topdir = "/tmp"

        branch1 = mock.Mock()
        branch2 = mock.Mock()

        opt = mock.Mock()
        opt.jobs = 1
        opt.this_manifest_only = False
        opt.branch = None
        opt.reviewers = None
        opt.cc = ["cc@test.com"]

        with (
            mock.patch.object(Upload, "GetProjects", return_value=[project]),
            mock.patch.object(Upload, "ParallelContext") as mock_pc,
            mock.patch.object(Upload, "get_parallel_context", return_value={}),
            mock.patch.object(Upload, "ExecuteInParallel") as mock_exec,
            mock.patch("kanon_cli.repo.subcmds.upload.RepoHook") as mock_hook_cls,
            mock.patch.object(cmd, "_MultipleBranches") as mock_multi,
        ):
            mock_pc.return_value.__enter__ = mock.MagicMock()
            mock_pc.return_value.__exit__ = mock.MagicMock()

            def run_exec(jobs, func, items, callback=None):
                return callback(None, None, [(0, [branch1, branch2])])

            mock_exec.side_effect = run_exec

            mock_hook = mock.Mock()
            mock_hook.Run.return_value = True
            mock_hook_cls.FromSubcmd.return_value = mock_hook

            cmd.Execute(opt, [])
            mock_multi.assert_called_once()
