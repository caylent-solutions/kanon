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

"""Unit tests for Bug 16: nested variable reference not detected in envsubst.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 16 -- os.path.expandvars() does
not support ${OUTER${INNER}} patterns. These are left unchanged silently. The
fix detects patterns like ${VAR_${INNER}} (nested ${...} inside ${...}) and
logs a WARNING per occurrence including the full nested pattern text. The tool
does not attempt to resolve nested variables.
"""

import logging
import re
from unittest import mock

import pytest

from kanon_cli.repo.subcmds.envsubst import Envsubst


# ---------------------------------------------------------------------------
# XML fixtures with nested variable references
# ---------------------------------------------------------------------------

_MANIFEST_WITH_NESTED_VAR = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${VAR_${INNER}}" />
  <default revision="main" remote="origin" />
</manifest>
"""

_MANIFEST_WITHOUT_NESTED_VAR = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${PLAIN_VAR}" />
  <default revision="main" remote="origin" />
</manifest>
"""

_MANIFEST_WITH_MULTIPLE_NESTED_VARS = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${BASE_${ENV}_URL}" />
  <remote name="backup" fetch="${BACKUP_${REGION}_HOST}" />
  <default revision="main" remote="origin" />
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
# AC-TEST-001 -- Warning logged when nested variable pattern is detected
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_warning_logged_for_nested_variable_pattern(tmp_path, caplog):
    """AC-TEST-001: EnvSubst() must log a WARNING when a nested ${...${...}} pattern
    is found in an XML manifest file.

    Nested variable references like ${VAR_${INNER}} cannot be resolved by
    os.path.expandvars(). The fix must detect these patterns and log a warning
    per occurrence so the user knows which patterns require attention.

    Arrange: Create a manifest with a nested variable reference ${VAR_${INNER}}.
    Act: Call EnvSubst() on the file.
    Assert: At least one WARNING log record exists indicating a nested pattern
    was detected.
    """
    manifest_path = tmp_path / "nested.xml"
    manifest_path.write_text(_MANIFEST_WITH_NESTED_VAR, encoding="utf-8")

    cmd = _make_cmd()

    with caplog.at_level(logging.WARNING):
        cmd.EnvSubst(str(manifest_path))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    # A nested-variable warning must mention the full nested pattern, not just
    # the inner variable name that the plain unresolved-var scan would catch.
    nested_warnings = [r for r in warning_records if "${VAR_${INNER}}" in r.message]
    assert nested_warnings, (
        "Expected at least one WARNING log record containing the full nested "
        "pattern '${VAR_${INNER}}' to indicate a nested variable was detected, "
        "but none found.\n"
        f"All warning records: {[r.message for r in warning_records]!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- Warning message includes the full nested pattern text
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_warning_includes_full_nested_pattern_text(tmp_path, caplog):
    """AC-TEST-002: The WARNING logged for a nested variable must include the full
    nested pattern text (e.g., '${VAR_${INNER}}') so the user can identify it.

    Arrange: Create a manifest with the nested pattern ${VAR_${INNER}}.
    Act: Call EnvSubst() on the file.
    Assert: At least one WARNING log record contains the full pattern text
    '${VAR_${INNER}}'.
    """
    manifest_path = tmp_path / "nested.xml"
    manifest_path.write_text(_MANIFEST_WITH_NESTED_VAR, encoding="utf-8")

    cmd = _make_cmd()

    with caplog.at_level(logging.WARNING):
        cmd.EnvSubst(str(manifest_path))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    pattern_in_warning = any("${VAR_${INNER}}" in r.message for r in warning_records)
    assert pattern_in_warning, (
        "Expected at least one WARNING log record containing the full nested "
        "pattern '${VAR_${INNER}}', but none found.\n"
        f"All warning records: {[r.message for r in warning_records]!r}"
    )


# ---------------------------------------------------------------------------
# No warning for plain (non-nested) variable references
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_nested_warning_for_plain_variable_references(tmp_path, caplog):
    """No nested-variable WARNING must be emitted for plain ${VAR} references.

    Plain ${VAR} references that do not contain a second ${...} inside are
    not nested and must not trigger the nested-variable warning.

    Arrange: Create a manifest with only plain ${PLAIN_VAR} references.
    Act: Call EnvSubst() on the file with PLAIN_VAR defined.
    Assert: No WARNING log record mentions 'nested' or nested pattern syntax.
    """
    manifest_path = tmp_path / "plain.xml"
    manifest_path.write_text(_MANIFEST_WITHOUT_NESTED_VAR, encoding="utf-8")

    cmd = _make_cmd()

    with mock.patch.dict("os.environ", {"PLAIN_VAR": "https://example.com/"}):
        with caplog.at_level(logging.WARNING):
            cmd.EnvSubst(str(manifest_path))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    # A nested-variable warning must contain a pattern with nested ${...${...}}.
    # A plain ${PLAIN_VAR} reference must not produce such a warning.
    # Check that no warning message contains a nested ${...${...} pattern.
    multi_brace_warnings = [r for r in warning_records if re.search(r"\$\{[^}]*\$\{", r.message)]
    assert not multi_brace_warnings, (
        "Expected no nested-variable WARNING for plain ${PLAIN_VAR} references, "
        f"but found: {[r.message for r in multi_brace_warnings]!r}"
    )


# ---------------------------------------------------------------------------
# Parametrized -- multiple nested patterns each produce a warning
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "nested_pattern",
    [
        "${BASE_${ENV}_URL}",
        "${BACKUP_${REGION}_HOST}",
    ],
    ids=["base_env_url", "backup_region_host"],
)
def test_each_nested_pattern_produces_warning(tmp_path, caplog, nested_pattern):
    """Each distinct nested variable pattern must produce its own warning.

    When a manifest contains multiple nested references, each nested pattern
    text must appear in at least one WARNING log record.

    Arrange: Create a manifest with two nested variable patterns.
    Act: Call EnvSubst() on the file.
    Assert: A WARNING record containing the specific nested_pattern text exists.
    """
    manifest_path = tmp_path / "multi_nested.xml"
    manifest_path.write_text(_MANIFEST_WITH_MULTIPLE_NESTED_VARS, encoding="utf-8")

    cmd = _make_cmd()

    with caplog.at_level(logging.WARNING):
        cmd.EnvSubst(str(manifest_path))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    pattern_in_warning = any(nested_pattern in r.message for r in warning_records)
    assert pattern_in_warning, (
        f"Expected a WARNING log record containing nested pattern {nested_pattern!r}, "
        f"but none found.\nAll warning records: {[r.message for r in warning_records]!r}"
    )
