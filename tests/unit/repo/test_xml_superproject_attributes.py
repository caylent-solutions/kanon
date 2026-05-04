"""Unit tests for <superproject> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <superproject> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <superproject> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified (no cross-channel
                  leakage)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <superproject> element documented attributes:
  Required:  name      (project repository path; no default)
  Optional:  remote    (remote name; defaults to manifest default remote)
  Optional:  revision  (branch/tag; defaults to remote.revision or
                        default.revisionExpr)

Additional constraints:
  - At most one <superproject> element is allowed; a duplicate raises
    ManifestParseError with "duplicate superproject".
  - When remote is given but does not reference a declared remote,
    ManifestParseError is raised.
  - When no remote can be resolved (no explicit remote AND no default remote),
    ManifestParseError is raised.
  - When no revision can be resolved (no explicit revision AND no default),
    ManifestParseError is raised.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- mirrors the pattern used in test_xml_repo_hooks_attributes.py
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


def _minimal_valid_superproject(
    superproject_name: str = "platform/superproject",
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
    extra_sp_attrs: str = "",
) -> str:
    """Build a minimal valid manifest XML with a <superproject> element.

    Args:
        superproject_name: Value for the name attribute on <superproject>.
        remote_name: Name of the remote to declare.
        fetch_url: Fetch URL for the remote declaration.
        default_revision: The revision used in the <default> element.
        extra_sp_attrs: Extra attribute string to append to the <superproject> tag.

    Returns:
        Full XML string for the manifest.
    """
    sp_attrs = f'name="{superproject_name}"'
    if extra_sp_attrs:
        sp_attrs = f"{sp_attrs} {extra_sp_attrs}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f"  <superproject {sp_attrs} />\n"
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: valid-value tests -- one per documented <superproject> attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectAttributeValidValues:
    """AC-TEST-001: every documented <superproject> attribute has a valid-value test.

    Documented attributes: name (required), remote (optional), revision (optional).
    """

    def test_name_valid_simple_path(self, tmp_path: pathlib.Path) -> None:
        """A <superproject name="platform/superproject"> parses without error.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(tmp_path, _minimal_valid_superproject())
        assert manifest.superproject is not None, "Expected manifest.superproject to be set for valid name but got None"
        assert manifest.superproject.name == "platform/superproject", (
            f"Expected superproject.name='platform/superproject' but got: {manifest.superproject.name!r}"
        )

    @pytest.mark.parametrize(
        "superproject_name",
        [
            "platform/superproject",
            "android/superproject",
            "org/mono-repo",
            "single-name",
        ],
    )
    def test_name_valid_various_values(
        self,
        tmp_path: pathlib.Path,
        superproject_name: str,
    ) -> None:
        """Parameterized: various valid name values are accepted and stored correctly.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            _minimal_valid_superproject(superproject_name=superproject_name),
        )
        assert manifest.superproject is not None, (
            f"Expected superproject to be set for name='{superproject_name}' but got None"
        )
        assert manifest.superproject.name == superproject_name, (
            f"Expected superproject.name='{superproject_name}' but got: {manifest.superproject.name!r}"
        )

    def test_remote_valid_explicit_named_remote(self, tmp_path: pathlib.Path) -> None:
        """A <superproject remote="upstream"> referencing a declared remote parses correctly.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="upstream" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)
        assert manifest.superproject is not None, (
            "Expected superproject to be set for valid explicit remote but got None"
        )
        assert manifest.superproject.name == "platform/superproject", (
            f"Expected superproject.name='platform/superproject' but got: {manifest.superproject.name!r}"
        )

    def test_remote_valid_default_remote_used_when_omitted(self, tmp_path: pathlib.Path) -> None:
        """When remote is omitted, the manifest default remote is used.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(tmp_path, _minimal_valid_superproject())
        assert manifest.superproject is not None, (
            "Expected superproject to be set when remote is inherited from default but got None"
        )
        assert manifest.superproject.remote is not None, (
            "Expected superproject.remote to be a RemoteSpec object but got None"
        )

    def test_revision_valid_explicit_branch(self, tmp_path: pathlib.Path) -> None:
        """A <superproject revision="refs/heads/stable"> stores the revision correctly.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            _minimal_valid_superproject(extra_sp_attrs='revision="refs/heads/stable"'),
        )
        assert manifest.superproject is not None, "Expected superproject to be set for explicit revision but got None"
        assert manifest.superproject.revision == "refs/heads/stable", (
            f"Expected superproject.revision='refs/heads/stable' but got: {manifest.superproject.revision!r}"
        )

    @pytest.mark.parametrize(
        "revision",
        [
            "main",
            "refs/heads/main",
            "refs/heads/stable",
            "refs/tags/v1.0.0",
        ],
    )
    def test_revision_valid_various_values(self, tmp_path: pathlib.Path, revision: str) -> None:
        """Parameterized: various valid revision values are accepted and stored correctly.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            _minimal_valid_superproject(extra_sp_attrs=f'revision="{revision}"'),
        )
        assert manifest.superproject is not None, (
            f"Expected superproject to be set for revision='{revision}' but got None"
        )
        assert manifest.superproject.revision == revision, (
            f"Expected superproject.revision='{revision}' but got: {manifest.superproject.revision!r}"
        )

    def test_revision_valid_inherited_from_default_when_omitted(self, tmp_path: pathlib.Path) -> None:
        """When revision is omitted, the <default> revisionExpr is used.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            _minimal_valid_superproject(default_revision="refs/heads/develop"),
        )
        assert manifest.superproject is not None, (
            "Expected superproject to be set when revision is inherited from default but got None"
        )
        assert manifest.superproject.revision == "refs/heads/develop", (
            f"Expected superproject.revision='refs/heads/develop' inherited from <default> "
            f"but got: {manifest.superproject.revision!r}"
        )

    def test_all_three_attributes_explicit(self, tmp_path: pathlib.Path) -> None:
        """A <superproject> with all three attributes explicit parses correctly.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/sp" remote="upstream" revision="refs/tags/v2.0" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)
        assert manifest.superproject is not None, (
            "Expected superproject to be set for all-explicit attributes but got None"
        )
        assert manifest.superproject.name == "platform/sp", (
            f"Expected superproject.name='platform/sp' but got: {manifest.superproject.name!r}"
        )
        assert manifest.superproject.revision == "refs/tags/v2.0", (
            f"Expected superproject.revision='refs/tags/v2.0' but got: {manifest.superproject.revision!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: invalid-value tests -- each attribute's invalid value raises
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectAttributeInvalidValues:
    """AC-TEST-002: every documented <superproject> attribute raises on invalid values.

    Invalid cases:
    - remote referencing a non-existent remote name raises ManifestParseError
    - Duplicate <superproject> elements raise ManifestParseError with
      "duplicate superproject"
    - <superproject> without a resolvable remote raises ManifestParseError
    - <superproject> without a resolvable revision raises ManifestParseError
    """

    def test_remote_referencing_undeclared_remote_raises_parse_error(self, tmp_path: pathlib.Path) -> None:
        """remote="no-such-remote" raises ManifestParseError because that remote is undeclared.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="no-such-remote" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, "Expected non-empty ManifestParseError for undeclared remote but got empty string"
        assert "no-such-remote" in error_text or "not defined" in error_text, (
            f"Expected error message to mention the undeclared remote name or 'not defined' but got: {error_text!r}"
        )

    @pytest.mark.parametrize(
        "undeclared_remote",
        [
            "does-not-exist",
            "missing-remote",
            "no-such",
        ],
    )
    def test_remote_various_undeclared_names_raise_parse_error(
        self, tmp_path: pathlib.Path, undeclared_remote: str
    ) -> None:
        """Parameterized: various undeclared remote names raise ManifestParseError.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <superproject name="platform/superproject" remote="{undeclared_remote}" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, (
            f"Expected non-empty ManifestParseError for undeclared remote='{undeclared_remote}' but got empty string"
        )

    def test_duplicate_superproject_element_raises_parse_error(self, tmp_path: pathlib.Path) -> None:
        """Two <superproject> elements in the same manifest raise ManifestParseError.

        AC-TEST-002: at most one <superproject> element is allowed per manifest.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            '  <superproject name="platform/other" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, "Expected non-empty ManifestParseError for duplicate <superproject> but got empty string"
        assert "duplicate" in error_text.lower(), (
            f"Expected 'duplicate' in error message for duplicate <superproject> but got: {error_text!r}"
        )

    def test_no_resolvable_remote_raises_parse_error(self, tmp_path: pathlib.Path) -> None:
        """When no remote can be resolved (no default, no explicit), ManifestParseError is raised.

        AC-TEST-002: the remote attribute cannot be omitted without a default remote.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, "Expected non-empty ManifestParseError when no remote is resolvable but got empty string"

    def test_no_resolvable_revision_raises_parse_error(self, tmp_path: pathlib.Path) -> None:
        """When no revision can be resolved (no explicit, no default), ManifestParseError is raised.

        AC-TEST-002: the revision attribute cannot be omitted without a default revision.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, "Expected non-empty ManifestParseError when no revision is resolvable but got empty string"


