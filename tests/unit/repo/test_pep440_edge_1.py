# Copyright (C) 2024 The Android Open Source Project
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

"""Unit tests for PEP 440 edge cases: wildcard-with-range and XML escaping.

Covers:
- AC-TEST-001: wildcard with range (>=1.0.0,<2.0.0,*) resolves correctly.
- AC-TEST-002: XML escape of < (as &lt;) is required and enforced.
- AC-TEST-003: XML escape of & (as &amp;) is required and enforced.
- AC-FUNC-001: XML escaping of < and & in PEP 440 strings is handled correctly.

Spec references:
- PEP440-009: Range constraints -- comma-separated specifiers (>=1.0.0,<2.0.0).
- PEP440-011: XML escape < -- revision attribute &lt;2.0.0 round-trips as <2.0.0.
- PEP440-012: XML escape & -- revision attribute a&amp;b round-trips as a&b.
"""

import io
import xml.dom.minidom

import pytest

from kanon_cli.repo import version_constraints

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_TAG_PREFIX = "refs/tags/project"

_RANGE_TAGS = [
    f"{_TAG_PREFIX}/0.9.0",
    f"{_TAG_PREFIX}/1.0.0",
    f"{_TAG_PREFIX}/1.2.0",
    f"{_TAG_PREFIX}/1.9.9",
    f"{_TAG_PREFIX}/2.0.0",
    f"{_TAG_PREFIX}/3.0.0",
]


# ---------------------------------------------------------------------------
# AC-TEST-001: Wildcard combined with range constraint
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWildcardWithRange:
    """AC-TEST-001: >=1.0.0,<2.0.0,* resolves to the highest version in the range.

    A compound constraint where a wildcard (*) appears alongside range specifiers
    (e.g., >=1.0.0,<2.0.0) should resolve to the highest version that satisfies
    the range. The wildcard is redundant within a range -- it means "any version"
    -- and the range specifiers narrow the candidate set.
    """

    @pytest.mark.parametrize(
        "constraint,available_tags,expected_tag",
        [
            (
                f"{_TAG_PREFIX}/>=1.0.0,<2.0.0,*",
                _RANGE_TAGS,
                f"{_TAG_PREFIX}/1.9.9",
            ),
            (
                f"{_TAG_PREFIX}/>=1.0.0,<2.0.0,*",
                [
                    f"{_TAG_PREFIX}/1.0.0",
                    f"{_TAG_PREFIX}/1.0.1",
                ],
                f"{_TAG_PREFIX}/1.0.1",
            ),
            (
                f"{_TAG_PREFIX}/>=2.0.0,*",
                _RANGE_TAGS,
                f"{_TAG_PREFIX}/3.0.0",
            ),
        ],
        ids=[
            "range-with-wildcard-picks-highest-in-range",
            "range-with-wildcard-single-match",
            "lower-bound-with-wildcard",
        ],
    )
    def test_wildcard_with_range_resolves_to_highest_in_range(self, constraint, available_tags, expected_tag):
        """>=X.Y.Z,<A.B.C,* resolves to the highest version in the range.

        Given: A compound constraint with range specifiers and a trailing wildcard.
        When: resolve_version_constraint() is called.
        Then: Returns the highest version satisfying the range (wildcard is redundant).
        AC: AC-TEST-001.
        """
        result = version_constraints.resolve_version_constraint(constraint, available_tags)
        assert result == expected_tag, (
            f"Range+wildcard constraint '{constraint}' should resolve to '{expected_tag}', got '{result}'"
        )

    def test_wildcard_with_range_is_detected_as_constraint(self):
        """>=1.0.0,<2.0.0,* is recognized as a version constraint.

        Given: A revision string with combined range and wildcard operators.
        When: is_version_constraint() is called.
        Then: Returns True.
        AC: AC-TEST-001 / AC-FUNC-001.
        """
        assert version_constraints.is_version_constraint(f"{_TAG_PREFIX}/>=1.0.0,<2.0.0,*") is True
        assert version_constraints.is_version_constraint(">=1.0.0,<2.0.0,*") is True

    def test_wildcard_with_range_excludes_versions_outside_range(self):
        """>=1.0.0,<2.0.0,* must not return versions below 1.0.0 or at/above 2.0.0.

        Given: Tags include versions below the lower bound and at/above the upper bound.
        When: resolve_version_constraint() is called with >=1.0.0,<2.0.0,*.
        Then: Returns only a version strictly in [1.0.0, 2.0.0).
        AC: AC-TEST-001 / AC-FUNC-001.
        """
        result = version_constraints.resolve_version_constraint(f"{_TAG_PREFIX}/>=1.0.0,<2.0.0,*", _RANGE_TAGS)
        assert result == f"{_TAG_PREFIX}/1.9.9"
        assert result != f"{_TAG_PREFIX}/0.9.0"
        assert result != f"{_TAG_PREFIX}/2.0.0"
        assert result != f"{_TAG_PREFIX}/3.0.0"


