"""Tests verifying that __file__-based path resolutions work correctly.

Each module in kanon_cli.repo that uses __file__ to locate adjacent resources
must resolve paths relative to its own location under src/kanon_cli/repo/.
This test suite verifies that every such path resolves to a file or directory
that actually exists in the expected location.
"""

import pathlib

import pytest

REPO_PACKAGE_DIR = pathlib.Path(__file__).parents[3] / "src" / "kanon_cli" / "repo"
"""Absolute path to the kanon_cli.repo package directory."""

KANON_CLI_DIR = pathlib.Path(__file__).parents[3] / "src" / "kanon_cli"
"""Absolute path to the kanon_cli package directory."""

SUBCMDS_DIR = REPO_PACKAGE_DIR / "subcmds"
"""Absolute path to the kanon_cli.repo.subcmds package directory."""


@pytest.mark.unit
def test_wrapper_path_resolves_to_repo_script() -> None:
    """WrapperPath() must resolve to the repo script adjacent to wrapper.py.

    The repo script is a launcher at src/kanon_cli/repo/repo.
    WrapperPath() uses pathlib.Path(__file__).resolve().parent / "repo" so
    it locates the script relative to wrapper.py's own location.
    """
    from kanon_cli.repo.wrapper import WrapperPath

    resolved = pathlib.Path(WrapperPath()).resolve()
    expected = (REPO_PACKAGE_DIR / "repo").resolve()

    assert resolved == expected, (
        f"WrapperPath() resolved to {resolved!r} but expected {expected!r}. "
        f"Ensure wrapper.py uses pathlib.Path(__file__).resolve().parent / 'repo'."
    )
    assert resolved.exists(), (
        f"WrapperPath() points to {resolved!r} which does not exist. "
        f"The repo script must be present at src/kanon_cli/repo/repo."
    )


@pytest.mark.unit
def test_wrapper_path_uses_pathlib() -> None:
    """WrapperPath() implementation must use pathlib.Path(__file__).resolve().parent.

    The pathlib-based pattern is more robust and explicit than os.path.dirname.
    """
    import inspect
    import kanon_cli.repo.wrapper as wrapper_module

    source = inspect.getsource(wrapper_module.WrapperPath)

    assert "pathlib.Path(__file__).resolve().parent" in source, (
        "WrapperPath() must use 'pathlib.Path(__file__).resolve().parent' "
        "for path resolution. Old os.path pattern must be replaced."
    )


@pytest.mark.unit
def test_ssh_proxy_path_resolves_to_git_ssh() -> None:
    """PROXY_PATH must resolve to the git_ssh helper adjacent to ssh.py.

    The git_ssh helper is at src/kanon_cli/repo/git_ssh.
    PROXY_PATH is computed using pathlib.Path(__file__).resolve().parent / "git_ssh"
    so it locates the helper relative to ssh.py's own location.
    """
    from kanon_cli.repo import ssh

    resolved = pathlib.Path(ssh.PROXY_PATH).resolve()
    expected = (REPO_PACKAGE_DIR / "git_ssh").resolve()

    assert resolved == expected, (
        f"ssh.PROXY_PATH resolved to {resolved!r} but expected {expected!r}. "
        f"Ensure ssh.py uses pathlib.Path(__file__).resolve().parent / 'git_ssh'."
    )
    assert resolved.exists(), (
        f"ssh.PROXY_PATH points to {resolved!r} which does not exist. "
        f"The git_ssh helper must be present at src/kanon_cli/repo/git_ssh."
    )


@pytest.mark.unit
def test_ssh_proxy_path_uses_pathlib() -> None:
    """PROXY_PATH must be set using pathlib.Path(__file__).resolve().parent.

    The pathlib-based pattern is more robust and explicit than os.path.dirname.
    """
    import inspect
    import kanon_cli.repo.ssh as ssh_module

    # PROXY_PATH is a module-level assignment, so we inspect the module source
    source = inspect.getsource(ssh_module)

    assert "pathlib.Path(__file__).resolve().parent" in source, (
        "ssh.py must use 'pathlib.Path(__file__).resolve().parent' "
        "to set PROXY_PATH. Old os.path.dirname pattern must be replaced."
    )


@pytest.mark.unit
def test_repo_trace_does_not_use_file_for_trace_dir() -> None:
    """_GetTraceFile must not use __file__ to derive the trace file location.

    The trace file location must NOT be computed by navigating ancestor
    directories of __file__, which would place trace files inside the
    installed kanon_cli package. Instead, cwd() or tempfile must be used.
    This test verifies the implementation by checking the source directly.
    """
    import inspect
    import kanon_cli.repo.repo_trace as repo_trace_module

    source = inspect.getsource(repo_trace_module._GetTraceFile)

    # Must NOT use __file__ to navigate to a parent directory for trace output.
    # The original pattern was os.path.dirname(os.path.dirname(__file__))
    # which points into the installed package directory.
    assert "__file__" not in source, (
        "_GetTraceFile must not use '__file__' to compute the trace directory. "
        "Use pathlib.Path.cwd() or tempfile.gettempdir() instead so trace "
        "files are placed in the working directory or temp dir, not inside "
        "the installed kanon_cli package."
    )


