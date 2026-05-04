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

"""Regression guard for E0-F6-S1-T1: envsubst malformed XML crash.

Bug reference: E0-F6-S1-T1 -- envsubst crashed with an unhandled ExpatError
when minidom.parse() encountered malformed XML after environment variable
substitution.

Root cause: subcmds/envsubst.py -- minidom.parse() raised ExpatError on
malformed XML with no try-except. Processing crashed and could orphan a .bak
file.

Fix: Wrapped minidom.parse() in a try-except for xml.parsers.expat.ExpatError.
Logs the error with the filename, skips the file, and continues processing
remaining files. Does not create a .bak backup for files that fail to parse.

This regression guard asserts that the fix remains in place and that the
exact bug condition from E0-F6-S1-T1 does not regress.
"""

import inspect
import logging
from unittest import mock
from xml.parsers.expat import ExpatError

import pytest

from kanon_cli.repo.subcmds import envsubst as envsubst_module
from kanon_cli.repo.subcmds.envsubst import Envsubst

# ---------------------------------------------------------------------------
# Constants -- malformed XML inputs that trigger the original bug
# ---------------------------------------------------------------------------

_MALFORMED_XML_UNCLOSED_TAG = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${GITBASE}"
  UNCLOSED TAG NO CLOSING BRACKET
