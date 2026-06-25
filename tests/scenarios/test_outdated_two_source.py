"""Scenario: ``kanon outdated`` across a two-source workspace (item 19 / Area F).

Drives ``kanon outdated`` end-to-end against an on-disk two-source workspace,
exactly as a consumer would, asserting the spec Section 4.4 / inventory item 19
behaviour for the alias-keyed 3.0.0 schema:

- ``--format table`` renders one ``alias -> name from <url>@<ref>`` provenance
  line per source (built from the per-alias ``KANON_SOURCE_<alias>_NAME`` and
  ``KANON_SOURCE_<alias>_URL`` block keys) followed by the fixed-width table
  whose ``name`` column carries each source alias and whose ``upgrade-type``
  column reflects the lock-vs-catalog delta.
- ``--fail-on-upgrade`` flips the exit code from 0 to 1: a workspace with at
  least one upgradable source exits 1 (and names the upgradable alias on
  stderr), while the same command without the flag exits 0, and a workspace
  whose sources are all at the latest matching tag exits 0 even with the flag.
- A single configured ``KANON_CATALOG_SOURCES`` entry is honoured when
  ``--catalog-source`` is omitted (spec Section 4.2 single-source precedence):
  the command resolves the catalog from the env var alone and renders the same
  rows.

The fixtures mirror the ``tests/scenarios`` style: per-alias ``.kanon`` blocks
are written with the shared ``write_kanonenv`` helper, project repos are built
with ``make_bare_repo_with_tags``, and the catalog manifest repo is built from
the same ``repo-specs/<name>-marketplace.xml`` layout the J4 search scenario
uses. Each test runs against its own ``tmp_path`` workspace so the suite stays
isolated.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from tests.scenarios.conftest import (
    clone_as_bare,
    init_git_work_dir,
    make_bare_repo_with_tags,
    run_git,
    run_kanon,
    write_kanonenv,
)


_MARKETPLACE_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>Scenario catalog entry for {name}.</description>
        <version>{version}</version>
        <type>plugin</type>
        <owner-name>Scenario Owner</owner-name>
        <owner-email>owner@kanon.example</owner-email>
        <keywords>{name}</keywords>
      </catalog-metadata>
    </manifest>
""")


_ALIAS_TIDY = "TIDY"
_ALIAS_TIDY_TAGS = ("1.0.0", "1.0.1", "1.1.0")
_ALIAS_TIDY_SPEC = ">=1.0.0,<1.1"

_ALIAS_FRESH = "FRESH"
_ALIAS_FRESH_TAGS = ("2.0.0", "2.0.1")
_ALIAS_FRESH_SPEC = ">=2.0.0,<2.1"


def _build_catalog_repo(parent: pathlib.Path, entry_names: tuple[str, ...]) -> pathlib.Path:
    """Build a bare catalog manifest repo carrying one entry per name.

    Each entry name gets a ``repo-specs/<name>-marketplace.xml`` whose
    ``<catalog-metadata><name>`` is the entry name. ``kanon outdated`` parses
    this catalog to validate the configured source, then fetches each project's
    tags directly from its ``KANON_SOURCE_<alias>_URL`` remote.

    Args:
        parent: Temp parent directory.
        entry_names: Catalog entry (manifest) names to declare.

    Returns:
        The resolved bare catalog repo path.
    """
    work = parent / "catalog.work"
    bare = parent / "catalog.git"
    init_git_work_dir(work)

    spec_dir = work / "repo-specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / ".gitkeep").write_text("")

    for name in entry_names:
        xml_path = spec_dir / f"{name}-marketplace.xml"
        xml_path.write_text(_MARKETPLACE_XML_TEMPLATE.format(name=name, version="1.0.0"))

    run_git(["add", "repo-specs"], work)
    run_git(["commit", "-m", "seed catalog"], work)
    return clone_as_bare(work, bare)


def _tag_sha(url: str, tag: str, cwd: pathlib.Path) -> str:
    """Return the full commit SHA for ``refs/tags/<tag>`` on the remote ``url``."""
    result = run_git(["ls-remote", url, f"refs/tags/{tag}"], cwd)
    line = result.stdout.strip()
    if not line:
        raise LookupError(f"tag {tag!r} not found on {url!r}: {result.stdout!r}")
    return line.split("\t")[0]


