# Copyright (C) 2026 Caylent, Inc.
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

"""Unit tests for Bug 1: envsubst crashes with ExpatError on malformed XML.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 1 -- Malformed XML in envsubst
causes unhandled exception.

Root cause: subcmds/envsubst.py line 54 -- minidom.parse() raises ExpatError
on malformed XML with no try-except. Processing crashes and may orphan a .bak
file.

Fix: Wrap minidom.parse() in a try-except for xml.parsers.expat.ExpatError.
Log the error with the filename, skip the file, and continue processing
remaining files. Do not create a .bak backup for files that fail to parse.
"""

import logging
from unittest import mock

import pytest

from kanon_cli.repo.subcmds.envsubst import Envsubst

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${GITBASE}" />
  <default revision="main" remote="origin" />
  <project name="myproject" path="myproject" />
</manifest>
"""

_MALFORMED_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${GITBASE}"
  UNCLOSED TAG NO CLOSING BRACKET
</manifest>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cmd():
    """Return an Envsubst instance without invoking __init__ parent chain."""
    cmd = Envsubst.__new__(Envsubst)
    cmd.manifest = mock.MagicMock()
    return cmd


# ---------------------------------------------------------------------------
# AC-TEST-001 -- Malformed XML file is skipped; processing continues
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_malformed_xml_is_skipped_and_processing_continues(tmp_path):
    """AC-TEST-001: When one file is malformed, the next valid file is still processed.

    Creates two XML files: a malformed one followed by a valid one.
    Execute() must skip the malformed file and call EnvSubst() on the valid one.
    """
    malformed_path = tmp_path / "malformed.xml"
    valid_path = tmp_path / "valid.xml"

    malformed_path.write_text(_MALFORMED_XML, encoding="utf-8")
    valid_path.write_text(_VALID_XML, encoding="utf-8")

    malformed_str = str(malformed_path)
    valid_str = str(valid_path)

    cmd = _make_cmd()

    processed_files = []

    def _fake_envsubst(infile):
        # The real EnvSubst raises for malformed XML; we track what is reached.
        processed_files.append(infile)

    with mock.patch("glob.glob", return_value=[malformed_str, valid_str]):
        with mock.patch("os.path.getsize", return_value=100):
            with mock.patch.object(cmd, "EnvSubst", side_effect=_fake_envsubst):
                with mock.patch("builtins.print"):
                    cmd.Execute(mock.MagicMock(), [])

    assert valid_str in processed_files, (
        f"Valid file {valid_str!r} must be processed even when the preceding "
        f"file is malformed. Processed files: {processed_files!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- No crash (ExpatError is caught) when XML is malformed
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_crash_on_malformed_xml(tmp_path):
    """AC-TEST-002: EnvSubst() must not raise ExpatError for malformed XML.

    Calls EnvSubst() directly on a file containing malformed XML and asserts
    that no exception propagates to the caller.
    """
    malformed_path = tmp_path / "malformed.xml"
    malformed_path.write_text(_MALFORMED_XML, encoding="utf-8")

    cmd = _make_cmd()

    # Must not raise -- ExpatError must be caught internally.
    cmd.EnvSubst(str(malformed_path))


# ---------------------------------------------------------------------------
# AC-TEST-003 -- No orphan .bak file left for files that fail to parse
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_bak_file_created_for_malformed_xml(tmp_path):
    """AC-TEST-003: No .bak backup file must be created when parsing fails.

    After EnvSubst() is called on a malformed XML file, the corresponding
    .bak file must not exist alongside the original.
    """
    malformed_path = tmp_path / "malformed.xml"
    malformed_path.write_text(_MALFORMED_XML, encoding="utf-8")

    bak_path = tmp_path / "malformed.xml.bak"

    cmd = _make_cmd()

    # Must not raise and must not create the .bak file.
    cmd.EnvSubst(str(malformed_path))

    assert not bak_path.exists(), (
        f"No .bak backup file must be created for a malformed XML file, "
        f"but {bak_path} exists after EnvSubst() returned."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-002 -- Error is logged with the filename of the malformed XML file
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_logged_with_filename_on_malformed_xml(tmp_path, caplog):
    """AC-FUNC-002: The filename of the malformed XML must appear in the logged error.

    When EnvSubst() encounters a malformed XML file, it must log an error
    message that includes the filename so the user knows which file to fix.
    """
    malformed_path = tmp_path / "malformed.xml"
    malformed_path.write_text(_MALFORMED_XML, encoding="utf-8")

    cmd = _make_cmd()

    with caplog.at_level(logging.ERROR):
        cmd.EnvSubst(str(malformed_path))

    filename = str(malformed_path)
    matching = [r for r in caplog.records if filename in r.message]
    assert matching, (
        f"Expected an ERROR log record containing the malformed file path "
        f"{filename!r}, but none found.\n"
        f"Log records: {[r.message for r in caplog.records]!r}"
    )


# ---------------------------------------------------------------------------
# Parametrized -- multiple malformed inputs all survive without crash
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_xml",
    [
        "not xml at all",
        "<unclosed>",
        "<?xml version='1.0'?><root><child></root>",
        "<root attr='unclosed",
    ],
    ids=["plain_text", "unclosed_tag", "mismatched_tags", "unclosed_attr"],
)
def test_various_malformed_inputs_do_not_crash(tmp_path, bad_xml):
    """Various malformed XML payloads must not cause EnvSubst() to raise."""
    bad_path = tmp_path / "bad.xml"
    bad_path.write_text(bad_xml, encoding="utf-8")

    cmd = _make_cmd()

    # Must not raise for any of the malformed inputs.
    cmd.EnvSubst(str(bad_path))

    # No .bak must be created.
    bak_path = tmp_path / "bad.xml.bak"
    assert not bak_path.exists(), (
        f"No .bak file must exist for malformed XML input {bad_xml!r}, but {bak_path} was created."
    )
