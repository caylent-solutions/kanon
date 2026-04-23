"""Unit tests for the <remove-project> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <remove-project> XML elements parse correctly when
given minimum required attributes, all documented attributes, and that default
attribute values behave as documented.

All tests use real manifest files written to tmp_path via shared helpers.
The conftest in tests/unit/repo/ auto-applies @pytest.mark.unit to every
item collected under that directory.

The <remove-project> element removes a project from the manifest. It can
be used in a manifest that includes another manifest to remove unwanted
projects. Documented attributes:
  Required (at least one): name (project name to remove), path (project
                           relpath to remove)
  Optional: base-rev (revision that must match), optional (bool -- if true,
            no error when project is absent)
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern used in test_xml_manifest_happy.py
# ---------------------------------------------------------------------------

_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest.

    Sets up:
    - <tmp>/.repo/
    - <tmp>/.repo/manifests/    (the include_root / worktree)
    - <tmp>/.repo/manifests.git/config  (remote origin URL for GitConfig)

    Args:
        tmp_path: Pytest tmp_path for isolation.

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
        tmp_path: Pytest tmp_path for isolation.
        xml_content: Full XML content for the manifest file.

    Returns:
        A loaded XmlManifest instance.
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, xml_content)
    return _load_manifest(repodir, manifest_file)


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid <remove-project> with minimum required attributes parses
#              correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveProjectMinimumAttributes:
    """Verify that <remove-project> with only the minimum required attribute (name)
    parses correctly and removes the named project from the manifest.

    The minimum valid <remove-project> requires either a name or a path. With
    only the name, the project matching that name is removed from the manifest.
    """

    def test_remove_project_name_only_removes_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project name="..."> removes the named project from the manifest.

        After parsing, the project must no longer appear in manifest.projects.

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
            f"Expected 'platform/core' to be absent after remove-project but got: {project_names!r}"
        )

    def test_remove_project_path_only_removes_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project path="..."> removes the project at that relpath.

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
            f"Expected 'platform/tools' to be absent after remove-project path but got: {project_names!r}"
        )

    def test_remove_project_nonexistent_project_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project> naming a non-existent project raises ManifestParseError.

        When optional is not set, missing the target project is a parse error.

        AC-TEST-001
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <remove-project name="platform/does-not-exist" />\n'
                "</manifest>\n",
            )
        assert "platform/does-not-exist" in str(exc_info.value), (
            f"Expected error to mention 'platform/does-not-exist' but got: {exc_info.value!r}"
        )

    def test_remove_project_missing_name_and_path_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project> with neither name nor path raises ManifestParseError.

        Both name and path are absent; the parser must reject this as invalid.

        AC-TEST-001
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                "  <remove-project />\n"
                "</manifest>\n",
            )
        error_message = str(exc_info.value)
        assert "name" in error_message.lower() or "path" in error_message.lower(), (
            f"Expected error to mention 'name' or 'path' but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "project_name",
        [
            "platform/core",
            "vendor/library",
            "tools/build",
        ],
    )
    def test_remove_project_name_with_various_project_names(
        self,
        tmp_path: pathlib.Path,
        project_name: str,
    ) -> None:
        """Parameterized: remove-project name works for various project name formats.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="{project_name}" path="proj" />\n'
            f'  <remove-project name="{project_name}" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert project_name not in project_names, (
            f"Expected '{project_name}' to be absent after remove-project but got: {project_names!r}"
        )

    def test_remove_project_name_only_does_not_affect_other_projects(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Removing a project by name leaves other projects untouched.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <project name="platform/tools" path="tools" />\n'
            '  <remove-project name="platform/core" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"Expected 'platform/core' to be removed but it is still present: {project_names!r}"
        )
        assert "platform/tools" in project_names, (
            f"Expected 'platform/tools' to remain after remove-project but got: {project_names!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <remove-project> with all documented attributes parses
#              correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveProjectAllDocumentedAttributes:
    """Verify that <remove-project> using all documented optional attributes parses
    correctly.

    Covers: name (required), path (required-or), base-rev (optional), optional
    (optional bool).
    """

    def test_remove_project_name_and_path_together_removes_matching_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project name="..." path="..."> removes the project matching both.

        Specifying both name and path restricts removal to the project whose
        name and relpath both match.

        AC-TEST-002, AC-FUNC-001
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
            f"Expected 'platform/core' to be absent after remove-project name+path but got: {project_names!r}"
        )

    def test_remove_project_optional_true_no_error_when_project_missing(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project optional="true"> does not raise when the project is absent.

        When optional="true", a missing project is silently ignored.

        AC-TEST-002, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/tools" path="tools" />\n'
            '  <remove-project name="platform/does-not-exist" optional="true" />\n'
            "</manifest>\n",
        )

        assert manifest is not None, "Expected XmlManifest instance but got None"
        project_names = [p.name for p in manifest.projects]
        assert "platform/tools" in project_names, (
            f"Expected 'platform/tools' to remain when optional remove-project targets absent project: {project_names!r}"
        )

    def test_remove_project_optional_false_raises_when_project_missing(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project optional="false"> raises ManifestParseError for a missing project.

        When optional="false" is explicitly set (the default), a missing target
        project is a parse error.

        AC-TEST-002
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <remove-project name="platform/absent" optional="false" />\n'
                "</manifest>\n",
            )

    def test_remove_project_base_rev_matching_removes_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project base-rev="..."> removes the project when revisions match.

        When the project's revisionExpr matches base-rev, the project is removed
        without error.

        AC-TEST-002, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" revision="refs/tags/v1.0.0" />\n'
            '  <remove-project name="platform/core" base-rev="refs/tags/v1.0.0" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"Expected 'platform/core' to be removed when base-rev matches but got: {project_names!r}"
        )

    def test_remove_project_base_rev_mismatch_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project base-rev="..."> raises ManifestParseError when revisions differ.

        When the project's revisionExpr does not match base-rev, the parser raises
        ManifestParseError describing the mismatch.

        AC-TEST-002
        """
        with pytest.raises(ManifestParseError) as exc_info:
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
        error_message = str(exc_info.value)
        assert (
            "mismatch" in error_message.lower()
            or "base" in error_message.lower()
            or "revision" in error_message.lower()
        ), f"Expected error to mention revision mismatch but got: {error_message!r}"

    def test_remove_project_path_only_with_multiple_projects(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project path="..."> removes only the project at that relpath.

        When multiple projects exist, only the one at the specified path is removed.

        AC-TEST-002, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <project name="platform/tools" path="tools" />\n'
            '  <project name="vendor/lib" path="lib" />\n'
            '  <remove-project path="tools" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/tools" not in project_names, (
            f"Expected 'platform/tools' to be removed by path but got: {project_names!r}"
        )
        assert "platform/core" in project_names, (
            f"Expected 'platform/core' to remain after path-only remove-project but got: {project_names!r}"
        )
        assert "vendor/lib" in project_names, (
            f"Expected 'vendor/lib' to remain after path-only remove-project but got: {project_names!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <remove-project> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveProjectDefaultAttributeValues:
    """Verify that default attribute behavior on <remove-project> behaves as documented.

    Default behaviors when optional attributes are omitted:
    - optional: defaults to False (missing project raises ManifestParseError)
    - base-rev: not checked (any revision is accepted)
    - path: not filtered (all projects with the given name are removed)
    """

    def test_remove_project_optional_defaults_to_false_on_missing_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When optional is omitted, removing a missing project raises ManifestParseError.

        The default for optional is False, so an absent project raises an error.

        AC-TEST-003
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <remove-project name="platform/absent" />\n'
                "</manifest>\n",
            )

    def test_remove_project_no_base_rev_removes_project_regardless_of_revision(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When base-rev is omitted, the project is removed regardless of its revision.

        No revision check is performed when base-rev is absent.

        AC-TEST-003
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" revision="refs/tags/v3.1.4" />\n'
            '  <remove-project name="platform/core" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"Expected 'platform/core' to be removed without base-rev check but got: {project_names!r}"
        )

    def test_remove_project_empty_manifest_after_removing_only_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After removing the only project, manifest.projects is empty.

        AC-TEST-003
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

        assert manifest.projects == [], (
            f"Expected empty project list after removing the only project but got: {manifest.projects!r}"
        )

    @pytest.mark.parametrize(
        "revision",
        [
            "main",
            "refs/tags/v1.0.0",
            "refs/heads/feature-branch",
            "abc1234",
        ],
    )
    def test_remove_project_without_base_rev_removes_any_revision(
        self,
        tmp_path: pathlib.Path,
        revision: str,
    ) -> None:
        """Parameterized: remove-project without base-rev removes project at any revision.

        AC-TEST-003
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="platform/core" path="core" revision="{revision}" />\n'
            '  <remove-project name="platform/core" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"Expected 'platform/core' to be removed for revision={revision!r} but got: {project_names!r}"
        )

    def test_remove_project_multiple_successive_removals_all_apply(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Multiple <remove-project> elements each independently remove their target.

        AC-TEST-003
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <project name="platform/tools" path="tools" />\n'
            '  <project name="vendor/lib" path="lib" />\n'
            '  <remove-project name="platform/core" />\n'
            '  <remove-project name="platform/tools" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"Expected 'platform/core' to be removed by first remove-project but got: {project_names!r}"
        )
        assert "platform/tools" not in project_names, (
            f"Expected 'platform/tools' to be removed by second remove-project but got: {project_names!r}"
        )
        assert "vendor/lib" in project_names, (
            f"Expected 'vendor/lib' to remain as it was not targeted but got: {project_names!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveProjectChannelDiscipline:
    """Verify that parse errors raise exceptions rather than writing to stdout.

    The <remove-project> parser must report errors exclusively through
    exceptions; it must not write error information to stdout. Tests here
    verify that a parse error is surfaced as a ManifestParseError and not
    silently swallowed or written to stdout.

    AC-CHANNEL-001 (parser tasks: no stdout leakage for success/failure paths)
    """

    def test_valid_remove_project_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest with a valid <remove-project> does not raise ManifestParseError.

        AC-CHANNEL-001
        """
        try:
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
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid remove-project to parse without ManifestParseError but got: {exc!r}")

    def test_invalid_remove_project_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remove-project> naming a non-existent project raises ManifestParseError.

        AC-CHANNEL-001
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <remove-project name="no-such-project" />\n'
                "</manifest>\n",
            )

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got empty string"

    def test_invalid_remove_project_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """An invalid <remove-project> raises an exception, not silently writing to stdout.

        AC-CHANNEL-001
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <remove-project name="no-such-project" />\n'
                "</manifest>\n",
            )

        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout output for remove-project error but got: {captured.out!r}"
