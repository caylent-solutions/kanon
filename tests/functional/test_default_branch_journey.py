"""Functional journey J8: default-branch resolution (AC-53).

Exercises the shared default-branch precedence helper
(:func:`kanon_cli.core.catalog.resolve_default_branch`) end-to-end against real
local bare git repositories (provider-agnostic ``file://`` URLs, no API/token),
covering spec Section 6 / Section 10.4 / FR-12 / FR-26 / FR-27:

- The literal ``auto`` default resolves the remote's advertised HEAD symref via a
  real ``git ls-remote --symref <url> HEAD`` call (routed through the shared
  runner), returning the bare default-branch name.
- A defaulted ref emits a single yellow WARN to stderr naming the branch, and the
  helper returns the branch on stdout-free channels so ``--format json`` / piped
  stdout is never corrupted.
- The WARN is deduped to once per defaulted source within an invocation.
- A remote that advertises no HEAD symref (an empty bare repo) fails fast with the
  actionable symref-absent error naming the operator's next step.

The fixtures build real bare git repos so the ``--symref`` parsing and the
branch-existence verification run against genuine git output, not a stub.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

from kanon_cli import constants
from kanon_cli.constants import CATALOG_DEFAULT_BRANCH_ENV_VAR
from kanon_cli.core.catalog import DefaultBranchResolutionError, resolve_default_branch

# ---------------------------------------------------------------------------
# Constants (no inline literals in assertions / fixtures).
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Default Branch Journey User"
_GIT_USER_EMAIL = "default-branch-journey@example.com"
_DEFAULT_BRANCH_NAME = "trunk"
_CONTENT_FILE = "README.md"
_CONTENT_TEXT = "default-branch journey content"
_AUTO = "auto"
_WARN_TOKEN = "WARNING"
_ANSI_YELLOW = "\033[33m"
_ANSI_RESET = "\033[0m"


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising on non-zero exit."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _make_bare_with_default_branch(base: pathlib.Path, branch: str) -> str:
    """Create a real bare repo whose HEAD symref targets ``branch``.

    Returns the ``file://`` URL of the bare repo, so ``git ls-remote --symref``
    advertises ``ref: refs/heads/<branch>\\tHEAD`` against it.
    """
    work = base / "work"
    work.mkdir()
    _git(["init", "-b", branch], cwd=work)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work)
    (work / _CONTENT_FILE).write_text(_CONTENT_TEXT, encoding="utf-8")
    _git(["add", _CONTENT_FILE], cwd=work)
    _git(["commit", "-m", "Initial commit"], cwd=work)

    bare = base / "manifest-bare.git"
    _git(["clone", "--bare", str(work), str(bare)], cwd=base)
    return f"file://{bare.resolve()}"


def _make_empty_bare(base: pathlib.Path) -> str:
    """Create an empty bare repo (no commits, no advertised HEAD symref).

    Returns the ``file://`` URL; ``git ls-remote --symref`` advertises no
    ``ref: refs/heads/...`` line against it (the symref-absent path).
    """
    bare = base / "empty-bare.git"
    _git(["init", "--bare", str(bare)], cwd=base)
    return f"file://{bare.resolve()}"


@pytest.fixture(autouse=True)
def _color_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable ANSI color for WARN assertions (the WARN is rendered yellow)."""
    monkeypatch.setattr(constants, "_NO_COLOR_ACTIVE", False)


@pytest.mark.functional
class TestDefaultBranchJourney:
    """J8: auto/--symref resolution, yellow WARN to stderr, symref-absent fail-fast."""

    def test_auto_resolves_advertised_default_branch(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """auto resolves the real HEAD symref to the advertised default branch."""
        url = _make_bare_with_default_branch(tmp_path, _DEFAULT_BRANCH_NAME)
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, _AUTO)
        resolved = resolve_default_branch(url, inline_ref=None, flag_value=None)
        assert resolved == _DEFAULT_BRANCH_NAME

    def test_defaulted_ref_emits_yellow_warn_to_stderr_only(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A defaulted ref writes a yellow WARN naming the branch to stderr, not stdout."""
        url = _make_bare_with_default_branch(tmp_path, _DEFAULT_BRANCH_NAME)
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, _AUTO)
        resolved = resolve_default_branch(url, inline_ref=None, flag_value=None)
        captured = capsys.readouterr()
        assert resolved == _DEFAULT_BRANCH_NAME
        # stdout stays clean so --format json / pipes are never corrupted.
        assert captured.out == ""
        assert _WARN_TOKEN in captured.err
        assert _DEFAULT_BRANCH_NAME in captured.err
        assert url in captured.err
        # The WARN is rendered in ANSI yellow when color is active.
        assert _ANSI_YELLOW in captured.err
        assert _ANSI_RESET in captured.err

    def test_warn_deduped_once_per_defaulted_source(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The WARN fires once per defaulted source across a multi-call invocation."""
        url = _make_bare_with_default_branch(tmp_path, _DEFAULT_BRANCH_NAME)
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, _AUTO)
        warned: set[str] = set()
        first = resolve_default_branch(url, inline_ref=None, flag_value=None, warned_urls=warned)
        second = resolve_default_branch(url, inline_ref=None, flag_value=None, warned_urls=warned)
        captured = capsys.readouterr()
        assert first == _DEFAULT_BRANCH_NAME
        assert second == _DEFAULT_BRANCH_NAME
        assert captured.err.count(_WARN_TOKEN) == 1
        assert warned == {url}

    def test_inline_ref_is_pinned_without_warn_or_symref(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An explicit inline @ref is returned verbatim with no WARN and no resolution."""
        url = _make_empty_bare(tmp_path)
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, _AUTO)
        # Even against a symref-absent remote, a pinned inline ref short-circuits:
        # the precedence never reaches the auto/symref step.
        resolved = resolve_default_branch(url, inline_ref="v9.9.9", flag_value=None)
        captured = capsys.readouterr()
        assert resolved == "v9.9.9"
        assert captured.err == ""

    def test_symref_absent_fails_fast_with_actionable_error(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """auto against a remote with no HEAD symref fails fast with the Section 6 error."""
        url = _make_empty_bare(tmp_path)
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, _AUTO)
        with pytest.raises(DefaultBranchResolutionError) as exc_info:
            resolve_default_branch(url, inline_ref=None, flag_value=None)
        message = str(exc_info.value)
        assert "cannot resolve the default branch" in message
        assert url in message
        # The actionable next steps are all named.
        assert "KANON_CATALOG_DEFAULT_BRANCH" in message
        assert "--catalog-default-branch" in message
        assert "@<ref>" in message

    def test_missing_defaulted_branch_fails_fast(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A defaulted branch absent from the remote fails fast on the existence check."""
        url = _make_bare_with_default_branch(tmp_path, _DEFAULT_BRANCH_NAME)
        # The env names a branch that does not exist on the remote.
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, "does-not-exist")
        with pytest.raises(DefaultBranchResolutionError) as exc_info:
            resolve_default_branch(url, inline_ref=None, flag_value=None)
        assert "not found on remote" in str(exc_info.value)
