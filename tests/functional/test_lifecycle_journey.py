"""Functional journey J1: the full kanon operator lifecycle (AC-46).

Drives the complete J1 operator arc end to end through the real ``kanon`` CLI as
a subprocess black box (``python -m kanon_cli``), asserting exit codes and
stdout/stderr at every step (spec ``specs/kanon-refinements.md`` Section 10.4 J1
/ FR-10, FR-11, FR-14, FR-18):

1. ``add`` (source-explicit) -- resolve a catalog entry from an explicit
   ``--catalog-source`` and append its alias-keyed
   ``KANON_SOURCE_<alias>_{URL,REF,PATH,NAME,GITBASE}`` block to ``.kanon``.
2. ``install`` (hermetic) -- install is driven SOLELY by the committed
   ``.kanon`` and writes ``.kanon.lock``; it never reads a catalog source and
   rejects ``--catalog-source``.
3. ``search`` -- discover the catalog entry from the same source, printing the
   entry name to stdout and the per-source header to stderr.
4. ``marketplace status`` -- render each dependency's alias and effective
   marketplace setting from the committed ``.kanon`` (a dependency with no
   ``_MARKETPLACE`` line reads ``disabled``).
5. ``remove`` -- remove the alias block from ``.kanon`` (the alias is gone after).

The world is built from a synthetic bare catalog repo (a real ``file://`` git
repo carrying ``repo-specs/<entry>-marketplace.xml`` with a
``<catalog-metadata>`` block and a PEP 440 release tag) so the journey runs
offline and deterministically on every platform that has ``git``. There is no
``skipif``: every step exercises a real surface of the shipped 3.0.0 CLI.

``KANON_ALLOW_INSECURE_REMOTES`` permits the ``file://`` scheme through the
remote-URL policy for the hermetic install step. A per-test ``KANON_HOME``
isolates the search TTL cache from the operator's real cache.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

from tests.functional.conftest import _git, _run_kanon

# ---------------------------------------------------------------------------
# Constants (no inline literals scattered across assertions / fixtures).
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Lifecycle Journey User"
_GIT_USER_EMAIL = "lifecycle-journey@example.com"
_DEFAULT_BRANCH = "main"

# The single catalog entry name published by the synthetic source repo. The
# add step keys the .kanon block under this bare alias.
_ENTRY_NAME = "widget"

# The PEP 440 release tag cut on the source repo. The catalog tag scheme uses
# both the per-manifest ``<name>/<version>`` tag and a plain version tag so an
# exact revision resolves.
_RELEASE_VERSION = "1.0.0"

# The repo-relative manifest path under repo-specs/.
_XML_FILENAME = f"{_ENTRY_NAME}-marketplace.xml"
_XML_REL_PATH = f"repo-specs/{_XML_FILENAME}"

_SOURCE_PREFIX = "KANON_SOURCE_"
_KANON_FILENAME = ".kanon"
_LOCKFILE_NAME = ".kanon.lock"

_INSECURE_REMOTES_ENV = "KANON_ALLOW_INSECURE_REMOTES"
_INSECURE_REMOTES_VALUE = "1"
_KANON_HOME_ENV = "KANON_HOME"
_CATALOG_SOURCES_ENV = "KANON_CATALOG_SOURCES"

# The marketplace status table renders a disabled dependency in the SETTING
# column; a freshly-added dep has no _MARKETPLACE line (canonical false).
_SETTING_DISABLED = "disabled"


def _catalog_xml() -> str:
    """Return a valid catalog-metadata XML body for the journey entry."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        "  <catalog-metadata>\n"
        f"    <name>{_ENTRY_NAME}</name>\n"
        "    <display-name>Widget Package</display-name>\n"
        "    <description>The J1 full-lifecycle journey entry.</description>\n"
        f"    <version>=={_RELEASE_VERSION}</version>\n"
        "    <type>marketplace</type>\n"
        "    <owner-name>Lifecycle Owner</owner-name>\n"
        "    <owner-email>lifecycle@example.com</owner-email>\n"
        f"    <keywords>{_ENTRY_NAME} journey</keywords>\n"
        "  </catalog-metadata>\n"
        "</manifest>\n"
    )


