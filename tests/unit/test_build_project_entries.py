"""Unit tests for kanon_cli.core.install.build_project_entries (A2b graph capture).

Exercises the install-side helper that resolves every synced repo package to a
fully-provenanced ``ProjectEntry`` from the already-synced local manifests + the
captured content pins, so the lockfile's previously-empty ``SourceEntry.projects``
layer is populated (which also fixes ``kanon why`` showing no project layer on
install-written lockfiles).

Covers: explicit-remote projects, default-remote / default-revision inheritance,
projects declared in an included manifest, the wildcard ``ref_spec`` and
``resolved_ref`` provenance, name de-duplication, and every skip path (a project
with no captured pin, a project whose remote cannot be resolved, and an empty
content-pin set). Uses on-disk manifest XML fixtures and hand-built content pins,
so no git or network is involved and every produced entry is asserted to
round-trip through ``read_lockfile``'s ``canonical_url`` validation.
"""

from __future__ import annotations

import pathlib

import pytest

from kanon_cli.core.install import build_project_entries
from kanon_cli.core.lockfile import (
    CURRENT_SCHEMA_VERSION,
    ContentPinEntry,
    Lockfile,
    SourceEntry,
    read_lockfile,
    write_lockfile,
)
from kanon_cli.core.url import canonicalize_repo_url


_ROOT_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="gh" fetch="https://github.com/caylent/" />\n'
    '  <default remote="gh" revision="main" />\n'
    '  <include name="inc.xml" />\n'
    '  <project name="p-explicit" path="pp1" remote="gh" revision="refs/tags/1.0.0" />\n'
    '  <project name="p-default" path="pp2" />\n'
    '  <project name="p-noremote-nomap" path="pp5" remote="missing" />\n'
    '  <project name="p-nopin" path="pp6" remote="gh" />\n'
    "</manifest>\n"
)

_INC_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <project name="p-inc" path="pp3" remote="gh" revision="develop" />\n'
    "</manifest>\n"
)


@pytest.fixture()
def _manifest_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Write the root + included manifest XML fixtures and return the repo root."""
    (tmp_path / "root.xml").write_text(_ROOT_XML, encoding="utf-8")
    (tmp_path / "inc.xml").write_text(_INC_XML, encoding="utf-8")
    return tmp_path


def _pins() -> list[ContentPinEntry]:
    """Return content pins for every project that has a materialised checkout."""
    return [
        ContentPinEntry(name="p-explicit", path="pp1", resolved_sha="a" * 40),
        ContentPinEntry(name="p-default", path="pp2", resolved_sha="b" * 40),
        ContentPinEntry(name="p-inc", path="pp3", resolved_sha="c" * 40),
        ContentPinEntry(name="p-noremote-nomap", path="pp5", resolved_sha="d" * 40),
        ContentPinEntry(name="p-orphan", path="pp4", resolved_sha="e" * 40),
    ]


@pytest.mark.unit
def test_resolves_explicit_default_and_included_projects(_manifest_dir: pathlib.Path) -> None:
    """Explicit-remote, default-remote, and included-manifest projects all resolve."""
    root = _manifest_dir / "root.xml"
    inc = _manifest_dir / "inc.xml"
    entries = build_project_entries(root, _manifest_dir, [root, inc], _pins())

    by_name = {e.name: e for e in entries}
    assert by_name["p-explicit"].url == "https://github.com/caylent/p-explicit"
    assert by_name["p-explicit"].canonical_url == canonicalize_repo_url("https://github.com/caylent/p-explicit")
    assert by_name["p-explicit"].ref_spec == "*"
    assert by_name["p-explicit"].resolved_ref == "refs/tags/1.0.0"
    assert by_name["p-explicit"].resolved_sha == "a" * 40

    assert by_name["p-default"].url == "https://github.com/caylent/p-default"
    assert by_name["p-default"].resolved_ref == "main"

    assert by_name["p-inc"].url == "https://github.com/caylent/p-inc"
    assert by_name["p-inc"].resolved_ref == "develop"


@pytest.mark.unit
def test_skips_unresolvable_and_unpinned_and_orphan_projects(_manifest_dir: pathlib.Path) -> None:
    """Projects with no remote map, no captured pin, or no manifest entry are skipped."""
    root = _manifest_dir / "root.xml"
    inc = _manifest_dir / "inc.xml"
    names = {e.name for e in build_project_entries(root, _manifest_dir, [root, inc], _pins())}

    assert "p-noremote-nomap" not in names
    assert "p-nopin" not in names
    assert "p-orphan" not in names
    assert names == {"p-explicit", "p-default", "p-inc"}


@pytest.mark.unit
def test_sorted_by_name(_manifest_dir: pathlib.Path) -> None:
    """Entries are returned sorted by project name for byte-stable lockfile output."""
    root = _manifest_dir / "root.xml"
    inc = _manifest_dir / "inc.xml"
    entries = build_project_entries(root, _manifest_dir, [root, inc], _pins())
    assert [e.name for e in entries] == sorted(e.name for e in entries)


@pytest.mark.unit
def test_empty_content_pins_yields_no_projects(_manifest_dir: pathlib.Path) -> None:
    """With no captured pins (e.g. a mocked sync) no project entries are produced."""
    root = _manifest_dir / "root.xml"
    assert build_project_entries(root, _manifest_dir, [root], []) == []


@pytest.mark.unit
def test_populated_projects_round_trip_through_lockfile(_manifest_dir: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """A source carrying build_project_entries output round-trips through read_lockfile."""
    root = _manifest_dir / "root.xml"
    inc = _manifest_dir / "inc.xml"
    projects = build_project_entries(root, _manifest_dir, [root, inc], _pins())

    lockfile = Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at="2026-07-14T00:00:00Z",
        generator="kanon-cli/test",
        kanon_hash="sha256:" + "a" * 64,
        sources=[
            SourceEntry(
                alias="FOO",
                name="foo",
                url="https://github.com/caylent/foo.git",
                ref_spec="main",
                resolved_ref="refs/heads/main",
                resolved_sha="f" * 40,
                path="repo-specs/root.xml",
                projects=projects,
                content_pins=_pins(),
            )
        ],
    )
    lock_path = tmp_path / "out.kanon.lock"
    write_lockfile(lockfile, lock_path)
    reloaded = read_lockfile(lock_path)

    assert [p.name for p in reloaded.sources[0].projects] == [p.name for p in projects]
