"""Unit tests for <remote> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <remote> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <remote> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified (no cross-channel
                  leakage)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <remote> element documented attributes:
  Required:  name      (remote identifier; used in git config; no default)
  Required:  fetch     (Git URL prefix for all projects; no default)
  Optional:  alias     (overrides name in per-project .git/config; no default)
  Optional:  pushurl   (separate push URL prefix; defaults to fetch URL)
  Optional:  review    (Gerrit review server hostname; no default)
  Optional:  revision  (default branch for projects using this remote; no default)

Additional constraints:
  - Duplicate remotes with identical attributes are idempotent (accepted silently).
  - Duplicate remotes with different attributes raise ManifestParseError.
  - Empty-string values for required attributes are treated as missing and
    raise ManifestParseError.
  - The <remote> element may contain zero or more <annotation> child elements.
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


def _build_remote_xml(
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    extra_attrs: str = "",
    annotation_elements: str = "",
    default_revision: str = "main",
) -> str:
    """Build a minimal valid manifest XML containing one <remote> element.

    Args:
        remote_name: Value for the name attribute on <remote>.
        fetch_url: Value for the fetch attribute on <remote>.
        extra_attrs: Additional XML attribute string appended to the <remote> element.
        annotation_elements: Optional child <annotation> elements as raw XML.
        default_revision: Revision value for the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    remote_attrs = f'name="{remote_name}" fetch="{fetch_url}"'
    if extra_attrs:
        remote_attrs = f"{remote_attrs} {extra_attrs}"

    if annotation_elements:
        remote_elem = f"  <remote {remote_attrs}>\n{annotation_elements}  </remote>\n"
    else:
        remote_elem = f"  <remote {remote_attrs} />\n"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f"{remote_elem}"
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests -- one per documented <remote> attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteValidValues:
    """AC-TEST-001: Every documented attribute of <remote> has a valid-value test.

    Each test method exercises one attribute with a legal value and asserts
    that (a) no exception is raised and (b) the expected observable effect
    on the parsed manifest is present.
    """

    def test_name_attribute_valid_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid name attribute is accepted and registered in manifest.remotes.

        The name attribute is required and uniquely identifies the remote.
        After parsing, manifest.remotes[name] must be present.
        """
        manifest = _write_and_load(tmp_path, _build_remote_xml(remote_name="origin"))

        assert "origin" in manifest.remotes, (
            "AC-TEST-001: expected 'origin' in manifest.remotes after parsing valid name attribute"
        )
        assert manifest.remotes["origin"].name == "origin", (
            f"AC-TEST-001: expected remote.name='origin' but got: {manifest.remotes['origin'].name!r}"
        )

    def test_fetch_attribute_valid_is_stored_as_fetch_url(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid fetch attribute is stored as remote.fetchUrl.

        The fetch attribute is required and supplies the base URL prefix
        for all project repositories using this remote.
        """
        manifest = _write_and_load(tmp_path, _build_remote_xml(fetch_url="https://git.example.com/org"))

        remote = manifest.remotes["origin"]
        assert remote.fetchUrl == "https://git.example.com/org", (
            f"AC-TEST-001: expected remote.fetchUrl='https://git.example.com/org' but got: {remote.fetchUrl!r}"
        )

    def test_alias_attribute_valid_is_stored_as_remote_alias(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid alias attribute is stored as remote.remoteAlias.

        The alias attribute is optional and overrides the remote name used
        in per-project .git/config entries.
        """
        manifest = _write_and_load(tmp_path, _build_remote_xml(extra_attrs='alias="upstream"'))

        remote = manifest.remotes["origin"]
        assert remote.remoteAlias == "upstream", (
            f"AC-TEST-001: expected remote.remoteAlias='upstream' but got: {remote.remoteAlias!r}"
        )

    def test_pushurl_attribute_valid_is_stored_as_push_url(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid pushurl attribute is stored as remote.pushUrl.

        The pushurl attribute is optional and specifies a separate URL prefix
        used when pushing; projects fall back to fetch URL when pushUrl is None.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_remote_xml(extra_attrs='pushurl="https://push.example.com"'),
        )

        remote = manifest.remotes["origin"]
        assert remote.pushUrl == "https://push.example.com", (
            f"AC-TEST-001: expected remote.pushUrl='https://push.example.com' but got: {remote.pushUrl!r}"
        )

    def test_review_attribute_valid_is_stored_as_review_url(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid review attribute is stored as remote.reviewUrl.

        The review attribute is optional and specifies the Gerrit review server
        hostname. When absent, remote.reviewUrl is None.
        """
        manifest = _write_and_load(tmp_path, _build_remote_xml(extra_attrs='review="review.example.com"'))

        remote = manifest.remotes["origin"]
        assert remote.reviewUrl == "review.example.com", (
            f"AC-TEST-001: expected remote.reviewUrl='review.example.com' but got: {remote.reviewUrl!r}"
        )

    def test_revision_attribute_valid_is_stored_as_revision(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid revision attribute is stored as remote.revision.

        The revision attribute is optional and provides the default branch
        for all projects that use this remote and do not declare their own.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_remote_xml(extra_attrs='revision="refs/heads/main"'),
        )

        remote = manifest.remotes["origin"]
        assert remote.revision == "refs/heads/main", (
            f"AC-TEST-001: expected remote.revision='refs/heads/main' but got: {remote.revision!r}"
        )

    @pytest.mark.parametrize(
        "attr_name,attr_value,field_name,expected_value",
        [
            ("alias", "upstream", "remoteAlias", "upstream"),
            ("alias", "alt-origin", "remoteAlias", "alt-origin"),
            ("pushurl", "https://push.corp.com/repos", "pushUrl", "https://push.corp.com/repos"),
            ("review", "gerrit.corp.com", "reviewUrl", "gerrit.corp.com"),
            ("revision", "refs/heads/stable", "revision", "refs/heads/stable"),
            ("revision", "refs/tags/v1.0.0", "revision", "refs/tags/v1.0.0"),
        ],
    )
    def test_optional_attribute_various_valid_values(
        self,
        tmp_path: pathlib.Path,
        attr_name: str,
        attr_value: str,
        field_name: str,
        expected_value: str,
    ) -> None:
        """AC-TEST-001: Parameterized valid values for each optional attribute are stored correctly.

        Each optional attribute must accept a range of valid string values and
        store them on the parsed remote object without raising any exception.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_remote_xml(extra_attrs=f'{attr_name}="{attr_value}"'),
        )

        remote = manifest.remotes["origin"]
        actual = getattr(remote, field_name)
        assert actual == expected_value, (
            f"AC-TEST-001: expected remote.{field_name}='{expected_value}' "
            f"for {attr_name}='{attr_value}' but got: {actual!r}"
        )

    @pytest.mark.parametrize(
        "remote_name,fetch_url",
        [
            ("origin", "https://github.com/org"),
            ("upstream", "https://gitlab.example.com/group"),
            ("caylent", "git://git.caylent.com/platform"),
        ],
    )
    def test_name_and_fetch_valid_for_various_urls(
        self,
        tmp_path: pathlib.Path,
        remote_name: str,
        fetch_url: str,
    ) -> None:
        """AC-TEST-001: Parameterized valid name and fetch combinations parse correctly.

        Various remote name strings and URL schemes must all be accepted
        and stored faithfully on the parsed remote object.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_remote_xml(remote_name=remote_name, fetch_url=fetch_url),
        )

        assert remote_name in manifest.remotes, (
            f"AC-TEST-001: expected '{remote_name}' in manifest.remotes but it was not found"
        )
        remote = manifest.remotes[remote_name]
        assert remote.fetchUrl == fetch_url, (
            f"AC-TEST-001: expected remote.fetchUrl='{fetch_url}' but got: {remote.fetchUrl!r}"
        )

    def test_all_attributes_together_parse_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001, AC-FUNC-001: A <remote> with all documented attributes present parses correctly.

        All six attributes (name, fetch, alias, pushurl, review, revision) are
        accepted and stored correctly when present simultaneously.
        """
        manifest = _write_and_load(
            tmp_path,
            _build_remote_xml(
                remote_name="origin",
                fetch_url="https://fetch.example.com",
                extra_attrs=(
                    'alias="upstream" '
                    'pushurl="https://push.example.com" '
                    'review="review.example.com" '
                    'revision="refs/heads/stable"'
                ),
            ),
        )

        remote = manifest.remotes["origin"]
        assert remote.name == "origin", f"AC-TEST-001: remote.name expected 'origin' got {remote.name!r}"
        assert remote.fetchUrl == "https://fetch.example.com", (
            f"AC-TEST-001: remote.fetchUrl expected 'https://fetch.example.com' got {remote.fetchUrl!r}"
        )
        assert remote.remoteAlias == "upstream", (
            f"AC-TEST-001: remote.remoteAlias expected 'upstream' got {remote.remoteAlias!r}"
        )
        assert remote.pushUrl == "https://push.example.com", (
            f"AC-TEST-001: remote.pushUrl expected 'https://push.example.com' got {remote.pushUrl!r}"
        )
        assert remote.reviewUrl == "review.example.com", (
            f"AC-TEST-001: remote.reviewUrl expected 'review.example.com' got {remote.reviewUrl!r}"
        )
        assert remote.revision == "refs/heads/stable", (
            f"AC-TEST-001: remote.revision expected 'refs/heads/stable' got {remote.revision!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Invalid-value tests -- raise ManifestParseError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteInvalidValues:
    """AC-TEST-002: Every attribute has invalid-value tests that raise ManifestParseError.

    Tests verify that illegal values are rejected at parse time with a
    ManifestParseError that carries a non-empty, actionable message.
    """

    def test_duplicate_remote_different_fetch_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: Duplicate <remote name> with different fetch URLs raises ManifestParseError.

        A second <remote> declaration with the same name but a different
        fetch attribute value must be rejected immediately.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://first.example.com" />\n'
            '  <remote name="origin" fetch="https://second.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for duplicate remote with different attributes"
        )
        assert "origin" in str(exc_info.value), (
            f"AC-TEST-002: expected error message to name the conflicting remote 'origin' "
            f"but got: {str(exc_info.value)!r}"
        )

    def test_duplicate_remote_different_alias_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: Duplicate <remote name> with different alias values raises ManifestParseError.

        All attributes participate in the equality check; differing alias
        values on remotes with the same name must be rejected.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" alias="a1" />\n'
            '  <remote name="origin" fetch="https://example.com" alias="a2" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for duplicate remote with different alias"
        )

    def test_duplicate_remote_different_revision_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: Duplicate <remote name> with different revision values raises ManifestParseError.

        A second declaration of the same remote name with a different revision
        attribute must be rejected with ManifestParseError.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" revision="main" />\n'
            '  <remote name="origin" fetch="https://example.com" revision="stable" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for duplicate remote with different revision"
        )

    def test_duplicate_remote_different_review_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: Duplicate <remote name> with different review values raises ManifestParseError.

        A second declaration of the same remote name with a different review
        attribute must be rejected with ManifestParseError.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" review="review1.example.com" />\n'
            '  <remote name="origin" fetch="https://example.com" review="review2.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for duplicate remote with different review"
        )

    def test_duplicate_remote_different_pushurl_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: Duplicate <remote name> with different pushurl values raises ManifestParseError.

        A second declaration of the same remote name with a different pushurl
        attribute must be rejected with ManifestParseError.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" pushurl="https://push1.example.com" />\n'
            '  <remote name="origin" fetch="https://example.com" pushurl="https://push2.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for duplicate remote with different pushurl"
        )

    @pytest.mark.parametrize(
        "different_attr,first_value,second_value",
        [
            ("fetch", "https://first.example.com", "https://second.example.com"),
            ("alias", "first-alias", "second-alias"),
            ("revision", "main", "stable"),
        ],
    )
    def test_duplicate_remote_various_conflicting_attrs_raise_parse_error(
        self,
        tmp_path: pathlib.Path,
        different_attr: str,
        first_value: str,
        second_value: str,
    ) -> None:
        """AC-TEST-002: Parameterized conflicting attribute values in duplicate remote raise ManifestParseError.

        When any attribute differs between two <remote> elements with the same
        name, ManifestParseError must be raised.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="origin" fetch="https://example.com" {different_attr}="{first_value}" />\n'
            f'  <remote name="origin" fetch="https://example.com" {different_attr}="{second_value}" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            f"AC-TEST-002: expected non-empty error message for duplicate remote with conflicting {different_attr}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Required attribute omission raises with message naming the attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteRequiredAttributeOmission:
    """AC-TEST-003: Required attribute omission raises ManifestParseError naming the attribute.

    The <remote> element has exactly two required attributes: name and fetch.
    Omitting either must raise ManifestParseError with a message that identifies
    the missing attribute by name, enabling the user to quickly locate and fix
    the problem.
    """

    def test_name_omitted_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: Omitting the required name attribute raises ManifestParseError.

        An <remote> without a name attribute cannot be registered and must
        be rejected at parse time.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_name_omitted_error_message_names_the_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: The ManifestParseError for missing name attribute includes 'name' in the message.

        The _reqatt helper produces a message of the form
        'no <attname> in <remote> within <manifestFile>', so the attribute
        name must appear in the exception message.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "name" in str(exc_info.value), (
            f"AC-TEST-003: expected error message to name the missing attribute 'name' but got: {str(exc_info.value)!r}"
        )

    def test_fetch_omitted_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: Omitting the required fetch attribute raises ManifestParseError.

        An <remote> without a fetch attribute has no URL prefix and must
        be rejected at parse time.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_fetch_omitted_error_message_names_the_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: The ManifestParseError for missing fetch attribute includes 'fetch' in the message.

        The _reqatt helper produces a message that includes the missing
        attribute name, allowing the user to identify the missing element.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "fetch" in str(exc_info.value), (
            f"AC-TEST-003: expected error message to name the missing attribute 'fetch' "
            f"but got: {str(exc_info.value)!r}"
        )

    def test_name_empty_string_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: An empty-string name attribute is treated as missing and raises ManifestParseError.

        The _reqatt helper returns the attribute value only when non-empty.
        An empty string for a required attribute is equivalent to omission.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_fetch_empty_string_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: An empty-string fetch attribute is treated as missing and raises ManifestParseError.

        The _reqatt helper returns the attribute value only when non-empty.
        An empty string for a required attribute is equivalent to omission.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    @pytest.mark.parametrize(
        "missing_attr,xml_fragment",
        [
            ("name", '<remote fetch="https://example.com" />'),
            ("fetch", '<remote name="origin" />'),
        ],
    )
    def test_required_attribute_omission_parameterized(
        self,
        tmp_path: pathlib.Path,
        missing_attr: str,
        xml_fragment: str,
    ) -> None:
        """AC-TEST-003: Parameterized -- each required attribute omission raises ManifestParseError.

        Both required attributes (name, fetch) must each independently cause
        ManifestParseError when absent, and the error message must name the
        missing attribute.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f"  {xml_fragment}\n"
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert missing_attr in str(exc_info.value), (
            f"AC-TEST-003: expected error message to name missing attribute '{missing_attr}' "
            f"but got: {str(exc_info.value)!r}"
        )

    def test_duplicate_identical_remote_is_idempotent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: Declaring the same <remote> twice with identical attributes does not raise.

        When all attributes match between two <remote> declarations with the
        same name, the second declaration is silently ignored (idempotent).
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        manifest = _write_and_load(tmp_path, xml_content)

        assert "origin" in manifest.remotes, (
            "AC-TEST-003: expected 'origin' in manifest.remotes after duplicate identical remote"
        )
        assert manifest.remotes["origin"].fetchUrl == "https://example.com", (
            f"AC-TEST-003: expected fetchUrl='https://example.com' after idempotent duplicate "
            f"but got: {manifest.remotes['origin'].fetchUrl!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Attribute validation happens at parse time (during m.Load())
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteAttributeValidatedAtParseTime:
    """AC-FUNC-001: Every documented attribute of <remote> is validated at parse time.

    Validation must be triggered during m.Load(), not deferred to a later
    pipeline stage. Tests verify that calling m.Load() is sufficient to
    surface all attribute errors immediately.
    """

    def test_missing_name_raises_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: ManifestParseError raised during m.Load() for missing name.

        Constructing XmlManifest must not itself parse the XML;
        the error must appear only when m.Load() is called.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        # Construction must not raise -- error is deferred until Load().
        with pytest.raises(ManifestParseError):
            m.Load()

    def test_missing_fetch_raises_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: ManifestParseError raised during m.Load() for missing fetch.

        Constructing XmlManifest must not itself parse the XML;
        the error must appear only when m.Load() is called.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        # Construction must not raise -- error is deferred until Load().
        with pytest.raises(ManifestParseError):
            m.Load()

    def test_conflicting_duplicate_raises_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: ManifestParseError raised during m.Load() for conflicting duplicate remote.

        The duplicate remote check runs during the parse phase triggered by
        m.Load(). No deferred validation is permitted.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://first.example.com" />\n'
            '  <remote name="origin" fetch="https://second.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        # Construction must not raise -- error is deferred until Load().
        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_remote_attributes_observable_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: All optional attributes are observable on the manifest object after m.Load().

        The parser must apply all attribute values to the remote object
        during m.Load() so they are immediately accessible to callers.
        """
        xml_content = _build_remote_xml(
            remote_name="origin",
            fetch_url="https://fetch.example.com",
            extra_attrs='alias="upstream" revision="refs/heads/main"',
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
        m.Load()

        remote = m.remotes["origin"]
        assert remote.remoteAlias == "upstream", (
            f"AC-FUNC-001: expected remote.remoteAlias='upstream' after m.Load() but got: {remote.remoteAlias!r}"
        )
        assert remote.revision == "refs/heads/main", (
            f"AC-FUNC-001: expected remote.revision='refs/heads/main' after m.Load() but got: {remote.revision!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteAttributeChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr discipline is verified (no cross-channel leakage).

    Attribute validation errors must be surfaced as exceptions, never as
    output written to stdout. Tests verify that parse failures produce
    ManifestParseError and leave stdout empty.
    """

    def test_missing_name_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: Missing name attribute raises ManifestParseError; stdout is empty.

        No diagnostic text from the parser must reach stdout when the
        required name attribute is absent.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output when name attribute is missing but got: {captured.out!r}"
        )

    def test_missing_fetch_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: Missing fetch attribute raises ManifestParseError; stdout is empty.

        No diagnostic text from the parser must reach stdout when the
        required fetch attribute is absent.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output when fetch attribute is missing but got: {captured.out!r}"
        )

    def test_conflicting_duplicate_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: Conflicting duplicate remote raises ManifestParseError; stdout is empty.

        No diagnostic text from the parser must reach stdout when duplicate
        remotes with conflicting attributes are encountered.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://first.example.com" />\n'
            '  <remote name="origin" fetch="https://second.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for conflicting duplicate remote but got: {captured.out!r}"
        )

    def test_valid_remote_does_not_raise_and_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: A valid <remote> parses without raising and without stdout output.

        Confirms that the positive path works correctly and introduces no
        spurious stdout output (no false positives from the negative tests).
        """
        xml_content = _build_remote_xml(remote_name="origin", fetch_url="https://example.com")

        try:
            _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(f"AC-CHANNEL-001: expected valid <remote> to parse without error but got: {exc!r}")

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for valid <remote> parse but got: {captured.out!r}"
        )
