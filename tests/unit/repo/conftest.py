"""Shared test helpers for tests/unit/repo/.

Configures sys.path so that the verbatim test files (which use relative bare
imports like ``from test_manifest_xml import ...``) can locate sibling test
modules during collection.

Provides pytest fixtures used across the repo test suite:

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
import sys

import pytest

import kanon_cli.repo.color as color
import kanon_cli.repo.platform_utils as platform_utils
import kanon_cli.repo.repo_trace as repo_trace

SMOKE_TEST_TIMEOUT_ENV_VAR = "SMOKE_TEST_TIMEOUT"

REPO_ROOT = pathlib.Path(__file__).parents[3]
"""Root of the kanon repository (3 levels up from tests/unit/repo/)."""

TARGET_DIR = REPO_ROOT / "src" / "kanon_cli" / "repo"
"""Package directory for the kanon_cli.repo subsystem."""

_THIS_DIR = str(pathlib.Path(__file__).parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)


# ---------------------------------------------------------------------------
# Auto-apply the unit marker to every test in this directory.
#
# The upstream files under tests/unit/repo/ were copied from the Gerrit repo
# test suite, which predates the project-level pytest marker conventions
# (unit / integration / functional). This hook applies @pytest.mark.unit to
# any test collected from tests/unit/repo/** that does not already carry one
# of the three registered markers, so every test runs under exactly one of
# the three make targets (make test-unit / test-integration / test-functional)
# and nothing is orphaned.
# ---------------------------------------------------------------------------


_MARKERS = {"unit", "integration", "functional"}


def pytest_collection_modifyitems(config, items):
    """Apply @pytest.mark.unit to unmarked items collected under tests/unit/repo/."""
    this_dir = pathlib.Path(__file__).resolve().parent
    for item in items:
        try:
            item_path = pathlib.Path(str(item.fspath)).resolve()
        except (AttributeError, OSError):
            continue
        try:
            item_path.relative_to(this_dir)
        except ValueError:
            continue
        if any(mark.name in _MARKERS for mark in item.iter_markers()):
            continue
        item.add_marker(pytest.mark.unit)


# ---------------------------------------------------------------------------
# Shared pytest fixtures for the repo test suite.
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


@pytest.fixture
def subprocess_timeout() -> int:
    """Return the timeout in seconds for subprocess calls in functional tests.

    Reads from the SMOKE_TEST_TIMEOUT environment variable which is
    exported by the Makefile test-functional target.

    Returns:
        Timeout value in seconds.

    Raises:
        RuntimeError: If SMOKE_TEST_TIMEOUT is not set or is not a positive integer.
    """
    value = os.environ.get(SMOKE_TEST_TIMEOUT_ENV_VAR)
    if value is None:
        raise RuntimeError(
            f"{SMOKE_TEST_TIMEOUT_ENV_VAR} environment variable is not set. "
            "Run functional tests via 'make test-functional' or "
            f"export {SMOKE_TEST_TIMEOUT_ENV_VAR}=<seconds> before running pytest."
        )
    try:
        timeout = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{SMOKE_TEST_TIMEOUT_ENV_VAR} must be a positive integer, got: '{value}'") from exc
    if timeout <= 0:
        raise RuntimeError(f"{SMOKE_TEST_TIMEOUT_ENV_VAR} must be a positive integer, got: {timeout}")
    return timeout


# ---------------------------------------------------------------------------
# Kanon repo root fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo_root() -> str:
    """Return the absolute path to the kanon repository root as a string.

    This fixture provides the repository root directory to tests that need
    to locate files relative to the project root (e.g., pyproject.toml,
    .yamllint, tests/fixtures/).

    Returns:
        Absolute path string for the kanon repository root.
    """
    return str(REPO_ROOT)


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
