"""Functional journey J2: ``kanon add`` alias + collision + force (AC-47).

Spec reference: ``specs/kanon-refinements.md`` Section 4.2 (``add`` source-explicit,
alias keying, ``--as`` override, force / same-NAME guard), Section 5.1 (the alias
model + ref sanitization), Section 10.4 (J2 journey), FR-6, FR-11.

This is a hermetic black-box journey driven via the real ``kanon`` CLI in a
subprocess (``python -m kanon_cli``), asserting on exit code / stdout / stderr at
each step.  The operator's world is built from synthetic bare catalog repos (real
``file://`` git repos with a ``repo-specs/<entry>.xml`` carrying a
``<catalog-metadata>`` block and PEP 440 tags), so the journey runs offline and
deterministically on every platform that has ``git``.  No ``skipif``.

The arc covered:

1. Happy path -- source-explicit ``add`` writes the bare-alias block from the
   single ``--catalog-source``.
2. Edge / determinism -- a cross-source add of the SAME manifest name auto-suffixes
   to ``<alias>_<sanitized-source-repo>``; re-reading the committed ``.kanon``
   reproduces both aliases (deterministic on re-read).
3. Error path -- a cross-source ``--as`` collision (the chosen alias is already
   mapped to a different source) fails fast with an actionable message.
4. Force path -- a ``--force`` re-add of the same source@ref overwrites the alias
   block and re-pins its ``.kanon.lock`` entry (the ``resolved_sha`` is updated to
   the source tip while the dep's ``NAME`` is preserved).
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

# ---------------------------------------------------------------------------
# Constants (no inline literals scattered across assertions / fixtures).
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Add Alias Journey User"
_GIT_USER_EMAIL = "add-alias-journey@example.com"
_DEFAULT_BRANCH = "main"

# The shared catalog manifest NAME published by BOTH source repos (the
# cross-source collision driver, spec Section 4.2 / FR-6).
_MANIFEST_NAME = "history"

# The two source-repo basenames. The second is the spec worked-example repo so
# the auto-suffixed alias is the spec's ``history_caylent_private_kanon``.
_REPO_FIRST = "org-a-history"
_REPO_SECOND = "caylent-private-kanon"

# The single PEP 440 tag each source repo publishes.
_RELEASE_TAG = "1.0.0"

# The repo-relative manifest path under repo-specs/.
_XML_FILENAME = "history-marketplace.xml"
_XML_REL_PATH = f"repo-specs/{_XML_FILENAME}"

_SOURCE_PREFIX = "KANON_SOURCE_"
_LOCKFILE_NAME = ".kanon.lock"

# A deliberately wrong placeholder SHA seeded into the lock so the --force re-pin
# is observable (the re-pinned SHA must differ from this stale value).
_STALE_SHA = "0" * 40


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit."""
    result = subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"git {args!r} in {cwd!r} exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


def _git_output(args: list[str], cwd: pathlib.Path) -> str:
    """Run a git command in cwd and return stripped stdout, raising on failure."""
    result = subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"git {args!r} in {cwd!r} exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
    return result.stdout.strip()