def _build_catalog_repo(base: pathlib.Path) -> pathlib.Path:
    """Create a bare catalog repo publishing the journey entry; return its bare path.

    The repo carries ``repo-specs/<entry>-marketplace.xml`` on ``main`` and is
    tagged with both ``<entry>/<version>`` (the per-manifest catalog tag) and a
    plain ``<version>`` tag so an exact revision resolves.

    Args:
        base: Parent directory under which the working + bare repos are created.

    Returns:
        The resolved absolute path to the bare catalog repository.
    """
    work = base / "catalog-work"
    repo_specs = work / "repo-specs"
    repo_specs.mkdir(parents=True)
    _git(["init", "-b", _DEFAULT_BRANCH], cwd=work)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work)

    (repo_specs / _XML_FILENAME).write_text(_catalog_xml(), encoding="utf-8")
    _git(["add", "."], cwd=work)
    _git(["commit", "-m", f"Add {_ENTRY_NAME} catalog entry"], cwd=work)
    _git(["tag", f"{_ENTRY_NAME}/{_RELEASE_VERSION}"], cwd=work)
    _git(["tag", _RELEASE_VERSION], cwd=work)

    bare = base / "catalog-bare.git"
    _git(["clone", "--bare", str(work), str(bare)], cwd=base)
    return bare.resolve()


def _block_value(kanon_text: str, alias: str, suffix: str) -> str | None:
    """Return the value of ``KANON_SOURCE_<alias>_<suffix>`` from .kanon text, or None.

    Args:
        kanon_text: The full text of a ``.kanon`` file.
        alias: The source alias keying the block.
        suffix: The block suffix including the leading underscore (e.g. ``_URL``).

    Returns:
        The value string, or ``None`` when the key is absent.
    """
    prefix = f"{_SOURCE_PREFIX}{alias}{suffix}="
    for line in kanon_text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    return None


@pytest.fixture()
def journey_world(tmp_path: pathlib.Path) -> "tuple[pathlib.Path, str, str]":
    """Build a synthetic catalog source, an empty project dir, and a KANON_HOME.

    Args:
        tmp_path: pytest-provided temporary directory root.

    Returns:
        A 3-tuple ``(project_dir, catalog_source, kanon_home)`` where
        ``catalog_source`` is a ``file://<bare>@<branch>`` catalog source and
        ``kanon_home`` is an isolated search-cache home.
    """
    repos = tmp_path / "repos"
    repos.mkdir()
    bare = _build_catalog_repo(repos)
    catalog_source = f"{bare.as_uri()}@{_DEFAULT_BRANCH}"

    project = tmp_path / "project"
    project.mkdir()

    kanon_home = tmp_path / "kanon-home"
    kanon_home.mkdir()

    return project, catalog_source, str(kanon_home)


