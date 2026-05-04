"""Unit tests for <project> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <project> are validated
               (remote name resolution -- a <project remote="..."> attribute
               must reference a declared <remote> element; an undeclared remote
               name raises ManifestParseError; when no remote is declared and
               no <default> remote exists, the parser raises; the ToRemoteSpec
               result for a project reflects the resolved remote)
  AC-TEST-002  Duplicate-element rules for <project> surface clear errors
               (two <project> elements with the same path raise ManifestParseError
               naming the duplicate path; two <project> elements with the same
               name but distinct paths are legal; the path defaults to name when
               omitted, so two projects with the same name and no path raise)
  AC-TEST-003  <project> in an unexpected parent raises or is ignored per spec
               (a manifest file whose root element is not <manifest> raises
               ManifestParseError before any <project> child is processed; a
               <project> nested inside another <project> element in the XML is
               treated as a subproject and the parser recurses -- it does not
               raise; an unknown sibling element alongside <project> inside a
               valid <manifest> root is silently ignored)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules for
               <project> at parse time (during XmlManifest.Load())
  AC-CHANNEL-001  stdout vs stderr discipline is verified (errors raise
                  ManifestParseError, not stdout writes; valid parses produce
                  no stdout output)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of parser
internals.

The cross-element rules for <project>:
- The remote attribute must reference a declared <remote> element by name;
  an undeclared name raises ManifestParseError.
- When remote is absent, the project inherits the <default> remote; if no
  <default> remote exists either, the parser raises ManifestParseError.
- Duplicate path values (two projects resolving to the same relpath) raise
  ManifestParseError naming the duplicate path.
- Two projects with the same name at distinct paths are valid.
- A <project> nested inside another <project> XML element is a subproject
  and is processed recursively, not rejected.
- <project> is processed only within a valid <manifest> root; files with
  any other root element are rejected at root-validation time.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- same pattern as other test_xml_*_crossref.py files
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
# AC-TEST-001: Cross-element reference validation for <project>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <project> are validated.

    The <project remote="..."> attribute is a cross-element reference: the
    named remote must have been declared by a <remote> element. The parser
    must raise ManifestParseError when the reference cannot be resolved.

    Additionally, when remote is absent and no <default> remote is set, the
    parser must raise rather than silently use an empty remote.
    """

    def test_project_referencing_declared_remote_resolves(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project remote="..."> naming a declared remote parses without error.

        After loading, the project's remote attribute reflects the declared
        remote's name and fetch URL.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert len(manifest.projects) == 1, f"AC-TEST-001: expected 1 project but got: {len(manifest.projects)}"
        project = manifest.projects[0]
        assert project.remote is not None, (
            "AC-TEST-001: expected project.remote to be set when remote='origin' "
            "references a declared remote but got None"
        )
        assert project.remote.name == "origin", (
            f"AC-TEST-001: expected project.remote.name='origin' but got: {project.remote.name!r}"
        )

    def test_project_referencing_undeclared_remote_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project remote="..."> naming an undeclared remote raises ManifestParseError.

        The error message must identify the undeclared remote name so the
        developer knows what to declare.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="ghost-remote" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-001: expected a non-empty ManifestParseError for undeclared project remote but got an empty string"
        )
        assert "ghost-remote" in error_message or "not defined" in error_message, (
            f"AC-TEST-001: expected error to name 'ghost-remote' or contain 'not defined' but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "undeclared_remote",
        [
            "missing-remote",
            "phantom-remote",
            "ORIGIN",
        ],
    )
    def test_project_various_undeclared_remotes_raise(
        self,
        tmp_path: pathlib.Path,
        undeclared_remote: str,
    ) -> None:
        """Parameterized: each undeclared remote name in <project> raises ManifestParseError.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="platform/lib" path="lib" remote="{undeclared_remote}" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-001: expected non-empty ManifestParseError for undeclared "
            f"project remote='{undeclared_remote}' but got an empty string"
        )

    def test_project_inherits_default_remote_when_remote_absent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> without a remote attribute inherits the <default> remote.

        The resolved project.remote must match the declared default remote.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="upstream" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = manifest.projects[0]
        assert project.remote is not None, (
            "AC-TEST-001: expected project.remote to be set via default remote inheritance but got None"
        )
        assert project.remote.name == "upstream", (
            f"AC-TEST-001: expected project.remote.name='upstream' via default inheritance "
            f"but got: {project.remote.name!r}"
        )

    def test_project_without_remote_and_no_default_remote_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> with no remote and no <default> remote raises ManifestParseError.

        When neither the project's remote attribute nor the manifest's <default>
        remote is set, the parser has no remote to assign and must raise.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-001: expected a non-empty ManifestParseError when no remote and "
            "no default remote are set but got an empty string"
        )

    def test_project_explicit_remote_overrides_default(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project remote="..."> overrides the <default> remote for that project.

        The project with an explicit remote must use the named remote, while
        a sibling project without a remote attribute inherits the default.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="mirror" fetch="https://mirror.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <project name="platform/lib" path="lib" remote="mirror" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        lib = projects["platform/lib"]

        assert core.remote.name == "origin", (
            f"AC-TEST-001: expected platform/core remote='origin' (default) but got: {core.remote.name!r}"
        )
        assert lib.remote.name == "mirror", (
            f"AC-TEST-001: expected platform/lib remote='mirror' (explicit) but got: {lib.remote.name!r}"
        )

    def test_project_fetch_url_resolved_from_declared_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The project's remote fetchUrl is resolved from the declared <remote> fetch attribute.

        After loading, the project's remote.fetchUrl must match the declared
        remote's fetch URL so the git tooling can compute the correct clone URL.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="partner" fetch="https://partner.example.com" />\n'
            '  <default revision="main" remote="partner" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = manifest.projects[0]
        assert project.remote.fetchUrl == "https://partner.example.com", (
            f"AC-TEST-001: expected project.remote.fetchUrl='https://partner.example.com' "
            f"but got: {project.remote.fetchUrl!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules for <project> surface clear errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectDuplicateElementRules:
    """AC-TEST-002: Duplicate-element rules for <project> surface clear errors.

    The parser enforces:
    - Two <project> elements resolving to the same relpath raise ManifestParseError.
      The error message must contain the duplicate path.
    - When path is omitted, it defaults to name; two projects with the same name
      and no path therefore collide on the same relpath and raise.
    - Two <project> elements with the same name but distinct explicit paths are
      legal (the same project at different checkout locations).
    """

    def test_duplicate_path_raises_naming_the_path(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <project> elements with the same path attribute raise ManifestParseError.

        The error message must contain the duplicate relpath so the developer
        can locate the conflict.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="shared-path" />\n'
            '  <project name="vendor/lib" path="shared-path" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-002: expected a non-empty ManifestParseError for duplicate path but got an empty string"
        )
        assert "shared-path" in error_message, (
            f"AC-TEST-002: expected error to name the duplicate path 'shared-path' but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "duplicate_path",
        [
            "platform/core",
            "vendor/lib",
            "tools/runner",
        ],
    )
    def test_duplicate_path_various_names_raise(
        self,
        tmp_path: pathlib.Path,
        duplicate_path: str,
    ) -> None:
        """Parameterized: any duplicate relpath between two <project> elements raises.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="first-project" path="{duplicate_path}" />\n'
            f'  <project name="second-project" path="{duplicate_path}" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-002: expected non-empty ManifestParseError for duplicate "
            f"path='{duplicate_path}' but got an empty string"
        )
        assert duplicate_path in error_message, (
            f"AC-TEST-002: expected error to name the duplicate path '{duplicate_path}' but got: {error_message!r}"
        )

    def test_duplicate_name_no_path_uses_name_as_path_and_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <project> elements with the same name and no path attribute raise.

        When path is omitted, it defaults to name. Two projects with identical
        names (and no explicit path) therefore collide at the same relpath and
        the parser must raise ManifestParseError.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" />\n'
            '  <project name="platform/core" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-002: expected a non-empty ManifestParseError for two projects "
            "with same name and no path but got an empty string"
        )

    def test_same_name_distinct_paths_is_legal(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <project> elements with the same name but distinct paths are accepted.

        The parser stores both projects in _projects[name] as a list. No error
        must be raised; both projects must appear in manifest.projects.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core-v1" />\n'
            '  <project name="platform/core" path="core-v2" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-002: expected two projects with same name and distinct paths "
                f"to parse without ManifestParseError but got: {exc!r}"
            )

        assert len(manifest.projects) == 2, (
            f"AC-TEST-002: expected 2 projects after same-name distinct-path parse but got: {len(manifest.projects)}"
        )
        paths = {p.relpath for p in manifest.projects}
        assert "core-v1" in paths, f"AC-TEST-002: expected 'core-v1' in project paths but got: {paths!r}"
        assert "core-v2" in paths, f"AC-TEST-002: expected 'core-v2' in project paths but got: {paths!r}"

    def test_distinct_name_distinct_path_is_legal(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <project> elements with different names and different paths are legal.

        This is the normal case and must parse without error.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <project name="vendor/lib" path="lib" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-002: expected two distinct projects to parse without ManifestParseError but got: {exc!r}"
            )

        assert len(manifest.projects) == 2, f"AC-TEST-002: expected 2 projects but got: {len(manifest.projects)}"


