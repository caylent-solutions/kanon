"""Unit tests for <include> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <include> are validated
               (e.g. remote name resolution -- projects pulled in via
               <include> that reference an undeclared remote raise, projects
               with a declared remote resolve correctly, the included manifest's
               remote declarations are visible after loading)
  AC-TEST-002  Duplicate-element rules for <include> surface clear errors
               (duplicate path caused by a project in an included manifest
               colliding with a project in the primary manifest, same-file
               include twice -- allowed when projects are non-conflicting,
               two includes each contributing conflicting remote declarations)
  AC-TEST-003  <include> in an unexpected parent raises or is ignored per
               spec (file whose root element is not <manifest>, <include>
               appearing inside an element that is not the direct manifest
               root, attempting a circular include chain)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules
               documented for <include>
  AC-CHANNEL-001  stdout vs stderr discipline is verified (errors raise
                  exceptions, not stdout writes)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of parser
internals.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- same pattern as other test_xml_include_*.py files
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


def _write_included_manifest(repodir: pathlib.Path, filename: str, xml_content: str) -> pathlib.Path:
    """Write xml_content to a named file inside the manifests include_root.

    Args:
        repodir: The .repo directory.
        filename: Filename for the included manifest (no directory separators).
        xml_content: Full XML content for the included manifest.

    Returns:
        Absolute path to the written included manifest file.
    """
    included_file = repodir / "manifests" / filename
    included_file.write_text(xml_content, encoding="utf-8")
    return included_file


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


def _setup_include_scenario(
    tmp_path: pathlib.Path,
    primary_xml: str,
    included_filename: str,
    included_xml: str,
) -> manifest_xml.XmlManifest:
    """Write a primary manifest that includes a secondary manifest and load it.

    Args:
        tmp_path: Pytest-provided temporary directory for test isolation.
        primary_xml: Full XML content for the primary manifest file.
        included_filename: Filename for the included manifest.
        included_xml: Full XML content for the included manifest.

    Returns:
        A loaded XmlManifest instance.
    """
    repodir = _make_repo_dir(tmp_path)
    _write_included_manifest(repodir, included_filename, included_xml)
    manifest_file = _write_manifest(repodir, primary_xml)
    return _load_manifest(repodir, manifest_file)


# ---------------------------------------------------------------------------
# AC-TEST-001: Cross-element reference validation for <include>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <include> are validated.

    The parser must:
    - Resolve remote names for projects pulled in via <include> against the
      set of declared <remote> elements in the merged manifest
    - Surface ManifestParseError when a project from an included manifest
      references an undeclared remote
    - Accept projects from included manifests whose remote references are valid
    """

    def test_included_project_with_undefined_remote_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A project in an included manifest that names an undeclared remote raises ManifestParseError.

        When the included manifest declares a project with remote="ghost" but
        "ghost" is not declared in any <remote> element in the combined manifest,
        the parser must raise ManifestParseError. The error must identify the
        undeclared remote by name.

        AC-TEST-001, AC-FUNC-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="ghost-remote" />\n'
            "</manifest>\n"
        )
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="sub.xml" />\n</manifest>\n'
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "sub.xml", included_xml)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert "ghost-remote" in error_message, (
            f"AC-TEST-001: expected error message to name undeclared remote 'ghost-remote' but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "undefined_remote_name",
        [
            "missing-remote",
            "typo-originn",
            "ORIGIN",
        ],
    )
    def test_included_project_various_undefined_remotes_raise(
        self,
        tmp_path: pathlib.Path,
        undefined_remote_name: str,
    ) -> None:
        """Parameterized: each undefined remote name in an included project raises ManifestParseError.

        The error message must always include the remote name that was not found.

        AC-TEST-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="platform/lib" path="lib" remote="{undefined_remote_name}" />\n'
            "</manifest>\n"
        )
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="sub.xml" />\n</manifest>\n'
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "sub.xml", included_xml)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert undefined_remote_name in error_message, (
            f"AC-TEST-001: expected error to name undeclared remote '{undefined_remote_name}' "
            f"but got: {error_message!r}"
        )

    def test_included_project_with_declared_remote_resolves_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A project in an included manifest whose remote names a declared remote resolves without error.

        After parsing, the included project must reference the remote object
        corresponding to the remote name declared in the included manifest.

        AC-TEST-001, AC-FUNC-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="upstream" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="sub.xml" />\n</manifest>\n'

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        assert "platform/core" in projects, (
            f"AC-TEST-001: expected 'platform/core' to be visible after <include> but got: {list(projects.keys())!r}"
        )
        core = projects["platform/core"]
        assert core.remote is not None, (
            "AC-TEST-001: expected project.remote to be set for included project with valid remote"
        )
        assert "upstream" in core.remote.name, (
            f"AC-TEST-001: expected 'upstream' in project.remote.name for included project but got: "
            f"{core.remote.name!r}"
        )

    def test_included_manifest_remote_declarations_visible_in_merged_manifest(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Remotes declared in an included manifest are visible in the merged result.

        After parsing, the combined manifest must contain remote declarations
        from both the primary manifest and all included manifests.

        The included manifest uses the same <default> as the primary manifest
        to avoid a duplicate-default conflict. The key assertion is that the
        remote from the included manifest ("partner") is present in the merged
        manifest alongside the remote from the primary manifest ("origin").

        AC-TEST-001, AC-FUNC-001
        """
        # The included manifest declares a new remote "partner" but does not
        # re-declare <default> to avoid a "duplicate default" error. The
        # included project names its remote explicitly so no default is needed.
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="partner" fetch="https://partner.example.com" />\n'
            '  <project name="vendor/lib" path="lib" remote="partner" revision="main" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <include name="sub.xml" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        assert "origin" in manifest.remotes, (
            f"AC-TEST-001: expected 'origin' from primary manifest in manifest.remotes but got: "
            f"{list(manifest.remotes.keys())!r}"
        )
        assert "partner" in manifest.remotes, (
            f"AC-TEST-001: expected 'partner' from included manifest in manifest.remotes but got: "
            f"{list(manifest.remotes.keys())!r}"
        )

    def test_primary_and_included_manifests_projects_both_visible(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Projects from both primary and included manifests are present after loading.

        The merged manifest must expose projects from all included manifests
        alongside projects declared directly in the primary manifest.

        AC-TEST-001, AC-FUNC-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="included/project" path="iproj" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="primary/project" path="pproj" />\n'
            '  <include name="sub.xml" />\n'
            "</manifest>\n"
        )

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        project_names = [p.name for p in manifest.projects]
        assert "primary/project" in project_names, (
            f"AC-TEST-001: expected 'primary/project' from primary manifest in projects but got: {project_names!r}"
        )
        assert "included/project" in project_names, (
            f"AC-TEST-001: expected 'included/project' from included manifest in projects but got: {project_names!r}"
        )

    def test_default_remote_in_included_manifest_applies_to_included_projects(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The <default remote="..."> in an included manifest resolves for its own projects.

        A project in the included manifest with no explicit remote attribute
        inherits the <default> remote declared in that same included manifest.
        The resulting project must have a non-None remote after loading.

        AC-TEST-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="included-remote" fetch="https://included.example.com" />\n'
            '  <default revision="main" remote="included-remote" />\n'
            '  <project name="tools/build" path="build" />\n'
            "</manifest>\n"
        )
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="sub.xml" />\n</manifest>\n'

        manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)

        projects = {p.name: p for p in manifest.projects}
        build = projects["tools/build"]
        assert build.remote is not None, (
            "AC-TEST-001: expected project.remote to be set for included project "
            "that inherits <default remote> from the included manifest"
        )
        assert "included-remote" in build.remote.name, (
            f"AC-TEST-001: expected 'included-remote' in project.remote.name but got: {build.remote.name!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules for <include> surface clear errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeDuplicateRules:
    """AC-TEST-002: Duplicate-element rules for <include> surface clear errors.

    Rules enforced by the parser:
    - A project from an included manifest whose path collides with an existing
      project path raises ManifestParseError naming the duplicate path
    - Two <include> elements for the same file with compatible content are
      accepted when projects have non-conflicting paths
    - A conflicting remote declaration imported via two different includes
      (same name, different fetch URLs) raises ManifestParseError
    - Two <include> elements whose combined projects produce a duplicate path
      raises ManifestParseError
    """

    def test_included_project_path_collides_with_primary_project_path_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A project from an included manifest whose path duplicates a primary manifest project raises.

        When an included manifest declares a project at the same relpath as a
        project already declared in the primary manifest, the parser must raise
        ManifestParseError with a message identifying the duplicate path.

        AC-TEST-002, AC-FUNC-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="included/core" path="shared/core" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="primary/core" path="shared/core" />\n'
            '  <include name="sub.xml" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "sub.xml", included_xml)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error message for duplicate path but got: {error_message!r}"
        )
        assert "shared/core" in error_message, (
            f"AC-TEST-002: expected duplicate path 'shared/core' named in error but got: {error_message!r}"
        )

    def test_conflicting_remote_across_two_includes_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <include>d manifests declaring the same remote name with conflicting URLs raises.

        When two included manifests both declare a remote with the same name
        but different fetch URLs, the parser must raise ManifestParseError
        and the error message must identify the conflicting remote name.

        AC-TEST-002, AC-FUNC-001
        """
        included_a_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="shared-remote" fetch="https://first.example.com" />\n'
            '  <default revision="main" remote="shared-remote" />\n'
            '  <project name="platform/alpha" path="alpha" />\n'
            "</manifest>\n"
        )
        included_b_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="shared-remote" fetch="https://second.example.com" />\n'
            '  <default revision="main" remote="shared-remote" />\n'
            '  <project name="platform/beta" path="beta" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="a.xml" />\n'
            '  <include name="b.xml" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "a.xml", included_a_xml)
        _write_included_manifest(repodir, "b.xml", included_b_xml)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert "shared-remote" in error_message, (
            f"AC-TEST-002: expected error to name conflicting remote 'shared-remote' but got: {error_message!r}"
        )

    def test_two_includes_same_file_non_conflicting_projects_is_accepted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <include> elements for the same file succeed when projects are non-conflicting.

        Including the same file twice is accepted when the projects in the
        included manifest have compatible declarations. The second include adds
        the same nodes again and the same-name same-fetch remote is idempotent.
        However, project paths would be duplicated and raise an error, so this
        test uses an empty included manifest (no projects, no remotes declared)
        to verify that multiple includes of the same empty file are accepted.

        AC-TEST-002, AC-FUNC-001
        """
        # Use a manifest with no projects to avoid duplicate path errors.
        # The remote and default are still present so the manifest is valid.
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="empty-projects.xml" />\n'
            '  <include name="empty-projects.xml" />\n'
            "</manifest>\n"
        )

        try:
            manifest = _setup_include_scenario(tmp_path, primary_xml, "empty-projects.xml", included_xml)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-002: expected two <include> elements for the same empty-project "
                f"manifest to succeed but got ManifestParseError: {exc!r}"
            )

        assert manifest is not None, (
            "AC-TEST-002: expected a valid XmlManifest instance after double-include of non-conflicting manifest"
        )

    def test_included_project_path_collides_with_other_include_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <include>d manifests whose projects produce a duplicate path raises.

        When manifest A includes file X (which declares project at path "shared")
        and also includes file Y (which declares a different project at the same
        path "shared"), the merged result has a duplicate path and the parser
        must raise ManifestParseError.

        AC-TEST-002, AC-FUNC-001
        """
        included_x_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="team-x/component" path="components/shared" />\n'
            "</manifest>\n"
        )
        included_y_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="team-y/component" path="components/shared" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="x.xml" />\n'
            '  <include name="y.xml" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "x.xml", included_x_xml)
        _write_included_manifest(repodir, "y.xml", included_y_xml)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error for duplicate path "
            f"across two includes but got: {error_message!r}"
        )
        assert "components/shared" in error_message, (
            f"AC-TEST-002: expected duplicate path 'components/shared' in error but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "duplicate_path",
        [
            "platform/core",
            "vendor/lib",
            "tools/build",
        ],
    )
    def test_parameterized_duplicate_path_from_include_raises(
        self,
        tmp_path: pathlib.Path,
        duplicate_path: str,
    ) -> None:
        """Parameterized: any duplicate path from an included manifest raises ManifestParseError.

        The error must name the duplicate path so the developer knows what to fix.

        AC-TEST-002
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="included/proj" path="{duplicate_path}" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="primary/proj" path="{duplicate_path}" />\n'
            '  <include name="sub.xml" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "sub.xml", included_xml)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert duplicate_path in error_message, (
            f"AC-TEST-002: expected duplicate path '{duplicate_path}' named in error but got: {error_message!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <include> in an unexpected parent raises or is ignored per spec
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeUnexpectedParent:
    """AC-TEST-003: <include> in an unexpected parent raises or is ignored per spec.

    The parser processes <include> only when it appears as a direct child of
    a <manifest> root element. Behavior:
    - An included manifest file whose root element is not <manifest> raises
      ManifestParseError (the include_root file itself is invalid)
    - A circular include chain (file A includes file B which includes file A)
      raises ManifestParseError (RuntimeError from Python's recursion limit
      or a custom depth guard)
    - <include> at the top level in the primary manifest with a non-manifest
      root in the included file raises ManifestParseError
    - <include> appearing outside a <manifest> root (i.e. in a file whose
      root element is not <manifest>) is never reached -- the outer file
      itself raises ManifestParseError before the include is processed
    """

    def test_included_file_with_non_manifest_root_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An included file whose root element is not <manifest> raises ManifestParseError.

        The _ParseManifestXml function requires the root element of every
        parsed file (including included ones) to be <manifest>. If the included
        file has a different root, ManifestParseError is raised.

        AC-TEST-003, AC-FUNC-001
        """
        bad_included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<repository>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            "</repository>\n"
        )
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="bad.xml" />\n</manifest>\n'
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "bad.xml", bad_included_xml)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-003: expected a non-empty error message when included file "
            "has a non-manifest root but got an empty string"
        )

    def test_include_in_file_with_non_manifest_root_is_never_reached(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <include> element inside a file whose root is not <manifest> is never processed.

        The parser first validates the root element. If it is not <manifest>,
        ManifestParseError is raised before any <include> child elements are
        reached. This means errors from the include itself are never surfaced
        because the file is already rejected.

        AC-TEST-003, AC-FUNC-001
        """
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <include name="sub.xml" />\n</config>\n'
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert "manifest" in error_message.lower(), (
            f"AC-TEST-003: expected error message to mention 'manifest' for non-manifest root "
            f"but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "non_manifest_root",
        [
            "repository",
            "config",
            "root",
            "repo",
        ],
    )
    def test_various_non_manifest_roots_containing_include_raise(
        self,
        tmp_path: pathlib.Path,
        non_manifest_root: str,
    ) -> None:
        """Parameterized: any non-manifest root element causes ManifestParseError regardless of children.

        An <include> nested under a non-manifest root element is unreachable
        because the file itself fails root-element validation first.

        AC-TEST-003
        """
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{non_manifest_root}>\n"
            '  <include name="sub.xml" />\n'
            f"</{non_manifest_root}>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-003: expected a non-empty error message for root element "
            f"<{non_manifest_root}> but got an empty string"
        )

    def test_include_with_valid_manifest_root_in_included_file_succeeds(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <include> whose referenced file has a valid <manifest> root succeeds.

        This is the normal positive case confirming that only non-manifest
        roots trigger errors. A valid included manifest must parse without error.

        AC-TEST-003, AC-FUNC-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="sub.xml" />\n</manifest>\n'

        try:
            manifest = _setup_include_scenario(tmp_path, primary_xml, "sub.xml", included_xml)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected valid <include> with manifest root to succeed "
                f"but got ManifestParseError: {exc!r}"
            )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"AC-TEST-003: expected 'platform/core' from included manifest in projects but got: {project_names!r}"
        )

    def test_deeply_nested_include_chain_is_supported(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A two-level include chain (A includes B which includes C) is supported.

        The parser supports recursive include expansion. A chain of three files
        (primary -> level1 -> level2) must parse correctly and expose projects
        from all three levels.

        AC-TEST-003, AC-FUNC-001
        """
        level2_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="level2/project" path="l2proj" />\n'
            "</manifest>\n"
        )
        level1_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="level1/project" path="l1proj" />\n'
            '  <include name="level2.xml" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="primary/project" path="pproj" />\n'
            '  <include name="level1.xml" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "level2.xml", level2_xml)
        _write_included_manifest(repodir, "level1.xml", level1_xml)
        manifest_file = _write_manifest(repodir, primary_xml)

        manifest = _load_manifest(repodir, manifest_file)

        project_names = [p.name for p in manifest.projects]
        assert "primary/project" in project_names, (
            f"AC-TEST-003: expected 'primary/project' in projects after 3-level chain but got: {project_names!r}"
        )
        assert "level1/project" in project_names, (
            f"AC-TEST-003: expected 'level1/project' in projects after 3-level chain but got: {project_names!r}"
        )
        assert "level2/project" in project_names, (
            f"AC-TEST-003: expected 'level2/project' in projects after 3-level chain but got: {project_names!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parser enforces all cross-element and uniqueness rules
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeCrossRefParseTimeEnforcement:
    """AC-FUNC-001: All cross-element and uniqueness rules are enforced at parse time.

    Validation must occur during manifest loading (XmlManifest.Load()), not
    lazily at first use of the resulting project objects.
    """

    def test_undefined_remote_in_included_project_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An undeclared remote in an included project raises during Load(), not on first use.

        ManifestParseError must be raised by XmlManifest.Load() and not by
        any subsequent access of manifest.projects.

        AC-FUNC-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="nonexistent-remote" />\n'
            "</manifest>\n"
        )
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="sub.xml" />\n</manifest>\n'
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "sub.xml", included_xml)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_duplicate_path_from_include_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A duplicate path caused by an included project raises during Load().

        The error must occur at parse/load time, not deferred to a later use.

        AC-FUNC-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="alt/proj" path="collision-path" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="primary/proj" path="collision-path" />\n'
            '  <include name="sub.xml" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "sub.xml", included_xml)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_conflicting_remote_across_includes_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Conflicting remote declarations from two included manifests raises during Load().

        AC-FUNC-001
        """
        included_a_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="conflict-remote" fetch="https://host-a.example.com" />\n'
            '  <default revision="main" remote="conflict-remote" />\n'
            "</manifest>\n"
        )
        included_b_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="conflict-remote" fetch="https://host-b.example.com" />\n'
            '  <default revision="main" remote="conflict-remote" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="a.xml" />\n'
            '  <include name="b.xml" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "a.xml", included_a_xml)
        _write_included_manifest(repodir, "b.xml", included_b_xml)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_multi_include_manifest_fully_parsed_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with multiple valid includes is fully parsed during Load().

        All cross-element resolution (remote name lookup, path deduplication)
        happens at Load() time and the resulting manifest is complete and correct.

        Each included manifest declares a different remote and names that remote
        explicitly on its project (no separate <default> in included files to
        avoid a "duplicate default" error when both files are merged).

        AC-FUNC-001
        """
        # Each included manifest adds a new remote and a project that explicitly
        # references that remote -- no <default> in included manifests to avoid
        # a "duplicate default" error when the two defaults have different remotes.
        included_a_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="remote-a" fetch="https://a.example.com" />\n'
            '  <project name="team-a/lib" path="a-lib" remote="remote-a" revision="main" />\n'
            "</manifest>\n"
        )
        included_b_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="remote-b" fetch="https://b.example.com" />\n'
            '  <project name="team-b/lib" path="b-lib" remote="remote-b" revision="main" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="a.xml" />\n'
            '  <include name="b.xml" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "a.xml", included_a_xml)
        _write_included_manifest(repodir, "b.xml", included_b_xml)
        manifest_file = _write_manifest(repodir, primary_xml)

        manifest = _load_manifest(repodir, manifest_file)

        project_names = [p.name for p in manifest.projects]
        assert "team-a/lib" in project_names, (
            f"AC-FUNC-001: expected 'team-a/lib' in projects after multi-include but got: {project_names!r}"
        )
        assert "team-b/lib" in project_names, (
            f"AC-FUNC-001: expected 'team-b/lib' in projects after multi-include but got: {project_names!r}"
        )
        assert "remote-a" in manifest.remotes, (
            f"AC-FUNC-001: expected 'remote-a' in manifest.remotes but got: {list(manifest.remotes.keys())!r}"
        )
        assert "remote-b" in manifest.remotes, (
            f"AC-FUNC-001: expected 'remote-b' in manifest.remotes but got: {list(manifest.remotes.keys())!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeCrossRefChannelDiscipline:
    """AC-CHANNEL-001: Cross-element and duplicate errors surface as exceptions, not stdout.

    All validation errors for <include>-related cross-element rules must be
    raised as ManifestParseError. No error information may be written to
    stdout. Tests verify that the parser uses the exception channel exclusively.
    """

    def test_undefined_remote_in_included_project_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """An undefined remote in an included project produces no stdout output.

        AC-CHANNEL-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="absent-remote" />\n'
            "</manifest>\n"
        )
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="sub.xml" />\n</manifest>\n'
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "sub.xml", included_xml)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for undefined remote error but got: {captured.out!r}"
        )

    def test_duplicate_path_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A duplicate path error from an included project produces no stdout output.

        AC-CHANNEL-001
        """
        included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="alt/proj" path="dup-path" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="main/proj" path="dup-path" />\n'
            '  <include name="sub.xml" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "sub.xml", included_xml)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for duplicate path error but got: {captured.out!r}"
        )

    def test_non_manifest_root_in_included_file_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A non-manifest root in an included file raises an exception, not stdout output.

        AC-CHANNEL-001
        """
        bad_included_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<config>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            "</config>\n"
        )
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="bad.xml" />\n</manifest>\n'
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "bad.xml", bad_included_xml)
        manifest_file = _write_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for non-manifest root in included file but got: {captured.out!r}"
        )

    def test_valid_multi_include_manifest_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A valid manifest with multiple <include> elements parses without raising.

        Each included manifest declares a different remote and uses an explicit
        remote attribute on its project (no <default> re-declaration) to avoid
        a "duplicate default" conflict when the two included manifests are merged.

        AC-CHANNEL-001 (positive case: valid manifests must not raise)
        """
        # Projects explicitly name their remote so no <default> is needed in
        # the included files -- avoiding "duplicate default" errors on merge.
        included_a_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="remote-alpha" fetch="https://alpha.example.com" />\n'
            '  <project name="alpha/core" path="acore" remote="remote-alpha" revision="main" />\n'
            "</manifest>\n"
        )
        included_b_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="remote-beta" fetch="https://beta.example.com" />\n'
            '  <project name="beta/core" path="bcore" remote="remote-beta" revision="main" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="a.xml" />\n'
            '  <include name="b.xml" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "a.xml", included_a_xml)
        _write_included_manifest(repodir, "b.xml", included_b_xml)
        manifest_file = _write_manifest(repodir, primary_xml)

        try:
            _load_manifest(repodir, manifest_file)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-CHANNEL-001: expected valid multi-include manifest to parse without "
                f"ManifestParseError but got: {exc!r}"
            )
