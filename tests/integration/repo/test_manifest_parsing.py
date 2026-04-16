"""Integration tests for manifest XML parsing.

Tests cover <include> element resolution, <remote> definitions, <default>
settings, project groups (manifest-group filtering), and malformed XML error
handling.

All tests use real manifest files on disk created in tmp_path.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: This file exists at tests/integration/repo/test_manifest_parsing.py
AC-FUNC-002: At least 12 test functions defined
AC-FUNC-003: Tests cover <include> element resolution (nested, missing)
AC-FUNC-004: Tests cover <remote> definitions (single, multiple, missing)
AC-FUNC-005: Tests cover <default> settings (revision, remote, sync-j, sync-c)
AC-FUNC-006: Tests cover project groups (group filtering, default groups)
AC-FUNC-007: Tests cover malformed XML error handling
AC-FUNC-008: All tests use real manifest files on disk
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared manifest setup helpers
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


def _write_included_manifest(repodir: pathlib.Path, name: str, xml_content: str) -> pathlib.Path:
    """Write an additional manifest file inside .repo/manifests/ for <include>.

    Args:
        repodir: The .repo directory.
        name: Filename relative to .repo/manifests/.
        xml_content: Full XML content for the included manifest.

    Returns:
        Absolute path to the written file.
    """
    target = repodir / "manifests" / name
    target.write_text(xml_content, encoding="utf-8")
    return target


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


# ---------------------------------------------------------------------------
# AC-FUNC-003: <include> element resolution
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_include_single_level_resolves_projects(tmp_path: pathlib.Path) -> None:
    """A single <include> in the main manifest merges projects from the included file.

    Writes a main manifest that includes a child.xml file. The child.xml
    defines a project. After loading, verifies that the project from child.xml
    appears in the manifest's project list.

    AC-FUNC-003, AC-FUNC-008
    """
    repodir = _make_repo_dir(tmp_path)

    child_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <project name="included/project" path="included-path" />\n'
        "</manifest>\n"
    )
    _write_included_manifest(repodir, "child.xml", child_xml)

    main_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <include name="child.xml" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, main_xml)
    manifest = _load_manifest(repodir, manifest_file)

    project_names = [p.name for p in manifest.projects]
    assert "included/project" in project_names, (
        f"Expected 'included/project' to appear in projects after <include> resolution, but got: {project_names!r}"
    )


@pytest.mark.integration
def test_include_missing_file_raises_manifest_parse_error(tmp_path: pathlib.Path) -> None:
    """A <include> referencing a nonexistent file raises ManifestParseError.

    The manifest references missing.xml which does not exist on disk. Loading
    must raise ManifestParseError with a message identifying the missing file.

    AC-FUNC-003, AC-FUNC-007, AC-FUNC-008
    """
    repodir = _make_repo_dir(tmp_path)

    main_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <include name="missing.xml" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, main_xml)

    with pytest.raises(ManifestParseError) as exc_info:
        _load_manifest(repodir, manifest_file)

    error_message = str(exc_info.value)
    assert "missing.xml" in error_message, (
        f"Expected error message to reference 'missing.xml' but got: {error_message!r}"
    )


@pytest.mark.integration
def test_include_nested_two_levels_resolves_all_projects(tmp_path: pathlib.Path) -> None:
    """Nested <include> chains (A -> B -> C) resolve projects from all levels.

    main.xml includes middle.xml which includes leaf.xml. Each level defines
    one project. After loading main.xml, all three projects must be present.

    AC-FUNC-003, AC-FUNC-008
    """
    repodir = _make_repo_dir(tmp_path)

    leaf_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <project name="leaf/project" path="leaf-path" />\n'
        "</manifest>\n"
    )
    _write_included_manifest(repodir, "leaf.xml", leaf_xml)

    middle_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <project name="middle/project" path="middle-path" />\n'
        '  <include name="leaf.xml" />\n'
        "</manifest>\n"
    )
    _write_included_manifest(repodir, "middle.xml", middle_xml)

    main_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="top/project" path="top-path" />\n'
        '  <include name="middle.xml" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, main_xml)
    manifest = _load_manifest(repodir, manifest_file)

    project_names = [p.name for p in manifest.projects]
    for expected_name in ("top/project", "middle/project", "leaf/project"):
        assert expected_name in project_names, (
            f"Expected '{expected_name}' in projects after nested <include> resolution, but got: {project_names!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-004: <remote> definitions
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_remote_single_definition_parsed(tmp_path: pathlib.Path) -> None:
    """A single <remote> element is parsed with the correct name and fetch URL.

    Writes a manifest with one remote element. After loading, verifies the
    remote's name and fetchUrl match the values written to disk.

    AC-FUNC-004, AC-FUNC-008
    """
    repodir = _make_repo_dir(tmp_path)

    main_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="myremote" fetch="https://git.example.com" />\n'
        '  <default revision="main" remote="myremote" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, main_xml)
    manifest = _load_manifest(repodir, manifest_file)

    assert "myremote" in manifest.remotes, (
        f"Expected remote named 'myremote' in manifest.remotes but got keys: {list(manifest.remotes.keys())!r}"
    )
    remote = manifest.remotes["myremote"]
    assert remote.fetchUrl is not None, "Expected remote.fetchUrl to be set but got None"
    assert "https://git.example.com" in remote.fetchUrl, (
        f"Expected 'https://git.example.com' in remote.fetchUrl but got: {remote.fetchUrl!r}"
    )


@pytest.mark.integration
def test_remote_multiple_definitions_all_parsed(tmp_path: pathlib.Path) -> None:
    """Multiple <remote> elements are all parsed and available by name.

    Writes a manifest with two distinct remote elements. After loading,
    verifies both remotes are present and have the correct fetch URLs.

    AC-FUNC-004, AC-FUNC-008
    """
    repodir = _make_repo_dir(tmp_path)

    main_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="alpha" fetch="https://alpha.example.com" />\n'
        '  <remote name="beta" fetch="https://beta.example.com" />\n'
        '  <default revision="main" remote="alpha" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, main_xml)
    manifest = _load_manifest(repodir, manifest_file)

    for remote_name, expected_fetch in (
        ("alpha", "https://alpha.example.com"),
        ("beta", "https://beta.example.com"),
    ):
        assert remote_name in manifest.remotes, (
            f"Expected remote '{remote_name}' in manifest.remotes but got: {list(manifest.remotes.keys())!r}"
        )
        actual_fetch = manifest.remotes[remote_name].fetchUrl
        assert expected_fetch in actual_fetch, (
            f"Expected '{expected_fetch}' in remote '{remote_name}' fetchUrl but got: {actual_fetch!r}"
        )


@pytest.mark.integration
def test_remote_missing_fetch_attribute_raises_manifest_parse_error(tmp_path: pathlib.Path) -> None:
    """A <remote> element without a required 'fetch' attribute raises ManifestParseError.

    The repo manifest format requires 'fetch' on every remote. Omitting it
    must cause a ManifestParseError when the manifest is loaded.

    AC-FUNC-004, AC-FUNC-007, AC-FUNC-008
    """
    repodir = _make_repo_dir(tmp_path)

    main_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="nofetch" />\n'
        '  <default revision="main" remote="nofetch" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, main_xml)

    with pytest.raises(ManifestParseError) as exc_info:
        _load_manifest(repodir, manifest_file)

    error_message = str(exc_info.value)
    assert error_message, "Expected a non-empty error message from ManifestParseError but got an empty string"


# ---------------------------------------------------------------------------
# AC-FUNC-005: <default> settings
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_default_revision_applied_to_project(tmp_path: pathlib.Path) -> None:
    """The <default> revision is inherited by projects without an explicit revision.

    Writes a manifest where the default revision is 'refs/heads/stable'. A
    project that does not set its own revision must inherit 'refs/heads/stable'.

    AC-FUNC-005, AC-FUNC-008
    """
    repodir = _make_repo_dir(tmp_path)

    main_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="refs/heads/stable" remote="origin" />\n'
        '  <project name="platform/build" path="build" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, main_xml)
    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    assert "platform/build" in projects, (
        f"Expected 'platform/build' in manifest projects but got: {list(projects.keys())!r}"
    )
    actual_revision = projects["platform/build"].revisionExpr
    assert actual_revision == "refs/heads/stable", (
        f"Expected project revision 'refs/heads/stable' from <default> but got: {actual_revision!r}"
    )


@pytest.mark.integration
def test_default_sync_j_and_sync_c_parsed(tmp_path: pathlib.Path) -> None:
    """The <default> sync-j integer and sync-c boolean attributes are parsed correctly.

    Writes a manifest with sync-j=8 and sync-c=true on the default element.
    After loading, verifies the parsed default values match the written values.

    AC-FUNC-005, AC-FUNC-008
    """
    repodir = _make_repo_dir(tmp_path)

    main_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" sync-j="8" sync-c="true" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, main_xml)
    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.default.sync_j == 8, f"Expected manifest default sync-j=8 but got: {manifest.default.sync_j!r}"
    assert manifest.default.sync_c is True, (
        f"Expected manifest default sync-c=True but got: {manifest.default.sync_c!r}"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-006: <manifest-group> elements / project group filtering
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_project_custom_group_assigned_and_matchable(tmp_path: pathlib.Path) -> None:
    """A project with groups='mygroup' is matched by a manifest_groups filter of 'mygroup'.

    Writes a manifest with two projects: one belonging to 'mygroup' and one
    without. Verifies that the project with 'mygroup' matches the 'mygroup'
    filter and the other does not.

    AC-FUNC-006, AC-FUNC-008
    """
    repodir = _make_repo_dir(tmp_path)

    main_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/build" path="build" groups="mygroup" />\n'
        '  <project name="platform/tools" path="tools" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, main_xml)
    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    assert "platform/build" in projects, (
        f"Expected 'platform/build' in manifest projects but got: {list(projects.keys())!r}"
    )
    assert "platform/tools" in projects, (
        f"Expected 'platform/tools' in manifest projects but got: {list(projects.keys())!r}"
    )

    build_project = projects["platform/build"]
    tools_project = projects["platform/tools"]

    assert build_project.MatchesGroups(["mygroup"]), (
        "Expected 'platform/build' (groups='mygroup') to match manifest group filter ['mygroup']"
    )
    assert not tools_project.MatchesGroups(["mygroup", "-default"]), (
        "Expected 'platform/tools' (no custom groups) not to match ['mygroup', '-default'] filter"
    )


@pytest.mark.integration
def test_every_project_has_implicit_all_group(tmp_path: pathlib.Path) -> None:
    """Every project automatically belongs to the 'all' group regardless of its groups attr.

    Writes a manifest with two projects: one with an explicit group and one
    without. Both must match the manifest group filter ['all'] because 'all'
    is implicitly added to every project's group list by the parser.

    AC-FUNC-006, AC-FUNC-008
    """
    repodir = _make_repo_dir(tmp_path)

    main_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/build" path="build" groups="special" />\n'
        '  <project name="platform/tools" path="tools" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, main_xml)
    manifest = _load_manifest(repodir, manifest_file)

    for project in manifest.projects:
        assert "all" in project.groups, (
            f"Expected project '{project.name}' to have implicit 'all' group but project.groups={project.groups!r}"
        )
        assert project.MatchesGroups(["all"]), (
            f"Expected project '{project.name}' to match manifest group filter ['all'] "
            f"but MatchesGroups returned False. project.groups={project.groups!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-007: Malformed XML error handling
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_malformed_xml_unclosed_tag_raises_manifest_parse_error(tmp_path: pathlib.Path) -> None:
    """XML with an unclosed element tag raises ManifestParseError on load.

    Writes a syntactically invalid manifest file that has an unclosed tag.
    The XML parser must detect the malformation and ManifestParseError must be
    raised with a message referencing the manifest file path.

    AC-FUNC-007, AC-FUNC-008
    """
    repodir = _make_repo_dir(tmp_path)

    malformed_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com"\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, malformed_xml)

    with pytest.raises(ManifestParseError) as exc_info:
        _load_manifest(repodir, manifest_file)

    error_message = str(exc_info.value)
    assert str(manifest_file) in error_message or "manifest" in error_message.lower(), (
        f"Expected error message to reference the manifest file or 'manifest' but got: {error_message!r}"
    )


@pytest.mark.integration
def test_malformed_xml_completely_invalid_content_raises_manifest_parse_error(
    tmp_path: pathlib.Path,
) -> None:
    """Completely non-XML content raises ManifestParseError on load.

    Writes a file that contains arbitrary non-XML bytes where a manifest is
    expected. The XML parser must raise an error that is caught and re-raised
    as ManifestParseError.

    AC-FUNC-007, AC-FUNC-008
    """
    repodir = _make_repo_dir(tmp_path)

    not_xml_at_all = "this is not xml content at all !!!\n"
    manifest_file = _write_manifest(repodir, not_xml_at_all)

    with pytest.raises(ManifestParseError):
        _load_manifest(repodir, manifest_file)


@pytest.mark.integration
def test_malformed_xml_invalid_attribute_value_in_sync_j_raises_manifest_parse_error(
    tmp_path: pathlib.Path,
) -> None:
    """A non-integer value for sync-j raises ManifestParseError.

    The <default> sync-j attribute must be an integer. Providing a non-numeric
    string value must cause the manifest load to fail with ManifestParseError.

    AC-FUNC-007, AC-FUNC-008
    """
    repodir = _make_repo_dir(tmp_path)

    main_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" sync-j="notanumber" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, main_xml)

    with pytest.raises(ManifestParseError) as exc_info:
        _load_manifest(repodir, manifest_file)

    error_message = str(exc_info.value)
    assert "sync-j" in error_message or "notanumber" in error_message, (
        f"Expected error message to mention 'sync-j' or 'notanumber' but got: {error_message!r}"
    )