# ---------------------------------------------------------------------------
# AC-TEST-002: XML escaping of < (less-than)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestXmlEscapeLessThan:
    """AC-TEST-002: XML must represent < as &lt; in attribute values.

    When a PEP 440 revision string contains the less-than operator (<),
    the XML serialization layer must store it as &lt; so the XML document
    is well-formed. The XML parser must recover the original < when reading
    back the attribute value.

    This behavior is required and enforced: the XML DOM library handles
    escaping automatically during serialization and unescaping during
    parsing, ensuring a lossless round-trip.
    """

    @pytest.mark.parametrize(
        "revision",
        [
            "refs/tags/pkg/<2.0.0",
            "refs/tags/pkg/<1.0.0",
            "refs/tags/project/lib/<3.5.0",
        ],
        ids=[
            "lt-2.0.0",
            "lt-1.0.0",
            "namespaced-lt-3.5.0",
        ],
    )
    def test_less_than_serialized_as_xml_entity_in_attribute(self, revision):
        """< in revision attribute is serialized as &lt; in XML output.

        Given: A revision string containing the < operator.
        When: The value is set as an XML attribute and the document is serialized.
        Then: The serialized XML contains &lt; instead of a raw <.
        AC: AC-TEST-002.
        """
        doc = xml.dom.minidom.Document()
        root = doc.createElement("manifest")
        doc.appendChild(root)
        elem = doc.createElement("project")
        root.appendChild(elem)
        elem.setAttribute("revision", revision)

        buf = io.StringIO()
        doc.writexml(buf)
        serialized = buf.getvalue()

        assert "&lt;" in serialized, (
            f"Serialized XML must contain '&lt;' for revision '{revision}', got: {serialized!r}"
        )
        assert f'revision="{revision}"' not in serialized, (
            f"Raw < must not appear unescaped in attribute value, got: {serialized!r}"
        )

    @pytest.mark.parametrize(
        "xml_attribute_value,expected_revision",
        [
            ("refs/tags/pkg/&lt;2.0.0", "refs/tags/pkg/<2.0.0"),
            ("refs/tags/pkg/&lt;1.0.0", "refs/tags/pkg/<1.0.0"),
            ("refs/tags/ns/lib/&lt;3.5.0", "refs/tags/ns/lib/<3.5.0"),
        ],
        ids=[
            "entity-lt-2.0.0",
            "entity-lt-1.0.0",
            "namespaced-entity-lt-3.5.0",
        ],
    )
    def test_xml_entity_lt_parsed_as_less_than_in_revision(self, xml_attribute_value, expected_revision):
        """&lt; in serialized XML is parsed back as < in the revision attribute.

        Given: An XML document with a revision attribute containing &lt;.
        When: The XML is parsed and the attribute is read.
        Then: The revision value contains < (not &lt;).
        AC: AC-TEST-002.
        """
        xml_str = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<manifest>"
            f'<project name="test" revision="{xml_attribute_value}"/>'
            "</manifest>"
        )
        doc = xml.dom.minidom.parseString(xml_str)
        projects = doc.getElementsByTagName("project")
        assert projects.length == 1
        revision = projects[0].getAttribute("revision")
        assert revision == expected_revision, f"Parsed revision should be '{expected_revision}', got '{revision!r}'"

    def test_less_than_revision_round_trips_through_xml(self):
        """A revision with < survives a full serialize-then-parse round-trip.

        Given: A revision string containing < written to an XML document.
        When: The document is serialized to a string and then parsed back.
        Then: The revision read from the parsed document equals the original value.
        AC: AC-TEST-002 / AC-FUNC-001.
        """
        original_revision = "refs/tags/pkg/<2.0.0"

        doc = xml.dom.minidom.Document()
        root = doc.createElement("manifest")
        doc.appendChild(root)
        elem = doc.createElement("project")
        root.appendChild(elem)
        elem.setAttribute("revision", original_revision)

        buf = io.StringIO()
        doc.writexml(buf)
        serialized = buf.getvalue()

        doc2 = xml.dom.minidom.parseString(serialized)
        projects = doc2.getElementsByTagName("project")
        assert projects.length == 1
        recovered_revision = projects[0].getAttribute("revision")
        assert recovered_revision == original_revision, (
            f"Round-trip failed: expected '{original_revision}', got '{recovered_revision!r}'"
        )

    def test_less_than_operator_detected_after_xml_parse(self):
        """< recovered from XML parsing is recognized as a PEP 440 constraint.

        Given: An XML document stores a revision with &lt; (less-than).
        When: The XML is parsed and the revision is passed to is_version_constraint().
        Then: Returns True (the operator is recognized after XML unescaping).
        AC: AC-TEST-002 / AC-FUNC-001.
        """
        xml_str = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<manifest>"
            '<project name="test" revision="refs/tags/pkg/&lt;2.0.0"/>'
            "</manifest>"
        )
        doc = xml.dom.minidom.parseString(xml_str)
        revision = doc.getElementsByTagName("project")[0].getAttribute("revision")
        assert version_constraints.is_version_constraint(revision) is True, (
            f"Revision '{revision}' recovered from XML must be detected as a version constraint"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: XML escaping of & (ampersand)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestXmlEscapeAmpersand:
    """AC-TEST-003: XML must represent & as &amp; in attribute values.

    When a revision string contains an ampersand (&), the XML serialization
    layer must store it as &amp; so the XML document is well-formed. The XML
    parser must recover the original & when reading back the attribute value.

    This behavior is required and enforced: the XML DOM library handles
    escaping automatically during serialization and unescaping during
    parsing, ensuring a lossless round-trip.
    """

    @pytest.mark.parametrize(
        "revision",
        [
            "refs/tags/pkg/a&b",
            "refs/tags/ns/foo&bar/1.0.0",
            "refs/tags/project/x&y&z",
        ],
        ids=[
            "simple-ampersand",
            "ampersand-in-namespace",
            "multiple-ampersands",
        ],
    )
    def test_ampersand_serialized_as_xml_entity_in_attribute(self, revision):
        """& in revision attribute is serialized as &amp; in XML output.

        Given: A revision string containing the & character.
        When: The value is set as an XML attribute and the document is serialized.
        Then: The serialized XML contains &amp; instead of a raw &.
        AC: AC-TEST-003.
        """
        doc = xml.dom.minidom.Document()
        root = doc.createElement("manifest")
        doc.appendChild(root)
        elem = doc.createElement("project")
        root.appendChild(elem)
        elem.setAttribute("revision", revision)

        buf = io.StringIO()
        doc.writexml(buf)
        serialized = buf.getvalue()

        assert "&amp;" in serialized, (
            f"Serialized XML must contain '&amp;' for revision '{revision}', got: {serialized!r}"
        )
        # A raw & in the attribute position (not followed by amp;) must not appear.
        import re

        raw_amp_pattern = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#)")
        assert not raw_amp_pattern.search(serialized), (
            f"Raw & must not appear unescaped in serialized XML, got: {serialized!r}"
        )

    @pytest.mark.parametrize(
        "xml_attribute_value,expected_revision",
        [
            ("refs/tags/pkg/a&amp;b", "refs/tags/pkg/a&b"),
            ("refs/tags/ns/foo&amp;bar/1.0.0", "refs/tags/ns/foo&bar/1.0.0"),
            ("refs/tags/project/x&amp;y&amp;z", "refs/tags/project/x&y&z"),
        ],
        ids=[
            "entity-amp-simple",
            "entity-amp-in-namespace",
            "entity-amp-multiple",
        ],
    )
    def test_xml_entity_amp_parsed_as_ampersand_in_revision(self, xml_attribute_value, expected_revision):
        """&amp; in serialized XML is parsed back as & in the revision attribute.

        Given: An XML document with a revision attribute containing &amp;.
        When: The XML is parsed and the attribute is read.
        Then: The revision value contains & (not &amp;).
        AC: AC-TEST-003.
        """
        xml_str = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<manifest>"
            f'<project name="test" revision="{xml_attribute_value}"/>'
            "</manifest>"
        )
        doc = xml.dom.minidom.parseString(xml_str)
        projects = doc.getElementsByTagName("project")
        assert projects.length == 1
        revision = projects[0].getAttribute("revision")
        assert revision == expected_revision, f"Parsed revision should be '{expected_revision}', got '{revision!r}'"

    def test_ampersand_revision_round_trips_through_xml(self):
        """A revision with & survives a full serialize-then-parse round-trip.

        Given: A revision string containing & written to an XML document.
        When: The document is serialized to a string and then parsed back.
        Then: The revision read from the parsed document equals the original value.
        AC: AC-TEST-003 / AC-FUNC-001.
        """
        original_revision = "refs/tags/pkg/a&b"

        doc = xml.dom.minidom.Document()
        root = doc.createElement("manifest")
        doc.appendChild(root)
        elem = doc.createElement("project")
        root.appendChild(elem)
        elem.setAttribute("revision", original_revision)

        buf = io.StringIO()
        doc.writexml(buf)
        serialized = buf.getvalue()

        doc2 = xml.dom.minidom.parseString(serialized)
        projects = doc2.getElementsByTagName("project")
        assert projects.length == 1
        recovered_revision = projects[0].getAttribute("revision")
        assert recovered_revision == original_revision, (
            f"Round-trip failed: expected '{original_revision}', got '{recovered_revision!r}'"
        )
