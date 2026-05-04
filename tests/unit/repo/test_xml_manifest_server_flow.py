"""Unit tests for the <manifest-server> element end-to-end parse flow.

Covers:
  AC-TEST-001  <manifest-server url=...> parses and the URL is accessible
               from the model: after Load(), manifest.manifest_server equals
               the url attribute value from the XML element.
  AC-TEST-002  Missing url attribute raises ManifestParseError with a
               message that names the missing attribute and the element.
  AC-TEST-003  Duplicate <manifest-server> raises ManifestParseError with
               a message that identifies the duplication.

  AC-FUNC-001  The manifest-server element is opt-in (absent when element is
               not present, set when element is present) and well-scoped
               (only the url attribute is read; no side effects on other model
               fields).
  AC-CHANNEL-001  stdout vs stderr discipline: successful parses produce no
               stdout output; parse errors raise ManifestParseError, not
               stdout writes.

All tests are marked @pytest.mark.unit.
Tests use real manifest files written to tmp_path -- no mocking of parser
internals.

The flow scenarios covered here complement the attribute, crossref, and
other happy tests for <manifest-server>. Each test class exercises one
end-to-end parse scenario as described in the AC definitions above.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- mirrors the pattern used in test_xml_superproject_flow.py
# ---------------------------------------------------------------------------

_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest.

    Args:
        tmp_path: Pytest tmp_path fixture for test isolation.

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


def _write_and_load(tmp_path: pathlib.Path, xml_content: str) -> manifest_xml.XmlManifest:
    """Write xml_content as the manifest file under a fresh .repo dir and load it.

    Args:
        tmp_path: Pytest tmp_path fixture for test isolation.
        xml_content: Full XML content for the manifest file.

    Returns:
        A loaded XmlManifest instance.
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, xml_content)
    return _load_manifest(repodir, manifest_file)


