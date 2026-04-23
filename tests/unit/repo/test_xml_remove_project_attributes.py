"""Unit tests for <remove-project> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <remove-project> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <remove-project> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <remove-project> element documented attributes:
  Required (at least one):
    name     -- project name to remove
    path     -- project relpath to remove
  Optional:
    base-rev -- guard: project revision must equal this before removal;
                raises ManifestParseError on mismatch
    optional -- bool; when True a missing target project is silently ignored;
                when False (default) a missing project raises ManifestParseError
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
class TestRemoveProjectValidValues:
    """AC-TEST-001: Every documented attribute of <remove-project> has a valid-value test.

    Each test method exercises one attribute with a legal value and asserts
    that (a) no exception is raised, and (b) the expected observable effect
    is present in the parsed manifest.
    """

    def test_name_attribute_valid_removes_project_by_name(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid name attribute removes the project with that name.

        After parsing, the named project must no longer appear in
        manifest.projects.
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
            f"AC-TEST-001: expected 'platform/core' to be absent after remove-project "
            f"name attribute but got: {project_names!r}"
        )

    def test_path_attribute_valid_removes_project_by_relpath(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid path attribute removes the project at that relpath.

        After parsing, the project whose relpath matches must no longer appear
        in manifest.projects.
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
            f"AC-TEST-001: expected 'platform/tools' to be absent after remove-project "
            f"path attribute but got: {project_names!r}"
        )

    def test_base_rev_attribute_valid_matching_removes_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid base-rev attribute that matches the project revision succeeds.

        When the project's revisionExpr equals the base-rev value, removal
        proceeds without error and the project is absent from the manifest.
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
            f"AC-TEST-001: expected 'platform/core' to be removed when base-rev matches but got: {project_names!r}"
        )

    def test_optional_attribute_valid_true_ignores_missing_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: optional='true' suppresses ManifestParseError for a missing project.

        When the named project does not exist and optional='true', the manifest
        parses without error and the rest of the projects are untouched.
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/tools" path="tools" />\n'
            '  <remove-project name="platform/absent" optional="true" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/tools" in project_names, (
            f"AC-TEST-001: expected 'platform/tools' to remain when optional=true targets "
            f"absent project but got: {project_names!r}"
        )

    def test_optional_attribute_valid_false_explicit_keeps_existing_behavior(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: optional='false' removes the project normally when it exists.

        When optional='false' is explicit and the project is present, removal
        proceeds successfully.
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <remove-project name="platform/core" optional="false" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"AC-TEST-001: expected 'platform/core' to be removed when optional=false and "
            f"project exists but got: {project_names!r}"
        )

    def test_name_and_path_together_valid_removes_matching_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: Both name and path attributes together are a valid combination.

        When both name and path are provided, the element is valid and the
        matching project is removed without error.
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
            f"AC-TEST-001: expected 'platform/core' to be removed with name+path but got: {project_names!r}"
        )

    @pytest.mark.parametrize(
        "revision_value",
        [
            "refs/tags/v1.0.0",
            "refs/heads/release",
            "abc1234def5678",
            "main",
        ],
    )
    def test_base_rev_attribute_valid_multiple_revision_formats(
        self,
        tmp_path: pathlib.Path,
        revision_value: str,
    ) -> None:
        """AC-TEST-001: base-rev accepts various revision expression formats.

        Parameterized over common revision formats to confirm none are
        incorrectly rejected by the parser.
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="platform/core" path="core" revision="{revision_value}" />\n'
            f'  <remove-project name="platform/core" base-rev="{revision_value}" />\n'
            "</manifest>\n",
        )

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" not in project_names, (
            f"AC-TEST-001: expected 'platform/core' to be removed with base-rev={revision_value!r} "
            f"but got: {project_names!r}"
        )

    @pytest.mark.parametrize(
        "optional_value",
        [
            "true",
            "True",
            "1",
            "yes",
        ],
    )
    def test_optional_attribute_truthy_values_suppress_missing_error(
        self,
        tmp_path: pathlib.Path,
        optional_value: str,
    ) -> None:
        """AC-TEST-001: All XmlBool-truthy values for optional suppress the missing-project error.

        The optional attribute is parsed via XmlBool, which accepts
        'true', 'True', '1', and 'yes' as truthy representations.
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            f'  <remove-project name="platform/absent" optional="{optional_value}" />\n'
            "</manifest>\n",
        )

        assert manifest is not None, (
            f"AC-TEST-001: expected manifest to parse without error for optional={optional_value!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Invalid-value tests -- every attribute's bad-input path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveProjectInvalidValues:
    """AC-TEST-002: Every attribute of <remove-project> has invalid-value tests.

    Each test method triggers an invalid input condition and verifies that the
    parser raises ManifestParseError with a message relevant to the problem.
    """

    def test_name_attribute_invalid_references_nonexistent_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: name referencing a non-existent project raises ManifestParseError.

        When no project with the given name has been declared, and optional is
        not set, the parser must raise ManifestParseError.
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
            f"AC-TEST-002: expected error message to mention 'platform/does-not-exist' but got: {exc_info.value!r}"
        )

    def test_path_attribute_invalid_references_nonexistent_relpath(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: path referencing a non-existent relpath raises ManifestParseError.

        When no project occupies the given relpath and optional is not set,
        the parser must raise ManifestParseError.
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <remove-project path="nonexistent-relpath" />\n'
                "</manifest>\n",
            )

        error_message = str(exc_info.value)
        assert error_message, "AC-TEST-002: expected a non-empty error message for missing path but got empty string"

    def test_base_rev_attribute_invalid_mismatch_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: base-rev that does not match the project's revision raises ManifestParseError.

        When the project's revisionExpr differs from base-rev, the parser must
        raise ManifestParseError describing the mismatch.
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
        ), f"AC-TEST-002: expected error to mention revision mismatch but got: {error_message!r}"

    def test_base_rev_mismatch_via_path_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: base-rev mismatch detected via path attribute raises ManifestParseError.

        When the removal target is identified by path and base-rev does not
        match, the parser must raise ManifestParseError.
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" revision="refs/tags/v1.0.0" />\n'
                '  <remove-project path="core" base-rev="refs/tags/v9.9.9" />\n'
                "</manifest>\n",
            )

        error_message = str(exc_info.value)
        assert (
            "mismatch" in error_message.lower()
            or "base" in error_message.lower()
            or "revision" in error_message.lower()
        ), f"AC-TEST-002: expected path-based base-rev mismatch error but got: {error_message!r}"

    def test_optional_false_explicit_missing_project_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: optional='false' with a missing project raises ManifestParseError.

        Explicit optional='false' must reject a missing project just as if the
        attribute were absent.
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

    @pytest.mark.parametrize(
        ("project_name", "base_rev_given", "actual_revision"),
        [
            ("platform/alpha", "refs/tags/v0.1.0", "refs/tags/v0.2.0"),
            ("platform/beta", "main", "develop"),
            ("platform/gamma", "abc123", "def456"),
        ],
    )
    def test_base_rev_mismatch_parametrized(
        self,
        tmp_path: pathlib.Path,
        project_name: str,
        base_rev_given: str,
        actual_revision: str,
    ) -> None:
        """AC-TEST-002: Parameterized base-rev mismatch cases all raise ManifestParseError.

        Exercises multiple mismatch combinations to confirm the revision guard
        applies consistently regardless of the specific values.
        """
        with pytest.raises(ManifestParseError):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                f'  <project name="{project_name}" path="proj" revision="{actual_revision}" />\n'
                f'  <remove-project name="{project_name}" base-rev="{base_rev_given}" />\n'
                "</manifest>\n",
            )


# ---------------------------------------------------------------------------
# AC-TEST-003: Required attribute omission raises with message naming the
#              attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveProjectRequiredAttributeOmission:
    """AC-TEST-003: Required attribute omission raises ManifestParseError naming the attribute.

    The <remove-project> element requires at least one of name or path.
    Omitting both must raise ManifestParseError, and the error message must
    name the attribute(s) involved.
    """

    def test_omit_both_name_and_path_raises_with_attribute_names(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: Omitting both name and path raises ManifestParseError.

        The error message must contain at least one of the words 'name' or
        'path' so the user knows which attribute to supply.
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
            f"AC-TEST-003: expected error to name the missing attribute ('name' or 'path') but got: {error_message!r}"
        )

    def test_omit_both_name_and_path_with_base_rev_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: Having base-rev but neither name nor path still raises ManifestParseError.

        base-rev alone is not sufficient -- name or path is required.
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <remove-project base-rev="refs/tags/v1.0.0" />\n'
                "</manifest>\n",
            )

        error_message = str(exc_info.value)
        assert "name" in error_message.lower() or "path" in error_message.lower(), (
            f"AC-TEST-003: expected error to name the missing required attribute but got: {error_message!r}"
        )

    def test_omit_both_name_and_path_with_optional_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: Having optional='true' but neither name nor path still raises.

        optional='true' suppresses the missing-project error, but the
        missing-identifier error (no name, no path) must still fire first.
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                '  <remove-project optional="true" />\n'
                "</manifest>\n",
            )

        error_message = str(exc_info.value)
        assert "name" in error_message.lower() or "path" in error_message.lower(), (
            f"AC-TEST-003: expected error about missing required attribute when optional=true "
            f"and no name/path provided but got: {error_message!r}"
        )

    def test_omit_name_and_path_error_is_manifest_parse_error_type(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: The exception type for missing required attributes is ManifestParseError.

        Confirms that ManifestParseError (not a generic Exception or ValueError)
        is the exact type raised when both name and path are omitted.
        """
        with pytest.raises(ManifestParseError):
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


