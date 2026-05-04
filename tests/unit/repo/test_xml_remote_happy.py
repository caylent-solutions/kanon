"""Unit tests for the <remote> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <remote> XML elements parse correctly when
given minimum required attributes, all documented attributes, and that
default attribute values behave as documented.

The <remote> element declares a named Git remote. Documented attributes:
  Required: name (remote identifier used in git config)
  Required: fetch (Git URL prefix for all projects)
  Optional: alias (overrides name in per-project .git/config)
  Optional: pushurl (separate push URL prefix; defaults to fetch)
  Optional: review (Gerrit review server hostname)
  Optional: revision (default branch for projects using this remote)

The <remote> element may contain zero or more <annotation> child elements.
Multiple remotes can be declared; each must have a unique name.

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


def _build_remote_manifest(
    remote_name: str,
    fetch_url: str,
    extra_remote_attrs: str = "",
    annotation_elements: str = "",
    default_revision: str = "main",
) -> str:
    """Build manifest XML containing one <remote> element.

    Args:
        remote_name: The name attribute for the <remote> element.
        fetch_url: The fetch attribute for the <remote> element.
        extra_remote_attrs: Extra attributes string for the <remote> element.
        annotation_elements: Optional child <annotation> elements as raw XML.
        default_revision: The revision for the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    remote_attrs = f'name="{remote_name}" fetch="{fetch_url}"'
    if extra_remote_attrs:
        remote_attrs = f"{remote_attrs} {extra_remote_attrs}"

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
# AC-TEST-001: Valid <remote> with minimum required attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteMinimumAttributes:
    """Verify that a <remote> element with only the required attributes parses correctly.

    The minimum valid <remote> requires name and fetch. All optional attributes
    (alias, pushurl, review, revision) must be absent and therefore None.
    """

    def test_remote_minimum_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with a minimal <remote name="..." fetch="..."> parses without error.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest is not None, "Expected XmlManifest instance but got None"

    def test_remote_is_registered_after_parse(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing, the named remote appears in manifest.remotes.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert "origin" in manifest.remotes, "Expected 'origin' in manifest.remotes after parsing but it was not found"

    def test_remote_name_matches_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """manifest.remotes[name].name equals the name attribute on the <remote> element.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="myremote",
            fetch_url="https://git.example.com",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["myremote"]
        assert remote.name == "myremote", f"Expected remote.name='myremote' but got: {remote.name!r}"

    def test_remote_fetch_url_matches_attribute(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """manifest.remotes[name].fetchUrl equals the fetch attribute on the <remote> element.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://git.example.com/org",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.fetchUrl == "https://git.example.com/org", (
            f"Expected remote.fetchUrl='https://git.example.com/org' but got: {remote.fetchUrl!r}"
        )

    def test_remote_optional_attrs_are_none_when_absent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When optional attributes are omitted, they are None on the parsed remote.

        AC-TEST-001: minimum-attribute parse leaves all optional fields at their default (None).
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.remoteAlias is None, (
            f"Expected remote.remoteAlias=None when alias absent but got: {remote.remoteAlias!r}"
        )
        assert remote.pushUrl is None, f"Expected remote.pushUrl=None when pushurl absent but got: {remote.pushUrl!r}"
        assert remote.reviewUrl is None, (
            f"Expected remote.reviewUrl=None when review absent but got: {remote.reviewUrl!r}"
        )
        assert remote.revision is None, (
            f"Expected remote.revision=None when revision absent but got: {remote.revision!r}"
        )

    def test_remote_annotations_empty_when_no_child_elements(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <annotation> child elements are present, remote.annotations is empty.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.annotations == [], (
            f"Expected remote.annotations=[] when no annotation children but got: {remote.annotations!r}"
        )

    @pytest.mark.parametrize(
        "remote_name,fetch_url",
        [
            ("origin", "https://github.com/org"),
            ("upstream", "https://gitlab.example.com/group"),
            ("caylent", "git://git.caylent.com/platform"),
        ],
    )
    def test_remote_name_and_fetch_parsed_for_various_values(
        self,
        tmp_path: pathlib.Path,
        remote_name: str,
        fetch_url: str,
    ) -> None:
        """Parameterized: various remote name and fetch URL values are parsed correctly.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name=remote_name,
            fetch_url=fetch_url,
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert remote_name in manifest.remotes, f"Expected '{remote_name}' in manifest.remotes but it was not found"
        remote = manifest.remotes[remote_name]
        assert remote.name == remote_name, f"Expected remote.name='{remote_name}' but got: {remote.name!r}"
        assert remote.fetchUrl == fetch_url, f"Expected remote.fetchUrl='{fetch_url}' but got: {remote.fetchUrl!r}"


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <remote> with all documented attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteAllDocumentedAttributes:
    """Verify that a <remote> element with all documented attributes parses correctly.

    The <remote> element documents six attributes:
    - name: required, the remote identifier
    - fetch: required, the Git URL prefix
    - alias: optional, overrides name in per-project .git/config
    - pushurl: optional, separate push URL prefix
    - review: optional, Gerrit review server hostname
    - revision: optional, default branch for projects using this remote
    """

    def test_remote_with_alias_attribute_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remote> element with an alias attribute parses the alias correctly.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
            extra_remote_attrs='alias="upstream"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.remoteAlias == "upstream", (
            f"Expected remote.remoteAlias='upstream' but got: {remote.remoteAlias!r}"
        )

    def test_remote_with_pushurl_attribute_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remote> element with a pushurl attribute parses the pushUrl correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://fetch.example.com",
            extra_remote_attrs='pushurl="https://push.example.com"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.pushUrl == "https://push.example.com", (
            f"Expected remote.pushUrl='https://push.example.com' but got: {remote.pushUrl!r}"
        )

    def test_remote_with_review_attribute_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remote> element with a review attribute parses the reviewUrl correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
            extra_remote_attrs='review="review.example.com"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.reviewUrl == "review.example.com", (
            f"Expected remote.reviewUrl='review.example.com' but got: {remote.reviewUrl!r}"
        )

    def test_remote_with_revision_attribute_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remote> element with a revision attribute parses the revision correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
            extra_remote_attrs='revision="refs/heads/main"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.revision == "refs/heads/main", (
            f"Expected remote.revision='refs/heads/main' but got: {remote.revision!r}"
        )

    def test_remote_with_all_optional_attributes_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remote> element with all optional attributes set parses all values correctly.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://fetch.example.com",
            extra_remote_attrs=(
                'alias="upstream" '
                'pushurl="https://push.example.com" '
                'review="review.example.com" '
                'revision="refs/heads/stable"'
            ),
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.name == "origin", f"Expected remote.name='origin' but got: {remote.name!r}"
        assert remote.fetchUrl == "https://fetch.example.com", (
            f"Expected remote.fetchUrl='https://fetch.example.com' but got: {remote.fetchUrl!r}"
        )
        assert remote.remoteAlias == "upstream", (
            f"Expected remote.remoteAlias='upstream' but got: {remote.remoteAlias!r}"
        )
        assert remote.pushUrl == "https://push.example.com", (
            f"Expected remote.pushUrl='https://push.example.com' but got: {remote.pushUrl!r}"
        )
        assert remote.reviewUrl == "review.example.com", (
            f"Expected remote.reviewUrl='review.example.com' but got: {remote.reviewUrl!r}"
        )
        assert remote.revision == "refs/heads/stable", (
            f"Expected remote.revision='refs/heads/stable' but got: {remote.revision!r}"
        )

    def test_remote_with_annotation_child_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remote> element with an <annotation> child parses the annotation correctly.

        AC-TEST-002: <remote> may contain annotation child elements.
        """
        repodir = _make_repo_dir(tmp_path)
        annotation_xml = '    <annotation name="team" value="platform" keep="true" />\n'
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
            annotation_elements=annotation_xml,
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert len(remote.annotations) == 1, f"Expected 1 annotation on remote but got: {len(remote.annotations)}"
        annotation = remote.annotations[0]
        assert annotation.name == "team", f"Expected annotation.name='team' but got: {annotation.name!r}"
        assert annotation.value == "platform", f"Expected annotation.value='platform' but got: {annotation.value!r}"

    def test_multiple_remotes_parse_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with multiple <remote> elements parses all into manifest.remotes.

        AC-TEST-002: multiple remotes can coexist in one manifest.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert "origin" in manifest.remotes, "Expected 'origin' in manifest.remotes but not found"
        assert "upstream" in manifest.remotes, "Expected 'upstream' in manifest.remotes but not found"
        assert manifest.remotes["origin"].fetchUrl == "https://origin.example.com", (
            f"Expected origin.fetchUrl='https://origin.example.com' but got: {manifest.remotes['origin'].fetchUrl!r}"
        )
        assert manifest.remotes["upstream"].fetchUrl == "https://upstream.example.com", (
            f"Expected upstream.fetchUrl='https://upstream.example.com' but got: "
            f"{manifest.remotes['upstream'].fetchUrl!r}"
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
    def test_remote_revision_parsed_for_various_values(
        self,
        tmp_path: pathlib.Path,
        revision: str,
    ) -> None:
        """Parameterized: various revision values on <remote> are parsed and stored correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
            extra_remote_attrs=f'revision="{revision}"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.revision == revision, f"Expected remote.revision='{revision}' but got: {remote.revision!r}"


# ---------------------------------------------------------------------------
# AC-TEST-003: <remote> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteDefaultAttributeValues:
    """Verify that default attribute values on <remote> behave as documented.

    The <remote> element documents:
    - When alias is omitted, remote.remoteAlias is None (name used as git remote name)
    - When pushurl is omitted, remote.pushUrl is None (fetch URL is used for push)
    - When review is omitted, remote.reviewUrl is None
    - When revision is omitted, remote.revision is None (default revision from <default>)
    - Duplicate remotes with identical attributes are idempotent
    - Duplicate remotes with different attributes raise ManifestParseError
    """

    def test_remote_alias_defaults_to_none_when_omitted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When alias is not specified, remote.remoteAlias is None.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.remoteAlias is None, (
            f"Expected remote.remoteAlias=None when alias omitted but got: {remote.remoteAlias!r}"
        )

    def test_remote_pushurl_defaults_to_none_when_omitted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When pushurl is not specified, remote.pushUrl is None.

        AC-TEST-003: per docs, projects fall back to the fetch URL for push when pushUrl is None.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.pushUrl is None, f"Expected remote.pushUrl=None when pushurl omitted but got: {remote.pushUrl!r}"

    def test_remote_revision_defaults_to_none_when_omitted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When revision is not specified on <remote>, remote.revision is None.

        AC-TEST-003: projects fall back to <default revision> when remote.revision is None.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.revision is None, (
            f"Expected remote.revision=None when revision omitted but got: {remote.revision!r}"
        )

    def test_remote_review_defaults_to_none_when_omitted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When review is not specified, remote.reviewUrl is None.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.reviewUrl is None, (
            f"Expected remote.reviewUrl=None when review omitted but got: {remote.reviewUrl!r}"
        )

    def test_duplicate_remote_with_same_attributes_is_idempotent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Declaring the same <remote> twice with identical attributes does not raise an error.

        AC-TEST-003: identical duplicate remotes are silently accepted (idempotent).
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert "origin" in manifest.remotes, "Expected 'origin' in manifest.remotes after duplicate parse"
        assert manifest.remotes["origin"].fetchUrl == "https://example.com", (
            f"Expected fetchUrl='https://example.com' but got: {manifest.remotes['origin'].fetchUrl!r}"
        )

    def test_duplicate_remote_with_different_attributes_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Declaring the same <remote> name with different fetch URLs raises ManifestParseError.

        AC-TEST-003: conflicting duplicate remotes are rejected with a clear error.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://first.example.com" />\n'
            '  <remote name="origin" fetch="https://second.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), (
            "Expected a non-empty error message from ManifestParseError for conflicting remote but got an empty string"
        )
        assert "origin" in str(exc_info.value), (
            f"Expected the error message to mention 'origin' but got: {str(exc_info.value)!r}"
        )

    def test_remote_missing_name_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remote> missing the required name attribute raises ManifestParseError.

        AC-TEST-003: required attributes have no default and must be provided.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), (
            "Expected a non-empty error message from ManifestParseError for missing name but got empty string"
        )

    def test_remote_missing_fetch_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <remote> missing the required fetch attribute raises ManifestParseError.

        AC-TEST-003: required attributes have no default and must be provided.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), (
            "Expected a non-empty error message from ManifestParseError for missing fetch but got empty string"
        )

    @pytest.mark.parametrize(
        "alias",
        [
            "upstream",
            "alt-origin",
            "mirror",
        ],
    )
    def test_remote_alias_parsed_for_various_values(
        self,
        tmp_path: pathlib.Path,
        alias: str,
    ) -> None:
        """Parameterized: various alias attribute values are parsed and stored correctly.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
            extra_remote_attrs=f'alias="{alias}"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        remote = manifest.remotes["origin"]
        assert remote.remoteAlias == alias, f"Expected remote.remoteAlias='{alias}' but got: {remote.remoteAlias!r}"


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteChannelDiscipline:
    """Verify that parse errors raise exceptions rather than writing to stdout.

    The <remote> parser must report errors exclusively through exceptions;
    it must not write error information to stdout. Tests here verify that a
    valid parse is error-free and that parse failures produce ManifestParseError.

    AC-CHANNEL-001 (parser tasks: no stdout leakage for success/failure paths)
    """

    def test_valid_remote_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest with a valid <remote> does not raise ManifestParseError.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_remote_manifest(
            remote_name="origin",
            fetch_url="https://example.com",
        )
        manifest_file = _write_manifest(repodir, xml_content)

        try:
            _load_manifest(repodir, manifest_file)
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid <remote> manifest to parse without ManifestParseError but got: {exc!r}")

    def test_invalid_remote_raises_manifest_parse_error_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Parsing a <remote> with missing name raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
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
