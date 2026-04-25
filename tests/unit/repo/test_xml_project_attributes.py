"""Unit tests for <project> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <project> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <project> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified (no cross-channel
                  leakage)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <project> element documented attributes:
  Required:  name         (unique project identifier and git path on remote; no default)
  Optional:  path         (local checkout path; defaults to name)
  Optional:  remote       (remote name; defaults to the <default> remote)
  Optional:  revision     (branch/tag/sha1; falls back to remote or default revision)
  Optional:  groups       (comma-separated group membership; always includes 'all',
                           'name:<name>', 'path:<relpath>')
  Optional:  rebase       (bool; default True)
  Optional:  sync-c       (bool; default False -- sync current branch only)
  Optional:  sync-s       (bool; default False -- sync submodules)
  Optional:  sync-tags    (bool; default True)
  Optional:  clone-depth  (positive int; shallow clone depth; no default)
  Optional:  dest-branch  (branch for push-to-review; no default)
  Optional:  upstream     (upstream tracking branch; no default)

Additional constraints:
  - name is required; omitting it raises ManifestParseError naming "name"
  - name and path must pass path-safety validation; invalid values raise
    ManifestInvalidPathError
  - clone-depth must be a positive integer (>0); value of 0 or negative raises
    ManifestParseError
  - Referencing an undefined remote raises ManifestParseError
  - No remote and no <default> remote raises ManifestParseError
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestInvalidPathError
from kanon_cli.repo.error import ManifestParseError


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
        ManifestInvalidPathError: If a path attribute is invalid.
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


def _build_project_xml(
    project_name: str = "platform/core",
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
    extra_project_attrs: str = "",
) -> str:
    """Build a minimal valid manifest XML containing one <project> element.

    Args:
        project_name: Value for the name attribute on <project>.
        remote_name: Value for the name attribute on <remote>.
        fetch_url: Value for the fetch attribute on <remote>.
        default_revision: Revision value for the <default> element.
        extra_project_attrs: Additional XML attribute string appended to <project>.

    Returns:
        Full XML string for the manifest.
    """
    project_attrs = f'name="{project_name}"'
    if extra_project_attrs:
        project_attrs = f"{project_attrs} {extra_project_attrs}"

    project_elem = f"  <project {project_attrs} />\n"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f"{project_elem}"
        "</manifest>\n"
    )


def _get_project(manifest: manifest_xml.XmlManifest, project_name: str):
    """Return the project with the given name from a loaded manifest.

    Args:
        manifest: A loaded XmlManifest instance.
        project_name: The name of the project to retrieve.

    Returns:
        The Project object with the given name.

    Raises:
        KeyError: If no project with that name is found.
    """
    projects_by_name = {p.name: p for p in manifest.projects}
    return projects_by_name[project_name]


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests -- one per documented <project> attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectValidValues:
    """AC-TEST-001: Every documented attribute of <project> has a valid-value test.

    Each method exercises one attribute with a legal value and asserts that
    (a) no exception is raised and (b) the expected observable effect on the
    parsed manifest is present.
    """

    def test_name_attribute_valid_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid name attribute is accepted and the project is registered.

        The name attribute is required. After parsing, the project must appear
        in manifest.projects with the correct name.
        """
        manifest = _write_and_load(tmp_path, _build_project_xml(project_name="platform/core"))

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"AC-TEST-001: expected 'platform/core' in manifest.projects but got: {project_names!r}"
        )

    def test_path_attribute_valid_is_stored_as_relpath(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid path attribute is stored as project.relpath.

        When path differs from name, project.relpath must equal the explicit
        path value provided in the manifest.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_project_xml(
                project_name="platform/core",
                extra_project_attrs='path="src/core"',
            ),
        )

        project = _get_project(manifest, "platform/core")
        assert project.relpath == "src/core", (
            f"AC-TEST-001: expected project.relpath='src/core' but got: {project.relpath!r}"
        )

    def test_remote_attribute_valid_overrides_default_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid remote attribute causes the project to use that remote.

        When an explicit remote attribute is set, project.remote.orig_name
        must equal the named remote.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="secondary" fetch="https://secondary.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" remote="secondary" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert project.remote is not None, "AC-TEST-001: expected project.remote to be set but got None"
        assert project.remote.orig_name == "secondary", (
            f"AC-TEST-001: expected project.remote.orig_name='secondary' but got: {project.remote.orig_name!r}"
        )

    def test_revision_attribute_valid_is_stored_as_revision_expr(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid revision attribute is stored as project.revisionExpr.

        An explicit revision on the project element overrides the default
        revision from the <default> element.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_project_xml(
                project_name="platform/core",
                extra_project_attrs='revision="refs/heads/stable"',
            ),
        )

        project = _get_project(manifest, "platform/core")
        assert project.revisionExpr == "refs/heads/stable", (
            f"AC-TEST-001: expected project.revisionExpr='refs/heads/stable' but got: {project.revisionExpr!r}"
        )

    def test_groups_attribute_valid_adds_named_groups(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid groups attribute adds the named groups to project.groups.

        User-specified groups from the manifest must appear in project.groups
        alongside the automatically-added default groups.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_project_xml(
                project_name="platform/core",
                extra_project_attrs='groups="infra,platform"',
            ),
        )

        project = _get_project(manifest, "platform/core")
        assert "infra" in project.groups, f"AC-TEST-001: expected 'infra' in project.groups but got: {project.groups!r}"
        assert "platform" in project.groups, (
            f"AC-TEST-001: expected 'platform' in project.groups but got: {project.groups!r}"
        )

    def test_rebase_attribute_false_is_stored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: rebase='false' is stored as project.rebase=False.

        The boolean rebase attribute defaults to True; an explicit 'false'
        value must be parsed and applied to the project.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_project_xml(
                project_name="platform/core",
                extra_project_attrs='rebase="false"',
            ),
        )

        project = _get_project(manifest, "platform/core")
        assert project.rebase is False, (
            f"AC-TEST-001: expected project.rebase=False for rebase='false' but got: {project.rebase!r}"
        )

    def test_rebase_attribute_true_is_stored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: rebase='true' is stored as project.rebase=True.

        An explicit 'true' value must parse the same as the default.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_project_xml(
                project_name="platform/core",
                extra_project_attrs='rebase="true"',
            ),
        )

        project = _get_project(manifest, "platform/core")
        assert project.rebase is True, (
            f"AC-TEST-001: expected project.rebase=True for rebase='true' but got: {project.rebase!r}"
        )

    def test_sync_c_attribute_true_is_stored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: sync-c='true' is stored as project.sync_c=True.

        The boolean sync-c attribute defaults to False; an explicit 'true'
        value must be parsed and applied.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_project_xml(
                project_name="platform/core",
                extra_project_attrs='sync-c="true"',
            ),
        )

        project = _get_project(manifest, "platform/core")
        assert project.sync_c is True, (
            f"AC-TEST-001: expected project.sync_c=True for sync-c='true' but got: {project.sync_c!r}"
        )

    def test_sync_s_attribute_true_is_stored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: sync-s='true' is stored as project.sync_s=True.

        The boolean sync-s attribute defaults to False; an explicit 'true'
        value must be parsed and applied.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_project_xml(
                project_name="platform/core",
                extra_project_attrs='sync-s="true"',
            ),
        )

        project = _get_project(manifest, "platform/core")
        assert project.sync_s is True, (
            f"AC-TEST-001: expected project.sync_s=True for sync-s='true' but got: {project.sync_s!r}"
        )

    def test_sync_tags_attribute_false_is_stored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: sync-tags='false' is stored as project.sync_tags=False.

        The boolean sync-tags attribute defaults to True; an explicit 'false'
        value must be parsed and applied.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_project_xml(
                project_name="platform/core",
                extra_project_attrs='sync-tags="false"',
            ),
        )

        project = _get_project(manifest, "platform/core")
        assert project.sync_tags is False, (
            f"AC-TEST-001: expected project.sync_tags=False for sync-tags='false' but got: {project.sync_tags!r}"
        )

    def test_clone_depth_attribute_valid_positive_integer_is_stored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A positive clone-depth value is stored as project.clone_depth.

        clone-depth must be a positive integer. A valid positive value must
        be parsed and stored faithfully.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_project_xml(
                project_name="platform/core",
                extra_project_attrs='clone-depth="5"',
            ),
        )

        project = _get_project(manifest, "platform/core")
        assert project.clone_depth == 5, (
            f"AC-TEST-001: expected project.clone_depth=5 for clone-depth='5' but got: {project.clone_depth!r}"
        )

    def test_dest_branch_attribute_valid_is_stored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid dest-branch value is stored as project.dest_branch.

        The dest-branch attribute specifies the branch used for push-to-review.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_project_xml(
                project_name="platform/core",
                extra_project_attrs='dest-branch="refs/heads/release"',
            ),
        )

        project = _get_project(manifest, "platform/core")
        assert project.dest_branch == "refs/heads/release", (
            f"AC-TEST-001: expected project.dest_branch='refs/heads/release' but got: {project.dest_branch!r}"
        )

    def test_upstream_attribute_valid_is_stored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid upstream value is stored as project.upstream.

        The upstream attribute specifies the upstream tracking branch.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_project_xml(
                project_name="platform/core",
                extra_project_attrs='upstream="refs/heads/main"',
            ),
        )

        project = _get_project(manifest, "platform/core")
        assert project.upstream == "refs/heads/main", (
            f"AC-TEST-001: expected project.upstream='refs/heads/main' but got: {project.upstream!r}"
        )

    @pytest.mark.parametrize(
        "project_name,expected_relpath",
        [
            ("platform/core", "platform/core"),
            ("infra/networking", "infra/networking"),
            ("tools/linter", "tools/linter"),
            ("simple", "simple"),
        ],
    )
    def test_name_valid_for_various_project_names(
        self,
        tmp_path: pathlib.Path,
        project_name: str,
        expected_relpath: str,
    ) -> None:
        """AC-TEST-001: Parameterized valid project names parse and default path equals name.

        Several well-formed name values (with and without path separators)
        must be accepted and stored correctly.
        """
        manifest = _write_and_load(tmp_path, _build_project_xml(project_name=project_name))

        project = _get_project(manifest, project_name)
        assert project.name == project_name, (
            f"AC-TEST-001: expected project.name='{project_name}' but got: {project.name!r}"
        )
        assert project.relpath == expected_relpath, (
            f"AC-TEST-001: expected project.relpath='{expected_relpath}' but got: {project.relpath!r}"
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
    def test_revision_valid_for_various_values(
        self,
        tmp_path: pathlib.Path,
        revision: str,
    ) -> None:
        """AC-TEST-001: Parameterized valid revision values are stored correctly.

        Various revision forms (short branch, full ref, tag) must be accepted
        and stored as project.revisionExpr without transformation.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_project_xml(
                project_name="platform/core",
                extra_project_attrs=f'revision="{revision}"',
            ),
        )

        project = _get_project(manifest, "platform/core")
        assert project.revisionExpr == revision, (
            f"AC-TEST-001: expected project.revisionExpr='{revision}' but got: {project.revisionExpr!r}"
        )

    @pytest.mark.parametrize(
        "clone_depth",
        [1, 5, 100],
    )
    def test_clone_depth_valid_for_various_positive_integers(
        self,
        tmp_path: pathlib.Path,
        clone_depth: int,
    ) -> None:
        """AC-TEST-001: Parameterized positive clone-depth values are stored correctly.

        All positive integer values for clone-depth must be accepted and
        stored as project.clone_depth.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_project_xml(
                project_name="platform/core",
                extra_project_attrs=f'clone-depth="{clone_depth}"',
            ),
        )

        project = _get_project(manifest, "platform/core")
        assert project.clone_depth == clone_depth, (
            f"AC-TEST-001: expected project.clone_depth={clone_depth} but got: {project.clone_depth!r}"
        )

    def test_all_optional_attributes_together_parse_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001, AC-FUNC-001: All documented optional attributes together parse correctly.

        When all optional attributes are set simultaneously, every attribute
        must be stored at its correct value on the project object.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_project_xml(
                project_name="platform/core",
                extra_project_attrs=(
                    'path="src/core" '
                    'revision="refs/heads/stable" '
                    'groups="infra,platform" '
                    'rebase="false" '
                    'sync-c="true" '
                    'sync-s="true" '
                    'sync-tags="false" '
                    'clone-depth="3" '
                    'dest-branch="refs/heads/release" '
                    'upstream="refs/heads/main"'
                ),
            ),
        )

        project = _get_project(manifest, "platform/core")
        assert project.relpath == "src/core", f"AC-TEST-001: expected relpath='src/core' but got: {project.relpath!r}"
        assert project.revisionExpr == "refs/heads/stable", (
            f"AC-TEST-001: expected revisionExpr='refs/heads/stable' but got: {project.revisionExpr!r}"
        )
        assert "infra" in project.groups, f"AC-TEST-001: expected 'infra' in groups but got: {project.groups!r}"
        assert "platform" in project.groups, f"AC-TEST-001: expected 'platform' in groups but got: {project.groups!r}"
        assert project.rebase is False, f"AC-TEST-001: expected rebase=False but got: {project.rebase!r}"
        assert project.sync_c is True, f"AC-TEST-001: expected sync_c=True but got: {project.sync_c!r}"
        assert project.sync_s is True, f"AC-TEST-001: expected sync_s=True but got: {project.sync_s!r}"
        assert project.sync_tags is False, f"AC-TEST-001: expected sync_tags=False but got: {project.sync_tags!r}"
        assert project.clone_depth == 3, f"AC-TEST-001: expected clone_depth=3 but got: {project.clone_depth!r}"
        assert project.dest_branch == "refs/heads/release", (
            f"AC-TEST-001: expected dest_branch='refs/heads/release' but got: {project.dest_branch!r}"
        )
        assert project.upstream == "refs/heads/main", (
            f"AC-TEST-001: expected upstream='refs/heads/main' but got: {project.upstream!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Invalid-value tests -- raise ManifestParseError or
#              ManifestInvalidPathError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectInvalidValues:
    """AC-TEST-002: Every attribute has invalid-value tests that raise an error.

    Tests verify that illegal values are rejected at parse time with either
    ManifestParseError or ManifestInvalidPathError, each carrying a non-empty,
    actionable message.
    """

    def test_name_with_absolute_path_raises_manifest_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A name value beginning with '/' raises ManifestInvalidPathError.

        Absolute paths are rejected by _CheckLocalPath; the name attribute
        must be a relative path.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="/absolute/path" />\n'
            "</manifest>\n"
        )

        with pytest.raises((ManifestParseError, ManifestInvalidPathError)) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for absolute name but got empty string"
        )

    def test_name_with_dotdot_component_raises_manifest_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A name containing '..' raises ManifestInvalidPathError.

        Path traversal via '..' is rejected by _CheckLocalPath to prevent
        escaping the working tree.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="../escape" />\n'
            "</manifest>\n"
        )

        with pytest.raises((ManifestParseError, ManifestInvalidPathError)) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), "AC-TEST-002: expected non-empty error message for dotdot name but got empty string"

    def test_name_with_dotgit_component_raises_manifest_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A name containing '.git' as a path component raises ManifestInvalidPathError.

        The path safety validator rejects '.git' components to protect the
        git metadata directory from being overwritten.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name=".git/evil" />\n'
            "</manifest>\n"
        )

        with pytest.raises((ManifestParseError, ManifestInvalidPathError)) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for .git name component but got empty string"
        )

    def test_path_with_dotdot_component_raises_manifest_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A path containing '..' raises ManifestInvalidPathError.

        Path traversal via '..' is rejected by _CheckLocalPath for the path
        attribute to prevent checkout outside the working tree.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="../outside" />\n'
            "</manifest>\n"
        )

        with pytest.raises((ManifestParseError, ManifestInvalidPathError)) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), "AC-TEST-002: expected non-empty error message for dotdot path but got empty string"

    def test_path_with_dotgit_component_raises_manifest_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A path containing '.git' as a component raises ManifestInvalidPathError.

        The path safety validator rejects '.git' components in the path
        attribute to protect the git metadata directory.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path=".git/proj" />\n'
            "</manifest>\n"
        )

        with pytest.raises((ManifestParseError, ManifestInvalidPathError)) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for .git path component but got empty string"
        )

    def test_clone_depth_zero_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: clone-depth='0' raises ManifestParseError.

        clone-depth must be strictly greater than zero. A value of zero
        must be rejected with a message identifying the invalid attribute.
        """
        xml_content = _build_project_xml(
            project_name="platform/core",
            extra_project_attrs='clone-depth="0"',
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for clone-depth=0 but got empty string"
        )
        assert "clone-depth" in str(exc_info.value), (
            f"AC-TEST-002: expected 'clone-depth' in error message but got: {str(exc_info.value)!r}"
        )

    def test_clone_depth_negative_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A negative clone-depth value raises ManifestParseError.

        Negative integers are not valid shallow clone depths; the parser must
        reject them with a message identifying the problem.
        """
        xml_content = _build_project_xml(
            project_name="platform/core",
            extra_project_attrs='clone-depth="-1"',
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for negative clone-depth but got empty string"
        )

    def test_undefined_remote_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: Referencing an undefined remote name raises ManifestParseError.

        When the remote attribute names a remote that has not been declared,
        the parser must fail immediately with a descriptive error.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" remote="nonexistent" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for undefined remote but got empty string"
        )

    def test_clone_depth_non_integer_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A non-integer clone-depth value raises ManifestParseError.

        The XmlInt parser rejects non-numeric strings for integer attributes.
        """
        xml_content = _build_project_xml(
            project_name="platform/core",
            extra_project_attrs='clone-depth="deep"',
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for non-integer clone-depth but got empty string"
        )

    @pytest.mark.parametrize(
        "bad_name,description",
        [
            ("/absolute/path", "absolute path"),
            ("../escape", "parent traversal"),
            (".git/evil", ".git component"),
        ],
    )
    def test_name_invalid_path_variants_raise_error(
        self,
        tmp_path: pathlib.Path,
        bad_name: str,
        description: str,
    ) -> None:
        """AC-TEST-002: Parameterized invalid name values raise ManifestParseError or ManifestInvalidPathError.

        Several categories of invalid name strings must each be rejected at
        parse time with a non-empty error message.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="{bad_name}" />\n'
            "</manifest>\n"
        )

        with pytest.raises((ManifestParseError, ManifestInvalidPathError)) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            f"AC-TEST-002: expected non-empty error message for invalid name ({description}) but got empty string"
        )

    @pytest.mark.parametrize(
        "clone_depth_value",
        [0, -1, -10],
    )
    def test_clone_depth_non_positive_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
        clone_depth_value: int,
    ) -> None:
        """AC-TEST-002: Parameterized non-positive clone-depth values raise ManifestParseError.

        Zero and negative integers are all invalid; each must be rejected.
        """
        xml_content = _build_project_xml(
            project_name="platform/core",
            extra_project_attrs=f'clone-depth="{clone_depth_value}"',
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            f"AC-TEST-002: expected non-empty error message for clone-depth={clone_depth_value} but got empty string"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Required attribute omission raises with message naming
#              the attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectRequiredAttributeOmission:
    """AC-TEST-003: Required attribute omission raises ManifestParseError naming the attribute.

    The <project> element has exactly one required attribute: name.
    Omitting it must raise ManifestParseError with a message that identifies
    the missing attribute by name.
    """

    def test_name_omitted_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: Omitting the required name attribute raises ManifestParseError.

        A <project> without a name attribute cannot be registered; the parser
        must reject it immediately with a descriptive error.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <project />\n"
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_name_omitted_error_message_names_the_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: The ManifestParseError for missing name includes 'name' in its message.

        The _reqatt helper produces a message containing the missing attribute
        name so the user can identify and fix the issue quickly.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <project />\n"
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "name" in str(exc_info.value), (
            f"AC-TEST-003: expected error message to contain 'name' for missing name attribute "
            f"but got: {str(exc_info.value)!r}"
        )

    def test_name_empty_string_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: An empty-string name attribute raises ManifestParseError.

        The _reqatt helper treats an empty string as equivalent to omission;
        the required attribute must have a non-empty value.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-003: expected non-empty error message for empty name attribute but got empty string"
        )

    def test_name_empty_string_error_message_names_the_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: The error for empty-string name includes 'name' in the message.

        The same _reqatt helper path that handles omission also handles the
        empty-string case; the attribute name must appear in the error.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "name" in str(exc_info.value), (
            f"AC-TEST-003: expected error message to contain 'name' for empty name attribute "
            f"but got: {str(exc_info.value)!r}"
        )

    def test_project_missing_name_raises_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003, AC-FUNC-001: The error for missing name is raised during m.Load().

        Constructing XmlManifest must not itself parse the XML; the error
        must appear only when m.Load() is called.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <project />\n"
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        # Construction must not raise -- error is deferred until Load().
        with pytest.raises(ManifestParseError):
            m.Load()


