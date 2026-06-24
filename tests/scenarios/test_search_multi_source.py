"""J4 -- `kanon search` multi-source journey (AC-49, spec Section 10.4 / FR-9, FR-10, FR-25).

Drives `kanon search` across two configured catalog sources as a real subprocess,
asserting the spec Section 4.1 multi-source behavior:

- Source-grouped output: a ``Source: <url>@<ref>`` header is written to stderr
  for each reachable source, before that source's entries (never on stdout).
- ``-A``/``--all`` version history vs. the latest-only default: ``-A`` lists every
  ``refs/tags/<name>/<pep440>`` release for each matching entry plus the branch-tip
  ``(latest)`` marker; the default mode shows only the latest.
- Skip + warn on an unreachable source: one bad source is skipped with a stderr
  WARNING (FLAG-B) and does NOT hard-fail the whole search -- the reachable source
  is still rendered and the command exits 0.

Each test isolates the TTL cache via a per-test ``KANON_HOME`` so the concurrent
enumeration writes/reads its ``cache/search/<sha>/versions.txt`` entries in a
sandbox and never touches the operator's real cache. The cache resolves under
``<KANON_HOME>/cache`` (the shared KANON_HOME store model).
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from tests.scenarios.conftest import (
    clone_as_bare,
    init_git_work_dir,
    run_git,
    run_kanon,
)

# ---------------------------------------------------------------------------
# Fixture builders: a name-namespaced catalog manifest repo
# ---------------------------------------------------------------------------

_MARKETPLACE_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>Entry {name} in {repo}.</description>
        <version>{version}</version>
        <type>plugin</type>
        <owner-name>Scenario Owner</owner-name>
        <owner-email>owner@kanon.example</owner-email>
        <keywords>{name}</keywords>
      </catalog-metadata>
    </manifest>
""")


def _build_catalog_repo(
    parent: pathlib.Path,
    repo_name: str,
    entry_name: str,
    versions: tuple[str, ...],
) -> pathlib.Path:
    """Build a bare catalog manifest repo with name-namespaced release tags.

    On ``main`` the repo carries ``repo-specs/<entry_name>-marketplace.xml`` whose
    ``<catalog-metadata><name>`` is ``entry_name`` and ``<version>`` is the newest
    version. For each version a ``refs/tags/<entry_name>/<version>`` tag is cut
    (the per-manifest catalog tag scheme, spec Section 6). The newest version is
    the tip of ``main`` so the branch-tip "latest" resolves cleanly.

    Args:
        parent: Temp parent directory.
        repo_name: Name for the on-disk ``<name>.git`` bare repo.
        entry_name: The catalog entry (manifest) name.
        versions: Release versions, oldest-first.

    Returns:
        The resolved bare repo path.
    """
    work = parent / f"{repo_name}.work"
    bare = parent / f"{repo_name}.git"
    init_git_work_dir(work)

    spec_dir = work / "repo-specs"
    spec_dir.mkdir(parents=True)
    xml_path = spec_dir / f"{entry_name}-marketplace.xml"

    for version in versions:
        xml_path.write_text(_MARKETPLACE_XML_TEMPLATE.format(name=entry_name, repo=repo_name, version=version))
        run_git(["add", "repo-specs"], work)
        run_git(["commit", "-m", f"release {entry_name}/{version}"], work)
        run_git(["tag", f"{entry_name}/{version}"], work)

    return clone_as_bare(work, bare)


# Source A: entry "alpha" with three releases.
_A_ENTRY = "alpha"
_A_VERSIONS = ("1.0.0", "1.1.0", "1.2.0")

# Source B: entry "beta" with two releases.
_B_ENTRY = "beta"
_B_VERSIONS = ("0.9.0", "1.0.0")


@pytest.fixture()
def multi_source_setup(tmp_path: pathlib.Path) -> dict[str, object]:
    """Build two reachable catalog sources, one unreachable source, and a KANON_HOME.

    The cache resolves under ``<KANON_HOME>/cache``; ``cache_dir`` in the returned
    mapping is that resolved cache directory, so the existing
    ``cache_dir / "search"`` assertions line up with where the CLI actually
    writes its TTL cache.
    """
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()

    repo_a = _build_catalog_repo(fixtures, "catalog-a", _A_ENTRY, _A_VERSIONS)
    repo_b = _build_catalog_repo(fixtures, "catalog-b", _B_ENTRY, _B_VERSIONS)

    source_a = f"{repo_a.as_uri()}@main"
    source_b = f"{repo_b.as_uri()}@main"

    # An unreachable source: a file:// URI to a path that does not exist.
    missing = fixtures / "does-not-exist.git"
    source_unreachable = f"{missing.as_uri()}@main"

    kanon_home = tmp_path / "kanon-home"
    kanon_home.mkdir()
    # The CLI resolves the cache as <KANON_HOME>/cache; expose that resolved
    # directory so search-cache assertions point at the real location.
    cache_dir = kanon_home / "cache"

    return {
        "source_a": source_a,
        "source_b": source_b,
        "source_unreachable": source_unreachable,
        "kanon_home": str(kanon_home),
        "cache_dir": str(cache_dir),
    }