# ---------------------------------------------------------------------------
# AC-FUNC-001: Every documented attribute is validated at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveProjectAttributesParsedAtLoadTime:
    """AC-FUNC-001: Every documented attribute of <remove-project> is validated at parse time.

    Confirms that attribute effects are observable immediately after XmlManifest.Load()
    returns, without any further method calls.
    """

    def test_name_validated_at_parse_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: name attribute is processed and validated during Load().

        If the named project does not exist, ManifestParseError is raised during
        Load(), not lazily on first access to manifest.projects.
        """
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <remove-project name="nonexistent" />\n'
            "</manifest>\n",
            encoding="utf-8",
        )
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_base_rev_mismatch_validated_at_parse_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: base-rev mismatch is caught during Load(), not deferred.

        The revision guard fires immediately during manifest loading so the
        caller can catch ManifestParseError from the Load() call site.
        """
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" revision="refs/tags/v1.0.0" />\n'
            '  <remove-project name="platform/core" base-rev="refs/tags/v99.0.0" />\n'
            "</manifest>\n",
            encoding="utf-8",
        )
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_optional_true_suppresses_error_at_parse_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: optional='true' suppresses the missing-project error during Load().

        The optional suppression is applied immediately in Load(); no error is
        raised even though the project is absent.
        """
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <remove-project name="platform/absent" optional="true" />\n'
            "</manifest>\n",
            encoding="utf-8",
        )
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
        m.Load()

        project_names = [p.name for p in m.projects]
        assert "platform/core" in project_names, (
            f"AC-FUNC-001: expected 'platform/core' to remain when optional=true targets "
            f"absent project but got: {project_names!r}"
        )

    def test_name_and_path_both_validated_at_parse_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: Both name and path attributes are applied during Load().

        The combined name+path filter is applied during Load() and the
        matching project is removed immediately.
        """
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            '  <remove-project name="platform/core" path="core" />\n'
            "</manifest>\n",
            encoding="utf-8",
        )
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
        m.Load()

        project_names = [p.name for p in m.projects]
        assert "platform/core" not in project_names, (
            f"AC-FUNC-001: expected 'platform/core' to be absent after name+path removal "
            f"at load time but got: {project_names!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveProjectChannelDiscipline:
    """AC-CHANNEL-001: Parser errors raise exceptions; nothing is written to stdout.

    The <remove-project> parser must surface all errors as ManifestParseError
    and must not write diagnostic output to stdout. Valid parses must also
    produce no stdout output.
    """

    def test_valid_parse_produces_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: A valid <remove-project> does not write to stdout.

        Successful parsing is silent on stdout.
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
            f"AC-CHANNEL-001: expected no stdout from valid remove-project parse but got: {captured.out!r}"
        )

    def test_missing_name_and_path_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: The missing name+path error raises, not writes to stdout.

        When ManifestParseError is raised for missing name+path, nothing is
        written to stdout; the entire error is surfaced via the exception.
        """
        with pytest.raises(ManifestParseError):
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

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout from missing-attribute error but got: {captured.out!r}"
        )

    def test_nonexistent_project_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: The nonexistent-project error raises, not writes to stdout.

        When ManifestParseError is raised for a missing project, nothing is
        written to stdout.
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
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout from nonexistent-project error but got: {captured.out!r}"
        )

    def test_base_rev_mismatch_error_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: base-rev mismatch error raises, not writes to stdout.

        When ManifestParseError is raised for a base-rev mismatch, nothing is
        written to stdout.
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
            f"AC-CHANNEL-001: expected no stdout from base-rev mismatch error but got: {captured.out!r}"
        )

    def test_invalid_remove_project_raises_manifest_parse_error_type(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-CHANNEL-001: The exception raised is specifically ManifestParseError.

        Verifies the error type contract so callers can catch the right exception
        class rather than a broad Exception.
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

        assert str(exc_info.value), (
            "AC-CHANNEL-001: expected a non-empty error message in ManifestParseError but got empty string"
        )
