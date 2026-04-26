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

"""Regression guard for E0-INSTALL-RELATIVE: kanon install .kanon relative path.

Bug reference: E0-INSTALL-RELATIVE -- when the user runs 'kanon install .kanon'
with a relative path argument, the path was passed as-is to downstream code that
enforces an absolute path requirement. Specifically, XmlManifest.__init__ in
src/kanon_cli/repo/manifest_xml.py line 409-410 asserts:

    if manifest_file != os.path.abspath(manifest_file):
        raise ManifestParseError("manifest_file must be abspath")

Before the fix, the relative Path('.kanon') flowed through install._run() into
parse_kanonenv() and install() without being converted to an absolute path, causing
ManifestParseError at the parser boundary. After the fix, install._run() calls
args.kanonenv_path.resolve() at the CLI boundary before invoking any downstream
code, so a relative '.kanon' argument is always resolved to an absolute path
regardless of the calling working directory.

Root cause: install._run() did not call .resolve() on the explicit
kanonenv_path argument (the auto-discovery path is already absolute because
find_kanonenv() returns an absolute path, but an explicit relative argument
bypassed the absolute-path requirement).

Fix: install._run() calls args.kanonenv_path = args.kanonenv_path.resolve()
immediately after the auto-discovery branch, before any downstream calls. This
converts a relative path like '.kanon' to the fully-resolved absolute path.

This regression guard asserts that:
1. Passing a relative '.kanon' Path to _run() resolves it to an absolute path
   before invoking install() (AC-TEST-001, AC-TEST-002).
2. The resolved path is correct -- it equals the absolute path to the .kanon
   file in the working directory (AC-TEST-001).
3. The resolve() call in install._run() is structurally present in the source
   so any future removal of the line is immediately detected (AC-FUNC-001).
4. Stdout vs stderr discipline: no error appears on stdout when the relative
   path resolves correctly (AC-CHANNEL-001).
"""

import inspect
import pathlib
from unittest.mock import patch

import pytest

