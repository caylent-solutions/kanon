"""Unit tests for <contactinfo> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <contactinfo> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <contactinfo> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified (no cross-channel
                  leakage)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <contactinfo> element documented attributes:
  Required:  bugurl  (URL for the project's bug tracker)

There are no optional attributes. The element may be repeated; later
entries clobber earlier ones. When no <contactinfo> element is present,
manifest.contactinfo.bugurl defaults to Wrapper().BUG_URL.

Error-message contract for required attributes:
  ManifestParseError("no bugurl in <contactinfo> within <manifest_file>")
  The message names the missing attribute: "bugurl".
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError
from kanon_cli.repo.wrapper import Wrapper


# ---------------------------------------------------------------------------
# Shared helpers
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


def _contactinfo_manifest(bugurl: str) -> str:
    """Build a minimal valid manifest XML string with a <contactinfo> element.

    Args:
        bugurl: Value for the required bugurl attribute.

    Returns:
        Full XML string for the manifest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        f'  <contactinfo bugurl="{bugurl}" />\n'
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every documented <contactinfo> attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContactInfoAttributeValidValues:
    """AC-TEST-001: Every documented attribute of <contactinfo> has a valid-value test.

    The only documented attribute is bugurl (required).
    """

    def test_bugurl_https_url_parses_correctly(self, tmp_path: pathlib.Path) -> None:
        """bugurl with an HTTPS URL parses and sets manifest.contactinfo.bugurl.

        AC-TEST-001, AC-FUNC-001
        """
        bugurl = "https://bugs.example.com/issues"
        manifest = _write_and_load(tmp_path, _contactinfo_manifest(bugurl))

        assert manifest.contactinfo is not None, (
            "Expected manifest.contactinfo to be non-None after parsing <contactinfo>"
        )
        assert manifest.contactinfo.bugurl == bugurl, (
            f"Expected contactinfo.bugurl={bugurl!r} but got: {manifest.contactinfo.bugurl!r}"
        )

    @pytest.mark.parametrize(
        "bugurl",
        [
            "https://bugs.example.com/issues",
            "https://github.com/org/repo/issues",
            "https://gitlab.com/group/project/-/issues",
            "https://jira.company.com/browse/PROJ",
            "https://example.com/bugs/project/myproject/component/core",
        ],
    )
    def test_bugurl_various_valid_urls_parsed(self, tmp_path: pathlib.Path, bugurl: str) -> None:
        """Parameterized: various well-formed bugurl values parse and store correctly.

        AC-TEST-001
        """
        manifest = _write_and_load(tmp_path, _contactinfo_manifest(bugurl))

        assert manifest.contactinfo is not None, f"Expected contactinfo to be non-None for bugurl={bugurl!r}"
        assert manifest.contactinfo.bugurl == bugurl, (
            f"Expected contactinfo.bugurl={bugurl!r} but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_bugurl_value_stored_verbatim(self, tmp_path: pathlib.Path) -> None:
        """The bugurl attribute value is stored verbatim without modification.

        AC-TEST-001
        """
        bugurl = "https://example.com/long/path/to/bug-tracker/myproject/core"
        manifest = _write_and_load(tmp_path, _contactinfo_manifest(bugurl))

        assert manifest.contactinfo.bugurl == bugurl, (
            f"Expected contactinfo.bugurl stored verbatim as {bugurl!r} but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_bugurl_attribute_is_string_type(self, tmp_path: pathlib.Path) -> None:
        """After parsing, contactinfo.bugurl is a non-empty str instance.

        AC-TEST-001, AC-FUNC-001
        """
        bugurl = "https://bugs.example.com/report"
        manifest = _write_and_load(tmp_path, _contactinfo_manifest(bugurl))

        assert isinstance(manifest.contactinfo.bugurl, str), (
            f"Expected contactinfo.bugurl to be str but got: {type(manifest.contactinfo.bugurl)!r}"
        )
        assert manifest.contactinfo.bugurl, "Expected contactinfo.bugurl to be non-empty but got an empty string"

    def test_repeated_contactinfo_last_entry_wins(self, tmp_path: pathlib.Path) -> None:
        """When <contactinfo> appears multiple times, the last bugurl is used.

        AC-TEST-001: the repeated-element clobber behavior is documented.
        """
        first_url = "https://first.example.com/bugs"
        second_url = "https://second.example.com/bugs"
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <contactinfo bugurl="{first_url}" />\n'
            f'  <contactinfo bugurl="{second_url}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml)

        assert manifest.contactinfo.bugurl == second_url, (
            f"Expected last <contactinfo> bugurl={second_url!r} to win but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_default_contactinfo_when_element_absent(self, tmp_path: pathlib.Path) -> None:
        """When no <contactinfo> element is present, bugurl defaults to Wrapper().BUG_URL.

        AC-TEST-001: the default-value behavior is part of the attribute surface.
        """
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml)
        expected_default = Wrapper().BUG_URL

        assert manifest.contactinfo is not None, (
            "Expected manifest.contactinfo to be non-None even when element is absent"
        )
        assert manifest.contactinfo.bugurl == expected_default, (
            f"Expected default contactinfo.bugurl={expected_default!r} but got: {manifest.contactinfo.bugurl!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Invalid-value tests -- each raises ManifestParseError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContactInfoAttributeInvalidValues:
    """AC-TEST-002: Invalid attribute values raise ManifestParseError.

    The only documented attribute is bugurl. Invalid cases are:
    - bugurl attribute absent entirely
    - bugurl attribute present but empty string
    """

    def test_bugurl_attribute_absent_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """A <contactinfo> with no bugurl attribute raises ManifestParseError.

        AC-TEST-002, AC-FUNC-001
        """
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <contactinfo />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml)

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"

    def test_bugurl_empty_string_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """A <contactinfo bugurl=""> with an empty string raises ManifestParseError.

        AC-TEST-002: empty string is treated as absent by _reqatt.
        """
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <contactinfo bugurl="" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml)

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"

    @pytest.mark.parametrize(
        "invalid_xml_fragment",
        [
            "  <contactinfo />\n",
            '  <contactinfo bugurl="" />\n',
        ],
    )
    def test_invalid_bugurl_variants_all_raise_manifest_parse_error(
        self, tmp_path: pathlib.Path, invalid_xml_fragment: str
    ) -> None:
        """Parameterized: each form of invalid bugurl raises ManifestParseError.

        AC-TEST-002
        """
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n' + invalid_xml_fragment + "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml)

        assert str(exc_info.value), (
            f"Expected non-empty ManifestParseError for fragment {invalid_xml_fragment!r} but got empty message"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Required attribute omission raises with message naming attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContactInfoRequiredAttributeOmission:
    """AC-TEST-003: Omitting the required bugurl attribute raises with its name in the message.

    The error from _reqatt is:
      "no bugurl in <contactinfo> within <manifest_file>"
    The message must contain the string "bugurl".
    """

    def test_missing_bugurl_raises_manifest_parse_error_naming_bugurl(self, tmp_path: pathlib.Path) -> None:
        """A <contactinfo> with no bugurl raises ManifestParseError with 'bugurl' in message.

        AC-TEST-003
        """
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <contactinfo />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml)

        error_text = str(exc_info.value)
        assert "bugurl" in error_text, (
            f"Expected error message to name the missing attribute 'bugurl' but got: {error_text!r}"
        )

    def test_empty_bugurl_raises_manifest_parse_error_naming_bugurl(self, tmp_path: pathlib.Path) -> None:
        """A <contactinfo bugurl=""> raises ManifestParseError with 'bugurl' in message.

        AC-TEST-003: empty string is treated identically to absent by _reqatt.
        """
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <contactinfo bugurl="" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml)

        error_text = str(exc_info.value)
        assert "bugurl" in error_text, f"Expected error message to name the attribute 'bugurl' but got: {error_text!r}"

    @pytest.mark.parametrize(
        "missing_attr,expected_in_message",
        [
            ("bugurl", "bugurl"),
        ],
    )
    def test_required_attribute_omission_names_attribute_parametrized(
        self,
        tmp_path: pathlib.Path,
        missing_attr: str,
        expected_in_message: str,
    ) -> None:
        """Parameterized: each required attribute omission names that attribute in the error.

        AC-TEST-003
        """
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <contactinfo />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml)

        error_text = str(exc_info.value)
        assert expected_in_message in error_text, (
            f"Expected '{expected_in_message}' in error for missing {missing_attr!r} but got: {error_text!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContactInfoAttributeChannelDiscipline:
    """AC-CHANNEL-001: Parse errors surface as exceptions; no leakage to stdout.

    For parser tasks: errors must be raised as ManifestParseError, not written
    to stdout. Valid parses must not produce any stdout output.
    """

    def test_valid_bugurl_does_not_raise(self, tmp_path: pathlib.Path) -> None:
        """Parsing <contactinfo> with a valid bugurl does not raise ManifestParseError.

        AC-CHANNEL-001
        """
        try:
            _write_and_load(tmp_path, _contactinfo_manifest("https://bugs.example.com/issues"))
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid <contactinfo> to parse without error but got: {exc!r}")

    def test_invalid_bugurl_raises_exception_not_stdout(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Missing bugurl raises ManifestParseError; no output is written to stdout.

        AC-CHANNEL-001
        """
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <contactinfo />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"Expected no stdout output when ManifestParseError is raised but got: {captured.out!r}"
        )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"

    def test_valid_bugurl_produces_no_stdout(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """Parsing a valid <contactinfo bugurl="..."> produces no stdout output.

        AC-CHANNEL-001: success path must not leak to stdout.
        """
        _write_and_load(tmp_path, _contactinfo_manifest("https://bugs.example.com/issues"))

        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout output for valid <contactinfo> parse but got: {captured.out!r}"
