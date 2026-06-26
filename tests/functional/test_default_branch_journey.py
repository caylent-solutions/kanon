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

import os
import pathlib
import subprocess
import sys

import pytest

from kanon_cli import constants
from kanon_cli.constants import CATALOG_DEFAULT_BRANCH_ENV_VAR
from kanon_cli.core.catalog import DefaultBranchResolutionError, resolve_default_branch


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

        assert captured.out == ""
        assert _WARN_TOKEN in captured.err
        assert _DEFAULT_BRANCH_NAME in captured.err
        assert url in captured.err

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

        assert "KANON_CATALOG_DEFAULT_BRANCH" in message
        assert "--catalog-default-branch" in message
        assert "@<ref>" in message

    def test_missing_defaulted_branch_fails_fast(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A defaulted branch absent from the remote fails fast on the existence check."""
        url = _make_bare_with_default_branch(tmp_path, _DEFAULT_BRANCH_NAME)

        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, "does-not-exist")
        with pytest.raises(DefaultBranchResolutionError) as exc_info:
            resolve_default_branch(url, inline_ref=None, flag_value=None)
        assert "not found on remote" in str(exc_info.value)


_ENTRY_NAME = "history"
_ENTRY_XML_FILENAME = "history-marketplace.xml"
_ENTRY_RELEASE_TAG = "1.0.0"
_INVALID_FORMAT_TOKEN = "Invalid catalog source format"
_PRECEDENCE_DEFAULT_BRANCH = "main"


def _catalog_entry_xml(name: str) -> str:
    """Return a valid catalog-metadata XML body for the given entry name."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<repo-specs>\n"
        "  <catalog-metadata>\n"
        f"    <name>{name}</name>\n"
        f"    <version>=={_ENTRY_RELEASE_TAG}</version>\n"
        "    <display-name>History Package</display-name>\n"
        "    <description>An entry published for the default-branch CLI journey.</description>\n"
        "    <type>library</type>\n"
        "    <owner-name>Journey Owner</owner-name>\n"
        "    <owner-email>journey@example.com</owner-email>\n"
        "    <keywords>test journey</keywords>\n"
        "  </catalog-metadata>\n"
        "</repo-specs>\n"
    )


def _make_bare_catalog_repo(base: pathlib.Path, branch: str, *, with_tag: bool) -> str:
    """Create a real bare catalog repo on ``branch`` and return its ``file://`` URL.

    The repo carries ``repo-specs/<entry>-marketplace.xml`` so ``kanon add`` /
    ``kanon search`` can resolve a real entry. When ``with_tag`` is True an
    annotated PEP 440 release tag is created so the per-entry version resolver
    has a tag to pin (the manifest-repo ref is the resolved default branch; the
    per-entry version is a SEPARATE concern resolved from the highest tag).
    """
    work = base / "catalog-work"
    work.mkdir()
    _git(["init", "-b", branch], cwd=work)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work)
    repo_specs = work / "repo-specs"
    repo_specs.mkdir()
    (repo_specs / _ENTRY_XML_FILENAME).write_text(_catalog_entry_xml(_ENTRY_NAME), encoding="utf-8")
    _git(["add", "."], cwd=work)
    _git(["commit", "-m", "Add history catalog entry"], cwd=work)
    if with_tag:
        _git(["tag", "-a", _ENTRY_RELEASE_TAG, "-m", f"Release {_ENTRY_RELEASE_TAG}"], cwd=work)

    bare = base / "catalog-bare.git"
    _git(["clone", "--bare", str(work), str(bare)], cwd=base)
    return f"file://{bare.resolve()}"


