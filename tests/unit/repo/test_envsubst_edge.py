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

"""Unit tests for envsubst edge cases.

Covers the following edge cases from parser-rules.tsv ENVSUBST-005..006 and
related documented behaviors:

  ENVSUBST-005  Undefined variable -- warns when a ${VAR} placeholder has no
                value in the environment; the placeholder is preserved in the
                output (no substitution takes place).
  ENVSUBST-006  Nested substitution -- ${${NESTED}} patterns warn and are left
                unchanged because os.path.expandvars() cannot resolve them.

Additional edge cases documented and tested:

  - $$ literal-dollar form -- two consecutive dollar signs pass through
    search_replace_placeholders unchanged.
  - ${VAR:-default} form -- the bash-style default-value syntax is NOT
    supported by os.path.expandvars(); the pattern is left in the output
    unchanged and no warning is emitted (explicitly rejected/unsupported).

All tests use the Envsubst subcommand directly (unit scope) without invoking
the CLI or any subprocess.

AC-TEST-001 undefined variable warns and placeholder is preserved
AC-TEST-002 nested substitution ${${NESTED}} warns and does not expand
AC-TEST-003 $$ literal-dollar form works
AC-TEST-004 ${VAR:-default} is explicitly rejected (not supported, not expanded)
"""

import logging
import os
import pathlib
from unittest import mock

import pytest

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


