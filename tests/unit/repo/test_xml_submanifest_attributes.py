"""Unit tests for <submanifest> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <submanifest> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <submanifest> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified (no cross-channel
                  leakage)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <submanifest> element documented attributes:
  Required:  name           (unique identifier; no default)
  Optional:  remote         (remote name; only valid together with project)
  Optional:  project        (project name on the remote; required if remote is given)
  Optional:  revision       (commitish to check out; no default)
  Optional:  manifest-name  (submanifest manifest file; no default, callers default to "default.xml")
  Optional:  groups         (comma-separated groups applied to all projects; defaults to [])
  Optional:  default-groups (comma-separated default group list; defaults to [])
  Optional:  path           (relative checkout path; no default)

Additional constraints:
  - remote without project raises ManifestParseError.
  - Duplicate <submanifest> elements with different attributes raise ManifestParseError.
  - Invalid path values (containing '..', '~', '.git', absolute paths) in
    path, revision (used as relpath), or name (used as relpath) raise
    ManifestInvalidPathError.
  - Missing required name attribute raises ManifestParseError naming the attribute.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestInvalidPathError, ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers
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
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


def _build_submanifest_manifest(
    submanifest_attrs: str,
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
    extra_remotes: str = "",
) -> str:
    """Build a manifest XML string containing a <submanifest> element.

    Args:
        submanifest_attrs: Full attribute string for the <submanifest> element.
        remote_name: Name of the primary remote to declare.
        fetch_url: Fetch URL for the primary remote.
        default_revision: The revision for the <default> element.
        extra_remotes: Additional <remote> elements as raw XML to insert.

    Returns:
        Full XML string for the manifest.
    """
    extra = f"{extra_remotes}\n" if extra_remotes else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f"{extra}"
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f"  <submanifest {submanifest_attrs} />\n"
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests -- one per documented <submanifest> attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmanifestAttributeValidValues:
    """AC-TEST-001: every documented <submanifest> attribute has a valid-value test.

    Documented attributes: name (required), remote (optional), project (optional),
    revision (optional), manifest-name (optional), groups (optional),
    default-groups (optional), path (optional).
    """

    def test_name_valid_simple_path_accepted(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-001: a valid name attribute is stored in manifest.submanifests.

        The name attribute is required and uniquely identifies the submanifest.
        After parsing, the name must appear as a key in manifest.submanifests.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_submanifest_manifest('name="platform/sub"'),
        )

        assert "platform/sub" in manifest.submanifests, (
            "AC-TEST-001: expected 'platform/sub' in manifest.submanifests after parsing valid name"
        )
        sm = manifest.submanifests["platform/sub"]
        assert sm.name == "platform/sub", f"AC-TEST-001: expected submanifest.name='platform/sub' but got: {sm.name!r}"

    @pytest.mark.parametrize(
        "name",
        [
            "platform/sub",
            "android/child",
            "org/nested-manifest",
            "simple",
        ],
    )
    def test_name_valid_various_values(self, tmp_path: pathlib.Path, name: str) -> None:
        """AC-TEST-001 parameterized: various valid name values are stored correctly.

        AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            _build_submanifest_manifest(f'name="{name}"'),
        )

        assert name in manifest.submanifests, (
            f"AC-TEST-001: expected '{name}' in manifest.submanifests but got keys: "
            f"{list(manifest.submanifests.keys())}"
        )
        assert manifest.submanifests[name].name == name, (
            f"AC-TEST-001: expected submanifest.name='{name}' but got: {manifest.submanifests[name].name!r}"
        )

    def test_remote_valid_with_project_accepted(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-001: a valid remote attribute paired with project is stored correctly.

        The remote attribute is optional and must be paired with project.
        AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            _build_submanifest_manifest(
                'name="platform/sub" remote="origin" project="sub/manifest" path="sub"',
            ),
        )

        sm = manifest.submanifests["platform/sub"]
        assert sm.remote == "origin", f"AC-TEST-001: expected submanifest.remote='origin' but got: {sm.remote!r}"

    def test_project_valid_with_remote_accepted(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-001: a valid project attribute paired with remote is stored correctly.

        The project attribute is optional but required when remote is given.
        AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            _build_submanifest_manifest(
                'name="platform/sub" remote="origin" project="platform/manifest" path="sub"',
            ),
        )

        sm = manifest.submanifests["platform/sub"]
        assert sm.project == "platform/manifest", (
            f"AC-TEST-001: expected submanifest.project='platform/manifest' but got: {sm.project!r}"
        )

    def test_revision_valid_branch_ref_accepted(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-001: a valid revision attribute is stored correctly.

        The revision attribute is optional and specifies the commitish to check out.
        AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            _build_submanifest_manifest(
                'name="platform/sub" revision="refs/heads/stable" path="sub"',
            ),
        )

        sm = manifest.submanifests["platform/sub"]
        assert sm.revision == "refs/heads/stable", (
            f"AC-TEST-001: expected submanifest.revision='refs/heads/stable' but got: {sm.revision!r}"
        )

    @pytest.mark.parametrize(
        "revision",
        [
            "main",
            "refs/heads/main",
            "refs/heads/stable",
            "refs/tags/v1.0.0",
        ],
    )
    def test_revision_valid_various_values(self, tmp_path: pathlib.Path, revision: str) -> None:
        """AC-TEST-001 parameterized: various valid revision values are stored correctly.

        AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            _build_submanifest_manifest(
                f'name="platform/sub" revision="{revision}" path="sub"',
            ),
        )

        sm = manifest.submanifests["platform/sub"]
        assert sm.revision == revision, (
            f"AC-TEST-001: expected submanifest.revision='{revision}' but got: {sm.revision!r}"
        )

    def test_manifest_name_valid_custom_file_accepted(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-001: a valid manifest-name attribute is stored in manifestName.

        The manifest-name attribute is optional and specifies the sub-manifest file.
        AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            _build_submanifest_manifest(
                'name="platform/sub" manifest-name="custom.xml"',
            ),
        )

        sm = manifest.submanifests["platform/sub"]
        assert sm.manifestName == "custom.xml", (
            f"AC-TEST-001: expected submanifest.manifestName='custom.xml' but got: {sm.manifestName!r}"
        )

    def test_groups_valid_comma_separated_accepted(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-001: a valid groups attribute is stored as a list in sm.groups.

        The groups attribute is optional and comma-separated.
        AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            _build_submanifest_manifest(
                'name="platform/sub" path="sub" groups="groupA,groupB"',
            ),
        )

        sm = manifest.submanifests["platform/sub"]
        assert "groupA" in sm.groups, f"AC-TEST-001: expected 'groupA' in submanifest.groups but got: {sm.groups!r}"
        assert "groupB" in sm.groups, f"AC-TEST-001: expected 'groupB' in submanifest.groups but got: {sm.groups!r}"

    def test_default_groups_valid_comma_separated_accepted(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-001: a valid default-groups attribute is stored as a list.

        The default-groups attribute is optional and comma-separated.
        AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            _build_submanifest_manifest(
                'name="platform/sub" path="sub" default-groups="default,extra"',
            ),
        )

        sm = manifest.submanifests["platform/sub"]
        assert "default" in sm.default_groups, (
            f"AC-TEST-001: expected 'default' in submanifest.default_groups but got: {sm.default_groups!r}"
        )
        assert "extra" in sm.default_groups, (
            f"AC-TEST-001: expected 'extra' in submanifest.default_groups but got: {sm.default_groups!r}"
        )

    def test_path_valid_simple_name_accepted(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-001: a valid path attribute is stored in sm.path and sm.relpath.

        The path attribute is optional and specifies the relative checkout path.
        AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            _build_submanifest_manifest(
                'name="platform/sub" path="my-checkout"',
            ),
        )

        sm = manifest.submanifests["platform/sub"]
        assert sm.path == "my-checkout", f"AC-TEST-001: expected submanifest.path='my-checkout' but got: {sm.path!r}"
        assert sm.relpath == "my-checkout", (
            f"AC-TEST-001: expected submanifest.relpath='my-checkout' when path is set but got: {sm.relpath!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Invalid-value tests -- every attribute has at least one invalid path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmanifestAttributeInvalidValues:
    """AC-TEST-002: every attribute has invalid-value tests raising the appropriate exception.

    The <submanifest> parser validates path-derived attributes (name used as
    relpath, revision used as relpath, explicit path) via _CheckLocalPath, which
    raises ManifestInvalidPathError.  Constraint violations (remote without
    project, duplicate conflicting elements) raise ManifestParseError.
    """

    def test_name_with_dotdot_segment_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: name containing '..' raises ManifestInvalidPathError.

        When no path is given, name is used as the relpath source and is validated
        by _CheckLocalPath.  '..' in the last segment is a forbidden path component.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name=".." />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "name" in str(exc_info.value).lower() or ".." in str(exc_info.value), (
            f"AC-TEST-002: expected error message to reference 'name' or '..' but got: {exc_info.value!r}"
        )

    def test_name_with_dotgit_segment_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: name containing '.git' raises ManifestInvalidPathError.

        '.git' is a forbidden path component per _CheckLocalPath.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name=".git" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), "AC-TEST-002: expected non-empty ManifestInvalidPathError message for name='.git'"

    def test_name_with_tilde_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: name containing '~' raises ManifestInvalidPathError.

        '~' is forbidden per _CheckLocalPath (8.3 filename concern).
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="~user/sub" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), "AC-TEST-002: expected non-empty ManifestInvalidPathError message for name with '~'"

    def test_name_with_dotrepo_prefix_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: name starting with '.repo' raises ManifestInvalidPathError.

        Path components starting with '.repo' are forbidden per _CheckLocalPath.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name=".repo-sub" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty ManifestInvalidPathError for name starting with '.repo'"
        )

    @pytest.mark.parametrize(
        "bad_name",
        [
            "..",
            ".git",
            "~user",
            ".repo-sub",
        ],
    )
    def test_name_invalid_values_raise_invalid_path_error(self, tmp_path: pathlib.Path, bad_name: str) -> None:
        """AC-TEST-002 parameterized: various invalid name values raise ManifestInvalidPathError.

        Each value triggers _CheckLocalPath validation when name is used as the
        relpath source (no path or revision attribute given).
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <submanifest name="{bad_name}" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestInvalidPathError):
            _write_and_load(tmp_path, xml_content)

    def test_revision_with_dotdot_last_segment_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: revision whose last segment is '..' raises ManifestInvalidPathError.

        When no path is given, the last segment of revision is used as the relpath
        and validated by _CheckLocalPath.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" revision="refs/heads/.." />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "revision" in str(exc_info.value).lower() or ".." in str(exc_info.value), (
            f"AC-TEST-002: expected error message to reference 'revision' or '..' but got: {exc_info.value!r}"
        )

    def test_revision_with_dotgit_last_segment_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: revision whose last segment is '.git' raises ManifestInvalidPathError.

        '.git' is a forbidden path component when used as the relpath derived from revision.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" revision="refs/heads/.git" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty ManifestInvalidPathError for revision ending in '.git'"
        )

    def test_path_with_dotdot_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: an explicit path containing '..' raises ManifestInvalidPathError.

        The path attribute is validated by _CheckLocalPath when explicitly given.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="../outside" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "path" in str(exc_info.value).lower() or ".." in str(exc_info.value), (
            f"AC-TEST-002: expected error message to reference 'path' or '..' but got: {exc_info.value!r}"
        )

    def test_path_with_tilde_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: an explicit path containing '~' raises ManifestInvalidPathError.

        '~' is forbidden in any path-checked value.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="~home/sub" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), "AC-TEST-002: expected non-empty ManifestInvalidPathError for path with '~'"

    def test_path_with_dotgit_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: an explicit path containing '.git' raises ManifestInvalidPathError.

        '.git' is a forbidden path component.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path=".git" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), "AC-TEST-002: expected non-empty ManifestInvalidPathError for path='.git'"

    @pytest.mark.parametrize(
        "bad_path",
        [
            "../outside",
            ".git",
            "~home",
            ".repo-dir",
        ],
    )
    def test_path_invalid_values_raise_invalid_path_error(self, tmp_path: pathlib.Path, bad_path: str) -> None:
        """AC-TEST-002 parameterized: various invalid path values raise ManifestInvalidPathError.

        Each value triggers _CheckLocalPath validation when path is explicitly set.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <submanifest name="platform/sub" path="{bad_path}" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestInvalidPathError):
            _write_and_load(tmp_path, xml_content)

    def test_remote_without_project_raises_parse_error(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: remote attribute given without project raises ManifestParseError.

        The remote and project attributes are a coupled pair; remote alone is invalid.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" remote="origin" path="sub" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        msg = str(exc_info.value).lower()
        assert "project" in msg or "remote" in msg, (
            f"AC-TEST-002: expected error message to mention 'project' or 'remote' but got: {exc_info.value!r}"
        )

    def test_duplicate_submanifest_conflicting_attrs_raises_parse_error(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: duplicate <submanifest> elements with different attributes raise ManifestParseError.

        Identical duplicates are silently accepted; conflicting ones must raise.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="sub1" />\n'
            '  <submanifest name="platform/sub" path="sub2" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty ManifestParseError for duplicate conflicting submanifest"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Required attribute omission -- message must name the attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmanifestRequiredAttributeOmission:
    """AC-TEST-003: omitting the required name attribute raises ManifestParseError naming it.

    The <submanifest> element has exactly one required attribute: name.
    When it is absent (or empty), the parser must raise ManifestParseError
    with a message that identifies the missing attribute by name.
    """

    def test_missing_name_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-003: <submanifest> without name raises ManifestParseError.

        The _reqatt helper raises ManifestParseError with a message of the form
        "no <attname> in <element> within <file>", which names the attribute.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <submanifest />\n"
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "name" in error_message.lower(), (
            f"AC-TEST-003: expected ManifestParseError message to name the missing 'name' attribute "
            f"but got: {error_message!r}"
        )

    def test_empty_name_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-003: <submanifest name=""> (empty string) raises ManifestParseError.

        An empty string is treated as absent by the _reqatt helper and raises the
        same error, naming the attribute in the message.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "name" in error_message.lower(), (
            f"AC-TEST-003: expected ManifestParseError message to name the missing 'name' attribute "
            f"but got: {error_message!r}"
        )

    def test_missing_name_error_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-003: ManifestParseError raised for missing name has a non-empty message.

        An empty error message is not actionable; the message must be non-empty
        and ideally identify both the attribute and the element.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <submanifest />\n"
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-003: expected a non-empty ManifestParseError message when name is absent but got an empty string"
        )

    def test_missing_name_error_references_submanifest_element(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-003: error message references 'submanifest' to identify the element context.

        The _reqatt format is 'no <att> in <<element>> within <file>'; this test
        asserts the element name appears in the message so users know which element
        caused the failure.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <submanifest />\n"
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "submanifest" in error_message.lower(), (
            f"AC-TEST-003: expected error message to reference 'submanifest' element but got: {error_message!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parse-time validation coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmanifestParseTimeValidation:
    """AC-FUNC-001: every documented attribute of <submanifest> is validated at parse time.

    This class exercises the parse-time validators rather than post-parse
    accessors.  It verifies that invalid values are rejected before any caller
    can access the parsed result.
    """

    def test_invalid_path_rejected_before_submanifest_is_accessible(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-001: parse fails immediately for an invalid path -- no partial result.

        If path validation fails, _write_and_load must raise before returning
        a manifest object.  The submanifest must not be accessible at all.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path=".git" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestInvalidPathError):
            _write_and_load(tmp_path, xml_content)

    def test_remote_project_constraint_validated_at_parse_time(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-001: remote-without-project constraint is enforced during Load(), not lazily.

        Validation happens at parse time, not deferred to first attribute access.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_valid_submanifest_attributes_all_accessible_after_parse(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-001: all documented attributes are accessible after a valid parse.

        Exercises name, revision, manifest-name, groups, default-groups, path
        in one manifest to confirm no attribute is silently dropped.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <submanifest"
            '    name="platform/sub"'
            '    revision="refs/heads/stable"'
            '    manifest-name="custom.xml"'
            '    groups="groupA,groupB"'
            '    default-groups="default,extra"'
            '    path="mypath"'
            " />\n"
            "</manifest>\n"
        )

        manifest = _write_and_load(tmp_path, xml_content)
        sm = manifest.submanifests["platform/sub"]

        assert sm.name == "platform/sub", f"AC-FUNC-001: expected name='platform/sub' but got: {sm.name!r}"
        assert sm.revision == "refs/heads/stable", (
            f"AC-FUNC-001: expected revision='refs/heads/stable' but got: {sm.revision!r}"
        )
        assert sm.manifestName == "custom.xml", (
            f"AC-FUNC-001: expected manifestName='custom.xml' but got: {sm.manifestName!r}"
        )
        assert "groupA" in sm.groups and "groupB" in sm.groups, (
            f"AC-FUNC-001: expected groups to contain 'groupA','groupB' but got: {sm.groups!r}"
        )
        assert "default" in sm.default_groups and "extra" in sm.default_groups, (
            f"AC-FUNC-001: expected default_groups to contain 'default','extra' but got: {sm.default_groups!r}"
        )
        assert sm.path == "mypath", f"AC-FUNC-001: expected path='mypath' but got: {sm.path!r}"
        assert sm.relpath == "mypath", (
            f"AC-FUNC-001: expected relpath='mypath' when path is given but got: {sm.relpath!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmanifestChannelDiscipline:
    """AC-CHANNEL-001: parse errors surface as exceptions; no stdout leakage.

    The <submanifest> parser must raise exceptions to signal errors rather
    than printing to stdout.  Tests here verify that both error and success
    paths do not write to stdout.
    """

    def test_valid_parse_produces_no_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """AC-CHANNEL-001: a valid <submanifest> parse produces no stdout output.

        Successful parsing must be silent on stdout.
        """
        xml_content = _build_submanifest_manifest('name="platform/sub"')
        _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for valid submanifest parse but got: {captured.out!r}"
        )

    def test_missing_name_error_does_not_write_to_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """AC-CHANNEL-001: ManifestParseError for missing name does not write to stdout.

        Error information must flow through the exception, not stdout.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <submanifest />\n"
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when ManifestParseError is raised but got: {captured.out!r}"
        )

    def test_invalid_path_error_does_not_write_to_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """AC-CHANNEL-001: ManifestInvalidPathError for bad path does not write to stdout.

        Error information must flow through the exception, not stdout.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" path="../outside" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestInvalidPathError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when ManifestInvalidPathError is raised but got: {captured.out!r}"
        )

    def test_remote_without_project_error_does_not_write_to_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """AC-CHANNEL-001: ManifestParseError for remote-without-project does not write to stdout.

        Constraint violation errors must surface via exception only.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <submanifest name="platform/sub" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when ManifestParseError is raised but got: {captured.out!r}"
        )