@pytest.mark.functional
class TestFullLifecycleJourney:
    """J1: add -> install -> search -> marketplace status -> remove via the real CLI."""

    def test_full_lifecycle_arc(self, journey_world: "tuple[pathlib.Path, str, str]") -> None:
        """Drive the complete J1 operator arc, asserting each step's I/O contract."""
        project, catalog_source, kanon_home = journey_world
        kanon_file = project / _KANON_FILENAME
        lock_file = project / _LOCKFILE_NAME
        base_env = {_KANON_HOME_ENV: kanon_home, _CATALOG_SOURCES_ENV: ""}

        # --- Step 1: add (source-explicit) -----------------------------------
        # Resolve the entry from the explicit --catalog-source and append the
        # alias-keyed block to .kanon (spec Section 4.2 / FR-11).
        add_result = _run_kanon(
            "add",
            _ENTRY_NAME,
            "--catalog-source",
            catalog_source,
            "--kanon-file",
            str(kanon_file),
            cwd=project,
            extra_env=base_env,
        )
        assert add_result.returncode == 0, (
            f"add (source-explicit) must exit 0.\n  stdout={add_result.stdout!r}\n  stderr={add_result.stderr!r}"
        )
        assert kanon_file.is_file(), "add must create the committed .kanon"
        kanon_after_add = kanon_file.read_text(encoding="utf-8")
        # The bare alias keys the block; _NAME carries the manifest name and the
        # block records URL/REF/PATH for the hermetic install.
        assert _block_value(kanon_after_add, _ENTRY_NAME, "_NAME") == _ENTRY_NAME
        assert _block_value(kanon_after_add, _ENTRY_NAME, "_URL") is not None
        assert _block_value(kanon_after_add, _ENTRY_NAME, "_REF") is not None
        assert _block_value(kanon_after_add, _ENTRY_NAME, "_PATH") == _XML_REL_PATH
        # add edits only .kanon -- no lock is written yet.
        assert not lock_file.exists(), "add must not write .kanon.lock"

        # --- Step 2: install (hermetic) --------------------------------------
        # install is driven solely by the committed .kanon and writes the lock.
        install_env = dict(base_env)
        install_env[_INSECURE_REMOTES_ENV] = _INSECURE_REMOTES_VALUE
        install_result = _run_kanon(
            "install",
            str(kanon_file),
            cwd=project,
            extra_env=install_env,
        )
        assert install_result.returncode == 0, (
            f"hermetic install must exit 0.\n  stdout={install_result.stdout!r}\n  stderr={install_result.stderr!r}"
        )
        assert "done" in install_result.stdout.lower(), (
            f"install success must print a completion message to stdout; got {install_result.stdout!r}"
        )
        assert lock_file.is_file(), "install must write the committed .kanon.lock"
        assert _ENTRY_NAME in lock_file.read_text(encoding="utf-8"), "the lock must record the committed source alias"

        # install is hermetic: it does not accept --catalog-source.
        reject_result = _run_kanon(
            "install",
            str(kanon_file),
            "--catalog-source",
            catalog_source,
            cwd=project,
            extra_env=install_env,
        )
        assert reject_result.returncode != 0, "install must reject --catalog-source (hermetic)"
        assert "--catalog-source" in reject_result.stderr
        assert "unrecognized arguments" in reject_result.stderr

        # --- Step 3: search --------------------------------------------------
        # Discover the entry from the same source: name on stdout, per-source
        # header on stderr (spec Section 4.1 / FR-9, FR-10).
        search_result = _run_kanon(
            "search",
            "--catalog-source",
            catalog_source,
            cwd=project,
            extra_env=base_env,
        )
        assert search_result.returncode == 0, (
            f"search must exit 0.\n  stdout={search_result.stdout!r}\n  stderr={search_result.stderr!r}"
        )
        stdout_entries = search_result.stdout.split()
        assert _ENTRY_NAME in stdout_entries, (
            f"search stdout must list the catalog entry {_ENTRY_NAME!r}; got {search_result.stdout!r}"
        )
        # The per-source header is on stderr, never on stdout (stdout stays pipeable).
        assert f"Source: {catalog_source}" in search_result.stderr
        assert "Source:" not in search_result.stdout

        # --- Step 4: marketplace status --------------------------------------
        # Render each dependency's alias + effective marketplace setting from
        # .kanon. The added dep has no _MARKETPLACE line, so it reads disabled
        # (spec Section 4.4 / FR-18).
        status_result = _run_kanon(
            "marketplace",
            "status",
            "--all",
            cwd=project,
            extra_env=base_env,
        )
        assert status_result.returncode == 0, (
            f"marketplace status must exit 0.\n  stdout={status_result.stdout!r}\n  stderr={status_result.stderr!r}"
        )
        status_row = next(
            (line for line in status_result.stdout.splitlines() if line.startswith(_ENTRY_NAME)),
            None,
        )
        assert status_row is not None, (
            f"marketplace status must render a row for {_ENTRY_NAME!r}; got {status_result.stdout!r}"
        )
        assert status_row.split()[-1] == _SETTING_DISABLED, (
            f"a dependency with no _MARKETPLACE line must read {_SETTING_DISABLED!r}; got row {status_row!r}"
        )

        # --- Step 5: remove --------------------------------------------------
        # Remove the alias block from .kanon; the alias is gone afterwards.
        remove_result = _run_kanon(
            "remove",
            _ENTRY_NAME,
            cwd=project,
            extra_env=base_env,
        )
        assert remove_result.returncode == 0, (
            f"remove must exit 0.\n  stdout={remove_result.stdout!r}\n  stderr={remove_result.stderr!r}"
        )
        kanon_after_remove = kanon_file.read_text(encoding="utf-8")
        assert _block_value(kanon_after_remove, _ENTRY_NAME, "_URL") is None, (
            f"remove must delete the {_ENTRY_NAME!r} alias block; .kanon still has it:\n{kanon_after_remove!r}"
        )
        assert f"{_SOURCE_PREFIX}{_ENTRY_NAME}_" not in kanon_after_remove, (
            "no KANON_SOURCE_<alias>_* line for the removed entry may remain"
        )

    def test_install_replays_lock_reproducibly(self, journey_world: "tuple[pathlib.Path, str, str]") -> None:
        """After add, two installs replay the committed lock byte-for-byte (FR-14).

        Confirms the hermetic-install determinism guarantee that the J1 arc
        relies on: the committed .kanon + .kanon.lock fully drive install, so a
        second run reproduces the same lock state (excluding the volatile
        ``generated_at`` line).
        """
        project, catalog_source, kanon_home = journey_world
        kanon_file = project / _KANON_FILENAME
        lock_file = project / _LOCKFILE_NAME
        base_env = {_KANON_HOME_ENV: kanon_home, _CATALOG_SOURCES_ENV: ""}

        add_result = _run_kanon(
            "add",
            _ENTRY_NAME,
            "--catalog-source",
            catalog_source,
            "--kanon-file",
            str(kanon_file),
            cwd=project,
            extra_env=base_env,
        )
        assert add_result.returncode == 0, f"add must succeed: {add_result.stderr!r}"

        install_env = dict(base_env)
        install_env[_INSECURE_REMOTES_ENV] = _INSECURE_REMOTES_VALUE

        def _stable_lock_body() -> str:
            lines = lock_file.read_text(encoding="utf-8").splitlines()
            return "\n".join(line for line in lines if not line.startswith("generated_at"))

        first = _run_kanon("install", str(kanon_file), cwd=project, extra_env=install_env)
        assert first.returncode == 0, f"first install must succeed: {first.stderr!r}"
        first_body = _stable_lock_body()

        second = _run_kanon("install", str(kanon_file), cwd=project, extra_env=install_env)
        assert second.returncode == 0, f"second install must succeed: {second.stderr!r}"
        second_body = _stable_lock_body()

        assert first_body == second_body, "install must replay the committed lock byte-for-byte across runs"


def test_journey_helpers_build_a_real_git_repo(tmp_path: pathlib.Path) -> None:
    """The catalog-repo builder produces a real bare git repo with the release tag.

    Guards the fixture builder itself (a real test that fails if the synthetic
    world stops being constructed correctly), so a green J1 arc is never a
    false pass caused by a broken builder.
    """
    bare = _build_catalog_repo(tmp_path)
    assert bare.is_dir(), "the builder must produce a bare repo directory on disk"
    tag_listing = subprocess.run(
        ["git", "tag", "--list"],
        cwd=str(bare),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert f"{_ENTRY_NAME}/{_RELEASE_VERSION}" in tag_listing
    assert _RELEASE_VERSION in tag_listing.split()
