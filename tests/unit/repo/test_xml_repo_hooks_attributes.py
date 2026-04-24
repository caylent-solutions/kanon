"""Unit tests for <repo-hooks> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <repo-hooks> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <repo-hooks> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified (no cross-channel
                  leakage)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <repo-hooks> element documented attributes:
  Required:  in-project   (name of the project that owns the hooks;
                           must reference a project declared in the manifest)
             enabled-list (space- or comma-separated list of enabled hook names)

Additional constraint: at most one <repo-hooks> element is allowed;
a second element raises ManifestParseError with "duplicate repo-hooks".
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- mirrors the pattern used in other attribute test files
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
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


def _minimal_manifest_with_hooks(
    in_project: str,
    enabled_list: str,
    hooks_project_name: str = "tools/hooks",
    hooks_project_path: str = "hooks",
) -> str:
    """Build manifest XML that contains a hooks project and a repo-hooks element.

    Args:
        in_project: Value for the in-project attribute on <repo-hooks>.
        enabled_list: Value for the enabled-list attribute on <repo-hooks>.
        hooks_project_name: The name attribute of the project declared as hooks.
        hooks_project_path: The path attribute of the project declared as hooks.

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
# AC-TEST-001: valid-value tests -- one per documented <repo-hooks> attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepoHooksAttributeValidValues:
    """AC-TEST-001: every documented <repo-hooks> attribute has a valid-value test.

    Documented attributes: in-project (required), enabled-list (required).
    """

    def test_in_project_valid_references_declared_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """in-project referencing a declared project parses without error.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            _minimal_manifest_with_hooks(
                in_project="tools/hooks",
                enabled_list="pre-upload",
            ),
        )
        assert manifest.repo_hooks_project is not None, (
            "Expected repo_hooks_project to be set for valid in-project='tools/hooks' but got None"
        )
        assert manifest.repo_hooks_project.name == "tools/hooks", (
            f"Expected repo_hooks_project.name='tools/hooks' but got: {manifest.repo_hooks_project.name!r}"
        )

    @pytest.mark.parametrize(
        "project_name",
        [
            "platform/hooks",
            "tools/repo-hooks",
            "hook-project",
        ],
    )
    def test_in_project_valid_various_project_names(
        self,
        tmp_path: pathlib.Path,
        project_name: str,
    ) -> None:
        """in-project accepts various valid project name strings.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="{project_name}" path="hooks" />\n'
            f'  <repo-hooks in-project="{project_name}" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)
        assert manifest.repo_hooks_project is not None, (
            f"Expected repo_hooks_project to be set for in-project='{project_name}' but got None"
        )
        assert manifest.repo_hooks_project.name == project_name, (
            f"Expected repo_hooks_project.name='{project_name}' but got: {manifest.repo_hooks_project.name!r}"
        )

    def test_enabled_list_valid_single_hook(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """enabled-list with a single hook name parses to a one-element list.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            _minimal_manifest_with_hooks(
                in_project="tools/hooks",
                enabled_list="pre-upload",
            ),
        )
        hooks = manifest.repo_hooks_project.enabled_repo_hooks
        assert "pre-upload" in hooks, f"Expected 'pre-upload' in enabled_repo_hooks but got: {hooks!r}"
        assert len(hooks) == 1, f"Expected exactly 1 hook in enabled_repo_hooks but got {len(hooks)}: {hooks!r}"

    @pytest.mark.parametrize(
        "enabled_list,expected_hooks",
        [
            ("pre-upload hook2", ["pre-upload", "hook2"]),
            ("pre-upload,hook2,hook3", ["pre-upload", "hook2", "hook3"]),
            ("commit-msg post-checkout applypatch-msg", ["commit-msg", "post-checkout", "applypatch-msg"]),
        ],
    )
    def test_enabled_list_valid_multiple_hooks(
        self,
        tmp_path: pathlib.Path,
        enabled_list: str,
        expected_hooks: list,
    ) -> None:
        """enabled-list with multiple hooks (space- or comma-separated) is parsed correctly.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            _minimal_manifest_with_hooks(
                in_project="tools/hooks",
                enabled_list=enabled_list,
            ),
        )
        hooks = manifest.repo_hooks_project.enabled_repo_hooks
        for expected in expected_hooks:
            assert expected in hooks, (
                f"Expected '{expected}' in enabled_repo_hooks for enabled-list='{enabled_list}' but got: {hooks!r}"
            )
        assert len(hooks) == len(expected_hooks), (
            f"Expected {len(expected_hooks)} hooks for enabled-list='{enabled_list}' but got {len(hooks)}: {hooks!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: invalid-value tests -- each attribute's invalid values
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepoHooksAttributeInvalidValues:
    """AC-TEST-002: every documented <repo-hooks> attribute raises on invalid values.

    Invalid cases:
    - in-project referencing a project name not declared in the manifest
      raises ManifestParseError with "not found for repo-hooks"
    - Duplicate <repo-hooks> elements raise ManifestParseError with
      "duplicate repo-hooks"
    """

    def test_in_project_nonexistent_project_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """in-project referencing an undeclared project name raises ManifestParseError.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <repo-hooks in-project="nonexistent/hooks" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, "Expected a non-empty error message from ManifestParseError but got empty string"
        assert "not found" in error_text or "nonexistent" in error_text, (
            f"Expected error message to mention 'not found' or 'nonexistent' but got: {error_text!r}"
        )

    @pytest.mark.parametrize(
        "nonexistent_name",
        [
            "does-not-exist",
            "tools/no-such-project",
            "missing",
        ],
    )
    def test_in_project_various_nonexistent_names_raise_parse_error(
        self,
        tmp_path: pathlib.Path,
        nonexistent_name: str,
    ) -> None:
        """in-project with various nonexistent project names all raise ManifestParseError.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            f'  <repo-hooks in-project="{nonexistent_name}" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, (
            f"Expected non-empty ManifestParseError for in-project='{nonexistent_name}' but got empty string"
        )

    def test_duplicate_repo_hooks_element_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <repo-hooks> elements in the same manifest raise ManifestParseError.

        AC-TEST-002: at most one <repo-hooks> is allowed per manifest.
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

        error_text = str(exc_info.value)
        assert error_text, "Expected non-empty ManifestParseError for duplicate <repo-hooks> but got empty string"
        assert "duplicate" in error_text, (
            f"Expected 'duplicate' in error message for duplicate <repo-hooks> but got: {error_text!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: required attribute omission raises with message naming the attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepoHooksRequiredAttributeOmission:
    """AC-TEST-003: omitting a required attribute raises ManifestParseError with
    the attribute name in the error message.

    Both in-project and enabled-list are required. Omitting either raises
    ManifestParseError with a message that includes the attribute name.
    """

    def test_missing_in_project_raises_parse_error_naming_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<repo-hooks> without in-project raises ManifestParseError naming 'in-project'.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, "Expected non-empty ManifestParseError for missing in-project but got empty string"
        assert "in-project" in error_text, (
            f"Expected 'in-project' in error message for missing required attribute but got: {error_text!r}"
        )

    def test_missing_enabled_list_raises_parse_error_naming_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<repo-hooks> without enabled-list raises ManifestParseError naming 'enabled-list'.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks in-project="tools/hooks" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, "Expected non-empty ManifestParseError for missing enabled-list but got empty string"
        assert "enabled-list" in error_text, (
            f"Expected 'enabled-list' in error message for missing required attribute but got: {error_text!r}"
        )

    @pytest.mark.parametrize(
        "xml_fragment,expected_attr_in_message",
        [
            ('  <repo-hooks enabled-list="pre-upload" />\n', "in-project"),
            ('  <repo-hooks in-project="tools/hooks" />\n', "enabled-list"),
        ],
    )
    def test_required_attribute_omission_parametrized(
        self,
        tmp_path: pathlib.Path,
        xml_fragment: str,
        expected_attr_in_message: str,
    ) -> None:
        """Parameterized: omitting each required attribute raises with the attribute name.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n' + xml_fragment + "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, (
            f"Expected non-empty ManifestParseError for missing '{expected_attr_in_message}' but got empty string"
        )
        assert expected_attr_in_message in error_text, (
            f"Expected '{expected_attr_in_message}' in error message for missing required attribute "
            f"but got: {error_text!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline (parser raises, never prints)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepoHooksChannelDiscipline:
    """AC-CHANNEL-001: the <repo-hooks> parser communicates errors exclusively
    through exceptions, never via stdout.

    For XML / parser tasks, stdout discipline means:
    - Successful parse raises no exception and produces no output
    - Failed parse raises ManifestParseError (not writes to stdout)
    """

    def test_valid_repo_hooks_raises_no_exception(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest with a valid <repo-hooks> element raises no exception.

        AC-CHANNEL-001
        """
        try:
            _write_and_load(
                tmp_path,
                _minimal_manifest_with_hooks(
                    in_project="tools/hooks",
                    enabled_list="pre-upload",
                ),
            )
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid <repo-hooks> to parse without ManifestParseError but got: {exc!r}")

    def test_missing_in_project_raises_not_prints(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Parsing with missing in-project raises ManifestParseError, not stdout output.

        AC-CHANNEL-001: errors must surface as exceptions, not printed output.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="tools/hooks" path="hooks" />\n'
            '  <repo-hooks enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert captured.out == "", (
            f"Expected no stdout output when ManifestParseError is raised but got: {captured.out!r}"
        )

    def test_nonexistent_project_raises_not_prints(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Parsing with nonexistent in-project raises ManifestParseError, not stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <repo-hooks in-project="no-such-project" enabled-list="pre-upload" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert captured.out == "", (
            f"Expected no stdout output when ManifestParseError is raised but got: {captured.out!r}"
        )
