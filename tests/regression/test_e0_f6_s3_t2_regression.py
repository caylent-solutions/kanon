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

"""Regression guard for E0-F6-S3-T2: Bugs 16-20 low severity fixes.

Bug reference: E0-F6-S3-T2 -- Five low-severity bugs fixed:

- Bug 16: Nested variable warning -- Patterns like ${VAR_${INNER}} (nested
  ${...} inside ${...}) must be detected. A WARNING is logged per occurrence
  including the full nested pattern text. The tool does not attempt to resolve
  nested variables.
- Bug 17: Path separators -- Documentation-only fix. No code guard needed.
- Bug 18: envsubst double-parse -- The XML parsing approach was replaced with
  string-based filtering that reads, substitutes, and writes in a single pass.
  The parseString import must not be present in the envsubst module namespace.
- Bug 19: Glob source path error -- When envsubst receives a glob source path
  whose source directory does not exist, os.path.exists() is checked first and
  a clear error message including the non-existent path is raised.
- Bug 20: Glob destination is a file -- When the glob destination path is an
  existing file (not a directory), an exception is raised instead of logging
  and continuing. The error message must include the destination path.

This regression guard asserts that:
1. Bug 16: nested ${...${...}} pattern produces a WARNING with full pattern text.
2. Bug 16: no nested-variable WARNING is logged for plain ${VAR} references.
3. Bug 18: parseString is not present in the envsubst module namespace.
4. Bug 18: EnvSubst() expands variables and writes output without double-parse.
5. Bug 19: non-existent glob source directory raises an exception with the path.
6. Bug 20: file-as-glob-destination raises an exception with the dest path.
7. Bug 20: directory-as-glob-destination does NOT raise an exception.
"""

import inspect
import logging
from unittest import mock

import pytest

from kanon_cli.repo import project as project_module
from kanon_cli.repo.error import ManifestInvalidPathError
from kanon_cli.repo.subcmds import envsubst as envsubst_module
from kanon_cli.repo.subcmds.envsubst import Envsubst


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MANIFEST_WITH_NESTED_VAR = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${BASE_${ENV}_URL}" />
  <default revision="main" remote="origin" />
</manifest>
"""

_MANIFEST_PLAIN_VAR = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${GITBASE}" />
  <default revision="main" remote="origin" />
</manifest>
"""


def _make_envsubst_cmd():
    """Return an Envsubst instance without invoking the parent __init__ chain."""
    cmd = Envsubst.__new__(Envsubst)
    cmd.manifest = mock.MagicMock()
    return cmd


def _make_link_file(worktree, src_rel, topdir, dest_rel):
    """Return a _LinkFile instance for the given paths."""
    return project_module._LinkFile(str(worktree), src_rel, str(topdir), dest_rel)


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-TEST-002 -- Bug 16: nested variable warning
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_bug16_nested_var_warning_logged(tmp_path, caplog):
    """AC-TEST-001: EnvSubst must log a WARNING when a nested ${...${...}}
    pattern is found in a manifest file.

    This test reproduces the exact bug condition from E0-F6-S3-T2: a manifest
    contains a nested variable reference like ${BASE_${ENV}_URL}. Before the
    fix, expandvars() silently left nested patterns unresolved with no
    diagnostic. After the fix, _warn_nested_vars() scans the raw content and
    logs a WARNING per nested pattern including the full pattern text.

    If this test fails with no WARNING, the Bug 16 nested-variable detection
    added in E0-F6-S3-T2 has been removed or broken.

    Arrange: Create a manifest with ${BASE_${ENV}_URL} nested variable.
    Act: Call EnvSubst() and capture log records.
    Assert: At least one WARNING contains the full nested pattern text.
    """
    manifest_path = tmp_path / "manifest.xml"
    manifest_path.write_text(_MANIFEST_WITH_NESTED_VAR, encoding="utf-8")

    cmd = _make_envsubst_cmd()

    with caplog.at_level(logging.WARNING):
        cmd.EnvSubst(str(manifest_path))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    nested_warnings = [r for r in warning_records if "${BASE_${ENV}_URL}" in r.message]
    assert nested_warnings, (
        "E0-F6-S3-T2 Bug 16 regression: no WARNING logged containing the full nested "
        "pattern '${BASE_${ENV}_URL}'. The _warn_nested_vars() function added in "
        "E0-F6-S3-T2 has been removed or no longer logs the full pattern text. "
        f"All WARNING records: {[r.message for r in warning_records]!r}"
    )