# ---------------------------------------------------------------------------
# AC-TEST-003: required attribute omission raises with message naming the attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectRequiredAttributeOmission:
    """AC-TEST-003: omitting the required name attribute raises ManifestParseError
    with the attribute name in the error message.

    The name attribute is the only required attribute. The parser reads it via
    _reqatt which produces a message containing the attribute name.
    """

    def test_missing_name_raises_parse_error(self, tmp_path: pathlib.Path) -> None:
        """<superproject/> without a name attribute raises ManifestParseError.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <superproject />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, "Expected non-empty ManifestParseError for missing name but got empty string"

    def test_missing_name_error_message_names_attribute(self, tmp_path: pathlib.Path) -> None:
        """ManifestParseError for missing name includes 'name' in the error message.

        AC-TEST-003: the error message must identify which attribute was missing.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <superproject />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert "name" in error_text, (
            f"Expected 'name' in error message for missing required attribute but got: {error_text!r}"
        )

    def test_name_empty_string_raises_parse_error(self, tmp_path: pathlib.Path) -> None:
        """<superproject name=""> with an empty name raises ManifestParseError.

        AC-TEST-003: an empty attribute value is treated as absent by _reqatt.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, "Expected non-empty ManifestParseError for empty name attribute but got empty string"

    @pytest.mark.parametrize(
        "xml_superproject_tag,expected_attr_in_message",
        [
            ("  <superproject />\n", "name"),
            ('  <superproject name="" />\n', "name"),
        ],
    )
    def test_missing_or_empty_name_parametrized(
        self,
        tmp_path: pathlib.Path,
        xml_superproject_tag: str,
        expected_attr_in_message: str,
    ) -> None:
        """Parameterized: absent and empty name both raise ManifestParseError naming 'name'.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n' + xml_superproject_tag + "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_text = str(exc_info.value)
        assert error_text, (
            f"Expected non-empty ManifestParseError for missing/empty '{expected_attr_in_message}' but got empty string"
        )
        assert expected_attr_in_message in error_text, (
            f"Expected '{expected_attr_in_message}' in error message but got: {error_text!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline (parser raises, never prints)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectChannelDiscipline:
    """AC-CHANNEL-001: the <superproject> parser communicates errors exclusively
    through exceptions, never via stdout.

    For XML / parser tasks, stdout discipline means:
    - Successful parse raises no exception and produces no output
    - Failed parse raises ManifestParseError (not writes to stdout)
    """

    def test_valid_superproject_raises_no_exception(self, tmp_path: pathlib.Path) -> None:
        """Parsing a manifest with a valid <superproject> element raises no exception.

        AC-CHANNEL-001
        """
        try:
            _write_and_load(tmp_path, _minimal_valid_superproject())
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid <superproject> manifest to parse without ManifestParseError but got: {exc!r}")

    def test_missing_name_raises_not_prints(self, tmp_path: pathlib.Path, capsys) -> None:
        """Parsing <superproject/> without name raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001: errors must surface as exceptions, not printed output.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <superproject />\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert captured.out == "", (
            f"Expected no stdout output when ManifestParseError is raised but got: {captured.out!r}"
        )

    def test_undeclared_remote_raises_not_prints(self, tmp_path: pathlib.Path, capsys) -> None:
        """Parsing with an undeclared remote raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="undeclared-remote" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert captured.out == "", (
            f"Expected no stdout output when ManifestParseError is raised but got: {captured.out!r}"
        )

    def test_duplicate_superproject_raises_not_prints(self, tmp_path: pathlib.Path, capsys) -> None:
        """Parsing with duplicate <superproject> raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            '  <superproject name="platform/other" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert captured.out == "", (
            f"Expected no stdout output when ManifestParseError is raised but got: {captured.out!r}"
        )
