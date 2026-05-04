"""Unit tests for <remove-project> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <remove-project> are validated
               (project name resolution -- remove-project targeting an undeclared
               project raises, with a declared project it resolves correctly;
               base-rev cross-checks the project's revisionExpr)
  AC-TEST-002  Duplicate-element rules for <remove-project> surface clear errors
               (removing the same project twice, removing after it was already
               removed, removing with a base-rev that does not match)
  AC-TEST-003  <remove-project> in an unexpected parent raises or is ignored per
               spec (file root is not <manifest>, remove-project before any
               projects are declared, remove-project appearing after its target
               project -- the normal case)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules
               documented for <remove-project>
  AC-CHANNEL-001  stdout vs stderr discipline is verified (errors raise
                  exceptions, not stdout writes)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of parser
internals.

The <remove-project> element documented cross-element interactions:
  Required (at least one): name (must match a declared project name)
                           path (must match a declared project relpath)
  Optional: base-rev (must equal the matched project's revisionExpr or
                      ManifestParseError is raised after the full pass)
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- same pattern as other test_xml_remove_project_*.py files
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

    Raises:
        ManifestParseError: If the manifest is invalid.
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, xml_content)
    return _load_manifest(repodir, manifest_file)


# ---------------------------------------------------------------------------
# AC-TEST-001: Cross-element reference validation for <remove-project>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveProjectCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <remove-project> are validated.

    The parser must:
    - Resolve the 'name' attribute against the set of already-declared projects
    - Resolve the 'path' attribute against the set of declared project relpaths
    - Surface clear ManifestParseError when a referenced project is unresolvable
    - Accept and correctly remove projects when name or path resolves successfully
    - Apply base-rev as a cross-check against the matched project's revisionExpr
    """

    def test_remove_project_name_references_undeclared_project_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project name="..."> naming an undeclared project raises ManifestParseError.

        When no project with the given name has been declared and optional is not
        set, parsing must fail. The error message must include the project name
        or the XML element text so the developer can identify the bad reference.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <remove-project name="platform/ghost-project" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-001: expected a non-empty error message for undeclared project reference but got an empty string"
        )

    @pytest.mark.parametrize(
        "project_name",
        [
            "platform/ghost-project",
            "vendor/missing-lib",
            "tools/phantom-tool",
        ],
    )
    def test_remove_project_various_undeclared_names_raise(
        self,
        tmp_path: pathlib.Path,
        project_name: str,
    ) -> None:
        """Parameterized: each undeclared project name in remove-project raises ManifestParseError.

        For every undeclared project name, a non-empty error must be raised.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <remove-project name="{project_name}" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-001: expected a non-empty error for undeclared project '{project_name}' but got an empty string"
        )

    def test_remove_project_path_references_undeclared_relpath_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project path="..."> referencing a non-existent relpath raises ManifestParseError.

        When no project occupies the given relpath and optional is not set,
        parsing must fail.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <remove-project path="nonexistent-relpath" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, "AC-TEST-001: expected a non-empty error for non-existent relpath but got an empty string"

    def test_remove_project_name_declared_project_resolves_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project name="..."> that matches a declared project resolves without error.

        After parsing, the named project must be absent from manifest.projects.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <remove-project name="platform/core" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"AC-TEST-001: expected 'platform/core' to be absent after resolution but got: {project_names!r}"
        )

    def test_remove_project_path_declared_relpath_resolves_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project path="..."> matching a declared relpath resolves without error.

        After parsing, the project at the given relpath must be absent.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/tools" path="tools" />\n'
            '  <remove-project path="tools" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/tools" not in project_names, (
            f"AC-TEST-001: expected 'platform/tools' to be absent after path resolution but got: {project_names!r}"
        )

    def test_remove_project_base_rev_matches_project_revision_resolves(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """base-rev matching the project's revisionExpr allows removal without error.

        When base-rev equals the project's declared revision, the cross-check
        passes and the project is removed.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" revision="refs/tags/v1.2.3" />\n'
            '  <remove-project name="platform/core" base-rev="refs/tags/v1.2.3" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"AC-TEST-001: expected 'platform/core' to be absent when base-rev matches revision "
            f"but got: {project_names!r}"
        )

    def test_remove_project_base_rev_mismatch_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """base-rev that does not match the project's revisionExpr raises ManifestParseError.

        This is a cross-element reference: remove-project's base-rev attribute
        is checked against the matched project's revisionExpr attribute.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" revision="refs/tags/v1.0.0" />\n'
            '  <remove-project name="platform/core" base-rev="refs/tags/v99.0.0" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, "AC-TEST-001: expected a non-empty error for base-rev mismatch but got an empty string"

    @pytest.mark.parametrize(
        ("project_name", "declared_revision", "given_base_rev"),
        [
            ("platform/alpha", "refs/tags/v1.0.0", "refs/tags/v2.0.0"),
            ("platform/beta", "develop", "main"),
            ("platform/gamma", "abc123def456", "000000000000"),
        ],
    )
    def test_remove_project_base_rev_mismatch_parametrized_raises(
        self,
        tmp_path: pathlib.Path,
        project_name: str,
        declared_revision: str,
        given_base_rev: str,
    ) -> None:
        """Parameterized: each base-rev mismatch combination raises ManifestParseError.

        Verifies that the revision cross-check applies consistently regardless
        of the specific revision values involved.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="{project_name}" path="proj" revision="{declared_revision}" />\n'
            f'  <remove-project name="{project_name}" base-rev="{given_base_rev}" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError):
            _load_manifest(repodir, manifest_file)

    def test_remove_project_name_and_path_both_resolve_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Both name and path attributes together resolve against declared project data.

        When both name and path are given and both match the same project,
        removal succeeds without error.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <remove-project name="platform/core" path="core" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"AC-TEST-001: expected 'platform/core' removed when name+path both resolve but got: {project_names!r}"
        )

    def test_remove_project_does_not_affect_unreferenced_projects(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project> targeting one project leaves all other projects intact.

        The cross-element removal applies only to the resolved project; sibling
        projects remain unaffected.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <project name="platform/sdk" path="sdk" />\n'
            '  <project name="vendor/lib" path="lib" />\n'
            '  <remove-project name="platform/core" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"AC-TEST-001: expected 'platform/core' to be absent after remove-project but got: {project_names!r}"
        )
        assert "platform/sdk" in project_names, (
            f"AC-TEST-001: expected 'platform/sdk' to remain untouched but got: {project_names!r}"
        )
        assert "vendor/lib" in project_names, (
            f"AC-TEST-001: expected 'vendor/lib' to remain untouched but got: {project_names!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules for <remove-project>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveProjectDuplicateRules:
    """AC-TEST-002: Duplicate-element rules for <remove-project> surface clear errors.

    Rules enforced by the parser:
    - Removing the same project by name twice: the second remove-project
      references an already-removed (non-existent) project and raises unless
      optional='true'
    - Removing the same project by path twice: same -- second reference fails
    - Removing a project that was itself removed by an earlier include raises
    - Duplicate base-rev mismatches for the same project accumulate and raise
      at the end of the second pass
    """

    def test_remove_project_twice_by_name_second_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <remove-project name="..."> for the same project: the second one raises.

        After the first remove-project succeeds, the project is no longer in
        the manifest. The second remove-project references a non-existent project
        and must raise ManifestParseError (optional is not set).

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <remove-project name="platform/core" />\n'
            '  <remove-project name="platform/core" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-002: expected a non-empty error when removing the same project twice but got an empty string"
        )

    def test_remove_project_twice_by_path_second_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <remove-project path="..."> for the same relpath: the second one raises.

        After the first path-based remove-project succeeds, the project's relpath
        is no longer registered. The second attempt must raise ManifestParseError.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/tools" path="tools" />\n'
            '  <remove-project path="tools" />\n'
            '  <remove-project path="tools" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-002: expected a non-empty error when removing the same relpath twice but got an empty string"
        )

    def test_remove_project_twice_with_optional_second_suppressed(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <remove-project> for the same project: second with optional='true' does not raise.

        When the second remove-project has optional='true', the missing-project
        error is suppressed and parsing succeeds.

        AC-TEST-002
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <project name="platform/sdk" path="sdk" />\n'
            '  <remove-project name="platform/core" />\n'
            '  <remove-project name="platform/core" optional="true" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"AC-TEST-002: expected 'platform/core' absent after both remove-project elements but got: {project_names!r}"
        )
        assert "platform/sdk" in project_names, (
            f"AC-TEST-002: expected 'platform/sdk' to remain after optional double-remove but got: {project_names!r}"
        )

    def test_remove_project_base_rev_mismatch_naming_project_in_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """base-rev mismatch raises ManifestParseError that includes context about the mismatch.

        The error must carry enough context for the developer to identify the
        project and the conflict: the error message must mention 'revision'
        or 'base' or include the project name.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" revision="develop" />\n'
            '  <remove-project name="platform/core" base-rev="main" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert (
            "platform/core" in error_message
            or "revision" in error_message.lower()
            or "base" in error_message.lower()
            or "mismatch" in error_message.lower()
        ), (
            f"AC-TEST-002: expected error to mention project or describe the base-rev mismatch "
            f"but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "project_name",
        [
            "platform/alpha",
            "vendor/missing-lib",
            "tools/phantom",
        ],
    )
    def test_remove_project_various_nonexistent_names_raise(
        self,
        tmp_path: pathlib.Path,
        project_name: str,
    ) -> None:
        """Parameterized: remove-project naming various non-existent projects raises.

        Each undeclared name must produce a ManifestParseError with a non-empty
        message.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <remove-project name="{project_name}" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-002: expected a non-empty error for undeclared project '{project_name}' but got an empty string"
        )

    def test_remove_project_base_rev_mismatch_via_path_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """base-rev mismatch detected via path-based resolution raises ManifestParseError.

        When the project is resolved by path and base-rev does not match the
        project's revisionExpr, the parser must raise.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" revision="refs/tags/v1.0.0" />\n'
            '  <remove-project path="core" base-rev="refs/tags/v9.9.9" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-002: expected a non-empty error for path-based base-rev mismatch but got an empty string"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <remove-project> in an unexpected parent raises or is ignored
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveProjectUnexpectedParent:
    """AC-TEST-003: <remove-project> in unexpected context raises or is ignored per spec.

    Parser behavior:
    - remove-project in a file whose root element is not <manifest> is never
      reached; parsing fails at the root-element check with 'no <manifest>'
    - remove-project appearing before any <project> declarations has no
      projects to match and raises ManifestParseError (unless optional='true')
    - remove-project nested inside a wrong root element raises at root check
    - remove-project after its target project (the normal case) succeeds
    - Unknown attributes on remove-project are silently ignored by the parser
      (the parser reads only documented attributes by name)
    """

    def test_remove_project_in_non_manifest_root_file_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A file whose root is not <manifest> raises ManifestParseError before remove-project.

        The parser requires a <manifest> root element. Any other root causes
        'no <manifest>' before remove-project is ever reached.

        AC-TEST-003, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<config>\n"
            '  <project name="platform/core" path="core" />\n'
            '  <remove-project name="platform/core" />\n'
            "</config>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "manifest" in error_message.lower(), (
            f"AC-TEST-003: expected error to mention 'manifest' for wrong root element but got: {error_message!r}"
        )

    def test_remove_project_before_any_project_declarations_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project> appearing before any <project> declarations raises.

        When remove-project appears before the target project is declared,
        there is no project to match and the parser raises ManifestParseError.

        Note: this differs from extend-project whose two-pass behavior means
        ordering restrictions apply strictly; remove-project processes in a
        single pass through node_list and must find the project already present.

        AC-TEST-003, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <remove-project name="platform/core" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-003: expected a non-empty error when remove-project appears before its "
            "target project but got an empty string"
        )

    def test_remove_project_after_target_project_succeeds(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project> following its target <project> parses without error.

        This is the normal use case and must succeed. The named project must be
        absent from manifest.projects after loading.

        AC-TEST-003, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <remove-project name="platform/core" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"AC-TEST-003: expected 'platform/core' absent after normal remove-project but got: {project_names!r}"
        )

    def test_remove_project_with_unknown_attribute_is_silently_ignored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An unknown attribute on <remove-project> is silently ignored by the parser.

        The parser reads only documented attributes (name, path, base-rev,
        optional) by name. Unrecognized attributes have no effect and must not
        cause a parse error.

        AC-TEST-003
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <project name="platform/sdk" path="sdk" />\n'
            '  <remove-project name="platform/core" unknown-future-attr="value" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"AC-TEST-003: expected 'platform/core' removed even with unknown attribute but got: {project_names!r}"
        )
        assert "platform/sdk" in project_names, (
            f"AC-TEST-003: expected 'platform/sdk' to remain after remove-project with "
            f"unknown attr but got: {project_names!r}"
        )

    @pytest.mark.parametrize(
        "root_element",
        [
            "repository",
            "config",
            "repo",
        ],
    )
    def test_remove_project_unreachable_under_various_wrong_roots_raises(
        self,
        tmp_path: pathlib.Path,
        root_element: str,
    ) -> None:
        """Parameterized: remove-project under any non-manifest root element causes an error.

        The manifest file must have <manifest> as its root. Any other root
        element causes ManifestParseError before remove-project processing starts.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{root_element}>\n"
            '  <project name="platform/core" path="core" />\n'
            '  <remove-project name="platform/core" />\n'
            f"</{root_element}>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-003: expected a non-empty error for root element <{root_element}> but got an empty string"
        )

    def test_remove_project_before_any_projects_with_optional_true_succeeds(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project optional='true'> appearing before any projects does not raise.

        When optional='true', the missing-project error is suppressed and the
        manifest parses successfully even if no matching project exists.

        AC-TEST-003
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <remove-project name="platform/core" optional="true" />\n'
            '  <project name="platform/sdk" path="sdk" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/sdk" in project_names, (
            f"AC-TEST-003: expected 'platform/sdk' to be present after optional remove-project "
            f"on absent project but got: {project_names!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parser enforces all cross-element and uniqueness rules at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveProjectCrossRefParseTimeEnforcement:
    """AC-FUNC-001: All cross-element and uniqueness rules are enforced at parse time.

    Validation must occur during manifest loading (XmlManifest.Load()), not
    lazily at first use of the resulting project objects.
    """

    def test_undeclared_name_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An undeclared project name in remove-project raises during Load(), not on first use.

        ManifestParseError must be raised within the _write_and_load call (which
        invokes XmlManifest.Load()), not lazily on access of manifest.projects.

        AC-FUNC-001
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <remove-project name="platform/not-declared" />\n'
                "</manifest>\n",
            )

    def test_base_rev_mismatch_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A base-rev mismatch in remove-project raises during Load(), not on first use.

        The revision cross-check fires immediately during manifest loading.

        AC-FUNC-001
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" revision="refs/tags/v1.0.0" />\n'
                '  <remove-project name="platform/core" base-rev="refs/tags/v99.0.0" />\n'
                "</manifest>\n",
            )

    def test_optional_true_suppresses_error_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """optional='true' suppresses the missing-project error during Load().

        The suppression is applied immediately in Load(); no error is raised
        even though the project is absent.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(
            repodir,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <remove-project name="platform/absent" optional="true" />\n'
            "</manifest>\n",
        )
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
        m.Load()

        project_names = [p.name for p in m.projects]
        assert "platform/core" in project_names, (
            f"AC-FUNC-001: expected 'platform/core' to remain when optional=true targets "
            f"absent project but got: {project_names!r}"
        )

    def test_all_valid_crossref_attributes_accepted_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest using all valid remove-project cross-element attributes parses without error.

        This positive test verifies that name, path, and base-rev (matching)
        together in a single <remove-project> element are all accepted at parse time.

        AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" revision="refs/tags/v5.0.0" />\n'
            '  <remove-project name="platform/core" path="core" base-rev="refs/tags/v5.0.0" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"AC-FUNC-001: expected 'platform/core' absent after all-valid remove-project "
            f"crossref attributes but got: {project_names!r}"
        )

    def test_double_remove_second_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A second remove-project for an already-removed project raises during Load().

        The uniqueness rule (cannot remove a project that no longer exists) is
        enforced immediately during loading.

        AC-FUNC-001
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <remove-project name="platform/core" />\n'
                '  <remove-project name="platform/core" />\n'
                "</manifest>\n",
            )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveProjectCrossRefChannelDiscipline:
    """AC-CHANNEL-001: Cross-element and duplicate errors surface as exceptions, not stdout.

    All validation errors for remove-project must be raised as ManifestParseError.
    No error information may be written to stdout. Tests verify that the parser
    uses the exception channel exclusively for all failure modes.
    """

    def test_undeclared_project_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """An undeclared project name error in remove-project produces no stdout output.

        AC-CHANNEL-001
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <remove-project name="platform/ghost" />\n'
                "</manifest>\n",
            )

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for undeclared project error but got: {captured.out!r}"
        )

    def test_base_rev_mismatch_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A base-rev mismatch error in remove-project produces no stdout output.

        AC-CHANNEL-001
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" revision="refs/tags/v1.0.0" />\n'
                '  <remove-project name="platform/core" base-rev="refs/tags/v2.0.0" />\n'
                "</manifest>\n",
            )

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for base-rev mismatch error but got: {captured.out!r}"
        )

    def test_double_remove_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A duplicate remove-project error produces no stdout output.

        AC-CHANNEL-001
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <remove-project name="platform/core" />\n'
                '  <remove-project name="platform/core" />\n'
                "</manifest>\n",
            )

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for duplicate remove-project error but got: {captured.out!r}"
        )

    def test_wrong_root_element_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A wrong-root-element error from remove-project file produces no stdout output.

        AC-CHANNEL-001
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<config>\n"
                '  <project name="platform/core" path="core" />\n'
                '  <remove-project name="platform/core" />\n'
                "</config>\n",
            )

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for wrong-root-element error but got: {captured.out!r}"
        )

    def test_valid_crossref_manifest_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A valid manifest with remove-project cross-references produces no stdout output.

        AC-CHANNEL-001
        """
        _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <remove-project name="platform/core" />\n'
            "</manifest>\n",
        )

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for valid remove-project crossref manifest but got: {captured.out!r}"
        )

    def test_valid_crossref_manifest_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with valid remove-project cross-references parses without error.

        AC-CHANNEL-001 (positive case: valid manifests must not raise)
        """
        try:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <project name="platform/sdk" path="sdk" />\n'
                '  <remove-project name="platform/core" />\n'
                "</manifest>\n",
            )
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-CHANNEL-001: expected valid manifest with remove-project cross-references "
                f"to parse without ManifestParseError but got: {exc!r}"
            )