def _write_manifest(path: pathlib.Path, content: str) -> None:
    """Write manifest content to path with UTF-8 encoding."""
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# AC-TEST-001: Undefined variable warns and placeholder is preserved
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_undefined_variable_logs_warning(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-TEST-001 (warning side): EnvSubst() logs a WARNING for each undefined ${VAR}.

    When a manifest contains ${EDGE_UNDEF_VAR_AC001} and that variable is absent
    from the environment, EnvSubst() must emit a WARNING log record that names
    the undefined variable. This documents the ENVSUBST-005 warn-on-undefined
    behavior.

    Arrange: manifest with one defined and one undefined variable; undefined name
    is absent from os.environ.
    Act: call EnvSubst().
    Assert: at least one WARNING record mentions the undefined variable name.
    """
    undefined_var = "EDGE_UNDEF_VAR_AC001"
    defined_var = "EDGE_DEFINED_VAR_AC001"
    defined_value = "https://defined.example.com/repos"

    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="defined-remote" fetch="${{{defined_var}}}" />\n'
        f'  <remote name="undef-remote" fetch="${{{undefined_var}}}" />\n'
        '  <default revision="main" remote="defined-remote" />\n'
        "</manifest>\n"
    )
    manifest_path = tmp_path / "undef_warn.xml"
    _write_manifest(manifest_path, manifest_content)

    cmd = _make_cmd()
    env = {k: v for k, v in os.environ.items() if k != undefined_var}
    env[defined_var] = defined_value

    with mock.patch.dict(os.environ, env, clear=True):
        with caplog.at_level(logging.WARNING):
            cmd.EnvSubst(str(manifest_path))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    undef_warnings = [r for r in warning_records if undefined_var in r.message]
    assert undef_warnings, (
        f"Expected at least one WARNING log record containing {undefined_var!r} "
        "to indicate the undefined variable was detected, but none found.\n"
        f"All warning records: {[r.message for r in warning_records]!r}"
    )


@pytest.mark.unit
def test_undefined_variable_placeholder_preserved_in_output(tmp_path: pathlib.Path) -> None:
    """AC-TEST-001 (preservation side): undefined ${VAR} is preserved literally in output.

    When expandvars() cannot resolve ${EDGE_UNDEF_PRESERVE_AC001} (the variable
    is absent from the environment), the placeholder must remain in the written
    output file exactly as-is. It must not be replaced with an empty string or
    removed. This documents the no-substitution behavior: undefined vars warn
    and the placeholder is kept.

    Arrange: manifest with one undefined variable; variable absent from environ.
    Act: call EnvSubst().
    Assert: output file still contains the original placeholder text.
    """
    undefined_var = "EDGE_UNDEF_PRESERVE_AC001"
    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="${{{undefined_var}}}" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_path = tmp_path / "undef_preserve.xml"
    _write_manifest(manifest_path, manifest_content)

    cmd = _make_cmd()
    env = {k: v for k, v in os.environ.items() if k != undefined_var}

    with mock.patch.dict(os.environ, env, clear=True):
        cmd.EnvSubst(str(manifest_path))

    result = manifest_path.read_text(encoding="utf-8")
    assert f"${{{undefined_var}}}" in result, (
        f"Expected undefined placeholder ${{{undefined_var}}} to be preserved "
        "literally in the output manifest (no substitution when var is absent), "
        f"but it was not found.\nOutput content:\n{result}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "undefined_var_name",
    [
        "EDGE_UNDEF_SINGLE",
        "EDGE_UNDEF_WITH_NUMBERS_123",
        "EDGE_UNDEF_TRAILING_",
    ],
    ids=["single_word", "with_numbers", "trailing_underscore"],
)
def test_various_undefined_variable_names_warn(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
    undefined_var_name: str,
) -> None:
    """AC-TEST-001 (parametrized): different undefined variable name shapes all warn.

    Verifies that the WARNING for undefined variables is emitted for different
    identifier forms: letters only, with numbers, trailing underscore.

    Arrange: manifest with a single ${VAR} placeholder; variable absent from env.
    Act: call EnvSubst().
    Assert: WARNING record contains the specific variable name.
    """
    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="${{{undefined_var_name}}}" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_path = tmp_path / f"undef_{undefined_var_name}.xml"
    _write_manifest(manifest_path, manifest_content)

    cmd = _make_cmd()
    env = {k: v for k, v in os.environ.items() if k != undefined_var_name}

    with mock.patch.dict(os.environ, env, clear=True):
        with caplog.at_level(logging.WARNING):
            cmd.EnvSubst(str(manifest_path))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    var_warnings = [r for r in warning_records if undefined_var_name in r.message]
    assert var_warnings, (
        f"Expected a WARNING log record containing {undefined_var_name!r}, "
        "but none found.\n"
        f"All warning records: {[r.message for r in warning_records]!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-002: Nested substitution ${${NESTED}} warns and does not expand
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_nested_substitution_logs_warning(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-TEST-002 (warning side): EnvSubst() logs a WARNING for ${${NESTED}} patterns.

    The pattern ${${NESTED_INNER}} contains an inner ${...} inside the outer
    ${...}. os.path.expandvars() cannot resolve such patterns and leaves them
    unchanged. The implementation must detect and warn about each occurrence.

    Arrange: manifest with a ${${NESTED_INNER}} placeholder in a fetch attribute.
    Act: call EnvSubst().
    Assert: at least one WARNING record mentions the full nested pattern text.
    """
    nested_pattern = "${${NESTED_INNER}}"
    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{nested_pattern}" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_path = tmp_path / "nested_warn.xml"
    _write_manifest(manifest_path, manifest_content)

    cmd = _make_cmd()

    with caplog.at_level(logging.WARNING):
        cmd.EnvSubst(str(manifest_path))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    nested_warnings = [r for r in warning_records if nested_pattern in r.message]
    assert nested_warnings, (
        f"Expected at least one WARNING log record containing the full nested "
        f"pattern {nested_pattern!r}, but none found.\n"
        f"All warning records: {[r.message for r in warning_records]!r}"
    )


@pytest.mark.unit
def test_nested_substitution_not_expanded(tmp_path: pathlib.Path) -> None:
    """AC-TEST-002 (no-expand side): ${${NESTED}} pattern is left unchanged in output.

    os.path.expandvars() cannot resolve ${${NESTED_INNER}} patterns. The
    implementation must NOT attempt to partially resolve them. The full nested
    pattern must survive in the written output file unchanged.

    Arrange: manifest with ${${NESTED_INNER}} in a fetch attribute.
    Act: call EnvSubst().
    Assert: output file still contains the original ${${NESTED_INNER}} text.
    """
    nested_pattern = "${${NESTED_INNER}}"
    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{nested_pattern}" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_path = tmp_path / "nested_noexpand.xml"
    _write_manifest(manifest_path, manifest_content)

    cmd = _make_cmd()
    cmd.EnvSubst(str(manifest_path))

    result = manifest_path.read_text(encoding="utf-8")
    assert nested_pattern in result, (
        f"Expected the nested pattern {nested_pattern!r} to remain unchanged "
        "in the output manifest (expandvars cannot resolve nested patterns), "
        f"but it was not found.\nOutput content:\n{result}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "nested_pattern",
    [
        "${${NESTED}}",
        "${BASE_${ENV}_URL}",
        "${PREFIX_${REGION}}",
    ],
    ids=["pure_nested", "base_env_url", "prefix_region"],
)
def test_nested_patterns_each_warn(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
    nested_pattern: str,
) -> None:
    """AC-TEST-002 (parametrized): multiple nested-pattern shapes all produce warnings.

    Each variety of nested ${...${...}...} pattern must trigger a WARNING
    regardless of the specific text around the inner ${...}.

    Arrange: manifest containing the given nested_pattern in a fetch attribute.
    Act: call EnvSubst().
    Assert: at least one WARNING record contains the nested_pattern text.
    """
    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{nested_pattern}" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_path = tmp_path / "nested_param.xml"
    _write_manifest(manifest_path, manifest_content)

    cmd = _make_cmd()

    with caplog.at_level(logging.WARNING):
        cmd.EnvSubst(str(manifest_path))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    pattern_warnings = [r for r in warning_records if nested_pattern in r.message]
    assert pattern_warnings, (
        f"Expected a WARNING log record containing nested pattern {nested_pattern!r}, "
        "but none found.\n"
        f"All warning records: {[r.message for r in warning_records]!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-003: $$ literal-dollar form works
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_double_dollar_preserved_in_output(tmp_path: pathlib.Path) -> None:
    """AC-TEST-003: EnvSubst() preserves $$ sequences unchanged in the output file.

    The $$ form is not a valid environment variable reference; os.path.expandvars()
    on POSIX leaves $$ intact. The envsubst command must pass $$ through without
    corruption -- it must appear in the written output exactly as in the input.

    Arrange: manifest with an attribute containing prefix$$suffix.
    Act: call EnvSubst() on the manifest file.
    Assert: output file contains '$$' at the expected location.
    """
    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <project name="proj" path="proj" remote="origin"'
        ' annotation="prefix$$suffix" />\n'
        "</manifest>\n"
    )
    manifest_path = tmp_path / "double_dollar.xml"
    _write_manifest(manifest_path, manifest_content)

    cmd = _make_cmd()
    cmd.EnvSubst(str(manifest_path))

    result = manifest_path.read_text(encoding="utf-8")
    assert "$$" in result, (
        "Expected the '$$' sequence to be preserved in the output manifest "
        "(os.path.expandvars leaves $$ intact on POSIX), but it was not found.\n"
        f"Output content:\n{result}"
    )


@pytest.mark.unit
def test_double_dollar_does_not_trigger_unresolved_warning(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-TEST-003: $$ does not trigger any unresolved-variable WARNING.

    Because '$$' does not match the ${IDENTIFIER} pattern, _collect_unresolved_vars
    must not flag it as an unresolved variable. No WARNING record must mention
    '$$' in the context of an unresolved variable.

    Arrange: manifest with '$$' in an attribute value; no other placeholders.
    Act: call EnvSubst().
    Assert: no WARNING record is emitted that mentions 'unresolved' together with '$$'.
    """
    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <project name="proj" path="proj" remote="origin"'
        ' annotation="cost$$total" />\n'
        "</manifest>\n"
    )
    manifest_path = tmp_path / "double_dollar_nowarn.xml"
    _write_manifest(manifest_path, manifest_content)

    cmd = _make_cmd()

    with caplog.at_level(logging.WARNING):
        cmd.EnvSubst(str(manifest_path))

    unresolved_warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and "unresolved" in r.message.lower()
    ]
    assert not unresolved_warnings, (
        "Expected no 'unresolved variable' WARNING when the only dollar-sequence "
        "is '$$' (which is not a variable placeholder), but found:\n"
        f"{[r.message for r in unresolved_warnings]!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "annotation_value,expected_in_output",
    [
        ("prefix$$suffix", "$$"),
        ("$$only", "$$"),
        ("a$$b$$c", "$$"),
    ],
    ids=["middle", "start", "multiple"],
)
def test_double_dollar_shapes_preserved(
    tmp_path: pathlib.Path,
    annotation_value: str,
    expected_in_output: str,
) -> None:
    """AC-TEST-003 (parametrized): multiple $$ placement shapes all survive envsubst.

    Verifies that $$ at the start, middle, and repeated positions within an
    attribute value are all preserved by search_replace_placeholders.

    Arrange: manifest with the given annotation_value containing $$.
    Act: call EnvSubst().
    Assert: output contains the expected_in_output marker.
    """
    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        f'  <project name="proj" path="proj" remote="origin"'
        f' annotation="{annotation_value}" />\n'
        "</manifest>\n"
    )
    manifest_path = tmp_path / f"double_dollar_{annotation_value[:6]}.xml"
    _write_manifest(manifest_path, manifest_content)

    cmd = _make_cmd()
    cmd.EnvSubst(str(manifest_path))

    result = manifest_path.read_text(encoding="utf-8")
    assert expected_in_output in result, (
        f"Expected {expected_in_output!r} to be preserved in the output manifest "
        f"for annotation value {annotation_value!r}, but it was not found.\n"
        f"Output content:\n{result}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-004: ${VAR:-default} is explicitly rejected (not supported)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_default_value_syntax_not_expanded(tmp_path: pathlib.Path) -> None:
    """AC-TEST-004 (no-expand side): ${VAR:-default} is NOT expanded by envsubst.

    os.path.expandvars() does not support the bash-style ${VAR:-default}
    (use-default-if-unset) syntax. The pattern is left unchanged in the output.
    The envsubst command does not implement this form; callers must not rely on
    it being expanded.

    Arrange: manifest with ${EDGE_VAR_DEFAULT:-fallback} in a fetch attribute;
    EDGE_VAR_DEFAULT absent from the environment.
    Act: call EnvSubst().
    Assert: output contains the literal text '${EDGE_VAR_DEFAULT:-fallback}'
    unchanged.
    """
    default_placeholder = "${EDGE_VAR_DEFAULT:-fallback}"
    var_name = "EDGE_VAR_DEFAULT"

    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{default_placeholder}" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_path = tmp_path / "default_syntax.xml"
    _write_manifest(manifest_path, manifest_content)

    cmd = _make_cmd()
    env = {k: v for k, v in os.environ.items() if k != var_name}

    with mock.patch.dict(os.environ, env, clear=True):
        cmd.EnvSubst(str(manifest_path))

    result = manifest_path.read_text(encoding="utf-8")
    assert default_placeholder in result, (
        f"Expected the unsupported placeholder {default_placeholder!r} to be "
        "preserved literally in the output (${VAR:-default} is not supported by "
        "os.path.expandvars), but it was absent or modified.\n"
        f"Output content:\n{result}"
    )


@pytest.mark.unit
def test_default_value_syntax_no_unresolved_warning(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-TEST-004 (no-warning side): ${VAR:-default} does NOT trigger an unresolved warning.

    The _UNRESOLVED_PATTERN regex only matches ${IDENTIFIER} where the content
    is a valid identifier ([A-Za-z_][A-Za-z0-9_]*). The bash-style colon-dash
    suffix ':-default' does not match this pattern, so no warning is emitted
    for the variable name.

    This documents the explicitly-rejected behavior: ${VAR:-default} is silently
    passed through without expansion and without a warning. Callers must be aware
    that this form is unsupported.

    Arrange: manifest with ${EDGE_DEFAULT_WARN:-value}; variable absent from env.
    Act: call EnvSubst().
    Assert: no WARNING record names 'EDGE_DEFAULT_WARN' as an unresolved var.
    """
    var_name = "EDGE_DEFAULT_WARN"
    default_placeholder = f"${{{var_name}:-value}}"

    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{default_placeholder}" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_path = tmp_path / "default_nowarn.xml"
    _write_manifest(manifest_path, manifest_content)

    cmd = _make_cmd()
    env = {k: v for k, v in os.environ.items() if k != var_name}

    with mock.patch.dict(os.environ, env, clear=True):
        with caplog.at_level(logging.WARNING):
            cmd.EnvSubst(str(manifest_path))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    unresolved_warnings = [r for r in warning_records if var_name in r.message and "unresolved" in r.message.lower()]
    assert not unresolved_warnings, (
        f"Expected no 'unresolved variable' WARNING for {var_name!r} when using "
        "the unsupported ${VAR:-default} syntax (the _UNRESOLVED_PATTERN does not "
        "match non-identifier content inside the braces), but warnings were found:\n"
        f"{[r.message for r in unresolved_warnings]!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "default_placeholder,var_name",
    [
        ("${EDGE_VAR_A:-default_a}", "EDGE_VAR_A"),
        ("${EDGE_VAR_B:-}", "EDGE_VAR_B"),
        ("${EDGE_VAR_C:-https://fallback.example.com}", "EDGE_VAR_C"),
    ],
    ids=["word_default", "empty_default", "url_default"],
)
def test_various_default_forms_all_preserved(
    tmp_path: pathlib.Path,
    default_placeholder: str,
    var_name: str,
) -> None:
    """AC-TEST-004 (parametrized): multiple ${VAR:-default} variants all preserved as-is.

    Verifies that the unsupported behavior is consistent across different default
    value shapes: simple word, empty default, URL as default. Each pattern must
    survive in the output manifest without modification.

    Arrange: manifest with the given default_placeholder; variable absent from env.
    Act: call EnvSubst().
    Assert: output contains the original literal placeholder unchanged.
    """
    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{default_placeholder}" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    manifest_path = tmp_path / f"default_param_{var_name}.xml"
    _write_manifest(manifest_path, manifest_content)

    cmd = _make_cmd()
    env = {k: v for k, v in os.environ.items() if k != var_name}

    with mock.patch.dict(os.environ, env, clear=True):
        cmd.EnvSubst(str(manifest_path))

    result = manifest_path.read_text(encoding="utf-8")
    assert default_placeholder in result, (
        f"Expected unsupported placeholder {default_placeholder!r} to be preserved "
        "literally in the output (${VAR:-default} is not supported by envsubst), "
        f"but it was absent or modified.\nOutput content:\n{result}"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001: envsubst edge cases documented and tested
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_edge_cases_channel_discipline(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """AC-FUNC-001 + AC-CHANNEL-001: edge cases produce no direct stderr leakage.

    Exercises multiple edge cases in a single manifest processed by EnvSubst():
    - undefined variable (warns via logging subsystem, not raw stderr)
    - $$ sequence (passes through unchanged)
    - ${VAR:-default} form (preserved unchanged)

    After processing, verifies that no text is written directly to stderr by
    EnvSubst(). Warnings must go through the logging subsystem, not print().

    AC-CHANNEL-001: stdout vs stderr discipline -- warnings must NOT be written
    directly to stderr via print(); they must use the logging subsystem so
    callers can redirect or suppress them via standard logging configuration.
    """
    undefined_var = "EDGE_CHANNEL_UNDEF"
    default_pattern = "${EDGE_DEFAULT_CH:-fallback}"

    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="${{{undefined_var}}}" />\n'
        '  <remote name="plain" fetch="https://plain.example.com" />\n'
        '  <project name="proj" path="proj" remote="plain" annotation="pre$$post" />\n'
        f'  <project name="dp" path="dp" remote="plain" annotation="{default_pattern}" />\n'
        "</manifest>\n"
    )
    manifest_path = tmp_path / "channel_test.xml"
    _write_manifest(manifest_path, manifest_content)

    cmd = _make_cmd()
    env = {k: v for k, v in os.environ.items() if k not in {undefined_var, "EDGE_DEFAULT_CH"}}

    with mock.patch.dict(os.environ, env, clear=True):
        cmd.EnvSubst(str(manifest_path))

    captured = capsys.readouterr()
    assert captured.err == "", (
        "Expected no direct stderr output from EnvSubst() -- warnings must use "
        "the logging subsystem, not print() to stderr.\n"
        f"Stderr content: {captured.err!r}"
    )

    result = manifest_path.read_text(encoding="utf-8")
    assert "$$" in result, (
        f"Expected '$$' to be preserved in the output manifest after EnvSubst().\nOutput content:\n{result}"
    )
    assert default_pattern in result, (
        f"Expected unsupported default pattern {default_pattern!r} to be preserved "
        "in the output manifest after EnvSubst().\n"
        f"Output content:\n{result}"
    )
