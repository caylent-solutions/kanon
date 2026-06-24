"""Functional journey J9: validation journeys (AC-54).

Drives the real ``kanon validate`` CLI as a subprocess over on-disk fixtures,
covering the three validation legs of spec Section 10.4 / FR-22, FR-23, FR-24,
FR-44:

1. Exact-tag ``<project revision>`` accept/reject -- ``kanon validate
   marketplace`` accepts an exact ``refs/tags/<path>/<pep440>`` revision and
   rejects a branch, the wildcard, and a version-range constraint with a
   non-zero exit and an actionable exact-tag error. This is the leg this task
   lands (the exact-only ``<project revision>`` complete-replacement of the
   permissive validator).
2. ``<catalog-metadata><version>`` enforcement -- ``kanon validate metadata``
   accepts a well-formed catalog entry and rejects one whose ``<version>``
   field is absent (the human-edited / malformed metadata leg), exiting
   non-zero with the metadata error on stderr.
3. ``kanon validate lockfile`` drift -- a ``.kanon`` whose alias set / ref-specs
   disagree with its ``.kanon.lock`` exits non-zero with an actionable drift
   message; a consistent pair exits 0.

Every leg drives the black-box CLI (``python -m kanon_cli ...``) via the shared
``_run_kanon`` helper; no leg invokes the network (the marketplace projects use
an unresolved ``<remote>`` so the existence check is skipped, and ``validate
lockfile`` only reads the two files).
"""

import xml.etree.ElementTree as ET

import pytest

from kanon_cli.core.lockfile import Lockfile, SourceEntry, write_lockfile

from tests.functional.conftest import _run_kanon


_VALIDATE = "validate"
_MARKETPLACE = "marketplace"
_METADATA = "metadata"
_LOCKFILE = "lockfile"
_REPO_ROOT_FLAG = "--repo-root"

_KANONENV_FILENAME = ".kanon"
_LOCK_FILENAME = ".kanon.lock"

_EXACT_TAG = "refs/tags/example/proj/1.0.0"
_VALID_SHA40 = "a" * 40
_VALID_KANON_HASH = "sha256:" + "a" * 64

_ALPHA = "alpha"
_BETA = "beta"
_REF_PINNED = "==1.2.3"
_REF_DRIFTED = "==9.9.9"


def _marketplace_xml(revision: str, *, with_version: bool = True) -> str:
    """Build a catalog-entry marketplace XML body with one project.

    Built via ElementTree so attribute values containing ``<`` / ``>`` (range
    constraints) are XML-encoded rather than producing invalid XML.

    Args:
        revision: The ``<project revision>`` attribute value.
        with_version: When False, omit the ``<catalog-metadata><version>``
            element so the metadata required-field check fails.

    Returns:
        The XML body string (without the XML declaration header).
    """
    root = ET.Element("manifest")
    project = ET.SubElement(root, "project", name="proj", path=".packages/proj", remote="r", revision=revision)
    ET.SubElement(project, "linkfile", src="s", dest="${CLAUDE_MARKETPLACES_DIR}/proj")
    meta = ET.SubElement(root, "catalog-metadata")
    ET.SubElement(meta, "name").text = "proj"
    ET.SubElement(meta, "display-name").text = "Proj"
    ET.SubElement(meta, "description").text = "d"
    if with_version:
        ET.SubElement(meta, "version").text = "1.0.0"
    return ET.tostring(root, encoding="unicode")


