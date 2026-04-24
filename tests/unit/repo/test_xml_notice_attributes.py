"""Unit tests for <notice> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <notice> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <notice> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified (no cross-channel
                  leakage)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <notice> element documented attributes:
  The <notice> element has no XML attributes. Its entire content is
  conveyed as text between the opening and closing tags. The text
  content is the only documented "attribute" of this element.

  Text content behavior:
    - Text between tags is the notice message
    - Leading and trailing blank lines are stripped (PEP-257-style)
    - Indentation is normalized using the PEP-257-style algorithm
    - At most one <notice> element is permitted; a duplicate raises
      ManifestParseError with "duplicate notice" in the message
    - An empty <notice></notice> (no child text node) raises
      ManifestParseError because the parser requires a text node

Additional constraints documented in the parser:
  - node.childNodes[0] must exist (requires non-empty tag)
  - The duplicate-notice check runs before text parsing, so a second
    <notice> always raises ManifestParseError
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- mirrors the pattern used in test_xml_notice_happy.py
# ---------------------------------------------------------------------------

_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest.

    Args:
        tmp_path: Pytest tmp_path fixture for isolation.

    Returns:
        The absolute path to the .repo directory.
    """
    repodir = tmp_path / ".repo"
    repodir.mkdir()
    (repodir / "manifests").mkdir()
    manifests_git = repodir / "manifests.git"
    manifests_git.mkdir()
    (manifests_git / "config").write_text(_GIT_CONFIG_TEMPLATE, encoding="utf-8")
    return repodir


def _write_and_load(tmp_path: pathlib.Path, xml_content: str) -> manifest_xml.XmlManifest:
    """Write xml_content as the primary manifest file and load it.

    Args:
        tmp_path: Pytest tmp_path fixture for isolation.
        xml_content: Full XML content for the manifest file.

    Returns:
        A loaded XmlManifest instance.

    Raises:
        ManifestParseError: If the manifest is invalid.
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


def _minimal_manifest_with_notice(notice_text: str) -> str:
    """Build a minimal valid manifest XML with an inline <notice> element.

    Args:
        notice_text: The text content to embed inside the <notice> tags.

    Returns:
        Full XML string for the manifest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f"  <notice>{notice_text}</notice>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )


