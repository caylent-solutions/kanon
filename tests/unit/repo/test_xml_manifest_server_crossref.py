"""Unit tests for <manifest-server> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <manifest-server> are validated
               (e.g. remote name resolution -- the url attribute of
               <manifest-server> is independent of any <remote> declaration;
               the stored url is coexistent with all other elements including
               <remote>, <default>, <project>, <notice>, and <superproject>
               without cross-reference interference)
  AC-TEST-002  Duplicate-element rules for <manifest-server> surface clear errors
               (two <manifest-server> elements in the same manifest raise
               ManifestParseError with "duplicate" and "manifest-server" in the
               message)
  AC-TEST-003  <manifest-server> in an unexpected parent raises or is ignored
               per spec (a manifest file whose root element is not <manifest>
               raises ManifestParseError before any <manifest-server> child is
               processed; within a valid <manifest> root an unknown sibling
               element is silently ignored without affecting <manifest-server>)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules
               documented for <manifest-server> at parse time (during
               XmlManifest.Load())
  AC-CHANNEL-001  stdout vs stderr discipline is verified (errors raise
                  ManifestParseError, not stdout writes; valid parses produce
                  no output)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of parser
internals.

The cross-element rules for <manifest-server>:
- The url attribute is stored verbatim; it is not validated against any
  declared <remote> element (no name-resolution cross-reference).
- At most one <manifest-server> element is allowed per manifest; a second
  raises ManifestParseError with "duplicate manifest-server" in the message.
- <manifest-server> is only processed as a child of the <manifest> root;
  if the file root is not <manifest> the file is rejected before any child
  is processed.
- An unknown element sibling to <manifest-server> inside a valid <manifest>
  root is silently ignored; the <manifest-server> element is still processed.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- same pattern as other test_xml_*_crossref.py files
# ---------------------------------------------------------------------------

_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest.

    Args:
        tmp_path: Pytest-provided temporary directory for test isolation.

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
    """Write xml_content to a manifest file and load it.

    Args:
        tmp_path: Pytest-provided temporary directory for test isolation.
        xml_content: Full XML content for the manifest file.

    Returns:
        A loaded XmlManifest instance.
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, xml_content)
    return _load_manifest(repodir, manifest_file)


