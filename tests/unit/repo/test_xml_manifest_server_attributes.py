"""Unit tests for <manifest-server> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <manifest-server> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <manifest-server> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified (no cross-channel
                  leakage)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <manifest-server> element documented attributes:
  Required:  url  (URL of the manifest server; no default)

The url attribute is the only documented attribute. It is required.
When absent, _reqatt raises ManifestParseError with message:
  "no url in <manifest-server> within <manifestFile>"

When the element appears more than once, ManifestParseError is raised
with "duplicate manifest-server" in the message.

Additional constraints:
  - The element is optional at the manifest level; when absent,
    manifest.manifest_server is None.
  - At most one <manifest-server> is allowed per manifest.
  - An empty string for the url attribute is treated as absent and
    raises ManifestParseError (the _reqatt helper treats falsy values
    as missing).
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- mirrors the pattern used in test_xml_superproject_attributes.py
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


def _manifest_with_server(url_attr: str) -> str:
    """Build a manifest XML string with a <manifest-server> element.

    Args:
        url_attr: The value of the url attribute on <manifest-server>.

    Returns:
        Full XML string for the manifest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        f'  <manifest-server url="{url_attr}" />\n'
        "</manifest>\n"
    )


def _manifest_without_server() -> str:
    """Build a minimal manifest XML string with no <manifest-server> element.

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
# AC-TEST-001: valid-value tests -- one per documented <manifest-server> attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerValidValues:
    """AC-TEST-001: every documented attribute of <manifest-server> has a valid-value test.

    The <manifest-server> element has one documented attribute:
    - url (required): URL string of the manifest server.

    Each test exercises a legal url value and asserts that the parsed
    manifest.manifest_server equals that url value.
    """

    def test_url_attribute_valid_https_stores_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A standard HTTPS url attribute value is accepted and stored verbatim.

        AC-TEST-001, AC-FUNC-001
        """
        url = "https://manifest.example.com/sync"
        manifest = _write_and_load(tmp_path, _manifest_with_server(url))

        assert manifest.manifest_server == url, (
            f"AC-TEST-001: expected manifest_server={url!r} but got: {manifest.manifest_server!r}"
        )

    def test_url_attribute_valid_http_stores_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An HTTP url attribute value (non-TLS scheme) is accepted and stored verbatim.

        AC-TEST-001: the parser does not validate the scheme; any non-empty
        url string is accepted.
        """
        url = "http://manifest.internal.example.com/sync"
        manifest = _write_and_load(tmp_path, _manifest_with_server(url))

        assert manifest.manifest_server == url, (
            f"AC-TEST-001: expected manifest_server={url!r} but got: {manifest.manifest_server!r}"
        )

    def test_url_attribute_with_port_stores_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A url attribute that includes a port number is accepted and stored verbatim.

        AC-TEST-001: path components, ports, and query strings are not
        modified by the parser.
        """
        url = "http://localhost:8080/sync"
        manifest = _write_and_load(tmp_path, _manifest_with_server(url))

        assert manifest.manifest_server == url, (
            f"AC-TEST-001: expected manifest_server={url!r} but got: {manifest.manifest_server!r}"
        )

    def test_url_attribute_with_path_segments_stores_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A url attribute with multiple path segments is accepted and stored verbatim.

        AC-TEST-001: the parser stores the url exactly as written with no
        path normalisation.
        """
        url = "https://manifest.example.com/api/v2/sync/stable"
        manifest = _write_and_load(tmp_path, _manifest_with_server(url))

        assert manifest.manifest_server == url, (
            f"AC-TEST-001: expected manifest_server={url!r} but got: {manifest.manifest_server!r}"
        )

    def test_url_attribute_with_trailing_slash_stores_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A url attribute with a trailing slash is stored verbatim without stripping.

        AC-TEST-001: the parser does not normalise the url (no trailing-slash
        removal, no lowercase conversion, no escaping).
        """
        url = "https://manifest.example.com/sync/"
        manifest = _write_and_load(tmp_path, _manifest_with_server(url))

        assert manifest.manifest_server == url, (
            f"AC-TEST-001: expected manifest_server={url!r} with trailing slash verbatim "
            f"but got: {manifest.manifest_server!r}"
        )

    def test_url_attribute_is_string_type(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After a valid parse, manifest.manifest_server is a str instance.

        AC-TEST-001, AC-FUNC-001: verifies the model type of the parsed value.
        """
        url = "https://manifest.example.com/sync"
        manifest = _write_and_load(tmp_path, _manifest_with_server(url))

        assert isinstance(manifest.manifest_server, str), (
            f"AC-TEST-001: expected manifest_server to be str but got type {type(manifest.manifest_server)!r}"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://manifest-server.example.com/",
            "https://sync.corp.internal/manifest",
            "http://localhost:8080/sync",
            "https://manifest.org/v2/sync/stable",
            "https://sync.internal.corp/manifest/v3/stable/",
        ],
    )
    def test_url_attribute_various_valid_values(
        self,
        tmp_path: pathlib.Path,
        url: str,
    ) -> None:
        """Parameterized: various valid url values are all accepted and stored correctly.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(tmp_path, _manifest_with_server(url))

        assert manifest.manifest_server == url, (
            f"AC-TEST-001: expected manifest_server={url!r} but got: {manifest.manifest_server!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: invalid-value tests -- one per documented <manifest-server> attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerInvalidValues:
    """AC-TEST-002: every documented attribute has invalid-value tests.

    The url attribute is the only documented attribute on <manifest-server>.
    Invalid values are those treated as falsy by _reqatt (empty string).
    The _reqatt helper raises ManifestParseError for any falsy attribute
    value, treating it as absent.

    Additional invalid cases:
    - The element appearing more than once raises ManifestParseError.
    """

    def test_url_attribute_empty_string_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An empty string url attribute raises ManifestParseError.

        AC-TEST-002: the _reqatt helper treats an empty string as absent
        (falsy), so it raises ManifestParseError -- the same error as
        when the attribute is completely missing.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_url_attribute_empty_string_error_names_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The error message for an empty url attribute names 'url'.

        AC-TEST-002: the error message must be actionable -- it names the
        invalid attribute so the user knows what to fix.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "url" in error_message, (
            f"AC-TEST-002: expected 'url' in error message for empty url attribute but got: {error_message!r}"
        )

    def test_url_attribute_empty_string_error_names_element(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The error message for an empty url attribute names 'manifest-server'.

        AC-TEST-002: the error message identifies the element so the user
        knows where in the manifest to look.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "manifest-server" in error_message, (
            f"AC-TEST-002: expected 'manifest-server' in error message for empty url but got: {error_message!r}"
        )

    def test_duplicate_manifest_server_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <manifest-server> elements in one manifest raise ManifestParseError.

        AC-TEST-002: at most one <manifest-server> element is allowed;
        a duplicate is an invalid manifest structure.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://server1.example.com/sync" />\n'
            '  <manifest-server url="https://server2.example.com/sync" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_duplicate_manifest_server_error_names_element(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The error for a duplicate <manifest-server> names 'manifest-server'.

        AC-TEST-002: the error message identifies the duplicated element.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://server1.example.com/sync" />\n'
            '  <manifest-server url="https://server2.example.com/sync" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "manifest-server" in error_message, (
            f"AC-TEST-002: expected 'manifest-server' in error for duplicate element but got: {error_message!r}"
        )

    def test_duplicate_manifest_server_error_contains_duplicate(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The error for a duplicate <manifest-server> contains 'duplicate'.

        AC-TEST-002: the error message identifies the cause of failure
        so the user knows the element appeared more than once.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://server1.example.com/sync" />\n'
            '  <manifest-server url="https://server2.example.com/sync" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error for duplicate <manifest-server> but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "url_a,url_b",
        [
            ("https://server-a.example.com/sync", "https://server-b.example.com/sync"),
            ("https://alpha.corp.internal/manifest", "https://beta.corp.internal/manifest"),
            ("http://localhost:8080/sync", "http://localhost:9090/sync"),
        ],
    )
    def test_duplicate_manifest_server_any_url_pair_raises(
        self,
        tmp_path: pathlib.Path,
        url_a: str,
        url_b: str,
    ) -> None:
        """Parameterized: any pair of distinct url values still triggers duplicate error.

        AC-TEST-002: duplication is detected regardless of which url values
        are used on the two elements.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <manifest-server url="{url_a}" />\n'
            f'  <manifest-server url="{url_b}" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error for url pair ({url_a!r}, {url_b!r}) but got: {error_message!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Required attribute omission raises with message naming the attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerRequiredAttributeOmission:
    """AC-TEST-003: omitting a required attribute raises ManifestParseError naming it.

    The url attribute is the only required attribute on <manifest-server>.
    When it is absent (or empty), _reqatt raises ManifestParseError with
    a message that names both the attribute and the element. The error must
    be actionable -- it tells the user exactly what to fix.
    """

    def test_url_omitted_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Omitting url entirely raises ManifestParseError.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <manifest-server />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_url_omitted_error_message_names_url(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """ManifestParseError for missing url names 'url' in the message.

        AC-TEST-003: the message must name the missing attribute so the
        user can identify what needs to be added to the manifest.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <manifest-server />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "url" in error_message, (
            f"AC-TEST-003: expected 'url' in ManifestParseError message for missing "
            f"url attribute but got: {error_message!r}"
        )

    def test_url_omitted_error_message_names_manifest_server(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """ManifestParseError for missing url names 'manifest-server' in the message.

        AC-TEST-003: the message must name the element so the user knows
        which XML element to look for the missing attribute.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <manifest-server />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "manifest-server" in error_message, (
            f"AC-TEST-003: expected 'manifest-server' in ManifestParseError message for "
            f"missing url attribute but got: {error_message!r}"
        )

    def test_url_omitted_parse_does_not_succeed_with_none(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Omitting url does not allow parsing to succeed with manifest_server=None.

        AC-TEST-003: fail-fast discipline -- an explicit <manifest-server>
        element without url must not silently degrade to manifest_server=None.
        The presence of the element without the required attribute must be
        an error, not a no-op.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <manifest-server />\n"
            "</manifest>\n"
        )
        raised = False
        try:
            _write_and_load(tmp_path, xml_content)
        except ManifestParseError:
            raised = True

        assert raised, (
            "AC-TEST-003: expected ManifestParseError when url attribute is absent "
            "but the parse completed without error"
        )

    def test_url_empty_string_treated_as_omitted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An empty string url value is treated as omitted by _reqatt and raises.

        AC-TEST-003: the _reqatt helper raises ManifestParseError for any
        falsy attribute value; an empty string is not a valid url.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "url" in error_message, (
            f"AC-TEST-003: expected 'url' in ManifestParseError for empty url string but got: {error_message!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: every documented attribute validated at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerAttributeValidatedAtParseTime:
    """AC-FUNC-001: every documented attribute is validated at parse time (on Load()).

    The url attribute is the only documented attribute. Validation happens
    eagerly during Load(), not lazily on first access.
    """

    def test_url_validation_happens_during_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """ManifestParseError is raised during Load(), not deferred to property access.

        AC-FUNC-001: the url attribute is validated eagerly. Callers should
        not need to access manifest_server to discover a parse error.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <manifest-server />\n"
            "</manifest>\n"
        )
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_url_attribute_accessible_immediately_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After Load() completes, manifest.manifest_server is immediately accessible.

        AC-FUNC-001: the url attribute is fully parsed during Load(); no lazy
        initialization is required to access the value after parsing.
        """
        url = "https://manifest.example.com/sync"
        manifest = _write_and_load(tmp_path, _manifest_with_server(url))

        assert manifest.manifest_server == url, (
            f"AC-FUNC-001: expected manifest_server={url!r} immediately after Load() "
            f"but got: {manifest.manifest_server!r}"
        )

    def test_url_attribute_survives_alongside_other_elements(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The url attribute is parsed correctly even when other optional elements are present.

        AC-FUNC-001: url validation is scoped to the <manifest-server> element
        and does not interact with parsing of other elements.
        """
        url = "https://manifest.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>A test notice.</notice>\n"
            f'  <manifest-server url="{url}" />\n'
            '  <project name="tools/example" path="example" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server == url, (
            f"AC-FUNC-001: expected manifest_server={url!r} alongside other elements "
            f"but got: {manifest.manifest_server!r}"
        )
        assert manifest.notice is not None, (
            "AC-FUNC-001: expected notice to remain set after parsing manifest-server but got None"
        )
        assert len(manifest.projects) == 1, (
            f"AC-FUNC-001: expected 1 project after parsing but got: {len(manifest.projects)}"
        )

    def test_absent_element_means_url_attribute_is_not_required(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When the <manifest-server> element is absent, url is not required.

        AC-FUNC-001: the url attribute is only required when the element
        is present. Its absence leaves manifest.manifest_server as None.
        """
        manifest = _write_and_load(tmp_path, _manifest_without_server())

        assert manifest.manifest_server is None, (
            f"AC-FUNC-001: expected manifest_server=None when element absent but got: {manifest.manifest_server!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerAttributeChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr discipline for attribute validation paths.

    For XML / parser tasks:
    - Successful parses produce no stdout output.
    - Parse errors raise ManifestParseError (not writes to stdout).
    - No cross-channel leakage: attribute errors do not write to stdout.
    """

    def test_valid_url_attribute_produces_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Parsing a valid url attribute produces no stdout output.

        AC-CHANNEL-001
        """
        _write_and_load(tmp_path, _manifest_with_server("https://manifest.example.com/sync"))

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for valid url attribute parse but got: {captured.out!r}"
        )

    def test_missing_url_attribute_raises_not_prints_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Missing url attribute raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001: error conditions use exceptions, not stdout writes.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <manifest-server />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when ManifestParseError is raised "
            f"for missing url attribute but got: {captured.out!r}"
        )
        assert str(exc_info.value), (
            "AC-CHANNEL-001: expected non-empty ManifestParseError message for missing "
            "url attribute but got empty string"
        )

    def test_empty_url_attribute_raises_not_prints_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """An empty url attribute raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001: the error path for an invalid attribute value uses
        exceptions, not stdout writes.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when ManifestParseError is raised "
            f"for empty url attribute but got: {captured.out!r}"
        )
        assert str(exc_info.value), (
            "AC-CHANNEL-001: expected non-empty ManifestParseError message for empty url attribute but got empty string"
        )

    def test_duplicate_manifest_server_raises_not_prints_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A duplicate <manifest-server> raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001: all attribute-level error paths use exceptions, not
        stdout writes.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://server1.example.com/sync" />\n'
            '  <manifest-server url="https://server2.example.com/sync" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when ManifestParseError is raised "
            f"for duplicate <manifest-server> but got: {captured.out!r}"
        )
        assert str(exc_info.value), (
            "AC-CHANNEL-001: expected non-empty ManifestParseError message for duplicate "
            "<manifest-server> but got empty string"
        )

    def test_absent_manifest_server_produces_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Parsing a manifest without <manifest-server> produces no stdout output.

        AC-CHANNEL-001
        """
        _write_and_load(tmp_path, _manifest_without_server())

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when manifest-server element is absent but got: {captured.out!r}"
        )
