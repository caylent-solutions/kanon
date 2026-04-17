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

"""Unit tests for subcmds/envsubst.py coverage."""

import os
from unittest import mock
from xml.dom import minidom

import pytest

from kanon_cli.repo.subcmds.envsubst import Envsubst


def _make_cmd():
    """Create an Envsubst command instance for testing."""
    cmd = Envsubst.__new__(Envsubst)
    cmd.manifest = mock.MagicMock()
    return cmd


@pytest.mark.unit
def test_execute():
    """Test Execute method."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    args = []

    with mock.patch("glob.glob", return_value=["/tmp/test.xml"]):
        with mock.patch("os.path.getsize", return_value=100):
            with mock.patch.object(cmd, "EnvSubst") as mock_envsubst:
                with mock.patch("builtins.print"):
                    cmd.Execute(opt, args)

                    mock_envsubst.assert_called_once_with("/tmp/test.xml")


@pytest.mark.unit
def test_execute_empty_file():
    """Test Execute skips empty files."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    args = []

    with mock.patch("glob.glob", return_value=["/tmp/empty.xml"]):
        with mock.patch("os.path.getsize", return_value=0):
            with mock.patch.object(cmd, "EnvSubst") as mock_envsubst:
                with mock.patch("builtins.print"):
                    cmd.Execute(opt, args)

                    mock_envsubst.assert_not_called()


@pytest.mark.unit
def test_execute_multiple_files():
    """Test Execute processes multiple XML files."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    args = []

    with mock.patch("glob.glob", return_value=["/tmp/file1.xml", "/tmp/file2.xml"]):
        with mock.patch("os.path.getsize", return_value=100):
            with mock.patch.object(cmd, "EnvSubst") as mock_envsubst:
                with mock.patch("builtins.print"):
                    cmd.Execute(opt, args)

                    assert mock_envsubst.call_count == 2


@pytest.mark.unit
def test_envsubst(tmp_path):
    """Test EnvSubst method reads file and calls parseString.

    Updated from minidom.parse to minidom.parseString after Bug 18 fix:
    EnvSubst now reads the file content first, then parses the string.
    """
    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest/>\n'
    test_file = tmp_path / "test.xml"
    test_file.write_text(xml_content, encoding="utf-8")

    cmd = _make_cmd()

    with mock.patch("xml.dom.minidom.parseString") as mock_parse_string:
        mock_doc = mock.MagicMock()
        mock_parse_string.return_value = mock_doc

        with mock.patch.object(cmd, "search_replace_placeholders"):
            with mock.patch("os.rename"):
                with mock.patch.object(cmd, "save"):
                    cmd.EnvSubst(str(test_file))

                    mock_parse_string.assert_called_once_with(xml_content.encode("utf-8"))


@pytest.mark.unit
def test_envsubst_creates_backup(tmp_path):
    """Test EnvSubst creates backup file.

    Updated to use a real file path so the open() call in EnvSubst succeeds
    before the mocked os.rename is checked.
    """
    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest/>\n'
    test_file = tmp_path / "test.xml"
    test_file.write_text(xml_content, encoding="utf-8")
    test_file_str = str(test_file)

    cmd = _make_cmd()

    with mock.patch("os.rename") as mock_rename:
        with mock.patch.object(cmd, "save"):
            cmd.EnvSubst(test_file_str)

            mock_rename.assert_called_once_with(test_file_str, test_file_str + ".bak")


@pytest.mark.unit
def test_is_placeholder_detected_true():
    """Test is_placeholder_detected with placeholder."""
    cmd = _make_cmd()

    assert cmd.is_placeholder_detected("${MYVAR}") is True
    assert cmd.is_placeholder_detected("prefix_${VAR}_suffix") is True
    assert cmd.is_placeholder_detected("$SIMPLE") is True


@pytest.mark.unit
def test_is_placeholder_detected_false():
    """Test is_placeholder_detected without placeholder."""
    cmd = _make_cmd()

    assert cmd.is_placeholder_detected("no_placeholder") is False
    assert cmd.is_placeholder_detected("") is False


@pytest.mark.unit
def test_resolve_variable():
    """Test resolve_variable method."""
    cmd = _make_cmd()

    with mock.patch.dict(os.environ, {"MYVAR": "myvalue"}):
        result = cmd.resolve_variable("${MYVAR}")
        assert result == "myvalue"


@pytest.mark.unit
def test_resolve_variable_multiple():
    """Test resolve_variable with multiple variables."""
    cmd = _make_cmd()

    with mock.patch.dict(os.environ, {"VAR1": "value1", "VAR2": "value2"}):
        result = cmd.resolve_variable("${VAR1}/${VAR2}")
        assert result == "value1/value2"


@pytest.mark.unit
def test_search_replace_placeholders_attributes():
    """Test search_replace_placeholders replaces attributes."""
    cmd = _make_cmd()

    xml_str = '<?xml version="1.0"?><root><elem attr="${MYVAR}"/></root>'
    doc = minidom.parseString(xml_str)

    with mock.patch.dict(os.environ, {"MYVAR": "replaced"}):
        cmd.search_replace_placeholders(doc)

        elem = doc.getElementsByTagName("elem")[0]
        assert elem.getAttribute("attr") == "replaced"


@pytest.mark.unit
def test_search_replace_placeholders_text():
    """Test search_replace_placeholders replaces text nodes."""
    cmd = _make_cmd()

    xml_str = '<?xml version="1.0"?><root><elem>${MYVAR}</elem></root>'
    doc = minidom.parseString(xml_str)

    with mock.patch.dict(os.environ, {"MYVAR": "replaced"}):
        cmd.search_replace_placeholders(doc)

        elem = doc.getElementsByTagName("elem")[0]
        assert elem.firstChild.nodeValue == "replaced"


@pytest.mark.unit
def test_search_replace_placeholders_no_change():
    """Test search_replace_placeholders when no placeholders."""
    cmd = _make_cmd()

    xml_str = '<?xml version="1.0"?><root><elem attr="value">text</elem></root>'
    doc = minidom.parseString(xml_str)

    cmd.search_replace_placeholders(doc)

    elem = doc.getElementsByTagName("elem")[0]
    assert elem.getAttribute("attr") == "value"
    assert elem.firstChild.nodeValue == "text"


@pytest.mark.unit
def test_save():
    """Test save method."""
    cmd = _make_cmd()

    xml_str = '<?xml version="1.0"?><root><elem attr="value"/></root>'
    doc = minidom.parseString(xml_str)

    with mock.patch("builtins.open", mock.mock_open()) as mock_file:
        cmd.save("/tmp/output.xml", doc)

        mock_file.assert_called_once_with("/tmp/output.xml", "wb")
        # Verify write was called
        handle = mock_file()
        assert handle.write.called
