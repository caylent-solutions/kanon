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

"""Unit tests for envsubst basic semantics.

Covers the three documented basic forms of environment variable substitution
defined in parser-rules.tsv ENVSUBST-001..004:

  ENVSUBST-001  $VAR form -- bare dollar sign without braces
  ENVSUBST-002  ${VAR} form -- dollar sign with curly-brace delimiters
  ENVSUBST-003  Escaped $$ -- two consecutive dollar signs pass through unchanged
  ENVSUBST-004  Linkfile abs dest -- absolute dest path accepted after substitution

All tests use the Envsubst subcommand directly (unit scope) without invoking
the CLI or any subprocess.
"""

import os
import pathlib
from unittest import mock
from xml.dom import minidom

import pytest

from kanon_cli.repo.manifest_xml import XmlManifest
from kanon_cli.repo.subcmds.envsubst import Envsubst


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cmd() -> Envsubst:
    """Return an Envsubst instance ready for direct method calls.

    Bypasses the Command __init__ parent chain so the instance can be used
    without a live repo or manifest on disk.
    """
    cmd = Envsubst.__new__(Envsubst)
    cmd.manifest = mock.MagicMock()
    return cmd


def _parse_xml(xml_text: str):
    """Parse raw XML text and return a minidom Document."""
    return minidom.parseString(xml_text.encode("utf-8"))


def _make_manifest_dir(base: pathlib.Path) -> pathlib.Path:
    """Create the .repo/manifests/ directory structure under base."""
    manifests_dir = base / ".repo" / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    return manifests_dir


