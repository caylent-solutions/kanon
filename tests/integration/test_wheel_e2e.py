"""E2E integration tests: install kanon wheel in isolated venv and verify repo works.

These tests build the wheel, install it into an isolated virtual environment
(created inside tmp_path so it is fully disposable), and then verify that:

1. kanon_cli.repo can be imported from the installed wheel.
2. repo_init runs successfully against a real file:// git repository.
3. The wheel contains all Python files under kanon_cli/repo/.
4. The wheel contains all non-Python runtime files (hooks, docs, etc.).

No network access is required -- all git operations use file:// URLs backed
by bare repositories created in tmp_path.

AC-TEST-001: test_wheel_install_and_repo_init
AC-TEST-002: test_wheel_contains_all_repo_files
AC-TEST-003: test_wheel_repo_non_python_files_present
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Generator

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).parents[2]
"""Root of the kanon repository (2 levels up from tests/integration/)."""

_REPO_PREFIX = "kanon_cli/repo/"
_SUBCMDS_PREFIX = "kanon_cli/repo/subcmds/"

_GIT_USER_NAME = "Wheel E2E Test User"
_GIT_USER_EMAIL = "wheel-e2e@example.com"
_MANIFEST_FILENAME = "default.xml"

# Expected Python files in kanon_cli/repo/ (root level, excluding __init__.py)
_ROOT_REPO_PYTHON_FILES = [
    "color.py",
    "command.py",
    "editor.py",
    "error.py",
    "event_log.py",
    "fetch.py",
    "git_command.py",
    "git_config.py",
    "git_refs.py",
    "git_superproject.py",
    "git_trace2_event_log.py",
    "git_trace2_event_log_base.py",
    "hooks.py",
    "main.py",
    "manifest_xml.py",
    "pager.py",
    "platform_utils.py",
    "platform_utils_win32.py",
    "progress.py",
    "project.py",
    "repo_logging.py",
    "repo_trace.py",
    "ssh.py",
    "version_constraints.py",
    "wrapper.py",
]

# Expected Python files in kanon_cli/repo/subcmds/
_SUBCMD_PYTHON_FILES = [
    "__init__.py",
    "abandon.py",
    "branches.py",
    "checkout.py",
    "cherry_pick.py",
    "diff.py",
    "diffmanifests.py",
    "download.py",
    "envsubst.py",
    "forall.py",
    "gc.py",
    "grep.py",
    "help.py",
    "info.py",
    "init.py",
    "list.py",
    "manifest.py",
    "overview.py",
    "prune.py",
    "rebase.py",
    "selfupdate.py",
    "smartsync.py",
    "stage.py",
    "start.py",
    "status.py",
    "sync.py",
    "upload.py",
]

# Non-Python runtime files relative to kanon_cli/repo/
_NON_PYTHON_RUNTIME_FILES = [
    "repo",
    "git_ssh",
    "hooks/commit-msg",
    "hooks/pre-auto-gc",
    "requirements.json",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_subprocess(args: list[str], cwd: pathlib.Path) -> subprocess.CompletedProcess:
    """Run a subprocess, raising RuntimeError on non-zero exit.

    Args:
        args: Command and arguments to execute.
        cwd: Working directory for the subprocess.

    Returns:
        The CompletedProcess result on success.

    Raises:
        RuntimeError: If the subprocess exits with a non-zero return code.
    """
    result = subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command {args!r} failed with exit code {result.returncode}.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _build_wheel(tmp_dir: pathlib.Path) -> pathlib.Path:
    """Build the kanon-cli wheel into tmp_dir via ``uv build --wheel``.

    Uses ``uv`` as the PEP 517 build driver so the test is independent of the
    interpreter or virtualenv running pytest. Only ``uv`` on PATH is required.

    Args:
        tmp_dir: Temporary directory to write the wheel into.

    Returns:
        Path to the built .whl file.

    Raises:
        RuntimeError: If ``uv`` is not on PATH, if ``uv build`` exits non-zero,
            or if no ``.whl`` file is produced on successful exit.
    """
    uv_executable = shutil.which("uv")
    if uv_executable is None:
        raise RuntimeError(
            "The 'uv' executable is required to build the kanon-cli wheel but was not found on PATH. "
            "Install uv (https://docs.astral.sh/uv/) and ensure it is reachable from the test runner's PATH."
        )
    _run_subprocess(
        [uv_executable, "build", "--wheel", "--out-dir", str(tmp_dir)],
        cwd=REPO_ROOT,
    )
    wheels = list(tmp_dir.glob("*.whl"))
    if not wheels:
        raise RuntimeError(
            f"Wheel build reported success but no .whl file found in {tmp_dir}. "
            "Check the build output for unexpected behavior."
        )
    return wheels[0]


def _create_isolated_venv(venv_dir: pathlib.Path) -> pathlib.Path:
    """Create an isolated virtual environment and return the python executable path.

    Args:
        venv_dir: Directory to create the venv in.

    Returns:
        Path to the Python interpreter inside the venv.

    Raises:
        RuntimeError: If venv creation fails.
    """
    _run_subprocess(
        [sys.executable, "-m", "venv", str(venv_dir)],
        cwd=venv_dir.parent,
    )
    python = venv_dir / "bin" / "python"
    if not python.exists():
        raise RuntimeError(
            f"Expected Python interpreter at {python} after venv creation, "
            f"but it was not found. Contents of {venv_dir}: {list(venv_dir.iterdir())!r}"
        )
    return python


def _install_wheel(python: pathlib.Path, wheel_path: pathlib.Path) -> None:
    """Install the wheel into the venv identified by python.

    Args:
        python: Path to the Python interpreter of the target venv.
        wheel_path: Path to the .whl file to install.

    Raises:
        RuntimeError: If pip install fails.
    """
    _run_subprocess(
        [str(python), "-m", "pip", "install", "--quiet", str(wheel_path)],
        cwd=python.parent.parent,
    )


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd.

    Args:
        args: git subcommand and arguments.
        cwd: Working directory for git.

    Raises:
        RuntimeError: If git exits with a non-zero return code.
    """
    _run_subprocess(["git"] + args, cwd=cwd)


