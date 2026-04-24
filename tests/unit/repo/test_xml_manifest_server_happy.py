"""Unit tests for the <manifest-server> element happy path.

Covers:
  AC-TEST-001  Valid <manifest-server> with minimum required attributes parses
               correctly. The url attribute is the only and required attribute;
               after Load(), manifest.manifest_server equals the url value from
               the XML.
  AC-TEST-002  Valid <manifest-server> with all documented attributes parses
               correctly. Since url is the sole documented attribute, this
               overlaps with AC-TEST-001 and additionally verifies the model
               type and value against a broader set of inputs.
  AC-TEST-003  <manifest-server> with default attribute values behaves per docs.
               The default state (element absent) is manifest_server=None.
               When the element is present, the value is the url string.

  AC-FUNC-001  The happy-path <manifest-server> parses without error and the
               parsed model matches the XML. This is a parser task; the test
               confirms that the model attribute equals what was written to the
               XML file.

  AC-CHANNEL-001  stdout vs stderr discipline for parser tasks: successful
               parses produce no stdout output; errors raise ManifestParseError,
               not stdout writes.

All tests are marked @pytest.mark.unit.
Tests use real manifest files written to tmp_path -- no mocking of parser
internals.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern used in test_xml_superproject_happy.py
# ---------------------------------------------------------------------------

_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest.

    Sets up:
    - <tmp>/.repo/
    - <tmp>/.repo/manifests/    (the include_root / worktree)
    - <tmp>/.repo/manifests.git/config  (remote origin URL for GitConfig)

    Args:
        tmp_path: Pytest tmp_path for isolation.

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


def _write_manifest(repodir: pathlib.Path, xml_content: str) -> pathlib.Path:
    """Write xml_content to the canonical manifest file path and return it.

    Args:
        repodir: The .repo directory.
        xml_content: Full XML content for the manifest file.

    Returns:
        Absolute path to the written manifest file.
    """
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    return manifest_file


def _load_manifest(repodir: pathlib.Path, manifest_file: pathlib.Path) -> manifest_xml.XmlManifest:
    """Instantiate and load an XmlManifest from disk.

    Args:
        repodir: The .repo directory.
        manifest_file: Absolute path to the primary manifest file.

    Returns:
        A loaded XmlManifest instance.
    """
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


def _build_manifest_server_manifest(
    server_url: str,
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
) -> str:
    """Build a manifest XML string that includes a <manifest-server> element.

    Args:
        server_url: The url attribute for the <manifest-server> element.
        remote_name: Name of the remote to declare.
        fetch_url: Fetch URL for the declared remote.
        default_revision: The revision on the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f'  <manifest-server url="{server_url}" />\n'
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid <manifest-server> with minimum required attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerMinimumAttributes:
    """Verify that a <manifest-server> element with the required url attribute parses correctly.

    The url attribute is the only documented attribute on <manifest-server>. The
    minimum valid <manifest-server> requires url. After Load(), manifest.manifest_server
    equals the url value.
    """

    def test_manifest_server_minimum_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with a minimal <manifest-server url="..."> parses without error.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_server_manifest(server_url="https://manifest.example.com/sync")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest is not None, "Expected XmlManifest instance but got None"

    def test_manifest_server_url_equals_xml_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """manifest.manifest_server equals the url attribute value after parsing.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        expected_url = "https://manifest.example.com/sync"
        xml_content = _build_manifest_server_manifest(server_url=expected_url)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server == expected_url, (
            f"AC-TEST-001: expected manifest_server={expected_url!r} but got: {manifest.manifest_server!r}"
        )

    def test_manifest_server_url_stored_verbatim(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The url attribute value is stored verbatim without transformation or normalisation.

        AC-TEST-001: the parser does not normalise, strip trailing slashes, or
        otherwise modify the url value.
        """
        repodir = _make_repo_dir(tmp_path)
        url = "https://sync.internal.corp/manifest/v3/stable/"
        xml_content = _build_manifest_server_manifest(server_url=url)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server == url, (
            f"AC-TEST-001: expected manifest_server={url!r} stored verbatim but got: {manifest.manifest_server!r}"
        )

    def test_manifest_server_url_is_string(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing, manifest.manifest_server is a non-empty string.

        AC-TEST-001: verify the type and non-emptiness of the parsed value.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_server_manifest(server_url="https://manifest.example.com/sync")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert isinstance(manifest.manifest_server, str), (
            f"AC-TEST-001: expected manifest_server to be a str but got: {type(manifest.manifest_server)!r}"
        )
        assert manifest.manifest_server, "AC-TEST-001: expected manifest_server to be non-empty but got empty string"

    def test_manifest_server_does_not_affect_remotes(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing <manifest-server> does not affect the remotes in the manifest model.

        AC-TEST-001, AC-FUNC-001: the manifest-server element is well-scoped;
        it only populates manifest_server and leaves other model fields intact.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_server_manifest(
            server_url="https://manifest.example.com/sync",
            remote_name="origin",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server == "https://manifest.example.com/sync", (
            f"AC-TEST-001: expected manifest_server to be set but got: {manifest.manifest_server!r}"
        )
        remotes = manifest.remotes
        assert "origin" in remotes, (
            f"AC-TEST-001: expected remote 'origin' to remain present after "
            f"parsing <manifest-server> but got remotes: {list(remotes.keys())!r}"
        )

    @pytest.mark.parametrize(
        "server_url",
        [
            "https://manifest-server.example.com/",
            "https://sync.corp.internal/manifest",
            "http://localhost:8080/sync",
            "https://manifest.org/v2/sync/stable",
        ],
    )
    def test_various_url_formats_parse_correctly(
        self,
        tmp_path: pathlib.Path,
        server_url: str,
    ) -> None:
        """Parameterized: various url values are each stored correctly.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_server_manifest(server_url=server_url)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server == server_url, (
            f"AC-TEST-001: expected manifest_server={server_url!r} but got: {manifest.manifest_server!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <manifest-server> with all documented attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerAllDocumentedAttributes:
    """Verify that a <manifest-server> element with all documented attributes parses correctly.

    The <manifest-server> element documents one attribute:
    - url: required, the URL of the manifest server

    Since url is the only documented attribute, these tests verify complete
    coverage of the documented API including type, value, and model consistency.
    """

    def test_manifest_server_url_attribute_is_accessible(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing with url attribute, manifest.manifest_server is accessible.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        url = "https://sync.example.com/api/v1/manifest"
        xml_content = _build_manifest_server_manifest(server_url=url)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server is not None, (
            "AC-TEST-002: expected manifest_server to be non-None after parsing url attribute but got None"
        )
        assert manifest.manifest_server == url, (
            f"AC-TEST-002: expected manifest_server={url!r} but got: {manifest.manifest_server!r}"
        )

    def test_manifest_server_url_with_path_segments_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A url with multiple path segments parses and is stored correctly.

        AC-TEST-002: verify that path segments in the url are preserved.
        """
        repodir = _make_repo_dir(tmp_path)
        url = "https://manifest.example.com/api/v2/sync/stable/latest"
        xml_content = _build_manifest_server_manifest(server_url=url)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server == url, (
            f"AC-TEST-002: expected manifest_server={url!r} with full path segments "
            f"but got: {manifest.manifest_server!r}"
        )

    def test_manifest_server_alongside_projects_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <manifest-server> element alongside <project> elements parses correctly.

        AC-TEST-002, AC-FUNC-001: the manifest-server element is scoped only to
        manifest_server; project parsing is unaffected.
        """
        repodir = _make_repo_dir(tmp_path)
        url = "https://manifest.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <manifest-server url="{url}" />\n'
            '  <project name="tools/example" path="example" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server == url, (
            f"AC-TEST-002: expected manifest_server={url!r} but got: {manifest.manifest_server!r}"
        )
        assert len(manifest.projects) == 1, (
            f"AC-TEST-002: expected exactly 1 project after parsing alongside "
            f"<manifest-server> but got: {len(manifest.projects)}"
        )

    def test_manifest_server_alongside_notice_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <manifest-server> element alongside <notice> parses correctly.

        AC-TEST-002, AC-FUNC-001: both elements are parsed independently; neither
        affects the other.
        """
        repodir = _make_repo_dir(tmp_path)
        url = "https://manifest.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>This manifest is for testing.</notice>\n"
            f'  <manifest-server url="{url}" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server == url, (
            f"AC-TEST-002: expected manifest_server={url!r} alongside notice but got: {manifest.manifest_server!r}"
        )
        assert manifest.notice is not None, (
            "AC-TEST-002: expected manifest.notice to remain set alongside <manifest-server> but got None"
        )

    @pytest.mark.parametrize(
        "server_url",
        [
            "https://manifest-server.corp.example.com/sync",
            "https://alpha.manifest.internal/api/v3/manifest",
            "http://localhost:9090/sync",
            "https://manifest.org/v1/stable",
        ],
    )
    def test_all_documented_attributes_match_model_for_various_urls(
        self,
        tmp_path: pathlib.Path,
        server_url: str,
    ) -> None:
        """Parameterized: the url attribute value matches manifest_server for various inputs.

        AC-TEST-002: exhaustive coverage of the single documented attribute.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_server_manifest(server_url=server_url)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server == server_url, (
            f"AC-TEST-002: expected manifest_server={server_url!r} but got: {manifest.manifest_server!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <manifest-server> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerDefaultAttributeValues:
    """Verify that default attribute values on <manifest-server> behave as documented.

    The <manifest-server> element documents:
    - When the element is absent, manifest.manifest_server is None (the default).
    - When present with url, manifest.manifest_server equals the url value.
    - The element has no optional attributes with fallback values; all behaviour
      is determined solely by the url attribute.
    """

    def test_manifest_server_absent_means_none(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The default state when <manifest-server> is omitted is manifest.manifest_server == None.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server is None, (
            f"AC-TEST-003: expected manifest_server=None when <manifest-server> "
            f"element is absent but got: {manifest.manifest_server!r}"
        )

    def test_manifest_server_present_means_url_not_none(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When <manifest-server> is present, manifest_server is non-None.

        AC-TEST-003: confirms the opt-in nature of the element and its default vs
        explicit-value behaviour.
        """
        repodir = _make_repo_dir(tmp_path)
        url = "https://manifest.example.com/sync"
        xml_content = _build_manifest_server_manifest(server_url=url)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server is not None, (
            "AC-TEST-003: expected manifest_server to be non-None when "
            "<manifest-server> element is present but got None"
        )

    def test_manifest_server_absent_with_projects_still_none(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """manifest_server remains None when <manifest-server> is absent, even with other elements.

        AC-TEST-003: the default value (None) is stable regardless of what other
        elements are present in the manifest.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/example" path="example" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server is None, (
            f"AC-TEST-003: expected manifest_server=None when element is absent "
            f"even with other elements present but got: {manifest.manifest_server!r}"
        )

    def test_manifest_server_absent_does_not_affect_remotes(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The absence of <manifest-server> does not affect other model fields.

        AC-TEST-003: the element's default (None) leaves no side effects on
        other manifest model fields.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server is None, (
            f"AC-TEST-003: expected manifest_server=None but got: {manifest.manifest_server!r}"
        )
        assert "origin" in manifest.remotes, (
            f"AC-TEST-003: expected remote 'origin' to be present when manifest-server "
            f"is absent but got remotes: {list(manifest.remotes.keys())!r}"
        )

    @pytest.mark.parametrize(
        "server_url",
        [
            "https://manifest-server.example.com/",
            "https://sync.corp.internal/manifest",
            "http://localhost:8080/sync",
        ],
    )
    def test_manifest_server_present_url_matches_for_various_values(
        self,
        tmp_path: pathlib.Path,
        server_url: str,
    ) -> None:
        """Parameterized: when present, manifest_server equals the url for various values.

        AC-TEST-003: confirms the transition from default (None) to a specific value
        across a range of url inputs.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_server_manifest(server_url=server_url)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server == server_url, (
            f"AC-TEST-003: expected manifest_server={server_url!r} but got: {manifest.manifest_server!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerHappyChannelDiscipline:
    """AC-CHANNEL-001: successful parses produce no stdout output.

    For XML / parser tasks, stdout discipline means:
    - Successful parses produce no stdout output.
    - The parser signals errors through ManifestParseError, not stdout writes.
    """

    def test_valid_manifest_server_produces_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Parsing a valid <manifest-server> produces no stdout output.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_server_manifest(server_url="https://manifest.example.com/sync")
        manifest_file = _write_manifest(repodir, xml_content)
        _load_manifest(repodir, manifest_file)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for valid manifest-server parse but got: {captured.out!r}"
        )

    def test_absent_manifest_server_produces_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Parsing a manifest without <manifest-server> produces no stdout output.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        _load_manifest(repodir, manifest_file)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when manifest-server element is absent but got: {captured.out!r}"
        )

    def test_missing_url_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Missing url attribute raises ManifestParseError; stdout remains empty.

        AC-CHANNEL-001: error conditions use exceptions, not stdout writes.
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
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when ManifestParseError is raised "
            f"for missing url but got: {captured.out!r}"
        )
        assert str(exc_info.value), (
            "AC-CHANNEL-001: expected a non-empty ManifestParseError message "
            "for missing url attribute but got empty string"
        )
