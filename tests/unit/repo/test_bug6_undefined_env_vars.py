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

"""Unit tests for Bug 6: undefined env vars silently preserved.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 6 -- after expandvars() processes
a file, any ${VARIABLE} patterns that remain in the output indicate undefined
environment variables. Currently these are silently preserved with no indication
to the user.

Fix: After expandvars(), scan the result for remaining ${...} patterns. Log a
warning per unresolved variable name (with the filename). Print a summary at the
end listing all unresolved variables across all files. Do not fail -- this is a
warning, not an error.
"""

import logging
import os
from unittest import mock

import pytest

from kanon_cli.repo.subcmds.envsubst import Envsubst


# ---------------------------------------------------------------------------
# XML fixtures
# ---------------------------------------------------------------------------

_MANIFEST_WITH_DEFINED_AND_UNDEFINED = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${DEFINED_VAR}" />
  <remote name="secondary" fetch="${UNDEFINED_VAR_ONE}" />
  <remote name="tertiary" fetch="${UNDEFINED_VAR_TWO}" />
</manifest>
"""

_MANIFEST_WITH_ONLY_DEFINED = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${DEFINED_VAR}" />
</manifest>
"""

_MANIFEST_WITH_TWO_UNDEFINED = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="primary" fetch="${UNDEFINED_FIRST}" />
  <remote name="secondary" fetch="${UNDEFINED_SECOND}" />
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
# AC-TEST-001 -- Warning logged for each unresolved variable
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_warning_logged_for_each_unresolved_variable(tmp_path, caplog):
    """AC-TEST-001: resolve_variable() must log a WARNING for each ${VAR} not expanded.

    When expandvars() leaves a ${VAR} pattern intact (variable undefined in the
    environment), EnvSubst() must emit a WARNING log record that includes both
    the variable name and the filename so the user can diagnose the missing
    variable.

    Arrange: Create a manifest with one defined var and two undefined vars. Set
    DEFINED_VAR in the environment; leave UNDEFINED_VAR_ONE and UNDEFINED_VAR_TWO
    absent.
    Act: Call EnvSubst() on the file.
    Assert: Two WARNING log records exist, each containing the respective
    undefined variable name and the filename.
    """
    manifest_path = tmp_path / "mixed.xml"
    manifest_path.write_text(_MANIFEST_WITH_DEFINED_AND_UNDEFINED, encoding="utf-8")

    cmd = _make_cmd()

    env = {k: v for k, v in os.environ.items() if k not in {"UNDEFINED_VAR_ONE", "UNDEFINED_VAR_TWO"}}
    env["DEFINED_VAR"] = "https://example.com/org/"

    with mock.patch.dict(os.environ, env, clear=True):
        with caplog.at_level(logging.WARNING):
            cmd.EnvSubst(str(manifest_path))

    filename = str(manifest_path)

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]

    var_one_warnings = [r for r in warning_records if "UNDEFINED_VAR_ONE" in r.message]
    assert var_one_warnings, (
        "Expected a WARNING log record containing 'UNDEFINED_VAR_ONE', "
        f"but none found.\nWarning records: {[r.message for r in warning_records]!r}"
    )
    for record in var_one_warnings:
        assert filename in record.message, (
            f"WARNING for UNDEFINED_VAR_ONE must include the filename {filename!r}, "
            f"but it does not.\nRecord message: {record.message!r}"
        )

    var_two_warnings = [r for r in warning_records if "UNDEFINED_VAR_TWO" in r.message]
    assert var_two_warnings, (
        "Expected a WARNING log record containing 'UNDEFINED_VAR_TWO', "
        f"but none found.\nWarning records: {[r.message for r in warning_records]!r}"
    )
    for record in var_two_warnings:
        assert filename in record.message, (
            f"WARNING for UNDEFINED_VAR_TWO must include the filename {filename!r}, "
            f"but it does not.\nRecord message: {record.message!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- Unresolved variables preserved in output
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_unresolved_variables_preserved_in_output(tmp_path):
    """AC-TEST-002: Undefined ${VAR} patterns must remain literally in the output.

    After EnvSubst() processes a file containing ${UNDEFINED_VAR_ONE} (with that
    variable absent from the environment), the written output file must still
    contain ${UNDEFINED_VAR_ONE} literally -- it must not be replaced with an
    empty string, removed, or modified.

    Arrange: Create a manifest with an undefined variable. Remove the variable
    from the environment.
    Act: Call EnvSubst() on the file.
    Assert: The output file contains the literal ${UNDEFINED_VAR_ONE} string.
    """
    manifest_path = tmp_path / "with_undefined.xml"
    manifest_path.write_text(_MANIFEST_WITH_DEFINED_AND_UNDEFINED, encoding="utf-8")

    cmd = _make_cmd()

    env = {k: v for k, v in os.environ.items() if k not in {"UNDEFINED_VAR_ONE", "UNDEFINED_VAR_TWO"}}
    env["DEFINED_VAR"] = "https://example.com/org/"

    with mock.patch.dict(os.environ, env, clear=True):
        cmd.EnvSubst(str(manifest_path))

    result_content = manifest_path.read_text(encoding="utf-8")
    assert "${UNDEFINED_VAR_ONE}" in result_content, (
        "Expected ${UNDEFINED_VAR_ONE} to be preserved literally in the output "
        f"manifest, but it was removed or expanded.\nOutput content:\n{result_content}"
    )
    assert "${UNDEFINED_VAR_TWO}" in result_content, (
        "Expected ${UNDEFINED_VAR_TWO} to be preserved literally in the output "
        f"manifest, but it was removed or expanded.\nOutput content:\n{result_content}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- Summary printed at end listing all unresolved variables
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_summary_printed_listing_all_unresolved_variables(tmp_path, caplog, capsys):
    """AC-TEST-003: Execute() must print a summary of all unresolved variables.

    When Execute() processes multiple files and some contain undefined ${VAR}
    patterns, it must print a summary at the end that lists all unresolved
    variable names found across all files.

    Arrange: Create two XML files. File one has UNDEFINED_FIRST; file two has
    UNDEFINED_SECOND. Both UNDEFINED_FIRST and UNDEFINED_SECOND are absent from
    the environment.
    Act: Call Execute() with both files via a patched glob.
    Assert: The output (stdout or a WARNING/INFO log record) includes both
    UNDEFINED_FIRST and UNDEFINED_SECOND as an unresolved summary.
    """
    file_one = tmp_path / "first.xml"
    file_two = tmp_path / "second.xml"

    file_one.write_text(_MANIFEST_WITH_TWO_UNDEFINED, encoding="utf-8")
    file_two.write_text(
        _MANIFEST_WITH_TWO_UNDEFINED.replace("UNDEFINED_FIRST", "UNDEFINED_ALPHA").replace(
            "UNDEFINED_SECOND", "UNDEFINED_BETA"
        ),
        encoding="utf-8",
    )

    cmd = _make_cmd()

    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"UNDEFINED_FIRST", "UNDEFINED_SECOND", "UNDEFINED_ALPHA", "UNDEFINED_BETA"}
    }

    with mock.patch("glob.glob", return_value=[str(file_one), str(file_two)]):
        with mock.patch("os.path.getsize", return_value=100):
            with mock.patch.dict(os.environ, env, clear=True):
                with caplog.at_level(logging.WARNING):
                    cmd.Execute(mock.MagicMock(), [])

    captured = capsys.readouterr()
    all_output = captured.out + captured.err

    all_messages = all_output + " ".join(r.message for r in caplog.records)

    assert "UNDEFINED_FIRST" in all_messages, (
        "Summary must mention UNDEFINED_FIRST as an unresolved variable, but it was not found in "
        f"stdout, stderr, or log records.\nOutput: {all_output!r}\n"
        f"Log records: {[r.message for r in caplog.records]!r}"
    )
    assert "UNDEFINED_SECOND" in all_messages, (
        "Summary must mention UNDEFINED_SECOND as an unresolved variable, but it was not found in "
        f"stdout, stderr, or log records.\nOutput: {all_output!r}\n"
        f"Log records: {[r.message for r in caplog.records]!r}"
    )
    assert "UNDEFINED_ALPHA" in all_messages, (
        "Summary must mention UNDEFINED_ALPHA as an unresolved variable from file two, but it was not found in "
        f"stdout, stderr, or log records.\nOutput: {all_output!r}\n"
        f"Log records: {[r.message for r in caplog.records]!r}"
    )
    assert "UNDEFINED_BETA" in all_messages, (
        "Summary must mention UNDEFINED_BETA as an unresolved variable from file two, but it was not found in "
        f"stdout, stderr, or log records.\nOutput: {all_output!r}\n"
        f"Log records: {[r.message for r in caplog.records]!r}"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-004 / AC-CYCLE-001 -- Command does not fail on unresolved variables
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_command_does_not_fail_on_unresolved_variables(tmp_path):
    """AC-FUNC-004: Execute() must not raise an exception for undefined variables.

    Unresolved ${VAR} patterns are a warning condition, not an error. Execute()
    must complete without raising any exception even when variables are undefined.

    Arrange: Create a manifest with an undefined variable. Remove it from env.
    Act: Call Execute() via patched glob.
    Assert: No exception is raised.
    """
    manifest_path = tmp_path / "undefined.xml"
    manifest_path.write_text(_MANIFEST_WITH_DEFINED_AND_UNDEFINED, encoding="utf-8")

    cmd = _make_cmd()

    env = {k: v for k, v in os.environ.items() if k not in {"UNDEFINED_VAR_ONE", "UNDEFINED_VAR_TWO"}}
    env["DEFINED_VAR"] = "https://example.com/org/"

    with mock.patch("glob.glob", return_value=[str(manifest_path)]):
        with mock.patch("os.path.getsize", return_value=100):
            with mock.patch.dict(os.environ, env, clear=True):
                # Must not raise -- undefined vars are warnings, not errors.
                cmd.Execute(mock.MagicMock(), [])


# ---------------------------------------------------------------------------
# AC-CYCLE-001 -- Full envsubst lifecycle: defined expanded, undefined preserved
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_envsubst_lifecycle_defined_expanded_undefined_preserved(tmp_path, caplog):
    """AC-CYCLE-001: Full lifecycle test with defined and undefined variables.

    Creates a manifest XML with ${DEFINED} and ${UNDEFINED} placeholders. Calls
    EnvSubst() with DEFINED set in env and UNDEFINED absent. Asserts:
    - DEFINED is expanded to its value in the output
    - UNDEFINED is preserved literally in the output
    - A WARNING is logged for UNDEFINED

    This is the end-to-end acceptance test for Bug 6.
    """
    manifest_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${DEFINED}" />
  <remote name="fallback" fetch="${UNDEFINED}" />
</manifest>
"""
    manifest_path = tmp_path / "lifecycle.xml"
    manifest_path.write_text(manifest_content, encoding="utf-8")

    cmd = _make_cmd()

    env = {k: v for k, v in os.environ.items() if k != "UNDEFINED"}
    env["DEFINED"] = "https://resolved.example.com/"

    with mock.patch.dict(os.environ, env, clear=True):
        with caplog.at_level(logging.WARNING):
            cmd.EnvSubst(str(manifest_path))

    result_content = manifest_path.read_text(encoding="utf-8")

    assert "https://resolved.example.com/" in result_content, (
        "Expected DEFINED to be expanded to 'https://resolved.example.com/' in the output, "
        f"but it was not found.\nOutput content:\n{result_content}"
    )
    assert "${DEFINED}" not in result_content, (
        "Expected ${DEFINED} placeholder to be replaced in output, "
        f"but it is still present.\nOutput content:\n{result_content}"
    )

    assert "${UNDEFINED}" in result_content, (
        "Expected ${UNDEFINED} to be preserved literally in the output, "
        f"but it was removed or expanded.\nOutput content:\n{result_content}"
    )

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING and "UNDEFINED" in r.message]
    assert warning_records, (
        "Expected a WARNING log record mentioning 'UNDEFINED' for the undefined variable, "
        f"but none found.\nAll log records: {[(r.levelno, r.message) for r in caplog.records]!r}"
    )


# ---------------------------------------------------------------------------
# Parametrized -- no warnings emitted when all variables are defined
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "manifest_content,env_additions",
    [
        (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest><remote name="a" fetch="${VAR_A}"/></manifest>',
            {"VAR_A": "val_a"},
        ),
        (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest><remote name="b" fetch="${VAR_B}" revision="${VAR_C}"/></manifest>',
            {"VAR_B": "val_b", "VAR_C": "val_c"},
        ),
    ],
    ids=["single_defined", "two_defined"],
)
def test_no_warnings_when_all_variables_defined(tmp_path, caplog, manifest_content, env_additions):
    """No WARNING logs must be emitted when all ${VAR} references are resolved.

    When expandvars() resolves every placeholder, no remaining ${...} patterns
    exist, and therefore no warnings should be logged for undefined variables.
    """
    manifest_path = tmp_path / "all_defined.xml"
    manifest_path.write_text(manifest_content, encoding="utf-8")

    cmd = _make_cmd()

    with mock.patch.dict(os.environ, env_additions):
        with caplog.at_level(logging.WARNING):
            cmd.EnvSubst(str(manifest_path))

    undefined_warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and "unresolved" in r.message.lower()
    ]
    assert not undefined_warnings, (
        "Expected no 'unresolved variable' WARNING records when all variables are defined, "
        f"but found: {[r.message for r in undefined_warnings]!r}"
    )
