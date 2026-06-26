"""Functional journey: the ``init.defaultBranch=main`` test prerequisite (item 33).

Proves the *actual effect* of the documented test prerequisite
(``git config --global init.defaultBranch main``, spec E15-F1-S1 /
``docs/integration-testing.md`` "Test prerequisites") on the real default-branch
resolution path (item 3 /
:func:`kanon_cli.core.catalog.resolve_default_branch`).

Unlike the ``git init -b main`` workaround used by the J8 journey
(``test_default_branch_journey.py``) and the integration fixtures, every repo
here is created with a *bare* ``git init`` (no ``-b`` override) inside a HOME
whose global git config sets ``init.defaultBranch``. The initial branch is
therefore chosen by that prerequisite config and nothing else, so a passing
positive case is genuine evidence that setting the prerequisite is what makes
``auto`` / ``@main`` default-branch resolution succeed against a freshly
``git init``-ed local repo.

Covered cases:

- POSITIVE: with ``init.defaultBranch=main`` configured in HOME, a bare
  ``git init`` creates a ``main`` branch, so both the literal ``auto`` symref
  resolution and the ``main`` default verify and return ``main``.
- NEGATIVE: with ``init.defaultBranch=master`` configured in HOME, a bare
  ``git init`` creates only ``master``; the ``main`` default then fails fast with
  the documented :class:`DefaultBranchResolutionError` (``main`` not found on the
  remote), and ``auto`` resolves to ``master`` (so a ``@main`` pin would not
  resolve) -- the exact failure the prerequisite section warns about.

The resolution helper shells out to real ``git ls-remote`` subprocesses that
inherit the process environment, so overriding ``HOME`` (and clearing any
ambient ``GIT_CONFIG_*`` overrides) is what routes both the fixture ``git init``
and the production ``ls-remote`` calls through the same prerequisite config.
"""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

from kanon_cli.constants import CATALOG_DEFAULT_BRANCH_AUTO, CATALOG_DEFAULT_BRANCH_DEFAULT
from kanon_cli.core.catalog import DefaultBranchResolutionError, resolve_default_branch
from kanon_cli.version import _list_branch_head


_GIT_USER_NAME = "Init Default Branch User"
_GIT_USER_EMAIL = "init-default-branch@example.com"
_CONTENT_FILE = "README.md"
_CONTENT_TEXT = "init.defaultBranch prerequisite content"
_BRANCH_MAIN = "main"
_BRANCH_MASTER = "master"
_GIT_CONFIG_OVERRIDE_ENV_VARS = (
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_NOSYSTEM",
)


def _git(args: list[str], cwd: pathlib.Path, home: pathlib.Path) -> subprocess.CompletedProcess[str]:
    """Run a git command with ``HOME`` pinned to *home*, raising on non-zero exit.

    Passing ``home`` explicitly through the subprocess environment ensures the
    fixture git invocations read the same global ``init.defaultBranch`` config
    that the production resolution path reads from the inherited process HOME.
    """
    env = {"HOME": str(home), "PATH": _path_env()}
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {args!r} failed in {cwd!r} (HOME={home!r}):\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
    return result


def _path_env() -> str:
    """Return the current ``PATH`` so the subprocess can locate the git binary."""
    return os.environ.get("PATH", "")


def _configure_home_default_branch(home: pathlib.Path, default_branch: str) -> None:
    """Write ``init.defaultBranch=<default_branch>`` into *home*'s global git config.

    This mirrors the documented prerequisite command
    (``git config --global init.defaultBranch main``) and the negative variant
    that leaves new repos on ``master``.
    """
    home.mkdir(parents=True, exist_ok=True)
    _git(["config", "--global", "init.defaultBranch", default_branch], cwd=home, home=home)


def _build_committed_repo(work: pathlib.Path, home: pathlib.Path) -> str:
    """Create a committed git work repo via a *bare* ``git init`` and return its ``file://`` URL.

    No ``-b`` override is passed, so the initial branch is dictated solely by the
    ``init.defaultBranch`` value configured in *home*. A single file is committed
    so the resulting branch ref exists and ``ls-remote`` advertises it.
    """
    work.mkdir(parents=True, exist_ok=True)
    _git(["init"], cwd=work, home=home)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work, home=home)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work, home=home)
    (work / _CONTENT_FILE).write_text(_CONTENT_TEXT, encoding="utf-8")
    _git(["add", _CONTENT_FILE], cwd=work, home=home)
    _git(["commit", "-m", "init"], cwd=work, home=home)
    return f"file://{work}"


def _current_branch(work: pathlib.Path, home: pathlib.Path) -> str:
    """Return the short symbolic-ref name of *work*'s current branch."""
    result = _git(["symbolic-ref", "--short", "HEAD"], cwd=work, home=home)
    return result.stdout.strip()