# ---------------------------------------------------------------------------
# AC-TEST-003: <project> in an unexpected parent raises or is ignored per spec
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectUnexpectedParent:
    """AC-TEST-003: <project> in an unexpected context raises or is handled per spec.

    Behavior:
    - A manifest file whose root element is not <manifest> raises
      ManifestParseError before any <project> child is processed.
      The error message mentions 'manifest'.
    - A <project> element nested inside another <project> element in the XML
      is treated as a subproject and the parser recurses -- no exception is raised.
    - An unknown element sibling to <project> inside a valid <manifest> root
      is silently ignored without affecting <project> processing.
    """

    def test_project_under_non_manifest_root_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest file whose root element is not <manifest> raises ManifestParseError.

        The parser rejects the file at root-element validation time before any
        <project> element is reached. The error message must mention 'manifest'.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<repository>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</repository>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert "manifest" in error_message.lower(), (
            f"AC-TEST-003: expected 'manifest' in error message for non-manifest root but got: {error_message!r}"
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
    def test_project_under_various_non_manifest_roots_raises(
        self,
        tmp_path: pathlib.Path,
        non_manifest_root: str,
    ) -> None:
        """Parameterized: <project> under any non-manifest root causes ManifestParseError.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{non_manifest_root}>\n"
            '  <project name="platform/core" path="core" />\n'
            f"</{non_manifest_root}>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-003: expected a non-empty error message when <project> appears "
            f"under <{non_manifest_root}> but got an empty string"
        )

    def test_project_nested_inside_project_is_treated_as_subproject(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> element nested inside a parent <project> element is a subproject.

        The parser recurses on child <project> elements and attaches them as
        subprojects to the parent project. This is the documented behavior and
        must not raise ManifestParseError.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core">\n'
            '    <project name="submodule" path="sub" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected nested <project> to be treated as subproject "
                f"without ManifestParseError but got: {exc!r}"
            )

        projects = {p.name: p for p in manifest.projects}
        assert "platform/core" in projects, (
            f"AC-TEST-003: expected 'platform/core' in manifest.projects but got: {list(projects.keys())!r}"
        )
        core = projects["platform/core"]
        assert len(core.subprojects) == 1, (
            f"AC-TEST-003: expected 1 subproject on platform/core but got: {len(core.subprojects)}"
        )
        subproject = core.subprojects[0]
        assert "submodule" in subproject.name, (
            f"AC-TEST-003: expected subproject name to contain 'submodule' but got: {subproject.name!r}"
        )

    def test_unknown_sibling_element_does_not_interfere_with_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An unknown element sibling to <project> inside <manifest> is silently ignored.

        Unknown XML elements inside a valid <manifest> root are skipped by the
        parser loop. The <project> elements must still be processed and appear
        in manifest.projects after loading.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <unknown-element attr="ignored-value" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected unknown sibling element to be silently ignored "
                f"but got ManifestParseError: {exc!r}"
            )

        assert len(manifest.projects) == 1, (
            f"AC-TEST-003: expected 1 project when unknown sibling element is present but got: {len(manifest.projects)}"
        )
        project = manifest.projects[0]
        assert project.name == "platform/core", (
            f"AC-TEST-003: expected project.name='platform/core' but got: {project.name!r}"
        )

    def test_project_valid_inside_manifest_root_resolves_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> inside a valid <manifest> root registers in manifest.projects.

        This positive test confirms that when the parent IS <manifest>,
        everything resolves normally.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="infra" fetch="https://infra.example.com" />\n'
            '  <default revision="refs/heads/main" remote="infra" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert len(manifest.projects) == 1, (
            f"AC-TEST-003: expected 1 project in manifest.projects but got: {len(manifest.projects)}"
        )
        assert manifest.projects[0].name == "platform/core", (
            f"AC-TEST-003: expected project.name='platform/core' but got: {manifest.projects[0].name!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parser enforces cross-element and uniqueness rules at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectCrossRefParseTimeEnforcement:
    """AC-FUNC-001: All cross-element and uniqueness rules are enforced at parse time.

    Validation must occur during XmlManifest.Load(), not lazily on first access
    of manifest.projects or individual project attributes. Tests confirm that
    errors fire during Load() and that the manifest state is consistent after
    a successful parse.
    """

    def test_undeclared_project_remote_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An undeclared remote in <project> raises during Load(), not on first access.

        ManifestParseError must be raised inside XmlManifest.Load() before
        any caller accesses manifest.projects.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="absent-remote" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_duplicate_project_path_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Duplicate project paths raise during Load(), not lazily.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="first" path="collision-path" />\n'
            '  <project name="second" path="collision-path" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_no_default_remote_and_no_project_remote_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Absence of both project remote and default remote raises during Load().

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_project_crossref_fully_resolved_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Valid <project> cross-element references are fully resolved after Load() returns.

        After Load(), manifest.projects is populated with all declared projects,
        each having a resolved remote attribute that corresponds to the declared
        <remote> element. No deferred resolution occurs.

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="refs/heads/main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <project name="vendor/lib" path="lib" remote="upstream" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert len(manifest.projects) == 2, (
            f"AC-FUNC-001: expected 2 projects after Load() but got: {len(manifest.projects)}"
        )
        projects = {p.name: p for p in manifest.projects}

        core = projects["platform/core"]
        assert core.remote is not None, "AC-FUNC-001: expected platform/core.remote to be set after Load()"
        assert core.remote.name == "origin", (
            f"AC-FUNC-001: expected platform/core.remote.name='origin' but got: {core.remote.name!r}"
        )

        lib = projects["vendor/lib"]
        assert lib.remote is not None, "AC-FUNC-001: expected vendor/lib.remote to be set after Load()"
        assert lib.remote.name == "upstream", (
            f"AC-FUNC-001: expected vendor/lib.remote.name='upstream' but got: {lib.remote.name!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectCrossRefChannelDiscipline:
    """AC-CHANNEL-001: All cross-element errors surface as exceptions, not stdout.

    ManifestParseError must be the sole channel for reporting validation
    failures. No error text must appear on stdout. Successful parses must
    raise no exception and produce no stdout output.
    """

    def test_undeclared_project_remote_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """An undeclared remote in <project> produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="phantom-remote" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for undeclared project remote error but got: {captured.out!r}"
        )

    def test_duplicate_project_path_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A duplicate path error in <project> produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="first" path="dup-path" />\n'
            '  <project name="second" path="dup-path" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for duplicate path error but got: {captured.out!r}"
        )

    def test_non_manifest_root_with_project_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A non-manifest root file with <project> raises an exception, not stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<config>\n"
            '  <project name="platform/core" path="core" />\n'
            "</config>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for non-manifest root error but got: {captured.out!r}"
        )

    def test_valid_project_crossref_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with valid <project> cross-element references does not raise.

        AC-CHANNEL-001 (positive case: valid parses must not produce errors)
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <project name="vendor/lib" path="lib" remote="upstream" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-CHANNEL-001: expected valid <project> cross-references to parse "
                f"without ManifestParseError but got: {exc!r}"
            )

        assert len(manifest.projects) == 2, (
            f"AC-CHANNEL-001: expected 2 projects after valid parse but got: {len(manifest.projects)}"
        )