def _make_manifest_repo(base: pathlib.Path, fetch_base_url: str) -> pathlib.Path:
    """Create a bare manifest git repository with a single-project manifest.

    Args:
        base: Parent directory in which all repos are created.
        fetch_base_url: file:// URL of the directory containing bare project repos.

    Returns:
        Absolute path to the bare manifest repository.
    """
    # Create a content repo that the manifest will reference
    content_work = base / "content-work"
    content_work.mkdir(parents=True)
    _git(["init", "-b", "main"], cwd=content_work)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=content_work)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=content_work)
    readme = content_work / "README.md"
    readme.write_text("# content\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=content_work)
    _git(["commit", "-m", "Initial commit"], cwd=content_work)
    content_bare = base / "content-bare"
    _git(["clone", "--bare", str(content_work), str(content_bare)], cwd=base)

    # Create a manifest repo referencing the content bare repo
    manifest_work = base / "manifest-work"
    manifest_work.mkdir(parents=True)
    _git(["init", "-b", "main"], cwd=manifest_work)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=manifest_work)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=manifest_work)

    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{fetch_base_url}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="content-bare" path="project-a" />\n'
        "</manifest>\n"
    )
    (manifest_work / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=manifest_work)
    _git(["commit", "-m", "Add manifest"], cwd=manifest_work)

    manifest_bare = base / "manifest-bare"
    _git(["clone", "--bare", str(manifest_work), str(manifest_bare)], cwd=base)
    return manifest_bare


def _wheel_entry_names(wheel_path: pathlib.Path) -> set[str]:
    """Return the set of all entry names in the wheel zip archive.

    Args:
        wheel_path: Path to the .whl file.

    Returns:
        Set of unique names found in the wheel.

    Raises:
        RuntimeError: If the wheel cannot be opened as a zip archive.
    """
    try:
        with zipfile.ZipFile(wheel_path) as whl:
            return set(whl.namelist())
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"Cannot open wheel {wheel_path} as a zip archive: {exc}") from exc


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built_wheel_path() -> Generator[pathlib.Path, None, None]:
    """Build the kanon-cli wheel once per module and yield its path.

    The wheel is built into a temporary directory that is cleaned up
    automatically after all tests in this module have run.

    Yields:
        Path to the built .whl file.

    Raises:
        RuntimeError: If the build fails or produces no wheel file.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        wheel_path = _build_wheel(pathlib.Path(tmp_dir))
        yield wheel_path


@pytest.fixture(scope="module")
def installed_venv(built_wheel_path: pathlib.Path) -> Generator[pathlib.Path, None, None]:
    """Create an isolated venv, install the wheel, and yield the Python path.

    The venv is created inside a temporary directory that is cleaned up after
    all tests in this module have run.

    Args:
        built_wheel_path: Path to the built wheel (from built_wheel_path fixture).

    Yields:
        Path to the Python interpreter inside the isolated venv.

    Raises:
        RuntimeError: If venv creation or wheel installation fails.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        venv_dir = pathlib.Path(tmp_dir) / "venv"
        python = _create_isolated_venv(venv_dir)
        _install_wheel(python, built_wheel_path)
        yield python