@pytest.mark.unit
def test_repo_trace_file_not_inside_package() -> None:
    """_GetTraceFile must return a path outside the installed kanon_cli package.

    When REPO_TRACE is enabled and the working directory is writable, the
    trace file must be placed in cwd, not inside src/kanon_cli/.
    """
    import kanon_cli.repo.repo_trace as repo_trace_module

    trace_path = pathlib.Path(repo_trace_module._GetTraceFile(quiet=True)).resolve()
    kanon_cli_resolved = KANON_CLI_DIR.resolve()

    assert not str(trace_path).startswith(str(kanon_cli_resolved)), (
        f"_GetTraceFile returned {trace_path!r} which is inside the installed "
        f"kanon_cli package at {kanon_cli_resolved!r}. "
        f"repo_trace.py must use pathlib.Path.cwd() or tempfile.gettempdir() "
        f"so that traces go to the working directory or temp dir."
    )


@pytest.mark.unit
def test_git_command_repo_source_version_uses_pathlib() -> None:
    """RepoSourceVersion must use pathlib.Path(__file__).resolve().parent for proj.

    The function computes a project path used to locate the .git directory.
    After relocation to src/kanon_cli/repo/, the path must resolve relative to
    the module's location using pathlib, not the legacy os.path.abspath pattern.
    """
    import inspect
    import kanon_cli.repo.git_command as gc

    source = inspect.getsource(gc.RepoSourceVersion)

    assert "pathlib.Path(__file__).resolve().parent" in source, (
        "RepoSourceVersion() must use 'pathlib.Path(__file__).resolve().parent' "
        "to compute the project directory. Found source does not contain this pattern."
    )
    assert "os.path.abspath(__file__)" not in source, (
        "RepoSourceVersion() must not use 'os.path.abspath(__file__)'. "
        "Replace with pathlib.Path(__file__).resolve().parent."
    )


@pytest.mark.unit
def test_project_hooks_uses_pathlib() -> None:
    """_ProjectHooks must use pathlib.Path(__file__).resolve().parent for the hooks dir.

    The hooks directory is at src/kanon_cli/repo/hooks/.
    project.py must use pathlib.Path(__file__).resolve().parent to locate it,
    not os.path.realpath(os.path.abspath(os.path.dirname(__file__))).
    """
    import inspect
    import kanon_cli.repo.project as project_module

    source = inspect.getsource(project_module._ProjectHooks)

    assert "pathlib.Path(__file__).resolve().parent" in source, (
        "_ProjectHooks() must use 'pathlib.Path(__file__).resolve().parent' "
        "to locate the hooks directory. Old os.path pattern must be replaced."
    )

    # Verify the hooks directory actually exists and has files
    hooks_dir = (REPO_PACKAGE_DIR / "hooks").resolve()
    assert hooks_dir.is_dir(), (
        f"Hooks directory not found at {hooks_dir!r}. "
        f"The hooks/ directory must be present at src/kanon_cli/repo/hooks/."
    )
    hook_files = list(hooks_dir.iterdir())
    assert len(hook_files) > 0, (
        f"Hooks directory {hooks_dir!r} is empty. Expected at least one hook file to be present."
    )


@pytest.mark.unit
def test_manifest_help_doc_resolves_to_package_docs() -> None:
    """manifest.py helpDescription must locate docs/manifest-format.md correctly.

    The docs directory is at src/kanon_cli/repo/docs/manifest-format.md.
    subcmds/manifest.py must use pathlib.Path(__file__).resolve().parent.parent
    to navigate from subcmds/ up to repo/, then find docs/manifest-format.md.
    """
    import inspect
    import kanon_cli.repo.subcmds.manifest as manifest_module

    source = inspect.getsource(manifest_module.Manifest.helpDescription.fget)

    assert "pathlib.Path(__file__).resolve().parent" in source, (
        "manifest.py helpDescription must use 'pathlib.Path(__file__).resolve().parent' "
        "to locate the docs directory. Found source does not contain this pattern."
    )

    # Verify the actual docs file exists at the expected location
    docs_file = (REPO_PACKAGE_DIR / "docs" / "manifest-format.md").resolve()
    assert docs_file.is_file(), (
        f"manifest-format.md not found at {docs_file!r}. "
        f"The file must exist at src/kanon_cli/repo/docs/manifest-format.md."
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "module_path,expected_file",
    [
        ("wrapper", "repo"),
        ("ssh", "git_ssh"),
    ],
)
def test_adjacent_script_files_exist(module_path: str, expected_file: str) -> None:
    """Verify that scripts referenced by __file__-relative paths actually exist.

    Args:
        module_path: Module name within kanon_cli.repo.
        expected_file: Script filename expected adjacent to the module.
    """
    expected = (REPO_PACKAGE_DIR / expected_file).resolve()
    assert expected.exists(), (
        f"Expected {expected_file!r} to exist at {expected!r} adjacent to "
        f"kanon_cli.repo.{module_path}, but the file was not found. "
        f"Ensure the file is present at src/kanon_cli/repo/{expected_file}."
    )
