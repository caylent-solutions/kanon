"""Unit tests for <include> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <include> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <include> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <include> element documented attributes:
  Required:  name      (path to included manifest, relative to manifest repo
                        root; validated by _CheckLocalPath at parse time)
  Optional:  groups    (comma-separated groups applied to all projects in
                        the included manifest)
             revision  (default revision applied to included projects that
                        do not specify their own revision)
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestInvalidPathError
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- mirrors the pattern used in test_xml_include_happy.py
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
        ManifestInvalidPathError: If an attribute contains an invalid path.
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


def _write_included_manifest(repodir: pathlib.Path, filename: str, xml_content: str) -> pathlib.Path:
    """Write xml_content to a named file inside the manifests include_root.

    Args:
        repodir: The .repo directory.
        filename: Filename for the included manifest (no directory separators).
        xml_content: Full XML content for the included manifest.

    Returns:
        Absolute path to the written included manifest file.
    """
    included_file = repodir / "manifests" / filename
    included_file.write_text(xml_content, encoding="utf-8")
    return included_file


def _setup_include_scenario(
    tmp_path: pathlib.Path,
    primary_xml: str,
    included_filename: str,
    included_xml: str,
) -> manifest_xml.XmlManifest:
    """Write a primary manifest that includes a secondary manifest and load it.

    Args:
        tmp_path: Pytest tmp_path fixture for isolation.
        primary_xml: Full XML content for the primary manifest file.
        included_filename: Filename for the included manifest.
        included_xml: Full XML content for the included manifest.

    Returns:
        A loaded XmlManifest instance.
    """
    repodir = _make_repo_dir(tmp_path)
    _write_included_manifest(repodir, included_filename, included_xml)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(primary_xml, encoding="utf-8")
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


def _setup_nested_include_scenario(
    tmp_path: pathlib.Path,
    bad_include_name: str,
) -> tuple:
    """Write a two-level include scenario where the included manifest references a bad path.

    The primary manifest includes an intermediate manifest (restrict_includes=False
    for the primary level). The intermediate manifest contains an <include> with
    the given bad_include_name. Because the intermediate manifest is loaded with
    restrict_includes=True (the default for recursive includes), the bad path
    triggers ManifestInvalidPathError.

    Args:
        tmp_path: Pytest tmp_path fixture for isolation.
        bad_include_name: The invalid name attribute to use in the nested include.

    Returns:
        A 2-tuple (XmlManifest instance, manifest_file path). The manifest has
        NOT been loaded yet -- callers must call m.Load() to trigger validation.
    """
    repodir = _make_repo_dir(tmp_path)
    # The intermediate manifest contains an <include> with the bad path.
    # It will be parsed with restrict_includes=True (the default) so
    # _CheckLocalPath runs and raises ManifestInvalidPathError.
    intermediate_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="{bad_include_name}" />\n</manifest>\n'
    )
    _write_included_manifest(repodir, "intermediate.xml", intermediate_xml)
    primary_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="intermediate.xml" />\n</manifest>\n'
    )
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(primary_xml, encoding="utf-8")
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    return m, manifest_file


_MINIMAL_INCLUDED_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="origin" fetch="https://example.com" />\n'
    '  <default revision="main" remote="origin" />\n'
    '  <project name="platform/core" path="core" />\n'
    "</manifest>\n"
)


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests -- one per documented <include> attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeAttributeValidValues:
    """AC-TEST-001: Every documented attribute of <include> has a valid-value test.

    Each test method exercises one attribute with a legal value and asserts
    that (a) no exception is raised and (b) the expected observable effect
    on the parsed manifest is present.
    """

    def test_name_attribute_valid_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid name attribute causes the include to be resolved.

        The included manifest file must exist on disk. After parsing the
        primary manifest, projects from the included manifest are visible.
        """
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="sub.xml" />\n</manifest>\n'

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", _MINIMAL_INCLUDED_XML)

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"AC-TEST-001: expected 'platform/core' from included manifest to appear after "
            f"<include name='sub.xml'> but got: {project_names!r}"
        )

    @pytest.mark.parametrize(
        "filename",
        [
            "extra.xml",
            "vendor-manifest.xml",
            "platform-projects.xml",
        ],
    )
    def test_name_attribute_valid_various_filenames(
        self,
        tmp_path: pathlib.Path,
        filename: str,
    ) -> None:
        """AC-TEST-001: The name attribute accepts various valid filenames.

        Each filename must refer to an existing file in the manifests directory.
        """
        primary_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="{filename}" />\n</manifest>\n'
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, filename, _MINIMAL_INCLUDED_XML)

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"AC-TEST-001: expected 'platform/core' visible after <include name='{filename}'> "
            f"but got: {project_names!r}"
        )

    def test_groups_attribute_valid_applies_to_included_projects(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid groups attribute applies listed groups to included projects.

        All projects in the included manifest receive the groups named in the
        <include groups="..."> attribute.
        """
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="sub.xml" groups="sdk,release" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", _MINIMAL_INCLUDED_XML)

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert "sdk" in core.groups, (
            f"AC-TEST-001: expected group 'sdk' from <include groups='sdk,release'> on "
            f"'platform/core' but got: {core.groups!r}"
        )
        assert "release" in core.groups, (
            f"AC-TEST-001: expected group 'release' from <include groups='sdk,release'> on "
            f"'platform/core' but got: {core.groups!r}"
        )

    def test_revision_attribute_valid_applies_to_included_projects_without_own_revision(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid revision attribute provides a default revision for included projects.

        Included projects that do not specify their own revision receive the
        revision from the <include revision="..."> attribute.
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default remote="origin" />\n'
            '  <project name="platform/norev" path="norev" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="sub.xml" revision="refs/tags/v2.0.0" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        norev = projects["platform/norev"]
        assert norev.revisionExpr == "refs/tags/v2.0.0", (
            f"AC-TEST-001: expected revisionExpr='refs/tags/v2.0.0' from "
            f"<include revision='refs/tags/v2.0.0'> on project with no own revision "
            f"but got: {norev.revisionExpr!r}"
        )

    def test_groups_and_revision_attributes_together_apply_both(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: Both groups and revision attributes can be used simultaneously.

        An <include> element with both groups and revision applies both to the
        included projects.
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default remote="origin" />\n'
            '  <project name="vendor/lib" path="lib" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="sub.xml" groups="external" revision="refs/tags/v1.5.0" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        lib = projects["vendor/lib"]
        assert "external" in lib.groups, (
            f"AC-TEST-001: expected group 'external' from <include groups='external'> but got: {lib.groups!r}"
        )
        assert lib.revisionExpr == "refs/tags/v1.5.0", (
            f"AC-TEST-001: expected revisionExpr='refs/tags/v1.5.0' from "
            f"<include revision='refs/tags/v1.5.0'> but got: {lib.revisionExpr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Invalid-value tests -- one per attribute with invalid inputs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeAttributeInvalidValues:
    """AC-TEST-002: Every attribute has invalid-value tests.

    Tests verify that illegal values raise ManifestParseError or
    ManifestInvalidPathError at parse time.
    """

    def test_name_path_traversal_raises_manifest_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A name containing '..' raises ManifestInvalidPathError.

        _CheckLocalPath rejects path components that would escape the manifests
        directory (e.g., '../other.xml'). This validation runs with
        restrict_includes=True which applies to <include> elements inside
        an already-included manifest file.
        """
        m, _ = _setup_nested_include_scenario(tmp_path, "../escape.xml")

        with pytest.raises(ManifestInvalidPathError):
            m.Load()

    def test_name_git_directory_component_raises_manifest_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A name containing '.git' raises ManifestInvalidPathError.

        _CheckLocalPath rejects path components equal to '.git' to prevent
        git directory traversal. The check applies to nested includes.
        """
        m, _ = _setup_nested_include_scenario(tmp_path, ".git/config")

        with pytest.raises(ManifestInvalidPathError):
            m.Load()

    def test_name_dot_repo_component_raises_manifest_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A name starting with '.repo' raises ManifestInvalidPathError.

        _CheckLocalPath rejects path components that start with '.repo'.
        The check applies to nested includes.
        """
        m, _ = _setup_nested_include_scenario(tmp_path, ".repo/secret.xml")

        with pytest.raises(ManifestInvalidPathError):
            m.Load()

    def test_name_nonexistent_file_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A name referencing a non-existent file raises ManifestParseError.

        After path validation passes, the parser checks that the named file
        actually exists on disk and raises ManifestParseError if it does not.
        This applies at any include nesting level.
        """
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="no-such-file.xml" />\n</manifest>\n'
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(primary_xml, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        assert "no-such-file.xml" in str(exc_info.value), (
            f"AC-TEST-002: expected error message to mention 'no-such-file.xml' but got: {exc_info.value!r}"
        )

    def test_name_tilde_in_path_raises_manifest_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A name containing '~' raises ManifestInvalidPathError.

        _CheckLocalPath rejects tilde in paths due to 8.3 filename concerns
        on Windows filesystems. The check applies to nested includes.
        """
        m, _ = _setup_nested_include_scenario(tmp_path, "~bad.xml")

        with pytest.raises(ManifestInvalidPathError):
            m.Load()

    @pytest.mark.parametrize(
        "bad_name",
        [
            "../escape.xml",
            ".git/config",
            ".repo/private.xml",
            "~home.xml",
        ],
    )
    def test_name_invalid_path_values_raise_manifest_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
        bad_name: str,
    ) -> None:
        """AC-TEST-002: Parameterized invalid name values all raise ManifestInvalidPathError.

        Each bad_name value violates a _CheckLocalPath constraint and must
        cause ManifestInvalidPathError when the include appears inside an
        already-included manifest file (where restrict_includes=True).
        """
        m, _ = _setup_nested_include_scenario(tmp_path, bad_name)

        with pytest.raises(ManifestInvalidPathError):
            m.Load()

    def test_name_invalid_path_error_message_identifies_include_element(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: The ManifestInvalidPathError message identifies the <include> element.

        The error message must mention 'include' so the user can locate the
        offending element in the manifest.
        """
        m, _ = _setup_nested_include_scenario(tmp_path, "../escape.xml")

        with pytest.raises(ManifestInvalidPathError) as exc_info:
            m.Load()

        assert "include" in str(exc_info.value).lower(), (
            f"AC-TEST-002: expected error message to identify '<include>' element but got: {exc_info.value!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Required attribute omission tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeRequiredAttributeOmission:
    """AC-TEST-003: Required attribute omission raises with message naming the attribute.

    The <include> element has exactly one required attribute: name.
    Omitting it must raise ManifestParseError with a message that names
    the missing attribute so the user can identify and fix the problem.
    """

    def test_name_omitted_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: Omitting the name attribute raises ManifestParseError.

        An <include> element without a name attribute is invalid.
        The parser must raise ManifestParseError immediately.
        """
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include />\n</manifest>\n'
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(primary_xml, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_name_omitted_error_message_names_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: The error for missing name attribute names 'name' in the message.

        The ManifestParseError raised by _reqatt includes the missing attribute
        name so the user can identify what is wrong.
        """
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include />\n</manifest>\n'
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(primary_xml, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        assert "name" in str(exc_info.value), (
            f"AC-TEST-003: expected error message to name the missing attribute 'name' but got: {exc_info.value!r}"
        )

    def test_name_empty_string_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: An empty name attribute is treated as missing and raises ManifestParseError.

        _reqatt returns the attribute value only if it is non-empty; an empty
        string is equivalent to a missing attribute and raises ManifestParseError.
        """
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="" />\n</manifest>\n'
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(primary_xml, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()


# ---------------------------------------------------------------------------
# AC-FUNC-001: Attribute validation happens at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeAttributeValidatedAtParseTime:
    """AC-FUNC-001: Every documented attribute of <include> is validated at parse time.

    Validation must be triggered during m.Load(), not deferred to a later
    pipeline stage. Tests verify that calling m.Load() is sufficient to
    surface attribute errors.
    """

    def test_invalid_name_raises_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: ManifestInvalidPathError raised during m.Load() for invalid name.

        The error is not deferred -- it is raised as part of the parse phase.
        The check applies when the <include> appears inside an already-included
        manifest file (where restrict_includes=True).
        """
        m, _ = _setup_nested_include_scenario(tmp_path, "../outside.xml")

        with pytest.raises(ManifestInvalidPathError):
            m.Load()

    def test_missing_name_raises_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: ManifestParseError raised during m.Load() for missing name.

        Constructing XmlManifest does not itself parse the XML; m.Load() must
        be called and it is during that call that the error is detected.
        """
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include />\n</manifest>\n'
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(primary_xml, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        # Construction must not raise -- error is deferred until Load().
        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_groups_attribute_applied_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: The groups attribute effect is observable immediately after m.Load().

        The included projects carry the groups from the <include> element
        as soon as m.Load() completes.
        """
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="sub.xml" groups="pdk" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", _MINIMAL_INCLUDED_XML)

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert "pdk" in core.groups, (
            f"AC-FUNC-001: expected group 'pdk' present after m.Load() for "
            f"<include groups='pdk'> but got: {core.groups!r}"
        )

    def test_valid_revision_attribute_applied_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: The revision attribute effect is observable immediately after m.Load().

        The included project carries the revision from the <include> element
        as soon as m.Load() completes.
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default remote="origin" />\n'
            '  <project name="platform/tools" path="tools" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="sub.xml" revision="refs/tags/v3.0.0" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        tools = projects["platform/tools"]
        assert tools.revisionExpr == "refs/tags/v3.0.0", (
            f"AC-FUNC-001: expected revisionExpr='refs/tags/v3.0.0' after m.Load() for "
            f"<include revision='refs/tags/v3.0.0'> but got: {tools.revisionExpr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeAttributeChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr discipline is verified.

    Attribute validation errors must be surfaced as exceptions, not written
    to stdout. Tests verify that parse errors produce no stdout output.
    """

    def test_invalid_name_path_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: An invalid name path raises an exception, not stdout output.

        No diagnostic text should reach stdout when a bad path is encountered.
        The check applies to nested includes where restrict_includes=True.
        """
        m, _ = _setup_nested_include_scenario(tmp_path, "../bad.xml")

        with pytest.raises(ManifestInvalidPathError):
            m.Load()

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for invalid <include> name path but got: {captured.out!r}"
        )

    def test_missing_name_attribute_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: A missing name attribute raises an exception, not stdout output.

        No diagnostic text should reach stdout when the name attribute is absent.
        """
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include />\n</manifest>\n'
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(primary_xml, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for missing <include> name but got: {captured.out!r}"
        )

    def test_nonexistent_include_file_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: A non-existent include file raises an exception, not stdout output.

        No diagnostic text should reach stdout when the named file is absent.
        """
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="phantom.xml" />\n</manifest>\n'
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(primary_xml, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for missing include file but got: {captured.out!r}"
        )

    def test_valid_include_does_not_raise_on_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-CHANNEL-001: A valid <include> loads without raising ManifestParseError.

        Confirms that the positive path works correctly as a sanity check for
        channel discipline (no false positives from the negative tests).
        """
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="sub.xml" />\n</manifest>\n'
        try:
            _setup_include_scenario(tmp_path, primary_xml, "sub.xml", _MINIMAL_INCLUDED_XML)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-CHANNEL-001: expected valid <include> to parse without ManifestParseError but got: {exc!r}"
            )