def _run_kanon_no_catalog_env(
    args: list[str],
    cwd: pathlib.Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon CLI in a subprocess with no ambient catalog env vars.

    Drops ``KANON_CATALOG_SOURCES`` and ``KANON_CATALOG_DEFAULT_BRANCH`` from the
    inherited environment so each test controls the default-branch precedence
    explicitly via the flag or ``extra_env``.
    """
    env = dict(os.environ)
    env.pop("KANON_CATALOG_SOURCES", None)
    env.pop(CATALOG_DEFAULT_BRANCH_ENV_VAR, None)
    env["NO_COLOR"] = "1"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
    )


@pytest.mark.functional
class TestDefaultBranchCliJourney:
    """End-to-end CLI coverage of the omit-@ref default-branch wiring (F-011 / F-067).

    These journeys drive the real ``kanon add`` / ``kanon search`` CLI via
    subprocess against real bare catalog repos, closing the gap the in-process
    resolver unit tests missed: that a ``--catalog-source`` supplied WITHOUT an
    ``@ref`` now resolves the default branch instead of hard-erroring with
    "Invalid catalog source format".
    """

    def test_add_without_ref_resolves_default_branch_and_warns(self, tmp_path: pathlib.Path) -> None:
        """add <entry> --catalog-source <url-no-@ref> resolves the default branch + WARNs."""
        url = _make_bare_catalog_repo(tmp_path, _PRECEDENCE_DEFAULT_BRANCH, with_tag=True)
        project = tmp_path / "project"
        project.mkdir()
        kanon_file = project / ".kanon"

        result = _run_kanon_no_catalog_env(
            ["add", _ENTRY_NAME, "--catalog-source", url, "--kanon-file", str(kanon_file)],
            cwd=project,
        )

        assert result.returncode == 0, (
            f"ref-less add must resolve the default branch, not error.\n"
            f"  stdout={result.stdout!r}\n  stderr={result.stderr!r}"
        )
        assert _INVALID_FORMAT_TOKEN not in result.stderr
        assert _WARN_TOKEN in result.stderr
        assert _PRECEDENCE_DEFAULT_BRANCH in result.stderr
        assert url in result.stderr

        kanon_text = kanon_file.read_text(encoding="utf-8")
        assert f"KANON_SOURCE_{_ENTRY_NAME}_URL=" in kanon_text

    def test_add_flag_overrides_env_default_branch(self, tmp_path: pathlib.Path) -> None:
        """--catalog-default-branch <b> overrides KANON_CATALOG_DEFAULT_BRANCH for a ref-less add."""
        flag_branch = "trunk"
        url = _make_bare_catalog_repo(tmp_path, flag_branch, with_tag=True)
        project = tmp_path / "project"
        project.mkdir()
        kanon_file = project / ".kanon"

        result = _run_kanon_no_catalog_env(
            [
                "add",
                _ENTRY_NAME,
                "--catalog-source",
                url,
                "--catalog-default-branch",
                flag_branch,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=project,
            extra_env={CATALOG_DEFAULT_BRANCH_ENV_VAR: "main"},
        )

        assert result.returncode == 0, (
            f"the flag must win over the env var (env=main, flag={flag_branch}).\n"
            f"  stdout={result.stdout!r}\n  stderr={result.stderr!r}"
        )
        assert _INVALID_FORMAT_TOKEN not in result.stderr
        assert flag_branch in result.stderr
        assert kanon_file.exists()

    def test_search_auto_resolves_symref_through_cli(self, tmp_path: pathlib.Path) -> None:
        """KANON_CATALOG_DEFAULT_BRANCH=auto resolves the HEAD symref via the search CLI path."""
        symref_branch = "trunk"
        url = _make_bare_catalog_repo(tmp_path, symref_branch, with_tag=False)
        project = tmp_path / "project"
        project.mkdir()

        result = _run_kanon_no_catalog_env(
            ["search", "--catalog-source", url],
            cwd=project,
            extra_env={CATALOG_DEFAULT_BRANCH_ENV_VAR: _AUTO},
        )

        assert result.returncode == 0, (
            f"auto must resolve the advertised HEAD symref through the search CLI.\n"
            f"  stdout={result.stdout!r}\n  stderr={result.stderr!r}"
        )
        assert _INVALID_FORMAT_TOKEN not in result.stderr
        assert _WARN_TOKEN in result.stderr
        assert symref_branch in result.stderr
        assert _ENTRY_NAME in result.stdout
