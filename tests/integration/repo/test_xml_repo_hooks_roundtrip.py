"""Integration tests for <repo-hooks> round-trip parsing.

Tests parse a real manifest XML file from disk containing a <repo-hooks>
element, verify the parsed model reflects the hooks configuration, and
confirm round-trip serialization via ToXml preserves the expected
structural elements.

All tests use real manifest files written to tmp_path. No network or
subprocess calls are made -- these are real file-system operations.
All tests are marked @pytest.mark.integration.

AC-FUNC-001: The happy-path <repo-hooks> parses without error and the
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


def _build_hooks_manifest(
    hooks_project: str = "tools/hooks",
    hooks_path: str = "hooks",
    enabled_list: str = "pre-upload",
) -> str:
    """Build a manifest XML string with a hooks project and repo-hooks element.

    Args:
        hooks_project: Name of the project that owns hooks.
        hooks_path: Path for the hooks project.
        enabled_list: Space or comma-separated list of hook names.

    Returns:
        Full XML string for the manifest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        f'  <project name="{hooks_project}" path="{hooks_path}" />\n'
        f'  <repo-hooks in-project="{hooks_project}" enabled-list="{enabled_list}" />\n'
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 + AC-FINAL-010: Parse + round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_repo_hooks_parses_without_error(tmp_path: pathlib.Path) -> None:
    """A manifest with <repo-hooks> parses into a valid XmlManifest without error.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_hooks_manifest(
        hooks_project="tools/hooks",
        enabled_list="pre-upload",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest is not None, "Expected XmlManifest instance but got None after loading"


@pytest.mark.integration
def test_repo_hooks_project_set_after_parse(tmp_path: pathlib.Path) -> None:
    """After parsing, manifest.repo_hooks_project is the expected Project object.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_hooks_manifest(
        hooks_project="tools/hooks",
        enabled_list="pre-upload",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.repo_hooks_project is not None, "Expected manifest.repo_hooks_project to be set but got None"
    assert manifest.repo_hooks_project.name == "tools/hooks", (
        f"Expected repo_hooks_project.name='tools/hooks' but got: {manifest.repo_hooks_project.name!r}"
    )


@pytest.mark.integration
def test_repo_hooks_enabled_repo_hooks_contains_hook(tmp_path: pathlib.Path) -> None:
    """After parsing, enabled_repo_hooks on the hooks project contains the enabled hook.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_hooks_manifest(
        hooks_project="tools/hooks",
        enabled_list="pre-upload",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert "pre-upload" in manifest.repo_hooks_project.enabled_repo_hooks, (
        f"Expected 'pre-upload' in enabled_repo_hooks but got: {manifest.repo_hooks_project.enabled_repo_hooks!r}"
    )


@pytest.mark.integration
def test_repo_hooks_roundtrip_preserves_repo_hooks_element(tmp_path: pathlib.Path) -> None:
    """Round-trip: ToXml output contains a <repo-hooks> element.

    Parses a manifest with repo-hooks, calls ToXml(), and verifies the
    resulting XML document contains exactly one <repo-hooks> element.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_hooks_manifest(
        hooks_project="tools/hooks",
        enabled_list="pre-upload",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    repo_hooks_elements = [n for n in root.childNodes if n.nodeName == "repo-hooks"]
    assert len(repo_hooks_elements) == 1, (
        f"Expected exactly 1 <repo-hooks> element in round-trip XML but found: {len(repo_hooks_elements)}"
    )


@pytest.mark.integration
def test_repo_hooks_roundtrip_in_project_attribute_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: the in-project attribute on <repo-hooks> is preserved in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_hooks_manifest(
        hooks_project="tools/hooks",
        enabled_list="pre-upload",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    repo_hooks_elements = [n for n in root.childNodes if n.nodeName == "repo-hooks"]
    assert len(repo_hooks_elements) == 1, (
        f"Expected exactly 1 <repo-hooks> element in round-trip XML but found: {len(repo_hooks_elements)}"
    )
    assert repo_hooks_elements[0].getAttribute("in-project") == "tools/hooks", (
        f"Expected in-project='tools/hooks' in round-trip XML but got: "
        f"{repo_hooks_elements[0].getAttribute('in-project')!r}"
    )


@pytest.mark.integration
def test_repo_hooks_roundtrip_enabled_list_attribute_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: the enabled-list attribute on <repo-hooks> is preserved in ToXml output.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_hooks_manifest(
        hooks_project="tools/hooks",
        enabled_list="pre-upload",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    repo_hooks_elements = [n for n in root.childNodes if n.nodeName == "repo-hooks"]
    assert len(repo_hooks_elements) == 1, (
        f"Expected exactly 1 <repo-hooks> element in round-trip XML but found: {len(repo_hooks_elements)}"
    )
    enabled_list = repo_hooks_elements[0].getAttribute("enabled-list")
    assert "pre-upload" in enabled_list, (
        f"Expected 'pre-upload' in round-trip enabled-list attribute but got: {enabled_list!r}"
    )


@pytest.mark.integration
def test_repo_hooks_roundtrip_multiple_hooks_preserved(tmp_path: pathlib.Path) -> None:
    """Round-trip: multiple hooks in enabled-list are all preserved after ToXml.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_hooks_manifest(
        hooks_project="tools/hooks",
        enabled_list="pre-upload commit-msg",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    repo_hooks_elements = [n for n in root.childNodes if n.nodeName == "repo-hooks"]
    assert len(repo_hooks_elements) == 1, (
        f"Expected exactly 1 <repo-hooks> element in round-trip XML but found: {len(repo_hooks_elements)}"
    )
    enabled_list = repo_hooks_elements[0].getAttribute("enabled-list")
    assert "pre-upload" in enabled_list, f"Expected 'pre-upload' in round-trip enabled-list but got: {enabled_list!r}"
    assert "commit-msg" in enabled_list, f"Expected 'commit-msg' in round-trip enabled-list but got: {enabled_list!r}"


@pytest.mark.integration
def test_repo_hooks_roundtrip_no_repo_hooks_when_absent(tmp_path: pathlib.Path) -> None:
    """Round-trip: no <repo-hooks> element in ToXml output when none was parsed.

    A manifest without a <repo-hooks> element must produce ToXml output that
    also has no <repo-hooks> element.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="tools/hooks" path="hooks" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    repo_hooks_elements = [n for n in root.childNodes if n.nodeName == "repo-hooks"]
    assert len(repo_hooks_elements) == 0, (
        f"Expected no <repo-hooks> elements in round-trip XML when none was present "
        f"but found: {len(repo_hooks_elements)}"
    )


@pytest.mark.integration
def test_repo_hooks_roundtrip_model_matches_parsed_data(tmp_path: pathlib.Path) -> None:
    """Round-trip: the parsed model repo_hooks_project matches what was written to disk.

    Writes a manifest with a specific hooks project name and hook list,
    parses it, and asserts that the parsed model attributes match the XML.

    AC-FUNC-001, AC-FINAL-010
    """
    hooks_project_name = "platform/repo-hooks"
    hook_names = ["pre-upload", "commit-msg", "post-checkout"]

    repodir = _make_repo_dir(tmp_path)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        f'  <project name="{hooks_project_name}" path="repo-hooks" />\n'
        f'  <repo-hooks in-project="{hooks_project_name}"'
        f' enabled-list="{" ".join(hook_names)}" />\n'
        "</manifest>\n"
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)

    assert manifest.repo_hooks_project is not None, "Expected manifest.repo_hooks_project to be set but got None"
    assert manifest.repo_hooks_project.name == hooks_project_name, (
        f"Expected repo_hooks_project.name='{hooks_project_name}' but got: {manifest.repo_hooks_project.name!r}"
    )
    for hook in hook_names:
        assert hook in manifest.repo_hooks_project.enabled_repo_hooks, (
            f"Expected '{hook}' in enabled_repo_hooks but got: {manifest.repo_hooks_project.enabled_repo_hooks!r}"
        )


@pytest.mark.integration
def test_repo_hooks_roundtrip_project_also_in_projects_list(tmp_path: pathlib.Path) -> None:
    """Round-trip: the hooks project appears in ToXml output as a regular <project> element.

    AC-FUNC-001, AC-FINAL-010
    """
    repodir = _make_repo_dir(tmp_path)
    xml_content = _build_hooks_manifest(
        hooks_project="tools/hooks",
        enabled_list="pre-upload",
    )
    manifest_file = _write_manifest(repodir, xml_content)

    manifest = _load_manifest(repodir, manifest_file)
    doc = manifest.ToXml()
    root = doc.documentElement

    project_elements = [n for n in root.childNodes if n.nodeName == "project"]
    project_names_in_xml = [e.getAttribute("name") for e in project_elements]
    assert "tools/hooks" in project_names_in_xml, (
        f"Expected 'tools/hooks' in round-trip <project> elements but got: {project_names_in_xml!r}"
    )
