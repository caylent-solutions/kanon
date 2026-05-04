"""Round-trip tests for PEP 440 operators in `<project revision>`.

Verifies that revision values containing XML special characters (`<`, `>`,
`<=`, `>=` and ranges combining them) survive write+read through kanon's
``XmlManifest.Save`` / ``XmlManifest.Load`` path. These constraints are
common when ``revision`` carries a PEP 440 version specifier such as
``refs/tags/<=1.1.0`` (see RX-08, RX-09, RX-12, RX-21, RX-22, RX-25 and
MK-09 in ``docs/integration-testing.md``).

The contract: kanon writes XML via :mod:`xml.dom.minidom`, whose
``setAttribute`` + ``writexml`` automatically escape ``<``/``>``/``&``
in attribute values to ``&lt;``/``&gt;``/``&amp;``. Reading the same
file back through ``minidom.parseString`` (which kanon uses internally)
unescapes them. These tests pin that contract so a future refactor that
introduces manual XML string formatting bypassing minidom would be
caught immediately. Implements AC-FUNC-001 / AC-FUNC-002 / AC-TEST-001
of E2-F3-S1-T7.
"""

from __future__ import annotations

import pathlib
import xml.dom.minidom

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest."""
    repodir = tmp_path / ".repo"
    repodir.mkdir()
    (repodir / "manifests").mkdir()
    manifests_git = repodir / "manifests.git"
    manifests_git.mkdir()
    (manifests_git / "config").write_text(_GIT_CONFIG_TEMPLATE, encoding="utf-8")
    return repodir


def _write_manifest(repodir: pathlib.Path, xml_content: str) -> pathlib.Path:
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    return manifest_file


def _load_manifest(repodir: pathlib.Path, manifest_file: pathlib.Path) -> manifest_xml.XmlManifest:
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


# ---------------------------------------------------------------------------
# Direct minidom round-trip: this is the contract kanon's Save() depends on.
# If a future refactor replaces minidom with custom string formatting and
# forgets to escape, these tests fail.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMinidomEscapesPep440Operators:
    @pytest.mark.parametrize(
        "revision",
        [
            "refs/tags/<=1.1.0",
            "refs/tags/>=1.0.0",
            "refs/tags/<2.0.0",
            "refs/tags/>=1.0.0,<2.0.0",
            "<=1.1.0",
            ">=1.0.0,<2.0.0",
        ],
    )
    def test_round_trip_preserves_revision(self, revision: str) -> None:
        doc = xml.dom.minidom.Document()
        root = doc.createElement("manifest")
        e = doc.createElement("project")
        e.setAttribute("name", "pkg")
        e.setAttribute("revision", revision)
        root.appendChild(e)
        doc.appendChild(root)

        # Serialize the way kanon does in XmlManifest.Save().
        import io

        buf = io.StringIO()
        doc.writexml(buf, "", "  ", "\n", "UTF-8")
        serialized = buf.getvalue()

        # Raw `<` or `>` inside the revision attribute value would make the
        # output ill-formed. Verify the serializer escaped them.
        assert 'revision="' + revision + '"' not in serialized, (
            "Serializer must NOT emit raw < or > inside the revision attribute"
        )

        # Re-parse and confirm the original value comes back.
        parsed = xml.dom.minidom.parseString(serialized)
        proj = parsed.getElementsByTagName("project")[0]
        assert proj.getAttribute("revision") == revision

    def test_ampersand_in_revision_is_escaped(self) -> None:
        """Belt-and-suspenders: confirm `&` is escaped (avoids `&lt;` getting
        accidentally double-decoded if the serializer is ever swapped)."""
        doc = xml.dom.minidom.Document()
        root = doc.createElement("manifest")
        e = doc.createElement("project")
        e.setAttribute("name", "pkg")
        e.setAttribute("revision", "tag&with&ampersand")
        root.appendChild(e)
        doc.appendChild(root)
        import io

        buf = io.StringIO()
        doc.writexml(buf, "", "  ", "\n", "UTF-8")
        serialized = buf.getvalue()
        assert "&amp;" in serialized
        parsed = xml.dom.minidom.parseString(serialized)
        proj = parsed.getElementsByTagName("project")[0]
        assert proj.getAttribute("revision") == "tag&with&ampersand"


# ---------------------------------------------------------------------------
# Manifest file containing escaped PEP 440 entities parses cleanly.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestXmlManifestLoadsEscapedRevision:
    @pytest.mark.parametrize(
        "encoded,decoded",
        [
            ("refs/tags/&lt;=1.1.0", "refs/tags/<=1.1.0"),
            ("refs/tags/&gt;=1.0.0", "refs/tags/>=1.0.0"),
            ("refs/tags/&lt;2.0.0", "refs/tags/<2.0.0"),
            ("refs/tags/&gt;=1.0.0,&lt;2.0.0", "refs/tags/>=1.0.0,<2.0.0"),
        ],
    )
    def test_load_decodes_revision_entities(self, tmp_path: pathlib.Path, encoded: str, decoded: str) -> None:
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://localhost:0" />\n'
            f'  <default revision="{encoded}" remote="origin" />\n'
            '  <project name="pkg" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = _load_manifest(repodir, manifest_file)
        # The default revision should round-trip through entity-decoding.
        assert m.default.revisionExpr == decoded

    def test_raw_unescaped_lt_is_rejected(self, tmp_path: pathlib.Path) -> None:
        """A manifest file with an unescaped `<` in revision is malformed XML
        and must surface as ManifestParseError (or upstream XML error).
        Kanon does NOT silently accept invalid XML."""
        repodir = _make_repo_dir(tmp_path)
        bad_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://localhost:0" />\n'
            '  <default revision="refs/tags/<=1.1.0" remote="origin" />\n'
            '  <project name="pkg" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, bad_xml)
        with pytest.raises(ManifestParseError):
            _load_manifest(repodir, manifest_file)


# ---------------------------------------------------------------------------
# Save() round-trip via the XmlManifest API: write a manifest containing a
# project whose revision carries PEP 440 operators, save it, parse the
# resulting file independently, and verify the revision is preserved.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestXmlManifestSaveRoundTrip:
    @pytest.mark.parametrize(
        "revision",
        [
            "refs/tags/<=1.1.0",
            "refs/tags/>=1.0.0",
            "refs/tags/<2.0.0",
            "refs/tags/>=1.0.0,<2.0.0",
        ],
    )
    def test_save_then_parse_preserves_default_revision(self, tmp_path: pathlib.Path, revision: str) -> None:
        repodir = _make_repo_dir(tmp_path)
        # Build an input manifest that the loader can accept (escape entities
        # so the file is valid XML).
        encoded = revision.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://localhost:0" />\n'
            f'  <default revision="{encoded}" remote="origin" />\n'
            '  <project name="pkg" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = _load_manifest(repodir, manifest_file)
        assert m.default.revisionExpr == revision

        # Save through kanon's XmlManifest.Save and re-parse the output as
        # plain XML; the round-tripped revision must match the original.
        out_path = tmp_path / "saved.xml"
        with out_path.open("w", encoding="utf-8") as fp:
            m.Save(fp)
        saved_text = out_path.read_text(encoding="utf-8")
        # Saved file must use entity escapes, not raw `<`/`>` inside attributes.
        assert f'revision="{revision}"' not in saved_text, (
            "Save() must not emit raw PEP 440 operators inside attribute values"
        )
        parsed = xml.dom.minidom.parseString(saved_text)
        defaults = parsed.getElementsByTagName("default")
        assert len(defaults) == 1
        assert defaults[0].getAttribute("revision") == revision