def _write_lockfile(lock_file: pathlib.Path, sources: list[dict[str, str]]) -> None:
    """Write a minimal schema-v4 ``.kanon.lock`` for the given alias-keyed sources.

    Schema v4 (spec item 7) is alias-keyed with no ``[catalog]`` block; each
    ``[[sources]]`` entry carries ``alias``, ``name``, ``url``, ``ref_spec``,
    ``resolved_ref``, ``resolved_sha`` and ``path``.

    Args:
        lock_file: Destination path for the lockfile.
        sources: One dict per source with keys ``alias``, ``name``, ``url``,
            ``ref_spec``, ``resolved_ref``, ``resolved_sha`` and ``path``.
    """
    lines = [
        "schema_version = 4",
        'generated_at = "2026-01-01T00:00:00Z"',
        'generator = "kanon-cli/scenario"',
        f'kanon_hash = "sha256:{"a" * 64}"',
    ]
    for source in sources:
        lines.append("")
        lines.append("[[sources]]")
        lines.append(f"alias = {source['alias']!r}")
        lines.append(f"name = {source['name']!r}")
        lines.append(f"url = {source['url']!r}")
        lines.append(f"ref_spec = {source['ref_spec']!r}")
        lines.append(f"resolved_ref = {source['resolved_ref']!r}")
        lines.append(f"resolved_sha = {source['resolved_sha']!r}")
        lines.append(f"path = {source['path']!r}")
    lock_file.write_text("\n".join(lines) + "\n")


@pytest.fixture()
def two_source_workspace(tmp_path: pathlib.Path) -> dict[str, object]:
    """Build a two-source workspace: two project repos, a catalog, ``.kanon`` + lock.

    ``TIDY`` is pinned (via its lock entry) to ``1.0.0`` under a ``>=1.0.0,<1.1``
    spec, so ``1.0.1`` is available within-spec -- an upgradable (``patch``)
    source. ``FRESH`` is pinned to ``2.0.1`` under ``>=2.0.0,<2.1``, the latest
    matching tag, so it is at-latest (``none``). This asymmetry lets the same
    workspace prove both the table provenance rows and the ``--fail-on-upgrade``
    exit-1 transition.

    Returns a mapping with the workspace dir, the catalog ``<url>@main`` source,
    each project URL, and the lock-file path.
    """
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()

    tidy_bare = make_bare_repo_with_tags(fixtures, "tidy", _ALIAS_TIDY_TAGS)
    fresh_bare = make_bare_repo_with_tags(fixtures, "fresh", _ALIAS_FRESH_TAGS)
    tidy_url = tidy_bare.as_uri()
    fresh_url = fresh_bare.as_uri()

    catalog_bare = _build_catalog_repo(fixtures, (_ALIAS_TIDY, _ALIAS_FRESH))
    catalog_source = f"{catalog_bare.as_uri()}@main"

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    write_kanonenv(
        workspace,
        sources=[
            (_ALIAS_TIDY, tidy_url, _ALIAS_TIDY_SPEC, "./tidy"),
            (_ALIAS_FRESH, fresh_url, _ALIAS_FRESH_SPEC, "./fresh"),
        ],
    )

    tidy_sha_100 = _tag_sha(tidy_url, "1.0.0", workspace)
    fresh_sha_201 = _tag_sha(fresh_url, "2.0.1", workspace)

    lock_file = workspace / ".kanon.lock"
    _write_lockfile(
        lock_file,
        sources=[
            {
                "alias": _ALIAS_TIDY,
                "name": _ALIAS_TIDY,
                "url": tidy_url,
                "ref_spec": _ALIAS_TIDY_SPEC,
                "resolved_ref": "refs/tags/1.0.0",
                "resolved_sha": tidy_sha_100,
                "path": "./tidy",
            },
            {
                "alias": _ALIAS_FRESH,
                "name": _ALIAS_FRESH,
                "url": fresh_url,
                "ref_spec": _ALIAS_FRESH_SPEC,
                "resolved_ref": "refs/tags/2.0.1",
                "resolved_sha": fresh_sha_201,
                "path": "./fresh",
            },
        ],
    )

    return {
        "workspace": workspace,
        "catalog_source": catalog_source,
        "tidy_url": tidy_url,
        "fresh_url": fresh_url,
        "lock_file": str(lock_file),
    }