# ---------------------------------------------------------------------------
# AC-TEST-001: $VAR and ${VAR} both substitute (ENVSUBST-001 + ENVSUBST-002)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "placeholder, var_name, expected_value",
    [
        pytest.param(
            "$ENVSUBST_BASIC_BARE",
            "ENVSUBST_BASIC_BARE",
            "https://bare.example.com/repos",
            id="bare_dollar_var_form",
        ),
        pytest.param(
            "${ENVSUBST_BASIC_BRACE}",
            "ENVSUBST_BASIC_BRACE",
            "https://brace.example.com/repos",
            id="dollar_brace_var_form",
        ),
    ],
)
def test_dollar_var_and_brace_var_both_substitute(
    tmp_path: pathlib.Path,
    placeholder: str,
    var_name: str,
    expected_value: str,
) -> None:
    """AC-TEST-001: Both $VAR and ${VAR} are resolved by search_replace_placeholders.

    ENVSUBST-001 ($VAR) and ENVSUBST-002 (${VAR}) must both produce the
    resolved environment variable value when the variable is present in
    os.environ. The resulting attribute value must equal the injected value
    and must not contain the original placeholder text.

    Parametrized to cover both syntactic forms in a single test function.
    """
    xml_input = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{placeholder}" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    doc = _parse_xml(xml_input)
    cmd = _make_cmd()

    with mock.patch.dict(os.environ, {var_name: expected_value}):
        cmd.search_replace_placeholders(doc)

    remote = doc.getElementsByTagName("remote")[0]
    actual_fetch = remote.getAttribute("fetch")

    assert actual_fetch == expected_value, (
        f"Expected fetch attribute to equal {expected_value!r} after resolving "
        f"placeholder {placeholder!r}, but got {actual_fetch!r}."
    )
    assert placeholder not in actual_fetch, (
        f"Expected placeholder {placeholder!r} to be absent from the fetch "
        f"attribute after substitution, but it is still present: {actual_fetch!r}."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002: $$ produces a literal $ (ENVSUBST-003)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_double_dollar_preserved_as_literal_dollar_signs() -> None:
    """AC-TEST-002: A $$ sequence in an attribute value is preserved unchanged.

    ENVSUBST-003 documents that $$ is an escaped dollar sign form. Through
    os.path.expandvars on POSIX, $$ is left intact (two dollar signs) because
    it does not match the variable-reference syntax. The envsubst command must
    not corrupt this sequence -- it must still be present in the output DOM
    attribute exactly as it was in the input.
    """
    xml_input = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <project name="proj" path="proj" remote="origin"'
        ' annotation="prefix$$suffix" />\n'
        "</manifest>\n"
    )
    doc = _parse_xml(xml_input)
    cmd = _make_cmd()

    cmd.search_replace_placeholders(doc)

    project = doc.getElementsByTagName("project")[0]
    actual_annotation = project.getAttribute("annotation")

    assert "$$" in actual_annotation, (
        f"Expected '$$' to be preserved in the annotation attribute after "
        f"search_replace_placeholders, but it was not found. "
        f"Actual value: {actual_annotation!r}."
    )
    assert actual_annotation == "prefix$$suffix", (
        f"Expected annotation attribute to be 'prefix$$suffix' after processing "
        f"($$  must not be corrupted), but got {actual_annotation!r}."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003: linkfile absolute dest after substitution is accepted (ENVSUBST-004)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_linkfile_absolute_dest_after_substitution_is_accepted(
    tmp_path: pathlib.Path,
) -> None:
    """AC-TEST-003: An absolute dest path resulting from ${VAR} substitution is accepted.

    ENVSUBST-004 covers the linkfile absolute dest pattern documented in
    manifest-format.md (lines 505-509). When a linkfile dest attribute contains
    ${VAR} and the variable resolves to an absolute filesystem path, the
    resulting value must be accepted by _ValidateFilePaths (abs_ok=True applies
    to linkfile dest paths).

    This test:
      1. Calls EnvSubst() on a manifest file with a linkfile whose dest is
         a ${VAR} placeholder.
      2. Sets the variable to a valid absolute path.
      3. Reads the resulting file and verifies:
         - The placeholder is replaced with the absolute path.
         - The absolute path is present in the output.
      4. Calls _ValidateFilePaths directly to confirm the resolved path is
         accepted with abs_ok=True (the same check performed at parse time).
    """
    abs_dest_value = "/opt/my-install-dir/settings.yml"
    env_var_name = "ENVSUBST_BASIC_ABS_DEST_DIR"

    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="myproject" path="myproject">\n'
        f'    <linkfile src="config/settings.yml" dest="${{{env_var_name}}}/settings.yml" />\n'
        "  </project>\n"
        "</manifest>\n"
    )
    manifests_dir = _make_manifest_dir(tmp_path)
    manifest_path = manifests_dir / "default.xml"
    manifest_path.write_text(manifest_content, encoding="utf-8")

    cmd = _make_cmd()
    # Resolve: ${ENVSUBST_BASIC_ABS_DEST_DIR}/settings.yml => /opt/my-install-dir/settings.yml
    abs_dir_value = "/opt/my-install-dir"

    with mock.patch.dict(os.environ, {env_var_name: abs_dir_value}):
        cmd.EnvSubst(str(manifest_path))

    result_content = manifest_path.read_text(encoding="utf-8")

    assert abs_dest_value in result_content, (
        f"Expected the resolved absolute dest path {abs_dest_value!r} to appear "
        f"in the manifest after envsubst, but it was not found.\n"
        f"Manifest content:\n{result_content}"
    )
    assert f"${{{env_var_name}}}" not in result_content, (
        f"Expected placeholder ${{{env_var_name}}} to be removed from the manifest "
        f"after substitution, but it is still present.\n"
        f"Manifest content:\n{result_content}"
    )

    # Verify that the resolved absolute path passes the same validation used at
    # manifest parse time for linkfile dest attributes (abs_ok=True).
    validation_result = XmlManifest._CheckLocalPath(abs_dest_value, abs_ok=True)
    assert validation_result is None, (
        f"Expected _CheckLocalPath to accept the resolved absolute dest path "
        f"{abs_dest_value!r} (abs_ok=True), but it returned an error: {validation_result!r}."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001: envsubst handles the three documented basic forms
# AC-CHANNEL-001: stdout vs stderr discipline (no cross-channel leakage)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_envsubst_handles_three_documented_basic_forms(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """AC-FUNC-001 + AC-CHANNEL-001: All three basic forms work; stdout is clean.

    Exercises $VAR (ENVSUBST-001), ${VAR} (ENVSUBST-002), and $$ pass-through
    (ENVSUBST-003) in a single manifest file processed by EnvSubst(). After
    processing:

    - The $VAR placeholder is replaced with its value.
    - The ${VAR} placeholder is replaced with its value.
    - The $$ sequence is preserved unchanged.
    - No error output appears on stderr (AC-CHANNEL-001).
    - No unexpected text leaks from stderr onto stdout.
    """
    bare_var_name = "ENVSUBST_BASIC_COMBINED_BARE"
    brace_var_name = "ENVSUBST_BASIC_COMBINED_BRACE"
    bare_value = "https://bare-combined.example.com"
    brace_value = "https://brace-combined.example.com"

    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="bare-remote" fetch="${bare_var_name}" />\n'
        f'  <remote name="brace-remote" fetch="${{{brace_var_name}}}" />\n'
        '  <project name="proj" path="proj" remote="bare-remote"'
        ' annotation="prefix$$suffix" />\n'
        "</manifest>\n"
    )
    manifests_dir = _make_manifest_dir(tmp_path)
    manifest_path = manifests_dir / "default.xml"
    manifest_path.write_text(manifest_content, encoding="utf-8")

    cmd = _make_cmd()
    env = {bare_var_name: bare_value, brace_var_name: brace_value}

    with mock.patch.dict(os.environ, env):
        cmd.EnvSubst(str(manifest_path))

    result_content = manifest_path.read_text(encoding="utf-8")

    # ENVSUBST-001: bare $VAR form resolved
    assert bare_value in result_content, (
        f"Expected bare $VAR resolved value {bare_value!r} in manifest, "
        f"but it was not found.\nManifest content:\n{result_content}"
    )
    assert f"${bare_var_name}" not in result_content, (
        f"Expected bare placeholder ${bare_var_name} to be replaced, "
        f"but it is still present.\nManifest content:\n{result_content}"
    )

    # ENVSUBST-002: ${VAR} form resolved
    assert brace_value in result_content, (
        f"Expected brace ${{VAR}} resolved value {brace_value!r} in manifest, "
        f"but it was not found.\nManifest content:\n{result_content}"
    )
    assert f"${{{brace_var_name}}}" not in result_content, (
        f"Expected brace placeholder ${{{brace_var_name}}} to be replaced, "
        f"but it is still present.\nManifest content:\n{result_content}"
    )

    # ENVSUBST-003: $$ sequence preserved
    assert "$$" in result_content, (
        f"Expected '$$' to be preserved in the annotation attribute, "
        f"but it was not found.\nManifest content:\n{result_content}"
    )

    # AC-CHANNEL-001: nothing unexpected on stderr
    captured = capsys.readouterr()
    assert captured.err == "", f"Expected no output on stderr after EnvSubst(), but got:\n{captured.err!r}"