def _catalog_xml(name: str) -> str:
    """Return a fully valid catalog-metadata XML body for the given entry name."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<repo-specs>\n"
        "  <catalog-metadata>\n"
        f"    <name>{name}</name>\n"
        f"    <version>=={_RELEASE_TAG}</version>\n"
        "    <display-name>History Package</display-name>\n"
        "    <description>A package published from two source repos for J2.</description>\n"
        "    <type>library</type>\n"
        "    <owner-name>Journey Owner</owner-name>\n"
        "    <owner-email>journey@example.com</owner-email>\n"
        "    <keywords>test journey</keywords>\n"
        "  </catalog-metadata>\n"
        "</repo-specs>\n"
    )


def _create_bare_catalog_repo(base: pathlib.Path, repo_name: str) -> pathlib.Path:
    """Create a bare catalog repo publishing the shared manifest name; return its bare path."""
    work = base / f"{repo_name}-work"
    work.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", _DEFAULT_BRANCH], cwd=work)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work)

    repo_specs = work / "repo-specs"
    repo_specs.mkdir()
    (repo_specs / _XML_FILENAME).write_text(_catalog_xml(_MANIFEST_NAME), encoding="utf-8")
    _git(["add", "."], cwd=work)
    _git(["commit", "-m", "Add history catalog entry"], cwd=work)
    _git(["tag", "-a", _RELEASE_TAG, "-m", f"Release {_RELEASE_TAG}"], cwd=work)

    bare = base / f"{repo_name}.git"
    _git(["clone", "--bare", str(work), str(bare)], cwd=base)
    return bare.resolve()


# ---------------------------------------------------------------------------
# Subprocess runner (real black-box CLI invocation)
# ---------------------------------------------------------------------------


def _run_kanon(
    args: list[str],
    cwd: pathlib.Path,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon CLI via the current interpreter, with no ambient catalog env."""
    env = dict(os.environ)
    env.pop("KANON_CATALOG_SOURCES", None)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
    )


def _block_value(kanon_text: str, alias: str, suffix: str) -> str | None:
    """Return the value of KANON_SOURCE_<alias>_<suffix> from .kanon text, or None."""
    pattern = re.compile(rf"^{re.escape(_SOURCE_PREFIX)}{re.escape(alias)}{re.escape(suffix)}=(.*)$", re.MULTILINE)
    match = pattern.search(kanon_text)
    return match.group(1) if match else None


def _sanitized_repo_alias(base_alias: str, repo_name: str) -> str:
    """Compute the expected cross-source-suffixed alias for a repo name (input-driven)."""
    return f"{base_alias}_{repo_name.replace('-', '_')}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def two_source_world(tmp_path: pathlib.Path) -> tuple[pathlib.Path, str, str]:
    """Build two bare catalog repos and an empty project dir.

    Returns ``(project_dir, source_url_first, source_url_second)`` where each
    source URL is a ``file://<bare>@<tag>`` catalog source publishing the same
    manifest name from a different source repo.
    """
    repos = tmp_path / "repos"
    repos.mkdir()
    bare_first = _create_bare_catalog_repo(repos, _REPO_FIRST)
    bare_second = _create_bare_catalog_repo(repos, _REPO_SECOND)
    source_first = f"file://{bare_first}@{_RELEASE_TAG}"
    source_second = f"file://{bare_second}@{_RELEASE_TAG}"

    project = tmp_path / "project"
    project.mkdir()
    return project, source_first, source_second


