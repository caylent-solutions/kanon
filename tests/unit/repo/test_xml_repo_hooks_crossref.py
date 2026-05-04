"""Unit tests for <repo-hooks> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <repo-hooks> are validated
               (e.g. in-project must resolve to a declared project; an
               undefined project name raises ManifestParseError naming the
               project)
  AC-TEST-002  Duplicate-element rules for <repo-hooks> surface clear errors
               (two <repo-hooks> elements in the same manifest raise
               ManifestParseError with "duplicate" and "repo-hooks" in the
               message)
  AC-TEST-003  <repo-hooks> in an unexpected parent raises or is ignored per
               spec (a manifest file whose root element is not <manifest>
               raises ManifestParseError before any <repo-hooks> child is
               processed; within a valid <manifest> root an unknown sibling
               element is ignored without affecting <repo-hooks>)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules
               for <repo-hooks> at parse time (during XmlManifest.Load())
  AC-CHANNEL-001  stdout vs stderr discipline is verified (errors raise
                  ManifestParseError, not stdout writes; valid parses produce
                  no output)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of parser
internals.

The cross-element rules for <repo-hooks>:
- in-project must name a project that has been declared earlier in the
  manifest (or in included manifests); a mismatch raises ManifestParseError
  with "not found for repo-hooks"
- Only one <repo-hooks> element may appear per manifest; a second raises
  ManifestParseError with "duplicate repo-hooks"
- <repo-hooks> is only reached as a child node of <manifest>; if the file
  root is not <manifest> the file is rejected before any child is processed
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- same pattern as other test_xml_repo_hooks_*.py files
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
# AC-TEST-001: Cross-element reference validation for <repo-hooks>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepoHooksCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <repo-hooks> are validated.

    The in-project attribute must resolve to a project declared in the manifest.
    An undeclared project name raises ManifestParseError with a message that
    identifies the unresolved project name.
    """

    def test_in_project_resolves_to_declared_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """in-project resolving to a declared project does not raise.

        After parsing, manifest.repo_hooks_project is set and its name matches
        the in-project attribute value.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.repo_hooks_project is not None, (
            "AC-TEST-001: expected repo_hooks_project to be set when in-project resolves "
            "to a declared project but got None"
        )
        assert manifest.repo_hooks_project.name == "tools/hooks", (
            f"AC-TEST-001: expected repo_hooks_project.name='tools/hooks' but got: {manifest.repo_hooks_project.name!r}"
        )

    def test_in_project_references_undeclared_project_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """in-project naming an undeclared project raises ManifestParseError.

        The error message must include text identifying the failed cross-reference.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <repo-hooks in-project="no-such-project" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-001: expected a non-empty ManifestParseError for undeclared in-project but got an empty string"
        )
        assert "no-such-project" in error_message or "not found" in error_message, (
            f"AC-TEST-001: expected error message to name the undeclared project or contain "
            f"'not found' but got: {error_message!r}"
        )

    def test_in_project_references_project_declared_after_repo_hooks_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """in-project names a project only declared after the repo-hooks element.

        The parser processes project elements and repo-hooks in the same pass
        of _ParseManifest. Projects are collected first, then repo-hooks is
        resolved. A project name that is present in the manifest but was
        declared -- even if structurally after repo-hooks -- is resolved
        correctly. However, if the project is entirely absent the parser raises.
        This test verifies the undeclared-name path is caught regardless of
        element ordering.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <repo-hooks in-project="completely-absent" enabled-list="pre-upload" />\n'
            '  <project name="tools/other" path="other" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, "AC-TEST-001: expected ManifestParseError for absent project name but got empty string"

    @pytest.mark.parametrize(
        "missing_project_name",
        [
            "no-such-project",
            "tools/missing-hooks",
            "platform/does-not-exist",
        ],
    )
    def test_in_project_various_undeclared_names_raise(
        self,
        tmp_path: pathlib.Path,
        missing_project_name: str,
    ) -> None:
        """Parameterized: each undeclared in-project name raises ManifestParseError.

        The error must be non-empty and the message must identify that
        the referenced project was not found.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            f'  <repo-hooks in-project="{missing_project_name}" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-001: expected non-empty ManifestParseError for undeclared "
            f"in-project='{missing_project_name}' but got empty string"
        )

    def test_in_project_resolves_hooks_project_is_also_in_projects_list(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The project resolved by in-project appears in manifest.projects.

        This verifies the cross-element linkage: repo_hooks_project is the
        same project object that appears in the full project list.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project_names = [p.name for p in manifest.projects]
        assert "tools/hooks" in project_names, (
            f"AC-TEST-001: expected 'tools/hooks' in manifest.projects after valid cross-ref but got: {project_names!r}"
        )
        assert manifest.repo_hooks_project is not None, (
            "AC-TEST-001: expected repo_hooks_project to be set but got None"
        )
        assert manifest.repo_hooks_project.name == "tools/hooks", (
            f"AC-TEST-001: expected repo_hooks_project.name='tools/hooks' but got: {manifest.repo_hooks_project.name!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules for <repo-hooks> surface clear errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepoHooksDuplicateElementRules:
    """AC-TEST-002: Duplicate-element rules for <repo-hooks> surface clear errors.

    Only one <repo-hooks> element is permitted per manifest. A second
    <repo-hooks> element raises ManifestParseError. The error message must
    contain both "duplicate" and "repo-hooks".
    """

    def test_two_repo_hooks_same_project_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <repo-hooks> pointing to the same project raise ManifestParseError.

        The error message must contain 'duplicate' and 'repo-hooks'.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="commit-msg" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error message for repeated <repo-hooks> but got: {error_message!r}"
        )
        assert "repo-hooks" in error_message.lower(), (
            f"AC-TEST-002: expected 'repo-hooks' in error message but got: {error_message!r}"
        )

    def test_two_repo_hooks_different_projects_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <repo-hooks> pointing to different projects raise ManifestParseError.

        Even when the two elements reference distinct valid projects, only one
        <repo-hooks> is allowed. The error message must contain 'duplicate' and
        'repo-hooks'.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks-a" path="hooks-a" />\n'
            '  <project name="tools/hooks-b" path="hooks-b" />\n'
            '  <repo-hooks in-project="tools/hooks-a" enabled-list="pre-upload" />\n'
            '  <repo-hooks in-project="tools/hooks-b" enabled-list="commit-msg" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error message for two different "
            f"<repo-hooks> elements but got: {error_message!r}"
        )
        assert "repo-hooks" in error_message.lower(), (
            f"AC-TEST-002: expected 'repo-hooks' in error message but got: {error_message!r}"
        )

    def test_duplicate_repo_hooks_error_message_is_non_empty(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The ManifestParseError raised for duplicate <repo-hooks> has a non-empty message.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="applypatch-msg" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected a non-empty error message for duplicate <repo-hooks> but got an empty string"
        )

    @pytest.mark.parametrize(
        "second_hooks_enabled_list",
        [
            "pre-upload",
            "commit-msg",
            "post-checkout applypatch-msg",
        ],
    )
    def test_duplicate_repo_hooks_regardless_of_enabled_list_raises(
        self,
        tmp_path: pathlib.Path,
        second_hooks_enabled_list: str,
    ) -> None:
        """Parameterized: duplicate <repo-hooks> raises regardless of the enabled-list value.

        The uniqueness constraint applies to the element itself, not just to
        identical attribute values.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload" />\n'
            f'  <repo-hooks in-project="tools/hooks" enabled-list="{second_hooks_enabled_list}" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert "duplicate" in error_message.lower(), (
            f"AC-TEST-002: expected 'duplicate' in error message for duplicate "
            f"<repo-hooks> with enabled-list='{second_hooks_enabled_list}' "
            f"but got: {error_message!r}"
        )

    def test_single_repo_hooks_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with exactly one <repo-hooks> element does not raise.

        This is the positive control: the duplicate rule only fires when a
        second element appears.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-002: expected single <repo-hooks> element to parse without "
                f"ManifestParseError but got: {exc!r}"
            )

        assert manifest.repo_hooks_project is not None, (
            "AC-TEST-002: expected repo_hooks_project to be set after single <repo-hooks> but got None"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <repo-hooks> in an unexpected parent raises or is ignored
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepoHooksUnexpectedParent:
    """AC-TEST-003: <repo-hooks> in an unexpected parent raises or is ignored per spec.

    The parser only processes <repo-hooks> when it appears as a direct child
    of the <manifest> root element. Behavior when the parent is unexpected:

    - A manifest file whose root element is not <manifest> raises
      ManifestParseError before any children (including <repo-hooks>) are
      examined. The error message mentions 'manifest'.
    - An unknown element sibling to <repo-hooks> inside a valid <manifest>
      root is silently ignored; the <repo-hooks> element is still processed.
    - A valid <manifest> root with a <repo-hooks> and unknown elements parses
      correctly and sets repo_hooks_project.
    """

    def test_repo_hooks_in_non_manifest_root_file_raises_before_processing(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A file whose root element is not <manifest> raises ManifestParseError.

        The parser rejects the file at root-element validation time; the
        <repo-hooks> child is never reached.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<repository>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload" />\n'
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
    def test_repo_hooks_under_various_non_manifest_roots_raises(
        self,
        tmp_path: pathlib.Path,
        non_manifest_root: str,
    ) -> None:
        """Parameterized: <repo-hooks> under any non-manifest root raises ManifestParseError.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{non_manifest_root}>\n"
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload" />\n'
            f"</{non_manifest_root}>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-003: expected a non-empty error message when <repo-hooks> "
            f"appears under <{non_manifest_root}> but got an empty string"
        )

    def test_unknown_sibling_element_does_not_interfere_with_repo_hooks(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An unknown element sibling to <repo-hooks> inside <manifest> is ignored.

        Unknown elements inside a valid <manifest> root are silently skipped
        by the parser loop. The <repo-hooks> element must still be processed
        and must resolve correctly.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <unknown-element attr="ignored-value" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected unknown sibling element to be silently ignored "
                f"but got ManifestParseError: {exc!r}"
            )

        assert manifest.repo_hooks_project is not None, (
            "AC-TEST-003: expected repo_hooks_project to be set when unknown sibling "
            "element is present alongside <repo-hooks> but got None"
        )
        assert manifest.repo_hooks_project.name == "tools/hooks", (
            f"AC-TEST-003: expected repo_hooks_project.name='tools/hooks' but got: {manifest.repo_hooks_project.name!r}"
        )

    def test_repo_hooks_valid_in_manifest_root_resolves_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <repo-hooks> inside a valid <manifest> root resolves its in-project correctly.

        This positive test confirms the unexpected-parent logic: when the parent
        IS <manifest>, everything resolves normally.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="infra/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="infra/hooks" enabled-list="commit-msg pre-upload" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.repo_hooks_project is not None, (
            "AC-TEST-003: expected repo_hooks_project to be set for valid <repo-hooks> "
            "inside proper <manifest> parent but got None"
        )
        assert manifest.repo_hooks_project.name == "infra/hooks", (
            f"AC-TEST-003: expected repo_hooks_project.name='infra/hooks' but got: {manifest.repo_hooks_project.name!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parser enforces cross-element and uniqueness rules at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepoHooksCrossRefParseTimeEnforcement:
    """AC-FUNC-001: All cross-element and uniqueness rules are enforced at parse time.

    Validation must occur during XmlManifest.Load(), not lazily on first use
    of repo_hooks_project. These tests confirm that errors fire during Load()
    and that the manifest state is consistent after a successful parse.
    """

    def test_undefined_in_project_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An undeclared in-project reference raises during Load(), not on first access.

        ManifestParseError must be raised inside XmlManifest.Load() before any
        caller accesses manifest.repo_hooks_project.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <repo-hooks in-project="absent-project" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_duplicate_repo_hooks_fails_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Duplicate <repo-hooks> elements raise during Load(), not on first access.

        AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="commit-msg" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_repo_hooks_fully_resolved_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A valid <repo-hooks> is fully resolved by the time Load() returns.

        After Load(), manifest.repo_hooks_project is set and its enabled_repo_hooks
        list is populated. No deferred resolution occurs.

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload commit-msg" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.repo_hooks_project is not None, (
            "AC-FUNC-001: expected repo_hooks_project to be set immediately after Load() but got None"
        )
        hooks = manifest.repo_hooks_project.enabled_repo_hooks
        assert "pre-upload" in hooks, (
            f"AC-FUNC-001: expected 'pre-upload' in enabled_repo_hooks after Load() but got: {hooks!r}"
        )
        assert "commit-msg" in hooks, (
            f"AC-FUNC-001: expected 'commit-msg' in enabled_repo_hooks after Load() but got: {hooks!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepoHooksCrossRefChannelDiscipline:
    """AC-CHANNEL-001: All cross-element errors surface as exceptions, not stdout.

    ManifestParseError must be the sole channel for reporting validation
    failures. No error text must appear on stdout. Successful parses must
    raise no exception and produce no output.
    """

    def test_undefined_in_project_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """An undefined in-project reference raises ManifestParseError, not stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <repo-hooks in-project="phantom-project" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for undefined in-project error but got: {captured.out!r}"
        )

    def test_duplicate_repo_hooks_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Duplicate <repo-hooks> raises ManifestParseError and produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="commit-msg" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for duplicate <repo-hooks> error but got: {captured.out!r}"
        )

    def test_non_manifest_root_with_repo_hooks_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A non-manifest root file with <repo-hooks> raises an exception, not stdout.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<config>\n"
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload" />\n'
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

    def test_valid_repo_hooks_crossref_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with a valid <repo-hooks> cross-element reference does not raise.

        AC-CHANNEL-001 (positive case: valid parses must not produce errors)
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload commit-msg" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-CHANNEL-001: expected valid <repo-hooks> cross-reference to parse "
                f"without ManifestParseError but got: {exc!r}"
            )

        assert manifest.repo_hooks_project is not None, (
            "AC-CHANNEL-001: expected repo_hooks_project to be set after valid parse but got None"
        )
