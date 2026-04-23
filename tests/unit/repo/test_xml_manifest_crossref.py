"""Unit tests for <manifest> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <manifest> are validated
               (e.g. remote name resolution for <default>, <project>,
               <superproject>, <extend-project>)
  AC-TEST-002  Duplicate-element rules for <manifest> surface clear errors
               (duplicate <remote> with conflicting attrs, duplicate <default>,
               duplicate <notice>, duplicate <manifest-server>, duplicate path,
               duplicate <repo-hooks>, duplicate <superproject>)
  AC-TEST-003  <manifest> in an unexpected parent raises or is ignored per spec
               (root element is not <manifest>; nested <manifest> inside a
               non-manifest element is silently ignored)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules
  AC-CHANNEL-001  stdout vs stderr discipline verified (errors raise exceptions,
                  not stdout writes)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of parser
internals.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- same pattern as other test_xml_manifest_*.py files
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
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, xml_content)
    return _load_manifest(repodir, manifest_file)


# ---------------------------------------------------------------------------
# AC-TEST-001: Cross-element reference validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <manifest> are validated.

    The parser must resolve remote names referenced in <default>, <project>,
    <superproject>, and <extend-project> against the set of declared <remote>
    elements. Unknown remote names raise ManifestParseError.
    """

    def test_project_with_undefined_remote_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> whose remote= refers to an undeclared remote raises ManifestParseError.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="no-such-remote" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "no-such-remote" in error_message, (
            f"Expected error message to name the unknown remote 'no-such-remote' but got: {error_message!r}"
        )

    def test_default_with_undefined_remote_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <default> whose remote= refers to an undeclared remote raises ManifestParseError.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="ghost-remote" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "ghost-remote" in error_message, (
            f"Expected error message to name the unknown remote 'ghost-remote' but got: {error_message!r}"
        )

    def test_project_with_valid_remote_resolves_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <project> whose remote= names a declared remote resolves without error.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <remote name="mirror" fetch="https://mirror.example.com" />\n'
            '  <default revision="main" remote="upstream" />\n'
            '  <project name="platform/core" path="core" remote="mirror" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        assert "platform/core" in projects, (
            f"Expected 'platform/core' in manifest.projects but got: {list(projects.keys())!r}"
        )
        project = projects["platform/core"]
        assert project.remote is not None, "Expected project.remote to be set but got None"
        assert "mirror" in project.remote.name, (
            f"Expected 'mirror' in project remote name but got: {project.remote.name!r}"
        )

    def test_default_remote_resolution_propagates_to_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A project with no remote attribute inherits the <default> remote.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="central" fetch="https://central.example.com" />\n'
            '  <default revision="main" remote="central" />\n'
            '  <project name="platform/lib" path="lib" />\n'
            "</manifest>\n",
        )

        projects = {p.name: p for p in manifest.projects}
        assert "platform/lib" in projects, (
            f"Expected 'platform/lib' in manifest.projects but got: {list(projects.keys())!r}"
        )
        project = projects["platform/lib"]
        assert project.remote is not None, "Expected project.remote to be set via default but got None"
        assert "central" in project.remote.name, (
            f"Expected 'central' in project remote name inherited from default but got: {project.remote.name!r}"
        )

    def test_superproject_with_undefined_remote_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <superproject> whose remote= refers to an undeclared remote raises ManifestParseError.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/super" remote="nonexistent" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "nonexistent" in error_message, (
            f"Expected error message to name the unknown remote 'nonexistent' but got: {error_message!r}"
        )

    def test_extend_project_with_nonexistent_project_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <extend-project> referencing a non-existent project raises ManifestParseError.

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
            f"Expected error message to name the missing project but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "undefined_remote_name",
        [
            "missing-remote",
            "typo-originn",
            "ORIGIN",
        ],
    )
    def test_project_various_undefined_remote_names_raise(
        self,
        tmp_path: pathlib.Path,
        undefined_remote_name: str,
    ) -> None:
        """Parameterized: each undefined remote name produces a ManifestParseError naming it.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="platform/core" path="core" remote="{undefined_remote_name}" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert undefined_remote_name in error_message, (
            f"Expected error message to name the unknown remote '{undefined_remote_name}' but got: {error_message!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules surface clear errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestDuplicateElementRules:
    """AC-TEST-002: Duplicate-element rules for <manifest> surface clear errors.

    The parser enforces:
    - Duplicate <remote> with conflicting attributes raises
    - Duplicate identical <remote> is accepted (idempotent inclusion)
    - Duplicate <default> with different attrs raises
    - Duplicate <notice> raises
    - Duplicate <manifest-server> raises
    - Duplicate project path raises
    - Duplicate <repo-hooks> raises
    - Duplicate <superproject> raises
    """

    def test_duplicate_remote_with_different_fetch_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <remote> elements with the same name but different fetch URLs raise ManifestParseError.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://first.example.com" />\n'
            '  <remote name="origin" fetch="https://second.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "origin" in error_message, (
            f"Expected error message to name the conflicting remote 'origin' but got: {error_message!r}"
        )

    def test_duplicate_identical_remote_is_accepted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <remote> elements with identical attributes do not raise (idempotent).

        AC-TEST-002, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n",
        )

        assert "origin" in manifest.remotes, (
            f"Expected 'origin' in manifest.remotes after idempotent duplicate but got: "
            f"{list(manifest.remotes.keys())!r}"
        )

    def test_duplicate_default_with_different_revision_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <default> elements with different revision attrs raise ManifestParseError.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <default revision="develop" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"Expected 'duplicate' in error message for conflicting <default> but got: {error_message!r}"
        )

    def test_duplicate_notice_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <notice> elements raise ManifestParseError naming 'duplicate notice'.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <notice>First notice text.</notice>\n"
            "  <notice>Second notice text.</notice>\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"Expected 'duplicate' in error message for repeated <notice> but got: {error_message!r}"
        )
        assert "notice" in error_message.lower(), (
            f"Expected 'notice' in error message for repeated <notice> but got: {error_message!r}"
        )

    def test_duplicate_manifest_server_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <manifest-server> elements raise ManifestParseError naming 'duplicate manifest-server'.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://server1.example.com" />\n'
            '  <manifest-server url="https://server2.example.com" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"Expected 'duplicate' in error message for repeated <manifest-server> but got: {error_message!r}"
        )
        assert "manifest-server" in error_message.lower(), (
            f"Expected 'manifest-server' in error message but got: {error_message!r}"
        )

    def test_duplicate_project_path_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <project> elements with the same path= raise ManifestParseError.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="shared/core" />\n'
            '  <project name="platform/utils" path="shared/core" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"Expected 'duplicate' in error message for repeated project path but got: {error_message!r}"
        )
        assert "shared/core" in error_message, (
            f"Expected duplicate path 'shared/core' named in error message but got: {error_message!r}"
        )

    def test_duplicate_repo_hooks_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <repo-hooks> elements raise ManifestParseError naming 'duplicate repo-hooks'.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks-a" path="hooks-a" />\n'
            '  <project name="tools/hooks-b" path="hooks-b" />\n'
            '  <repo-hooks in-project="tools/hooks-a" enabled-list="commit-msg" />\n'
            '  <repo-hooks in-project="tools/hooks-b" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"Expected 'duplicate' in error message for repeated <repo-hooks> but got: {error_message!r}"
        )
        assert "repo-hooks" in error_message.lower(), (
            f"Expected 'repo-hooks' in error message but got: {error_message!r}"
        )

    def test_duplicate_superproject_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <superproject> elements raise ManifestParseError naming 'duplicate superproject'.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/super-a" />\n'
            '  <superproject name="platform/super-b" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"Expected 'duplicate' in error message for repeated <superproject> but got: {error_message!r}"
        )
        assert "superproject" in error_message.lower(), (
            f"Expected 'superproject' in error message but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "element_name,xml_snippet",
        [
            (
                "notice",
                "  <notice>First.</notice>\n  <notice>Second.</notice>\n",
            ),
            (
                "manifest-server",
                (
                    '  <manifest-server url="https://srv1.example.com" />\n'
                    '  <manifest-server url="https://srv2.example.com" />\n'
                ),
            ),
        ],
    )
    def test_duplicate_singleton_elements_raise(
        self,
        tmp_path: pathlib.Path,
        element_name: str,
        xml_snippet: str,
    ) -> None:
        """Parameterized: any singleton element repeated with conflicting content raises.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n' + xml_snippet + "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"Expected 'duplicate' in error message for repeated <{element_name}> but got: {error_message!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <manifest> in an unexpected parent raises or is ignored per spec
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestUnexpectedParent:
    """AC-TEST-003: <manifest> in an unexpected parent raises or is ignored per spec.

    Per the parser implementation (_ParseManifestXml):
    - The root XML document must have a <manifest> element directly under it.
      If the root element is something other than <manifest>, parsing raises
      ManifestParseError with "no <manifest>".
    - If a <manifest> element appears nested inside another non-manifest root
      (e.g. as a child of <repository>), it is not found and parsing raises.
    - A file whose root IS <manifest> but contains unexpected child elements
      (unknown to the parser) is silently ignored per the implementation's
      loop structure (unrecognized nodeName in _ParseManifest is skipped).
    """

    def test_root_element_not_manifest_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest file whose root element is not <manifest> raises ManifestParseError.

        AC-TEST-003, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<repository>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            "</repository>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "manifest" in error_message.lower(), (
            f"Expected 'manifest' in error message for wrong root element but got: {error_message!r}"
        )

    def test_nested_manifest_inside_wrong_root_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <manifest> nested as a child of a non-manifest root element is not found, raising an error.

        The parser searches for a <manifest> directly among the root document's
        child ELEMENT_NODEs. If <manifest> appears only as a grandchild of a
        different root, it is not found and raises ManifestParseError.

        AC-TEST-003, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<wrapper>\n"
            "  <manifest>\n"
            '    <remote name="origin" fetch="https://example.com" />\n'
            '    <default revision="main" remote="origin" />\n'
            "  </manifest>\n"
            "</wrapper>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "manifest" in error_message.lower(), (
            f"Expected 'manifest' in error message for wrapped root but got: {error_message!r}"
        )

    def test_unknown_child_element_in_manifest_is_silently_ignored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An unknown child element inside a valid <manifest> root is silently ignored.

        The _ParseManifest loop skips unrecognized element names without raising,
        so valid sibling elements (like <remote> and <default>) are still parsed.

        AC-TEST-003, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <unknown-element attr="value" />\n'
            "</manifest>\n",
        )

        assert manifest is not None, "Expected manifest to load successfully despite unknown element"
        assert "origin" in manifest.remotes, (
            f"Expected 'origin' in manifest.remotes after unknown child element "
            f"but got: {list(manifest.remotes.keys())!r}"
        )

    @pytest.mark.parametrize(
        "root_element",
        [
            "repository",
            "config",
            "root",
            "repo",
        ],
    )
    def test_various_non_manifest_root_elements_raise(
        self,
        tmp_path: pathlib.Path,
        root_element: str,
    ) -> None:
        """Parameterized: any root element other than <manifest> causes a ManifestParseError.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{root_element}>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            f"</{root_element}>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, (
            f"Expected a non-empty error message for root element <{root_element}> but got an empty string"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Parser enforces rules via exceptions, not stdout
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestCrossRefChannelDiscipline:
    """AC-FUNC-001 + AC-CHANNEL-001: All cross-ref and duplicate errors raise exceptions.

    The parser reports validation errors exclusively through ManifestParseError.
    No error output goes to stdout; callers detect failures by catching the
    exception. These tests confirm that violation paths raise an exception with
    a non-empty message and do not silently succeed.
    """

    def test_undefined_remote_raises_not_silently_ignored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An undefined remote reference raises ManifestParseError with a non-empty message.

        AC-FUNC-001, AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="phantom" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"

    def test_duplicate_remote_raises_not_silently_ignored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A duplicate remote with conflicting attrs raises ManifestParseError with a non-empty message.

        AC-FUNC-001, AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://first.example.com" />\n'
            '  <remote name="origin" fetch="https://second.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"

    def test_valid_manifest_with_multiple_remotes_and_projects_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A valid manifest using multiple distinct remotes and projects parses without error.

        AC-FUNC-001, AC-CHANNEL-001
        """
        try:
            manifest = _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://origin.example.com" />\n'
                '  <remote name="partner" fetch="https://partner.example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <project name="platform/sdk" path="sdk" remote="partner" />\n'
                "</manifest>\n",
            )
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid multi-remote manifest to parse without ManifestParseError but got: {exc!r}")

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"Expected 'platform/core' in manifest.projects but got: {project_names!r}"
        )
        assert "platform/sdk" in project_names, (
            f"Expected 'platform/sdk' in manifest.projects but got: {project_names!r}"
        )
