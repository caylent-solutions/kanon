# Copyright (C) 2019 The Android Open Source Project
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

"""Unittests for the editor.py module."""

import os
import unittest
from unittest import mock

import pytest

from kanon_cli.repo.editor import Editor


class EditorTestCase(unittest.TestCase):
    """Take care of resetting Editor state across tests."""

    def setUp(self):
        self.setEditor(None)

    def tearDown(self):
        self.setEditor(None)

    @staticmethod
    def setEditor(editor):
        Editor._editor = editor


class GetEditor(EditorTestCase):
    """Check GetEditor behavior."""

    def test_basic(self):
        """Basic checking of _GetEditor."""
        self.setEditor(":")
        self.assertEqual(":", Editor._GetEditor())


class EditString(EditorTestCase):
    """Check EditString behavior."""

    def test_no_editor(self):
        """Check behavior when no editor is available."""
        self.setEditor(":")
        self.assertEqual("foo", Editor.EditString("foo"))

    def test_cat_editor(self):
        """Check behavior when editor is `cat`."""
        self.setEditor("cat")
        self.assertEqual("foo", Editor.EditString("foo"))


@pytest.mark.unit
class SelectEditorTests(EditorTestCase):
    """Tests for Editor._SelectEditor method."""

    def test_select_editor_uses_git_editor(self):
        """_SelectEditor should prefer GIT_EDITOR environment variable."""
        with mock.patch.dict(os.environ, {"GIT_EDITOR": "git-editor"}):
            result = Editor._SelectEditor()
            self.assertEqual(result, "git-editor")

    def test_select_editor_uses_core_editor_config(self):
        """_SelectEditor should use core.editor from config."""
        Editor.globalConfig = mock.Mock()
        Editor.globalConfig.GetString.return_value = "config-editor"
        with mock.patch.dict(os.environ, {}, clear=True):
            result = Editor._SelectEditor()
            self.assertEqual(result, "config-editor")

    def test_select_editor_uses_visual(self):
        """_SelectEditor should use VISUAL environment variable."""
        Editor.globalConfig = mock.Mock()
        Editor.globalConfig.GetString.return_value = None
        with mock.patch.dict(os.environ, {"VISUAL": "visual-editor"}, clear=True):
            result = Editor._SelectEditor()
            self.assertEqual(result, "visual-editor")

    def test_select_editor_uses_editor(self):
        """_SelectEditor should use EDITOR environment variable."""
        Editor.globalConfig = mock.Mock()
        Editor.globalConfig.GetString.return_value = None
        with mock.patch.dict(os.environ, {"EDITOR": "editor-cmd"}, clear=True):
            result = Editor._SelectEditor()
            self.assertEqual(result, "editor-cmd")

    def test_select_editor_defaults_to_vi(self):
        """_SelectEditor should default to vi."""
        Editor.globalConfig = mock.Mock()
        Editor.globalConfig.GetString.return_value = None
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.dict(os.environ, {"TERM": "xterm"}):
                result = Editor._SelectEditor()
                self.assertEqual(result, "vi")

    def test_select_editor_exits_on_dumb_terminal(self):
        """_SelectEditor should exit if terminal is dumb and no editor set."""
        Editor.globalConfig = mock.Mock()
        Editor.globalConfig.GetString.return_value = None
        with mock.patch.dict(os.environ, {"TERM": "dumb"}, clear=True):
            with mock.patch("sys.exit") as mock_exit:
                with mock.patch("builtins.print"):
                    Editor._SelectEditor()
                    mock_exit.assert_called_once_with(1)


@pytest.mark.unit
class GetEditorTests(EditorTestCase):
    """Tests for Editor._GetEditor method."""

    def test_get_editor_caches_result(self):
        """_GetEditor should cache the editor selection."""
        with mock.patch.object(Editor, "_SelectEditor", return_value="cached"):
            result1 = Editor._GetEditor()
            result2 = Editor._GetEditor()
            self.assertEqual(result1, result2)
            self.assertEqual(result1, "cached")

    def test_get_editor_calls_select_once(self):
        """_GetEditor should only call _SelectEditor once."""
        with mock.patch.object(Editor, "_SelectEditor", return_value="test") as mock_select:
            Editor._GetEditor()
            Editor._GetEditor()
            mock_select.assert_called_once()