# ---------------------------------------------------------------------------
# J4 scenario tests
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestSearchMultiSourceJourney:
    """J4: search across two sources -- grouping, -A vs latest-only, skip+warn."""

    def test_source_grouped_output_default_latest_only(self, multi_source_setup: dict[str, object]) -> None:
        """Two reachable sources render under separate ``Source:`` headers on stderr.

        Default (latest-only) mode prints each matching entry once; the per-source
        header is on stderr (not stdout) so stdout stays pipeable.
        """
        source_a = str(multi_source_setup["source_a"])
        source_b = str(multi_source_setup["source_b"])
        kanon_home = str(multi_source_setup["kanon_home"])

        result = run_kanon(
            "search",
            "--catalog-source",
            source_a,
            "--catalog-source",
            source_b,
            extra_env={"KANON_HOME": kanon_home},
        )

        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        # Both source group headers are on stderr, never on stdout.
        assert f"Source: {source_a}" in result.stderr
        assert f"Source: {source_b}" in result.stderr
        assert "Source:" not in result.stdout
        # Default mode shows the latest of each entry (one row per matching entry).
        assert f"{_A_ENTRY} (latest)" in result.stdout
        assert f"{_B_ENTRY} (latest)" in result.stdout
        # Latest-only default does NOT enumerate the full release history.
        assert f"{_A_ENTRY}@1.0.0" not in result.stdout
        assert f"{_B_ENTRY}@0.9.0" not in result.stdout

    def test_all_versions_shows_full_history_per_source(self, multi_source_setup: dict[str, object]) -> None:
        """-A/--all lists every refs/tags/<name>/<pep440> release plus the (latest) tip."""
        source_a = str(multi_source_setup["source_a"])
        source_b = str(multi_source_setup["source_b"])
        kanon_home = str(multi_source_setup["kanon_home"])

        result = run_kanon(
            "search",
            "-A",
            "--catalog-source",
            source_a,
            "--catalog-source",
            source_b,
            extra_env={"KANON_HOME": kanon_home},
        )

        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        # Every alpha release is enumerated (source A).
        for version in _A_VERSIONS:
            assert f"{_A_ENTRY}@{version}" in result.stdout, (
                f"missing {_A_ENTRY}@{version} in -A output: {result.stdout!r}"
            )
        # Every beta release is enumerated (source B).
        for version in _B_VERSIONS:
            assert f"{_B_ENTRY}@{version}" in result.stdout
        # Each entry also shows the branch-tip latest marker.
        assert f"{_A_ENTRY} (latest)" in result.stdout
        assert f"{_B_ENTRY} (latest)" in result.stdout
        # Both source headers present on stderr.
        assert f"Source: {source_a}" in result.stderr
        assert f"Source: {source_b}" in result.stderr

    def test_all_versions_newest_first_within_source(self, multi_source_setup: dict[str, object]) -> None:
        """-A renders alpha's releases newest-first (1.2.0 before 1.0.0)."""
        source_a = str(multi_source_setup["source_a"])
        source_b = str(multi_source_setup["source_b"])
        kanon_home = str(multi_source_setup["kanon_home"])

        result = run_kanon(
            "search",
            "-A",
            "--catalog-source",
            source_a,
            "--catalog-source",
            source_b,
            extra_env={"KANON_HOME": kanon_home},
        )

        assert result.returncode == 0
        out = result.stdout
        idx_newest = out.index(f"{_A_ENTRY}@1.2.0")
        idx_mid = out.index(f"{_A_ENTRY}@1.1.0")
        idx_oldest = out.index(f"{_A_ENTRY}@1.0.0")
        assert idx_newest < idx_mid < idx_oldest, f"alpha versions not newest-first: {out!r}"

    def test_unreachable_source_skip_and_warn(self, multi_source_setup: dict[str, object]) -> None:
        """An unreachable source is skipped with a stderr WARNING; search still exits 0.

        The reachable source's entry is still rendered, proving skip+warn does not
        hard-fail the whole search (spec Section 4.1 / FLAG-B).
        """
        source_a = str(multi_source_setup["source_a"])
        source_unreachable = str(multi_source_setup["source_unreachable"])
        kanon_home = str(multi_source_setup["kanon_home"])

        result = run_kanon(
            "search",
            "--catalog-source",
            source_a,
            "--catalog-source",
            source_unreachable,
            extra_env={"KANON_HOME": kanon_home},
        )

        # skip+warn: the whole search is NOT hard-failed.
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        # A WARNING names the unreachable source on stderr.
        assert "WARNING" in result.stderr
        assert source_unreachable in result.stderr
        # The reachable source is still rendered.
        assert f"Source: {source_a}" in result.stderr
        assert f"{_A_ENTRY} (latest)" in result.stdout
        # The unreachable source is NOT rendered as a group header.
        assert f"Source: {source_unreachable}" not in result.stderr

    def test_filter_narrows_across_sources(self, multi_source_setup: dict[str, object]) -> None:
        """A positional substring filter narrows entries within each source group."""
        source_a = str(multi_source_setup["source_a"])
        source_b = str(multi_source_setup["source_b"])
        kanon_home = str(multi_source_setup["kanon_home"])

        result = run_kanon(
            "search",
            _A_ENTRY,
            "--catalog-source",
            source_a,
            "--catalog-source",
            source_b,
            extra_env={"KANON_HOME": kanon_home},
        )

        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        # alpha matches; beta does not.
        assert f"{_A_ENTRY} (latest)" in result.stdout
        assert _B_ENTRY not in result.stdout

    def test_no_matches_exits_zero_with_note(self, multi_source_setup: dict[str, object]) -> None:
        """A filter matching nothing across all sources exits 0 with a 'no matches' note."""
        source_a = str(multi_source_setup["source_a"])
        source_b = str(multi_source_setup["source_b"])
        kanon_home = str(multi_source_setup["kanon_home"])

        result = run_kanon(
            "search",
            "this-entry-does-not-exist-anywhere",
            "--catalog-source",
            source_a,
            "--catalog-source",
            source_b,
            extra_env={"KANON_HOME": kanon_home},
        )

        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "no matches" in result.stderr
        assert _A_ENTRY not in result.stdout
        assert _B_ENTRY not in result.stdout

    def test_cache_reused_within_ttl(self, multi_source_setup: dict[str, object]) -> None:
        """The TTL cache is populated by the first -A run and reused on the second.

        After the first multi-source -A search, the per-source enumeration is
        written under ``<cache>/search/<sha>/versions.txt``. A second identical run
        within the TTL reads through that cache (proving the search version
        enumeration is TTL-cached, spec Section 4.1 / FR-25 / AC-17).
        """
        source_a = str(multi_source_setup["source_a"])
        source_b = str(multi_source_setup["source_b"])
        kanon_home = str(multi_source_setup["kanon_home"])
        # The CLI writes its TTL cache under <KANON_HOME>/cache; the fixture's
        # cache_dir is exactly that resolved directory.
        cache_dir = pathlib.Path(str(multi_source_setup["cache_dir"]))

        first = run_kanon(
            "search",
            "-A",
            "--catalog-source",
            source_a,
            "--catalog-source",
            source_b,
            extra_env={"KANON_HOME": kanon_home},
        )
        assert first.returncode == 0, f"stdout={first.stdout!r} stderr={first.stderr!r}"

        # The search cache namespace now holds at least one per-source entry.
        search_cache = cache_dir / "search"
        assert search_cache.is_dir(), f"search cache dir not created under {cache_dir}"
        versions_files = list(search_cache.rglob("versions.txt"))
        assert versions_files, f"no versions.txt cache entry written under {search_cache}"
        # The cached enumeration carries the alpha release tags.
        cached_text = "\n".join(p.read_text() for p in versions_files)
        assert "1.2.0" in cached_text

        # A second identical run within the TTL still succeeds and renders history.
        second = run_kanon(
            "search",
            "-A",
            "--catalog-source",
            source_a,
            "--catalog-source",
            source_b,
            extra_env={"KANON_HOME": kanon_home},
        )
        assert second.returncode == 0
        assert f"{_A_ENTRY}@1.2.0" in second.stdout
