"""Unit tests for <notice> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <notice> are validated
               (e.g. remote name resolution -- <notice> has no remote=
               attribute, so no remote-name resolution cross-check is
               performed; <notice> coexists correctly with remote, project,
               default, superproject, and other manifest elements; the notice
               text is stored correctly regardless of the surrounding elements)
  AC-TEST-002  Duplicate-element rules for <notice> surface clear errors
               (two <notice> elements raise ManifestParseError; the error
               message must contain both 'duplicate' and 'notice'; any
               combination of distinct or identical texts raises)
  AC-TEST-003  <notice> in an unexpected parent raises or is ignored per
               spec (a manifest file whose root element is not <manifest>
               raises ManifestParseError before any <notice> child is
               processed; a <notice> sibling to an unknown element inside
               a valid <manifest> root is still parsed normally)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules
               documented for <notice> at parse time (during
               XmlManifest.Load())
  AC-CHANNEL-001  stdout vs stderr discipline is verified (errors raise
                  ManifestParseError, not stdout writes; valid parses produce
                  no output)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of parser
internals.

The cross-element rules for <notice>:
- The element conveys its data as text content between tags. It has no
  XML attributes and therefore no remote= attribute. No remote-name
  resolution cross-check is performed by the parser.
- The element is a singleton: at most one <notice> may appear in a
  manifest. A second <notice> raises ManifestParseError with both
  'duplicate' and 'notice' in the message.
- <notice> is only processed when it appears as a direct child of the
  <manifest> root; if the file root is not <manifest> the file is rejected
  before any child is processed.
- When no <notice> element is present, manifest.notice is None.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- same pattern as other test_xml_notice_*.py files
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
# AC-TEST-001: Cross-element reference validation for <notice>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoticeCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <notice> are validated.

    The <notice> element has no remote= attribute, so no remote-name
    resolution cross-check is required. The cross-element behavior tested
    here is that <notice> coexists correctly with all other manifest
    elements (remotes, defaults, projects, superproject, etc.) and that
    the notice text is stored and retrievable regardless of the surrounding
    elements.

    The absence of a remote cross-reference is itself a property of the spec:
    the notice text is a standalone string and the parser does not validate
    it against any declared element.
    """

    def test_notice_coexists_with_remote_and_default(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<notice> alongside <remote> and <default> parses without error.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>Cross-element coexistence test.</notice>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.notice is not None, (
            "AC-TEST-001: expected notice to be set when sibling to <remote> and <default> but got None"
        )
        assert manifest.notice == "Cross-element coexistence test.", (
            f"AC-TEST-001: expected notice='Cross-element coexistence test.' but got: {manifest.notice!r}"
        )

    def test_notice_text_preserved_when_manifest_has_projects(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<notice> text is preserved correctly when the manifest also declares projects.

        AC-TEST-001, AC-FUNC-001
        """
        notice_text = "Notice displayed alongside project declarations."
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f"  <notice>{notice_text}</notice>\n"
            '  <project name="platform/core" path="core" />\n'
            '  <project name="platform/sdk" path="sdk" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.notice == notice_text, (
            f"AC-TEST-001: expected notice='{notice_text}' with projects present but got: {manifest.notice!r}"
        )
        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"AC-TEST-001: expected 'platform/core' in manifest.projects alongside notice but got: {project_names!r}"
        )
        assert "platform/sdk" in project_names, (
            f"AC-TEST-001: expected 'platform/sdk' in manifest.projects alongside notice but got: {project_names!r}"
        )

    def test_notice_coexists_with_superproject(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<notice> alongside <superproject> parses without error.

        A manifest may declare both a <notice> and a <superproject>.
        Both must be set after loading and each must have the correct value.

        AC-TEST-001, AC-FUNC-001
        """
        notice_text = "Notice alongside superproject."
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f"  <notice>{notice_text}</notice>\n"
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.notice is not None, (
            "AC-TEST-001: expected notice to be set alongside <superproject> but got None"
        )
        assert manifest.notice == notice_text, (
            f"AC-TEST-001: expected notice='{notice_text}' alongside <superproject> but got: {manifest.notice!r}"
        )
        assert manifest.superproject is not None, (
            "AC-TEST-001: expected superproject to be set when <notice> is also present but got None"
        )

    def test_notice_has_no_remote_cross_reference(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<notice> text content bears no relationship to declared remotes and parses correctly.

        The notice text is a standalone string. The parser does not resolve it
        against any declared <remote> element. Text that references remote
        names as plain strings must parse without error.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://vcs.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>See origin remote for fetch details.</notice>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.notice == "See origin remote for fetch details.", (
            f"AC-TEST-001: expected notice text mentioning remote name to be stored verbatim "
            f"without cross-reference validation but got: {manifest.notice!r}"
        )

    def test_notice_absent_when_other_elements_present(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When <notice> is absent, manifest.notice is None even with other elements present.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.notice is None, (
            f"AC-TEST-001: expected manifest.notice to be None when <notice> is absent but got: {manifest.notice!r}"
        )

    @pytest.mark.parametrize(
        "notice_text",
        [
            "Short notice",
            "Notice with numbers: 12345",
            "Notice with special chars @#$%*()",
        ],
    )
    def test_notice_text_preserved_alongside_various_remotes(
        self,
        tmp_path: pathlib.Path,
        notice_text: str,
    ) -> None:
        """Parameterized: notice text is preserved regardless of the declared remotes.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="alpha" fetch="https://alpha.example.com" />\n'
            '  <remote name="beta" fetch="https://beta.example.com" />\n'
            '  <default revision="main" remote="alpha" />\n'
            f"  <notice>{notice_text}</notice>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.notice == notice_text, (
            f"AC-TEST-001: expected notice='{notice_text}' alongside multiple remotes but got: {manifest.notice!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules for <notice>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoticeDuplicateElementRules:
    """AC-TEST-002: Duplicate-element rules for <notice> surface clear errors.

    Unlike elements such as <contactinfo> that support multiple occurrences,
    <notice> is a singleton. A second <notice> element always raises
    ManifestParseError. The error message must contain both 'duplicate'
    and 'notice'.

    Tests here verify:
    - Two <notice> elements with different texts raises ManifestParseError.
    - Two <notice> elements with the same text still raises (no idempotent rule).
    - Three <notice> elements also raise (on the second occurrence).
    - The error message identifies the element: 'duplicate' and 'notice' appear.
    - Any ordering of the duplicate raises the same way.
    """

    def test_two_notice_elements_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <notice> elements in the same manifest raise ManifestParseError.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>First notice text.</notice>\n"
            "  <notice>Second notice text.</notice>\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, (
            "AC-TEST-002: expected non-empty ManifestParseError for duplicate <notice> but got empty string"
        )
        assert "duplicate" in error_text.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error message for duplicate <notice> but got: {error_text!r}"
        )
        assert "notice" in error_text.lower(), (
            f"AC-TEST-002: expected 'notice' in error message for duplicate <notice> but got: {error_text!r}"
        )

    def test_duplicate_notice_raises_not_silently_overwrites(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A second <notice> raises ManifestParseError; it does not silently overwrite the first.

        AC-TEST-002, AC-FUNC-001: <notice> is a singleton, not a last-writer-wins element.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>First notice.</notice>\n"
            "  <notice>Second notice.</notice>\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_identical_duplicate_notice_also_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two identical <notice> elements raise ManifestParseError (no idempotent rule).

        AC-TEST-002: the parser does not permit a second <notice> even when
        the text is identical to the first.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>Same content.</notice>\n"
            "  <notice>Same content.</notice>\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert "duplicate" in error_text.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error for identical <notice> elements but got: {error_text!r}"
        )
        assert "notice" in error_text.lower(), (
            f"AC-TEST-002: expected 'notice' in error for identical <notice> elements but got: {error_text!r}"
        )

    def test_three_notice_elements_raises_on_second(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Three <notice> elements raise ManifestParseError (fires on the second occurrence).

        AC-TEST-002: the duplicate check fires as soon as a second <notice>
        is encountered; a third would never be reached.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>First.</notice>\n"
            "  <notice>Second.</notice>\n"
            "  <notice>Third.</notice>\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert "duplicate" in error_text.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error for three <notice> elements but got: {error_text!r}"
        )
        assert "notice" in error_text.lower(), (
            f"AC-TEST-002: expected 'notice' in error for three <notice> elements but got: {error_text!r}"
        )

    @pytest.mark.parametrize(
        "first_text,second_text",
        [
            ("First notice.", "Second notice."),
            ("Notice A.", "Notice B."),
            ("Same content.", "Same content."),
            ("Short.", "A much longer notice text here."),
        ],
    )
    def test_parameterized_duplicate_notice_raises(
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
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f"  <notice>{first_text}</notice>\n"
            f"  <notice>{second_text}</notice>\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, (
            f"AC-TEST-002: expected non-empty ManifestParseError for duplicate notice "
            f"({first_text!r}, {second_text!r}) but got empty string"
        )
        assert "duplicate" in error_text.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error for ({first_text!r}, {second_text!r}) but got: {error_text!r}"
        )
        assert "notice" in error_text.lower(), (
            f"AC-TEST-002: expected 'notice' in error for ({first_text!r}, {second_text!r}) but got: {error_text!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <notice> in an unexpected parent raises or is ignored per spec
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoticeUnexpectedParent:
    """AC-TEST-003: <notice> in an unexpected parent raises or is ignored per spec.

    The parser processes <notice> only when it appears as a direct child
    of the <manifest> root element. Behaviour when the parent is unexpected:

    - A manifest file whose root element is not <manifest> raises
      ManifestParseError before any children (including <notice>) are
      examined. The error message mentions 'manifest'.
    - An unknown element sibling to <notice> inside a valid <manifest>
      root is silently ignored; <notice> is still processed normally.
    - A valid <manifest> root with <notice> and unknown siblings parses
      correctly and sets manifest.notice.
    """

    def test_notice_in_non_manifest_root_file_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A file whose root element is not <manifest> raises ManifestParseError.

        The parser rejects the file at root-element validation time; the
        <notice> child is never reached.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<repository>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            "  <notice>This notice is under a wrong root.</notice>\n"
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
    def test_notice_under_various_non_manifest_roots_raises(
        self,
        tmp_path: pathlib.Path,
        non_manifest_root: str,
    ) -> None:
        """Parameterized: <notice> under any non-manifest root raises ManifestParseError.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{non_manifest_root}>\n"
            "  <notice>Notice under wrong root.</notice>\n"
            f"</{non_manifest_root}>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-003: expected a non-empty error message when <notice> "
            f"appears under <{non_manifest_root}> but got an empty string"
        )

    def test_unknown_sibling_element_does_not_interfere_with_notice(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An unknown element sibling to <notice> inside <manifest> is ignored.

        Unknown elements inside a valid <manifest> root are silently skipped
        by the parser loop. The <notice> element must still be processed
        and must store the correct text.

        AC-TEST-003, AC-FUNC-001
        """
        notice_text = "Notice with unknown sibling."
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <unknown-element attr="ignored-value" />\n'
            f"  <notice>{notice_text}</notice>\n"
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected unknown sibling element to be silently ignored "
                f"but got ManifestParseError: {exc!r}"
            )

        assert manifest.notice is not None, (
            "AC-TEST-003: expected notice to be set when unknown sibling "
            "element is present alongside <notice> but got None"
        )
        assert manifest.notice == notice_text, (
            f"AC-TEST-003: expected notice='{notice_text}' when unknown sibling is present but got: {manifest.notice!r}"
        )

    def test_notice_valid_in_manifest_root_resolves_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <notice> inside a valid <manifest> root resolves its text correctly.

        This positive test confirms the unexpected-parent logic: when the parent
        IS <manifest>, everything resolves normally.

        AC-TEST-003
        """
        notice_text = "Notice inside proper manifest root."
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f"  <notice>{notice_text}</notice>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.notice is not None, (
            "AC-TEST-003: expected notice to be set for valid <notice> inside proper <manifest> parent but got None"
        )
        assert manifest.notice == notice_text, (
            f"AC-TEST-003: expected notice='{notice_text}' but got: {manifest.notice!r}"
        )

    def test_nested_manifest_root_containing_notice_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <manifest> nested inside a non-manifest root (not at top level) raises.

        The parser searches for <manifest> only as a direct child of the
        document root. A <manifest> nested deeper than that is not found
        and ManifestParseError is raised.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<wrapper>\n"
            "  <manifest>\n"
            '    <remote name="origin" fetch="https://example.com" />\n'
            '    <default revision="main" remote="origin" />\n'
            "    <notice>Notice inside nested manifest.</notice>\n"
            "  </manifest>\n"
            "</wrapper>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert "manifest" in error_message.lower(), (
            f"AC-TEST-003: expected 'manifest' in error for wrapped root containing <notice> but got: {error_message!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parser enforces cross-element and uniqueness rules at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoticeCrossRefParseTimeEnforcement:
    """AC-FUNC-001: All cross-element and uniqueness rules are enforced at parse time.

    Validation must occur during XmlManifest.Load(), not lazily on first use
    of manifest.notice. These tests confirm that errors fire during Load()
    and that the manifest state is consistent after a successful parse.
    """

    def test_duplicate_notice_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A duplicate <notice> raises ManifestParseError during Load(), not on first access.

        ManifestParseError must be raised inside XmlManifest.Load() before any
        caller accesses manifest.notice.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>First notice.</notice>\n"
            "  <notice>Second notice.</notice>\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_notice_fully_resolved_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A valid <notice> is fully resolved by the time Load() returns.

        After Load(), manifest.notice is set to the text from the element.
        No deferred resolution occurs.

        AC-FUNC-001
        """
        notice_text = "Fully resolved notice after load."
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f"  <notice>{notice_text}</notice>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.notice is not None, (
            "AC-FUNC-001: expected notice to be set immediately after Load() but got None"
        )
        assert manifest.notice == notice_text, (
            f"AC-FUNC-001: expected notice='{notice_text}' after Load() but got: {manifest.notice!r}"
        )

    def test_notice_none_after_load_when_absent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <notice> element is present, manifest.notice is None after Load().

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.notice is None, (
            f"AC-FUNC-001: expected manifest.notice to be None after Load() "
            "when no <notice> element is present but got: "
            f"{manifest.notice!r}"
        )

    def test_non_manifest_root_raises_during_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A non-manifest root file with <notice> raises ManifestParseError during Load().

        AC-FUNC-001: validation must happen at parse time in Load().
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<config>\n"
            "  <notice>Notice inside wrong root.</notice>\n"
            "</config>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoticeCrossRefChannelDiscipline:
    """AC-CHANNEL-001: All cross-element errors surface as exceptions, not stdout.

    ManifestParseError must be the sole channel for reporting validation
    failures. No error text must appear on stdout. Successful parses must
    raise no exception and produce no output.
    """

    def test_duplicate_notice_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A duplicate <notice> raises ManifestParseError and produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>First.</notice>\n"
            "  <notice>Second.</notice>\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for duplicate <notice> error but got: {captured.out!r}"
        )

    def test_non_manifest_root_with_notice_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A non-manifest root file with <notice> raises an exception, not stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<config>\n"
            "  <notice>Notice inside wrong root.</notice>\n"
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

    def test_valid_notice_crossref_does_not_raise_or_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A manifest with valid <notice> alongside other elements does not raise or write to stdout.

        AC-CHANNEL-001 (positive case: valid parses must not produce errors or output)
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="partner" fetch="https://partner.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>Valid cross-element notice.</notice>\n"
            '  <project name="platform/core" path="core" />\n'
            '  <project name="platform/sdk" path="sdk" remote="partner" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-CHANNEL-001: expected valid <notice> cross-reference to parse "
                f"without ManifestParseError but got: {exc!r}"
            )

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for valid <notice> cross-element parse but got: {captured.out!r}"
        )
        assert manifest.notice == "Valid cross-element notice.", (
            f"AC-CHANNEL-001: expected notice='Valid cross-element notice.' after valid parse "
            f"but got: {manifest.notice!r}"
        )

    def test_unknown_sibling_of_notice_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Unknown sibling element inside <manifest> with <notice> produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <unknown-element attr="ignored" />\n'
            "  <notice>Notice with unknown sibling.</notice>\n"
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when unknown sibling is ignored alongside <notice> "
            f"but got: {captured.out!r}"
        )
