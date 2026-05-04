# Copyright 2021 The Android Open Source Project
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

"""Unittests for the platform_utils.py module."""

import os
import tempfile
import unittest
from unittest import mock

import pytest

from kanon_cli.repo import platform_utils


class RemoveTests(unittest.TestCase):
    """Check remove() helper."""

    def testMissingOk(self):
        """Check missing_ok handling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test")

            # Should not fail.
            platform_utils.remove(path, missing_ok=True)

            # Should fail.
            self.assertRaises(OSError, platform_utils.remove, path)
            self.assertRaises(OSError, platform_utils.remove, path, missing_ok=False)

            # Should not fail if it exists.
            open(path, "w").close()
            platform_utils.remove(path, missing_ok=True)
            self.assertFalse(os.path.exists(path))

            open(path, "w").close()
            platform_utils.remove(path)
            self.assertFalse(os.path.exists(path))

            open(path, "w").close()
            platform_utils.remove(path, missing_ok=False)
            self.assertFalse(os.path.exists(path))


@pytest.mark.unit
class IsWindowsTests(unittest.TestCase):
    """Tests for isWindows function."""

    def test_returns_true_on_windows(self):
        """isWindows should return True on Windows platform."""
        with mock.patch("platform.system", return_value="Windows"):
            self.assertTrue(platform_utils.isWindows())

    def test_returns_false_on_linux(self):
        """isWindows should return False on Linux."""
        with mock.patch("platform.system", return_value="Linux"):
            self.assertFalse(platform_utils.isWindows())

    def test_returns_false_on_darwin(self):
        """isWindows should return False on macOS."""
        with mock.patch("platform.system", return_value="Darwin"):
            self.assertFalse(platform_utils.isWindows())

    def test_returns_false_on_cygwin(self):
        """isWindows should return False on Cygwin."""
        with mock.patch("platform.system", return_value="CYGWIN_NT-10.0"):
            self.assertFalse(platform_utils.isWindows())


@pytest.mark.unit
class SymlinkTests(unittest.TestCase):
    """Tests for symlink function."""

    def test_calls_os_symlink_on_unix(self):
        """symlink should call os.symlink on Unix systems."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=False):
            with mock.patch("os.symlink") as mock_symlink:
                platform_utils.symlink("target", "link")
                mock_symlink.assert_called_once_with("target", "link")

    def test_validates_path_on_windows(self):
        """symlink should validate paths on Windows."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
            with mock.patch("kanon_cli.repo.platform_utils._validate_winpath") as mock_validate:
                with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=False):
                    with mock.patch("sys.modules", {"platform_utils_win32": mock.Mock()}):
                        mock_validate.return_value = "valid_path"
                        platform_utils.symlink("target", "link")
                        self.assertEqual(mock_validate.call_count, 2)


@pytest.mark.unit
class ValidateWinpathTests(unittest.TestCase):
    """Tests for _validate_winpath function."""

    def test_raises_on_invalid_path(self):
        """_validate_winpath should raise ValueError for invalid paths."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
            with mock.patch("kanon_cli.repo.platform_utils._winpath_is_valid", return_value=False):
                with self.assertRaises(ValueError):
                    platform_utils._validate_winpath("\\\\bad\\path")

    def test_returns_normalized_path(self):
        """_validate_winpath should return normalized valid path."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
            with mock.patch("kanon_cli.repo.platform_utils._winpath_is_valid", return_value=True):
                result = platform_utils._validate_winpath("path\\to\\file")
                self.assertIsInstance(result, str)


@pytest.mark.unit
class WinpathIsValidTests(unittest.TestCase):
    """Tests for _winpath_is_valid function."""

    def test_relative_path_is_valid(self):
        """Relative paths should be valid on Windows."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
            result = platform_utils._winpath_is_valid(".\\foo")
            self.assertTrue(result)

    def test_absolute_path_with_drive_is_valid(self):
        """Absolute paths with drive letter should be valid."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
            result = platform_utils._winpath_is_valid("C:\\foo")
            self.assertTrue(result)


@pytest.mark.unit
class MakelongpathTests(unittest.TestCase):
    """Tests for _makelongpath function."""

    def test_returns_unchanged_on_unix(self):
        """_makelongpath should return path unchanged on Unix."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=False):
            result = platform_utils._makelongpath("/long/path/to/file")
            self.assertEqual(result, "/long/path/to/file")

    def test_returns_unchanged_for_short_path_on_windows(self):
        """_makelongpath should not modify short paths on Windows."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
            result = platform_utils._makelongpath("C:\\short")
            self.assertEqual(result, "C:\\short")

    def test_adds_prefix_for_long_path_on_windows(self):
        """_makelongpath should add \\\\?\\ prefix for long paths."""
        import platform

        if platform.system() == "Windows":
            long_path = "C:\\" + "x" * 250
            result = platform_utils._makelongpath(long_path)
            self.assertTrue(result.startswith("\\\\?\\"))
        else:
            # On non-Windows, long paths are returned unchanged
            long_path = "/path/" + "x" * 250
            result = platform_utils._makelongpath(long_path)
            self.assertEqual(result, long_path)

    def test_does_not_double_prefix(self):
        """_makelongpath should not add prefix if already present."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
            path = "\\\\?\\C:\\already\\prefixed"
            result = platform_utils._makelongpath(path)
            self.assertEqual(result, path)

    def test_skips_relative_paths_on_windows(self):
        """_makelongpath should not modify relative paths."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
            with mock.patch("os.path.isabs", return_value=False):
                result = platform_utils._makelongpath("relative\\path")
                self.assertEqual(result, "relative\\path")


@pytest.mark.unit
class RmtreeTests(unittest.TestCase):
    """Tests for rmtree function."""

    def test_calls_shutil_rmtree(self):
        """rmtree should call shutil.rmtree."""
        with mock.patch("shutil.rmtree") as mock_rmtree:
            with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=False):
                platform_utils.rmtree("/path/to/remove")
                mock_rmtree.assert_called_once()

    def test_uses_onerror_on_windows(self):
        """rmtree should use error handler on Windows."""
        with mock.patch("shutil.rmtree") as mock_rmtree:
            with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
                with mock.patch("kanon_cli.repo.platform_utils._makelongpath", return_value="path"):
                    platform_utils.rmtree("path")
                    call_kwargs = mock_rmtree.call_args[1]
                    self.assertIsNotNone(call_kwargs.get("onerror"))

    def test_handles_ignore_errors(self):
        """rmtree should pass ignore_errors parameter."""
        with mock.patch("shutil.rmtree") as mock_rmtree:
            with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=False):
                platform_utils.rmtree("/path", ignore_errors=True)
                call_kwargs = mock_rmtree.call_args[1]
                self.assertTrue(call_kwargs.get("ignore_errors"))


@pytest.mark.unit
class HandleRmtreeErrorTests(unittest.TestCase):
    """Tests for handle_rmtree_error function."""

    def test_changes_permissions_and_retries(self):
        """handle_rmtree_error should change permissions and retry."""
        mock_func = mock.Mock()
        with mock.patch("os.chmod") as mock_chmod:
            import stat

            platform_utils.handle_rmtree_error(mock_func, "/path", None)
            mock_chmod.assert_called_once_with("/path", stat.S_IWRITE)
            mock_func.assert_called_once_with("/path")


@pytest.mark.unit
class RenameTests(unittest.TestCase):
    """Tests for rename function."""

    def test_uses_shutil_move_on_unix(self):
        """rename should use shutil.move on Unix."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=False):
            with mock.patch("shutil.move") as mock_move:
                platform_utils.rename("src", "dst")
                mock_move.assert_called_once_with("src", "dst")

    def test_uses_os_rename_on_windows(self):
        """rename should use os.rename on Windows."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
            with mock.patch("os.rename") as mock_rename:
                with mock.patch("kanon_cli.repo.platform_utils._makelongpath", side_effect=lambda x: x):
                    platform_utils.rename("src", "dst")
                    mock_rename.assert_called_once()

    def test_removes_existing_file_on_windows_eexist(self):
        """rename should remove existing destination on EEXIST."""
        import errno

        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
            with mock.patch("os.rename") as mock_rename:
                with mock.patch("os.remove") as mock_remove:
                    with mock.patch("kanon_cli.repo.platform_utils._makelongpath", side_effect=lambda x: x):
                        error = OSError()
                        error.errno = errno.EEXIST
                        mock_rename.side_effect = [error, None]
                        platform_utils.rename("src", "dst")
                        mock_remove.assert_called_once()


@pytest.mark.unit
class RemoveExtendedTests(unittest.TestCase):
    """Extended tests for remove function."""

    def test_remove_handles_eacces_and_chmod(self):
        """remove should chmod and retry on EACCES."""
        import errno
        import stat

        with mock.patch("os.remove") as mock_remove:
            with mock.patch("os.chmod") as mock_chmod:
                with mock.patch("kanon_cli.repo.platform_utils._makelongpath", side_effect=lambda x: x):
                    with mock.patch("kanon_cli.repo.platform_utils.islink", return_value=False):
                        error = OSError()
                        error.errno = errno.EACCES
                        mock_remove.side_effect = [error, None]
                        platform_utils.remove("/path")
                        mock_chmod.assert_called_once_with("/path", stat.S_IWRITE)
                        self.assertEqual(mock_remove.call_count, 2)

    def test_remove_uses_rmdir_for_dir_symlinks(self):
        """remove should use rmdir for directory symlinks on EACCES."""
        import errno

        with mock.patch("os.remove") as mock_remove:
            with mock.patch("os.chmod"):
                with mock.patch("os.rmdir") as mock_rmdir:
                    with mock.patch("kanon_cli.repo.platform_utils._makelongpath", side_effect=lambda x: x):
                        with mock.patch("kanon_cli.repo.platform_utils.islink", return_value=True):
                            with mock.patch("kanon_cli.repo.platform_utils.isdir", return_value=True):
                                error = OSError()
                                error.errno = errno.EACCES
                                mock_remove.side_effect = error
                                platform_utils.remove("/dirlink")
                                mock_rmdir.assert_called_once_with("/dirlink")

    def test_remove_handles_erofs_with_missing_ok(self):
        """remove should ignore EROFS when missing_ok and file doesn't exist."""
        import errno

        with mock.patch("os.remove") as mock_remove:
            with mock.patch("os.path.exists", return_value=False):
                with mock.patch("kanon_cli.repo.platform_utils._makelongpath", side_effect=lambda x: x):
                    error = OSError()
                    error.errno = errno.EROFS
                    mock_remove.side_effect = error
                    # Should not raise
                    platform_utils.remove("/path", missing_ok=True)

    def test_remove_raises_erofs_when_file_exists(self):
        """remove should raise EROFS when file exists even with missing_ok."""
        import errno

        with mock.patch("os.remove") as mock_remove:
            with mock.patch("os.path.exists", return_value=True):
                with mock.patch("kanon_cli.repo.platform_utils._makelongpath", side_effect=lambda x: x):
                    error = OSError()
                    error.errno = errno.EROFS
                    mock_remove.side_effect = error
                    with self.assertRaises(OSError):
                        platform_utils.remove("/path", missing_ok=True)


