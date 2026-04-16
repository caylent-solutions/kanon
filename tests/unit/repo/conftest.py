"""Shared test helpers for tests/unit/repo/.

Provides reusable utilities for content-match tests that verify copied
rpm-git-repo source files against their originals.

Also configures sys.path so that the verbatim-copied rpm-git-repo test files
(which use relative bare imports like ``from test_manifest_xml import ...``)
can locate sibling test modules during collection.  Import fixes for these
files happen in E0-F5-S1-T3; this path entry is the minimal change needed to
prevent collection errors while those files are still unmodified.

Also provides pytest fixtures adapted from rpm-git-repo's conftest.py for
use by the repo test suite:

- reset_color_default
- disable_repo_trace
- session_tmp_home_dir
- tmp_home_dir
- setup_user_identity

Additional fixtures loaded from tests/unit/repo/fixtures/:

- mock_manifest_xml
- mock_project_config
"""

import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

import kanon_cli.repo.color as color
import kanon_cli.repo.platform_utils as platform_utils
import kanon_cli.repo.repo_trace as repo_trace

REPO_ROOT = pathlib.Path(__file__).parents[3]
"""Root of the kanon repository (3 levels up from tests/unit/repo/)."""

TARGET_DIR = REPO_ROOT / "src" / "kanon_cli" / "repo"
"""Target directory where rpm-git-repo source files are copied."""

_THIS_DIR = str(pathlib.Path(__file__).parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)


def get_rpm_source_dir(subdirectory: str | None = None) -> pathlib.Path:
    """Return the rpm-git-repo source directory from the RPM_GIT_REPO_PATH env var.

    Skips the calling test via pytest.skip() if RPM_GIT_REPO_PATH is not set,
    so tests are skipped gracefully rather than erroring when the env var is absent.

    Args:
        subdirectory: Optional subdirectory name to append to the source root
            (e.g. ``"subcmds"`` to get the subcmds directory).

    Returns:
        The resolved source directory path.

    Raises:
        RuntimeError: If RPM_GIT_REPO_PATH is set but does not point to an
            existing directory, or if the requested subdirectory does not exist.
    """
    raw = os.environ.get("RPM_GIT_REPO_PATH")
    if not raw:
        pytest.skip("RPM_GIT_REPO_PATH is not set -- skipping content-match tests")
    source_root = pathlib.Path(raw)
    if not source_root.is_dir():
        raise RuntimeError(f"RPM_GIT_REPO_PATH={raw!r} does not point to an existing directory.")
    if subdirectory is None:
        return source_root
    source_dir = source_root / subdirectory
    if not source_dir.is_dir():
        raise RuntimeError(f"Expected {subdirectory!r} directory at {source_dir} but it does not exist.")
    return source_dir


def ruff_format_source(content: bytes) -> str:
    """Run ruff format on the given source bytes and return the formatted string.

    Args:
        content: Raw Python source bytes to format.

    Returns:
        The formatted source as a UTF-8 string.

    Raises:
        subprocess.CalledProcessError: If ruff format exits with a non-zero code.
    """
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--quiet", "-"],
        input=content,
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8")


def strip_noqa_annotations(source: str) -> str:
    """Strip inline ruff lint-suppression annotations from formatted source.

    Args:
        source: Formatted Python source string.

    Returns:
        Source with all ``# noqa`` inline comments removed.
    """
    return re.sub(r"[ \t]+#[ \t]*noqa[^\n]*", "", source)


# ---------------------------------------------------------------------------
# Fixtures adapted from rpm-git-repo tests/conftest.py
# All imports use kanon_cli.repo.* package paths.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_color_default():
    """Prevent test pollution via color.DEFAULT global state."""
    saved = color.DEFAULT
    yield
    color.DEFAULT = saved


@pytest.fixture(autouse=True)
def disable_repo_trace(tmp_path):
    """Set an environment marker to relax certain strict checks for test code."""
    repo_trace._TRACE_FILE = str(tmp_path / "TRACE_FILE_from_test")


def _set_home(monkeypatch, path: pathlib.Path) -> pathlib.Path:
    """Set the home directory using a pytest monkeypatch context.

    Args:
        monkeypatch: A pytest monkeypatch or MonkeyPatch context.
        path: The path to use as HOME.

    Returns:
        The path that was set as HOME.
    """
    win = platform_utils.isWindows()
    env_vars = ["HOME"] + win * ["USERPROFILE"]
    for var in env_vars:
        monkeypatch.setenv(var, str(path))
    return path


@pytest.fixture(scope="session")
def monkeysession():
    """Session-scoped monkeypatch context."""
    with pytest.MonkeyPatch.context() as mp:
        yield mp


@pytest.fixture(autouse=True, scope="session")
def session_tmp_home_dir(tmp_path_factory, monkeysession):
    """Set HOME to a temporary directory, avoiding the user's .gitconfig.

    Set home at session scope to take effect prior to test class setUpClass.
    """
    return _set_home(monkeysession, tmp_path_factory.mktemp("home"))


@pytest.fixture(autouse=True)
def tmp_home_dir(monkeypatch, tmp_path_factory):
    """Set HOME to a temporary directory.

    Ensures that state does not accumulate in $HOME across tests.

    Note that in conjunction with session_tmp_home_dir, the HOME
    directory is patched twice: once at session scope, and then again at
    the function scope.
    """
    return _set_home(monkeypatch, tmp_path_factory.mktemp("home"))


@pytest.fixture(autouse=True)
def setup_user_identity(monkeysession, scope="session"):
    """Set env variables for author and committer name and email."""
    monkeysession.setenv("GIT_AUTHOR_NAME", "Foo Bar")
    monkeysession.setenv("GIT_COMMITTER_NAME", "Foo Bar")
    monkeysession.setenv("GIT_AUTHOR_EMAIL", "foo@bar.baz")
    monkeysession.setenv("GIT_COMMITTER_EMAIL", "foo@bar.baz")


# ---------------------------------------------------------------------------
# Fixtures loaded from tests/unit/repo/fixtures/
# ---------------------------------------------------------------------------

_FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture()
def mock_manifest_xml(tmp_path: pathlib.Path) -> pathlib.Path:
    """Return a path to a temporary copy of the sample manifest XML fixture.

    Copies the golden sample-manifest.xml fixture into tmp_path so each test
    gets an isolated, writable copy.

    Returns:
        Path to the manifest XML file under tmp_path.
    """
    source = _FIXTURES_DIR / "sample-manifest.xml"
    dest = tmp_path / "sample-manifest.xml"
    dest.write_bytes(source.read_bytes())
    return dest


@pytest.fixture()
def mock_project_config() -> dict:
    """Return a project config dict loaded from the sample-project-config.json fixture.

    Returns:
        Dict with keys: name, path, remote, revision, and optional extras.
    """
    source = _FIXTURES_DIR / "sample-project-config.json"
    return json.loads(source.read_text(encoding="utf-8"))