@pytest.mark.unit
class EditStringTests(EditorTestCase):
    """Tests for Editor.EditString method."""

    def test_edit_string_returns_input_for_colon_editor(self):
        """EditString should return input unchanged when editor is ':'."""
        self.setEditor(":")
        result = Editor.EditString("test data")
        self.assertEqual(result, "test data")

    def test_edit_string_creates_temp_file(self):
        """EditString should create a temporary file."""
        self.setEditor("cat")
        with mock.patch("tempfile.mkstemp") as mock_mkstemp:
            mock_mkstemp.return_value = (999, "/tmp/test")
            with mock.patch("os.write"):
                with mock.patch("os.close"):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_popen.return_value.wait.return_value = 0
                        with mock.patch("builtins.open", mock.mock_open(read_data=b"result")):
                            with mock.patch("kanon_cli.repo.platform_utils.remove"):
                                Editor.EditString("data")
                                mock_mkstemp.assert_called_once()

    def test_edit_string_writes_data_to_temp_file(self):
        """EditString should write data to temporary file."""
        self.setEditor("cat")
        with mock.patch("tempfile.mkstemp", return_value=(999, "/tmp/test")):
            with mock.patch("os.write") as mock_write:
                with mock.patch("os.close"):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_popen.return_value.wait.return_value = 0
                        with mock.patch("builtins.open", mock.mock_open(read_data=b"result")):
                            with mock.patch("kanon_cli.repo.platform_utils.remove"):
                                Editor.EditString("test data")
                                call_args = mock_write.call_args[0]
                                self.assertEqual(call_args[0], 999)
                                self.assertEqual(call_args[1], b"test data")

    def test_edit_string_closes_fd(self):
        """EditString should close file descriptor after writing."""
        self.setEditor("cat")
        with mock.patch("tempfile.mkstemp", return_value=(999, "/tmp/test")):
            with mock.patch("os.write"):
                with mock.patch("os.close") as mock_close:
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_popen.return_value.wait.return_value = 0
                        with mock.patch("builtins.open", mock.mock_open(read_data=b"result")):
                            with mock.patch("kanon_cli.repo.platform_utils.remove"):
                                Editor.EditString("data")
                                mock_close.assert_called_with(999)

    def test_edit_string_runs_editor(self):
        """EditString should run the editor command."""
        self.setEditor("myeditor")
        with mock.patch("tempfile.mkstemp", return_value=(999, "/tmp/test")):
            with mock.patch("os.write"):
                with mock.patch("os.close"):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_popen.return_value.wait.return_value = 0
                        with mock.patch("builtins.open", mock.mock_open(read_data=b"result")):
                            with mock.patch("kanon_cli.repo.platform_utils.remove"):
                                with mock.patch(
                                    "kanon_cli.repo.platform_utils.isWindows",
                                    return_value=False,
                                ):
                                    Editor.EditString("data")
                                    call_args = mock_popen.call_args[0][0]
                                    self.assertIn("myeditor", call_args)

    def test_edit_string_reads_result(self):
        """EditString should read and return edited content."""
        self.setEditor("cat")
        with mock.patch("tempfile.mkstemp", return_value=(999, "/tmp/test")):
            with mock.patch("os.write"):
                with mock.patch("os.close"):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_popen.return_value.wait.return_value = 0
                        with mock.patch(
                            "builtins.open",
                            mock.mock_open(read_data=b"edited result"),
                        ):
                            with mock.patch("kanon_cli.repo.platform_utils.remove"):
                                result = Editor.EditString("data")
                                self.assertEqual(result, "edited result")

    def test_edit_string_removes_temp_file(self):
        """EditString should remove temporary file after editing."""
        self.setEditor("cat")
        with mock.patch("tempfile.mkstemp", return_value=(999, "/tmp/test")):
            with mock.patch("os.write"):
                with mock.patch("os.close"):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_popen.return_value.wait.return_value = 0
                        with mock.patch("builtins.open", mock.mock_open(read_data=b"result")):
                            with mock.patch("kanon_cli.repo.platform_utils.remove") as mock_remove:
                                Editor.EditString("data")
                                mock_remove.assert_called_once_with("/tmp/test")

    def test_edit_string_raises_on_nonzero_exit(self):
        """EditString should raise EditorError on nonzero exit code."""
        from kanon_cli.repo.error import EditorError

        self.setEditor("cat")
        with mock.patch("tempfile.mkstemp", return_value=(999, "/tmp/test")):
            with mock.patch("os.write"):
                with mock.patch("os.close"):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_popen.return_value.wait.return_value = 1
                        with mock.patch("kanon_cli.repo.platform_utils.remove"):
                            with self.assertRaises(EditorError):
                                Editor.EditString("data")

    def test_edit_string_raises_on_oserror(self):
        """EditString should raise EditorError on OSError."""
        from kanon_cli.repo.error import EditorError

        self.setEditor("nonexistent-editor")
        with mock.patch("tempfile.mkstemp", return_value=(999, "/tmp/test")):
            with mock.patch("os.write"):
                with mock.patch("os.close"):
                    with mock.patch("subprocess.Popen", side_effect=OSError("fail")):
                        with mock.patch("kanon_cli.repo.platform_utils.remove"):
                            with self.assertRaises(EditorError):
                                Editor.EditString("data")

    def test_edit_string_uses_shlex_on_windows(self):
        """EditString should use shlex.split on Windows."""
        self.setEditor("my editor")
        with mock.patch("tempfile.mkstemp", return_value=(999, "/tmp/test")):
            with mock.patch("os.write"):
                with mock.patch("os.close"):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_popen.return_value.wait.return_value = 0
                        with mock.patch("builtins.open", mock.mock_open(read_data=b"result")):
                            with mock.patch("kanon_cli.repo.platform_utils.remove"):
                                with mock.patch(
                                    "kanon_cli.repo.platform_utils.isWindows",
                                    return_value=True,
                                ):
                                    Editor.EditString("data")
                                    call_kwargs = mock_popen.call_args[1]
                                    self.assertFalse(call_kwargs.get("shell", True))

    def test_edit_string_uses_shell_for_complex_editor(self):
        """EditString should use shell for complex editor commands on Unix."""
        self.setEditor("vi $OPTS")
        with mock.patch("tempfile.mkstemp", return_value=(999, "/tmp/test")):
            with mock.patch("os.write"):
                with mock.patch("os.close"):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_popen.return_value.wait.return_value = 0
                        with mock.patch("builtins.open", mock.mock_open(read_data=b"result")):
                            with mock.patch("kanon_cli.repo.platform_utils.remove"):
                                with mock.patch(
                                    "kanon_cli.repo.platform_utils.isWindows",
                                    return_value=False,
                                ):
                                    Editor.EditString("data")
                                    call_kwargs = mock_popen.call_args[1]
                                    self.assertTrue(call_kwargs.get("shell", False))
