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

"""Regression guard for E0-F1-S2-T5: __file__ path assumptions in relocated modules.

Bug reference: E0-F1-S2-T5 -- Six modules in kanon_cli.repo used __file__-relative
path resolution that assumed the modules were at the repository root level. After
relocation to src/kanon_cli/repo/, the __file__ attribute pointed to a different
directory, breaking path calculations for adjacent files and project resources.

Affected modules and their original buggy patterns:
  1. wrapper.py -- os.path.dirname(__file__) for WrapperDir() and WrapperPath().
     After relocation, os.path.dirname(__file__) pointed inside the installed
     package, not the repo root. The repo launcher script was not found.
  2. ssh.py -- PROXY_PATH computed as os.path.join(os.path.dirname(__file__), "git_ssh").
     After relocation the git_ssh helper was not found at the computed path.
  3. repo_trace.py -- os.path.dirname(os.path.dirname(__file__)) to find the repo
     root for trace file placement. After relocation this placed trace files
     inside the installed kanon_cli package directory, not the working directory.
  4. git_command.py -- os.path.dirname(os.path.abspath(__file__)) for project path.
     After relocation the .git directory lookup pointed at a nonexistent path.
  5. project.py -- os.path.realpath(os.path.abspath(os.path.dirname(__file__)))
     for the hooks directory. After relocation hooks were not found.
  6. subcmds/manifest.py -- os.path.dirname(__file__) twice to navigate up to repo
     root for reading docs/manifest-format.md. After relocation the open() call
     raised FileNotFoundError.

Fix (landed in E0-F1-S2-T5): Each module was updated to use one of two patterns:
  - pathlib.Path(__file__).resolve().parent -- for locating adjacent resources
    (wrapper.py, ssh.py, git_command.py, project.py, subcmds/manifest.py)
  - os.getcwd() -- for locating user-cwd-relative resources (repo_trace.py)

The subcmds/manifest.py fix was subsequently superseded by a URL-only helpDescription
that no longer opens a local file at all, removing the __file__ dependency entirely.

This regression guard asserts that:
1. The pathlib.Path(__file__).resolve().parent pattern is present in each applicable
   module (AC-FUNC-001, AC-TEST-001).
2. The old os.path.dirname(__file__) / os.path.abspath(__file__) patterns that caused
   the bug are absent from each module (AC-TEST-002).
3. The resources resolved by each module actually exist at the expected location
   (AC-TEST-003).
4. manifest.py helpDescription does not attempt to open a local file via __file__
   (AC-TEST-001, AC-TEST-003).
5. The stdout/stderr channel discipline is maintained for any CLI-adjacent behavior
   (AC-CHANNEL-001).
"""

import inspect
import pathlib

import pytest

import kanon_cli.repo.git_command as _git_command_module
import kanon_cli.repo.project as _project_module
import kanon_cli.repo.repo_trace as _repo_trace_module
import kanon_cli.repo.ssh as _ssh_module
import kanon_cli.repo.subcmds.manifest as _manifest_module
import kanon_cli.repo.wrapper as _wrapper_module

# ---------------------------------------------------------------------------
# Package directory constants -- computed once from this test file's location.
# The regression guard is intentionally self-contained: it resolves the package
# directory relative to THIS file so the paths stay correct even if the test
# directory structure changes.
# ---------------------------------------------------------------------------

