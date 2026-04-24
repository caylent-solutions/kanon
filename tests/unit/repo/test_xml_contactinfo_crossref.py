"""Unit tests for <contactinfo> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <contactinfo> are validated
               (e.g. <contactinfo> coexists correctly with remote, project,
               default, superproject, and other manifest elements; the bugurl
               is stored correctly regardless of what other elements surround
               it; no remote-name resolution is performed for <contactinfo>
               because the element has no remote= attribute)
  AC-TEST-002  Duplicate-element rules for <contactinfo> surface clear errors
               (two <contactinfo> elements do NOT raise -- later entries clobber
               earlier ones; the last bugurl wins; this is the documented
               behaviour, distinct from singleton elements that raise on duplicate)
  AC-TEST-003  <contactinfo> in an unexpected parent raises or is ignored per
               spec (a manifest file whose root element is not <manifest>
               raises ManifestParseError before any <contactinfo> child is
               processed; a <contactinfo> sibling to an unknown element inside
               a valid <manifest> root is still parsed normally)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules
               documented for <contactinfo> at parse time (during
               XmlManifest.Load())
  AC-CHANNEL-001  stdout vs stderr discipline is verified (errors raise
                  ManifestParseError, not stdout writes; valid parses produce
                  no output)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of parser
internals.

The cross-element rules for <contactinfo>:
- The element has a single required attribute: bugurl. There is no remote=
  attribute, so no remote-name resolution cross-check is performed.
- The element may appear multiple times; later entries clobber earlier ones.
  This is explicitly documented and does NOT raise ManifestParseError.
- <contactinfo> is only processed when it appears as a direct child of the
  <manifest> root; if the file root is not <manifest> the file is rejected
  before any child is processed.
- When no <contactinfo> element is present, manifest.contactinfo.bugurl is
  set to Wrapper().BUG_URL by default.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError
from kanon_cli.repo.wrapper import Wrapper


# ---------------------------------------------------------------------------
# Shared helpers -- same pattern as other test_xml_contactinfo_*.py files
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
# AC-TEST-001: Cross-element reference validation for <contactinfo>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContactInfoCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <contactinfo> are validated.

    The <contactinfo> element has no remote= attribute, so no remote-name
    resolution cross-check is required. The cross-element behavior tested
    here is that <contactinfo> coexists correctly with all other manifest
    elements (remotes, defaults, projects, superproject, etc.) and that
    the bugurl is stored and retrievable regardless of the surrounding elements.

    The absence of a remote cross-reference is itself a property of the spec:
    the bugurl is a standalone URL string and the parser does not validate it
    against any declared element.
    """

    def test_contactinfo_coexists_with_remote_and_default(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<contactinfo> alongside <remote> and <default> parses without error.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <contactinfo bugurl="https://bugs.example.com/issues" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.contactinfo is not None, (
            "AC-TEST-001: expected contactinfo to be set when sibling to <remote> and <default> but got None"
        )
        assert manifest.contactinfo.bugurl == "https://bugs.example.com/issues", (
            f"AC-TEST-001: expected contactinfo.bugurl='https://bugs.example.com/issues' but got: "
            f"{manifest.contactinfo.bugurl!r}"
        )

    def test_contactinfo_bugurl_preserved_when_manifest_has_projects(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<contactinfo> bugurl is preserved correctly when the manifest also declares projects.

        AC-TEST-001, AC-FUNC-001
        """
        bugurl = "https://bugs.example.com/tracker"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <contactinfo bugurl="{bugurl}" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <project name="platform/sdk" path="sdk" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.contactinfo.bugurl == bugurl, (
            f"AC-TEST-001: expected contactinfo.bugurl='{bugurl}' with projects present but got: "
            f"{manifest.contactinfo.bugurl!r}"
        )
        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"AC-TEST-001: expected 'platform/core' in manifest.projects alongside contactinfo "
            f"but got: {project_names!r}"
        )
        assert "platform/sdk" in project_names, (
            f"AC-TEST-001: expected 'platform/sdk' in manifest.projects alongside contactinfo "
            f"but got: {project_names!r}"
        )

    def test_contactinfo_coexists_with_superproject(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<contactinfo> alongside <superproject> parses without error.

        A manifest may declare both a <contactinfo> and a <superproject>.
        Both must be set after loading and each must have the correct value.

        AC-TEST-001, AC-FUNC-001
        """
        bugurl = "https://bugs.example.com/superproject-tracker"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <contactinfo bugurl="{bugurl}" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.contactinfo is not None, (
            "AC-TEST-001: expected contactinfo to be set alongside <superproject> but got None"
        )
        assert manifest.contactinfo.bugurl == bugurl, (
            f"AC-TEST-001: expected contactinfo.bugurl='{bugurl}' alongside <superproject> but got: "
            f"{manifest.contactinfo.bugurl!r}"
        )
        assert manifest.superproject is not None, (
            "AC-TEST-001: expected superproject to be set when <contactinfo> is also present but got None"
        )

    def test_contactinfo_has_no_remote_cross_reference(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<contactinfo> with a bugurl that shares no relationship with any declared remote parses correctly.

        The bugurl is a standalone URL string. The parser does not resolve it
        against any declared <remote> element. A bugurl pointing to a host that
        differs from all remote fetch URLs must parse without error.

        AC-TEST-001, AC-FUNC-001
        """
        bugurl = "https://entirely-different-host.example.com/bugs"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://vcs.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <contactinfo bugurl="{bugurl}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.contactinfo.bugurl == bugurl, (
            f"AC-TEST-001: expected contactinfo.bugurl='{bugurl}' (unrelated to remote host) "
            f"to be stored without cross-reference validation but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_contactinfo_absent_uses_default_when_other_elements_present(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When <contactinfo> is absent, manifest.contactinfo.bugurl defaults even with other elements.

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

        expected_default = Wrapper().BUG_URL
        assert manifest.contactinfo is not None, (
            "AC-TEST-001: expected manifest.contactinfo to be set even without <contactinfo> element but got None"
        )
        assert manifest.contactinfo.bugurl == expected_default, (
            f"AC-TEST-001: expected contactinfo.bugurl='{expected_default}' (default) when element absent "
            f"but got: {manifest.contactinfo.bugurl!r}"
        )

    @pytest.mark.parametrize(
        "bugurl",
        [
            "https://bugs.example.com/issues",
            "https://github.com/org/repo/issues",
            "https://jira.example.com/browse/PROJ",
        ],
    )
    def test_contactinfo_bugurl_preserved_alongside_various_remotes(
        self,
        tmp_path: pathlib.Path,
        bugurl: str,
    ) -> None:
        """Parameterized: contactinfo.bugurl is preserved regardless of the declared remotes.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="alpha" fetch="https://alpha.example.com" />\n'
            '  <remote name="beta" fetch="https://beta.example.com" />\n'
            '  <default revision="main" remote="alpha" />\n'
            f'  <contactinfo bugurl="{bugurl}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.contactinfo.bugurl == bugurl, (
            f"AC-TEST-001: expected contactinfo.bugurl='{bugurl}' alongside multiple remotes "
            f"but got: {manifest.contactinfo.bugurl!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules for <contactinfo>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContactInfoDuplicateElementRules:
    """AC-TEST-002: Duplicate-element rules for <contactinfo> surface clear behavior.

    Unlike singleton elements such as <manifest-server> or <superproject>,
    <contactinfo> elements are NOT singleton -- multiple occurrences are
    explicitly supported. Each subsequent <contactinfo> overwrites the previous
    one (last-writer-wins). This behavior is documented and must NOT raise
    ManifestParseError.

    Tests here verify:
    - Two <contactinfo> elements with different bugurlss does not raise; the
      last one's bugurl is used.
    - Three <contactinfo> elements: the last bugurl wins.
    - Two identical <contactinfo> elements: same result as one.
    - The clobber sequence is deterministic (later in document order wins).
    """

    def test_two_contactinfo_elements_last_bugurl_wins(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <contactinfo> elements do not raise; the last bugurl is stored.

        The documented behaviour is that repeated <contactinfo> elements
        clobber each other; the last one in document order is the effective one.

        AC-TEST-002, AC-FUNC-001
        """
        first_url = "https://first.example.com/bugs"
        second_url = "https://second.example.com/bugs"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <contactinfo bugurl="{first_url}" />\n'
            f'  <contactinfo bugurl="{second_url}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.contactinfo.bugurl == second_url, (
            f"AC-TEST-002: expected last <contactinfo> bugurl='{second_url}' to win over "
            f"first='{first_url}' but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_two_contactinfo_elements_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <contactinfo> elements do not raise ManifestParseError.

        Unlike singleton elements, <contactinfo> permits multiple occurrences.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <contactinfo bugurl="https://first.example.com/bugs" />\n'
            '  <contactinfo bugurl="https://second.example.com/bugs" />\n'
            "</manifest>\n"
        )
        try:
            _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-002: expected multiple <contactinfo> elements to NOT raise "
                f"ManifestParseError but got: {exc!r}"
            )

    def test_three_contactinfo_elements_last_bugurl_wins(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Three <contactinfo> elements all parse without error; the last bugurl is used.

        AC-TEST-002, AC-FUNC-001
        """
        first_url = "https://first.example.com/bugs"
        second_url = "https://second.example.com/bugs"
        third_url = "https://third.example.com/bugs"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <contactinfo bugurl="{first_url}" />\n'
            f'  <contactinfo bugurl="{second_url}" />\n'
            f'  <contactinfo bugurl="{third_url}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.contactinfo.bugurl == third_url, (
            f"AC-TEST-002: expected third (last) <contactinfo> bugurl='{third_url}' to win "
            f"but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_identical_contactinfo_elements_are_accepted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two identical <contactinfo> elements parse without error and the bugurl is correct.

        When both elements carry the same bugurl, the result is the same as
        a single element.

        AC-TEST-002
        """
        bugurl = "https://bugs.example.com/same-url"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <contactinfo bugurl="{bugurl}" />\n'
            f'  <contactinfo bugurl="{bugurl}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.contactinfo.bugurl == bugurl, (
            f"AC-TEST-002: expected identical <contactinfo> elements to result in bugurl='{bugurl}' "
            f"but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_second_contactinfo_overrides_first_not_merges(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The second <contactinfo> completely replaces (not merges with) the first.

        The first element's bugurl must NOT be present in the final state.

        AC-TEST-002, AC-FUNC-001
        """
        first_url = "https://first.example.com/bugs"
        second_url = "https://second.example.com/bugs"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <contactinfo bugurl="{first_url}" />\n'
            f'  <contactinfo bugurl="{second_url}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.contactinfo.bugurl != first_url, (
            f"AC-TEST-002: expected first bugurl='{first_url}' to be replaced by the second "
            f"but contactinfo.bugurl still equals the first one: {manifest.contactinfo.bugurl!r}"
        )
        assert manifest.contactinfo.bugurl == second_url, (
            f"AC-TEST-002: expected second bugurl='{second_url}' to be the effective value "
            f"but got: {manifest.contactinfo.bugurl!r}"
        )

    @pytest.mark.parametrize(
        "bugurlss",
        [
            (
                "https://first.example.com/bugs",
                "https://second.example.com/bugs",
            ),
            (
                "https://github.com/org/repo/issues",
                "https://jira.example.com/browse/PROJ",
            ),
            (
                "https://gitlab.com/group/project/-/issues",
                "https://bugzilla.example.com/buglist.cgi",
            ),
        ],
    )
    def test_parameterized_last_contactinfo_wins(
        self,
        tmp_path: pathlib.Path,
        bugurlss: tuple,
    ) -> None:
        """Parameterized: in all cases the last <contactinfo> bugurl wins.

        AC-TEST-002
        """
        first_url, second_url = bugurlss
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <contactinfo bugurl="{first_url}" />\n'
            f'  <contactinfo bugurl="{second_url}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.contactinfo.bugurl == second_url, (
            f"AC-TEST-002: expected last bugurl='{second_url}' to win over first='{first_url}' "
            f"but got: {manifest.contactinfo.bugurl!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <contactinfo> in an unexpected parent raises or is ignored
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContactInfoUnexpectedParent:
    """AC-TEST-003: <contactinfo> in an unexpected parent raises or is ignored per spec.

    The parser processes <contactinfo> only when it appears as a direct child
    of the <manifest> root element. Behaviour when the parent is unexpected:

    - A manifest file whose root element is not <manifest> raises
      ManifestParseError before any children (including <contactinfo>) are
      examined. The error message mentions 'manifest'.
    - An unknown element sibling to <contactinfo> inside a valid <manifest>
      root is silently ignored; <contactinfo> is still processed normally.
    - A valid <manifest> root with <contactinfo> and unknown siblings parses
      correctly and sets manifest.contactinfo.
    """

    def test_contactinfo_in_non_manifest_root_file_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A file whose root element is not <manifest> raises ManifestParseError.

        The parser rejects the file at root-element validation time; the
        <contactinfo> child is never reached.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<repository>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <contactinfo bugurl="https://bugs.example.com/issues" />\n'
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
    def test_contactinfo_under_various_non_manifest_roots_raises(
        self,
        tmp_path: pathlib.Path,
        non_manifest_root: str,
    ) -> None:
        """Parameterized: <contactinfo> under any non-manifest root raises ManifestParseError.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{non_manifest_root}>\n"
            '  <contactinfo bugurl="https://bugs.example.com/issues" />\n'
            f"</{non_manifest_root}>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-003: expected a non-empty error message when <contactinfo> "
            f"appears under <{non_manifest_root}> but got an empty string"
        )

    def test_unknown_sibling_element_does_not_interfere_with_contactinfo(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An unknown element sibling to <contactinfo> inside <manifest> is ignored.

        Unknown elements inside a valid <manifest> root are silently skipped
        by the parser loop. The <contactinfo> element must still be processed
        and must store the correct bugurl.

        AC-TEST-003, AC-FUNC-001
        """
        bugurl = "https://bugs.example.com/issues"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <unknown-element attr="ignored-value" />\n'
            f'  <contactinfo bugurl="{bugurl}" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected unknown sibling element to be silently ignored "
                f"but got ManifestParseError: {exc!r}"
            )

        assert manifest.contactinfo is not None, (
            "AC-TEST-003: expected contactinfo to be set when unknown sibling "
            "element is present alongside <contactinfo> but got None"
        )
        assert manifest.contactinfo.bugurl == bugurl, (
            f"AC-TEST-003: expected contactinfo.bugurl='{bugurl}' when unknown sibling "
            f"is present but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_contactinfo_valid_in_manifest_root_resolves_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <contactinfo> inside a valid <manifest> root resolves its bugurl correctly.

        This positive test confirms the unexpected-parent logic: when the parent
        IS <manifest>, everything resolves normally.

        AC-TEST-003
        """
        bugurl = "https://bugs.example.com/expected"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <contactinfo bugurl="{bugurl}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.contactinfo is not None, (
            "AC-TEST-003: expected contactinfo to be set for valid <contactinfo> "
            "inside proper <manifest> parent but got None"
        )
        assert manifest.contactinfo.bugurl == bugurl, (
            f"AC-TEST-003: expected contactinfo.bugurl='{bugurl}' but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_nested_manifest_root_containing_contactinfo_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <manifest> nested inside a non-manifest root (not found at top level) raises.

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
            '    <contactinfo bugurl="https://bugs.example.com/issues" />\n'
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
            f"AC-TEST-003: expected 'manifest' in error for wrapped root containing "
            f"<contactinfo> but got: {error_message!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parser enforces cross-element and uniqueness rules at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContactInfoCrossRefParseTimeEnforcement:
    """AC-FUNC-001: All cross-element and uniqueness rules are enforced at parse time.

    Validation must occur during XmlManifest.Load(), not lazily on first use
    of manifest.contactinfo. These tests confirm that errors fire during
    Load() and that the manifest state is consistent after a successful parse.
    """

    def test_invalid_bugurl_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A missing bugurl attribute raises during Load(), not on first access.

        ManifestParseError must be raised inside XmlManifest.Load() before any
        caller accesses manifest.contactinfo.bugurl.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <contactinfo />\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_contactinfo_fully_resolved_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A valid <contactinfo> is fully resolved by the time Load() returns.

        After Load(), manifest.contactinfo is set with the bugurl from the
        element. No deferred resolution occurs.

        AC-FUNC-001
        """
        bugurl = "https://bugs.example.com/complete"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <contactinfo bugurl="{bugurl}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.contactinfo is not None, (
            "AC-FUNC-001: expected contactinfo to be set immediately after Load() but got None"
        )
        assert manifest.contactinfo.bugurl == bugurl, (
            f"AC-FUNC-001: expected contactinfo.bugurl='{bugurl}' after Load() but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_last_contactinfo_wins_enforced_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When multiple <contactinfo> elements appear, the last bugurl is the one after Load().

        The clobber behaviour is applied during Load() -- callers see the
        final effective state immediately after Load() completes.

        AC-FUNC-001
        """
        first_url = "https://first.example.com/bugs"
        last_url = "https://last.example.com/bugs"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <contactinfo bugurl="{first_url}" />\n'
            f'  <contactinfo bugurl="{last_url}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.contactinfo.bugurl == last_url, (
            f"AC-FUNC-001: expected last contactinfo bugurl='{last_url}' after Load() "
            f"but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_default_contactinfo_set_before_any_element_is_processed(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <contactinfo> element is present, manifest.contactinfo is still set after Load().

        The manifest initialises contactinfo to the default value during Load().
        The caller does not need to check for None.

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

        assert manifest.contactinfo is not None, (
            "AC-FUNC-001: expected manifest.contactinfo to be non-None after Load() "
            "even when no <contactinfo> element is present"
        )
        assert isinstance(manifest.contactinfo.bugurl, str), (
            "AC-FUNC-001: expected manifest.contactinfo.bugurl to be a str after Load() "
            f"but got: {type(manifest.contactinfo.bugurl)!r}"
        )
        assert manifest.contactinfo.bugurl, (
            "AC-FUNC-001: expected manifest.contactinfo.bugurl to be non-empty after Load()"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContactInfoCrossRefChannelDiscipline:
    """AC-CHANNEL-001: All cross-element errors surface as exceptions, not stdout.

    ManifestParseError must be the sole channel for reporting validation
    failures. No error text must appear on stdout. Successful parses must
    raise no exception and produce no output.
    """

    def test_missing_bugurl_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A missing bugurl raises ManifestParseError and produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <contactinfo />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for missing bugurl error but got: {captured.out!r}"
        )

    def test_non_manifest_root_with_contactinfo_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A non-manifest root file with <contactinfo> raises an exception, not stdout.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<config>\n"
            '  <contactinfo bugurl="https://bugs.example.com/issues" />\n'
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

    def test_duplicate_contactinfo_valid_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Duplicate <contactinfo> elements (which are valid) produce no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <contactinfo bugurl="https://first.example.com/bugs" />\n'
            '  <contactinfo bugurl="https://second.example.com/bugs" />\n'
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for valid duplicate <contactinfo> but got: {captured.out!r}"
        )

    def test_valid_contactinfo_crossref_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with valid <contactinfo> alongside other elements does not raise.

        AC-CHANNEL-001 (positive case: valid parses must not produce errors)
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <contactinfo bugurl="https://bugs.example.com/issues" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <project name="platform/sdk" path="sdk" remote="upstream" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-CHANNEL-001: expected valid <contactinfo> cross-reference to parse "
                f"without ManifestParseError but got: {exc!r}"
            )

        assert manifest.contactinfo is not None, (
            "AC-CHANNEL-001: expected contactinfo to be set after valid parse but got None"
        )
        assert manifest.contactinfo.bugurl == "https://bugs.example.com/issues", (
            f"AC-CHANNEL-001: expected contactinfo.bugurl='https://bugs.example.com/issues' "
            f"but got: {manifest.contactinfo.bugurl!r}"
        )
