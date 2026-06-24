"""CS (Catalog Source PEP 440 Constraints) scenarios from `docs/integration-testing.md`.

Tests that ``--catalog-source <url>@<constraint>`` resolves PEP 440 constraints
(``==``, ``~=``, ``>=``, ``<=``, ``<``, ``>``, ``!=``, ranges, ``latest``, ``*``)
to the correct catalog-repo tag before reading the catalog, and that plain
branches/tags pass through unchanged.

Mode: pre-merge editable mode (``uv run pytest``). The editable install is already
present in the dev environment, so no extra setup is required.  The doc says to run
the category twice (pre-merge editable + post-release PyPI); this file automates the
pre-merge pass only -- the post-release pass is a CI release-gate concern.

3.0.0 surface: ``kanon bootstrap`` was removed; the catalog-source constraint
resolution it exercised is now driven through ``kanon search`` (the doc maps
``bootstrap list`` to ``kanon search``). Each scenario resolves a constraint and
asserts the resolved tag via ``search``.

Fixture: ``cs_catalog_bare`` (class-scoped) -- a bare git repo tagged
1.0.0, 1.0.1, 1.1.0, 1.2.0, 2.0.0, 2.1.0, 3.0.0. Each tag publishes a *single*
catalog entry whose name encodes the tag (``entry_<tag>``, e.g. ``entry_2_0_0``),
so the entry listed by ``kanon search`` uniquely identifies which catalog-repo
tag the constraint resolved to. HEAD on ``main`` is the 3.0.0 commit (the highest
semver tag).

Verification strategy: each scenario runs
``kanon search --catalog-source <url>@<constraint>`` (flag delivery) or the same
with ``KANON_CATALOG_SOURCES`` (env delivery) and asserts that stdout lists the
entry published at the expected tag and lists no entry from any other tag.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import (
    clone_as_bare,
    init_git_work_dir,
    run_git,
    run_kanon,
)


_CS_SCENARIOS: list[tuple[str, str, str, str]] = [
    ("CS-01", "*", "flag", "3.0.0"),
    ("CS-02", "*", "env", "3.0.0"),
    ("CS-03", "latest", "flag", "3.0.0"),
    ("CS-04", "latest", "env", "3.0.0"),
    ("CS-05", "~=1.0.0", "flag", "1.0.1"),
    ("CS-06", "~=1.0.0", "env", "1.0.1"),
    ("CS-07", "~=2.0.0", "flag", "2.0.0"),
    ("CS-08", "~=2.0.0", "env", "2.0.0"),
    ("CS-09", ">=1.0.0,<2.0.0", "flag", "1.2.0"),
    ("CS-10", ">=1.0.0,<2.0.0", "env", "1.2.0"),
    ("CS-11", ">=2.0.0,<3.0.0", "flag", "2.1.0"),
    ("CS-12", ">=2.0.0,<3.0.0", "env", "2.1.0"),
    ("CS-13", ">=1.0.0", "flag", "3.0.0"),
    ("CS-14", ">=1.0.0", "env", "3.0.0"),
    ("CS-15", "<2.0.0", "flag", "1.2.0"),
    ("CS-16", "<2.0.0", "env", "1.2.0"),
    ("CS-17", "<=2.0.0", "flag", "2.0.0"),
    ("CS-18", "<=2.0.0", "env", "2.0.0"),
    ("CS-19", "==1.1.0", "flag", "1.1.0"),
    ("CS-20", "==1.1.0", "env", "1.1.0"),
    ("CS-21", "!=1.0.0", "flag", "3.0.0"),
    ("CS-22", "!=1.0.0", "env", "3.0.0"),
    ("CS-23", ">1.0.0,<2.0.0", "flag", "1.2.0"),
    ("CS-24", ">1.0.0,<2.0.0", "env", "1.2.0"),
    ("CS-25", "main", "flag", "3.0.0"),
    ("CS-26", "2.0.0", "flag", "2.0.0"),
]

_CS_TAGS = ("1.0.0", "1.0.1", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "3.0.0")


_CATALOG_SOURCES_ENV = "KANON_CATALOG_SOURCES"


def _entry_name_for_tag(tag: str) -> str:
    """Return the unique catalog entry name published at the given tag.

    The tag's dots are replaced with underscores so the name is a valid catalog
    entry identifier (e.g. ``2.0.0`` -> ``entry_2_0_0``). Because each tag
    publishes exactly this one entry, the entry listed by ``kanon search``
    pinpoints which catalog-repo tag the constraint resolved to.
    """
    return f"entry_{tag.replace('.', '_')}"


def _marketplace_xml(entry_name: str, version: str) -> str:
    """Return a valid catalog-metadata XML body for a single entry at a version."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        "  <catalog-metadata>\n"
        f"    <name>{entry_name}</name>\n"
        f"    <display-name>{entry_name} Display</display-name>\n"
        f"    <description>CS catalog entry published at tag {version}.</description>\n"
        f"    <version>=={version}</version>\n"
        "    <type>library</type>\n"
        "    <owner-name>CS Owner</owner-name>\n"
        "    <owner-email>cs@example.com</owner-email>\n"
        "    <keywords>cs constraint</keywords>\n"
        "  </catalog-metadata>\n"
        "</manifest>\n"
    )


