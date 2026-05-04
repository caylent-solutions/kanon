"""Integration tests for <extend-project> round-trip parsing.

Tests parse a real manifest XML file from disk containing <extend-project>
elements, verify the parsed model reflects the extensions applied, and
confirm round-trip serialization via ToXml preserves the expected structural
elements.

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <extend-project> parses without error and the
parsed model matches the XML.
AC-FINAL-010: Real manifest parse + round-trip succeeds against a real
on-disk fixture.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern in test_xml_manifest_roundtrip.py
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


# ---------------------------------------------------------------------------
# Fixture XML content for extend-project round-trip tests
# ---------------------------------------------------------------------------

_EXTEND_PROJECT_FIXTURE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="origin" fetch="https://example.com" />\n'
    '  <remote name="mirror" fetch="https://mirror.example.com" />\n'
    '  <default revision="main" remote="origin" />\n'
    '  <project name="platform/build" path="build" groups="pdk" />\n'
    '  <project name="platform/tools" path="tools" revision="refs/tags/v1.0.0" />\n'
    '  <extend-project name="platform/build" groups="extra,release" />\n'
    '  <extend-project name="platform/tools" revision="refs/tags/v2.0.0" dest-branch="refs/heads/stable" />\n'
    "</manifest>\n"
)


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-FINAL-010: Real parse + model verification
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_extend_project_manifest_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest containing <extend-project> elements parses into a valid XmlManifest.

    Writes the fixture XML to a real .repo directory structure and loads it.
    No exception must be raised.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _EXTEND_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading extend-project manifest"


@pytest.mark.integration
def test_extend_project_groups_applied_to_project(tmp_path: pathlib.Path) -> None:
    """After parsing, <extend-project groups="extra,release"> is applied to platform/build.

    The fixture extends platform/build with groups 'extra' and 'release'. After
    parsing, those groups must appear on the project alongside the original 'pdk'.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _EXTEND_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    build = projects["platform/build"]
    assert "pdk" in build.groups, (
        f"Expected original group 'pdk' to be preserved on platform/build but got: {build.groups!r}"
    )
    assert "extra" in build.groups, (
        f"Expected extended group 'extra' on platform/build after extend-project but got: {build.groups!r}"
    )
    assert "release" in build.groups, (
        f"Expected extended group 'release' on platform/build after extend-project but got: {build.groups!r}"
    )


@pytest.mark.integration
def test_extend_project_revision_updated_on_project(tmp_path: pathlib.Path) -> None:
    """After parsing, <extend-project revision="refs/tags/v2.0.0"> updates platform/tools.

    The fixture declares platform/tools with revision refs/tags/v1.0.0 and then
    extends it with revision refs/tags/v2.0.0. The resulting project must have
    revisionExpr == "refs/tags/v2.0.0".

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _EXTEND_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    tools = projects["platform/tools"]
    assert tools.revisionExpr == "refs/tags/v2.0.0", (
        f"Expected platform/tools revisionExpr='refs/tags/v2.0.0' after extend-project but got: {tools.revisionExpr!r}"
    )


@pytest.mark.integration
def test_extend_project_dest_branch_updated_on_project(tmp_path: pathlib.Path) -> None:
    """After parsing, <extend-project dest-branch="..."> sets dest_branch on platform/tools.

    The fixture extends platform/tools with dest-branch="refs/heads/stable".
    After parsing, the project's dest_branch must be "refs/heads/stable".

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _EXTEND_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    tools = projects["platform/tools"]
    assert tools.dest_branch == "refs/heads/stable", (
        f"Expected platform/tools dest_branch='refs/heads/stable' after extend-project but got: {tools.dest_branch!r}"
    )


@pytest.mark.integration
def test_extend_project_non_extended_project_unmodified(tmp_path: pathlib.Path) -> None:
    """Projects not named in any <extend-project> retain their original attributes.

    AC-FUNC-001
    """
    repodir = _make_repo_dir(tmp_path)
    # Only platform/tools is extended here; platform/build is not
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/build" path="build" groups="pdk" />\n'
        '  <project name="platform/tools" path="tools" />\n'
        '  <extend-project name="platform/tools" groups="extra" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    build = projects["platform/build"]
    assert "pdk" in build.groups, f"Expected 'pdk' group on platform/build to be unmodified but got: {build.groups!r}"
    assert "extra" not in build.groups, (
        f"Expected 'extra' NOT in platform/build.groups (only tools was extended) but got: {build.groups!r}"
    )


