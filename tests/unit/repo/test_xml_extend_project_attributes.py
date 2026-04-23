"""Unit tests for <extend-project> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <extend-project> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <extend-project> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <extend-project> element documented attributes:
  Required:  name            (name of an already-declared project)
  Optional:  path            (relpath filter; limits extension to one project)
             dest-path       (move project to a new relpath after extension)
             groups          (comma-separated groups to append)
             revision        (override revision expression)
             remote          (override remote name)
             dest-branch     (set dest_branch on the project)
             upstream        (set upstream on the project)
             base-rev        (guard: current revision must equal this before
                              revision is applied)
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
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
    """Write xml_content to a manifest file and load it.

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


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests -- one per documented attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendProjectValidValues:
    """AC-TEST-001: Every documented attribute of <extend-project> has a valid-value test.

    Each test method exercises one attribute with a legal value and asserts
    that (a) no exception is raised, and (b) the expected observable effect
    on the parsed project is present.
    """

    def test_name_attribute_valid_references_declared_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid name attribute references an already-declared project.

        The minimal valid <extend-project> element contains only the required
        name attribute. Parsing must succeed and the named project must be
        present in the manifest.
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"AC-TEST-001: expected 'platform/core' in manifest.projects after valid name "
            f"attribute but got: {project_names!r}"
        )

    def test_groups_attribute_valid_appends_groups(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid groups attribute appends comma-separated groups to the project.

        After parsing, the project's groups list must contain every group listed
        in the groups attribute of <extend-project>.
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" groups="pdk,sdk" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        for expected_group in ("pdk", "sdk"):
            assert expected_group in core.groups, (
                f"AC-TEST-001: expected group '{expected_group}' in project.groups after "
                f"valid groups attribute but got: {core.groups!r}"
            )

    def test_revision_attribute_valid_updates_revision_expr(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid revision attribute updates the project's revisionExpr.

        After parsing, the project's revisionExpr must equal the value provided
        by the <extend-project revision="..."> attribute.
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/tools" path="tools" />\n'
            '  <extend-project name="platform/tools" revision="refs/tags/v3.0.0" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        tools = projects["platform/tools"]
        assert tools.revisionExpr == "refs/tags/v3.0.0", (
            f"AC-TEST-001: expected revisionExpr='refs/tags/v3.0.0' after valid revision "
            f"attribute but got: {tools.revisionExpr!r}"
        )

    def test_remote_attribute_valid_updates_project_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid remote attribute updates the project's remote.

        After parsing, the project's remote must reference the remote named in
        the <extend-project remote="..."> attribute.
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="backup" fetch="https://backup.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" remote="backup" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert core.remote is not None, "AC-TEST-001: expected project.remote to be set after valid remote attribute"
        assert core.remote.name == "backup", (
            f"AC-TEST-001: expected project.remote.name='backup' after valid remote "
            f"attribute but got: {core.remote.name!r}"
        )

    def test_dest_branch_attribute_valid_sets_dest_branch(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid dest-branch attribute sets the project's dest_branch.

        After parsing, the project's dest_branch must equal the value provided
        by <extend-project dest-branch="...">.
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" dest-branch="refs/heads/release" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert core.dest_branch == "refs/heads/release", (
            f"AC-TEST-001: expected dest_branch='refs/heads/release' after valid "
            f"dest-branch attribute but got: {core.dest_branch!r}"
        )

    def test_upstream_attribute_valid_sets_upstream(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid upstream attribute sets the project's upstream.

        After parsing, the project's upstream must equal the value provided
        by <extend-project upstream="...">.
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" upstream="refs/heads/upstream-main" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert core.upstream == "refs/heads/upstream-main", (
            f"AC-TEST-001: expected upstream='refs/heads/upstream-main' after valid "
            f"upstream attribute but got: {core.upstream!r}"
        )

    def test_path_attribute_valid_filters_extension_to_matching_relpath(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid path attribute limits the extension to the project at that relpath.

        When a project exists at a given relpath and <extend-project path="...">
        specifies that same relpath, the extension is applied to the project.
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" path="core" groups="path-filtered" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert "path-filtered" in core.groups, (
            f"AC-TEST-001: expected 'path-filtered' in project.groups after valid path "
            f"attribute matching relpath but got: {core.groups!r}"
        )

    def test_dest_path_attribute_valid_moves_project_relpath(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid dest-path attribute moves the project to a new relpath.

        After parsing with a dest-path attribute, the project must appear at
        the new relpath and the old relpath must be absent from manifest.paths.
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="original-path" />\n'
            '  <extend-project name="platform/core" dest-path="new-path" />\n'
            "</manifest>\n",
        )

        assert "new-path" in manifest.paths, (
            f"AC-TEST-001: expected 'new-path' in manifest.paths after valid dest-path "
            f"attribute but got: {list(manifest.paths.keys())!r}"
        )
        assert "original-path" not in manifest.paths, (
            f"AC-TEST-001: expected 'original-path' to be absent from manifest.paths "
            f"after dest-path relocation but got: {list(manifest.paths.keys())!r}"
        )

    def test_base_rev_attribute_valid_matching_revision_applies_revision(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: When base-rev matches the project's current revision, revision is applied.

        If the project's current revisionExpr equals the base-rev value, the
        new revision attribute value is applied without error.
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" revision="main" />\n'
            '  <extend-project name="platform/core" revision="refs/tags/v1.0.0"'
            ' base-rev="main" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert core.revisionExpr == "refs/tags/v1.0.0", (
            f"AC-TEST-001: expected revisionExpr='refs/tags/v1.0.0' after base-rev "
            f"matched and revision applied but got: {core.revisionExpr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Invalid-value tests -- one or more per attribute that can fail
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendProjectInvalidValues:
    """AC-TEST-002: Every attribute with a constrained value has negative tests.

    Each test method verifies that an illegal value raises ManifestParseError
    or ManifestInvalidPathError (a subclass of ManifestParseError).
    """

    def test_name_references_nonexistent_project_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: name attribute naming a non-existent project raises ManifestParseError.

        When the project named by <extend-project name="..."> was never declared
        by a <project> element, parsing must fail with ManifestParseError and the
        error message must include the unknown project name.
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <extend-project name="platform/no-such-project" />\n'
                "</manifest>\n",
            )

        error_text = str(exc_info.value)
        assert "platform/no-such-project" in error_text, (
            f"AC-TEST-002: expected error message to mention 'platform/no-such-project' but got: {error_text!r}"
        )

    @pytest.mark.parametrize(
        "bad_project_name",
        [
            "vendor/missing-lib",
            "tools/nonexistent",
            "platform/unknown-service",
        ],
    )
    def test_name_references_various_nonexistent_projects_raises(
        self,
        tmp_path: pathlib.Path,
        bad_project_name: str,
    ) -> None:
        """AC-TEST-002: Parameterized -- various non-existent project names raise ManifestParseError.

        The error message must always include the name that was not found.
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                f'  <extend-project name="{bad_project_name}" />\n'
                "</manifest>\n",
            )

        error_text = str(exc_info.value)
        assert bad_project_name in error_text, (
            f"AC-TEST-002: expected error message to mention '{bad_project_name}' but got: {error_text!r}"
        )

    def test_remote_attribute_undeclared_remote_name_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A remote attribute naming an undeclared remote raises ManifestParseError.

        When <extend-project remote="..."> names a remote that was never declared
        by a <remote> element in the manifest, parsing must fail.
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <extend-project name="platform/core" remote="undeclared-remote" />\n'
                "</manifest>\n",
            )

        error_text = str(exc_info.value)
        assert "undeclared-remote" in error_text, (
            f"AC-TEST-002: expected error message to mention 'undeclared-remote' but got: {error_text!r}"
        )

    def test_dest_path_with_multiple_matching_projects_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: dest-path with multiple matching projects and no path filter raises.

        When a name matches more than one project and dest-path is given without
        a path filter, parsing must fail with ManifestParseError naming the
        ambiguous project name.
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core-a" />\n'
                '  <project name="platform/core" path="core-b" />\n'
                '  <extend-project name="platform/core" dest-path="moved-core" />\n'
                "</manifest>\n",
            )

        error_text = str(exc_info.value)
        assert "platform/core" in error_text, (
            f"AC-TEST-002: expected error message to mention 'platform/core' when "
            f"dest-path is ambiguous but got: {error_text!r}"
        )

    def test_base_rev_mismatch_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: base-rev that does not match the project's current revision raises.

        When <extend-project base-rev="..."> is given and the project's current
        revisionExpr does not equal the base-rev value, parsing must fail with
        ManifestParseError describing the mismatch.
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" revision="develop" />\n'
                '  <extend-project name="platform/core" revision="refs/tags/v2.0.0"'
                ' base-rev="main" />\n'
                "</manifest>\n",
            )

        error_text = str(exc_info.value)
        assert "platform/core" in error_text or "base" in error_text.lower(), (
            f"AC-TEST-002: expected error message to mention project name or base-rev "
            f"mismatch context but got: {error_text!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Required attribute omission raises naming the attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendProjectRequiredAttributeOmission:
    """AC-TEST-003: Omitting a required attribute raises ManifestParseError naming it.

    The only required attribute of <extend-project> is 'name'. Omitting it must
    raise ManifestParseError with a message that explicitly names 'name' as the
    missing attribute so developers receive an actionable error.
    """

    def test_name_attribute_omitted_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: Omitting the required name attribute raises ManifestParseError.

        The error message must name the missing attribute ('name') so the
        developer knows exactly what to add.
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                "  <extend-project />\n"
                "</manifest>\n",
            )

        error_text = str(exc_info.value)
        assert "name" in error_text, (
            f"AC-TEST-003: expected error message to name the missing 'name' attribute but got: {error_text!r}"
        )

    def test_name_attribute_empty_string_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: An empty name attribute is treated as omitted and raises ManifestParseError.

        The _reqatt validator treats an empty attribute value the same as a
        missing attribute. An empty name must raise ManifestParseError that
        names the 'name' attribute.
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <extend-project name="" />\n'
                "</manifest>\n",
            )

        error_text = str(exc_info.value)
        assert "name" in error_text, (
            f"AC-TEST-003: expected error message to name the empty 'name' attribute but got: {error_text!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Attribute validation at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendProjectParseTimeValidation:
    """AC-FUNC-001: All documented attributes are validated at manifest parse time.

    Validation must occur during manifest loading (XmlManifest.Load()), not
    lazily at first use of the resulting project objects.
    """

    def test_invalid_name_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: An invalid name attribute fails during Load(), not on first use.

        ManifestParseError must be raised by _write_and_load (which calls
        XmlManifest.Load()) rather than by any subsequent access of
        manifest.projects.
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <extend-project name="not-declared" />\n'
                "</manifest>\n",
            )

    def test_invalid_remote_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: An undeclared remote attribute fails during Load().

        ManifestParseError must be raised during manifest loading when the
        remote specified in extend-project does not match any declared remote.
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <extend-project name="platform/core" remote="ghost-remote" />\n'
                "</manifest>\n",
            )

    def test_all_valid_attributes_accepted_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: A manifest using all valid extend-project attributes parses without error.

        This integration-level positive test verifies that using name, groups,
        revision, remote, dest-branch, and upstream together in a single
        <extend-project> element is accepted at parse time.
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="mirror" fetch="https://mirror.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core"'
            '    groups="pdk,sdk"'
            '    revision="refs/tags/v4.0.0"'
            '    remote="mirror"'
            '    dest-branch="refs/heads/stable"'
            '    upstream="refs/heads/upstream" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert "pdk" in core.groups, (
            f"AC-FUNC-001: expected 'pdk' in groups after all-attributes extend-project but got: {core.groups!r}"
        )
        assert core.revisionExpr == "refs/tags/v4.0.0", (
            f"AC-FUNC-001: expected revisionExpr='refs/tags/v4.0.0' after all-attributes "
            f"extend-project but got: {core.revisionExpr!r}"
        )
        assert core.dest_branch == "refs/heads/stable", (
            f"AC-FUNC-001: expected dest_branch='refs/heads/stable' after all-attributes "
            f"extend-project but got: {core.dest_branch!r}"
        )
        assert core.upstream == "refs/heads/upstream", (
            f"AC-FUNC-001: expected upstream='refs/heads/upstream' after all-attributes "
            f"extend-project but got: {core.upstream!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendProjectAttributeChannelDiscipline:
    """AC-CHANNEL-001: Parse errors surface as exceptions, not stdout writes.

    All attribute-level validation errors must be raised as ManifestParseError.
    No error information may be written to stdout. Tests here verify that the
    parser uses the exception channel exclusively.
    """

    def test_missing_name_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: A missing required name attribute produces no stdout output.

        The ManifestParseError must be raised silently (no stdout) so callers
        can capture the exception without contaminating their output streams.
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                "  <extend-project />\n"
                "</manifest>\n",
            )

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output when name attribute is missing but got: {captured.out!r}"
        )

    def test_undeclared_remote_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: An undeclared remote attribute produces no stdout output.

        The ManifestParseError for an undeclared remote must be raised as an
        exception with no stdout side effects.
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <extend-project name="platform/core" remote="absent-remote" />\n'
                "</manifest>\n",
            )

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for undeclared remote error but got: {captured.out!r}"
        )

    def test_nonexistent_project_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: A non-existent project name produces no stdout output.

        Verifies the non-existent project ManifestParseError is raised as an
        exception without writing to stdout.
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <extend-project name="ghost-project" />\n'
                "</manifest>\n",
            )

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for non-existent project error but got: {captured.out!r}"
        )
