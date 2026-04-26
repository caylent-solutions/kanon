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

"""Regression guard for E0-F6-S2-T2: undefined env vars silently preserved.

Bug reference: E0-F6-S2-T2 / Bug 6 -- after expandvars() processes an XML
manifest file, any ${VARIABLE} patterns that remain in the output indicate
environment variables that were not defined in the calling process. Before the
fix, these unresolved placeholders were silently written back to the output
file with no indication to the user that substitution was incomplete.

Root cause: subcmds/envsubst.py EnvSubst() called search_replace_placeholders()
which ran os.path.expandvars() on every attribute value and text node, then
wrote the result with save() -- but never checked whether any ${...} patterns
remained after the substitution pass. The command exited zero with no log
output, leaving the user unaware that manifest variables were unresolved.

Fix (landed in E0-F6-S2-T2): After search_replace_placeholders(), _collect_unresolved_vars()
scans all attribute values and text node values in the DOM for remaining
_UNRESOLVED_PATTERN matches. EnvSubst() logs a WARNING per unresolved variable
name (including the filename). Execute() aggregates unresolved names across all
files and prints a summary line listing them all. The command continues without
failing -- unresolved variables are a warning condition, not an error.

This regression guard asserts that:
1. A WARNING log record containing the variable name and filename is emitted
   for each ${VAR} that expandvars() could not resolve (AC-TEST-001).
2. The exact bug condition from E0-F6-S2-T2 is reproduced: EnvSubst() is called
   on a manifest with undefined variables and must not silently pass -- at least
   one WARNING must be logged (AC-TEST-002).
3. The test passes against the current fixed code (AC-TEST-003).
4. The structural _collect_unresolved_vars guard is present in the source
   (AC-FUNC-001).
5. Diagnostic warnings go to the logging channel, not stdout (AC-CHANNEL-001).
"""

import inspect
import logging
import os
from unittest import mock

import pytest

from kanon_cli.repo.subcmds import envsubst as envsubst_module
from kanon_cli.repo.subcmds.envsubst import Envsubst


# ---------------------------------------------------------------------------
# XML fixtures
# ---------------------------------------------------------------------------

_MANIFEST_WITH_UNDEFINED_VARS = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${DEFINED_BUG6}" />
  <remote name="secondary" fetch="${UNDEFINED_BUG6_ONE}" />
  <remote name="tertiary" fetch="${UNDEFINED_BUG6_TWO}" />
</manifest>
"""

_MANIFEST_ALL_DEFINED = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${DEFINED_BUG6}" />
</manifest>
"""

_MANIFEST_SINGLE_UNDEFINED = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${DEFINED_BUG6}" />
  <remote name="fallback" fetch="${UNDEFINED_BUG6_SINGLE}" />
</manifest>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cmd() -> Envsubst:
    """Return an Envsubst instance without invoking the parent __init__ chain.

    Bypasses the Command superclass initialiser to avoid requiring a real
    manifest directory, git client, or remote configuration. The manifest
    attribute is set to a MagicMock so any attribute access on it is safe.

    Returns:
        An Envsubst instance whose EnvSubst() and Execute() can be called directly.
    """
    cmd = Envsubst.__new__(Envsubst)
    cmd.manifest = mock.MagicMock()
    return cmd


def _env_without(*excluded_vars: str) -> dict:
    """Return os.environ without the named variables.

    Used to guarantee the environment does not contain the variable names
    that the test expects to remain unresolved after expandvars().

    Args:
        excluded_vars: Variable names to remove from the returned dict.

    Returns:
        A copy of os.environ with the excluded variables removed.
    """
    return {k: v for k, v in os.environ.items() if k not in excluded_vars}