# ---------------------------------------------------------------------------
# Round-trip: parse + ToXml preserves structural elements
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_roundtrip_extend_project_project_count_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: the project count is preserved after parse + serialize.

    <extend-project> elements modify project attributes but do not add or
    remove projects. The serialized output must contain the same number of
    <project> elements as the original manifest.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _EXTEND_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    original_project_count = len(manifest.projects)

    doc = manifest.ToXml()
    root = doc.documentElement
    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    assert len(project_elements) == original_project_count, (
        f"Expected {original_project_count} <project> elements in round-trip XML but found: {len(project_elements)}"
    )


@pytest.mark.integration
def test_roundtrip_extend_project_remote_count_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: the remote count is preserved after parse + serialize.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _EXTEND_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)
    original_remote_count = len(manifest.remotes)

    doc = manifest.ToXml()
    root = doc.documentElement
    remote_elements = [n for n in root.childNodes if n.nodeName == "remote"]
    assert len(remote_elements) == original_remote_count, (
        f"Expected {original_remote_count} <remote> elements in round-trip XML but found: {len(remote_elements)}"
    )


@pytest.mark.integration
def test_roundtrip_extend_project_project_names_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: the project names survive parse + serialize.

    Parses the fixture, calls ToXml(), and verifies the expected project names
    appear in the resulting XML document.

    AC-FUNC-001
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, _EXTEND_PROJECT_FIXTURE_XML)

    manifest = _load_manifest(repodir, manifest_file)

    doc = manifest.ToXml()
    xml_text = doc.toxml(encoding="UTF-8").decode("utf-8")

    for project_name in ("platform/build", "platform/tools"):
        assert project_name in xml_text, f"Expected project name '{project_name}' in round-trip XML but it was absent"


@pytest.mark.integration
def test_roundtrip_extend_project_revised_revision_in_model(tmp_path: pathlib.Path) -> None:
    """Round-trip: the model reflects the revised revision after extend-project.

    After parse + serialize, the manifest model's project has the updated
    revision from the <extend-project revision="..."> element, not the original.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/tools" path="tools" revision="refs/tags/v1.0.0" />\n'
        '  <extend-project name="platform/tools" revision="refs/tags/v3.0.0" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    tools = projects["platform/tools"]
    assert tools.revisionExpr == "refs/tags/v3.0.0", (
        f"Expected revisionExpr='refs/tags/v3.0.0' (updated by extend-project) but got: {tools.revisionExpr!r}"
    )


@pytest.mark.integration
def test_inline_extend_project_parse_and_model_match(tmp_path: pathlib.Path) -> None:
    """Inline manifest with <extend-project>: parsed model matches expectations.

    Writes an inline manifest directly to tmp_path, parses it, and verifies
    the parsed model reflects all applied extensions.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    fetch_url = "https://inline.example.com"
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{fetch_url}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core" path="core" />\n'
        '  <project name="vendor/lib" path="lib" />\n'
        '  <extend-project name="platform/core" groups="sdk,dev" />\n'
        '  <extend-project name="vendor/lib" revision="refs/tags/v0.9.0" upstream="refs/heads/main" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    projects = {p.name: p for p in manifest.projects}
    core = projects["platform/core"]
    assert "sdk" in core.groups, f"Expected 'sdk' in platform/core.groups after extend-project but got: {core.groups!r}"
    assert "dev" in core.groups, f"Expected 'dev' in platform/core.groups after extend-project but got: {core.groups!r}"

    lib = projects["vendor/lib"]
    assert lib.revisionExpr == "refs/tags/v0.9.0", (
        f"Expected vendor/lib revisionExpr='refs/tags/v0.9.0' after extend-project but got: {lib.revisionExpr!r}"
    )
    assert lib.upstream == "refs/heads/main", (
        f"Expected vendor/lib upstream='refs/heads/main' after extend-project but got: {lib.upstream!r}"
    )
