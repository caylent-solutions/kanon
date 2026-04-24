"""Unit tests for the <repo-hooks> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <repo-hooks> XML elements parse correctly when
given minimum required attributes, all documented attributes, and that
default attribute values behave as documented.

The <repo-hooks> element identifies one project as the hooks project and
lists which hooks within that project are enabled. Documented attributes:
  Required: in-project (name of the hooks project)
  Required: enabled-list (space or comma-separated list of hook names)

The enabled-list may contain one or more hook names, and the list is
parsed with whitespace and commas as separators (empty elements discarded).

All tests use real manifest files written to tmp_path via shared helpers.
The conftest in tests/unit/repo/ auto-applies @pytest.mark.unit to every
item collected under that directory.
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


def _build_manifest_with_hooks(
    in_project: str,
    enabled_list: str,
    hooks_project_name: str = "tools/hooks",
    hooks_project_path: str = "hooks",
) -> str:
    """Build manifest XML that includes a hooks project and a repo-hooks element.

    Args:
        in_project: The value of the in-project attribute on repo-hooks.
        enabled_list: The value of the enabled-list attribute on repo-hooks.
        hooks_project_name: The name attribute of the hooks project.
        hooks_project_path: The path attribute of the hooks project.

    Returns:
        Full XML string for the manifest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        f'  <project name="{hooks_project_name}" path="{hooks_project_path}" />\n'
        f'  <repo-hooks in-project="{in_project}" enabled-list="{enabled_list}" />\n'
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid <repo-hooks> with minimum required attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepoHooksMinimumAttributes:
    """Verify that a <repo-hooks> element with only required attributes parses correctly.

    The minimum valid <repo-hooks> requires in-project and enabled-list.
    Both are required; the parser raises ManifestParseError when either is absent.
    """

    def test_repo_hooks_minimum_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with a minimal <repo-hooks> element parses without raising an error.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_hooks(
            in_project="tools/hooks",
            enabled_list="pre-upload",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest is not None, "Expected XmlManifest instance but got None"

    def test_repo_hooks_project_is_set_after_parse(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing, manifest.repo_hooks_project is not None.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_hooks(
            in_project="tools/hooks",
            enabled_list="pre-upload",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.repo_hooks_project is not None, (
            "Expected manifest.repo_hooks_project to be set after parsing <repo-hooks> but got None"
        )

    def test_repo_hooks_project_name_matches_in_project_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """manifest.repo_hooks_project.name equals the in-project attribute value.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_hooks(
            in_project="tools/hooks",
            enabled_list="pre-upload",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.repo_hooks_project.name == "tools/hooks", (
            f"Expected repo_hooks_project.name='tools/hooks' but got: {manifest.repo_hooks_project.name!r}"
        )

    def test_repo_hooks_single_hook_in_enabled_repo_hooks(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A single hook name in enabled-list is present in enabled_repo_hooks.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_hooks(
            in_project="tools/hooks",
            enabled_list="pre-upload",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert "pre-upload" in manifest.repo_hooks_project.enabled_repo_hooks, (
            f"Expected 'pre-upload' in enabled_repo_hooks but got: {manifest.repo_hooks_project.enabled_repo_hooks!r}"
        )

    def test_repo_hooks_none_when_no_repo_hooks_element(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <repo-hooks> element is present, manifest.repo_hooks_project is None.

        AC-TEST-001: verifies the absence case so the presence case is meaningful.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.repo_hooks_project is None, (
            f"Expected manifest.repo_hooks_project=None when no <repo-hooks> "
            f"element is present but got: {manifest.repo_hooks_project!r}"
        )

    @pytest.mark.parametrize(
        "project_name,hook_name",
        [
            ("platform/hooks", "pre-upload"),
            ("tools/repo-hooks", "commit-msg"),
            ("infra/hook-project", "post-checkout"),
        ],
    )
    def test_repo_hooks_project_name_parsed_for_various_values(
        self,
        tmp_path: pathlib.Path,
        project_name: str,
        hook_name: str,
    ) -> None:
        """Parameterized: in-project and enabled-list values are parsed correctly.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="{project_name}" path="hooks" />\n'
            f'  <repo-hooks in-project="{project_name}" enabled-list="{hook_name}" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.repo_hooks_project is not None, (
            f"Expected repo_hooks_project to be set for in-project='{project_name}' but got None"
        )
        assert manifest.repo_hooks_project.name == project_name, (
            f"Expected repo_hooks_project.name='{project_name}' but got: {manifest.repo_hooks_project.name!r}"
        )
        assert hook_name in manifest.repo_hooks_project.enabled_repo_hooks, (
            f"Expected '{hook_name}' in enabled_repo_hooks but got: {manifest.repo_hooks_project.enabled_repo_hooks!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <repo-hooks> with all documented attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepoHooksAllDocumentedAttributes:
    """Verify that a <repo-hooks> element with all documented attributes parses correctly.

    The <repo-hooks> element documents two attributes:
    - in-project: required, names the project that owns the hooks
    - enabled-list: required, space or comma separated list of enabled hook names

    Multiple hook names in enabled-list are all preserved after parsing.
    """

    def test_repo_hooks_multiple_hooks_space_separated(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Space-separated hook names in enabled-list are each present in enabled_repo_hooks.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_hooks(
            in_project="tools/hooks",
            enabled_list="pre-upload commit-msg",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        hooks = manifest.repo_hooks_project.enabled_repo_hooks
        assert "pre-upload" in hooks, f"Expected 'pre-upload' in enabled_repo_hooks but got: {hooks!r}"
        assert "commit-msg" in hooks, f"Expected 'commit-msg' in enabled_repo_hooks but got: {hooks!r}"

    def test_repo_hooks_multiple_hooks_comma_separated(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Comma-separated hook names in enabled-list are each present in enabled_repo_hooks.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_hooks(
            in_project="tools/hooks",
            enabled_list="pre-upload,commit-msg",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        hooks = manifest.repo_hooks_project.enabled_repo_hooks
        assert "pre-upload" in hooks, f"Expected 'pre-upload' in enabled_repo_hooks but got: {hooks!r}"
        assert "commit-msg" in hooks, f"Expected 'commit-msg' in enabled_repo_hooks but got: {hooks!r}"

    def test_repo_hooks_multiple_hooks_count_matches(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The count of parsed hooks matches the number of names in enabled-list.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_hooks(
            in_project="tools/hooks",
            enabled_list="pre-upload commit-msg post-checkout",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        hooks = manifest.repo_hooks_project.enabled_repo_hooks
        assert len(hooks) == 3, f"Expected 3 hooks in enabled_repo_hooks but got {len(hooks)}: {hooks!r}"

    def test_repo_hooks_in_project_points_to_project_in_manifest(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """repo_hooks_project refers to the same Project object loaded from manifest projects.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_hooks(
            in_project="tools/hooks",
            enabled_list="pre-upload",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project_names = [p.name for p in manifest.projects]
        assert manifest.repo_hooks_project.name in project_names, (
            f"Expected repo_hooks_project.name '{manifest.repo_hooks_project.name}' "
            f"to be in the manifest projects list but got: {project_names!r}"
        )

    def test_repo_hooks_hooks_stored_on_project_object(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing, enabled_repo_hooks is set on the Project object itself.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_hooks(
            in_project="tools/hooks",
            enabled_list="pre-upload",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project_map = {p.name: p for p in manifest.projects}
        hooks_project = project_map["tools/hooks"]
        assert hasattr(hooks_project, "enabled_repo_hooks"), (
            "Expected enabled_repo_hooks attribute on the hooks project but it is absent"
        )
        assert "pre-upload" in hooks_project.enabled_repo_hooks, (
            f"Expected 'pre-upload' in hooks_project.enabled_repo_hooks but got: {hooks_project.enabled_repo_hooks!r}"
        )

    @pytest.mark.parametrize(
        "enabled_list,expected_hooks",
        [
            ("pre-upload", ["pre-upload"]),
            ("pre-upload commit-msg", ["pre-upload", "commit-msg"]),
            ("pre-upload,commit-msg,post-checkout", ["pre-upload", "commit-msg", "post-checkout"]),
            (
                "pre-upload commit-msg post-checkout applypatch-msg",
                ["pre-upload", "commit-msg", "post-checkout", "applypatch-msg"],
            ),
        ],
    )
    def test_enabled_list_parsed_for_various_hook_counts(
        self,
        tmp_path: pathlib.Path,
        enabled_list: str,
        expected_hooks: list,
    ) -> None:
        """Parameterized: enabled-list values with varying hook counts are all parsed.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_hooks(
            in_project="tools/hooks",
            enabled_list=enabled_list,
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        hooks = manifest.repo_hooks_project.enabled_repo_hooks
        for expected in expected_hooks:
            assert expected in hooks, (
                f"Expected '{expected}' in enabled_repo_hooks for enabled-list='{enabled_list}' but got: {hooks!r}"
            )
        assert len(hooks) == len(expected_hooks), (
            f"Expected {len(expected_hooks)} hooks for enabled-list='{enabled_list}' but got {len(hooks)}: {hooks!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <repo-hooks> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepoHooksDefaultAttributeValues:
    """Verify that default attribute values on <repo-hooks> behave as documented.

    The <repo-hooks> element has no optional attributes with defaults -- both
    in-project and enabled-list are required. The documented default behavior:
    - When no <repo-hooks> element is present, manifest.repo_hooks_project is None
    - A single-hook enabled-list results in a list of one element
    - Whitespace-only entries in enabled-list are discarded
    """

    def test_repo_hooks_absent_means_no_hooks_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The default state when <repo-hooks> is omitted is no hooks project.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.repo_hooks_project is None, (
            f"Expected manifest.repo_hooks_project=None when element absent but got: {manifest.repo_hooks_project!r}"
        )

    def test_repo_hooks_single_hook_produces_list_of_one(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A single hook name in enabled-list produces a list with exactly one element.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_hooks(
            in_project="tools/hooks",
            enabled_list="pre-upload",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        hooks = manifest.repo_hooks_project.enabled_repo_hooks
        assert len(hooks) == 1, f"Expected exactly 1 hook in enabled_repo_hooks but got {len(hooks)}: {hooks!r}"
        assert hooks[0] == "pre-upload", f"Expected hooks[0]='pre-upload' but got: {hooks[0]!r}"

    def test_repo_hooks_enabled_list_mixed_separators(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Hooks separated by a mix of spaces and commas are all parsed correctly.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_hooks(
            in_project="tools/hooks",
            enabled_list="pre-upload, commit-msg",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        hooks = manifest.repo_hooks_project.enabled_repo_hooks
        assert "pre-upload" in hooks, f"Expected 'pre-upload' in enabled_repo_hooks but got: {hooks!r}"
        assert "commit-msg" in hooks, f"Expected 'commit-msg' in enabled_repo_hooks but got: {hooks!r}"
        assert len(hooks) == 2, f"Expected exactly 2 hooks but got {len(hooks)}: {hooks!r}"

    def test_repo_hooks_project_is_also_a_normal_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The hooks project appears in manifest.projects alongside other projects.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/build" path="build" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="tools/hooks" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project_names = [p.name for p in manifest.projects]
        assert "platform/build" in project_names, (
            f"Expected 'platform/build' in manifest.projects but got: {project_names!r}"
        )
        assert "tools/hooks" in project_names, f"Expected 'tools/hooks' in manifest.projects but got: {project_names!r}"
        assert manifest.repo_hooks_project is not None, "Expected manifest.repo_hooks_project to be set but got None"
        assert manifest.repo_hooks_project.name == "tools/hooks", (
            f"Expected repo_hooks_project.name='tools/hooks' but got: {manifest.repo_hooks_project.name!r}"
        )

    def test_repo_hooks_missing_in_project_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <repo-hooks> missing the required in-project attribute raises ManifestParseError.

        AC-TEST-003: required attributes have no default and must be provided.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"

    def test_repo_hooks_missing_enabled_list_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <repo-hooks> missing the required enabled-list attribute raises ManifestParseError.

        AC-TEST-003: required attributes have no default and must be provided.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="tools/hooks" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepoHooksChannelDiscipline:
    """Verify that parse errors raise exceptions rather than writing to stdout.

    The <repo-hooks> parser must report errors exclusively through exceptions;
    it must not write error information to stdout. Tests here verify that a
    valid parse is error-free and that parse failures produce ManifestParseError.

    AC-CHANNEL-001 (parser tasks: no stdout leakage for success/failure paths)
    """

    def test_valid_repo_hooks_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest with valid <repo-hooks> does not raise ManifestParseError.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_hooks(
            in_project="tools/hooks",
            enabled_list="pre-upload",
        )
        manifest_file = _write_manifest(repodir, xml_content)

        try:
            _load_manifest(repodir, manifest_file)
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid <repo-hooks> manifest to parse without ManifestParseError but got: {exc!r}")

    def test_repo_hooks_nonexistent_project_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <repo-hooks> referencing a nonexistent project raises ManifestParseError.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <repo-hooks in-project="nonexistent/hooks" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"
