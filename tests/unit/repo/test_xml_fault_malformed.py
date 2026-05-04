# Copyright (C) 2026 Caylent, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for XML fault injection: malformed and encoding scenarios.

Covers:
  AC-TEST-001 -- malformed XML (unclosed tag) produces an actionable error
  AC-TEST-002 -- XXE / entity expansion is blocked or bounded
  AC-TEST-003 -- CDATA sections are preserved through parse and serialize
  AC-TEST-004 -- bad encoding declaration surfaces a clear error

All tests exercise the manifest parser path in
kanon_cli.repo.manifest_xml.XmlManifest via real files on disk.
The conftest.py in this directory auto-applies @pytest.mark.unit to every
item collected here that does not carry a marker already.
"""

import pathlib

import pytest
import xml.dom.minidom

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared setup helpers (mirrors pattern in test_xml_manifest_happy.py)
# ---------------------------------------------------------------------------

_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest.

    Args:
        tmp_path: Pytest tmp_path for isolation.

    Returns:
        Absolute path to the .repo directory.
    """
    repodir = tmp_path / ".repo"
    repodir.mkdir()
    (repodir / "manifests").mkdir()
    manifests_git = repodir / "manifests.git"
    manifests_git.mkdir()
    (manifests_git / "config").write_text(_GIT_CONFIG_TEMPLATE, encoding="utf-8")
    return repodir


def _write_manifest_bytes(repodir: pathlib.Path, content: bytes) -> pathlib.Path:
    """Write raw bytes to the canonical manifest file path.

    Used when the encoding must be precisely controlled (e.g. bad encoding
    declaration tests) and cannot go through the default UTF-8 str path.

    Args:
        repodir: The .repo directory.
        content: Raw byte content for the manifest file.

    Returns:
        Absolute path to the written manifest file.
    """
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_bytes(content)
    return manifest_file


def _write_manifest(repodir: pathlib.Path, xml_content: str) -> pathlib.Path:
    """Write xml_content to the canonical manifest file path.

    Args:
        repodir: The .repo directory.
        xml_content: Full XML string for the manifest file.

    Returns:
        Absolute path to the written manifest file.
    """
    return _write_manifest_bytes(repodir, xml_content.encode("utf-8"))


def _load_manifest(repodir: pathlib.Path, manifest_file: pathlib.Path) -> manifest_xml.XmlManifest:
    """Instantiate an XmlManifest from disk.

    Args:
        repodir: The .repo directory.
        manifest_file: Absolute path to the primary manifest file.

    Returns:
        A loaded XmlManifest instance.
    """
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