# ---------------------------------------------------------------------------
# AC-TEST-001: Cross-element reference validation for <manifest-server>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <manifest-server> are validated.

    The <manifest-server> url attribute is stored verbatim and is NOT
    cross-referenced against any declared <remote> element. The url is an
    opaque string pointing at an external server. No remote-resolution
    validation is performed by the parser on this attribute.

    Cross-element concerns tested here:
    - <manifest-server> coexists with <remote> declarations without conflict.
    - <manifest-server> coexists with <project> elements; neither affects the
      other's model field.
    - <manifest-server> coexists with <default> elements; the url is
      independent of the default remote resolution.
    - <manifest-server> coexists with <notice> and <superproject> elements.
    - The url attribute is not validated against declared remote names; a url
      that shares a name with a remote is not treated as a cross-reference.
    """

    def test_manifest_server_url_coexists_with_remote_declarations(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<manifest-server> and <remote> coexist; url does not reference the remote.

        After parsing, manifest_server equals the url value and the remote is
        independently accessible in manifest.remotes. Neither field is modified
        by the presence of the other.

        AC-TEST-001, AC-FUNC-001
        """
        server_url = "https://manifest-server.example.com/sync"
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
            f"AC-TEST-001: expected manifest_server={server_url!r} but got: {manifest.manifest_server!r}"
        )
        assert "origin" in manifest.remotes, (
            "AC-TEST-001: expected 'origin' in manifest.remotes after parsing alongside <manifest-server> but not found"
        )

    def test_manifest_server_url_does_not_reference_remotes(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The url attribute is not cross-referenced against declared remote names.

        A url that superficially matches a remote name is stored verbatim and
        does not affect the remote registry. No ManifestParseError is raised for
        non-existent "remote references" in the url value.

        AC-TEST-001, AC-FUNC-001
        """
        server_url = "https://origin.example.com/manifest-server"
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
            f"AC-TEST-001: expected manifest_server={server_url!r} stored verbatim "
            f"without remote cross-reference but got: {manifest.manifest_server!r}"
        )

    def test_manifest_server_coexists_with_multiple_remotes(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<manifest-server> coexists with multiple <remote> declarations without conflict.

        After parsing, manifest_server is set and both remotes are accessible
        in manifest.remotes. Cross-element isolation is maintained.

        AC-TEST-001, AC-FUNC-001
        """
        server_url = "https://manifest-server.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <manifest-server url="{server_url}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server == server_url, (
            f"AC-TEST-001: expected manifest_server={server_url!r} but got: {manifest.manifest_server!r}"
        )
        assert "origin" in manifest.remotes, (
            "AC-TEST-001: expected 'origin' in manifest.remotes alongside <manifest-server> but not found"
        )
        assert "upstream" in manifest.remotes, (
            "AC-TEST-001: expected 'upstream' in manifest.remotes alongside <manifest-server> but not found"
        )

    def test_manifest_server_coexists_with_project_elements(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<manifest-server> and <project> coexist; neither field is affected by the other.

        After parsing, manifest_server is set and the project list contains
        the expected project. The manifest-server element does not alter project
        parsing, and project elements do not affect manifest_server.

        AC-TEST-001, AC-FUNC-001
        """
        server_url = "https://manifest-server.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <manifest-server url="{server_url}" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server == server_url, (
            f"AC-TEST-001: expected manifest_server={server_url!r} alongside project but got: "
            f"{manifest.manifest_server!r}"
        )
        assert len(manifest.projects) == 1, (
            f"AC-TEST-001: expected 1 project alongside <manifest-server> but got: {len(manifest.projects)}"
        )
        assert manifest.projects[0].name == "platform/core", (
            f"AC-TEST-001: expected project name='platform/core' but got: {manifest.projects[0].name!r}"
        )

    def test_manifest_server_coexists_with_notice_element(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<manifest-server> and <notice> coexist; both fields are set independently.

        Neither the notice nor the manifest_server is affected by the presence
        of the other.

        AC-TEST-001, AC-FUNC-001
        """
        server_url = "https://manifest-server.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>Test notice for cross-element coexistence.</notice>\n"
            f'  <manifest-server url="{server_url}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server == server_url, (
            f"AC-TEST-001: expected manifest_server={server_url!r} alongside notice but got: "
            f"{manifest.manifest_server!r}"
        )
        assert manifest.notice is not None, (
            "AC-TEST-001: expected manifest.notice to be set alongside <manifest-server> but got None"
        )

    def test_manifest_server_coexists_with_superproject_element(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<manifest-server> and <superproject> coexist; both fields are set independently.

        The manifest-server url is not affected by the superproject's remote
        reference, and the superproject is not affected by the manifest-server url.

        AC-TEST-001, AC-FUNC-001
        """
        server_url = "https://manifest-server.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <manifest-server url="{server_url}" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server == server_url, (
            f"AC-TEST-001: expected manifest_server={server_url!r} alongside superproject but got: "
            f"{manifest.manifest_server!r}"
        )
        assert manifest.superproject is not None, (
            "AC-TEST-001: expected superproject to be set alongside <manifest-server> but got None"
        )

    @pytest.mark.parametrize(
        "server_url",
        [
            "https://manifest-server.corp.example.com/sync",
            "https://sync.internal/manifest/v2",
            "http://localhost:8081/sync",
        ],
    )
    def test_various_url_values_coexist_with_remotes_and_projects(
        self,
        tmp_path: pathlib.Path,
        server_url: str,
    ) -> None:
        """Parameterized: various url values coexist with remotes and projects correctly.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <manifest-server url="{server_url}" />\n'
            '  <project name="tools/example" path="example" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server == server_url, (
            f"AC-TEST-001: expected manifest_server={server_url!r} but got: {manifest.manifest_server!r}"
        )
        assert len(manifest.projects) == 1, (
            f"AC-TEST-001: expected 1 project alongside manifest-server url={server_url!r} "
            f"but got: {len(manifest.projects)}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules for <manifest-server> surface clear errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerDuplicateElementRules:
    """AC-TEST-002: Duplicate-element rules for <manifest-server> surface clear errors.

    Only one <manifest-server> element is permitted per manifest. A second
    <manifest-server> element raises ManifestParseError. The error message must
    contain both "duplicate" and "manifest-server". No silent override of the
    first value is allowed.
    """

    def test_two_manifest_server_elements_same_url_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <manifest-server> elements with the same url raise ManifestParseError.

        The error message must contain 'duplicate' and 'manifest-server'.

        AC-TEST-002, AC-FUNC-001
        """
        url = "https://manifest-server.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <manifest-server url="{url}" />\n'
            f'  <manifest-server url="{url}" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error message for repeated "
            f"<manifest-server> but got: {error_message!r}"
        )
        assert "manifest-server" in error_message, (
            f"AC-TEST-002: expected 'manifest-server' in error message but got: {error_message!r}"
        )

    def test_two_manifest_server_elements_different_urls_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <manifest-server> elements with different urls raise ManifestParseError.

        Even when the two elements have distinct url values, only one
        <manifest-server> is allowed. The error message must contain 'duplicate'
        and 'manifest-server'.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://server-a.example.com/sync" />\n'
            '  <manifest-server url="https://server-b.example.com/sync" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error message for two distinct "
            f"<manifest-server> urls but got: {error_message!r}"
        )
        assert "manifest-server" in error_message, (
            f"AC-TEST-002: expected 'manifest-server' in error message but got: {error_message!r}"
        )

    def test_duplicate_manifest_server_error_message_is_non_empty(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The ManifestParseError raised for duplicate <manifest-server> has a non-empty message.

        AC-TEST-002
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
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected a non-empty error message for duplicate <manifest-server> but got an empty string"
        )

    def test_duplicate_does_not_silently_keep_first_or_second_value(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <manifest-server> elements must not silently keep either the first or second url.

        The parser must not silently accept duplicate elements by treating
        the second as an override or ignoring the conflict.

        AC-TEST-002, AC-FUNC-001
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
            "AC-TEST-002: expected ManifestParseError for duplicate <manifest-server> "
            "but the parse completed without error"
        )

    def test_single_manifest_server_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with exactly one <manifest-server> element does not raise.

        This is the positive control: the duplicate rule only fires when a
        second element appears.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://manifest-server.example.com/sync" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-002: expected single <manifest-server> element to parse without "
                f"ManifestParseError but got: {exc!r}"
            )

        assert manifest.manifest_server is not None, (
            "AC-TEST-002: expected manifest_server to be set after single <manifest-server> but got None"
        )

    @pytest.mark.parametrize(
        "url_a,url_b",
        [
            ("https://server-a.example.com/sync", "https://server-b.example.com/sync"),
            ("https://alpha.corp.internal/manifest", "https://beta.corp.internal/manifest"),
            ("http://localhost:8080/sync", "http://localhost:9090/sync"),
        ],
    )
    def test_duplicate_manifest_server_various_url_pairs_raises(
        self,
        tmp_path: pathlib.Path,
        url_a: str,
        url_b: str,
    ) -> None:
        """Parameterized: any pair of distinct urls still triggers the duplicate error.

        AC-TEST-002
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
            f"AC-TEST-002: expected 'duplicate' in error for urls ({url_a!r}, {url_b!r}) but got: {error_message!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <manifest-server> in an unexpected parent raises or is ignored
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerUnexpectedParent:
    """AC-TEST-003: <manifest-server> in an unexpected parent raises or is ignored per spec.

    The parser only processes <manifest-server> when it appears as a direct
    child of the <manifest> root element. Behavior when the parent is unexpected:

    - A manifest file whose root element is not <manifest> raises
      ManifestParseError before any children (including <manifest-server>)
      are examined. The error message mentions 'manifest'.
    - An unknown element sibling to <manifest-server> inside a valid <manifest>
      root is silently ignored; the <manifest-server> element is still processed.
    - A valid <manifest> root with a <manifest-server> and unknown siblings
      parses correctly and sets manifest.manifest_server.
    """

    def test_manifest_server_in_non_manifest_root_file_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A file whose root element is not <manifest> raises ManifestParseError.

        The parser rejects the file at root-element validation time; the
        <manifest-server> child is never reached.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<repository>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://manifest-server.example.com/sync" />\n'
            "</repository>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert "manifest" in error_message.lower(), (
            f"AC-TEST-003: expected 'manifest' in error message for non-manifest root but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "non_manifest_root",
        [
            "repository",
            "config",
            "root",
            "repo",
        ],
    )
    def test_manifest_server_under_various_non_manifest_roots_raises(
        self,
        tmp_path: pathlib.Path,
        non_manifest_root: str,
    ) -> None:
        """Parameterized: <manifest-server> under any non-manifest root raises ManifestParseError.

        The error must be non-empty because the parser rejects the file at
        root-element validation before any <manifest-server> is examined.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{non_manifest_root}>\n"
            '  <manifest-server url="https://manifest-server.example.com/sync" />\n'
            f"</{non_manifest_root}>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-003: expected a non-empty error message when <manifest-server> "
            f"appears under <{non_manifest_root}> but got an empty string"
        )

    def test_unknown_sibling_element_does_not_interfere_with_manifest_server(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An unknown element sibling to <manifest-server> inside <manifest> is silently ignored.

        Unknown elements inside a valid <manifest> root are skipped by the
        parser loop. The <manifest-server> element must still be processed and
        must set manifest.manifest_server after loading.

        AC-TEST-003, AC-FUNC-001
        """
        server_url = "https://manifest-server.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <unknown-element attr="ignored-value" />\n'
            f'  <manifest-server url="{server_url}" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected unknown sibling element to be silently ignored "
                f"but got ManifestParseError: {exc!r}"
            )

        assert manifest.manifest_server == server_url, (
            f"AC-TEST-003: expected manifest_server={server_url!r} when unknown sibling "
            f"element is present alongside <manifest-server> but got: {manifest.manifest_server!r}"
        )

    def test_manifest_server_before_unknown_sibling_still_parsed(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<manifest-server> appearing before an unknown sibling element is still parsed.

        The order of sibling elements does not affect whether <manifest-server>
        is processed. Unknown siblings appearing after <manifest-server> are
        ignored without affecting the already-stored url.

        AC-TEST-003, AC-FUNC-001
        """
        server_url = "https://manifest-server.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <manifest-server url="{server_url}" />\n'
            '  <unknown-element attr="ignored-value" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected unknown sibling after <manifest-server> to be silently "
                f"ignored but got ManifestParseError: {exc!r}"
            )

        assert manifest.manifest_server == server_url, (
            f"AC-TEST-003: expected manifest_server={server_url!r} when unknown element "
            f"follows <manifest-server> but got: {manifest.manifest_server!r}"
        )

    def test_manifest_server_valid_in_manifest_root_resolves_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <manifest-server> inside a valid <manifest> root sets manifest_server correctly.

        This positive test confirms the unexpected-parent logic: when the parent
        IS <manifest>, everything resolves normally.

        AC-TEST-003
        """
        server_url = "https://infra-manifest-server.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="infra" fetch="https://infra.example.com" />\n'
            '  <default revision="refs/heads/main" remote="infra" />\n'
            f'  <manifest-server url="{server_url}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server == server_url, (
            f"AC-TEST-003: expected manifest_server={server_url!r} for valid "
            f"<manifest-server> inside proper <manifest> parent but got: {manifest.manifest_server!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parser enforces cross-element and uniqueness rules at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerCrossRefParseTimeEnforcement:
    """AC-FUNC-001: All cross-element and uniqueness rules are enforced at parse time.

    Validation must occur during XmlManifest.Load(), not lazily on first use
    of manifest.manifest_server. Tests confirm that errors fire during Load()
    and that the manifest state is consistent after a successful parse.
    """

    def test_duplicate_manifest_server_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Duplicate <manifest-server> elements raise during Load(), not on first access.

        The ManifestParseError must be raised inside XmlManifest.Load() before
        any caller accesses manifest.manifest_server.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://server-a.example.com/sync" />\n'
            '  <manifest-server url="https://server-b.example.com/sync" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_non_manifest_root_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A non-manifest root file with <manifest-server> raises during Load().

        The error is raised during XmlManifest.Load() before the caller
        can access any manifest fields.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<config>\n"
            '  <manifest-server url="https://manifest-server.example.com/sync" />\n'
            "</config>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_manifest_server_fully_set_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A valid <manifest-server> is fully resolved by the time Load() returns.

        After Load(), manifest.manifest_server is set to the url attribute
        value. No deferred resolution occurs.

        AC-FUNC-001
        """
        server_url = "https://manifest-server.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="refs/heads/main" remote="origin" />\n'
            f'  <manifest-server url="{server_url}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.manifest_server is not None, (
            "AC-FUNC-001: expected manifest_server to be set immediately after Load() but got None"
        )
        assert manifest.manifest_server == server_url, (
            f"AC-FUNC-001: expected manifest_server={server_url!r} after Load() but got: {manifest.manifest_server!r}"
        )

    def test_manifest_server_absence_sets_none_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <manifest-server> element is present, manifest_server is None after Load().

        The default state (no element) is manifest_server == None immediately
        after Load() returns.

        AC-FUNC-001
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
            f"AC-FUNC-001: expected manifest_server=None when element is absent after Load() "
            f"but got: {manifest.manifest_server!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestServerCrossRefChannelDiscipline:
    """AC-CHANNEL-001: All cross-element errors surface as exceptions, not stdout.

    ManifestParseError must be the sole channel for reporting validation
    failures. No error text must appear on stdout. Successful parses must
    raise no exception and produce no output.
    """

    def test_duplicate_manifest_server_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Duplicate <manifest-server> raises ManifestParseError and produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://server-a.example.com/sync" />\n'
            '  <manifest-server url="https://server-b.example.com/sync" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for duplicate <manifest-server> error but got: {captured.out!r}"
        )

    def test_non_manifest_root_with_manifest_server_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A non-manifest root file with <manifest-server> raises an exception, not stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<config>\n"
            '  <manifest-server url="https://manifest-server.example.com/sync" />\n'
            "</config>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for non-manifest root error but got: {captured.out!r}"
        )

    def test_valid_manifest_server_crossref_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with a valid <manifest-server> parses without error.

        AC-CHANNEL-001 (positive case: valid parses must not produce errors or output)
        """
        server_url = "https://manifest-server.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <manifest-server url="{server_url}" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-CHANNEL-001: expected valid <manifest-server> to parse without ManifestParseError but got: {exc!r}"
            )

        assert manifest.manifest_server == server_url, (
            f"AC-CHANNEL-001: expected manifest_server={server_url!r} after valid parse "
            f"but got: {manifest.manifest_server!r}"
        )

    def test_valid_manifest_server_produces_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Parsing a valid <manifest-server> produces no stdout output.

        AC-CHANNEL-001
        """
        server_url = "https://manifest-server.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <manifest-server url="{server_url}" />\n'
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for valid manifest-server parse but got: {captured.out!r}"
        )

    def test_unknown_sibling_element_with_manifest_server_produces_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Parsing <manifest-server> alongside an unknown sibling element produces no stdout.

        AC-CHANNEL-001: the unknown-sibling case is silently ignored by the
        parser; no error output is produced on stdout.
        """
        server_url = "https://manifest-server.example.com/sync"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <unknown-element attr="ignored-value" />\n'
            f'  <manifest-server url="{server_url}" />\n'
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when unknown sibling element is present "
            f"alongside <manifest-server> but got: {captured.out!r}"
        )