@pytest.mark.unit
def test_regression_bug16_no_nested_warning_for_plain_var(tmp_path, caplog):
    """Bug 16 regression: no nested-variable WARNING for plain ${VAR} references.

    Plain variable references must not trigger the nested-variable warning.
    This verifies the fix is scoped to genuinely nested patterns and does not
    produce false positives on ordinary ${VAR} syntax.

    Arrange: Create a manifest with only plain ${GITBASE} reference. Set GITBASE.
    Act: Call EnvSubst() and capture log records.
    Assert: No WARNING contains a nested ${...${...}...} pattern.
    """
    import re

    manifest_path = tmp_path / "plain.xml"
    manifest_path.write_text(_MANIFEST_PLAIN_VAR, encoding="utf-8")

    cmd = _make_envsubst_cmd()

    with mock.patch.dict("os.environ", {"GITBASE": "https://example.com/"}):
        with caplog.at_level(logging.WARNING):
            cmd.EnvSubst(str(manifest_path))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    nested_warnings = [r for r in warning_records if re.search(r"\$\{[^}]*\$\{", r.message)]
    assert not nested_warnings, (
        "E0-F6-S3-T2 Bug 16 regression: a nested-variable WARNING was emitted for "
        "a plain ${GITBASE} reference. The _warn_nested_vars() regex is too broad "
        "and produces false positives. "
        f"Unexpected nested-variable warnings: {[r.message for r in nested_warnings]!r}"
    )


@pytest.mark.unit
def test_regression_bug16_warn_nested_vars_function_exists():
    """Bug 16 structural guard: _warn_nested_vars function exists in envsubst.

    Inspects the envsubst module to confirm that _warn_nested_vars() is still
    present. If this test fails, the nested-variable warning function has been
    removed from envsubst.py and Bug 16 has regressed.
    """
    assert hasattr(envsubst_module, "_warn_nested_vars"), (
        "E0-F6-S3-T2 Bug 16 structural regression: _warn_nested_vars() is no "
        "longer present in the envsubst module. The nested-variable detection "
        "function added in E0-F6-S3-T2 has been removed from "
        "src/kanon_cli/repo/subcmds/envsubst.py."
    )