# ---------------------------------------------------------------------------
# AC-TEST-001 -- regression: WARNING logged for each unresolved variable
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "undefined_var,description",
    [
        ("UNDEFINED_BUG6_ONE", "first undefined variable in multi-variable manifest"),
        ("UNDEFINED_BUG6_TWO", "second undefined variable in multi-variable manifest"),
    ],
)
def test_regression_warning_logged_for_each_unresolved_variable(
    tmp_path: pytest.TempPathFactory,
    caplog: pytest.LogCaptureFixture,
    undefined_var: str,
    description: str,
) -> None:
    """AC-TEST-001: EnvSubst() must log a WARNING for each ${VAR} not resolved.

    This test reproduces the exact bug condition from E0-F6-S2-T2: a manifest
    contains ${DEFINED_BUG6}, ${UNDEFINED_BUG6_ONE}, and ${UNDEFINED_BUG6_TWO}.
    DEFINED_BUG6 is present in the environment; the two UNDEFINED variants are
    absent. Before the fix, Execute() wrote the output silently with no WARNING.
    After the fix a WARNING including both the variable name and the filename is
    emitted for each unresolved ${...} pattern.

    If this test fails with no WARNING record, the _collect_unresolved_vars()
    guard and/or the WARNING log call in EnvSubst() have been removed and Bug 6
    has regressed.

    Arrange: Write a manifest with defined and undefined variables. Exclude
    the undefined variable names from os.environ.
    Act: Call EnvSubst() on the file.
    Assert: At least one WARNING log record exists that contains both the
    undefined variable name and the filename.
    """
    manifest_path = tmp_path / "mixed.xml"
    manifest_path.write_text(_MANIFEST_WITH_UNDEFINED_VARS, encoding="utf-8")

    cmd = _make_cmd()

    env = _env_without("UNDEFINED_BUG6_ONE", "UNDEFINED_BUG6_TWO")
    env["DEFINED_BUG6"] = "https://example.com/org/"

    with mock.patch.dict(os.environ, env, clear=True):
        with caplog.at_level(logging.WARNING):
            cmd.EnvSubst(str(manifest_path))

    filename = str(manifest_path)
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]

    matching = [r for r in warning_records if undefined_var in r.message]
    assert matching, (
        f"E0-F6-S2-T2 regression ({description}): expected at least one WARNING "
        f"log record containing {undefined_var!r} when that variable is absent "
        f"from the environment, but none was found.\n"
        f"All WARNING records: {[r.message for r in warning_records]!r}\n"
        "The _collect_unresolved_vars() scan or the WARNING log call in "
        "envsubst.py EnvSubst() has been removed. Restore both to guard "
        "against Bug 6 regressing."
    )

    for record in matching:
        assert filename in record.message, (
            f"E0-F6-S2-T2 regression ({description}): WARNING for {undefined_var!r} "
            f"must include the filename {filename!r} so the user knows which file "
            f"has the unresolved variable, but it does not.\n"
            f"Record message: {record.message!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- exact bug condition: EnvSubst() must not silently pass
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_exact_bug_condition_no_silent_pass_on_undefined_vars(
    tmp_path: pytest.TempPathFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-TEST-002: EnvSubst() must not silently ignore undefined ${VAR} references.

    This test reproduces the exact bug condition from E0-F6-S2-T2: EnvSubst()
    is called on a manifest that contains ${UNDEFINED_BUG6_SINGLE} with that
    variable absent from the environment. Before the fix the command wrote the
    manifest back silently with no WARNING, leaving the user unaware that the
    placeholder was not substituted.

    The regression is confirmed if this test finds zero WARNING log records
    after EnvSubst() completes -- that is the silent-pass symptom of Bug 6.

    Arrange: Write a manifest containing one defined and one undefined variable.
    Exclude the undefined variable from os.environ.
    Act: Call EnvSubst() on the file.
    Assert: At least one WARNING log record exists (not a silent pass).
    Assert: No exception is raised (the command must not crash either).
    """
    manifest_path = tmp_path / "single_undefined.xml"
    manifest_path.write_text(_MANIFEST_SINGLE_UNDEFINED, encoding="utf-8")

    cmd = _make_cmd()

    env = _env_without("UNDEFINED_BUG6_SINGLE")
    env["DEFINED_BUG6"] = "https://example.com/org/"

    with mock.patch.dict(os.environ, env, clear=True):
        with caplog.at_level(logging.WARNING):
            try:
                cmd.EnvSubst(str(manifest_path))
            except Exception as exc:
                pytest.fail(
                    f"E0-F6-S2-T2 regression: EnvSubst() raised {type(exc).__name__} "
                    f"when processing a manifest with an undefined variable. "
                    f"Unresolved variables are a warning condition, not an error. "
                    f"Exception: {exc}"
                )

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    undefined_warnings = [r for r in warning_records if "UNDEFINED_BUG6_SINGLE" in r.message]

    assert undefined_warnings, (
        "E0-F6-S2-T2 regression: EnvSubst() completed silently with no WARNING "
        "for the undefined variable 'UNDEFINED_BUG6_SINGLE'. "
        "This is the exact Bug 6 symptom: unresolved ${...} patterns pass through "
        "without any user-visible indication.\n"
        f"All log records: {[(r.levelno, r.message) for r in caplog.records]!r}\n"
        "Restore the _collect_unresolved_vars() call and the WARNING log in "
        "envsubst.py EnvSubst() to prevent Bug 6 from recurring."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- passes against the current fixed code
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "manifest_content,env_additions,undefined_var_names,description",
    [
        (
            _MANIFEST_SINGLE_UNDEFINED,
            {"DEFINED_BUG6": "https://resolved.example.com/"},
            ["UNDEFINED_BUG6_SINGLE"],
            "single undefined variable triggers one WARNING per name",
        ),
        (
            _MANIFEST_WITH_UNDEFINED_VARS,
            {"DEFINED_BUG6": "https://resolved.example.com/"},
            ["UNDEFINED_BUG6_ONE", "UNDEFINED_BUG6_TWO"],
            "two undefined variables each trigger a WARNING",
        ),
        (
            _MANIFEST_ALL_DEFINED,
            {"DEFINED_BUG6": "https://resolved.example.com/"},
            [],
            "all variables defined -- no undefined-variable WARNINGs emitted",
        ),
    ],
    ids=[
        "single_undefined",
        "two_undefined",
        "all_defined_no_warnings",
    ],
)
def test_regression_fixed_code_behavior(
    tmp_path: pytest.TempPathFactory,
    caplog: pytest.LogCaptureFixture,
    manifest_content: str,
    env_additions: dict,
    undefined_var_names: list,
    description: str,
) -> None:
    """AC-TEST-003: Current fixed code emits WARNINGs only for undefined variables.

    Verifies that the fix from E0-F6-S2-T2 is in place and produces the correct
    output for multiple manifest scenarios:
    - One undefined variable: exactly one WARNING mentioning that variable.
    - Two undefined variables: WARNINGs for both names.
    - All defined: no undefined-variable WARNINGs emitted.

    For the "all_defined" case the fix must also remain silent (no false positives
    for variables that were successfully resolved).

    If any parametrized case with undefined_var_names fails to find matching
    WARNINGs, Bug 6 has regressed. If the all_defined case emits unexpected
    undefined-variable WARNINGs, the regex scan is producing false positives.

    Arrange: Write a manifest from the parametrized content. Set env_additions
    in os.environ; exclude all undefined_var_names from the environment.
    Act: Call EnvSubst() on the file.
    Assert: Each expected undefined variable name appears in at least one
    WARNING. No unexpected undefined-variable WARNINGs for the all_defined case.
    """
    manifest_path = tmp_path / "manifest.xml"
    manifest_path.write_text(manifest_content, encoding="utf-8")

    cmd = _make_cmd()

    env = _env_without(*undefined_var_names)
    env.update(env_additions)

    with mock.patch.dict(os.environ, env, clear=True):
        with caplog.at_level(logging.WARNING):
            cmd.EnvSubst(str(manifest_path))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]

    for var_name in undefined_var_names:
        matching = [r for r in warning_records if var_name in r.message]
        assert matching, (
            f"E0-F6-S2-T2 regression ({description}): expected a WARNING "
            f"containing {var_name!r} but none was found.\n"
            f"All WARNING records: {[r.message for r in warning_records]!r}\n"
            "The Bug 6 fix (_collect_unresolved_vars + WARNING log) has been removed."
        )

    if not undefined_var_names:
        unexpected = [r for r in warning_records if "unresolved" in r.message.lower() or "${" in r.message]
        assert not unexpected, (
            f"E0-F6-S2-T2 regression ({description}): no undefined variables "
            f"expected, but found unexpected undefined-variable WARNING records: "
            f"{[r.message for r in unexpected]!r}. "
            "The _UNRESOLVED_PATTERN regex is matching resolved variables (false positive)."
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- structural guards present in source
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_unresolved_vars_guard_present_in_envsubst_source() -> None:
    """AC-FUNC-001: The unresolved-variable guard is present in EnvSubst() source.

    Inspects the source of Envsubst.EnvSubst() and the module-level symbols to
    confirm:
    - _collect_unresolved_vars is defined at module level.
    - EnvSubst() calls _collect_unresolved_vars (or references it).
    - The WARNING log call for unresolved variables is in EnvSubst().

    If any check fails, the guard has been structurally removed and the
    E0-F6-S2-T2 bug would regress silently for any manifest with undefined
    environment variables.
    """
    assert hasattr(envsubst_module, "_collect_unresolved_vars"), (
        "E0-F6-S2-T2 regression guard: '_collect_unresolved_vars' is no longer "
        "defined in envsubst.py. This module-level helper scans the DOM for "
        "remaining ${...} patterns after expandvars(). Restore it to prevent "
        "Bug 6 from recurring."
    )

    envsubst_source = inspect.getsource(Envsubst.EnvSubst)

    assert "_collect_unresolved_vars" in envsubst_source, (
        "E0-F6-S2-T2 regression guard: '_collect_unresolved_vars' is no longer "
        "called inside Envsubst.EnvSubst(). The call that scans for remaining "
        "${...} patterns has been removed from envsubst.py EnvSubst(). "
        "Restore the '_collect_unresolved_vars(doc)' call after "
        "search_replace_placeholders() to prevent Bug 6 from recurring."
    )

    assert "_LOG.warning" in envsubst_source, (
        "E0-F6-S2-T2 regression guard: '_LOG.warning' is no longer called in "
        "Envsubst.EnvSubst(). The WARNING log that notifies the user about "
        "unresolved ${VAR} patterns has been removed from envsubst.py EnvSubst(). "
        "Restore the per-variable '_LOG.warning(\"Unresolved variable ...\")' call."
    )

    assert hasattr(envsubst_module, "_UNRESOLVED_PATTERN"), (
        "E0-F6-S2-T2 regression guard: '_UNRESOLVED_PATTERN' is no longer "
        "defined in envsubst.py. This module-level regex constant matches "
        "remaining ${VAR_NAME} patterns that expandvars() could not resolve. "
        "Restore the constant to prevent Bug 6 from recurring."
    )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001 -- stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_undefined_var_warning_goes_to_logging_not_stdout(
    tmp_path: pytest.TempPathFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-CHANNEL-001: The undefined-variable WARNING goes to the logging channel.

    stdout is reserved for machine-consumable output. Diagnostic messages such
    as the undefined-variable warning must go through the logging subsystem
    (which routes to stderr in production), not via print() to stdout.

    The summary line printed by Execute() at the end ('Unresolved environment
    variables: ...') is an intentional user-facing summary and is allowed to go
    to stdout. The per-variable WARNING emitted by EnvSubst() must use the
    logging channel.

    This test calls EnvSubst() directly (not Execute()) so it captures only the
    per-variable WARNING path. The test verifies:
    1. The WARNING appears in the captured log records (logging channel used).
    2. The WARNING message does not appear in any print() calls to stdout.

    Arrange: Write a manifest with an undefined variable. Exclude it from env.
    Capture print() calls and log records.
    Act: Call EnvSubst() directly.
    Assert: WARNING in log records; warning text not printed to stdout.
    """
    manifest_path = tmp_path / "channel_check.xml"
    manifest_path.write_text(_MANIFEST_SINGLE_UNDEFINED, encoding="utf-8")

    cmd = _make_cmd()

    env = _env_without("UNDEFINED_BUG6_SINGLE")
    env["DEFINED_BUG6"] = "https://example.com/org/"

    printed_lines: list[str] = []

    def _capture_print(*args, **kwargs) -> None:
        printed_lines.extend(str(a) for a in args)

    with mock.patch.dict(os.environ, env, clear=True):
        with mock.patch("builtins.print", side_effect=_capture_print):
            with caplog.at_level(logging.WARNING, logger=envsubst_module._LOG.name):
                cmd.EnvSubst(str(manifest_path))

    warning_records = [
        r for r in caplog.records if r.levelno == logging.WARNING and "UNDEFINED_BUG6_SINGLE" in r.message
    ]
    assert warning_records, (
        "E0-F6-S2-T2 regression (channel discipline): expected a WARNING log "
        "record containing 'UNDEFINED_BUG6_SINGLE' from the logging channel, "
        f"but none was captured.\n"
        f"Captured log records: {[(r.levelno, r.message) for r in caplog.records]!r}\n"
        "The per-variable WARNING must use _LOG.warning(), not print()."
    )

    stdout_with_var = [line for line in printed_lines if "UNDEFINED_BUG6_SINGLE" in line]
    assert not stdout_with_var, (
        "E0-F6-S2-T2 regression (channel discipline): the per-variable undefined "
        "variable warning for 'UNDEFINED_BUG6_SINGLE' was written to stdout via "
        "print() instead of the logging channel.\n"
        f"stdout lines containing the variable: {stdout_with_var!r}\n"
        "Diagnostic warnings must use _LOG.warning(), not print()."
    )
