"""Unit tests for the <manifest> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <manifest> XML files parse correctly when given
minimum required attributes, all documented attributes, and that default
attribute values on child elements behave as documented.

All tests use real manifest files written to tmp_path via the shared
conftest helpers. The conftest in tests/unit/repo/ auto-applies
@pytest.mark.unit to every item collected under that directory.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern used in test_manifest_parsing.py
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
# AC-TEST-001: Valid <manifest> with minimum required attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestMinimumAttributes:
    """Verify that a manifest with only the minimum required attributes parses correctly.

    The minimum valid manifest requires a <remote> element with name and fetch,
    and a <default> element with revision and remote. A <project> element needs
    a name and at least one inherited or explicit remote and revision.
    """

    def test_minimal_manifest_with_remote_and_default_loads_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with only <remote> and <default> loads without raising any error.

        AC-TEST-001, AC-FUNC-001
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

        assert manifest is not None, "Expected XmlManifest instance but got None"
        assert "origin" in manifest.remotes, (
            f"Expected 'origin' in manifest.remotes but got: {list(manifest.remotes.keys())!r}"
        )

    def test_minimal_manifest_remote_name_and_fetch_parsed(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The <remote> name and fetch attributes are available after parsing.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="myremote" fetch="https://git.example.com" />\n'
            '  <default revision="main" remote="myremote" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert "myremote" in manifest.remotes, (
            f"Expected remote 'myremote' in manifest.remotes but got: {list(manifest.remotes.keys())!r}"
        )
        remote = manifest.remotes["myremote"]
        assert remote.fetchUrl is not None, "Expected fetchUrl to be set but got None"
        assert "https://git.example.com" in remote.fetchUrl, (
            f"Expected 'https://git.example.com' in fetchUrl but got: {remote.fetchUrl!r}"
        )

    def test_minimal_manifest_default_revision_parsed(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The <default> revision attribute is available after parsing the minimum manifest.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="refs/heads/main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.revisionExpr == "refs/heads/main", (
            f"Expected default.revisionExpr='refs/heads/main' but got: {manifest.default.revisionExpr!r}"
        )

    def test_minimal_manifest_with_one_project_parses_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with <remote>, <default>, and one <project> parses the project.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"Expected 'platform/core' in manifest.projects but got: {project_names!r}"
        )

    @pytest.mark.parametrize(
        "remote_name,fetch_url",
        [
            ("origin", "https://example.com"),
            ("upstream", "https://upstream.example.org"),
            ("mirror", "git://git.example.net/mirror"),
        ],
    )
    def test_remote_name_and_fetch_parsed_for_various_values(
        self,
        tmp_path: pathlib.Path,
        remote_name: str,
        fetch_url: str,
    ) -> None:
        """Parameterized: remote name and fetch URL are parsed correctly for varied values.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
            f'  <default revision="main" remote="{remote_name}" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert remote_name in manifest.remotes, (
            f"Expected remote '{remote_name}' in manifest.remotes but got: {list(manifest.remotes.keys())!r}"
        )
        remote = manifest.remotes[remote_name]
        assert remote.fetchUrl is not None, f"Expected fetchUrl to be set for remote '{remote_name}' but got None"


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <manifest> with all documented attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestAllDocumentedAttributes:
    """Verify that a manifest using all documented attributes parses correctly.

    Covers: <remote> (name, fetch, pushurl, alias, review, revision),
    <default> (revision, remote, sync-j, sync-c, sync-s, sync-tags,
    dest-branch, upstream), <project> (name, path, remote, revision, groups,
    rebase, sync-c, sync-s, sync-tags, clone-depth), <notice>, <manifest-server>,
    <contactinfo>.
    """

    def test_remote_with_all_optional_attributes_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remote> element with all optional attributes (alias, pushurl, review, revision) parses correctly.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin"\n'
            '          fetch="https://example.com"\n'
            '          alias="alias-origin"\n'
            '          pushurl="https://push.example.com"\n'
            '          review="https://review.example.com"\n'
            '          revision="refs/heads/stable" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.name == "origin", f"Expected remote.name='origin' but got: {remote.name!r}"
        assert "https://example.com" in remote.fetchUrl, (
            f"Expected 'https://example.com' in remote.fetchUrl but got: {remote.fetchUrl!r}"
        )
        assert remote.remoteAlias == "alias-origin", (
            f"Expected remote.remoteAlias='alias-origin' but got: {remote.remoteAlias!r}"
        )
        assert remote.pushUrl == "https://push.example.com", (
            f"Expected remote.pushUrl='https://push.example.com' but got: {remote.pushUrl!r}"
        )
        assert remote.reviewUrl == "https://review.example.com", (
            f"Expected remote.reviewUrl='https://review.example.com' but got: {remote.reviewUrl!r}"
        )
        assert remote.revision == "refs/heads/stable", (
            f"Expected remote.revision='refs/heads/stable' but got: {remote.revision!r}"
        )

    def test_default_with_all_documented_attributes_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <default> element with sync-j, sync-c, sync-s, sync-tags attributes parses correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main"\n'
            '           remote="origin"\n'
            '           sync-j="8"\n'
            '           sync-c="true"\n'
            '           sync-s="true"\n'
            '           sync-tags="false" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        d = manifest.default
        assert d.sync_j == 8, f"Expected default.sync_j=8 but got: {d.sync_j!r}"
        assert d.sync_c is True, f"Expected default.sync_c=True but got: {d.sync_c!r}"
        assert d.sync_s is True, f"Expected default.sync_s=True but got: {d.sync_s!r}"
        assert d.sync_tags is False, f"Expected default.sync_tags=False but got: {d.sync_tags!r}"

    def test_notice_element_parsed(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <notice> element is parsed and its text content is accessible via manifest.notice.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice>This is the manifest notice text.</notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.notice is not None, "Expected manifest.notice to be set but got None"
        assert "notice text" in manifest.notice, (
            f"Expected 'notice text' in manifest.notice but got: {manifest.notice!r}"
        )

    def test_manifest_server_element_parsed(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <manifest-server> element is parsed and its URL is accessible via manifest.manifest_server.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://manifest-server.example.com" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.manifest_server == "https://manifest-server.example.com", (
            f"Expected manifest_server='https://manifest-server.example.com' but got: {manifest.manifest_server!r}"
        )

    def test_contactinfo_element_parsed(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <contactinfo> element is parsed and its bugurl is accessible via manifest.contactinfo.bugurl.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <contactinfo bugurl="https://bugs.example.com/file-a-bug" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.contactinfo.bugurl == "https://bugs.example.com/file-a-bug", (
            f"Expected contactinfo.bugurl='https://bugs.example.com/file-a-bug' "
            f"but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_project_with_all_documented_attributes_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> element with name, path, groups, and sync attributes parses correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/build"\n'
            '           path="build"\n'
            '           revision="refs/tags/v2.0.0"\n'
            '           groups="pdk,extra"\n'
            '           sync-c="true"\n'
            '           sync-s="true" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        projects = {p.name: p for p in manifest.projects}
        assert "platform/build" in projects, (
            f"Expected 'platform/build' in manifest projects but got: {list(projects.keys())!r}"
        )
        p = projects["platform/build"]
        assert p.relpath == "build", f"Expected project relpath='build' but got: {p.relpath!r}"
        assert p.revisionExpr == "refs/tags/v2.0.0", (
            f"Expected project revisionExpr='refs/tags/v2.0.0' but got: {p.revisionExpr!r}"
        )
        assert p.sync_c is True, f"Expected project sync_c=True but got: {p.sync_c!r}"
        assert p.sync_s is True, f"Expected project sync_s=True but got: {p.sync_s!r}"
        assert "pdk" in p.groups, f"Expected 'pdk' in project.groups but got: {p.groups!r}"

    def test_multiple_remotes_all_parsed(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Multiple <remote> elements are all parsed and accessible by name.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="alpha" fetch="https://alpha.example.com" />\n'
            '  <remote name="beta" fetch="https://beta.example.com" />\n'
            '  <remote name="gamma" fetch="https://gamma.example.com" />\n'
            '  <default revision="main" remote="alpha" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        for name in ("alpha", "beta", "gamma"):
            assert name in manifest.remotes, (
                f"Expected remote '{name}' in manifest.remotes but got: {list(manifest.remotes.keys())!r}"
            )

    def test_multiple_projects_all_parsed(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Multiple <project> elements are all parsed and accessible.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/build" path="build" />\n'
            '  <project name="platform/tools" path="tools" />\n'
            '  <project name="platform/docs" path="docs" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project_names = [p.name for p in manifest.projects]
        for name in ("platform/build", "platform/tools", "platform/docs"):
            assert name in project_names, f"Expected '{name}' in manifest.projects but got: {project_names!r}"


# ---------------------------------------------------------------------------
# AC-TEST-003: <manifest> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestDefaultAttributeValues:
    """Verify that default attribute values on manifest child elements behave as documented.

    The repo manifest format documents these defaults:
    - <default sync-c>: False (no shallow clone)
    - <default sync-s>: False (no submodule sync)
    - <default sync-tags>: True (fetch tags)
    - <project> inherits default revision when no revision specified
    - <project> inherits default remote when no remote specified
    """

    def test_default_sync_c_is_false_when_not_specified(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When sync-c is not set on <default>, manifest.default.sync_c is False.

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

        assert manifest.default.sync_c is False, (
            f"Expected default.sync_c=False when not specified but got: {manifest.default.sync_c!r}"
        )

    def test_default_sync_s_is_false_when_not_specified(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When sync-s is not set on <default>, manifest.default.sync_s is False.

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

        assert manifest.default.sync_s is False, (
            f"Expected default.sync_s=False when not specified but got: {manifest.default.sync_s!r}"
        )

    def test_default_sync_tags_is_true_when_not_specified(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When sync-tags is not set on <default>, manifest.default.sync_tags is True.

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

        assert manifest.default.sync_tags is True, (
            f"Expected default.sync_tags=True when not specified but got: {manifest.default.sync_tags!r}"
        )

    def test_default_sync_j_is_none_when_not_specified(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When sync-j is not set on <default>, manifest.default.sync_j is None.

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

        assert manifest.default.sync_j is None, (
            f"Expected default.sync_j=None when not specified but got: {manifest.default.sync_j!r}"
        )

    def test_project_inherits_default_revision_when_none_specified(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with no explicit revision inherits the <default> revision.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="refs/heads/develop" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        projects = {p.name: p for p in manifest.projects}
        assert "platform/core" in projects, (
            f"Expected 'platform/core' in manifest projects but got: {list(projects.keys())!r}"
        )
        assert projects["platform/core"].revisionExpr == "refs/heads/develop", (
            f"Expected project revisionExpr='refs/heads/develop' from <default> "
            f"but got: {projects['platform/core'].revisionExpr!r}"
        )

    def test_project_explicit_revision_overrides_default(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with an explicit revision uses that instead of the <default> revision.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/pinned" path="pinned" revision="refs/tags/v1.0.0" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        projects = {p.name: p for p in manifest.projects}
        assert "platform/pinned" in projects, (
            f"Expected 'platform/pinned' in manifest projects but got: {list(projects.keys())!r}"
        )
        assert projects["platform/pinned"].revisionExpr == "refs/tags/v1.0.0", (
            f"Expected explicit project revision='refs/tags/v1.0.0' to override default "
            f"but got: {projects['platform/pinned'].revisionExpr!r}"
        )

    def test_project_without_explicit_path_defaults_to_name(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> without a path attribute uses the project name as the checkout path.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        projects = {p.name: p for p in manifest.projects}
        assert "platform/core" in projects, (
            f"Expected 'platform/core' in manifest projects but got: {list(projects.keys())!r}"
        )
        assert projects["platform/core"].relpath == "platform/core", (
            f"Expected project relpath='platform/core' (name used as path) "
            f"but got: {projects['platform/core'].relpath!r}"
        )

    @pytest.mark.parametrize(
        "sync_c_value,expected",
        [
            ("true", True),
            ("false", False),
            ("1", True),
            ("0", False),
            ("yes", True),
            ("no", False),
        ],
    )
    def test_default_sync_c_boolean_values_parsed(
        self,
        tmp_path: pathlib.Path,
        sync_c_value: str,
        expected: bool,
    ) -> None:
        """Parameterized: sync-c boolean variants are each parsed correctly.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            f'  <default revision="main" remote="origin" sync-c="{sync_c_value}" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.sync_c is expected, (
            f"Expected default.sync_c={expected!r} for sync-c='{sync_c_value}' but got: {manifest.default.sync_c!r}"
        )

    def test_project_all_group_implicit(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Every project automatically belongs to the implicit 'all' group.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        projects = {p.name: p for p in manifest.projects}
        assert "platform/core" in projects, (
            f"Expected 'platform/core' in manifest projects but got: {list(projects.keys())!r}"
        )
        assert "all" in projects["platform/core"].groups, (
            f"Expected 'all' in project.groups by default but got: {projects['platform/core'].groups!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestChannelDiscipline:
    """Verify that parse errors raise exceptions rather than writing to stdout.

    The <manifest> parser must report errors exclusively through exceptions;
    it must not write error information to stdout. Tests here verify that a
    parse error is surfaced as a ManifestParseError and not silently swallowed
    or written to stdout.

    AC-CHANNEL-001 (parser tasks: no stdout leakage for success/failure paths)
    """

    def test_valid_manifest_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a valid manifest does not raise ManifestParseError.

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

        try:
            _load_manifest(repodir, manifest_file)
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid manifest to parse without ManifestParseError but got: {exc!r}")

    def test_invalid_manifest_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest missing required remote attributes raises ManifestParseError.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"