def _minimal_manifest_without_notice() -> str:
    """Build a minimal valid manifest XML without a <notice> element.

    Returns:
        Full XML string for the manifest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: valid-value tests -- one per documented <notice> content form
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoticeTextContentValidValues:
    """AC-TEST-001: every documented content form of <notice> has a valid-value test.

    Since <notice> has no XML attributes, this class tests the text content --
    the sole documented "attribute" of the element.

    Valid forms:
    - Single-line non-empty text (the minimum valid content)
    - Multi-line text (leading blank lines and trailing blank lines stripped)
    - Text with special characters (punctuation, digits, symbols)
    - Indented multi-line text (indentation is normalized per PEP-257)
    """

    def test_text_content_single_line_parses_without_error(self, tmp_path: pathlib.Path) -> None:
        """A <notice> with a single non-empty line parses without raising an error.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(tmp_path, _minimal_manifest_with_notice("This is a notice."))
        assert manifest.notice is not None, "Expected manifest.notice to be set but got None"
        assert manifest.notice == "This is a notice.", (
            f"Expected notice='This is a notice.' but got: {manifest.notice!r}"
        )

    @pytest.mark.parametrize(
        "notice_text",
        [
            "Simple one-line notice",
            "Notice with numbers: 12345",
            "Notice with special chars @#$%^*()",
            "Notice-with-hyphens and underscores_here",
            "Notice with period at end.",
            "SHORT",
        ],
    )
    def test_text_content_single_line_various_values(
        self,
        tmp_path: pathlib.Path,
        notice_text: str,
    ) -> None:
        """Parameterized: various single-line text values are accepted and stored.

        AC-TEST-001: every documented content form must have a valid-value test.
        Note: raw ampersand is reserved in XML and must not appear unescaped in
        the text node; the parametrize list uses only XML-safe characters.
        """
        manifest = _write_and_load(tmp_path, _minimal_manifest_with_notice(notice_text))
        assert manifest.notice is not None, (
            f"Expected manifest.notice to be non-None for text={notice_text!r} but got None"
        )
        assert manifest.notice == notice_text, f"Expected notice={notice_text!r} but got: {manifest.notice!r}"

    def test_text_content_multiline_parses_without_error(self, tmp_path: pathlib.Path) -> None:
        """A <notice> with multi-line text content parses without raising an error.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice>\n"
            "    First line of notice.\n"
            "    Second line of notice.\n"
            "  </notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)
        assert manifest.notice is not None, "Expected manifest.notice to be set for multi-line content but got None"
        assert "First line of notice." in manifest.notice, (
            f"Expected 'First line of notice.' in manifest.notice but got: {manifest.notice!r}"
        )
        assert "Second line of notice." in manifest.notice, (
            f"Expected 'Second line of notice.' in manifest.notice but got: {manifest.notice!r}"
        )

    def test_text_content_indentation_is_normalized(self, tmp_path: pathlib.Path) -> None:
        """Common leading indentation is stripped from multi-line <notice> text.

        AC-TEST-001, AC-FUNC-001: the PEP-257-style algorithm strips minimum
        indentation from all non-first lines.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice>\n"
            "    Line one.\n"
            "    Line two.\n"
            "  </notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)
        assert manifest.notice is not None, "Expected manifest.notice to be set but got None"
        lines = manifest.notice.splitlines()
        for line in lines:
            assert not line.startswith("    "), (
                f"Expected indentation normalized (4-space indent removed) but got line: {line!r}"
            )

    def test_text_content_leading_trailing_blank_lines_stripped(self, tmp_path: pathlib.Path) -> None:
        """Leading and trailing blank lines in <notice> text content are stripped.

        AC-TEST-001, AC-FUNC-001: blank lines at the start and end are removed
        per the PEP-257-style algorithm.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice>\n"
            "\n"
            "    Content after leading blank line.\n"
            "\n"
            "  </notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)
        assert manifest.notice is not None, "Expected manifest.notice to be set but got None"
        assert not manifest.notice.startswith("\n"), (
            f"Expected no leading newline after parse but got: {manifest.notice!r}"
        )
        assert not manifest.notice.endswith("\n"), (
            f"Expected no trailing newline after parse but got: {manifest.notice!r}"
        )
        assert "Content after leading blank line." in manifest.notice, (
            f"Expected content fragment in manifest.notice but got: {manifest.notice!r}"
        )

    @pytest.mark.parametrize(
        "notice_lines,expected_fragment",
        [
            (["Alpha.", "Beta."], "Alpha."),
            (["First.", "Second.", "Third."], "Second."),
            (["Only line."], "Only line."),
        ],
    )
    def test_text_content_multiline_parametrized(
        self,
        tmp_path: pathlib.Path,
        notice_lines: list,
        expected_fragment: str,
    ) -> None:
        """Parameterized: various multi-line text contents parse and store the expected fragment.

        AC-TEST-001
        """
        indented_body = "\n" + "".join(f"    {line}\n" for line in notice_lines) + "  "
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f"  <notice>{indented_body}</notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)
        assert manifest.notice is not None, (
            f"Expected manifest.notice to be set for lines={notice_lines!r} but got None"
        )
        assert expected_fragment in manifest.notice, (
            f"Expected fragment {expected_fragment!r} in manifest.notice but got: {manifest.notice!r}"
        )

    def test_no_notice_element_gives_none(self, tmp_path: pathlib.Path) -> None:
        """When no <notice> element is present, manifest.notice is None.

        AC-TEST-001, AC-FUNC-001: absence is the documented default.
        """
        manifest = _write_and_load(tmp_path, _minimal_manifest_without_notice())
        assert manifest.notice is None, (
            f"Expected manifest.notice to be None when <notice> absent but got: {manifest.notice!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: invalid-value tests -- invalid content raises ManifestParseError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoticeTextContentInvalidValues:
    """AC-TEST-002: every invalid content form of <notice> raises the appropriate error.

    Invalid cases for <notice>:
    - Duplicate <notice> elements raise ManifestParseError with "duplicate notice"
    - An empty tag <notice></notice> or self-closing <notice /> raises
      ManifestParseError because the parser requires a child text node
    - Whitespace-only content collapses to an empty string (stored as '')

    AC-TEST-002, AC-FUNC-001
    """

    def test_duplicate_notice_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """Two <notice> elements in the same manifest raise ManifestParseError.

        AC-TEST-002, AC-FUNC-001: at most one <notice> element is permitted.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice>First notice.</notice>\n"
            "  <notice>Second notice.</notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, "Expected non-empty ManifestParseError for duplicate <notice> but got empty string"
        assert "duplicate" in error_text.lower(), (
            f"Expected 'duplicate' in error message for duplicate <notice> but got: {error_text!r}"
        )
        assert "notice" in error_text.lower(), (
            f"Expected 'notice' in error message for duplicate <notice> but got: {error_text!r}"
        )

    @pytest.mark.parametrize(
        "first_text,second_text",
        [
            ("First notice.", "Second notice."),
            ("Notice A.", "Notice B."),
            ("Same content.", "Same content."),
        ],
    )
    def test_duplicate_notice_parametrized_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
        first_text: str,
        second_text: str,
    ) -> None:
        """Parameterized: any two <notice> elements regardless of content raise ManifestParseError.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f"  <notice>{first_text}</notice>\n"
            f"  <notice>{second_text}</notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, (
            f"Expected non-empty ManifestParseError for duplicate notice "
            f"({first_text!r}, {second_text!r}) but got empty string"
        )
        assert "duplicate" in error_text.lower(), (
            f"Expected 'duplicate' in error for ({first_text!r}, {second_text!r}) but got: {error_text!r}"
        )

    def test_empty_tag_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """An empty <notice></notice> tag raises ManifestParseError.

        AC-TEST-002, AC-FUNC-001: the parser requires a child text node;
        an empty tag has no childNodes and must raise ManifestParseError
        rather than propagating an unhandled IndexError.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice></notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, "Expected non-empty ManifestParseError for empty <notice> tag but got empty string"

    def test_self_closing_notice_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """A self-closing <notice /> tag raises ManifestParseError.

        AC-TEST-002, AC-FUNC-001: a self-closing tag has no child text node;
        the parser must raise ManifestParseError rather than propagating an
        unhandled IndexError.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice />\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, "Expected non-empty ManifestParseError for self-closing <notice /> but got empty string"

    def test_third_notice_element_also_raises(self, tmp_path: pathlib.Path) -> None:
        """Three <notice> elements raise ManifestParseError (not just two).

        AC-TEST-002: the duplicate check fires on the second occurrence;
        verifying three elements confirms the constraint holds generally.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice>First.</notice>\n"
            "  <notice>Second.</notice>\n"
            "  <notice>Third.</notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert "duplicate" in error_text.lower(), (
            f"Expected 'duplicate' in error for three <notice> elements but got: {error_text!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: content omission -- empty / missing text content behavior
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoticeRequiredContentOmission:
    """AC-TEST-003: the <notice> element has no required XML attributes,
    but its text content is the functional payload.

    This class verifies:
    - When the element is absent, manifest.notice is None (documented default).
    - When the element is present with an empty tag, ManifestParseError is
      raised, because the parser requires a text child node.
    - When the element is present with whitespace-only content, the notice
      is stored as an empty string (the documented whitespace-stripping result).
    - The error message when an empty tag is used mentions "notice" so the
      user can identify which element caused the failure.

    AC-TEST-003, AC-FUNC-001
    """

    def test_absent_notice_element_gives_none_not_error(self, tmp_path: pathlib.Path) -> None:
        """When no <notice> element is present, manifest.notice is None; no error is raised.

        AC-TEST-003: the element is optional; omitting it entirely is valid.
        """
        manifest = _write_and_load(tmp_path, _minimal_manifest_without_notice())
        assert manifest.notice is None, (
            f"Expected manifest.notice=None when element absent but got: {manifest.notice!r}"
        )

    def test_empty_notice_tag_raises_parse_error_naming_notice(self, tmp_path: pathlib.Path) -> None:
        """Empty <notice></notice> raises ManifestParseError with 'notice' in message.

        AC-TEST-003: the error message must identify the failing element so the
        user knows which element to fix.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice></notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert "notice" in error_text.lower(), (
            f"Expected 'notice' in error message for empty tag but got: {error_text!r}"
        )

    def test_self_closing_notice_raises_parse_error_naming_notice(self, tmp_path: pathlib.Path) -> None:
        """Self-closing <notice /> raises ManifestParseError with 'notice' in message.

        AC-TEST-003: the error message must identify the failing element.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice />\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert "notice" in error_text.lower(), (
            f"Expected 'notice' in error message for self-closing tag but got: {error_text!r}"
        )

    def test_whitespace_only_content_results_in_empty_string(self, tmp_path: pathlib.Path) -> None:
        """Whitespace-only text in <notice> is normalized to an empty string by the parser.

        AC-TEST-003: whitespace-only content passes through _ParseNotice and
        results in manifest.notice == '' after blank-line stripping.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice>   \n   </notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)
        assert manifest.notice == "", (
            f"Expected manifest.notice='' for whitespace-only content but got: {manifest.notice!r}"
        )

    @pytest.mark.parametrize(
        "empty_notice_xml",
        [
            "  <notice></notice>\n",
            "  <notice />\n",
        ],
    )
    def test_empty_or_self_closing_notice_parametrized_raises(
        self,
        tmp_path: pathlib.Path,
        empty_notice_xml: str,
    ) -> None:
        """Parameterized: empty and self-closing <notice> tags both raise ManifestParseError.

        AC-TEST-003: both empty forms have no text child node, so the parser
        must raise ManifestParseError for each.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n" + empty_notice_xml + '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, (
            f"Expected non-empty ManifestParseError for empty notice xml={empty_notice_xml!r} but got empty string"
        )
        assert "notice" in error_text.lower(), (
            f"Expected 'notice' in error message for empty tag xml={empty_notice_xml!r} but got: {error_text!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline (parser raises, never prints)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoticeChannelDiscipline:
    """AC-CHANNEL-001: the <notice> parser communicates errors exclusively
    through exceptions, never via stdout.

    For XML/parser tasks, stdout discipline means:
    - Successful parse raises no exception and produces no stdout output
    - Failed parse raises ManifestParseError (not written to stdout)
    """

    def test_valid_notice_raises_no_exception_and_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """A valid <notice> parses without raising an exception and without writing to stdout.

        AC-CHANNEL-001
        """
        manifest = _write_and_load(tmp_path, _minimal_manifest_with_notice("Valid notice text."))
        assert manifest is not None, "Expected XmlManifest instance but got None"

        captured = capsys.readouterr()
        assert captured.out == "", f"Expected no stdout output for valid <notice> parse but got: {captured.out!r}"

    def test_duplicate_notice_raises_not_prints(self, tmp_path: pathlib.Path, capsys) -> None:
        """Duplicate <notice> raises ManifestParseError; stdout remains empty.

        AC-CHANNEL-001: errors surface as exceptions, not as printed output.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice>First.</notice>\n"
            "  <notice>Second.</notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert captured.out == "", (
            f"Expected no stdout output when ManifestParseError is raised but got: {captured.out!r}"
        )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got empty string"

    def test_empty_notice_raises_not_prints(self, tmp_path: pathlib.Path, capsys) -> None:
        """Empty <notice></notice> raises ManifestParseError; stdout remains empty.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice></notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert captured.out == "", f"Expected no stdout output for empty <notice> error but got: {captured.out!r}"
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got empty string"