def _make_catalog_repo(tmp_path, xml_body: str):
    """Write a repo-specs/ tree carrying one marketplace XML; return the repo root."""
    repo_root = tmp_path / "catalog"
    specs = repo_root / "repo-specs"
    specs.mkdir(parents=True)
    (specs / "proj-marketplace.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body, encoding="utf-8")
    return repo_root


@pytest.mark.functional
class TestExactTagRevisionJourney:
    """AC-54 leg 1: exact-only <project revision> accept/reject via the real CLI."""

    def test_exact_tag_revision_accepted(self, tmp_path) -> None:
        """An exact refs/tags/<path>/<pep440> revision validates green (exit 0)."""
        repo_root = _make_catalog_repo(tmp_path, _marketplace_xml(_EXACT_TAG))

        result = _run_kanon(_VALIDATE, _MARKETPLACE, _REPO_ROOT_FLAG, str(repo_root))

        assert result.returncode == 0, (
            f"AC-54: an exact-tag revision must pass.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert result.stderr == "", f"AC-54: no stderr expected on success.\n  stderr: {result.stderr!r}"

    @pytest.mark.parametrize(
        "rejected_revision",
        [
            "main",
            "*",
            ">=1.0.0,<2.0.0",
            "~=1.2.0",
            "refs/tags/example/proj/*",
            "refs/heads/main",
        ],
    )
    def test_non_exact_revision_rejected(self, tmp_path, rejected_revision: str) -> None:
        """A branch / wildcard / range-constraint revision exits 1 with the exact-tag error."""
        repo_root = _make_catalog_repo(tmp_path, _marketplace_xml(rejected_revision))

        result = _run_kanon(_VALIDATE, _MARKETPLACE, _REPO_ROOT_FLAG, str(repo_root))

        assert result.returncode == 1, (
            f"AC-54: revision={rejected_revision!r} must be rejected exact-only.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert "exact" in result.stderr.lower(), (
            f"AC-54: expected an actionable exact-tag error on stderr.\n  stderr: {result.stderr!r}"
        )
        assert rejected_revision in result.stderr, (
            f"AC-54: the rejected revision must appear in the error.\n  stderr: {result.stderr!r}"
        )
        assert "error" not in result.stdout.lower(), (
            f"AC-54: errors must not leak to stdout.\n  stdout: {result.stdout!r}"
        )


@pytest.mark.functional
class TestCatalogVersionEnforcementJourney:
    """AC-54 leg 2: catalog metadata <version> enforcement via the real CLI."""

    def test_well_formed_version_accepted(self, tmp_path) -> None:
        """A catalog entry carrying a <version> validates green (no error findings)."""
        repo_root = _make_catalog_repo(tmp_path, _marketplace_xml(_EXACT_TAG, with_version=True))

        result = _run_kanon(_VALIDATE, _METADATA, _REPO_ROOT_FLAG, str(repo_root))

        assert result.returncode == 0, (
            f"AC-54: a well-formed catalog <version> must pass metadata validation.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_missing_version_rejected(self, tmp_path) -> None:
        """A catalog entry whose <version> field is absent exits non-zero with an error."""
        repo_root = _make_catalog_repo(tmp_path, _marketplace_xml(_EXACT_TAG, with_version=False))

        result = _run_kanon(_VALIDATE, _METADATA, _REPO_ROOT_FLAG, str(repo_root))

        assert result.returncode == 1, (
            f"AC-54: a catalog entry missing <version> must be rejected.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert "version" in result.stdout.lower() or "version" in result.stderr.lower(), (
            f"AC-54: the metadata error must name the missing <version> field.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


def _write_kanon(directory, sources):
    """Write a minimal ``.kanon`` declaring the given source triples; return its path."""
    lines = []
    for alias, data in sources.items():
        lines.append(f"KANON_SOURCE_{alias}_URL={data['url']}")
        lines.append(f"KANON_SOURCE_{alias}_REF={data['ref']}")
        lines.append(f"KANON_SOURCE_{alias}_PATH={data['path']}")
        lines.append(f"KANON_SOURCE_{alias}_NAME={alias}")
        lines.append(f"KANON_SOURCE_{alias}_GITBASE={data['url']}")
    path = directory / _KANONENV_FILENAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _source_entry(alias, ref_spec):
    """Return a v4 SourceEntry for the given alias and ref-spec with valid scalar fields."""
    return SourceEntry(
        alias=alias,
        name=alias,
        url=f"https://example.com/{alias}.git",
        ref_spec=ref_spec,
        resolved_ref="refs/tags/example/proj/1.0.0",
        resolved_sha=_VALID_SHA40,
        path=f"repo-specs/{alias}.xml",
    )


def _write_lock(directory, sources):
    """Write a v4 ``.kanon.lock`` carrying the given source entries; return its path."""
    lockfile = Lockfile(
        schema_version=4,
        generated_at="2026-01-01T00:00:00Z",
        generator="kanon-cli/3.0.0",
        kanon_hash=_VALID_KANON_HASH,
        sources=sources,
    )
    path = directory / _LOCK_FILENAME
    write_lockfile(lockfile, path)
    return path


@pytest.mark.functional
class TestLockfileDriftJourney:
    """AC-54 leg 3: kanon validate lockfile flags .kanon <-> .kanon.lock drift."""

    def test_consistent_pair_exits_zero(self, tmp_path) -> None:
        """A consistent .kanon / .kanon.lock pair exits 0."""
        _write_kanon(
            tmp_path,
            {
                _ALPHA: {"url": "https://example.com/alpha.git", "ref": _REF_PINNED, "path": "p1"},
                _BETA: {"url": "https://example.com/beta.git", "ref": _REF_PINNED, "path": "p2"},
            },
        )
        _write_lock(tmp_path, [_source_entry(_ALPHA, _REF_PINNED), _source_entry(_BETA, _REF_PINNED)])

        result = _run_kanon(_VALIDATE, _LOCKFILE, cwd=tmp_path)

        assert result.returncode == 0, (
            f"AC-54: a consistent .kanon/.kanon.lock pair must exit 0.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert "are consistent" in result.stdout

    def test_alias_set_drift_exits_nonzero(self, tmp_path) -> None:
        """A .kanon declaring an alias absent from the lock exits non-zero with a clear message."""
        _write_kanon(
            tmp_path,
            {
                _ALPHA: {"url": "https://example.com/alpha.git", "ref": _REF_PINNED, "path": "p1"},
                _BETA: {"url": "https://example.com/beta.git", "ref": _REF_PINNED, "path": "p2"},
            },
        )

        _write_lock(tmp_path, [_source_entry(_ALPHA, _REF_PINNED)])

        result = _run_kanon(_VALIDATE, _LOCKFILE, cwd=tmp_path)

        assert result.returncode != 0, (
            f"AC-54: alias-set drift must exit non-zero.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _BETA in result.stderr, (
            f"AC-54: the drift message must name the offending alias.\n  stderr: {result.stderr!r}"
        )

    def test_ref_spec_drift_exits_nonzero(self, tmp_path) -> None:
        """A per-alias ref-spec mismatch between .kanon and .kanon.lock exits non-zero."""
        _write_kanon(
            tmp_path,
            {_ALPHA: {"url": "https://example.com/alpha.git", "ref": _REF_PINNED, "path": "p1"}},
        )

        _write_lock(tmp_path, [_source_entry(_ALPHA, _REF_DRIFTED)])

        result = _run_kanon(_VALIDATE, _LOCKFILE, cwd=tmp_path)

        assert result.returncode != 0, (
            f"AC-54: ref-spec drift must exit non-zero.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _ALPHA in result.stderr, (
            f"AC-54: the drift message must name the drifted alias.\n  stderr: {result.stderr!r}"
        )
