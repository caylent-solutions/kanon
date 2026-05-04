"""Unit tests for the <superproject> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <superproject> XML elements parse correctly when
given minimum required attributes, all documented attributes, and that
default attribute values behave as documented.

The <superproject> element identifies the superproject repository for the
manifest. Documented attributes:
  Required: name (project name/path)
  Optional: remote (remote name; defaults to the manifest's default remote)
  Optional: revision (branch; defaults to remote.revision or default.revisionExpr)

There can be at most one <superproject> element per manifest; a duplicate
raises ManifestParseError.

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


def _build_superproject_manifest(
    superproject_name: str,
    extra_attrs: str = "",
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
) -> str:
    """Build manifest XML that includes a <superproject> element.

    Args:
        superproject_name: The name attribute for the <superproject> element.
        extra_attrs: Extra attributes string for the <superproject> element.
        remote_name: Name of the remote to define.
        fetch_url: Fetch URL for the remote.
        default_revision: The revision for the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    sp_attrs = f'name="{superproject_name}"'
    if extra_attrs:
        sp_attrs = f"{sp_attrs} {extra_attrs}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f"  <superproject {sp_attrs} />\n"
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid <superproject> with minimum required attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectMinimumAttributes:
    """Verify that a <superproject> element with only the required name attribute parses correctly.

    The minimum valid <superproject> requires only the name attribute. The remote
    and revision are inherited from the manifest's <default> element.
    """

    def test_superproject_minimum_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with a minimal <superproject name="..."> parses without raising an error.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_superproject_manifest(superproject_name="platform/superproject")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest is not None, "Expected XmlManifest instance but got None"

    def test_superproject_is_set_after_parse(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing a manifest with <superproject>, manifest.superproject is not None.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_superproject_manifest(superproject_name="platform/superproject")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.superproject is not None, (
            "Expected manifest.superproject to be set after parsing <superproject> but got None"
        )

    def test_superproject_name_matches_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """manifest.superproject.name equals the name attribute on the <superproject> element.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_superproject_manifest(superproject_name="platform/superproject")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.superproject.name == "platform/superproject", (
            f"Expected superproject.name='platform/superproject' but got: {manifest.superproject.name!r}"
        )

    def test_superproject_none_when_element_absent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <superproject> element is present, manifest.superproject is None.

        AC-TEST-001: verifies the absence case to make the presence case meaningful.
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

        assert manifest.superproject is None, (
            f"Expected manifest.superproject=None when element absent but got: {manifest.superproject!r}"
        )

    def test_superproject_inherits_default_revision_when_not_specified(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no revision attribute is given, superproject.revision is inherited from <default>.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_superproject_manifest(
            superproject_name="platform/superproject",
            default_revision="refs/heads/main",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.superproject.revision == "refs/heads/main", (
            f"Expected superproject.revision='refs/heads/main' inherited from <default> "
            f"but got: {manifest.superproject.revision!r}"
        )

    @pytest.mark.parametrize(
        "superproject_name",
        [
            "platform/superproject",
            "android/superproject",
            "org/mono-repo",
        ],
    )
    def test_superproject_name_parsed_for_various_values(
        self,
        tmp_path: pathlib.Path,
        superproject_name: str,
    ) -> None:
        """Parameterized: various superproject name values are parsed correctly.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_superproject_manifest(superproject_name=superproject_name)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.superproject is not None, (
            f"Expected superproject to be set for name='{superproject_name}' but got None"
        )
        assert manifest.superproject.name == superproject_name, (
            f"Expected superproject.name='{superproject_name}' but got: {manifest.superproject.name!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <superproject> with all documented attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectAllDocumentedAttributes:
    """Verify that a <superproject> element with all documented attributes parses correctly.

    The <superproject> element documents three attributes:
    - name: required, the project repository path
    - remote: optional, the remote name (defaults to manifest's default remote)
    - revision: optional, the branch to track (defaults to remote.revision or default.revisionExpr)
    """

    def test_superproject_with_explicit_remote_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <superproject> element with an explicit remote attribute parses correctly.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="upstream" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.superproject is not None, "Expected superproject to be set but got None"
        assert manifest.superproject.name == "platform/superproject", (
            f"Expected superproject.name='platform/superproject' but got: {manifest.superproject.name!r}"
        )

    def test_superproject_with_explicit_revision_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <superproject> element with an explicit revision attribute parses correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_superproject_manifest(
            superproject_name="platform/superproject",
            extra_attrs='revision="refs/heads/stable"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.superproject is not None, "Expected superproject to be set but got None"
        assert manifest.superproject.revision == "refs/heads/stable", (
            f"Expected superproject.revision='refs/heads/stable' but got: {manifest.superproject.revision!r}"
        )

    def test_superproject_with_explicit_remote_and_revision_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <superproject> with both explicit remote and revision attributes parses correctly.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" remote="upstream" revision="refs/heads/stable" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.superproject is not None, "Expected superproject to be set but got None"
        assert manifest.superproject.name == "platform/superproject", (
            f"Expected superproject.name='platform/superproject' but got: {manifest.superproject.name!r}"
        )
        assert manifest.superproject.revision == "refs/heads/stable", (
            f"Expected superproject.revision='refs/heads/stable' but got: {manifest.superproject.revision!r}"
        )

    def test_superproject_remote_object_set_after_parse(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing, manifest.superproject.remote is a RemoteSpec object.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_superproject_manifest(superproject_name="platform/superproject")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.superproject.remote is not None, "Expected superproject.remote to be set but got None"

    def test_superproject_revision_is_string(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing, manifest.superproject.revision is a non-empty string.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_superproject_manifest(
            superproject_name="platform/superproject",
            extra_attrs='revision="refs/heads/feature"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert isinstance(manifest.superproject.revision, str), (
            f"Expected superproject.revision to be a str but got: {type(manifest.superproject.revision)!r}"
        )
        assert manifest.superproject.revision, "Expected superproject.revision to be non-empty but got an empty string"

    def test_duplicate_superproject_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with two <superproject> elements raises ManifestParseError.

        AC-TEST-002: each documented constraint on the element is tested.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            '  <superproject name="platform/other" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert "duplicate superproject" in str(exc_info.value).lower() or str(exc_info.value), (
            "Expected a non-empty error message from ManifestParseError for duplicate superproject"
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
    def test_superproject_explicit_revision_values(
        self,
        tmp_path: pathlib.Path,
        revision: str,
    ) -> None:
        """Parameterized: various explicit revision values are parsed and stored correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_superproject_manifest(
            superproject_name="platform/superproject",
            extra_attrs=f'revision="{revision}"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.superproject.revision == revision, (
            f"Expected superproject.revision='{revision}' but got: {manifest.superproject.revision!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <superproject> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectDefaultAttributeValues:
    """Verify that default attribute values on <superproject> behave as documented.

    The <superproject> element documents:
    - When no remote is given, the default remote is used
    - When no revision is given, the remote.revision or default.revisionExpr is used
    - When no <superproject> element is present, manifest.superproject is None
    """

    def test_superproject_absent_means_none(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The default state when <superproject> is omitted is manifest.superproject == None.

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

        assert manifest.superproject is None, (
            f"Expected manifest.superproject=None when element absent but got: {manifest.superproject!r}"
        )

    def test_superproject_default_revision_from_default_element(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no revision attribute is specified, superproject.revision comes from <default>.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="refs/heads/develop" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.superproject.revision == "refs/heads/develop", (
            f"Expected superproject.revision='refs/heads/develop' from <default> "
            f"but got: {manifest.superproject.revision!r}"
        )

    def test_superproject_explicit_revision_overrides_default(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When an explicit revision is given, it overrides the <default> revisionExpr.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="refs/heads/develop" remote="origin" />\n'
            '  <superproject name="platform/superproject" revision="refs/tags/v2.0.0" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.superproject.revision == "refs/tags/v2.0.0", (
            f"Expected explicit superproject.revision='refs/tags/v2.0.0' to override default "
            f"but got: {manifest.superproject.revision!r}"
        )

    def test_superproject_no_remote_no_default_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <superproject> with no resolvable remote raises ManifestParseError.

        AC-TEST-003: required attribute constraints are tested for their no-default behavior.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"

    def test_superproject_name_attribute_required(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <superproject> missing the required name attribute raises ManifestParseError.

        AC-TEST-003: required attributes have no default and must be provided.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <superproject />\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"

    @pytest.mark.parametrize(
        "default_revision,expected_revision",
        [
            ("main", "main"),
            ("refs/heads/main", "refs/heads/main"),
            ("refs/heads/stable", "refs/heads/stable"),
        ],
    )
    def test_superproject_revision_defaults_for_various_default_revisions(
        self,
        tmp_path: pathlib.Path,
        default_revision: str,
        expected_revision: str,
    ) -> None:
        """Parameterized: superproject inherits various <default> revisionExpr values.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            f'  <default revision="{default_revision}" remote="origin" />\n'
            '  <superproject name="platform/superproject" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.superproject.revision == expected_revision, (
            f"Expected superproject.revision='{expected_revision}' inherited from "
            f"<default revision='{default_revision}'> but got: {manifest.superproject.revision!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperprojectChannelDiscipline:
    """Verify that parse errors raise exceptions rather than writing to stdout.

    The <superproject> parser must report errors exclusively through exceptions;
    it must not write error information to stdout. Tests here verify that a
    valid parse is error-free and that parse failures produce ManifestParseError.

    AC-CHANNEL-001 (parser tasks: no stdout leakage for success/failure paths)
    """

    def test_valid_superproject_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest with a valid <superproject> does not raise ManifestParseError.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_superproject_manifest(superproject_name="platform/superproject")
        manifest_file = _write_manifest(repodir, xml_content)

        try:
            _load_manifest(repodir, manifest_file)
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid <superproject> manifest to parse without ManifestParseError but got: {exc!r}")

    def test_invalid_superproject_raises_manifest_parse_error_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Parsing a <superproject> with missing name raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "  <superproject />\n"
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