def _pin_home_for_resolution(monkeypatch: pytest.MonkeyPatch, home: pathlib.Path) -> None:
    """Route the production ``git`` subprocesses through *home*'s global config.

    The resolution helpers inherit the process environment, so HOME is pointed at
    the prerequisite-configured directory and any ambient ``GIT_CONFIG_*``
    overrides (which would shadow the per-HOME global config) are cleared.
    """
    monkeypatch.setenv("HOME", str(home))
    for var in _GIT_CONFIG_OVERRIDE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.mark.functional
class TestInitDefaultBranchMainPrerequisiteSatisfied:
    """POSITIVE: ``init.defaultBranch=main`` makes ``auto`` / ``main`` resolution succeed."""

    def test_bare_git_init_creates_main_branch(self, tmp_path: pathlib.Path) -> None:
        """A bare ``git init`` under a ``main``-configured HOME creates ``main``, not ``master``."""
        home = tmp_path / "home_main"
        _configure_home_default_branch(home, _BRANCH_MAIN)
        work = tmp_path / "repo_main"
        _build_committed_repo(work, home)
        assert _current_branch(work, home) == _BRANCH_MAIN

    def test_auto_resolves_main_against_freshly_init_repo(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``auto`` resolves the advertised HEAD symref to ``main`` for a ``main``-init'd repo."""
        home = tmp_path / "home_main"
        _configure_home_default_branch(home, _BRANCH_MAIN)
        work = tmp_path / "repo_main"
        url = _build_committed_repo(work, home)
        _pin_home_for_resolution(monkeypatch, home)
        resolved = resolve_default_branch(url, inline_ref=None, flag_value=CATALOG_DEFAULT_BRANCH_AUTO)
        assert resolved == _BRANCH_MAIN

    def test_default_main_verifies_and_returns_main(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The implicit ``main`` default verifies existence and returns ``main``."""
        home = tmp_path / "home_main"
        _configure_home_default_branch(home, _BRANCH_MAIN)
        work = tmp_path / "repo_main"
        url = _build_committed_repo(work, home)
        _pin_home_for_resolution(monkeypatch, home)
        resolved = resolve_default_branch(url, inline_ref=None, flag_value=CATALOG_DEFAULT_BRANCH_DEFAULT)
        assert resolved == CATALOG_DEFAULT_BRANCH_DEFAULT


@pytest.mark.functional
class TestInitDefaultBranchMasterPrerequisiteUnsatisfied:
    """NEGATIVE: ``init.defaultBranch=master`` reproduces the documented ``main not found`` failure."""

    def test_bare_git_init_creates_master_branch(self, tmp_path: pathlib.Path) -> None:
        """A bare ``git init`` under a ``master``-configured HOME creates only ``master``."""
        home = tmp_path / "home_master"
        _configure_home_default_branch(home, _BRANCH_MASTER)
        work = tmp_path / "repo_master"
        _build_committed_repo(work, home)
        assert _current_branch(work, home) == _BRANCH_MASTER

    def test_default_main_fails_fast_when_only_master_exists(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Resolving the ``main`` default fails fast because ``main`` is absent on the remote."""
        home = tmp_path / "home_master"
        _configure_home_default_branch(home, _BRANCH_MASTER)
        work = tmp_path / "repo_master"
        url = _build_committed_repo(work, home)
        _pin_home_for_resolution(monkeypatch, home)
        with pytest.raises(DefaultBranchResolutionError) as excinfo:
            resolve_default_branch(url, inline_ref=None, flag_value=CATALOG_DEFAULT_BRANCH_DEFAULT)
        message = str(excinfo.value)
        assert _BRANCH_MAIN in message
        assert "not found" in message

    def test_auto_resolves_to_master_and_main_ref_is_absent(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``auto`` tracks the configured initial branch (``master``) and ``refs/heads/main`` is absent.

        Resolving ``auto`` returns ``master`` (the advertised HEAD symref), and a
        direct ``ls-remote refs/heads/main`` lookup fails because the ``main`` ref
        the ``@main`` pin depends on was never created -- the documented
        empty/``main not found`` failure when the prerequisite is unsatisfied.
        """
        home = tmp_path / "home_master"
        _configure_home_default_branch(home, _BRANCH_MASTER)
        work = tmp_path / "repo_master"
        url = _build_committed_repo(work, home)
        _pin_home_for_resolution(monkeypatch, home)
        resolved_auto = resolve_default_branch(url, inline_ref=None, flag_value=CATALOG_DEFAULT_BRANCH_AUTO)
        assert resolved_auto == _BRANCH_MASTER
        with pytest.raises(ValueError) as excinfo:
            _list_branch_head(url, _BRANCH_MAIN)
        assert "not found" in str(excinfo.value)
