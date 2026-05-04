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

"""Unit tests for Bug 18: envsubst XML save uses inefficient double-parse.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 18 -- The current save() method
calls toprettyxml() then re-parses the output with parseString() to filter
empty lines. This is a double XML parse. The fix replaces the second parse with
string-based line filtering that achieves the same result in a single pass.
"""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds.envsubst import Envsubst


# ---------------------------------------------------------------------------
# XML fixtures
# ---------------------------------------------------------------------------

_SIMPLE_MANIFEST = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${GITBASE}" />
  <default revision="main" remote="origin" />
  <project name="myproject" path="myproject" />
</manifest>
"""

_MANIFEST_WITH_VAR = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${GITBASE}" />
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
# AC-TEST-003 -- Single-pass substitution produces correct output
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_single_pass_substitution_produces_correct_output(tmp_path):
    """AC-TEST-003: EnvSubst() must expand ${VAR} references and write the
    result to the output file in a single pass without double XML parsing.

    After EnvSubst() processes a file, the output file must contain the
    expanded variable value and must not contain the original placeholder.
    This verifies the substitution is functionally correct regardless of
    whether the implementation is XML-based or string-based.

    Arrange: Create a manifest with ${GITBASE} placeholder. Set GITBASE in env.
    Act: Call EnvSubst() on the file.
    Assert: The output file contains the resolved URL, not the placeholder.
    """
    manifest_path = tmp_path / "manifest.xml"
    manifest_path.write_text(_MANIFEST_WITH_VAR, encoding="utf-8")

    cmd = _make_cmd()
    expected_url = "https://github.com/org/"

    with mock.patch.dict("os.environ", {"GITBASE": expected_url}):
        cmd.EnvSubst(str(manifest_path))

    result = manifest_path.read_text(encoding="utf-8")

    assert expected_url in result, (
        f"Expected the resolved URL {expected_url!r} to appear in the output file, "
        f"but it was not found.\nOutput content:\n{result}"
    )
    assert "${GITBASE}" not in result, (
        "Expected the ${GITBASE} placeholder to be replaced in the output, "
        f"but it is still present.\nOutput content:\n{result}"
    )


@pytest.mark.unit
def test_output_file_contains_no_blank_lines(tmp_path):
    """The output file written by EnvSubst() must not contain blank lines.

    The previous double-parse approach used parseString() to filter empty
    lines from toprettyxml() output. The fix must achieve the same result
    (no blank lines) using string manipulation rather than a second XML parse.

    Arrange: Create a valid manifest XML file.
    Act: Call EnvSubst() on the file.
    Assert: The output file has no blank (empty or whitespace-only) lines.
    """
    manifest_path = tmp_path / "manifest.xml"
    manifest_path.write_text(_SIMPLE_MANIFEST, encoding="utf-8")

    cmd = _make_cmd()

    cmd.EnvSubst(str(manifest_path))

    result = manifest_path.read_text(encoding="utf-8")
    lines = result.splitlines()
    blank_lines = [i + 1 for i, line in enumerate(lines) if not line.strip()]
    assert not blank_lines, (
        f"Expected no blank lines in the output file, but found blank lines "
        f"at line numbers: {blank_lines}\nFull output:\n{result}"
    )


@pytest.mark.unit
def test_parsestring_not_in_envsubst_module_namespace():
    """parseString must not be available in the envsubst module's namespace
    (double-parse fix).

    The bug was that save() called parseString() to filter blank lines from
    toprettyxml() output, requiring 'from xml.dom.minidom import parseString'.
    The fix replaces the second parse with string-based filtering, so the
    parseString import is removed.

    This test verifies that 'parseString' is no longer a name in the envsubst
    module's namespace, confirming the import has been removed.
    """
    import kanon_cli.repo.subcmds.envsubst as envsubst_module

    assert not hasattr(envsubst_module, "parseString"), (
        "The envsubst module must not export 'parseString' after the double-parse "
        "fix (Bug 18). Found 'parseString' in the module's namespace, which "
        "indicates 'from xml.dom.minidom import parseString' is still present."
    )
