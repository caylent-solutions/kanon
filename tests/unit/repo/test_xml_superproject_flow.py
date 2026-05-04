"""Unit tests for the <superproject> element end-to-end parse flow.

Covers:
  AC-TEST-001  <superproject> with an explicit remote attribute parses
               correctly: the remote is resolved to the named remote, the
               superproject name is set, and the manifest model reflects the
               resolved remote object.
  AC-TEST-002  <superproject> inheriting remote from <default> parses
               correctly: when no remote attribute is given the parser falls
               back to the manifest default remote, and manifest.superproject
               reflects that inherited remote.
  AC-TEST-003  <superproject> with a tag revision (refs/tags/...) parses
               correctly: the tag-style revision string is stored verbatim on
               manifest.superproject.revision.
  AC-FUNC-001  The superproject element is parsed and integrated into the
               manifest model: after Load(), manifest.superproject is a
               Superproject instance with name, remote, and revision all
               populated from the XML.
  AC-CHANNEL-001  stdout vs stderr discipline: successful parses produce no
               stdout output; parse errors raise ManifestParseError, not
               stdout writes.

All tests are marked @pytest.mark.unit.
Tests use real manifest files written to tmp_path -- no mocking of parser
internals.

The flow scenarios covered here complement the attribute, crossref, and happy
tests for <superproject>. Each test class exercises one end-to-end parse
scenario as described in the AC definitions above.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- mirrors the pattern used in other test_xml_superproject_* files
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
# AC-TEST-001: <superproject> with explicit remote parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectExplicitRemoteFlow:
    """AC-TEST-001: <superproject> with an explicit remote attribute parses correctly.

    The explicit remote= attribute names a declared <remote> element. After
    parsing, manifest.superproject.name reflects the name attribute and
    manifest.superproject.remote reflects the resolved RemoteSpec for the
    named remote, not the default remote.
    """

    def test_explicit_remote_superproject_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <superproject> with remote= referencing a declared remote raises no error.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="infra" fetch="https://infra.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="infra" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            "AC-TEST-001: expected manifest.superproject to be set for explicit remote but got None"
        )

    def test_explicit_remote_superproject_name_is_correct(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The name attribute from <superproject> is stored verbatim in manifest.superproject.name.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="infra" fetch="https://infra.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="infra" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject.name == "platform/superproject", (
            f"AC-TEST-001: expected superproject.name='platform/superproject' but got: {manifest.superproject.name!r}"
        )

    def test_explicit_remote_superproject_remote_is_set(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing, manifest.superproject.remote is a non-None RemoteSpec object.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="infra" fetch="https://infra.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="infra" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject.remote is not None, (
            "AC-TEST-001: expected superproject.remote to be a RemoteSpec object but got None"
        )

    def test_explicit_remote_superproject_revision_inherited_from_default(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no revision attribute is given, the revision is inherited from <default>.

        AC-TEST-001: explicit-remote flow without explicit revision uses <default> revision.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="infra" fetch="https://infra.example.com" />\n'
            '  <default revision="refs/heads/main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="infra" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject.revision == "refs/heads/main", (
            f"AC-TEST-001: expected superproject.revision='refs/heads/main' inherited from "
            f"<default> when no revision attribute on <superproject>, but got: "
            f"{manifest.superproject.revision!r}"
        )

    @pytest.mark.parametrize(
        "superproject_name,remote_name",
        [
            ("platform/superproject", "infra"),
            ("android/superproject", "upstream"),
            ("org/mono-repo", "backup"),
        ],
    )
    def test_explicit_remote_various_name_and_remote_combinations(
        self,
        tmp_path: pathlib.Path,
        superproject_name: str,
        remote_name: str,
    ) -> None:
        """Parameterized: various name/remote combinations all parse correctly.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            f'  <remote name="{remote_name}" fetch="https://{remote_name}.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <superproject name="{superproject_name}" remote="{remote_name}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            f"AC-TEST-001: expected superproject to be set for name='{superproject_name}' "
            f"remote='{remote_name}' but got None"
        )
        assert manifest.superproject.name == superproject_name, (
            f"AC-TEST-001: expected superproject.name='{superproject_name}' but got: {manifest.superproject.name!r}"
        )
        assert manifest.superproject.remote is not None, (
            f"AC-TEST-001: expected superproject.remote to be set for remote='{remote_name}' but got None"
        )

    def test_explicit_remote_with_explicit_revision_flow(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An explicit remote combined with an explicit revision parses correctly.

        AC-TEST-001: the full explicit-attribute flow (both remote and revision specified).
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="infra" fetch="https://infra.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="infra"'
            ' revision="refs/heads/stable" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            "AC-TEST-001: expected superproject to be set for explicit remote+revision but got None"
        )
        assert manifest.superproject.name == "platform/superproject", (
            f"AC-TEST-001: expected superproject.name='platform/superproject' but got: {manifest.superproject.name!r}"
        )
        assert manifest.superproject.revision == "refs/heads/stable", (
            f"AC-TEST-001: expected superproject.revision='refs/heads/stable' but got: "
            f"{manifest.superproject.revision!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: <superproject> inheriting remote from <default> parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectInheritedRemoteFlow:
    """AC-TEST-002: <superproject> inheriting remote from <default> parses correctly.

    When no remote= attribute is present on <superproject>, the parser falls
    back to the manifest default remote (from the <default> element's remote
    attribute). The resulting manifest.superproject.remote is resolved from
    the default, not from an explicit attribute.
    """

    def test_inherited_remote_superproject_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <superproject> without remote= but with a <default remote=> parses without error.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            "AC-TEST-002: expected manifest.superproject to be set when remote is inherited from <default> but got None"
        )

    def test_inherited_remote_superproject_name_is_correct(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The name attribute is stored correctly when remote is inherited from <default>.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject.name == "platform/superproject", (
            f"AC-TEST-002: expected superproject.name='platform/superproject' but got: {manifest.superproject.name!r}"
        )

    def test_inherited_remote_superproject_remote_is_set(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing, manifest.superproject.remote is not None when inherited from default.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject.remote is not None, (
            "AC-TEST-002: expected superproject.remote to be resolved from <default> but got None"
        )

    def test_inherited_remote_superproject_revision_from_default(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When both remote and revision are inherited, both come from <default>.

        AC-TEST-002: full inherited-from-default flow.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="refs/heads/develop" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject.revision == "refs/heads/develop", (
            f"AC-TEST-002: expected superproject.revision='refs/heads/develop' inherited "
            f"from <default> but got: {manifest.superproject.revision!r}"
        )

    @pytest.mark.parametrize(
        "default_revision",
        [
            "main",
            "refs/heads/main",
            "refs/heads/develop",
            "refs/heads/release-1.0",
        ],
    )
    def test_inherited_remote_various_default_revisions(
        self,
        tmp_path: pathlib.Path,
        default_revision: str,
    ) -> None:
        """Parameterized: various <default> revision values are inherited by <superproject>.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            f'  <default revision="{default_revision}" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            f"AC-TEST-002: expected superproject to be set for default_revision='{default_revision}' but got None"
        )
        assert manifest.superproject.revision == default_revision, (
            f"AC-TEST-002: expected superproject.revision='{default_revision}' inherited "
            f"from <default> but got: {manifest.superproject.revision!r}"
        )

    def test_inherited_remote_no_default_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <default> remote exists and no remote= given, ManifestParseError is raised.

        AC-TEST-002: the inherited-remote flow requires that a default remote exists;
        when it does not, the parse fails fast with a clear error.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, (
            "AC-TEST-002: expected a non-empty ManifestParseError when no default remote "
            "is available for <superproject> inheritance but got an empty string"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <superproject> with tag revision parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectTagRevisionFlow:
    """AC-TEST-003: <superproject> with a tag revision parses correctly.

    Tag revisions use the refs/tags/... notation. The parser stores the
    revision verbatim on manifest.superproject.revision without modification.
    This test class verifies that tag-style revision strings are accepted and
    stored correctly in each combination: explicit tag revision, inherited
    tag revision (from <default>), and tag revision combined with explicit remote.
    """

    def test_tag_revision_superproject_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <superproject> with revision="refs/tags/v1.0.0" parses without error.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" revision="refs/tags/v1.0.0" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            "AC-TEST-003: expected manifest.superproject to be set for tag revision but got None"
        )

    def test_tag_revision_stored_verbatim_on_superproject(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The tag revision string is stored verbatim in manifest.superproject.revision.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" revision="refs/tags/v1.0.0" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject.revision == "refs/tags/v1.0.0", (
            f"AC-TEST-003: expected superproject.revision='refs/tags/v1.0.0' but got: "
            f"{manifest.superproject.revision!r}"
        )

    @pytest.mark.parametrize(
        "tag_revision",
        [
            "refs/tags/v1.0.0",
            "refs/tags/v2.3.1",
            "refs/tags/release-2024.01",
            "refs/tags/platform-4.19",
        ],
    )
    def test_various_tag_revision_formats_parse_correctly(
        self,
        tmp_path: pathlib.Path,
        tag_revision: str,
    ) -> None:
        """Parameterized: various refs/tags/... revision strings are stored correctly.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <superproject name="platform/superproject" revision="{tag_revision}" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            f"AC-TEST-003: expected superproject to be set for tag_revision='{tag_revision}' but got None"
        )
        assert manifest.superproject.revision == tag_revision, (
            f"AC-TEST-003: expected superproject.revision='{tag_revision}' but got: {manifest.superproject.revision!r}"
        )

    def test_tag_revision_from_default_element_inherited(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A tag revision set on <default> is inherited by <superproject> correctly.

        AC-TEST-003: the inherited-from-default flow works with tag-style revisions.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="refs/tags/v3.0.0" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            "AC-TEST-003: expected superproject to be set when tag revision is inherited from <default> but got None"
        )
        assert manifest.superproject.revision == "refs/tags/v3.0.0", (
            f"AC-TEST-003: expected superproject.revision='refs/tags/v3.0.0' inherited "
            f"from <default> but got: {manifest.superproject.revision!r}"
        )

    def test_explicit_tag_revision_overrides_default_branch_revision(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An explicit tag revision on <superproject> overrides a branch revision on <default>.

        AC-TEST-003: the explicit attribute always wins over the inherited value.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="refs/heads/main" remote="origin" />\n'
            '  <superproject name="platform/superproject" revision="refs/tags/v2.0.0" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject.revision == "refs/tags/v2.0.0", (
            f"AC-TEST-003: expected explicit tag revision 'refs/tags/v2.0.0' to override "
            f"<default> branch revision but got: {manifest.superproject.revision!r}"
        )

    def test_tag_revision_with_explicit_remote_flow(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A tag revision combined with an explicit remote parses correctly.

        AC-TEST-003: verifies the combination of explicit remote and tag revision.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="releases" fetch="https://releases.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="releases"'
            ' revision="refs/tags/v5.0.0" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            "AC-TEST-003: expected superproject to be set for tag revision + explicit remote flow but got None"
        )
        assert manifest.superproject.name == "platform/superproject", (
            f"AC-TEST-003: expected superproject.name='platform/superproject' but got: {manifest.superproject.name!r}"
        )
        assert manifest.superproject.revision == "refs/tags/v5.0.0", (
            f"AC-TEST-003: expected superproject.revision='refs/tags/v5.0.0' but got: "
            f"{manifest.superproject.revision!r}"
        )
        assert manifest.superproject.remote is not None, (
            "AC-TEST-003: expected superproject.remote to be set for explicit remote but got None"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Superproject element parsed and integrated into manifest model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectManifestModelIntegration:
    """AC-FUNC-001: The superproject element is parsed and integrated into the manifest model.

    After Load(), manifest.superproject is a Superproject instance with all
    fields populated. This class verifies the integration between the XML
    parser and the manifest model for various representative parse flows.
    """

    def test_superproject_is_superproject_instance_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """manifest.superproject is a Superproject object (not a dict or raw XML node).

        AC-FUNC-001
        """
        from kanon_cli.repo.git_superproject import Superproject

        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert isinstance(manifest.superproject, Superproject), (
            f"AC-FUNC-001: expected manifest.superproject to be a Superproject instance "
            f"but got: {type(manifest.superproject)!r}"
        )

    def test_superproject_model_has_all_fields_populated(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After Load(), manifest.superproject has name, remote, and revision all set.

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="refs/heads/main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject.name == "platform/superproject", (
            f"AC-FUNC-001: expected superproject.name='platform/superproject' but got: {manifest.superproject.name!r}"
        )
        assert manifest.superproject.remote is not None, (
            "AC-FUNC-001: expected superproject.remote to be set but got None"
        )
        assert manifest.superproject.revision == "refs/heads/main", (
            f"AC-FUNC-001: expected superproject.revision='refs/heads/main' but got: {manifest.superproject.revision!r}"
        )

    def test_manifest_superproject_is_none_when_element_absent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <superproject> element is present, manifest.superproject is None.

        AC-FUNC-001: the manifest model represents absence as None.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is None, (
            f"AC-FUNC-001: expected manifest.superproject=None when <superproject> is "
            f"absent but got: {manifest.superproject!r}"
        )

    def test_superproject_integrated_with_explicit_remote_and_tag(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """All three attributes explicit -- manifest model reflects all three after Load().

        AC-FUNC-001: integration test combining explicit remote + explicit tag revision.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="releases" fetch="https://releases.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="android/superproject" remote="releases"'
            ' revision="refs/tags/android-14.0.0" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.superproject is not None, (
            "AC-FUNC-001: expected superproject to be set for full explicit flow but got None"
        )
        assert manifest.superproject.name == "android/superproject", (
            f"AC-FUNC-001: expected superproject.name='android/superproject' but got: {manifest.superproject.name!r}"
        )
        assert manifest.superproject.remote is not None, (
            "AC-FUNC-001: expected superproject.remote to be set but got None"
        )
        assert manifest.superproject.revision == "refs/tags/android-14.0.0", (
            f"AC-FUNC-001: expected superproject.revision='refs/tags/android-14.0.0' but got: "
            f"{manifest.superproject.revision!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectFlowChannelDiscipline:
    """AC-CHANNEL-001: parse errors raise ManifestParseError; stdout is never written.

    For XML / parser tasks, stdout discipline means:
    - Successful parse produces no output and raises no exception.
    - Failed parse raises ManifestParseError (not writes to stdout).
    """

    def test_explicit_remote_flow_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Parsing <superproject> with an explicit remote produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="infra" fetch="https://infra.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="infra" />\n'
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for explicit-remote superproject parse but got: {captured.out!r}"
        )

    def test_inherited_remote_flow_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Parsing <superproject> with inherited remote produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for inherited-remote superproject parse but got: {captured.out!r}"
        )

    def test_tag_revision_flow_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Parsing <superproject> with a tag revision produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" revision="refs/tags/v1.0.0" />\n'
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for tag-revision superproject parse but got: {captured.out!r}"
        )

    def test_no_default_remote_raises_not_prints(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """When no default remote exists, ManifestParseError is raised; stdout is empty.

        AC-CHANNEL-001: error flow uses exceptions, not stdout writes.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when ManifestParseError is raised "
            f"for missing default remote but got: {captured.out!r}"
        )
        assert str(exc_info.value), (
            "AC-CHANNEL-001: expected a non-empty ManifestParseError message but got empty string"
        )