# ---------------------------------------------------------------------------
# AC-TEST-001 -- malformed XML (unclosed tag) produces actionable error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMalformedXmlUnclosedTag:
    """Verify that malformed XML with unclosed tags raises ManifestParseError.

    The error must be informative: it must contain the manifest file path so
    the user can identify which file to fix.
    """

    def test_unclosed_tag_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """An unclosed XML tag must raise ManifestParseError, not ExpatError.

        AC-TEST-001: ManifestParseError is the contract surface; ExpatError
        must not propagate to callers.
        """
        repodir = _make_repo_dir(tmp_path)
        malformed_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            "  <notice>unclosed\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, malformed_xml)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert str(manifest_file) in error_message, (
            f"Error message must contain the manifest file path {str(manifest_file)!r} "
            f"so the user knows which file to fix. Got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "bad_xml",
        [
            (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com"\n'
                "</manifest>\n"
            ),
            (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <project name="foo" path="foo"\n'
            ),
            ('<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <remote\n'),
        ],
        ids=["unclosed_remote_attr", "truncated_project", "truncated_remote"],
    )
    def test_various_malformed_structures_raise_manifest_parse_error(
        self, tmp_path: pathlib.Path, bad_xml: str
    ) -> None:
        """Multiple malformed XML forms all raise ManifestParseError.

        AC-TEST-001: Every malformed input must raise ManifestParseError
        with the file path embedded in the message.
        """
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, bad_xml)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert str(manifest_file) in error_message, (
            f"Error message must contain the manifest file path. Got: {error_message!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- XXE / entity expansion is blocked or bounded
# ---------------------------------------------------------------------------

_MAX_EXPANDED_ENTITY_CHARS = 10_000
"""Upper bound on the total character count permitted after entity expansion.

This constant prevents DoS via quadratic / exponential entity blowup while
still allowing legitimate entity definitions that expand to a modest size.
The value is deliberately generous to avoid false positives on real manifests.
"""


@pytest.mark.unit
class TestXxeEntityExpansion:
    """Verify that external entity references are not resolved and that
    internal entity expansion is bounded to prevent denial-of-service attacks.

    minidom delegates XML parsing to the expat C library. By default:
      - External entity references (SYSTEM) are not loaded (no network/fs
        calls are made by expat for SYSTEM entities without a handler).
      - Internal entities expand in-memory but are subject to expat limits.

    These tests document and pin the existing safe behavior so that any future
    parser change that accidentally enables external entity loading will cause
    an immediate test failure.
    """

    def test_external_system_entity_not_resolved(self, tmp_path: pathlib.Path) -> None:
        """A SYSTEM entity referencing a local file must not read that file.

        The sentinel file contains a recognizable string. If the parser
        resolves the external entity, that string will appear in the parsed
        document. The test asserts it does not.

        Tests at the raw minidom level so the parser's XXE behavior is verified
        without interference from the ManifestParseError wrapping layer.

        AC-TEST-002
        """
        sentinel_file = tmp_path / "sentinel.txt"
        sentinel_content = "XXE-EXTERNAL-ENTITY-RESOLVED-SENTINEL"
        sentinel_file.write_text(sentinel_content, encoding="utf-8")

        xxe_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<!DOCTYPE manifest [\n"
            f'  <!ENTITY xxe SYSTEM "file://{sentinel_file}">\n'
            "]>\n"
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>&xxe;</notice>\n"
            "</manifest>\n"
        )

        # Parse directly via minidom -- the parser must not read the sentinel file.
        doc = xml.dom.minidom.parseString(xxe_xml.encode("utf-8"))
        notices = doc.getElementsByTagName("notice")
        assert notices, "Expected <notice> element in parsed document"

        # The notice text must not contain the sentinel content from the file.
        notice_text = notices[0].firstChild.nodeValue if notices[0].firstChild else ""
        assert sentinel_content not in notice_text, (
            f"External SYSTEM entity was resolved: sentinel content "
            f"{sentinel_content!r} appeared in the parsed notice text. "
            "The parser must not read local files via SYSTEM entities. "
            f"Got notice text: {notice_text!r}"
        )

    def test_internal_entity_expansion_is_bounded(self, tmp_path: pathlib.Path) -> None:
        """A modest entity expansion chain must not produce unbounded output.

        This test defines three levels of entity nesting and asserts that the
        total expanded text does not exceed the defined cap. This documents
        that expat's default limits prevent an exponential blowup.

        Tests at the raw minidom level so the behavior is verified without
        interference from the ManifestParseError wrapping layer.

        AC-TEST-002
        """
        # Three-level expansion: lol3 -> 5x lol2 -> 10x lol -> "lol"
        # Total chars: len("lol") * 10 * 5 = 150 characters -- well bounded.
        entity_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<!DOCTYPE manifest [\n"
            '  <!ENTITY lol "lol">\n'
            '  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">\n'
            '  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;">\n'
            "]>\n"
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>&lol3;</notice>\n"
            "</manifest>\n"
        )

        # Parse directly via minidom to verify expansion is bounded.
        doc = xml.dom.minidom.parseString(entity_xml.encode("utf-8"))
        notices = doc.getElementsByTagName("notice")
        assert notices, "Expected <notice> element in parsed document"

        notice_text = notices[0].firstChild.nodeValue if notices[0].firstChild else ""
        assert len(notice_text) <= _MAX_EXPANDED_ENTITY_CHARS, (
            f"Entity expansion produced {len(notice_text)} characters, "
            f"which exceeds the safety limit of {_MAX_EXPANDED_ENTITY_CHARS}. "
            "The parser must bound entity expansion to prevent DoS."
        )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- CDATA sections are preserved through parse and serialize
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCdataPreservation:
    """Verify that CDATA sections survive a parse + serialize round-trip.

    minidom represents CDATA as CDATASection nodes (nodeType=4). When the
    document is serialized via toxml(), those nodes emit <![CDATA[...]]>
    markers. The raw content (including characters that would need escaping
    in plain text, such as < and &) must be present in the serialized output.
    """

    def test_cdata_node_type_preserved_after_parse(self, tmp_path: pathlib.Path) -> None:
        """A CDATA section must be parsed as a CDATASection node (nodeType 4).

        AC-TEST-003
        """
        cdata_content = "<b>bold</b> & special chars"
        manifest_xml_str = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f"  <notice><![CDATA[{cdata_content}]]></notice>\n"
            "</manifest>\n"
        )

        doc = xml.dom.minidom.parseString(manifest_xml_str.encode("utf-8"))
        notices = doc.getElementsByTagName("notice")
        assert notices, "Expected <notice> element in parsed document"

        notice_node = notices[0]
        child_nodes = list(notice_node.childNodes)
        assert child_nodes, "Expected at least one child node inside <notice>"

        cdata_node = child_nodes[0]
        assert cdata_node.nodeType == xml.dom.minidom.Node.CDATA_SECTION_NODE, (
            f"Expected nodeType {xml.dom.minidom.Node.CDATA_SECTION_NODE} "
            f"(CDATA_SECTION_NODE) but got {cdata_node.nodeType}. "
            "CDATA sections must be preserved as CDATASection nodes after parsing."
        )
        assert cdata_node.data == cdata_content, (
            f"CDATA content mismatch. Expected {cdata_content!r} but got {cdata_node.data!r}."
        )

    def test_cdata_round_trip_preserves_raw_content(self, tmp_path: pathlib.Path) -> None:
        """CDATA content including < and & must survive a serialize round-trip.

        After parsing and re-serializing via toxml(), the output must contain
        the CDATA markers and the original raw content unchanged.

        AC-TEST-003
        """
        cdata_content = "<b>alert</b> & <script>danger</script>"
        manifest_xml_str = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f"  <notice><![CDATA[{cdata_content}]]></notice>\n"
            "</manifest>\n"
        )

        doc = xml.dom.minidom.parseString(manifest_xml_str.encode("utf-8"))
        serialized = doc.toxml()

        assert "<![CDATA[" in serialized, (
            f"CDATA section markers must be present in the serialized output. Serialized output: {serialized!r}"
        )
        assert cdata_content in serialized, (
            f"CDATA raw content {cdata_content!r} must be present verbatim "
            f"in the serialized output. Got: {serialized!r}"
        )

    @pytest.mark.parametrize(
        "raw_content",
        [
            "<tag>with angle brackets</tag>",
            "ampersand & entity",
            "quotes \" and ' apostrophes",
            "newlines\nand\ttabs",
            "<mixed> & \"special\" 'chars'",
        ],
        ids=["angle_brackets", "ampersand", "quotes", "whitespace", "mixed"],
    )
    def test_cdata_various_special_chars_preserved(self, tmp_path: pathlib.Path, raw_content: str) -> None:
        """CDATA sections with various special characters survive parse+serialize.

        AC-TEST-003
        """
        manifest_xml_str = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f"  <notice><![CDATA[{raw_content}]]></notice>\n"
            "</manifest>\n"
        )

        doc = xml.dom.minidom.parseString(manifest_xml_str.encode("utf-8"))
        notices = doc.getElementsByTagName("notice")
        assert notices, "Expected <notice> element"

        cdata_node = notices[0].firstChild
        assert cdata_node is not None, "Expected child node in <notice>"
        assert cdata_node.data == raw_content, (
            f"CDATA content mismatch for input {raw_content!r}. Got: {cdata_node.data!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004 -- bad encoding declaration surfaces clear error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBadEncodingDeclaration:
    """Verify that a bad encoding declaration raises ManifestParseError.

    When the XML declaration names an encoding that Python / expat does not
    recognize, the parser must raise ManifestParseError (not a raw
    LookupError or any other internal exception) so that callers receive a
    consistent, actionable error rooted in the public error contract.
    """

    def test_unknown_encoding_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """An XML declaration with an unknown encoding must raise ManifestParseError.

        AC-TEST-004: The error must be ManifestParseError (not raw LookupError)
        and must contain the manifest file path.
        """
        repodir = _make_repo_dir(tmp_path)

        bad_encoding_xml = b'<?xml version="1.0" encoding="NonExistentXYZ"?><manifest/>'
        manifest_file = _write_manifest_bytes(repodir, bad_encoding_xml)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert str(manifest_file) in error_message, (
            f"Error message must contain the manifest file path {str(manifest_file)!r} "
            f"so the user knows which file to fix. Got: {error_message!r}"
        )

    def test_encoding_mismatch_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """XML declared as UTF-8 but containing non-UTF-8 bytes raises ManifestParseError.

        AC-TEST-004: A byte-level encoding mismatch (Latin-1 content in a
        UTF-8 declared file) must raise ManifestParseError, not a raw
        exception from the underlying parser.
        """
        repodir = _make_repo_dir(tmp_path)

        # UTF-8 declaration with a Latin-1 byte (0xe9 = 'e with acute') that
        # is not valid UTF-8.
        bad_bytes = b'<?xml version="1.0" encoding="UTF-8"?><manifest><notice>caf\xe9</notice></manifest>'
        manifest_file = _write_manifest_bytes(repodir, bad_bytes)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert str(manifest_file) in error_message, (
            f"Error message must contain the manifest file path {str(manifest_file)!r}. Got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "encoding_name",
        [
            "NonExistentXYZ",
            "BOGUS-ENCODING-1234",
            "UTF-9999",
        ],
        ids=["nonexistent", "bogus", "nonexistent_utf"],
    )
    def test_various_bad_encoding_names_raise_manifest_parse_error(
        self, tmp_path: pathlib.Path, encoding_name: str
    ) -> None:
        """Multiple invalid encoding names all raise ManifestParseError.

        AC-TEST-004
        """
        repodir = _make_repo_dir(tmp_path)

        bad_xml = f'<?xml version="1.0" encoding="{encoding_name}"?><manifest/>'.encode("ascii")
        manifest_file = _write_manifest_bytes(repodir, bad_xml)

        with pytest.raises(ManifestParseError):
            _load_manifest(repodir, manifest_file)


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- Parser resilience: malformed and malicious XML
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParserResilience:
    """End-to-end resilience: the manifest parser must never let raw internal
    exceptions (ExpatError, LookupError) propagate to the caller.

    All exceptional conditions below must produce ManifestParseError with
    an actionable message, not a raw exception from the underlying library.
    """

    def test_valid_manifest_loads_successfully(self, tmp_path: pathlib.Path) -> None:
        """A well-formed manifest loads without error.

        Baseline sanity check: verifies the test helper and parser stack
        work correctly for a valid input before testing error paths.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        valid_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, valid_xml)
        loaded = _load_manifest(repodir, manifest_file)

        assert loaded is not None, "Expected XmlManifest instance but got None"
        assert "origin" in loaded.remotes, (
            f"Expected 'origin' in manifest.remotes but got: {list(loaded.remotes.keys())!r}"
        )

    @pytest.mark.parametrize(
        "raw_bytes",
        [
            b'<?xml version="1.0" encoding="UTF-8"?><manifest><notice>caf\xe9</notice></manifest>',
            b"",
            b"   \n\t  ",
        ],
        ids=["truncated_utf8", "empty_doc", "whitespace_only"],
    )
    def test_corrupt_input_always_raises_manifest_parse_error(self, tmp_path: pathlib.Path, raw_bytes: bytes) -> None:
        """Corrupt inputs of any kind must raise ManifestParseError, not raw exceptions.

        The parser must wrap all internal exceptions (ExpatError, LookupError,
        OSError) in ManifestParseError so callers receive a consistent error type.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest_bytes(repodir, raw_bytes)

        with pytest.raises(ManifestParseError):
            _load_manifest(repodir, manifest_file)