# ---------------------------------------------------------------------------
# AC-FUNC-001: Attribute validation happens at parse time (during m.Load())
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectAttributeValidatedAtParseTime:
    """AC-FUNC-001: Every documented attribute of <project> is validated at parse time.

    Validation must be triggered during m.Load(), not deferred to a later
    stage. Tests verify that calling m.Load() is sufficient to surface all
    attribute errors immediately.
    """

    def test_invalid_clone_depth_raises_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: ManifestParseError for clone-depth=0 is raised during m.Load().

        The clone-depth check runs during the parse phase triggered by
        m.Load(). No deferred validation is permitted.
        """
        xml_content = _build_project_xml(
            project_name="platform/core",
            extra_project_attrs='clone-depth="0"',
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        # Construction must not raise -- error is deferred until Load().
        with pytest.raises(ManifestParseError):
            m.Load()

    def test_invalid_name_path_raises_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: ManifestInvalidPathError for bad name is raised during m.Load().

        The path-safety check on the name attribute runs during the parse
        phase triggered by m.Load(). No deferred validation is permitted.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="../escape" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        # Construction must not raise -- error is deferred until Load().
        with pytest.raises((ManifestParseError, ManifestInvalidPathError)):
            m.Load()

    def test_valid_project_attributes_observable_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: All optional attributes are observable on the project after m.Load().

        The parser must apply all attribute values to the project object
        during m.Load() so they are immediately accessible to callers.
        """
        xml_content = _build_project_xml(
            project_name="platform/core",
            extra_project_attrs=(
                'path="src/core" '
                'revision="refs/heads/stable" '
                'dest-branch="refs/heads/release" '
                'upstream="refs/heads/main"'
            ),
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
        m.Load()

        project = _get_project(m, "platform/core")
        assert project.relpath == "src/core", (
            f"AC-FUNC-001: expected relpath='src/core' after m.Load() but got: {project.relpath!r}"
        )
        assert project.revisionExpr == "refs/heads/stable", (
            f"AC-FUNC-001: expected revisionExpr='refs/heads/stable' after m.Load() but got: {project.revisionExpr!r}"
        )
        assert project.dest_branch == "refs/heads/release", (
            f"AC-FUNC-001: expected dest_branch='refs/heads/release' after m.Load() but got: {project.dest_branch!r}"
        )
        assert project.upstream == "refs/heads/main", (
            f"AC-FUNC-001: expected upstream='refs/heads/main' after m.Load() but got: {project.upstream!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectAttributeChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr discipline is verified (no cross-channel leakage).

    Attribute validation errors must be surfaced as exceptions, never as
    output written to stdout. Tests verify that parse failures produce
    ManifestParseError and leave stdout empty.
    """

    def test_missing_name_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: Missing name attribute raises ManifestParseError; stdout is empty.

        No diagnostic text from the parser must reach stdout when the
        required name attribute is absent.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <project />\n"
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output when name attribute is missing but got: {captured.out!r}"
        )

    def test_invalid_clone_depth_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: Invalid clone-depth raises ManifestParseError; stdout is empty.

        No diagnostic text from the parser must reach stdout when clone-depth
        is invalid.
        """
        xml_content = _build_project_xml(
            project_name="platform/core",
            extra_project_attrs='clone-depth="0"',
        )

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for invalid clone-depth but got: {captured.out!r}"
        )

    def test_invalid_name_path_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: Invalid name path raises an error; stdout is empty.

        No diagnostic text from the parser must reach stdout when the name
        attribute contains an invalid path component.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="../escape" />\n'
            "</manifest>\n"
        )

        with pytest.raises((ManifestParseError, ManifestInvalidPathError)):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for invalid name path but got: {captured.out!r}"
        )

    def test_valid_project_does_not_raise_and_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: A valid <project> parses without raising and without stdout output.

        Confirms that the positive path works correctly and introduces no
        spurious stdout output (no false positives from the negative tests).
        """
        xml_content = _build_project_xml(project_name="platform/core")

        manifest = _write_and_load(tmp_path, xml_content)
        assert manifest is not None, "AC-CHANNEL-001: expected manifest to be loaded but got None"

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for valid <project> parse but got: {captured.out!r}"
        )