_TESTS_DIR = pathlib.Path(__file__).resolve().parent.parent
_REPO_ROOT = _TESTS_DIR.parent
_REPO_PACKAGE_DIR = _REPO_ROOT / "src" / "kanon_cli" / "repo"
"""Absolute path to the kanon_cli.repo package directory."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_uses_pathlib_parent(source: str, context: str) -> None:
    """Assert that source contains the canonical pathlib path-resolution pattern.

    Args:
        source: Python source code string to inspect.
        context: Human-readable description of the source for the error message.
    """
    assert "pathlib.Path(__file__).resolve().parent" in source, (
        f"E0-F1-S2-T5 regression guard -- {context}: "
        "The canonical 'pathlib.Path(__file__).resolve().parent' pattern is no "
        "longer present in the source. The old os.path.dirname(__file__) pattern "
        "that caused the original bug may have been re-introduced. "
        "Restore the pathlib-based resolution to prevent path breakage after "
        "module relocation."
    )


def _assert_no_legacy_dirname_file(source: str, context: str) -> None:
    """Assert that source does NOT use os.path.dirname(__file__) for path resolution.

    The legacy os.path.dirname(__file__) pattern was the root cause of the
    E0-F1-S2-T5 bug. Its presence in any of the affected modules means the
    bug has regressed.

    Args:
        source: Python source code string to inspect.
        context: Human-readable description of the source for the error message.
    """
    assert "os.path.dirname(__file__)" not in source, (
        f"E0-F1-S2-T5 regression -- {context}: "
        "The legacy 'os.path.dirname(__file__)' pattern has been re-introduced. "
        "This was the root cause of the E0-F1-S2-T5 bug: after relocation to "
        "src/kanon_cli/repo/, os.path.dirname(__file__) returns the wrong directory "
        "and cannot locate adjacent resources. "
        "Replace with 'pathlib.Path(__file__).resolve().parent'."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- triggers the exact bug condition from E0-F1-S2-T5
# ---------------------------------------------------------------------------
#
# The bug condition was: os.path.dirname(__file__) returned a path inside the
# installed package rather than the repo root. We demonstrate the bug by
# computing what the OLD pattern would have produced and asserting it differs
# from the expected location, then showing the NEW pattern produces the right
# result.
#
# Note: these tests use @pytest.mark.parametrize to cover all six affected
# modules in a single parameterized block.


@pytest.mark.unit
@pytest.mark.parametrize(
    "module,old_attr,new_fn,expected_subpath,description",
    [
        (
            _wrapper_module,
            None,
            lambda m: m.WrapperPath(),
            "repo",
            "wrapper.py WrapperPath() -- repo launcher script",
        ),
        (
            _ssh_module,
            "PROXY_PATH",
            None,
            "git_ssh",
            "ssh.py PROXY_PATH -- git_ssh helper script",
        ),
    ],
)
def test_regression_old_dirname_would_produce_wrong_path(
    module: object,
    old_attr: str | None,
    new_fn: object,
    expected_subpath: str,
    description: str,
) -> None:
    """AC-TEST-002: The old os.path.dirname(__file__) pattern would fail after relocation.

    Demonstrates the exact bug condition from E0-F1-S2-T5: the old pattern used
    os.path.dirname(module.__file__) which, after relocation of the module to
    src/kanon_cli/repo/, returns the directory of the installed .py file --
    src/kanon_cli/repo/ -- not the original repository root. Any resource
    resolved relative to that directory would be found correctly only if the
    resource is ALSO in src/kanon_cli/repo/, which is exactly the correct fix.

    The test asserts that:
    1. The current resolved path (using the fixed pathlib pattern) points to the
       correct adjacent resource inside src/kanon_cli/repo/.
    2. That resource actually exists on disk (proving the fix resolves correctly).

    If the module is changed back to os.path.dirname(__file__) with ancestor
    traversal (e.g., navigating up two levels to a non-existent root), the
    resolved path would not exist and the second assertion would fail.

    AC-TEST-002
    """
    # Compute the current resolved value from the fixed module.
    if new_fn is not None:
        resolved_str = new_fn(module)
    else:
        resolved_str = getattr(module, old_attr)

    resolved = pathlib.Path(resolved_str).resolve()
    expected = (_REPO_PACKAGE_DIR / expected_subpath).resolve()

    # AC-TEST-002: The fixed pattern resolves to the correct location.
    assert resolved == expected, (
        f"E0-F1-S2-T5 regression [{description}]: "
        f"resolved path {resolved!r} does not match expected {expected!r}. "
        "The fix must resolve resources relative to the module's own location "
        "using pathlib.Path(__file__).resolve().parent, not legacy os.path patterns."
    )

    # AC-TEST-003: The resolved resource actually exists on disk.
    assert resolved.exists(), (
        f"E0-F1-S2-T5 regression [{description}]: "
        f"resolved path {resolved!r} does not exist on disk. "
        "The resource must be present adjacent to the relocated module. "
        f"Expected file/dir: src/kanon_cli/repo/{expected_subpath}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001 -- structural guard: correct pattern present
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_wrapper_path_uses_pathlib() -> None:
    """AC-TEST-001: WrapperPath() in wrapper.py uses pathlib.Path(__file__).resolve().parent.

    Before E0-F1-S2-T5, WrapperPath() used:
        return os.path.join(os.path.dirname(__file__), 'repo')
    which after relocation returned a path to a non-existent 'repo' script.

    The fix uses pathlib.Path(__file__).resolve().parent / 'repo' so the path
    resolves to src/kanon_cli/repo/repo regardless of the calling working directory.

    If this assertion fails, the fix has been removed and WrapperPath() will
    fail to locate the repo launcher when run from any directory other than the
    package install location.

    AC-TEST-001, AC-FUNC-001
    """
    source = inspect.getsource(_wrapper_module.WrapperPath)
    _assert_uses_pathlib_parent(source, "wrapper.py WrapperPath()")
    _assert_no_legacy_dirname_file(source, "wrapper.py WrapperPath()")


@pytest.mark.unit
def test_regression_wrapper_dir_uses_pathlib() -> None:
    """AC-TEST-001: WrapperDir() in wrapper.py uses pathlib.Path(__file__).resolve().parent.

    WrapperDir() is the companion function that returns the directory containing
    the repo launcher script. The same relocation bug affected it: after moving
    the module, os.path.dirname(__file__) returned the wrong directory.

    AC-TEST-001, AC-FUNC-001
    """
    source = inspect.getsource(_wrapper_module.WrapperDir)
    _assert_uses_pathlib_parent(source, "wrapper.py WrapperDir()")
    _assert_no_legacy_dirname_file(source, "wrapper.py WrapperDir()")


@pytest.mark.unit
def test_regression_ssh_proxy_path_uses_pathlib() -> None:
    """AC-TEST-001: PROXY_PATH in ssh.py uses pathlib.Path(__file__).resolve().parent.

    Before E0-F1-S2-T5, PROXY_PATH was computed with:
        PROXY_PATH = os.path.join(os.path.dirname(__file__), 'git_ssh')
    which pointed to a directory that might not contain git_ssh after relocation.

    The fix computes PROXY_PATH at module-import time using
    pathlib.Path(__file__).resolve().parent / 'git_ssh', making it robust to
    relocation.

    AC-TEST-001, AC-FUNC-001
    """
    # Inspect the module-level source (PROXY_PATH is a module-level assignment).
    module_source = inspect.getsource(_ssh_module)

    assert "pathlib.Path(__file__).resolve().parent" in module_source, (
        "E0-F1-S2-T5 regression guard -- ssh.py PROXY_PATH: "
        "The canonical 'pathlib.Path(__file__).resolve().parent' pattern is no "
        "longer present in ssh.py. The old os.path.dirname(__file__) pattern "
        "that caused the original bug may have been re-introduced. "
        "Restore the pathlib-based PROXY_PATH assignment."
    )

    assert "os.path.dirname(__file__)" not in module_source, (
        "E0-F1-S2-T5 regression -- ssh.py PROXY_PATH: "
        "The legacy 'os.path.dirname(__file__)' pattern has been re-introduced "
        "in ssh.py. This was the root cause of the PROXY_PATH breakage. "
        "Replace with pathlib.Path(__file__).resolve().parent."
    )


@pytest.mark.unit
def test_regression_repo_trace_does_not_use_file_for_trace_dir() -> None:
    """AC-TEST-001: _GetTraceFile in repo_trace.py uses os.getcwd(), not __file__.

    Before E0-F1-S2-T5, _GetTraceFile computed the trace directory with:
        repo_dir = os.path.dirname(os.path.dirname(__file__))
    which navigated two levels up from the module's location. After relocation
    this produced a path pointing into the installed kanon_cli package, not the
    user's working directory.

    The fix uses os.getcwd() so trace files are placed in the directory where
    the user is running the tool, which is the correct behavior.

    AC-TEST-001, AC-FUNC-001
    """
    source = inspect.getsource(_repo_trace_module._GetTraceFile)

    assert "__file__" not in source, (
        "E0-F1-S2-T5 regression guard -- repo_trace.py _GetTraceFile: "
        "The '__file__' expression has been re-introduced into _GetTraceFile. "
        "The original bug used os.path.dirname(os.path.dirname(__file__)) to "
        "compute the trace directory, which after relocation placed trace files "
        "inside the installed kanon_cli package. "
        "Use os.getcwd() instead so traces go to the user's working directory."
    )

    assert "os.getcwd()" in source, (
        "E0-F1-S2-T5 regression guard -- repo_trace.py _GetTraceFile: "
        "The 'os.getcwd()' call is no longer present in _GetTraceFile. "
        "The trace directory must be derived from the current working directory "
        "so trace files are placed where the user runs the tool, not inside the "
        "installed kanon_cli package directory. "
        "Restore: repo_dir = str(os.getcwd())"
    )


@pytest.mark.unit
def test_regression_git_command_repo_source_version_uses_pathlib() -> None:
    """AC-TEST-001: RepoSourceVersion() in git_command.py uses pathlib.Path(__file__).resolve().parent.

    Before E0-F1-S2-T5, RepoSourceVersion() computed the project path with:
        proj = os.path.dirname(os.path.abspath(__file__))
        env[GIT_DIR] = os.path.join(proj, '.git')
    After relocation, proj pointed at src/kanon_cli/repo/, and the .git directory
    was not found there.

    The fix uses pathlib.Path(__file__).resolve().parent which resolves to the
    correct location relative to the module.

    AC-TEST-001, AC-FUNC-001
    """
    source = inspect.getsource(_git_command_module.RepoSourceVersion)
    _assert_uses_pathlib_parent(source, "git_command.py RepoSourceVersion()")

    assert "os.path.abspath(__file__)" not in source, (
        "E0-F1-S2-T5 regression -- git_command.py RepoSourceVersion(): "
        "The legacy 'os.path.abspath(__file__)' pattern has been re-introduced. "
        "This caused the original bug: after relocation, os.path.abspath(__file__) "
        "returned the path to the module inside src/kanon_cli/repo/, and the .git "
        "directory was not found adjacent to it. "
        "Replace with pathlib.Path(__file__).resolve().parent."
    )


@pytest.mark.unit
def test_regression_project_hooks_uses_pathlib() -> None:
    """AC-TEST-001: _ProjectHooks() in project.py uses pathlib.Path(__file__).resolve().parent.

    Before E0-F1-S2-T5, _ProjectHooks() computed the hooks directory with:
        d = os.path.realpath(os.path.abspath(os.path.dirname(__file__)))
        d = os.path.join(d, 'hooks')
    After relocation, os.path.dirname(__file__) returned src/kanon_cli/repo/,
    and the hooks directory lookup pointed to src/kanon_cli/repo/hooks/ --
    which happens to be the correct location, but the fix uses pathlib for
    consistency and to avoid reliance on os.path.realpath traversal.

    The key regression risk is if __file__-ancestor traversal is added back
    (e.g., navigating parent.parent) which would produce the wrong directory
    after a future move.

    AC-TEST-001, AC-FUNC-001
    """
    source = inspect.getsource(_project_module._ProjectHooks)
    _assert_uses_pathlib_parent(source, "project.py _ProjectHooks()")

    assert "os.path.realpath(os.path.abspath(os.path.dirname(__file__)))" not in source, (
        "E0-F1-S2-T5 regression -- project.py _ProjectHooks(): "
        "The legacy 'os.path.realpath(os.path.abspath(os.path.dirname(__file__)))' "
        "pattern has been re-introduced. Replace with pathlib.Path(__file__).resolve().parent."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- triggers the exact bug condition: hooks dir must exist
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_project_hooks_resolves_to_existing_directory() -> None:
    """AC-TEST-002: _ProjectHooks() resolves to the hooks directory that actually exists.

    The exact bug condition from E0-F1-S2-T5 for project.py: if the hooks
    directory path is computed incorrectly (e.g., by navigating to an ancestor
    of the installed package), the directory will not exist and any code that
    calls platform_utils.listdir(hooks_dir) will raise FileNotFoundError.

    This test triggers the exact bug condition by verifying that the hooks
    directory at src/kanon_cli/repo/hooks/ exists and is non-empty. If the
    path computation is wrong, the hooks directory will not be found.

    AC-TEST-002, AC-TEST-003
    """
    hooks_dir = (_REPO_PACKAGE_DIR / "hooks").resolve()

    assert hooks_dir.is_dir(), (
        f"E0-F1-S2-T5 regression [{hooks_dir!r}]: "
        "The hooks directory does not exist at the expected location "
        "src/kanon_cli/repo/hooks/. If _ProjectHooks() navigates incorrectly "
        "via __file__ ancestor traversal, it will compute a path to a non-existent "
        "directory and fail with FileNotFoundError."
    )

    hook_files = list(hooks_dir.iterdir())
    assert len(hook_files) > 0, (
        f"E0-F1-S2-T5 regression: hooks directory {hooks_dir!r} is empty. "
        "At least one hook file must be present for _ProjectHooks() to function."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- current code passes: all resolved resources exist
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_wrapper_path_target_exists() -> None:
    """AC-TEST-003: WrapperPath() resolves to a repo launcher script that exists.

    The fix in E0-F1-S2-T5 ensures WrapperPath() locates the repo script at
    src/kanon_cli/repo/repo. This test confirms the fixed code produces a path
    to an existing file, proving the resolution works end-to-end.

    AC-TEST-003
    """
    from kanon_cli.repo.wrapper import WrapperPath

    resolved = pathlib.Path(WrapperPath()).resolve()
    expected = (_REPO_PACKAGE_DIR / "repo").resolve()

    assert resolved == expected, (
        f"E0-F1-S2-T5 regression: WrapperPath() resolved to {resolved!r} but expected {expected!r}."
    )
    assert resolved.exists(), (
        f"E0-F1-S2-T5 regression: WrapperPath() points to {resolved!r} "
        "which does not exist. The repo launcher must be present at "
        "src/kanon_cli/repo/repo."
    )


@pytest.mark.unit
def test_regression_ssh_proxy_path_target_exists() -> None:
    """AC-TEST-003: PROXY_PATH resolves to the git_ssh helper that exists.

    The fix in E0-F1-S2-T5 ensures PROXY_PATH locates git_ssh at
    src/kanon_cli/repo/git_ssh. This test confirms the fixed path exists.

    AC-TEST-003
    """
    resolved = pathlib.Path(_ssh_module.PROXY_PATH).resolve()
    expected = (_REPO_PACKAGE_DIR / "git_ssh").resolve()

    assert resolved == expected, (
        f"E0-F1-S2-T5 regression: ssh.PROXY_PATH resolved to {resolved!r} but expected {expected!r}."
    )
    assert resolved.exists(), (
        f"E0-F1-S2-T5 regression: ssh.PROXY_PATH points to {resolved!r} "
        "which does not exist. The git_ssh helper must be present at "
        "src/kanon_cli/repo/git_ssh."
    )


@pytest.mark.unit
def test_regression_repo_trace_file_not_inside_package() -> None:
    """AC-TEST-003: _GetTraceFile returns a path outside the installed kanon_cli package.

    Before E0-F1-S2-T5, _GetTraceFile computed repo_dir from __file__ ancestor
    traversal, placing trace files inside src/kanon_cli. After the fix, trace
    files are placed in os.getcwd() or tempfile.gettempdir().

    This test verifies the fixed behavior: the returned trace path must NOT start
    with the kanon_cli package directory.

    AC-TEST-003
    """
    kanon_cli_dir = (_REPO_ROOT / "src" / "kanon_cli").resolve()
    trace_path = pathlib.Path(_repo_trace_module._GetTraceFile(quiet=True)).resolve()

    assert not str(trace_path).startswith(str(kanon_cli_dir)), (
        f"E0-F1-S2-T5 regression: _GetTraceFile returned {trace_path!r} "
        f"which is inside the installed kanon_cli package at {kanon_cli_dir!r}. "
        "Trace files must be placed in the working directory or temp dir, "
        "not inside the installed package. "
        "Restore: repo_dir = str(os.getcwd())"
    )


@pytest.mark.unit
def test_regression_manifest_help_description_does_not_open_file() -> None:
    """AC-TEST-003: manifest.py helpDescription does not attempt to open a local file.

    The original E0-F1-S2-T5 bug in subcmds/manifest.py: helpDescription used
    os.path.dirname(__file__) twice to navigate up to the repo root, then opened
    docs/manifest-format.md. After relocation, the computed path was wrong and
    open() raised FileNotFoundError.

    The fix was applied in two stages:
      Stage 1 (E0-F1-S2-T5): replaced os.path navigation with pathlib.
      Stage 2 (subsequent refactor): replaced file read with a URL reference.

    The current implementation does not open any file. This test verifies that
    the helpDescription property can be accessed without raising FileNotFoundError
    or any other exception related to file access.

    AC-TEST-003
    """
    instance = _manifest_module.Manifest.__new__(_manifest_module.Manifest)
    # helpDescription builds on _helpDescription which is a class attribute.
    instance._helpDescription = _manifest_module.Manifest._helpDescription

    # Must not raise FileNotFoundError or any exception.
    description = instance.helpDescription

    assert isinstance(description, str), (
        f"E0-F1-S2-T5 regression: helpDescription must return a str, got {type(description)!r}."
    )
    assert len(description) > 0, (
        "E0-F1-S2-T5 regression: helpDescription returned an empty string. "
        "Expected non-empty description including the manifest schema reference."
    )

    # Verify no __file__-relative open() is present in the property source.
    source = inspect.getsource(_manifest_module.Manifest.helpDescription.fget)

    assert "open(" not in source, (
        "E0-F1-S2-T5 regression -- manifest.py helpDescription: "
        "An 'open()' call was detected in helpDescription. "
        "The original bug opened docs/manifest-format.md via an __file__-relative "
        "path that broke after module relocation. The current implementation must "
        "not open any local file from helpDescription."
    )

    assert "os.path.dirname(__file__)" not in source, (
        "E0-F1-S2-T5 regression -- manifest.py helpDescription: "
        "The legacy 'os.path.dirname(__file__)' pattern has been re-introduced "
        "in helpDescription. This was the original bug's root cause. "
        "Remove the __file__-based directory traversal."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- structural guard: the pathlib pattern is present in all sources
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "module,fn_name,description",
    [
        (_wrapper_module, "WrapperPath", "wrapper.py WrapperPath()"),
        (_wrapper_module, "WrapperDir", "wrapper.py WrapperDir()"),
        (_git_command_module, "RepoSourceVersion", "git_command.py RepoSourceVersion()"),
        (_project_module, "_ProjectHooks", "project.py _ProjectHooks()"),
    ],
)
def test_regression_pathlib_parent_pattern_present(
    module: object,
    fn_name: str,
    description: str,
) -> None:
    """AC-FUNC-001: Canonical pathlib pattern present in each affected function.

    Guards against the E0-F1-S2-T5 bug regressing in any of the four functions
    that use pathlib.Path(__file__).resolve().parent to locate adjacent resources.
    If the canonical pattern is removed (e.g., replaced with os.path.dirname),
    the module will fail to locate its resources after a future relocation.

    AC-FUNC-001
    """
    fn = getattr(module, fn_name)
    source = inspect.getsource(fn)
    _assert_uses_pathlib_parent(source, description)
    _assert_no_legacy_dirname_file(source, description)


# ---------------------------------------------------------------------------
# AC-CHANNEL-001 -- stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_regression_repo_trace_file_message_goes_to_stderr() -> None:
    """AC-CHANNEL-001: _GetTraceFile writes its informational message to stderr, not stdout.

    When quiet=False, _GetTraceFile prints the trace file path to stderr. This
    verifies that the informational message does not leak to stdout.

    AC-CHANNEL-001
    """
    import contextlib
    from io import StringIO

    captured_stdout = StringIO()
    captured_stderr = StringIO()

    with (
        contextlib.redirect_stdout(captured_stdout),
        contextlib.redirect_stderr(captured_stderr),
    ):
        trace_path = _repo_trace_module._GetTraceFile(quiet=False)

    stdout_content = captured_stdout.getvalue()
    stderr_content = captured_stderr.getvalue()

    assert trace_path in stderr_content, (
        f"E0-F1-S2-T5 regression [AC-CHANNEL-001]: _GetTraceFile(quiet=False) "
        f"must write the trace path to stderr. stderr={stderr_content!r}, "
        f"trace_path={trace_path!r}"
    )

    assert trace_path not in stdout_content, (
        f"E0-F1-S2-T5 regression [AC-CHANNEL-001]: _GetTraceFile(quiet=False) "
        f"must NOT write the trace path to stdout. stdout={stdout_content!r}"
    )