@pytest.mark.unit
def test_regression_bug16_nested_var_pattern_in_source():
    """Bug 16 structural guard: _NESTED_VAR_PATTERN regex present in envsubst.

    Inspects envsubst module attributes to confirm the compiled regex pattern
    for detecting nested variables still exists. If this test fails, the regex
    constant has been removed and Bug 16 detection has been broken.
    """
    assert hasattr(envsubst_module, "_NESTED_VAR_PATTERN"), (
        "E0-F6-S3-T2 Bug 16 structural regression: _NESTED_VAR_PATTERN constant "
        "is no longer present in the envsubst module. The nested-variable regex "
        "added in E0-F6-S3-T2 has been removed from "
        "src/kanon_cli/repo/subcmds/envsubst.py."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 / AC-TEST-003 -- Bug 18: single-pass envsubst (no double-parse)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_bug18_parsestring_not_in_envsubst_namespace():
    """AC-TEST-002 / Bug 18 regression: parseString must not be in envsubst namespace.

    This test reproduces the exact bug condition from E0-F6-S3-T2: before the
    fix, save() called parseString() to filter blank lines from toprettyxml()
    output, requiring 'from xml.dom.minidom import parseString'. The fix
    replaces the second parse with string-based filtering, removing the import.

    If this test fails, the double-parse pattern has been reintroduced and
    Bug 18 has regressed.

    Arrange: Import the envsubst module.
    Act: Check whether parseString is present in the module namespace.
    Assert: parseString is NOT a name in the envsubst module namespace.
    """
    assert not hasattr(envsubst_module, "parseString"), (
        "E0-F6-S3-T2 Bug 18 regression: 'parseString' is present in the envsubst "
        "module namespace. The double-parse approach (Bug 18) has been reintroduced. "
        "The save() method must use string-based line filtering instead of a second "
        "minidom.parseString() call. Remove 'from xml.dom.minidom import parseString' "
        "from src/kanon_cli/repo/subcmds/envsubst.py."
    )


@pytest.mark.unit
def test_regression_bug18_single_pass_substitution(tmp_path):
    """AC-TEST-003 / Bug 18 regression: EnvSubst expands variables and writes output.

    After EnvSubst() processes a manifest, the output file must contain the
    expanded variable value and must not contain the original placeholder. This
    verifies that the string-based single-pass substitution (Bug 18 fix) is
    functionally correct.

    If this test fails, the substitution pipeline has been broken and either
    variables are not expanded or output is not written correctly.

    Arrange: Create a manifest with ${GITBASE}. Set GITBASE in environment.
    Act: Call EnvSubst() on the file.
    Assert: Output contains the resolved URL; placeholder is gone.
    """
    manifest_path = tmp_path / "manifest.xml"
    manifest_path.write_text(_MANIFEST_PLAIN_VAR, encoding="utf-8")

    cmd = _make_envsubst_cmd()
    expected_url = "https://git.example.com/org/"

    with mock.patch.dict("os.environ", {"GITBASE": expected_url}):
        cmd.EnvSubst(str(manifest_path))

    result = manifest_path.read_text(encoding="utf-8")
    assert expected_url in result, (
        "E0-F6-S3-T2 Bug 18 regression: the resolved URL was not found in the "
        f"output file. Expected {expected_url!r} to be present. "
        f"Output content:\n{result}"
    )
    assert "${GITBASE}" not in result, (
        "E0-F6-S3-T2 Bug 18 regression: the ${GITBASE} placeholder was not replaced. "
        "The single-pass substitution in EnvSubst() has been broken. "
        f"Output content:\n{result}"
    )


@pytest.mark.unit
def test_regression_bug18_save_uses_string_filtering_not_double_parse():
    """Bug 18 structural guard: save() uses string-based filtering, not parseString.

    Inspects the source of Envsubst.save() to confirm the string-based filtering
    approach is present. The original double-parse approach (Bug 18) called
    parseString() to strip blank lines. The fix replaced it with splitlines()
    and join() manipulation. The module-level namespace check already confirms
    parseString is not imported; this test confirms the positive -- that the
    string filtering logic is present in save().

    If this test fails, the string-based filtering in save() has been removed
    and the double-parse approach may have been reintroduced.
    """
    source = inspect.getsource(Envsubst.save)
    assert "splitlines" in source or "join" in source, (
        "E0-F6-S3-T2 Bug 18 structural regression: string-based filtering logic "
        "(splitlines or join) not found in Envsubst.save(). The single-pass "
        "approach added in E0-F6-S3-T2 may have been removed or replaced by a "
        "double-parse. Source of save():\n" + source
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- Bug 19: non-existent glob source directory raises error
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_bug19_nonexistent_glob_src_raises_error(tmp_path):
    """AC-TEST-002 / Bug 19 regression: non-existent glob source directory raises error.

    This test reproduces the exact bug condition from E0-F6-S3-T2: a _LinkFile
    with a glob src pattern whose base directory does not exist. Before the fix,
    glob.glob() returned an empty list silently. After the fix, os.path.exists()
    is checked on the source directory first and a ManifestInvalidPathError is
    raised with a message including the non-existent path.

    If this test fails without raising an exception, the Bug 19 pre-glob
    existence check in _Link() has been removed and Bug 19 has regressed.

    Arrange: Create _LinkFile with glob src pointing to a non-existent directory.
    Act: Call _Link().
    Assert: An exception is raised containing the non-existent path in the message.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()
    dest_dir = topdir / "dest"
    dest_dir.mkdir()

    nonexistent_src_rel = "nonexistent_dir/*.xml"
    lf = _make_link_file(worktree, nonexistent_src_rel, topdir, "dest")

    with pytest.raises((ManifestInvalidPathError, FileNotFoundError, ValueError, OSError)) as exc_info:
        lf._Link()

    error_message = str(exc_info.value)
    expected_path = str(worktree / "nonexistent_dir")
    assert expected_path in error_message or "nonexistent_dir" in error_message, (
        "E0-F6-S3-T2 Bug 19 regression: exception raised but the non-existent source "
        f"directory path {expected_path!r} is not in the error message. "
        "The ManifestInvalidPathError must include the missing path to help the user. "
        f"Error message: {error_message!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "src_rel",
    [
        "missing/*.xml",
        "does/not/exist/*.conf",
    ],
    ids=["simple_missing_dir", "nested_missing_path"],
)
def test_regression_bug19_error_includes_path_parametrized(tmp_path, src_rel):
    """Bug 19 regression: each non-existent glob source produces error with the path.

    Parametrized to verify the error message consistently includes the missing
    directory path for different glob patterns.

    Arrange: Create _LinkFile with glob src pointing to a non-existent dir.
    Act: Call _Link().
    Assert: Exception raised; error message includes the directory component.
    """
    import os

    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    lf = _make_link_file(worktree, src_rel, topdir, "dest")

    with pytest.raises((ManifestInvalidPathError, FileNotFoundError, ValueError, OSError)) as exc_info:
        lf._Link()

    error_message = str(exc_info.value)
    src_dir = os.path.dirname(src_rel)
    assert src_dir in error_message or src_rel in error_message, (
        "E0-F6-S3-T2 Bug 19 regression: exception raised but the missing source "
        f"directory {src_dir!r} is not in the error message. "
        f"Error message: {error_message!r}"
    )


@pytest.mark.unit
def test_regression_bug19_glob_check_before_glob_call_in_source():
    """Bug 19 structural guard: os.path.exists check on src_dir precedes glob.glob.

    Inspects the _Link source to confirm os.path.exists() is checked on the
    source directory before calling glob.glob(). If this test fails, the
    pre-glob existence check has been removed and Bug 19 has regressed.
    """
    source = inspect.getsource(project_module._LinkFile._Link)
    assert "os.path.exists" in source, (
        "E0-F6-S3-T2 Bug 19 structural regression: os.path.exists() is no longer "
        "present in _LinkFile._Link(). The pre-glob existence check added in "
        "E0-F6-S3-T2 has been removed from src/kanon_cli/repo/project.py _Link()."
    )
    assert "src_dir" in source, (
        "E0-F6-S3-T2 Bug 19 structural regression: 'src_dir' variable is no longer "
        "present in _LinkFile._Link(). The source directory check added in "
        "E0-F6-S3-T2 has been removed from src/kanon_cli/repo/project.py _Link()."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- Bug 20: file-as-glob-destination raises exception
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_bug20_file_dest_raises_exception(tmp_path):
    """AC-TEST-002 / Bug 20 regression: file-as-glob-destination raises an exception.

    This test reproduces the exact bug condition from E0-F6-S3-T2: a _LinkFile
    with a glob src pattern but the destination is an existing regular file
    (not a directory). Before the fix, the code logged an error and continued
    silently. After the fix, ManifestInvalidPathError is raised so callers know
    the link operation failed.

    If this test fails without raising, the Bug 20 raise-instead-of-log fix in
    _Link() has been removed and Bug 20 has regressed.

    Arrange: Create glob src with matching file. Create dest as a regular file.
    Act: Call _Link().
    Assert: An exception is raised.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_dir = worktree / "configs"
    src_dir.mkdir()
    (src_dir / "app.xml").write_text("<config/>", encoding="utf-8")

    dest_file = topdir / "dest_as_file"
    dest_file.write_text("I am a file, not a directory", encoding="utf-8")

    lf = _make_link_file(worktree, "configs/*.xml", topdir, "dest_as_file")

    with pytest.raises((ManifestInvalidPathError, FileExistsError, ValueError, OSError)):
        lf._Link()


@pytest.mark.unit
def test_regression_bug20_file_dest_error_includes_dest_path(tmp_path):
    """Bug 20 regression: the exception when dest is a file must include the dest path.

    A clear error message including the destination path helps the user
    understand which path caused the problem and how to resolve it (e.g., by
    removing the blocking file so a directory can be created).

    If the error message does not include the destination path, the message
    contract added in E0-F6-S3-T2 has been loosened and Bug 20 has partially
    regressed.

    Arrange: Create glob src with matching file. Create dest as a regular file.
    Act: Call _Link().
    Assert: Exception message includes the destination path.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_dir = worktree / "templates"
    src_dir.mkdir()
    (src_dir / "base.xml").write_text("<template/>", encoding="utf-8")

    dest_file = topdir / "my_blocking_dest"
    dest_file.write_text("blocking file content", encoding="utf-8")
    expected_dest_path = str(dest_file)

    lf = _make_link_file(worktree, "templates/*.xml", topdir, "my_blocking_dest")

    with pytest.raises((ManifestInvalidPathError, FileExistsError, ValueError, OSError)) as exc_info:
        lf._Link()

    error_message = str(exc_info.value)
    assert expected_dest_path in error_message or "my_blocking_dest" in error_message, (
        "E0-F6-S3-T2 Bug 20 regression: exception raised but the destination path "
        f"{expected_dest_path!r} is not in the error message. "
        "The ManifestInvalidPathError must include the blocking dest path. "
        f"Error message: {error_message!r}"
    )


@pytest.mark.unit
def test_regression_bug20_directory_dest_does_not_raise(tmp_path):
    """Bug 20 regression: directory-as-glob-destination must NOT raise.

    When the glob destination is a valid directory, _Link() must succeed
    without raising. This verifies the fix only applies to the file-as-dest
    case and does not break the valid directory destination path.

    Arrange: Create glob src with matching file. Create dest as a directory.
    Act: Call _Link().
    Assert: No exception is raised.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_dir = worktree / "configs"
    src_dir.mkdir()
    (src_dir / "app.xml").write_text("<config/>", encoding="utf-8")

    dest_dir = topdir / "dest_dir"
    dest_dir.mkdir()

    lf = _make_link_file(worktree, "configs/*.xml", topdir, "dest_dir")

    lf._Link()


@pytest.mark.unit
def test_regression_bug20_raise_not_log_in_link_source():
    """Bug 20 structural guard: raise is present in the file-dest guard in _Link().

    Inspects the _Link source to confirm that when the dest is an existing
    file, a ManifestInvalidPathError is raised (not logged). If this test
    fails, the raise has been replaced by a log-and-continue and Bug 20 has
    regressed.
    """
    source = inspect.getsource(project_module._LinkFile._Link)
    assert "ManifestInvalidPathError" in source, (
        "E0-F6-S3-T2 Bug 20 structural regression: ManifestInvalidPathError is no "
        "longer raised inside _LinkFile._Link(). The raise-instead-of-log fix added "
        "in E0-F6-S3-T2 has been removed from src/kanon_cli/repo/project.py _Link()."
    )