@pytest.mark.unit
class WalkTests(unittest.TestCase):
    """Tests for walk function."""

    def test_calls_os_walk_on_unix(self):
        """walk should call os.walk on Unix."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=False):
            with mock.patch("os.walk") as mock_walk:
                mock_walk.return_value = iter([])
                list(platform_utils.walk("/path"))
                mock_walk.assert_called_once()

    def test_uses_custom_impl_on_windows(self):
        """walk should use custom implementation on Windows."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
            with mock.patch("kanon_cli.repo.platform_utils.listdir", return_value=[]):
                result = list(platform_utils.walk("C:\\path"))
                self.assertEqual(len(result), 1)


@pytest.mark.unit
class ListdirTests(unittest.TestCase):
    """Tests for listdir function."""

    def test_calls_os_listdir(self):
        """listdir should call os.listdir with long path."""
        with mock.patch("os.listdir") as mock_listdir:
            with mock.patch("kanon_cli.repo.platform_utils._makelongpath", side_effect=lambda x: x):
                mock_listdir.return_value = []
                platform_utils.listdir("/path")
                mock_listdir.assert_called_once()


@pytest.mark.unit
class RmdirTests(unittest.TestCase):
    """Tests for rmdir function."""

    def test_calls_os_rmdir(self):
        """rmdir should call os.rmdir with long path."""
        with mock.patch("os.rmdir") as mock_rmdir:
            with mock.patch("kanon_cli.repo.platform_utils._makelongpath", side_effect=lambda x: x):
                platform_utils.rmdir("/path")
                mock_rmdir.assert_called_once()


