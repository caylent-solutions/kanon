"""Unit tests for <extend-project> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <extend-project> are validated
               (e.g. remote name resolution -- extend-project with an undeclared
               remote raises, with a declared remote resolves correctly)
  AC-TEST-002  Duplicate-element rules for <extend-project> surface clear errors
               (e.g. extend-project naming a non-existent project, dest-path
               collision when multiple projects match, duplicate dest-path targets)
  AC-TEST-003  <extend-project> in an unexpected parent raises or is ignored per
               spec (nested inside a non-project element, appearing before its
               target project, appearing outside a <manifest> root)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules for
               <extend-project>
  AC-CHANNEL-001  stdout vs stderr discipline is verified (errors raise
                  exceptions, not stdout writes)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of parser
internals.

The <extend-project> element documented attributes (cross-element focus):
  Required:  name     (must reference an already-declared project by name)
  Optional:  path     (relpath filter; the named remote must be declared)
             remote   (must reference a declared <remote> element)
             dest-path (single-project restriction when no path filter)
             base-rev  (guard: project revisionExpr must equal this value)
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- same pattern as other test_xml_extend_project_*.py files
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
# AC-TEST-001: Cross-element reference validation for <extend-project>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendProjectCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <extend-project> are validated.

    The parser must:
    - Resolve the 'name' attribute against the set of already-declared projects
    - Resolve the 'remote' attribute against the set of declared <remote> elements
    - Surface clear ManifestParseError when either reference is unresolvable
    """

    def test_extend_project_with_undeclared_remote_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project remote="..."> naming an undeclared remote raises ManifestParseError.

        When the remote attribute of <extend-project> names a remote that was never
        declared by a <remote> element, parsing must fail and the error message must
        include the undeclared remote name.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" remote="undeclared-remote" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "undeclared-remote" in error_message, (
            f"AC-TEST-001: expected error message to name 'undeclared-remote' but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "undeclared_remote",
        [
            "ghost-remote",
            "missing-mirror",
            "ORIGIN",
        ],
    )
    def test_extend_project_various_undeclared_remotes_raise(
        self,
        tmp_path: pathlib.Path,
        undeclared_remote: str,
    ) -> None:
        """Parameterized: each undeclared remote name in extend-project produces a ManifestParseError.

        The error message must always include the remote name that was not found.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            f'  <extend-project name="platform/core" remote="{undeclared_remote}" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert undeclared_remote in error_message, (
            f"AC-TEST-001: expected error to name undeclared remote '{undeclared_remote}' but got: {error_message!r}"
        )

    def test_extend_project_with_declared_remote_resolves_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project remote="..."> naming a declared remote resolves without error.

        After parsing, the project's remote attribute must reference the remote
        object corresponding to the name supplied in the extend-project element.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="mirror" fetch="https://mirror.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" remote="mirror" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        assert "platform/core" in projects, (
            f"AC-TEST-001: expected 'platform/core' in manifest.projects but got: {list(projects.keys())!r}"
        )
        core = projects["platform/core"]
        assert core.remote is not None, (
            "AC-TEST-001: expected project.remote to be set after extend-project remote= but got None"
        )
        assert "mirror" in core.remote.name, (
            f"AC-TEST-001: expected 'mirror' in project.remote.name after extend-project remote= "
            f"but got: {core.remote.name!r}"
        )

    def test_extend_project_name_references_nonexistent_project_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project name="..."> naming a non-existent project raises ManifestParseError.

        The error message must include the name of the missing project so the
        developer knows exactly which project reference to fix.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <extend-project name="platform/does-not-exist" groups="extra" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "platform/does-not-exist" in error_message, (
            f"AC-TEST-001: expected error to name missing project 'platform/does-not-exist' but got: {error_message!r}"
        )

    def test_extend_project_remote_resolution_propagates_to_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project> remote attribute overrides the project's inherited default remote.

        When a project initially inherits the default remote and an extend-project
        subsequently overrides the remote, the project must reflect the new remote
        from the extend-project, not the original default.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/lib" path="lib" />\n'
            '  <extend-project name="platform/lib" remote="upstream" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        lib = projects["platform/lib"]
        assert lib.remote is not None, (
            "AC-TEST-001: expected project.remote to be set after extend-project remote override"
        )
        assert "upstream" in lib.remote.name, (
            f"AC-TEST-001: expected 'upstream' in project.remote.name after remote override "
            f"but got: {lib.remote.name!r}"
        )

    def test_extend_project_with_multiple_declared_remotes_resolves_named_one(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """With multiple declared remotes, extend-project resolves the one specified by name.

        When three remotes are declared (origin, backup, partner) and extend-project
        names 'partner', the project must end up with the partner remote -- not
        origin or backup.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="backup" fetch="https://backup.example.com" />\n'
            '  <remote name="partner" fetch="https://partner.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" remote="partner" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert core.remote is not None, (
            "AC-TEST-001: expected project.remote to be set after extend-project names 'partner'"
        )
        assert "partner" in core.remote.name, (
            f"AC-TEST-001: expected 'partner' in project.remote.name but got: {core.remote.name!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules for <extend-project> surface clear errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendProjectDuplicateRules:
    """AC-TEST-002: Duplicate-element rules for <extend-project> surface clear errors.

    Rules enforced by the parser:
    - dest-path with multiple matching projects (no path filter) raises
    - base-rev mismatch raises with context identifying the project and conflict
    - Multiple extend-project elements for the same project are legal (additive)
    - Multiple extend-project elements with dest-path on the same project raises
      when more than one project matches
    """

    def test_dest_path_with_multiple_matching_projects_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """dest-path with multiple matching projects and no path filter raises ManifestParseError.

        When the same project name exists at two different relpaths (allowed by the
        manifest format) and extend-project supplies dest-path without a path filter,
        the parser cannot determine which project to relocate and must raise.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core-a" />\n'
            '  <project name="platform/core" path="core-b" />\n'
            '  <extend-project name="platform/core" dest-path="moved-core" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "platform/core" in error_message, (
            f"AC-TEST-002: expected error to name the ambiguous project 'platform/core' but got: {error_message!r}"
        )

    def test_base_rev_mismatch_raises_naming_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """base-rev that does not match the project's revisionExpr raises ManifestParseError.

        The error must contain enough context for the developer to identify the
        project and the conflict: either the project name or the word 'base' must
        appear in the message.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" revision="develop" />\n'
            '  <extend-project name="platform/core" revision="refs/tags/v2.0.0"'
            ' base-rev="main" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "platform/core" in error_message or "base" in error_message.lower(), (
            f"AC-TEST-002: expected error to name project or describe base-rev mismatch but got: {error_message!r}"
        )

    def test_multiple_extend_project_for_same_project_is_additive(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Multiple <extend-project> elements for the same project do not raise.

        Applying extend-project twice to the same project is legal; the second
        invocation accumulates its changes on top of the first.

        AC-TEST-002, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" groups="first-extension" />\n'
            '  <extend-project name="platform/core" groups="second-extension" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert "first-extension" in core.groups, (
            f"AC-TEST-002: expected 'first-extension' in groups after first extend-project but got: {core.groups!r}"
        )
        assert "second-extension" in core.groups, (
            f"AC-TEST-002: expected 'second-extension' in groups after second extend-project but got: {core.groups!r}"
        )

    @pytest.mark.parametrize(
        "project_name",
        [
            "platform/missing-lib",
            "vendor/does-not-exist",
            "tools/phantom",
        ],
    )
    def test_extend_project_various_nonexistent_names_raise(
        self,
        tmp_path: pathlib.Path,
        project_name: str,
    ) -> None:
        """Parameterized: extend-project naming various non-existent projects raises ManifestParseError.

        For each undeclared project name, the error message must contain the
        project name so the developer knows what to declare.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <extend-project name="{project_name}" groups="extra" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert project_name in error_message, (
            f"AC-TEST-002: expected error to name missing project '{project_name}' but got: {error_message!r}"
        )

    def test_extend_project_dest_path_with_path_filter_disambiguates_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """dest-path combined with a path filter resolves the ambiguity and succeeds.

        When two projects share the same name and dest-path is given, adding a
        path filter that matches exactly one of them removes the ambiguity and
        the manifest must parse without error.

        AC-TEST-002
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core-a" />\n'
            '  <project name="platform/core" path="core-b" />\n'
            '  <extend-project name="platform/core" path="core-a" dest-path="moved-core-a" />\n'
            "</manifest>\n",
        )

        assert "moved-core-a" in manifest.paths, (
            f"AC-TEST-002: expected 'moved-core-a' in manifest.paths after disambiguated "
            f"dest-path but got: {list(manifest.paths.keys())!r}"
        )
        assert "core-a" not in manifest.paths, (
            f"AC-TEST-002: expected 'core-a' to be absent from manifest.paths after relocation "
            f"but got: {list(manifest.paths.keys())!r}"
        )

    def test_base_rev_match_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When base-rev matches the project's revisionExpr, no error is raised.

        AC-TEST-002
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
            f"AC-TEST-002: expected revisionExpr='refs/tags/v1.0.0' after matched "
            f"base-rev but got: {core.revisionExpr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <extend-project> in an unexpected parent raises or is ignored
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendProjectUnexpectedParent:
    """AC-TEST-003: <extend-project> in unexpected context raises or is ignored per spec.

    The parser processes <extend-project> only during the second pass through
    the manifest (after all <project> elements are collected). Behavior:
    - extend-project appearing before its target project in the same manifest
      raises ManifestParseError (project not yet known at parse-time resolution)
    - extend-project nested inside a non-manifest root (i.e. a file whose root
      element is not <manifest>) is never reached because the file itself raises
    - extend-project appearing after a valid project declaration in the same
      manifest is the normal case and must succeed
    - Unknown attributes on extend-project are silently ignored (the parser
      reads only documented attributes by name)
    """

    def test_extend_project_before_target_project_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project> that appears before its target <project> raises ManifestParseError.

        The manifest format requires the named project to be declared before it
        can be extended. When extend-project appears first in document order, the
        project is not yet in _projects and the parser must raise.

        AC-TEST-003, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <extend-project name="platform/core" groups="too-early" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "platform/core" in error_message, (
            f"AC-TEST-003: expected error to name the unavailable project 'platform/core' but got: {error_message!r}"
        )

    def test_extend_project_inside_non_manifest_root_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project> nested inside a non-manifest root element raises ManifestParseError.

        The parser first requires a <manifest> root element. If the root is
        something else, parsing fails before extend-project is ever reached.

        AC-TEST-003, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<config>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" groups="extra" />\n'
            "</config>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "manifest" in error_message.lower(), (
            f"AC-TEST-003: expected error message to mention 'manifest' for wrong root "
            f"element but got: {error_message!r}"
        )

    def test_extend_project_after_target_project_succeeds(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project> following its target <project> parses without error.

        This is the normal use case and must succeed.

        AC-TEST-003, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" groups="after-project" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        assert "platform/core" in projects, (
            f"AC-TEST-003: expected 'platform/core' in manifest.projects but got: {list(projects.keys())!r}"
        )
        core = projects["platform/core"]
        assert "after-project" in core.groups, (
            f"AC-TEST-003: expected 'after-project' in project.groups but got: {core.groups!r}"
        )

    def test_extend_project_with_unknown_attribute_is_silently_ignored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An unknown attribute on <extend-project> is silently ignored.

        The parser reads only documented attributes by name; unrecognized
        attributes have no effect and must not cause a parse error.

        AC-TEST-003
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" groups="known" unknown-attr="value" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert "known" in core.groups, (
            f"AC-TEST-003: expected 'known' in project.groups when unknown-attr is present but got: {core.groups!r}"
        )

    @pytest.mark.parametrize(
        "root_element",
        [
            "repository",
            "config",
            "repo",
        ],
    )
    def test_extend_project_unreachable_under_various_wrong_roots_raises(
        self,
        tmp_path: pathlib.Path,
        root_element: str,
    ) -> None:
        """Parameterized: extend-project under any non-manifest root element causes an error.

        The manifest file must have <manifest> as its root. Any other root element
        causes ManifestParseError before extend-project processing ever starts.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{root_element}>\n"
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core" groups="extra" />\n'
            f"</{root_element}>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-003: expected a non-empty error message for root element <{root_element}> but got an empty string"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parser enforces all cross-element and uniqueness rules
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendProjectCrossRefParseTimeEnforcement:
    """AC-FUNC-001: All cross-element and uniqueness rules are enforced at parse time.

    Validation must occur during manifest loading (XmlManifest.Load()), not
    lazily at first use of the resulting project objects.
    """

    def test_undeclared_remote_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An undeclared remote in extend-project raises during Load(), not on first use.

        ManifestParseError must be raised by _write_and_load (which calls
        XmlManifest.Load()) and not by any subsequent access of manifest.projects.

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
                '  <extend-project name="platform/core" remote="phantom-remote" />\n'
                "</manifest>\n",
            )

    def test_nonexistent_project_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A non-existent project name in extend-project raises during Load(), not on first use.

        AC-FUNC-001
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <extend-project name="platform/not-declared" />\n'
                "</manifest>\n",
            )

    def test_dest_path_ambiguity_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An ambiguous dest-path (multiple matching projects) raises during Load().

        AC-FUNC-001
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core-x" />\n'
                '  <project name="platform/core" path="core-y" />\n'
                '  <extend-project name="platform/core" dest-path="core-moved" />\n'
                "</manifest>\n",
            )

    def test_all_valid_crossref_attributes_accepted_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest using all valid cross-element extend-project references parses without error.

        This positive test verifies that name, remote, groups, revision, and
        dest-branch together in a single <extend-project> element are all
        accepted at parse time.

        AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <extend-project name="platform/core"'
            '    remote="upstream"'
            '    groups="pdk,sdk"'
            '    revision="refs/tags/v5.0.0"'
            '    dest-branch="refs/heads/stable" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        assert core.remote is not None, "AC-FUNC-001: expected project.remote to be set after all-valid extend-project"
        assert "upstream" in core.remote.name, (
            f"AC-FUNC-001: expected 'upstream' in project.remote.name but got: {core.remote.name!r}"
        )
        assert "pdk" in core.groups, f"AC-FUNC-001: expected 'pdk' in project.groups but got: {core.groups!r}"
        assert core.revisionExpr == "refs/tags/v5.0.0", (
            f"AC-FUNC-001: expected revisionExpr='refs/tags/v5.0.0' but got: {core.revisionExpr!r}"
        )
        assert core.dest_branch == "refs/heads/stable", (
            f"AC-FUNC-001: expected dest_branch='refs/heads/stable' but got: {core.dest_branch!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendProjectCrossRefChannelDiscipline:
    """AC-CHANNEL-001: Cross-element and duplicate errors surface as exceptions, not stdout.

    All validation errors for extend-project must be raised as ManifestParseError.
    No error information may be written to stdout. Tests here verify that the
    parser uses the exception channel exclusively for all failure modes.
    """

    def test_undeclared_remote_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """An undeclared remote error in extend-project produces no stdout output.

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
                '  <extend-project name="platform/core" remote="absent-remote" />\n'
                "</manifest>\n",
            )

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for undeclared remote error but got: {captured.out!r}"
        )

    def test_nonexistent_project_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A non-existent project name in extend-project produces no stdout output.

        AC-CHANNEL-001
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
            f"AC-CHANNEL-001: expected no stdout for non-existent project error but got: {captured.out!r}"
        )

    def test_dest_path_ambiguity_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """An ambiguous dest-path error in extend-project produces no stdout output.

        AC-CHANNEL-001
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core-p" />\n'
                '  <project name="platform/core" path="core-q" />\n'
                '  <extend-project name="platform/core" dest-path="relocated" />\n'
                "</manifest>\n",
            )

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for dest-path ambiguity error but got: {captured.out!r}"
        )

    def test_base_rev_mismatch_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A base-rev mismatch error in extend-project produces no stdout output.

        AC-CHANNEL-001
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" revision="develop" />\n'
                '  <extend-project name="platform/core" revision="refs/tags/v3.0.0"'
                ' base-rev="main" />\n'
                "</manifest>\n",
            )

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for base-rev mismatch error but got: {captured.out!r}"
        )

    def test_valid_crossref_manifest_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with valid cross-element extend-project references parses without error.

        AC-CHANNEL-001 (positive case: valid manifests must not raise)
        """
        try:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <remote name="partner" fetch="https://partner.example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <extend-project name="platform/core" remote="partner" groups="extra" />\n'
                "</manifest>\n",
            )
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-CHANNEL-001: expected valid manifest with extend-project cross-references "
                f"to parse without ManifestParseError but got: {exc!r}"
            )
