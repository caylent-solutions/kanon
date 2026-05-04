"""Unit tests for <default> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <default> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <default> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified (no cross-channel
                  leakage)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <default> element documented attributes (all optional):
  remote     -- name of a declared <remote> element
  revision   -- default branch/tag/SHA expression for projects
  dest-branch -- default destination branch for pushed changes
  upstream   -- default upstream branch
  sync-j     -- number of parallel sync jobs; must be > 0 integer
  sync-c     -- boolean; sync only the current branch; default False
  sync-s     -- boolean; sync submodules; default False
  sync-tags  -- boolean; sync tags; default True

Documented constraints for invalid-value tests:
  - remote references an undeclared remote -> ManifestParseError naming the remote
  - sync-j is a non-integer string -> ManifestParseError naming the attribute
  - sync-j is 0 or negative -> ManifestParseError (must be > 0)
  - Duplicate <default> with different attribute values -> ManifestParseError

Note: XmlBool for sync-c/sync-s/sync-tags emits a non-fatal warning to stderr
and returns the default when the value is not a recognized boolean string.
That behavior is tested here for completeness (AC-CHANNEL-001: no stdout leakage).
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


def _build_manifest_with_default(
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_attrs: str = "",
    extra_remotes: str = "",
) -> str:
    """Build a minimal manifest XML containing one <remote> and one <default> element.

    Args:
        remote_name: The name attribute for the primary <remote>.
        fetch_url: The fetch attribute for the primary <remote>.
        default_attrs: Attribute string to place on the <default> element.
        extra_remotes: Additional <remote> XML fragments inserted after the primary remote.

    Returns:
        Full XML string for the manifest.
    """
    default_elem = f"  <default {default_attrs} />\n" if default_attrs else "  <default />\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f"{extra_remotes}"
        f"{default_elem}"
        "</manifest>\n"
    )


def _build_manifest_no_remote_with_default(default_attrs: str = "") -> str:
    """Build a manifest XML with NO <remote> declarations but a <default> element.

    Used to verify that referencing an undefined remote raises ManifestParseError.

    Args:
        default_attrs: Attribute string to place on the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    default_elem = f"  <default {default_attrs} />\n" if default_attrs else "  <default />\n"
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n{default_elem}</manifest>\n'


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests -- one per documented <default> attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultValidValues:
    """AC-TEST-001: Every documented attribute of <default> has a valid-value test.

    Each method exercises one attribute with a legal value and asserts that
    (a) no exception is raised and (b) the expected observable effect on the
    parsed manifest is present.
    """

    def test_remote_attribute_valid_resolves_to_declared_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid remote attribute resolves to the declared <remote>.

        The remote attribute on <default> must reference an existing remote by
        name. After parsing, manifest.default.remote must be the corresponding
        _XmlRemote object with the declared name.
        """
        xml_content = _build_manifest_with_default(
            remote_name="origin",
            fetch_url="https://example.com",
            default_attrs='remote="origin"',
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.remote is not None, (
            "AC-TEST-001: expected default.remote to be set for valid remote attribute but got None"
        )
        assert manifest.default.remote.name == "origin", (
            f"AC-TEST-001: expected default.remote.name='origin' but got: {manifest.default.remote.name!r}"
        )

    def test_revision_attribute_valid_sets_revision_expr(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid revision attribute sets default.revisionExpr.

        The revision attribute on <default> accepts any branch name, tag, or
        SHA expression. After parsing, default.revisionExpr must match.
        """
        xml_content = _build_manifest_with_default(default_attrs='revision="main"')
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.revisionExpr == "main", (
            f"AC-TEST-001: expected default.revisionExpr='main' but got: {manifest.default.revisionExpr!r}"
        )

    def test_dest_branch_attribute_valid_sets_dest_branch_expr(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid dest-branch attribute sets default.destBranchExpr.

        The dest-branch attribute on <default> specifies the default destination
        branch for pushed changes. After parsing, default.destBranchExpr must match.
        """
        xml_content = _build_manifest_with_default(default_attrs='dest-branch="release"')
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.destBranchExpr == "release", (
            f"AC-TEST-001: expected default.destBranchExpr='release' but got: {manifest.default.destBranchExpr!r}"
        )

    def test_upstream_attribute_valid_sets_upstream_expr(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid upstream attribute sets default.upstreamExpr.

        The upstream attribute on <default> specifies the default upstream branch
        for projects. After parsing, default.upstreamExpr must match.
        """
        xml_content = _build_manifest_with_default(default_attrs='upstream="main"')
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.upstreamExpr == "main", (
            f"AC-TEST-001: expected default.upstreamExpr='main' but got: {manifest.default.upstreamExpr!r}"
        )

    def test_sync_j_attribute_valid_positive_integer_sets_sync_j(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A valid sync-j attribute with a positive integer sets default.sync_j.

        The sync-j attribute on <default> must be a positive integer. After
        parsing, default.sync_j must be the integer value.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-j="4"')
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.sync_j == 4, (
            f"AC-TEST-001: expected default.sync_j=4 but got: {manifest.default.sync_j!r}"
        )

    def test_sync_c_attribute_true_sets_sync_c(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A sync-c="true" attribute sets default.sync_c to True.

        The sync-c attribute on <default> is a boolean. The string "true" must
        parse to Python True.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-c="true"')
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.sync_c is True, (
            f"AC-TEST-001: expected default.sync_c=True for sync-c='true' but got: {manifest.default.sync_c!r}"
        )

    def test_sync_c_attribute_false_sets_sync_c(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A sync-c="false" attribute sets default.sync_c to False.

        The sync-c attribute on <default> is a boolean. The string "false" must
        parse to Python False.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-c="false"')
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.sync_c is False, (
            f"AC-TEST-001: expected default.sync_c=False for sync-c='false' but got: {manifest.default.sync_c!r}"
        )

    def test_sync_s_attribute_true_sets_sync_s(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A sync-s="true" attribute sets default.sync_s to True.

        The sync-s attribute on <default> is a boolean. The string "true" must
        parse to Python True.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-s="true"')
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.sync_s is True, (
            f"AC-TEST-001: expected default.sync_s=True for sync-s='true' but got: {manifest.default.sync_s!r}"
        )

    def test_sync_tags_attribute_false_sets_sync_tags(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A sync-tags="false" attribute sets default.sync_tags to False.

        The sync-tags attribute on <default> is a boolean with default True.
        The string "false" must parse to Python False.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-tags="false"')
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.sync_tags is False, (
            f"AC-TEST-001: expected default.sync_tags=False for sync-tags='false' but got: {manifest.default.sync_tags!r}"
        )

    def test_sync_tags_attribute_true_sets_sync_tags(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: A sync-tags="true" attribute sets default.sync_tags to True.

        Explicitly setting sync-tags to its documented default value must parse
        correctly and leave default.sync_tags as True.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-tags="true"')
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.sync_tags is True, (
            f"AC-TEST-001: expected default.sync_tags=True for sync-tags='true' but got: {manifest.default.sync_tags!r}"
        )

    @pytest.mark.parametrize(
        "bool_xml_value,expected_bool",
        [
            ("true", True),
            ("1", True),
            ("yes", True),
            ("false", False),
            ("0", False),
            ("no", False),
        ],
    )
    def test_sync_c_boolean_all_recognized_values(
        self,
        tmp_path: pathlib.Path,
        bool_xml_value: str,
        expected_bool: bool,
    ) -> None:
        """AC-TEST-001: Parameterized -- all recognized boolean strings for sync-c parse correctly.

        The XmlBool parser recognizes true/1/yes as True and false/0/no as False.
        All six recognized values must produce the expected Python bool.
        """
        xml_content = _build_manifest_with_default(default_attrs=f'sync-c="{bool_xml_value}"')
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.sync_c is expected_bool, (
            f"AC-TEST-001: expected default.sync_c={expected_bool} "
            f"for sync-c='{bool_xml_value}' but got: {manifest.default.sync_c!r}"
        )

    @pytest.mark.parametrize(
        "revision",
        [
            "main",
            "refs/heads/stable",
            "refs/tags/v2.0.0",
            "abc1234567890abcdef1234567890abcdef123456",
        ],
    )
    def test_revision_attribute_various_valid_values(
        self,
        tmp_path: pathlib.Path,
        revision: str,
    ) -> None:
        """AC-TEST-001: Parameterized -- various revision strings are accepted and stored correctly.

        The revision attribute accepts branch names, ref paths, and full SHA
        expressions; all must be stored faithfully in default.revisionExpr.
        """
        xml_content = _build_manifest_with_default(default_attrs=f'revision="{revision}"')
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.revisionExpr == revision, (
            f"AC-TEST-001: expected default.revisionExpr='{revision}' but got: {manifest.default.revisionExpr!r}"
        )

    @pytest.mark.parametrize(
        "sync_j_value",
        [1, 2, 4, 8, 16, 32],
    )
    def test_sync_j_attribute_various_positive_integer_values(
        self,
        tmp_path: pathlib.Path,
        sync_j_value: int,
    ) -> None:
        """AC-TEST-001: Parameterized -- various positive sync-j integer values parse correctly.

        Any positive integer for sync-j must be accepted and stored as an
        integer on default.sync_j.
        """
        xml_content = _build_manifest_with_default(default_attrs=f'sync-j="{sync_j_value}"')
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default.sync_j == sync_j_value, (
            f"AC-TEST-001: expected default.sync_j={sync_j_value} but got: {manifest.default.sync_j!r}"
        )

    def test_all_documented_attributes_together_parse_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001, AC-FUNC-001: A <default> with all documented attributes parses every field correctly.

        All eight attributes (remote, revision, dest-branch, upstream, sync-j,
        sync-c, sync-s, sync-tags) present simultaneously must be accepted and
        stored on the parsed default object.
        """
        xml_content = _build_manifest_with_default(
            remote_name="origin",
            fetch_url="https://example.com",
            default_attrs=(
                'remote="origin" revision="refs/heads/main" dest-branch="release" '
                'upstream="main" sync-j="8" sync-c="true" sync-s="false" sync-tags="false"'
            ),
        )
        manifest = _write_and_load(tmp_path, xml_content)

        d = manifest.default
        assert d.remote is not None, "AC-TEST-001: expected default.remote set but got None"
        assert d.remote.name == "origin", (
            f"AC-TEST-001: expected default.remote.name='origin' but got: {d.remote.name!r}"
        )
        assert d.revisionExpr == "refs/heads/main", (
            f"AC-TEST-001: expected default.revisionExpr='refs/heads/main' but got: {d.revisionExpr!r}"
        )
        assert d.destBranchExpr == "release", (
            f"AC-TEST-001: expected default.destBranchExpr='release' but got: {d.destBranchExpr!r}"
        )
        assert d.upstreamExpr == "main", (
            f"AC-TEST-001: expected default.upstreamExpr='main' but got: {d.upstreamExpr!r}"
        )
        assert d.sync_j == 8, f"AC-TEST-001: expected default.sync_j=8 but got: {d.sync_j!r}"
        assert d.sync_c is True, f"AC-TEST-001: expected default.sync_c=True but got: {d.sync_c!r}"
        assert d.sync_s is False, f"AC-TEST-001: expected default.sync_s=False but got: {d.sync_s!r}"
        assert d.sync_tags is False, f"AC-TEST-001: expected default.sync_tags=False but got: {d.sync_tags!r}"


# ---------------------------------------------------------------------------
# AC-TEST-002: Invalid-value tests -- raise ManifestParseError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultInvalidValues:
    """AC-TEST-002: Every attribute has invalid-value tests that raise ManifestParseError.

    Tests verify that illegal values are rejected at parse time with a
    ManifestParseError that carries a non-empty, actionable message.
    """

    def test_remote_referencing_undeclared_remote_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A remote attribute referencing an undeclared remote raises ManifestParseError.

        When the name given in remote="..." does not correspond to any
        previously declared <remote> element, _get_remote() must raise
        ManifestParseError naming the missing remote.
        """
        xml_content = _build_manifest_no_remote_with_default(default_attrs='remote="nonexistent"')

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message when remote attribute references undeclared remote"
        )
        assert "nonexistent" in str(exc_info.value), (
            f"AC-TEST-002: expected error message to name the missing remote 'nonexistent' "
            f"but got: {str(exc_info.value)!r}"
        )

    def test_remote_not_in_manifest_remotes_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: Referencing a remote that is declared in the manifest but with a different name raises.

        If the <default remote="..."> specifies a name that is not defined
        anywhere in the manifest's <remote> elements, ManifestParseError must
        be raised at parse time.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default remote="upstream" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "upstream" in str(exc_info.value), (
            f"AC-TEST-002: expected error message to name the missing remote 'upstream' "
            f"but got: {str(exc_info.value)!r}"
        )

    def test_sync_j_non_integer_string_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A sync-j attribute with a non-integer string raises ManifestParseError.

        XmlInt raises ManifestParseError when the attribute value cannot be
        converted to an integer. The error message must name the attribute.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-j="not_a_number"')

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), "AC-TEST-002: expected non-empty error message for non-integer sync-j value"
        assert "sync-j" in str(exc_info.value), (
            f"AC-TEST-002: expected error message to name 'sync-j' but got: {str(exc_info.value)!r}"
        )

    def test_sync_j_zero_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A sync-j="0" attribute raises ManifestParseError (must be > 0).

        The documented constraint is that sync-j must be a positive integer
        greater than 0. Zero must be rejected at parse time.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-j="0"')

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "sync-j" in str(exc_info.value), (
            f"AC-TEST-002: expected error message to name 'sync-j' but got: {str(exc_info.value)!r}"
        )

    def test_sync_j_negative_integer_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A sync-j="-1" attribute raises ManifestParseError (must be > 0).

        Any non-positive integer for sync-j must be rejected at parse time.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-j="-1"')

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "sync-j" in str(exc_info.value), (
            f"AC-TEST-002: expected error message to name 'sync-j' but got: {str(exc_info.value)!r}"
        )

    def test_duplicate_default_with_different_revision_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A second <default> with a different revision raises ManifestParseError.

        At most one non-empty <default> element may appear in a manifest.
        A second <default> with different attribute values must be rejected.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" />\n'
            '  <default revision="stable" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for duplicate <default> with different revision"
        )

    def test_duplicate_default_with_different_remote_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A second <default> with a different remote raises ManifestParseError.

        Two <default> elements with conflicting remote attributes must be rejected.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default remote="origin" />\n'
            '  <default remote="upstream" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for duplicate <default> with different remote"
        )

    def test_duplicate_default_with_different_sync_j_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: A second <default> with a different sync-j raises ManifestParseError.

        Two <default> elements with conflicting sync-j attributes must be rejected.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default sync-j="4" />\n'
            '  <default sync-j="8" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), (
            "AC-TEST-002: expected non-empty error message for duplicate <default> with different sync-j"
        )

    @pytest.mark.parametrize(
        "bad_sync_j",
        ["abc", "1.5", "  ", "1e3", "none"],
    )
    def test_sync_j_various_non_integer_strings_raise_parse_error(
        self,
        tmp_path: pathlib.Path,
        bad_sync_j: str,
    ) -> None:
        """AC-TEST-002: Parameterized -- various non-integer strings for sync-j raise ManifestParseError.

        Any value for sync-j that cannot be parsed as a Python int must
        raise ManifestParseError naming the attribute.
        """
        xml_content = _build_manifest_with_default(default_attrs=f'sync-j="{bad_sync_j}"')

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "sync-j" in str(exc_info.value), (
            f"AC-TEST-002: expected error message to name 'sync-j' for value '{bad_sync_j}' "
            f"but got: {str(exc_info.value)!r}"
        )

    @pytest.mark.parametrize(
        "non_positive_sync_j",
        [0, -1, -5, -100],
    )
    def test_sync_j_non_positive_integers_raise_parse_error(
        self,
        tmp_path: pathlib.Path,
        non_positive_sync_j: int,
    ) -> None:
        """AC-TEST-002: Parameterized -- non-positive sync-j values raise ManifestParseError.

        Zero and all negative integers must be rejected as sync-j values.
        The documented constraint is sync-j > 0.
        """
        xml_content = _build_manifest_with_default(default_attrs=f'sync-j="{non_positive_sync_j}"')

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "sync-j" in str(exc_info.value), (
            f"AC-TEST-002: expected error message to name 'sync-j' for value {non_positive_sync_j} "
            f"but got: {str(exc_info.value)!r}"
        )

    @pytest.mark.parametrize(
        "missing_remote_name",
        ["nonexistent", "missing-remote", "typo_origin"],
    )
    def test_remote_various_undeclared_names_raise_parse_error(
        self,
        tmp_path: pathlib.Path,
        missing_remote_name: str,
    ) -> None:
        """AC-TEST-002: Parameterized -- referencing various undeclared remote names raises ManifestParseError.

        Any remote name that has not been declared in a <remote> element must
        cause ManifestParseError when referenced from <default remote="...">.
        """
        xml_content = _build_manifest_no_remote_with_default(default_attrs=f'remote="{missing_remote_name}"')

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert missing_remote_name in str(exc_info.value), (
            f"AC-TEST-002: expected error message to name missing remote '{missing_remote_name}' "
            f"but got: {str(exc_info.value)!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: No strictly required attributes -- validation of referential constraints
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultRequiredAttributeConstraints:
    """AC-TEST-003: Omitting optional attributes is permitted; referential constraints raise.

    The <default> element has no strictly required attributes. However,
    the remote attribute introduces a referential constraint: the named
    remote must be declared in the manifest. Tests verify that the error
    message names the offending attribute or its invalid value.
    """

    def test_all_optional_attrs_absent_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: An empty <default /> with no attributes is valid and parses without error.

        Since all attributes of <default> are optional, omitting all of them
        must be accepted by the parser.
        """
        xml_content = _build_manifest_with_default()
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default is not None, (
            "AC-TEST-003: expected a _Default object when all attributes absent but got None"
        )

    def test_remote_attr_referencing_missing_remote_error_names_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: ManifestParseError for an undefined remote references the remote name in the message.

        When remote="..." names an undeclared remote, the error message must
        identify the missing remote by name so the user can locate and fix it.
        """
        xml_content = _build_manifest_no_remote_with_default(default_attrs='remote="undefined-remote"')

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "undefined-remote" in str(exc_info.value), (
            f"AC-TEST-003: expected error message to name 'undefined-remote' but got: {str(exc_info.value)!r}"
        )

    def test_sync_j_non_integer_error_names_the_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: ManifestParseError for invalid sync-j value names the attribute in the message.

        When sync-j has a non-integer value, the error message must name the
        attribute so the user can identify and fix the malformed XML.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-j="bad"')

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "sync-j" in str(exc_info.value), (
            f"AC-TEST-003: expected error message to name 'sync-j' attribute but got: {str(exc_info.value)!r}"
        )

    def test_sync_j_zero_error_names_the_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: ManifestParseError for sync-j=0 names the attribute in the message.

        When sync-j is zero (violating the > 0 constraint), the error message
        must name the attribute so the user can identify the violation.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-j="0"')

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert "sync-j" in str(exc_info.value), (
            f"AC-TEST-003: expected error message to name 'sync-j' attribute for value 0 "
            f"but got: {str(exc_info.value)!r}"
        )

    def test_duplicate_default_conflicting_raises_parse_error_naming_context(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: ManifestParseError for duplicate <default> elements carries a non-empty message.

        A second <default> element with different attribute values must raise
        ManifestParseError with a message indicating the duplicate.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" />\n'
            '  <default revision="develop" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        assert str(exc_info.value), "AC-TEST-003: expected non-empty error message for conflicting duplicate <default>"

    @pytest.mark.parametrize(
        "attr_to_omit,remaining_attrs",
        [
            ("remote", 'revision="main"'),
            ("revision", 'dest-branch="release"'),
            ("dest-branch", 'upstream="main"'),
            ("upstream", 'sync-j="4"'),
            ("sync-j", 'sync-c="true"'),
            ("sync-c", 'sync-s="true"'),
            ("sync-s", 'sync-tags="false"'),
            ("sync-tags", 'revision="main"'),
        ],
    )
    def test_each_optional_attribute_can_be_omitted_independently(
        self,
        tmp_path: pathlib.Path,
        attr_to_omit: str,
        remaining_attrs: str,
    ) -> None:
        """AC-TEST-003: Parameterized -- each optional attribute can be omitted independently.

        Since all <default> attributes are optional, omitting any single
        attribute while specifying others must parse without error.
        """
        xml_content = _build_manifest_with_default(
            remote_name="origin",
            fetch_url="https://example.com",
            default_attrs=remaining_attrs,
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert manifest.default is not None, (
            f"AC-TEST-003: expected successful parse when omitting '{attr_to_omit}' but manifest.default is None"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Attribute validation happens at parse time (during m.Load())
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultAttributeValidatedAtParseTime:
    """AC-FUNC-001: Every documented attribute of <default> is validated at parse time.

    Validation must be triggered during m.Load(), not deferred to a later
    pipeline stage. Tests verify that calling m.Load() is sufficient to
    surface all attribute errors immediately.
    """

    def test_invalid_sync_j_raises_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: ManifestParseError for invalid sync-j is raised during m.Load().

        Constructing XmlManifest must not itself parse the XML.
        The error must appear only when m.Load() is called.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-j="abc"')
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_undefined_remote_raises_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: ManifestParseError for an undefined remote reference is raised during m.Load().

        Constructing XmlManifest must not itself parse the XML.
        The error must appear only when m.Load() is called.
        """
        xml_content = _build_manifest_no_remote_with_default(default_attrs='remote="missing"')
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_sync_j_zero_raises_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: ManifestParseError for sync-j=0 is raised during m.Load().

        The constraint sync-j > 0 must be enforced during m.Load(),
        not deferred to a later operation.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-j="0"')
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_duplicate_default_raises_at_load_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: ManifestParseError for duplicate <default> is raised during m.Load().

        The duplicate-default check must run as part of m.Load(), not deferred.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" />\n'
            '  <default revision="stable" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_default_attributes_observable_after_load(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: All attribute values are observable on the manifest object after m.Load().

        The parser must apply all attribute values to the _Default object
        during m.Load() so they are immediately accessible to callers.
        """
        xml_content = _build_manifest_with_default(
            remote_name="origin",
            fetch_url="https://example.com",
            default_attrs='remote="origin" revision="refs/heads/stable" sync-j="2"',
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
        m.Load()

        d = m.default
        assert d.remote is not None, "AC-FUNC-001: expected default.remote set after m.Load() but got None"
        assert d.remote.name == "origin", (
            f"AC-FUNC-001: expected default.remote.name='origin' after m.Load() but got: {d.remote.name!r}"
        )
        assert d.revisionExpr == "refs/heads/stable", (
            f"AC-FUNC-001: expected default.revisionExpr='refs/heads/stable' after m.Load() but got: {d.revisionExpr!r}"
        )
        assert d.sync_j == 2, f"AC-FUNC-001: expected default.sync_j=2 after m.Load() but got: {d.sync_j!r}"


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultAttributeChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr discipline is verified (no cross-channel leakage).

    Attribute validation errors must be surfaced as exceptions, never as
    output written to stdout. Tests verify that parse failures produce
    ManifestParseError and leave stdout empty.

    Note: XmlBool emits a non-fatal warning to stderr (not stdout) when an
    unrecognized boolean string is encountered. That behavior is intentional
    and AC-CHANNEL-001 only requires that no content reaches stdout.
    """

    def test_invalid_sync_j_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: Invalid sync-j raises ManifestParseError; stdout is empty.

        No diagnostic text from the parser must reach stdout when sync-j
        contains a non-integer value.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-j="bad"')

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for invalid sync-j but got: {captured.out!r}"
        )

    def test_undefined_remote_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: Undefined remote reference raises ManifestParseError; stdout is empty.

        No diagnostic text from the parser must reach stdout when the remote
        attribute references a remote that is not declared in the manifest.
        """
        xml_content = _build_manifest_no_remote_with_default(default_attrs='remote="ghost"')

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for undefined remote but got: {captured.out!r}"
        )

    def test_sync_j_zero_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: sync-j=0 raises ManifestParseError; stdout is empty.

        No diagnostic text from the parser must reach stdout when sync-j
        violates the > 0 constraint.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-j="0"')

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, f"AC-CHANNEL-001: expected no stdout output for sync-j=0 but got: {captured.out!r}"

    def test_duplicate_default_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: Duplicate conflicting <default> raises ManifestParseError; stdout is empty.

        No diagnostic text from the parser must reach stdout when duplicate
        <default> elements with conflicting attributes are encountered.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" />\n'
            '  <default revision="stable" />\n'
            "</manifest>\n"
        )

        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for duplicate <default> but got: {captured.out!r}"
        )

    def test_valid_default_does_not_raise_and_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: A valid <default> parses without raising and without stdout output.

        Confirms that the positive path works correctly and introduces no
        spurious stdout output (no false positives from the negative tests).
        """
        xml_content = _build_manifest_with_default(
            remote_name="origin",
            fetch_url="https://example.com",
            default_attrs='remote="origin" revision="main" sync-j="4"',
        )

        try:
            _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(f"AC-CHANNEL-001: expected valid <default> to parse without error but got: {exc!r}")

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for valid <default> parse but got: {captured.out!r}"
        )

    def test_unrecognized_bool_for_sync_c_warns_to_stderr_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: An unrecognized boolean for sync-c warns to stderr, not stdout.

        XmlBool emits a non-fatal warning to sys.stderr when the attribute
        value is not one of the recognized boolean strings. This must not
        write to stdout. No exception is raised; the attribute falls back to
        its documented default.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-c="UNKNOWN_VALUE"')

        manifest = _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for unrecognized sync-c boolean but got: {captured.out!r}"
        )
        assert manifest.default.sync_c is False, (
            f"AC-CHANNEL-001: expected default.sync_c=False (fallback) for unrecognized boolean "
            f"but got: {manifest.default.sync_c!r}"
        )