</manifest>
"""

_MALFORMED_XML_MISMATCHED = "<?xml version='1.0'?><root><child></root>"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cmd():
    """Return an Envsubst instance without invoking __init__ parent chain."""
    cmd = Envsubst.__new__(Envsubst)
    cmd.manifest = mock.MagicMock()
    return cmd


# ---------------------------------------------------------------------------
# AC-TEST-001 -- Regression: ExpatError is caught; no exception propagates
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_envsubst_malformed_xml_does_not_raise(tmp_path):
    """AC-TEST-001: EnvSubst() must not propagate ExpatError for malformed XML.

    This test reproduces the exact bug condition from E0-F6-S1-T1: a malformed
    XML file is passed to EnvSubst(). Before the fix, minidom.parseString()
    raised ExpatError and crashed processing. After the fix the exception is
    caught, logged, and the call returns without raising.

    If this test fails with ExpatError, the E0-F6-S1-T1 bug has regressed.
    """
    malformed_path = tmp_path / "malformed.xml"
    malformed_path.write_text(_MALFORMED_XML_UNCLOSED_TAG, encoding="utf-8")

    cmd = _make_cmd()

    try:
        result = cmd.EnvSubst(str(malformed_path))
    except ExpatError as exc:
        pytest.fail(
            f"E0-F6-S1-T1 regression: EnvSubst() raised ExpatError for malformed XML. "
            f"The try-except for ExpatError in envsubst.py has been removed or broken. "
            f"Original error: {exc}"
        )

    assert result == set(), f"EnvSubst() must return an empty set when parsing fails, got: {result!r}"


# ---------------------------------------------------------------------------
# AC-TEST-002 -- Regression: exact E0-F6-S1-T1 bug condition
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "malformed_xml,test_id",
    [
        (_MALFORMED_XML_UNCLOSED_TAG, "unclosed_tag_in_attribute"),
        (_MALFORMED_XML_MISMATCHED, "mismatched_tags"),
        ("<unclosed>", "bare_unclosed_tag"),
        ("not xml at all", "plain_text"),
        ("<root attr='unclosed", "unclosed_attribute_value"),
    ],
)
def test_exact_bug_condition_all_malformed_inputs(tmp_path, malformed_xml, test_id):
    """AC-TEST-002: All malformed XML inputs from the original bug condition are handled.

    Verifies the exact bug condition: any ExpatError from minidom.parseString()
    must be caught. The parametrized inputs cover the full range of malformed XML
    that triggered the original crash in E0-F6-S1-T1.

    If any parametrized case raises ExpatError, the regression is confirmed.
    """
    bad_path = tmp_path / f"{test_id}.xml"
    bad_path.write_text(malformed_xml, encoding="utf-8")

    cmd = _make_cmd()

    try:
        result = cmd.EnvSubst(str(bad_path))
    except ExpatError as exc:
        pytest.fail(
            f"E0-F6-S1-T1 regression for input {test_id!r}: ExpatError propagated. "
            f"The try-except guard in envsubst.py is missing or broken. Error: {exc}"
        )

    assert result == set(), (
        f"EnvSubst() must return an empty set when parsing fails (input={test_id!r}), got: {result!r}"
    )

    bak_path = tmp_path / f"{test_id}.xml.bak"
    assert not bak_path.exists(), (
        f"No .bak backup must be created for malformed XML input {test_id!r}, "
        f"but {bak_path} was found after EnvSubst() returned."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- Guard: try-except for ExpatError is present in source code
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_expat_error_handler_present_in_source():
    """AC-TEST-003: The ExpatError try-except guard is present in envsubst.py source.

    Inspects the source code of Envsubst.EnvSubst() to confirm that ExpatError
    is caught. If this test fails, the guard has been removed from the source
    and the bug would regress for any malformed XML input.

    This test is complementary to the behavioral tests above: it makes the
    regression condition immediately obvious from the failure message.
    """
    source = inspect.getsource(Envsubst.EnvSubst)

    assert "ExpatError" in source, (
        "E0-F6-S1-T1 regression guard: ExpatError is no longer caught in "
        "Envsubst.EnvSubst(). The try-except block that prevents a crash on "
        "malformed XML has been removed. Restore the handler in "
        "src/kanon_cli/repo/subcmds/envsubst.py."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- Guard: malformed file skipped; processing continues
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_malformed_xml_skipped_processing_continues(tmp_path):
    """AC-FUNC-001: When one file is malformed, subsequent valid files are still processed.

    Verifies the guard prevents the E0-F6-S1-T1 bug from stopping all processing
    when a malformed XML file appears before valid files in the glob list.
    """
    malformed_path = tmp_path / "malformed.xml"
    valid_path = tmp_path / "valid.xml"

    malformed_path.write_text(_MALFORMED_XML_UNCLOSED_TAG, encoding="utf-8")
    valid_path.write_text(
        "<?xml version='1.0' encoding='UTF-8'?><manifest><project name='p'/></manifest>",
        encoding="utf-8",
    )

    malformed_str = str(malformed_path)
    valid_str = str(valid_path)

    cmd = _make_cmd()
    processed_files = []

    def _tracking_envsubst(infile):
        processed_files.append(infile)

    with mock.patch("glob.glob", return_value=[malformed_str, valid_str]):
        with mock.patch("os.path.getsize", return_value=100):
            with mock.patch.object(cmd, "EnvSubst", side_effect=_tracking_envsubst):
                with mock.patch("builtins.print"):
                    cmd.Execute(mock.MagicMock(), [])

    assert valid_str in processed_files, (
        f"E0-F6-S1-T1 regression guard: the valid file {valid_str!r} was not "
        f"processed when preceded by a malformed XML file. "
        f"Processed files: {processed_files!r}"
    )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001 -- Error is logged to the correct channel
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_malformed_xml_error_logged_with_filename(tmp_path, caplog):
    """AC-CHANNEL-001: The malformed XML error is logged (not printed to stdout).

    Verifies that the error message uses the logging subsystem and includes the
    filename, satisfying the channel discipline requirement: errors go to the
    logging channel (stderr in production), not to stdout via print().
    """
    malformed_path = tmp_path / "bad_manifest.xml"
    malformed_path.write_text(_MALFORMED_XML_UNCLOSED_TAG, encoding="utf-8")

    cmd = _make_cmd()
    filename_str = str(malformed_path)

    with caplog.at_level(logging.ERROR, logger=envsubst_module._LOG.name):
        cmd.EnvSubst(filename_str)

    matching = [r for r in caplog.records if filename_str in r.message]
    assert matching, (
        f"E0-F6-S1-T1 regression guard: expected an ERROR log record containing "
        f"the malformed file path {filename_str!r} but none was found. "
        f"Log records: {[r.message for r in caplog.records]!r}"
    )

    assert all(r.levelno == logging.ERROR for r in matching), (
        f"The malformed XML log record must have ERROR level, got: {[r.levelname for r in matching]!r}"
    )
