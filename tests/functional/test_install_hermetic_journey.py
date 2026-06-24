"""Functional journey J3: hermetic, reproducible ``kanon install`` (AC-48).

Exercises ``kanon install`` end-to-end as a real CLI black box (subprocess, no
mocks) against a real local ``file://`` manifest repository, covering spec
Section 4.3 / Section 10.4 / FR-14:

- install is driven SOLELY by the committed ``.kanon`` (+ ``.kanon.lock``): the
  first run resolves from ``.kanon`` and writes ``.kanon.lock``; the second run
  replays the committed lock and is byte-identical (excluding the volatile
  ``generated_at`` timestamp line) -- reproducible across two runs.
- A populated ``KANON_CATALOG_SOURCES`` environment variable has NO effect on
  install: it is ignored (never read), and install still succeeds and produces
  the same lockfile state.
- ``--catalog-source`` is NOT accepted by the install parser: passing it exits
  non-zero with a clear, actionable error on stderr.

The fixtures build a real bare manifest repo so ``repo init``/``sync`` run
against genuine git output (provider-agnostic ``file://`` URL, no API/token, no
network).  ``KANON_ALLOW_INSECURE_REMOTES`` permits the ``file://`` scheme through
the remote-URL policy.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.functional.conftest import _git, _run_kanon


_GIT_USER_NAME = "Hermetic Journey User"
_GIT_USER_EMAIL = "hermetic-journey@example.com"
_MANIFEST_FILENAME = "manifest.xml"
_DEFAULT_BRANCH = "main"
_SOURCE_ALIAS = "alpha"
_EXACT_REVISION = "==1.0.0"
_RELEASE_TAG = "1.0.0"
_INSECURE_REMOTES_ENV = "KANON_ALLOW_INSECURE_REMOTES"
_INSECURE_REMOTES_VALUE = "1"
_CATALOG_SOURCES_ENV = "KANON_CATALOG_SOURCES"
_LOCKFILE_NAME = ".kanon.lock"


_VOLATILE_LOCK_PREFIX = "generated_at"


def _make_manifest_bare_repo(base: pathlib.Path) -> str:
    """Create a real bare manifest repo with a tagged, zero-project manifest.

    The manifest declares a remote whose fetch base is the temp dir and no
    ``<project>`` entries, so ``repo init``/``sync`` complete offline without any
    project checkout.  The single commit is tagged ``1.0.0`` so an exact PEP 440
    revision (``==1.0.0``) resolves against ``refs/tags/1.0.0``.

    Returns the ``file://`` URL of the bare repo.
    """
    work = base / "manifest-work"
    work.mkdir()
    _git(["init", "-b", _DEFAULT_BRANCH], cwd=work)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work)
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="file://{base.resolve()}" />\n'
        f'  <default revision="{_DEFAULT_BRANCH}" remote="local" />\n'
        "</manifest>\n"
    )
    (work / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work)
    _git(["commit", "-m", "Add manifest"], cwd=work)
    _git(["tag", _RELEASE_TAG], cwd=work)

    bare = base / "manifest-bare.git"
    _git(["clone", "--bare", str(work), str(bare)], cwd=base)
    return f"file://{bare.resolve()}"


def _write_kanon(project_dir: pathlib.Path, source_url: str) -> pathlib.Path:
    """Write a single-source committed .kanon pointing at ``source_url``."""
    kanon_path = project_dir / ".kanon"
    kanon_path.write_text(
        f"CLAUDE_MARKETPLACES_DIR={project_dir}/mktplc\n"
        "KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{_SOURCE_ALIAS}_URL={source_url}\n"
        f"KANON_SOURCE_{_SOURCE_ALIAS}_REF={_EXACT_REVISION}\n"
        f"KANON_SOURCE_{_SOURCE_ALIAS}_PATH={_MANIFEST_FILENAME}\n"
        f"KANON_SOURCE_{_SOURCE_ALIAS}_NAME={_SOURCE_ALIAS}\n"
        f"KANON_SOURCE_{_SOURCE_ALIAS}_GITBASE={source_url}\n",
        encoding="utf-8",
    )
    kanon_path.chmod(0o600)
    return kanon_path


def _stable_lock_body(lock_path: pathlib.Path) -> str:
    """Return the lockfile content with the volatile generated_at line removed."""
    lines = lock_path.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.startswith(_VOLATILE_LOCK_PREFIX))


@pytest.fixture()
def hermetic_project(tmp_path: pathlib.Path) -> pathlib.Path:
    """Build a real file:// manifest repo and a committed .kanon project dir.

    Returns the project directory containing the committed .kanon (cwd for the
    subprocess install invocations).
    """
    source_url = _make_manifest_bare_repo(tmp_path)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _write_kanon(project_dir, source_url)
    return project_dir


@pytest.mark.functional
class TestHermeticInstallJourney:
    """J3: install is hermetic, reproducible, env-ignoring, and rejects --catalog-source."""

    def test_first_install_resolves_from_kanon_and_writes_lock(
        self, hermetic_project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The first install resolves from the committed .kanon and writes .kanon.lock."""
        monkeypatch.delenv(_CATALOG_SOURCES_ENV, raising=False)
        result = _run_kanon(
            "install",
            str(hermetic_project / ".kanon"),
            extra_env={_INSECURE_REMOTES_ENV: _INSECURE_REMOTES_VALUE},
        )
        assert result.returncode == 0, f"install must succeed.\n  stdout={result.stdout!r}\n  stderr={result.stderr!r}"
        lock_path = hermetic_project / _LOCKFILE_NAME
        assert lock_path.is_file(), "install must write the committed .kanon.lock"

        assert _SOURCE_ALIAS in lock_path.read_text(encoding="utf-8")

    def test_install_is_reproducible_across_two_runs(
        self, hermetic_project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two consecutive installs produce a byte-identical lockfile (excluding generated_at)."""
        monkeypatch.delenv(_CATALOG_SOURCES_ENV, raising=False)
        env = {_INSECURE_REMOTES_ENV: _INSECURE_REMOTES_VALUE}
        lock_path = hermetic_project / _LOCKFILE_NAME

        first = _run_kanon("install", str(hermetic_project / ".kanon"), extra_env=env)
        assert first.returncode == 0, f"first install must succeed. stderr={first.stderr!r}"
        first_body = _stable_lock_body(lock_path)

        second = _run_kanon("install", str(hermetic_project / ".kanon"), extra_env=env)
        assert second.returncode == 0, f"second install must succeed. stderr={second.stderr!r}"
        second_body = _stable_lock_body(lock_path)

        assert first_body == second_body, "install must replay the committed lock byte-for-byte across runs"

    def test_install_ignores_populated_catalog_sources_env(self, hermetic_project: pathlib.Path) -> None:
        """A populated KANON_CATALOG_SOURCES env has no effect: install succeeds with the same lock."""
        lock_path = hermetic_project / _LOCKFILE_NAME

        baseline = _run_kanon(
            "install",
            str(hermetic_project / ".kanon"),
            extra_env={_INSECURE_REMOTES_ENV: _INSECURE_REMOTES_VALUE, _CATALOG_SOURCES_ENV: ""},
        )
        assert baseline.returncode == 0, f"baseline install must succeed. stderr={baseline.stderr!r}"
        baseline_body = _stable_lock_body(lock_path)

        with_env = _run_kanon(
            "install",
            str(hermetic_project / ".kanon"),
            extra_env={
                _INSECURE_REMOTES_ENV: _INSECURE_REMOTES_VALUE,
                _CATALOG_SOURCES_ENV: "file:///nonexistent/should-be-ignored.git@main",
            },
        )
        assert with_env.returncode == 0, (
            "a populated KANON_CATALOG_SOURCES must be IGNORED (install still succeeds), not rejected.\n"
            f"  stdout={with_env.stdout!r}\n  stderr={with_env.stderr!r}"
        )

        env_body = _stable_lock_body(lock_path)
        assert "should-be-ignored" not in env_body
        assert env_body == baseline_body

    @pytest.mark.parametrize(
        "catalog_value",
        ["file:///some/catalog.git@main", "https://example.com/catalog.git", "latest"],
    )
    def test_install_rejects_catalog_source_flag(self, hermetic_project: pathlib.Path, catalog_value: str) -> None:
        """Passing --catalog-source to install exits non-zero with a clear error on stderr."""
        result = _run_kanon(
            "install",
            str(hermetic_project / ".kanon"),
            "--catalog-source",
            catalog_value,
            extra_env={_INSECURE_REMOTES_ENV: _INSECURE_REMOTES_VALUE},
        )
        assert result.returncode != 0, "install must reject --catalog-source with a non-zero exit"

        assert "--catalog-source" in result.stderr
        assert "unrecognized arguments" in result.stderr
