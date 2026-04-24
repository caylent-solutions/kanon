"""Unit tests for the <contactinfo> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <contactinfo> XML elements parse correctly when
given minimum required attributes, all documented attributes, and that
default attribute values behave as documented.

The <contactinfo> element provides a custom bug-report URL for the manifest.
Documented attributes:
  Required: bugurl (URL for the project's bug tracker)

The element may be repeated; later entries clobber earlier ones. When no
<contactinfo> element is present, manifest.contactinfo.bugurl is the
default value from Wrapper().BUG_URL.

All tests use real manifest files written to tmp_path via shared helpers.
The conftest in tests/unit/repo/ auto-applies @pytest.mark.unit to every
item collected under that directory.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError
from kanon_cli.repo.wrapper import Wrapper


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


def _build_contactinfo_manifest(
    bugurl: str,
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
) -> str:
    """Build manifest XML that includes a <contactinfo> element.

    Args:
        bugurl: The bugurl attribute for the <contactinfo> element.
        remote_name: Name of the remote to define.
        fetch_url: Fetch URL for the remote.
        default_revision: The revision for the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f'  <contactinfo bugurl="{bugurl}" />\n'
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid <contactinfo> with minimum required attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContactInfoMinimumAttributes:
    """Verify that a <contactinfo> element with only the required bugurl attribute parses correctly.

    The minimum (and only) required attribute for <contactinfo> is bugurl. There are
    no optional attributes -- the element is entirely defined by this single URL.
    """

    def test_contactinfo_minimum_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with a minimal <contactinfo bugurl="..."> parses without raising an error.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_contactinfo_manifest(bugurl="https://bugs.example.com/issues")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest is not None, "Expected XmlManifest instance but got None"

    def test_contactinfo_is_set_after_parse(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing a manifest with <contactinfo>, manifest.contactinfo is not None.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_contactinfo_manifest(bugurl="https://bugs.example.com/issues")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.contactinfo is not None, (
            "Expected manifest.contactinfo to be set after parsing <contactinfo> but got None"
        )

    def test_contactinfo_bugurl_matches_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """manifest.contactinfo.bugurl equals the bugurl attribute on the <contactinfo> element.

        AC-TEST-001
        """
        expected_url = "https://bugs.example.com/issues"
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_contactinfo_manifest(bugurl=expected_url)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.contactinfo.bugurl == expected_url, (
            f"Expected contactinfo.bugurl='{expected_url}' but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_contactinfo_bugurl_is_string(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """manifest.contactinfo.bugurl is a non-empty string after parsing.

        AC-TEST-001
        """
        expected_url = "https://bugs.example.com/issues"
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_contactinfo_manifest(bugurl=expected_url)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert isinstance(manifest.contactinfo.bugurl, str), (
            f"Expected contactinfo.bugurl to be a str but got: {type(manifest.contactinfo.bugurl)!r}"
        )
        assert manifest.contactinfo.bugurl, "Expected contactinfo.bugurl to be non-empty but got an empty string"

    @pytest.mark.parametrize(
        "bugurl",
        [
            "https://bugs.example.com/issues",
            "https://github.com/my-org/my-repo/issues",
            "https://jira.example.com/projects/PROJ",
        ],
    )
    def test_contactinfo_bugurl_parsed_for_various_values(
        self,
        tmp_path: pathlib.Path,
        bugurl: str,
    ) -> None:
        """Parameterized: various bugurl values are parsed and stored correctly.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_contactinfo_manifest(bugurl=bugurl)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.contactinfo is not None, f"Expected contactinfo to be set for bugurl='{bugurl}' but got None"
        assert manifest.contactinfo.bugurl == bugurl, (
            f"Expected contactinfo.bugurl='{bugurl}' but got: {manifest.contactinfo.bugurl!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <contactinfo> with all documented attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContactInfoAllDocumentedAttributes:
    """Verify that a <contactinfo> element with all documented attributes parses correctly.

    The <contactinfo> element documents exactly one attribute:
    - bugurl: required, the URL for the project's bug tracker

    There are no optional attributes. This class verifies the full attribute surface.
    """

    def test_contactinfo_with_https_bugurl_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <contactinfo> with an HTTPS bugurl parses correctly.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_contactinfo_manifest(bugurl="https://bugs.example.com/issues")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.contactinfo is not None, "Expected contactinfo to be set but got None"
        assert manifest.contactinfo.bugurl == "https://bugs.example.com/issues", (
            f"Expected contactinfo.bugurl='https://bugs.example.com/issues' but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_contactinfo_bugurl_stored_verbatim(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The bugurl attribute value is stored verbatim without modification.

        AC-TEST-002
        """
        bugurl = "https://example.com/bugs/project/myproject/component/core"
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <contactinfo bugurl="{bugurl}" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.contactinfo.bugurl == bugurl, (
            f"Expected contactinfo.bugurl to be stored verbatim as '{bugurl}' but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_contactinfo_missing_bugurl_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <contactinfo> element without the required bugurl attribute raises ManifestParseError.

        AC-TEST-002: required attribute constraints are tested.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <contactinfo />\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"

    def test_duplicate_contactinfo_last_wins(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When <contactinfo> appears multiple times, the last entry's bugurl is used.

        AC-TEST-002: repeated elements clobber earlier ones per the documented behavior.
        """
        first_url = "https://first.example.com/issues"
        second_url = "https://second.example.com/issues"
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <contactinfo bugurl="{first_url}" />\n'
            f'  <contactinfo bugurl="{second_url}" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.contactinfo.bugurl == second_url, (
            f"Expected last <contactinfo> bugurl='{second_url}' to win but got: {manifest.contactinfo.bugurl!r}"
        )

    @pytest.mark.parametrize(
        "bugurl",
        [
            "https://bugs.example.com/issues",
            "https://github.com/org/repo/issues",
            "https://gitlab.com/group/project/-/issues",
            "https://jira.company.com/browse/PROJ",
        ],
    )
    def test_contactinfo_all_attribute_values_parsed(
        self,
        tmp_path: pathlib.Path,
        bugurl: str,
    ) -> None:
        """Parameterized: various bugurl formats are parsed and stored correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_contactinfo_manifest(bugurl=bugurl)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.contactinfo.bugurl == bugurl, (
            f"Expected contactinfo.bugurl='{bugurl}' but got: {manifest.contactinfo.bugurl!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <contactinfo> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContactInfoDefaultAttributeValues:
    """Verify that default attribute values on <contactinfo> behave as documented.

    When no <contactinfo> element is present, manifest.contactinfo.bugurl is
    initialized to Wrapper().BUG_URL. When a <contactinfo> element is present,
    its bugurl overrides the default.
    """

    def test_contactinfo_absent_uses_default_bugurl(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <contactinfo> element is present, contactinfo.bugurl is Wrapper().BUG_URL.

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

        default_bugurl = Wrapper().BUG_URL
        assert manifest.contactinfo.bugurl == default_bugurl, (
            f"Expected contactinfo.bugurl='{default_bugurl}' (default) when element absent "
            f"but got: {manifest.contactinfo.bugurl!r}"
        )

    def test_contactinfo_explicit_bugurl_overrides_default(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An explicit <contactinfo bugurl="..."> overrides the default Wrapper().BUG_URL.

        AC-TEST-003
        """
        custom_url = "https://custom.bugs.example.com/issues"
        default_bugurl = Wrapper().BUG_URL
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_contactinfo_manifest(bugurl=custom_url)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.contactinfo.bugurl == custom_url, (
            f"Expected explicit contactinfo.bugurl='{custom_url}' to override default "
            f"'{default_bugurl}' but got: {manifest.contactinfo.bugurl!r}"
        )
        assert manifest.contactinfo.bugurl != default_bugurl, (
            f"Expected explicit bugurl to differ from default '{default_bugurl}' "
            f"but contactinfo.bugurl='{manifest.contactinfo.bugurl!r}'"
        )

    def test_contactinfo_default_is_not_none(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """manifest.contactinfo is never None -- even without a <contactinfo> element.

        AC-TEST-003: the manifest initializes contactinfo to a ContactInfo with
        the default bugurl, so contactinfo is always set.
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

        assert manifest.contactinfo is not None, (
            "Expected manifest.contactinfo to always be set (not None) but got None"
        )

    def test_contactinfo_default_bugurl_is_a_nonempty_string(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The default contactinfo.bugurl is a non-empty string.

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

        assert isinstance(manifest.contactinfo.bugurl, str), (
            f"Expected default contactinfo.bugurl to be a str but got: {type(manifest.contactinfo.bugurl)!r}"
        )
        assert manifest.contactinfo.bugurl, (
            "Expected default contactinfo.bugurl to be non-empty but got an empty string"
        )

    @pytest.mark.parametrize(
        "bugurl",
        [
            "https://bugs.example.com/issues",
            "https://github.com/org/repo/issues",
        ],
    )
    def test_contactinfo_explicit_bugurl_overrides_for_various_values(
        self,
        tmp_path: pathlib.Path,
        bugurl: str,
    ) -> None:
        """Parameterized: various explicit bugurl values each override the default.

        AC-TEST-003
        """
        default_bugurl = Wrapper().BUG_URL
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_contactinfo_manifest(bugurl=bugurl)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.contactinfo.bugurl == bugurl, (
            f"Expected contactinfo.bugurl='{bugurl}' to override default "
            f"'{default_bugurl}' but got: {manifest.contactinfo.bugurl!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContactInfoChannelDiscipline:
    """Verify that parse errors raise exceptions rather than writing to stdout.

    The <contactinfo> parser must report errors exclusively through exceptions;
    it must not write error information to stdout. Tests here verify that a
    valid parse is error-free and that parse failures produce ManifestParseError.

    AC-CHANNEL-001 (parser tasks: no stdout leakage for success/failure paths)
    """

    def test_valid_contactinfo_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest with a valid <contactinfo> does not raise ManifestParseError.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_contactinfo_manifest(bugurl="https://bugs.example.com/issues")
        manifest_file = _write_manifest(repodir, xml_content)

        try:
            _load_manifest(repodir, manifest_file)
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid <contactinfo> manifest to parse without ManifestParseError but got: {exc!r}")

    def test_invalid_contactinfo_raises_manifest_parse_error_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Parsing a <contactinfo> with missing bugurl raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <contactinfo />\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"Expected no stdout output when ManifestParseError is raised but got: {captured.out!r}"
        )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"