@pytest.mark.unit
class IsdirTests(unittest.TestCase):
    """Tests for isdir function."""

    def test_calls_os_path_isdir(self):
        """isdir should call os.path.isdir with long path."""
        with mock.patch("os.path.isdir") as mock_isdir:
            with mock.patch("kanon_cli.repo.platform_utils._makelongpath", side_effect=lambda x: x):
                mock_isdir.return_value = True
                result = platform_utils.isdir("/path")
                mock_isdir.assert_called_once()
                self.assertTrue(result)


@pytest.mark.unit
class IslinkTests(unittest.TestCase):
    """Tests for islink function."""

    def test_calls_os_islink_on_unix(self):
        """islink should call os.path.islink on Unix."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=False):
            with mock.patch("os.path.islink") as mock_islink:
                mock_islink.return_value = True
                result = platform_utils.islink("/path")
                mock_islink.assert_called_once()
                self.assertTrue(result)

    def test_uses_win32_on_windows(self):
        """islink should use platform_utils_win32 on Windows."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
            with mock.patch("kanon_cli.repo.platform_utils._makelongpath", side_effect=lambda x: x):
                mock_win32 = mock.Mock()
                mock_win32.islink.return_value = False
                with mock.patch.dict("sys.modules", {"platform_utils_win32": mock_win32}):
                    result = platform_utils.islink("C:\\path")
                    mock_win32.islink.assert_called_once()
                    self.assertFalse(result)


@pytest.mark.unit
class ReadlinkTests(unittest.TestCase):
    """Tests for readlink function."""

    def test_calls_os_readlink_on_unix(self):
        """readlink should call os.readlink on Unix."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=False):
            with mock.patch("os.readlink") as mock_readlink:
                mock_readlink.return_value = "/target"
                result = platform_utils.readlink("/link")
                mock_readlink.assert_called_once()
                self.assertEqual(result, "/target")

    def test_uses_win32_on_windows(self):
        """readlink should use platform_utils_win32 on Windows."""
        with mock.patch("kanon_cli.repo.platform_utils.isWindows", return_value=True):
            with mock.patch("kanon_cli.repo.platform_utils._makelongpath", side_effect=lambda x: x):
                mock_win32 = mock.Mock()
                mock_win32.readlink.return_value = "C:\\target"
                with mock.patch.dict("sys.modules", {"platform_utils_win32": mock_win32}):
                    result = platform_utils.readlink("C:\\link")
                    mock_win32.readlink.assert_called_once()
                    self.assertEqual(result, "C:\\target")