def _build_cs_catalog_repo(parent: pathlib.Path) -> pathlib.Path:
    """Build a bare catalog repo whose every tag publishes a unique entry.

    Each tag commit replaces ``repo-specs/`` with a single
    ``<entry>-marketplace.xml`` whose entry name encodes the tag
    (``entry_<tag>``). Tags: 1.0.0, 1.0.1, 1.1.0, 1.2.0, 2.0.0, 2.1.0, 3.0.0.
    HEAD on ``main`` is the 3.0.0 commit (the highest semver tag), so plain
    ``main`` resolves to the 3.0.0 entry.
    """
    work = parent / "cs-catalog.work"
    bare = parent / "cs-catalog.git"
    init_git_work_dir(work)

    repo_specs = work / "repo-specs"
    repo_specs.mkdir()

    for tag in _CS_TAGS:
        for stale in repo_specs.glob("*.xml"):
            stale.unlink()
        entry_name = _entry_name_for_tag(tag)
        (repo_specs / f"{entry_name}-marketplace.xml").write_text(_marketplace_xml(entry_name, tag), encoding="utf-8")
        run_git(["add", "-A"], work)
        run_git(["commit", "-m", f"release {tag}"], work)
        run_git(["tag", tag], work)

    return clone_as_bare(work, bare)


@pytest.fixture(scope="class")
def cs_catalog_bare(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Class-scoped bare catalog repo for all CS scenarios."""
    parent = tmp_path_factory.mktemp("cs-fixtures")
    return _build_cs_catalog_repo(parent)


@pytest.mark.scenario
class TestCS:
    """CS-01..CS-26: Catalog Source PEP 440 Constraints (3.0.0 ``search`` surface).

    Each scenario runs ``kanon search`` with the catalog source pinned at a PEP
    440 constraint and asserts that the entry published at the expected tag is
    listed (and no entry from any other tag is). Both delivery modes are covered:

    - ``flag``: ``--catalog-source <url>@<constraint>``
    - ``env``: ``KANON_CATALOG_SOURCES=<url>@<constraint>``
    """

    @pytest.mark.parametrize(
        "cs_id, constraint, delivery, expected_tag",
        _CS_SCENARIOS,
        ids=[s[0] for s in _CS_SCENARIOS],
    )
    def test_cs_constraint(
        self,
        cs_catalog_bare: pathlib.Path,
        cs_id: str,
        constraint: str,
        delivery: str,
        expected_tag: str,
        tmp_path: pathlib.Path,
    ) -> None:
        """Verify that the given PEP 440 constraint resolves to the expected tag.

        Mode: pre-merge editable mode (kanon installed via ``uv run``).
        The bare repo is shared across all 26 scenarios via a class-scoped fixture.

        Verification: ``kanon search`` lists the unique entry published at the
        resolved tag; the entry name pinpoints the resolved tag exactly.
        """
        catalog_url = cs_catalog_bare.as_uri()
        catalog_source = f"{catalog_url}@{constraint}"
        expected_entry = _entry_name_for_tag(expected_tag)

        if delivery == "flag":
            result = run_kanon(
                "search",
                "--catalog-source",
                catalog_source,
                cwd=tmp_path,
            )
        else:
            result = run_kanon(
                "search",
                cwd=tmp_path,
                extra_env={_CATALOG_SOURCES_ENV: catalog_source},
            )

        assert result.returncode == 0, (
            f"{cs_id}: kanon search (@{constraint}) expected exit 0, got {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

        listed_entries = result.stdout.split()
        assert expected_entry in listed_entries, (
            f"{cs_id}: constraint {constraint!r} must resolve to tag {expected_tag!r} "
            f"(entry {expected_entry!r}); got entries {listed_entries!r}\n"
            f"stderr={result.stderr!r}"
        )

        for other_tag in _CS_TAGS:
            if other_tag == expected_tag:
                continue
            other_entry = _entry_name_for_tag(other_tag)
            assert other_entry not in listed_entries, (
                f"{cs_id}: constraint {constraint!r} resolved to the wrong tag; "
                f"entry {other_entry!r} (tag {other_tag!r}) must NOT be listed.\n"
                f"stdout={result.stdout!r}"
            )