# ---------------------------------------------------------------------------
# AC-TEST-001: <manifest-server url=...> parses and URL is accessible from model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerUrlParseFlow:
    """AC-TEST-001: <manifest-server url=...> parses and the URL is accessible from the model.

    After calling Load(), manifest.manifest_server equals the url attribute
    value written in the XML. The value is stored verbatim with no
    normalisation. This class exercises the full parse path from XML on disk
    to the Python model property.
    """

    def test_manifest_server_url_is_accessible_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """manifest.manifest_server returns the url value after a successful parse.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://manifest.example.com/sync" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server == "https://manifest.example.com/sync", (
            f"AC-TEST-001: expected manifest_server='https://manifest.example.com/sync' "
            f"but got: {manifest.manifest_server!r}"
        )

    def test_manifest_server_url_stored_verbatim(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The url attribute value is stored verbatim without transformation.

        AC-TEST-001: the parser does not normalise, strip trailing slashes, or
        otherwise modify the url value.
        """
        url = "https://sync.internal.corp/manifest/v3/stable"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <manifest-server url="{url}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server == url, (
            f"AC-TEST-001: expected manifest_server={url!r} stored verbatim but got: {manifest.manifest_server!r}"
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
    def test_various_url_formats_parsed_correctly(
        self,
        tmp_path: pathlib.Path,
        server_url: str,
    ) -> None:
        """Parameterized: various url values are each stored correctly.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <manifest-server url="{server_url}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server == server_url, (
            f"AC-TEST-001: expected manifest_server={server_url!r} for url={server_url!r} "
            f"but got: {manifest.manifest_server!r}"
        )

    def test_manifest_server_does_not_affect_remotes(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing <manifest-server> does not affect the remotes in the manifest model.

        AC-TEST-001, AC-FUNC-001: the manifest-server element is well-scoped;
        it only populates manifest_server and leaves all other model fields
        untouched.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://manifest.example.com/sync" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server == "https://manifest.example.com/sync", (
            f"AC-TEST-001: expected manifest_server to be set but got: {manifest.manifest_server!r}"
        )
        remotes = manifest.remotes
        assert "origin" in remotes, (
            f"AC-TEST-001: expected remote 'origin' to be present after parsing manifest-server "
            f"but got remotes: {list(remotes.keys())!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Missing url attribute raises ManifestParseError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerMissingUrlRaises:
    """AC-TEST-002: Missing url attribute on <manifest-server> raises ManifestParseError.

    The url attribute is required. When it is absent, the parser must fail
    fast with a ManifestParseError whose message names the missing attribute
    and the element. No fallback value is provided.
    """

    def test_missing_url_attribute_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<manifest-server> with no url attribute raises ManifestParseError.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <manifest-server />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_missing_url_error_message_names_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The ManifestParseError message names 'url' when the url attribute is absent.

        AC-TEST-002: the error is actionable -- it tells the user exactly
        which attribute is missing.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <manifest-server />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "url" in error_message, (
            f"AC-TEST-002: expected 'url' in ManifestParseError message for missing "
            f"url attribute but got: {error_message!r}"
        )

    def test_missing_url_error_message_names_element(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The ManifestParseError message names 'manifest-server' when url is absent.

        AC-TEST-002: the error message identifies the element so the user
        knows where in the XML to look.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <manifest-server />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "manifest-server" in error_message, (
            f"AC-TEST-002: expected 'manifest-server' in ManifestParseError message "
            f"for missing url attribute but got: {error_message!r}"
        )

    def test_missing_url_is_not_silently_ignored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When url is absent, the parse does not succeed with manifest_server=None.

        AC-TEST-002: fail-fast discipline -- the absence of a required
        attribute must never result in a successful load with a None value.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
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
            "AC-TEST-002: expected ManifestParseError when url attribute is absent "
            "but the parse completed without error"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Duplicate <manifest-server> raises ManifestParseError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerDuplicateRaises:
    """AC-TEST-003: Duplicate <manifest-server> elements raise ManifestParseError.

    Only one <manifest-server> element is allowed per manifest. When two or
    more are present, the parser must fail fast with a ManifestParseError
    whose message contains 'duplicate' and 'manifest-server'. No silent
    override of the first value is allowed.
    """

    def test_duplicate_manifest_server_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <manifest-server> elements in one manifest raise ManifestParseError.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://server1.example.com/sync" />\n'
            '  <manifest-server url="https://server2.example.com/sync" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_duplicate_manifest_server_error_message_contains_duplicate(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The ManifestParseError message contains 'duplicate' for repeated elements.

        AC-TEST-003: the error is actionable -- it names the cause of failure.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://server1.example.com/sync" />\n'
            '  <manifest-server url="https://server2.example.com/sync" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"AC-TEST-003: expected 'duplicate' in ManifestParseError message for "
            f"repeated <manifest-server> but got: {error_message!r}"
        )

    def test_duplicate_manifest_server_error_message_names_element(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The ManifestParseError message contains 'manifest-server' for repeated elements.

        AC-TEST-003: the error message identifies which element was duplicated.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://server1.example.com/sync" />\n'
            '  <manifest-server url="https://server2.example.com/sync" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "manifest-server" in error_message, (
            f"AC-TEST-003: expected 'manifest-server' in ManifestParseError message for "
            f"repeated <manifest-server> but got: {error_message!r}"
        )

    def test_duplicate_does_not_silently_override_first_value(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <manifest-server> elements must not silently keep the first or second url.

        AC-TEST-003: the parser must not silently accept duplicate elements by
        treating the second as an override or ignoring the conflict.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://first.example.com/sync" />\n'
            '  <manifest-server url="https://second.example.com/sync" />\n'
            "</manifest>\n"
        )
        raised = False
        try:
            _write_and_load(tmp_path, xml_content)
        except ManifestParseError:
            raised = True

        assert raised, (
            "AC-TEST-003: expected ManifestParseError for duplicate <manifest-server> "
            "but the parse completed without error"
        )

    @pytest.mark.parametrize(
        "url_a,url_b",
        [
            ("https://server-a.example.com/sync", "https://server-b.example.com/sync"),
            ("https://alpha.corp.internal/manifest", "https://beta.corp.internal/manifest"),
            ("http://localhost:8080/sync", "http://localhost:9090/sync"),
        ],
    )
    def test_duplicate_manifest_server_various_url_pairs(
        self,
        tmp_path: pathlib.Path,
        url_a: str,
        url_b: str,
    ) -> None:
        """Parameterized: any pair of distinct urls still triggers duplicate error.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <manifest-server url="{url_a}" />\n'
            f'  <manifest-server url="{url_b}" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"AC-TEST-003: expected 'duplicate' in error for urls ({url_a!r}, {url_b!r}) but got: {error_message!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: manifest-server is opt-in and well-scoped
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerOptInAndWellScoped:
    """AC-FUNC-001: manifest-server element is opt-in and well-scoped.

    When the element is absent, manifest.manifest_server is None. When
    present, only manifest_server is populated; no other model fields are
    affected. This verifies the element does not introduce global side effects.
    """

    def test_manifest_server_is_none_when_element_is_absent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """manifest.manifest_server is None when no <manifest-server> element is present.

        AC-FUNC-001: the element is opt-in.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server is None, (
            f"AC-FUNC-001: expected manifest_server=None when <manifest-server> element "
            f"is absent but got: {manifest.manifest_server!r}"
        )

    def test_manifest_server_set_does_not_nullify_notice(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing <manifest-server> alongside <notice> leaves both fields correctly set.

        AC-FUNC-001: manifest-server is well-scoped and does not interfere with
        other optional elements such as <notice>.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>This manifest is for testing.</notice>\n"
            '  <manifest-server url="https://manifest.example.com/sync" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server == "https://manifest.example.com/sync", (
            f"AC-FUNC-001: expected manifest_server to be set but got: {manifest.manifest_server!r}"
        )
        assert manifest.notice is not None, (
            "AC-FUNC-001: expected manifest.notice to remain set alongside manifest-server but got None"
        )

    def test_manifest_server_set_does_not_affect_projects(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <manifest-server> element does not prevent projects from being parsed.

        AC-FUNC-001: manifest-server is scoped only to the manifest_server
        property; project parsing is unaffected.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://manifest.example.com/sync" />\n'
            '  <project name="tools/example" path="example" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server == "https://manifest.example.com/sync", (
            f"AC-FUNC-001: expected manifest_server to be set but got: {manifest.manifest_server!r}"
        )
        assert len(manifest.projects) == 1, (
            f"AC-FUNC-001: expected exactly 1 project after parsing but got: {len(manifest.projects)}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerFlowChannelDiscipline:
    """AC-CHANNEL-001: parse errors raise ManifestParseError; stdout is never written.

    For XML / parser tasks, stdout discipline means:
    - Successful parses produce no stdout output.
    - Failed parses raise ManifestParseError (not writes to stdout).
    """

    def test_url_parse_flow_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Parsing a valid <manifest-server> produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://manifest.example.com/sync" />\n'
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for valid manifest-server parse but got: {captured.out!r}"
        )

    def test_absent_element_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Parsing a manifest without <manifest-server> produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when manifest-server element is absent but got: {captured.out!r}"
        )

    def test_missing_url_raises_not_prints(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Missing url attribute raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001: error flow uses exceptions, not stdout writes.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
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
            "AC-CHANNEL-001: expected a non-empty ManifestParseError message "
            "for missing url attribute but got empty string"
        )

    def test_duplicate_element_raises_not_prints(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Duplicate <manifest-server> raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001: error flow uses exceptions, not stdout writes.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
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
            "AC-CHANNEL-001: expected a non-empty ManifestParseError message "
            "for duplicate <manifest-server> but got empty string"
        )