# ---------------------------------------------------------------------------
# J2 journey (AC-47)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestAddAliasJourney:
    """J2: source-explicit add, deterministic auto-suffix, --as collision, --force re-pin."""

    def _add(
        self,
        project: pathlib.Path,
        source: str,
        *extra: str,
    ) -> subprocess.CompletedProcess[str]:
        """Run ``kanon add <name> --catalog-source <source> [extra...]`` in the project dir."""
        kanon_file = project / ".kanon"
        return _run_kanon(
            ["add", _MANIFEST_NAME, "--catalog-source", source, "--kanon-file", str(kanon_file), *extra],
            cwd=project,
        )

    def test_source_explicit_add_writes_bare_alias_block(self, two_source_world: tuple[pathlib.Path, str, str]) -> None:
        """Happy path: a source-explicit add writes the bare-alias block (Section 4.2 / FR-11)."""
        project, source_first, _source_second = two_source_world

        result = self._add(project, source_first)
        assert result.returncode == 0, (
            f"source-explicit add must succeed.\n  stdout={result.stdout!r}\n  stderr={result.stderr!r}"
        )
        kanon_text = (project / ".kanon").read_text(encoding="utf-8")
        # The bare alias keys the block and _NAME carries the manifest name.
        assert _block_value(kanon_text, _MANIFEST_NAME, "_URL") is not None
        assert _block_value(kanon_text, _MANIFEST_NAME, "_NAME") == _MANIFEST_NAME
        assert _block_value(kanon_text, _MANIFEST_NAME, "_REF") is not None

    def test_missing_source_fails_fast(self, two_source_world: tuple[pathlib.Path, str, str]) -> None:
        """Error path: add with neither --catalog-source nor a single env source fails fast."""
        project, _source_first, _source_second = two_source_world
        kanon_file = project / ".kanon"
        result = _run_kanon(["add", _MANIFEST_NAME, "--kanon-file", str(kanon_file)], cwd=project)
        assert result.returncode != 0, "add without an explicit source must fail fast"
        assert "catalog" in result.stderr.lower()
        # No .kanon is written on the fail-fast path.
        assert not kanon_file.exists()

    def test_cross_source_add_auto_suffixes_deterministically(
        self, two_source_world: tuple[pathlib.Path, str, str]
    ) -> None:
        """Edge / determinism: a same-NAME add from a 2nd source auto-suffixes; re-read is stable."""
        project, source_first, source_second = two_source_world

        first = self._add(project, source_first)
        assert first.returncode == 0, f"first add failed: {first.stderr!r}"

        second = self._add(project, source_second)
        assert second.returncode == 0, (
            f"cross-source add of the same name must succeed via auto-suffix.\n  stderr={second.stderr!r}"
        )

        kanon_text = (project / ".kanon").read_text(encoding="utf-8")
        expected_suffixed = _sanitized_repo_alias(_MANIFEST_NAME, _REPO_SECOND)
        # First add keeps the bare alias; the second is suffixed with the source repo.
        assert _block_value(kanon_text, _MANIFEST_NAME, "_URL") is not None
        assert _block_value(kanon_text, expected_suffixed, "_URL") is not None
        # The two blocks point at distinct sources and never collapse to "__".
        assert "__" not in expected_suffixed
        first_url = _block_value(kanon_text, _MANIFEST_NAME, "_URL")
        second_url = _block_value(kanon_text, expected_suffixed, "_URL")
        assert first_url != second_url

        # Determinism on re-read: re-adding the SAME first source@ref is now a
        # true duplicate (no-op/error), not a third aliasing -- proving the alias
        # set is reproducible from the committed .kanon and never grows.
        duplicate = self._add(project, source_first)
        assert duplicate.returncode != 0, "re-add of the identical name+source@ref must be a duplicate error"
        reread = (project / ".kanon").read_text(encoding="utf-8")
        assert reread == kanon_text, "a duplicate re-add must not modify the committed .kanon"

    def test_cross_source_as_collision_fails_fast(self, two_source_world: tuple[pathlib.Path, str, str]) -> None:
        """Error path: an --as alias already mapped to a different source fails fast (FR-11)."""
        project, source_first, source_second = two_source_world

        first = self._add(project, source_first)
        assert first.returncode == 0, f"first add failed: {first.stderr!r}"

        # The bare alias is taken by source_first; reusing it via --as for the
        # second (different) source is a hard error, not an auto-suffix.
        collision = self._add(project, source_second, "--as", _MANIFEST_NAME)
        assert collision.returncode != 0, "an --as alias already mapped to a different source must fail fast"
        assert _MANIFEST_NAME in collision.stderr
        # Actionable message points to the remedy.
        assert "--force" in collision.stderr or "kanon remove" in collision.stderr
        # The committed .kanon is unchanged by the failed add.
        kanon_text = (project / ".kanon").read_text(encoding="utf-8")
        assert _block_value(kanon_text, _MANIFEST_NAME, "_URL") is not None
        assert kanon_text.count(f"{_SOURCE_PREFIX}{_MANIFEST_NAME}_URL=") == 1

    def test_as_override_writes_chosen_alias(self, two_source_world: tuple[pathlib.Path, str, str]) -> None:
        """Edge: --as <alias> keys the block by the operator-chosen alias."""
        project, source_first, _source_second = two_source_world
        chosen = "my_history"

        result = self._add(project, source_first, "--as", chosen)
        assert result.returncode == 0, f"--as override add must succeed: {result.stderr!r}"
        kanon_text = (project / ".kanon").read_text(encoding="utf-8")
        assert _block_value(kanon_text, chosen, "_URL") is not None
        # The auto-computed bare alias is NOT written when --as is given.
        assert _block_value(kanon_text, _MANIFEST_NAME, "_URL") is None

    def test_invalid_as_override_fails_fast(self, two_source_world: tuple[pathlib.Path, str, str]) -> None:
        """Error path: an --as alias outside the charset fails fast before any write."""
        project, source_first, _source_second = two_source_world

        result = self._add(project, source_first, "--as", "bad-alias")
        assert result.returncode != 0, "an --as alias with a hyphen must be rejected"
        assert "--as" in result.stderr
        assert not (project / ".kanon").exists()

    def test_force_readd_overwrites_block_and_repins_lock(
        self, two_source_world: tuple[pathlib.Path, str, str]
    ) -> None:
        """Force path: --force re-add of the same source@ref re-pins the lock SHA, keeping NAME."""
        project, source_first, _source_second = two_source_world

        first = self._add(project, source_first)
        assert first.returncode == 0, f"first add failed: {first.stderr!r}"

        # The block's REF spec as written by add (verbatim from the committed .kanon).
        kanon_text = (project / ".kanon").read_text(encoding="utf-8")
        ref_spec = _block_value(kanon_text, _MANIFEST_NAME, "_REF")
        url = _block_value(kanon_text, _MANIFEST_NAME, "_URL")
        assert ref_spec is not None and url is not None

        # Seed a committed .kanon.lock carrying the history alias with a STALE sha
        # so the --force re-pin is observable.
        lock_path = project / _LOCKFILE_NAME
        lock_path.write_text(
            "schema_version = 4\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            f'alias = "{_MANIFEST_NAME}"\n'
            f'name = "{_MANIFEST_NAME}"\n'
            f"url = {url!r}\n"
            f'ref_spec = "{ref_spec}"\n'
            f'resolved_ref = "refs/tags/{_RELEASE_TAG}"\n'
            f'resolved_sha = "{_STALE_SHA}"\n'
            f'path = "{_XML_REL_PATH}"\n',
            encoding="utf-8",
        )

        # --force re-add of the SAME source@ref overwrites the block and re-pins
        # the lock. The expected tip SHA is the real tag SHA on the source repo.
        expected_sha = _git_output(["ls-remote", url, f"refs/tags/{_RELEASE_TAG}"], cwd=project).split("\t")[0]
        assert expected_sha != _STALE_SHA

        forced = self._add(project, source_first, "--force")
        assert forced.returncode == 0, (
            f"--force re-add must succeed.\n  stdout={forced.stdout!r}\n  stderr={forced.stderr!r}"
        )

        lock_text = lock_path.read_text(encoding="utf-8")
        # The lock entry is re-pinned to the real tip SHA (the stale SHA is gone).
        assert f'resolved_sha = "{expected_sha}"' in lock_text
        assert _STALE_SHA not in lock_text
        # The dep's NAME is preserved across the overwrite (spec Section 4.2).
        assert f'name = "{_MANIFEST_NAME}"' in lock_text
        # The alias block stays keyed by the bare alias (overwrite, not auto-suffix).
        kanon_after = (project / ".kanon").read_text(encoding="utf-8")
        assert _block_value(kanon_after, _MANIFEST_NAME, "_URL") == url
        assert _block_value(kanon_after, _sanitized_repo_alias(_MANIFEST_NAME, _REPO_FIRST), "_URL") is None