@pytest.mark.scenario
class TestOutdatedTwoSourceJourney:
    """Item 19: two-source ``outdated`` -- table rows + ``--fail-on-upgrade`` transition."""

    def test_table_renders_alias_name_rows_and_upgrade_types(self, two_source_workspace: dict[str, object]) -> None:
        """``--format table`` renders both ``alias -> name from url@ref`` rows + the table.

        Each source contributes a provenance line built from its per-alias
        ``_NAME``/``_URL``/``_REF`` block keys; the table ``name`` column carries
        the alias and the ``upgrade-type`` column reflects the lock-vs-spec delta
        (TIDY is a within-spec ``patch``; FRESH is at-latest ``none``).
        """
        workspace = pathlib.Path(str(two_source_workspace["workspace"]))
        catalog_source = str(two_source_workspace["catalog_source"])
        tidy_url = str(two_source_workspace["tidy_url"])
        fresh_url = str(two_source_workspace["fresh_url"])
        lock_file = str(two_source_workspace["lock_file"])

        result = run_kanon(
            "outdated",
            "--catalog-source",
            catalog_source,
            "--lock-file",
            lock_file,
            "--format",
            "table",
            cwd=workspace,
            extra_env={"KANON_CATALOG_SOURCES": ""},
        )

        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

        assert f"{_ALIAS_TIDY} -> {_ALIAS_TIDY} from {tidy_url}@{_ALIAS_TIDY_SPEC}" in result.stdout
        assert f"{_ALIAS_FRESH} -> {_ALIAS_FRESH} from {fresh_url}@{_ALIAS_FRESH_SPEC}" in result.stdout

        assert "name" in result.stdout
        assert "upgrade-type" in result.stdout

        out_lines = result.stdout.splitlines()
        tidy_row = next(line for line in out_lines if line.startswith(f"{_ALIAS_TIDY} ") and "|" in line)
        fresh_row = next(line for line in out_lines if line.startswith(f"{_ALIAS_FRESH} ") and "|" in line)

        tidy_cells = [c.strip() for c in tidy_row.split("|")]
        fresh_cells = [c.strip() for c in fresh_row.split("|")]

        assert tidy_cells[0] == _ALIAS_TIDY
        assert tidy_cells[1] == "1.0.0"
        assert tidy_cells[2] == "1.0.1"
        assert tidy_cells[3] == "1.1.0"
        assert tidy_cells[4] == "patch"

        assert fresh_cells[0] == _ALIAS_FRESH
        assert fresh_cells[1] == "2.0.1"
        assert fresh_cells[2] == "2.0.1"
        assert fresh_cells[4] == "none"

    def test_fail_on_upgrade_flips_exit_code_from_zero_to_one(self, two_source_workspace: dict[str, object]) -> None:
        """The same workspace exits 0 without ``--fail-on-upgrade`` and 1 with it.

        Without the flag ``outdated`` always exits 0 (parity with
        ``pip list --outdated``); with the flag it exits 1 because TIDY has a
        within-spec patch upgrade, and the upgradable alias is named on stderr.
        """
        workspace = pathlib.Path(str(two_source_workspace["workspace"]))
        catalog_source = str(two_source_workspace["catalog_source"])
        lock_file = str(two_source_workspace["lock_file"])

        base_args = (
            "outdated",
            "--catalog-source",
            catalog_source,
            "--lock-file",
            lock_file,
        )

        without_flag = run_kanon(
            *base_args,
            cwd=workspace,
            extra_env={"KANON_CATALOG_SOURCES": ""},
        )
        assert without_flag.returncode == 0, (
            f"expected exit 0 without --fail-on-upgrade; stdout={without_flag.stdout!r} stderr={without_flag.stderr!r}"
        )

        with_flag = run_kanon(
            *base_args,
            "--fail-on-upgrade",
            cwd=workspace,
            extra_env={"KANON_CATALOG_SOURCES": ""},
        )
        assert with_flag.returncode == 1, (
            f"expected exit 1 with --fail-on-upgrade and TIDY upgradable; "
            f"stdout={with_flag.stdout!r} stderr={with_flag.stderr!r}"
        )

        assert "outdated source(s) found" in with_flag.stderr
        assert _ALIAS_TIDY in with_flag.stderr
        assert _ALIAS_FRESH not in with_flag.stderr.replace("outdated source(s) found", "")

    def test_fail_on_upgrade_exits_zero_when_all_at_latest(self, two_source_workspace: dict[str, object]) -> None:
        """``--fail-on-upgrade`` exits 0 once every source is locked to its latest tag.

        Rewriting the lock so TIDY is pinned to ``1.0.1`` (the highest tag within
        ``>=1.0.0,<1.1``) leaves no upgradable source, so the gate passes.
        """
        workspace = pathlib.Path(str(two_source_workspace["workspace"]))
        catalog_source = str(two_source_workspace["catalog_source"])
        tidy_url = str(two_source_workspace["tidy_url"])
        fresh_url = str(two_source_workspace["fresh_url"])
        lock_file = pathlib.Path(str(two_source_workspace["lock_file"]))

        tidy_sha_101 = _tag_sha(tidy_url, "1.0.1", workspace)
        fresh_sha_201 = _tag_sha(fresh_url, "2.0.1", workspace)

        _write_lockfile(
            lock_file,
            sources=[
                {
                    "alias": _ALIAS_TIDY,
                    "name": _ALIAS_TIDY,
                    "url": tidy_url,
                    "ref_spec": _ALIAS_TIDY_SPEC,
                    "resolved_ref": "refs/tags/1.0.1",
                    "resolved_sha": tidy_sha_101,
                    "path": "./tidy",
                },
                {
                    "alias": _ALIAS_FRESH,
                    "name": _ALIAS_FRESH,
                    "url": fresh_url,
                    "ref_spec": _ALIAS_FRESH_SPEC,
                    "resolved_ref": "refs/tags/2.0.1",
                    "resolved_sha": fresh_sha_201,
                    "path": "./fresh",
                },
            ],
        )

        result = run_kanon(
            "outdated",
            "--catalog-source",
            catalog_source,
            "--lock-file",
            str(lock_file),
            "--fail-on-upgrade",
            cwd=workspace,
            extra_env={"KANON_CATALOG_SOURCES": ""},
        )

        assert result.returncode == 0, (
            f"expected exit 0 with --fail-on-upgrade when all sources at latest; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "outdated source(s) found" not in result.stderr

    def test_single_env_catalog_source_honored_without_flag(self, two_source_workspace: dict[str, object]) -> None:
        """A single ``KANON_CATALOG_SOURCES`` entry is honoured when ``--catalog-source`` is omitted.

        Per spec Section 4.2 the catalog-source precedence is ``--catalog-source``
        then the single configured ``KANON_CATALOG_SOURCES`` entry. With the flag
        omitted and exactly one env entry set, ``outdated`` resolves the catalog
        from the env var alone and renders the same alias->name provenance rows.
        """
        workspace = pathlib.Path(str(two_source_workspace["workspace"]))
        catalog_source = str(two_source_workspace["catalog_source"])
        tidy_url = str(two_source_workspace["tidy_url"])
        fresh_url = str(two_source_workspace["fresh_url"])
        lock_file = str(two_source_workspace["lock_file"])

        result = run_kanon(
            "outdated",
            "--lock-file",
            lock_file,
            "--format",
            "table",
            cwd=workspace,
            extra_env={"KANON_CATALOG_SOURCES": catalog_source},
        )

        assert result.returncode == 0, (
            f"expected exit 0 resolving catalog from single KANON_CATALOG_SOURCES entry; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

        assert f"{_ALIAS_TIDY} -> {_ALIAS_TIDY} from {tidy_url}@{_ALIAS_TIDY_SPEC}" in result.stdout
        assert f"{_ALIAS_FRESH} -> {_ALIAS_FRESH} from {fresh_url}@{_ALIAS_FRESH_SPEC}" in result.stdout

        out_lines = result.stdout.splitlines()
        tidy_row = next(line for line in out_lines if line.startswith(f"{_ALIAS_TIDY} ") and "|" in line)
        tidy_cells = [c.strip() for c in tidy_row.split("|")]
        assert tidy_cells[0] == _ALIAS_TIDY
        assert tidy_cells[4] == "patch"