# ---------------------------------------------------------------------------
# AC-TEST-001: test_wheel_install_and_repo_init
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_wheel_install_and_repo_init(
    installed_venv: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    """Install kanon wheel in isolated venv and run repo_init against a file:// repo.

    Builds the kanon-cli wheel, installs it into an isolated virtual
    environment, then invokes kanon_cli.repo.repo_init inside that venv
    via a subprocess Python script against a local file:// manifest git
    repository. Verifies that the .repo/ directory is created successfully.

    No network access is required -- all git operations use file:// URLs.

    AC-TEST-001
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()
    fetch_base_url = f"file://{repos_base}"

    manifest_bare = _make_manifest_repo(repos_base, fetch_base_url)
    manifest_url = f"file://{manifest_bare}"

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Script executed inside the isolated venv to run repo_init
    run_script = (
        "import kanon_cli.repo as repo\n"
        f"repo.repo_init(\n"
        f"    repo_dir={str(workspace)!r},\n"
        f"    url={manifest_url!r},\n"
        f"    revision='main',\n"
        f"    manifest_path={_MANIFEST_FILENAME!r},\n"
        f")\n"
    )

    _run_subprocess(
        [str(installed_venv), "-c", run_script],
        cwd=workspace,
    )

    repo_dot_dir = workspace / ".repo"
    assert repo_dot_dir.is_dir(), (
        f"Expected .repo/ directory at {repo_dot_dir} after repo_init ran from the "
        f"installed wheel, but it was not created. Workspace contents: "
        f"{sorted(str(p) for p in workspace.iterdir())!r}"
    )
    manifests_dir = repo_dot_dir / "manifests"
    assert manifests_dir.is_dir(), (
        f"Expected .repo/manifests/ at {manifests_dir} after repo_init but it was not "
        f"created. .repo/ contents: {sorted(str(p) for p in repo_dot_dir.iterdir())!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-002: test_wheel_contains_all_repo_files
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_wheel_contains_all_repo_files(built_wheel_path: pathlib.Path) -> None:
    """Verify the built wheel includes all Python files under kanon_cli/repo/.

    Inspects the wheel archive (which is a zip file) and confirms that every
    .py file from src/kanon_cli/repo/ (both root-level and subcmds/) is
    present. This validates the hatchling build configuration correctly
    packages the repo subpackage.

    AC-TEST-002
    """
    entry_names = _wheel_entry_names(built_wheel_path)

    missing_root = [
        f"{_REPO_PREFIX}{filename}"
        for filename in _ROOT_REPO_PYTHON_FILES
        if f"{_REPO_PREFIX}{filename}" not in entry_names
    ]
    assert not missing_root, (
        f"The following root-level repo .py files are missing from the wheel:\n"
        f"  {missing_root}\n"
        f"Check [tool.hatch.build.targets.wheel] packages includes 'src/kanon_cli/repo' "
        f"in pyproject.toml. Wheel contains {len(entry_names)} entries."
    )

    missing_init = f"{_REPO_PREFIX}__init__.py"
    assert missing_init in entry_names, (
        f"Expected '{missing_init}' to be present in the wheel but it was not found. "
        f"Check [tool.hatch.build.targets.wheel] packages in pyproject.toml."
    )

    missing_subcmds = [
        f"{_SUBCMDS_PREFIX}{filename}"
        for filename in _SUBCMD_PYTHON_FILES
        if f"{_SUBCMDS_PREFIX}{filename}" not in entry_names
    ]
    assert not missing_subcmds, (
        f"The following subcmds .py files are missing from the wheel:\n"
        f"  {missing_subcmds}\n"
        f"Check [tool.hatch.build.targets.wheel] packages includes 'src/kanon_cli/repo/subcmds' "
        f"in pyproject.toml. Wheel contains {len(entry_names)} entries."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003: test_wheel_repo_non_python_files_present
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_wheel_repo_non_python_files_present(built_wheel_path: pathlib.Path) -> None:
    """Verify the built wheel includes non-Python runtime files from kanon_cli/repo/.

    Inspects the wheel archive and confirms that the required non-Python
    runtime files (git hooks, git_ssh script, requirements.json) are bundled
    inside the wheel.

    AC-TEST-003
    """
    entry_names = _wheel_entry_names(built_wheel_path)

    missing_runtime = [
        f"{_REPO_PREFIX}{relative_path}"
        for relative_path in _NON_PYTHON_RUNTIME_FILES
        if f"{_REPO_PREFIX}{relative_path}" not in entry_names
    ]
    assert not missing_runtime, (
        f"The following non-Python runtime files are missing from the wheel:\n"
        f"  {missing_runtime}\n"
        f"Check [tool.hatch.build.targets.wheel] include list in pyproject.toml "
        f"contains patterns for 'repo', 'git_ssh', 'hooks/*', 'requirements.json'."
    )