import kanon_cli.commands.install as install_module
from kanon_cli.commands.install import _run
from tests.conftest import write_kanonenv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(kanonenv_path: pathlib.Path) -> object:
    """Return a minimal args namespace with kanonenv_path set."""
    from unittest.mock import MagicMock

    args = MagicMock()
    args.kanonenv_path = kanonenv_path
    return args


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-TEST-002 -- exact bug condition: relative .kanon resolves
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_relative_kanon_path_resolved_to_absolute_before_install(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-001 / AC-TEST-002: relative '.kanon' Path is resolved to absolute before install().

    This test reproduces the exact bug condition from E0-INSTALL-RELATIVE:
    install._run() receives a relative pathlib.Path('.kanon') as the
    kanonenv_path argument (matching what argparse produces when the user
    types 'kanon install .kanon'). Before the fix, this relative path was
    forwarded as-is to parse_kanonenv() and install(), which eventually
    reached XmlManifest.__init__ where it triggered:

        ManifestParseError("manifest_file must be abspath")

    After the fix, args.kanonenv_path = args.kanonenv_path.resolve() runs
    at the CLI boundary, converting the relative path to an absolute path
    that satisfies the downstream abspath requirement.

    This test verifies the fix is in place by:
    1. Arranging a real .kanon file in tmp_path.
    2. Changing the working directory to tmp_path so that Path('.kanon').resolve()
       produces the correct absolute path.
    3. Passing a relative Path('.kanon') to _run() via mocked args.
    4. Asserting that install() receives an absolute path, not the relative one.

    If this test fails (install receives a non-absolute path), the resolve()
    call in install._run() has been removed and E0-INSTALL-RELATIVE has regressed.

    AC-TEST-001, AC-TEST-002
    """
    write_kanonenv(tmp_path)
    monkeypatch.chdir(tmp_path)

    relative_path = pathlib.Path(".kanon")
    assert not relative_path.is_absolute(), "Test setup: .kanon must be a relative path for this test."

    received_paths: list[pathlib.Path] = []

    def _capture_install(path: pathlib.Path) -> None:
        received_paths.append(path)

    args = _make_args(relative_path)

    with patch("kanon_cli.commands.install.install", side_effect=_capture_install):
        with patch("kanon_cli.core.kanonenv.parse_kanonenv"):
            _run(args)

    assert len(received_paths) == 1, (
        "E0-INSTALL-RELATIVE regression: install() was not called exactly once. "
        f"install() call count: {len(received_paths)}"
    )

    received = received_paths[0]
    assert received.is_absolute(), (
        "E0-INSTALL-RELATIVE regression: install() received a non-absolute path. "
        f"Got {received!r}. "
        "The args.kanonenv_path.resolve() call in install._run() has been removed "
        "or moved after the install() invocation. "
        "Restore 'args.kanonenv_path = args.kanonenv_path.resolve()' immediately "
        "after the auto-discovery branch in src/kanon_cli/commands/install.py."
    )

    expected_absolute = (tmp_path / ".kanon").resolve()
    assert received == expected_absolute, (
        "E0-INSTALL-RELATIVE regression: install() received the wrong absolute path. "
        f"Expected {expected_absolute!r}, got {received!r}. "
        "The resolve() call must convert relative '.kanon' to the path of the "
        ".kanon file in the calling working directory."
    )


@pytest.mark.unit
def test_regression_relative_subdir_kanon_resolved_to_absolute(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-002: relative subdir path 'subdir/.kanon' is resolved to absolute.

    Verifies the exact bug condition with a relative path that includes a
    subdirectory component, e.g. 'kanon install subdir/.kanon'. Both simple
    '.kanon' and 'subdir/.kanon' relative forms must be resolved to absolute
    paths before reaching any downstream code.

    Arrange: Write .kanon in a subdirectory of tmp_path. chdir to tmp_path.
    Act: Pass relative pathlib.Path('subdir/.kanon') to _run().
    Assert: install() receives an absolute path matching subdir/.kanon resolved
            from tmp_path.

    AC-TEST-002
    """
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    write_kanonenv(subdir)
    monkeypatch.chdir(tmp_path)

    relative_path = pathlib.Path("subdir/.kanon")
    assert not relative_path.is_absolute(), "Test setup: path must be relative."

    received_paths: list[pathlib.Path] = []

    def _capture_install(path: pathlib.Path) -> None:
        received_paths.append(path)

    args = _make_args(relative_path)

    with patch("kanon_cli.commands.install.install", side_effect=_capture_install):
        with patch("kanon_cli.core.kanonenv.parse_kanonenv"):
            _run(args)

    assert len(received_paths) == 1, (
        f"E0-INSTALL-RELATIVE regression: install() not called once for subdir path. call count: {len(received_paths)}"
    )

    received = received_paths[0]
    assert received.is_absolute(), (
        "E0-INSTALL-RELATIVE regression: install() received non-absolute path for "
        f"'subdir/.kanon' relative argument. Got {received!r}."
    )

    expected_absolute = (tmp_path / "subdir" / ".kanon").resolve()
    assert received == expected_absolute, (
        "E0-INSTALL-RELATIVE regression: install() received wrong resolved path. "
        f"Expected {expected_absolute!r}, got {received!r}."
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "rel_kanon_str",
    [
        ".kanon",
        "./subdir/.kanon",
    ],
    ids=["simple_dot_kanon", "subdir_dot_kanon"],
)
def test_regression_install_receives_absolute_path_for_relative_inputs(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    rel_kanon_str: str,
) -> None:
    """AC-TEST-002: Both relative '.kanon' forms are resolved to absolute paths.

    Parametrized over the two relative path forms that the original
    E0-INSTALL-RELATIVE bug affected. In both cases, install() must receive
    an absolute path, never the original relative Path object.

    If this test fails for any parametrized case, the resolve() call in
    install._run() is not covering that relative path variant.

    AC-TEST-002
    """
    rel_path = pathlib.Path(rel_kanon_str)
    assert not rel_path.is_absolute(), f"Test setup error: {rel_kanon_str!r} must be relative."

    # Create the .kanon file at the location the relative path points to.
    kanon_file = (tmp_path / rel_path).resolve()
    kanon_file.parent.mkdir(parents=True, exist_ok=True)
    kanon_file.write_text(
        "KANON_SOURCE_s_URL=https://example.com/s.git\nKANON_SOURCE_s_REVISION=main\nKANON_SOURCE_s_PATH=m.xml\n"
    )
    monkeypatch.chdir(tmp_path)

    received_paths: list[pathlib.Path] = []

    def _capture(path: pathlib.Path) -> None:
        received_paths.append(path)

    args = _make_args(rel_path)

    with patch("kanon_cli.commands.install.install", side_effect=_capture):
        with patch("kanon_cli.core.kanonenv.parse_kanonenv"):
            _run(args)

    assert len(received_paths) == 1, f"E0-INSTALL-RELATIVE regression [{rel_kanon_str!r}]: install() not called once."

    received = received_paths[0]
    assert received.is_absolute(), (
        f"E0-INSTALL-RELATIVE regression [{rel_kanon_str!r}]: install() received "
        f"non-absolute path {received!r}. The .resolve() call is missing."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- current fixed code passes
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_current_code_passes_absolute_path_to_install(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-TEST-003: Current fixed code resolves relative '.kanon' to an absolute path.

    Verifies that the existing fix is functionally correct: when _run() is called
    with a relative Path('.kanon') from a directory where .kanon exists, install()
    is called with an absolute path equal to the resolved .kanon file.

    This is the positive assertion that the fix works end-to-end: the relative
    path resolves to an absolute path and install() receives the correct file.

    AC-TEST-003
    """
    kanonenv = write_kanonenv(tmp_path)
    monkeypatch.chdir(tmp_path)

    received_paths: list[pathlib.Path] = []

    def _capture_install(path: pathlib.Path) -> None:
        received_paths.append(path)

    args = _make_args(pathlib.Path(".kanon"))

    with patch("kanon_cli.commands.install.install", side_effect=_capture_install):
        with patch("kanon_cli.core.kanonenv.parse_kanonenv"):
            _run(args)

    assert len(received_paths) == 1
    received = received_paths[0]

    assert received.is_absolute(), (
        "AC-TEST-003: The current fix is not resolving the path to absolute. "
        f"Got {received!r}. Check src/kanon_cli/commands/install.py _run()."
    )

    assert received == kanonenv.resolve(), (
        "AC-TEST-003: The resolved path does not match the expected .kanon location. "
        f"Expected {kanonenv.resolve()!r}, got {received!r}."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- structural guard: resolve() is present in install._run source
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_resolve_call_present_in_install_run_source() -> None:
    """AC-FUNC-001: args.kanonenv_path.resolve() is present in install._run source.

    Inspects the source of install._run() to confirm that the .resolve() call
    used to convert a relative path to absolute is still in place. If this test
    fails, the structural fix for E0-INSTALL-RELATIVE has been removed from
    install._run() and the bug would regress for any relative '.kanon' argument.

    The exact pattern expected is 'args.kanonenv_path = args.kanonenv_path.resolve()'
    which converts any relative pathlib.Path to its resolved absolute counterpart.

    AC-FUNC-001
    """
    source = inspect.getsource(_run)

    assert "args.kanonenv_path.resolve()" in source, (
        "E0-INSTALL-RELATIVE regression guard: args.kanonenv_path.resolve() is no "
        "longer present in install._run(). The fix that converts a relative '.kanon' "
        "path to an absolute path before invoking parse_kanonenv() and install() has "
        "been removed. Restore the following line in install._run() before the "
        "parse_kanonenv() call:\n"
        "    args.kanonenv_path = args.kanonenv_path.resolve()"
    )


@pytest.mark.unit
def test_regression_resolve_precedes_parse_and_install_in_source() -> None:
    """AC-FUNC-001: resolve() appears before parse_kanonenv and install() in _run source.

    Verifies the ordering of the resolve() call relative to the downstream
    parse_kanonenv() and install() calls. The resolve() must happen first so
    that both downstream calls always receive an absolute path.

    If resolve() appears after parse_kanonenv or install in the source, the
    fix is incorrectly positioned and E0-INSTALL-RELATIVE may still regress
    for the first downstream call.

    AC-FUNC-001
    """
    source = inspect.getsource(_run)

    resolve_pos = source.find("args.kanonenv_path.resolve()")
    parse_pos = source.find("parse_kanonenv(")
    install_pos = source.find("install(args.kanonenv_path)")

    assert resolve_pos != -1, (
        "E0-INSTALL-RELATIVE regression guard: resolve() call not found in _run. "
        "See AC-FUNC-001 guard in test_regression_resolve_call_present_in_install_run_source."
    )
    assert parse_pos != -1, (
        "E0-INSTALL-RELATIVE regression guard: parse_kanonenv() call not found in _run. "
        "The install command must call parse_kanonenv() to validate the .kanon file."
    )
    assert install_pos != -1, (
        "E0-INSTALL-RELATIVE regression guard: install(args.kanonenv_path) call not found "
        "in _run. The install command must delegate to core install() after path resolution."
    )

    assert resolve_pos < parse_pos, (
        "E0-INSTALL-RELATIVE regression guard: resolve() appears AFTER parse_kanonenv() "
        "in _run. The path must be resolved to absolute before parse_kanonenv() is called, "
        f"otherwise parse_kanonenv() may receive a relative path. "
        f"resolve() position: {resolve_pos}, parse_kanonenv() position: {parse_pos}"
    )

    assert resolve_pos < install_pos, (
        "E0-INSTALL-RELATIVE regression guard: resolve() appears AFTER install() in _run. "
        "The path must be resolved before install() is invoked. "
        f"resolve() position: {resolve_pos}, install() position: {install_pos}"
    )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001 -- stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_relative_path_success_no_error_on_stdout(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """AC-CHANNEL-001: resolving a relative '.kanon' path does not produce errors on stdout.

    When _run() receives a relative '.kanon' path that resolves to an existing
    file, no error message must appear on stdout. Errors must be written to
    stderr only. This verifies the channel discipline: the resolve() fix must
    not introduce any output on stdout.

    AC-CHANNEL-001
    """
    write_kanonenv(tmp_path)
    monkeypatch.chdir(tmp_path)

    args = _make_args(pathlib.Path(".kanon"))

    with patch("kanon_cli.commands.install.install"):
        with patch("kanon_cli.core.kanonenv.parse_kanonenv"):
            _run(args)

    captured = capsys.readouterr()
    assert "Error" not in captured.out, (
        "AC-CHANNEL-001: An 'Error' message appeared on stdout when resolving a "
        "valid relative '.kanon' path. Error output must go to stderr only. "
        f"stdout content: {captured.out!r}"
    )
    assert ".kanon file not found" not in captured.out, (
        "AC-CHANNEL-001: '.kanon file not found' error leaked to stdout. "
        "All error messages must be written to stderr via print(..., file=sys.stderr). "
        f"stdout content: {captured.out!r}"
    )


@pytest.mark.unit
def test_regression_missing_relative_path_error_goes_to_stderr(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """AC-CHANNEL-001: missing relative '.kanon' error goes to stderr, not stdout.

    When _run() receives a relative '.kanon' path that resolves to a
    non-existent file, the error message must appear on stderr and must NOT
    appear on stdout. This verifies channel discipline for the error path.

    Arrange: Empty tmp_path (no .kanon). chdir to tmp_path.
    Act: Pass relative Path('.kanon') to _run() -- file does not exist.
    Assert: SystemExit(1) raised; error on stderr; nothing on stdout.

    AC-CHANNEL-001
    """
    monkeypatch.chdir(tmp_path)

    args = _make_args(pathlib.Path(".kanon"))

    with pytest.raises(SystemExit) as exc_info:
        _run(args)

    assert exc_info.value.code == 1, (
        f"AC-CHANNEL-001: Expected SystemExit(1) for missing relative '.kanon'. Got exit code {exc_info.value.code!r}."
    )

    captured = capsys.readouterr()

    assert ".kanon file not found" in captured.err, (
        f"AC-CHANNEL-001: '.kanon file not found' error must appear on stderr. stderr content: {captured.err!r}"
    )

    assert ".kanon file not found" not in captured.out, (
        f"AC-CHANNEL-001: '.kanon file not found' error must NOT appear on stdout. stdout content: {captured.out!r}"
    )


# ---------------------------------------------------------------------------
# Additional structural guard: install_module exports _run
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_install_module_has_run_function() -> None:
    """Structural guard: install module exposes _run callable.

    Verifies that the _run function still exists in kanon_cli.commands.install.
    If _run is renamed or removed, the install command entry point is broken
    and the regression guards above would all fail to import.

    AC-FUNC-001
    """
    assert hasattr(install_module, "_run"), (
        "E0-INSTALL-RELATIVE regression guard: _run is no longer present in "
        "kanon_cli.commands.install. The install command entry point has been "
        "renamed or removed. Restore _run() in src/kanon_cli/commands/install.py."
    )
    assert callable(install_module._run), (
        "E0-INSTALL-RELATIVE regression guard: install_module._run is not callable. "
        "Expected a function, got {type(install_module._run)!r}."
    )
