"""Unit tests for the <default> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <default> XML elements parse correctly when
given minimum required attributes, all documented attributes, and that
default attribute values behave as documented.

The <default> element sets project defaults for the manifest. Documented attributes:
  Optional: remote (reference to a declared <remote> element)
  Optional: revision (default branch/tag/SHA expression for projects)
  Optional: dest-branch (default destination branch for pushed changes)
  Optional: upstream (default upstream branch)
  Optional: sync-j (number of parallel sync jobs; must be > 0)
  Optional: sync-c (boolean; sync only the current branch; default False)
  Optional: sync-s (boolean; sync submodules; default False)
  Optional: sync-tags (boolean; sync tags; default True)

A <default> element with no attributes is valid and sets all values to their
class-level defaults. At most one non-empty <default> element may appear in
a manifest (duplicates with differing values raise ManifestParseError).

All tests use real manifest files written to tmp_path via shared helpers.
The conftest in tests/unit/repo/ auto-applies @pytest.mark.unit to every
item collected under that directory.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared setup helpers
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


def _build_manifest_with_default(
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_attrs: str = "",
) -> str:
    """Build manifest XML containing a <remote> and a <default> element.

    Args:
        remote_name: The name attribute for the <remote> element.
        fetch_url: The fetch attribute for the <remote> element.
        default_attrs: Attribute string for the <default> element. If empty,
            the default element has no attributes.

    Returns:
        Full XML string for the manifest.
    """
    default_elem = f"  <default {default_attrs} />\n" if default_attrs else "  <default />\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f"{default_elem}"
        "</manifest>\n"
    )


def _build_manifest_with_remote_and_default(
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    revision: str = "main",
    extra_default_attrs: str = "",
) -> str:
    """Build manifest XML with a <remote> and a <default> that references the remote.

    Args:
        remote_name: The name attribute for the <remote> element.
        fetch_url: The fetch attribute for the <remote> element.
        revision: The revision attribute on the <default> element.
        extra_default_attrs: Any additional attributes for the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    default_attrs = f'remote="{remote_name}" revision="{revision}"'
    if extra_default_attrs:
        default_attrs = f"{default_attrs} {extra_default_attrs}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f"  <default {default_attrs} />\n"
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid <default> with minimum required attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultMinimumAttributes:
    """Verify that a <default> element with no attributes parses correctly.

    The <default> element has no required attributes. A bare <default /> is
    valid; all fields on the parsed default object must be at their class-level
    defaults.
    """

    def test_empty_default_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with an empty <default /> element parses without raising any error.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default()
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest is not None, "Expected XmlManifest instance but got None"

    def test_empty_default_revision_is_none(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An empty <default /> element leaves default.revisionExpr as None.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default()
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.revisionExpr is None, (
            f"Expected default.revisionExpr=None when revision absent but got: {manifest.default.revisionExpr!r}"
        )

    def test_empty_default_remote_is_none(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An empty <default /> element leaves default.remote as None.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default()
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.remote is None, (
            f"Expected default.remote=None when remote absent but got: {manifest.default.remote!r}"
        )

    def test_empty_default_dest_branch_is_none(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An empty <default /> element leaves default.destBranchExpr as None.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default()
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.destBranchExpr is None, (
            f"Expected default.destBranchExpr=None when dest-branch absent but got: {manifest.default.destBranchExpr!r}"
        )

    def test_empty_default_upstream_is_none(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An empty <default /> element leaves default.upstreamExpr as None.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default()
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.upstreamExpr is None, (
            f"Expected default.upstreamExpr=None when upstream absent but got: {manifest.default.upstreamExpr!r}"
        )

    def test_empty_default_sync_j_is_none(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An empty <default /> element leaves default.sync_j as None.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default()
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.sync_j is None, (
            f"Expected default.sync_j=None when sync-j absent but got: {manifest.default.sync_j!r}"
        )

    def test_default_with_only_revision_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <default revision="main" /> parses and exposes the revision expression.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default(default_attrs='revision="main"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.revisionExpr == "main", (
            f"Expected default.revisionExpr='main' but got: {manifest.default.revisionExpr!r}"
        )

    @pytest.mark.parametrize(
        "revision",
        [
            "main",
            "refs/heads/stable",
            "abc1234567890abcdef1234567890abcdef123456",
        ],
    )
    def test_default_with_various_revision_values_parses(
        self,
        tmp_path: pathlib.Path,
        revision: str,
    ) -> None:
        """Parameterized: various revision strings on <default> are parsed correctly.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default(default_attrs=f'revision="{revision}"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.revisionExpr == revision, (
            f"Expected default.revisionExpr='{revision}' but got: {manifest.default.revisionExpr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <default> with all documented attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultAllDocumentedAttributes:
    """Verify that a <default> element with all documented attributes parses correctly.

    The <default> element documents eight attributes:
    - remote: optional, name of a declared <remote>
    - revision: optional, default branch/tag/SHA expression
    - dest-branch: optional, destination branch for pushed changes
    - upstream: optional, default upstream branch
    - sync-j: optional integer, number of parallel sync jobs
    - sync-c: optional boolean, sync current branch only (default False)
    - sync-s: optional boolean, sync submodules (default False)
    - sync-tags: optional boolean, sync tags (default True)
    """

    def test_default_remote_attribute_sets_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <default remote="origin" ... /> element sets default.remote to the parsed remote.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_remote_and_default(
            remote_name="origin",
            fetch_url="https://example.com",
            revision="main",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.remote is not None, "Expected default.remote to be set but got None"
        assert manifest.default.remote.name == "origin", (
            f"Expected default.remote.name='origin' but got: {manifest.default.remote.name!r}"
        )

    def test_default_revision_attribute_sets_revision_expr(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <default revision="main" /> element sets default.revisionExpr to 'main'.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_remote_and_default(
            remote_name="origin",
            fetch_url="https://example.com",
            revision="main",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.revisionExpr == "main", (
            f"Expected default.revisionExpr='main' but got: {manifest.default.revisionExpr!r}"
        )

    def test_default_dest_branch_attribute_sets_dest_branch_expr(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <default dest-branch="release"> element sets default.destBranchExpr.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_remote_and_default(
            remote_name="origin",
            fetch_url="https://example.com",
            revision="main",
            extra_default_attrs='dest-branch="release"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.destBranchExpr == "release", (
            f"Expected default.destBranchExpr='release' but got: {manifest.default.destBranchExpr!r}"
        )

    def test_default_upstream_attribute_sets_upstream_expr(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <default upstream="main"> element sets default.upstreamExpr.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_remote_and_default(
            remote_name="origin",
            fetch_url="https://example.com",
            revision="main",
            extra_default_attrs='upstream="main"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.upstreamExpr == "main", (
            f"Expected default.upstreamExpr='main' but got: {manifest.default.upstreamExpr!r}"
        )

    def test_default_sync_j_attribute_sets_sync_j(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <default sync-j="4"> element sets default.sync_j to 4.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_remote_and_default(
            remote_name="origin",
            fetch_url="https://example.com",
            revision="main",
            extra_default_attrs='sync-j="4"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.sync_j == 4, f"Expected default.sync_j=4 but got: {manifest.default.sync_j!r}"

    def test_default_sync_c_true_attribute_sets_sync_c(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <default sync-c="true"> element sets default.sync_c to True.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_remote_and_default(
            remote_name="origin",
            fetch_url="https://example.com",
            revision="main",
            extra_default_attrs='sync-c="true"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.sync_c is True, f"Expected default.sync_c=True but got: {manifest.default.sync_c!r}"

    def test_default_sync_s_true_attribute_sets_sync_s(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <default sync-s="true"> element sets default.sync_s to True.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_remote_and_default(
            remote_name="origin",
            fetch_url="https://example.com",
            revision="main",
            extra_default_attrs='sync-s="true"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.sync_s is True, f"Expected default.sync_s=True but got: {manifest.default.sync_s!r}"

    def test_default_sync_tags_false_attribute_sets_sync_tags(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <default sync-tags="false"> element sets default.sync_tags to False.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_remote_and_default(
            remote_name="origin",
            fetch_url="https://example.com",
            revision="main",
            extra_default_attrs='sync-tags="false"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.sync_tags is False, (
            f"Expected default.sync_tags=False but got: {manifest.default.sync_tags!r}"
        )

    def test_default_all_documented_attributes_parse(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <default> with all documented attributes parses every field correctly.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_remote_and_default(
            remote_name="origin",
            fetch_url="https://example.com",
            revision="refs/heads/main",
            extra_default_attrs=(
                'dest-branch="release" upstream="main" sync-j="8" sync-c="true" sync-s="false" sync-tags="false"'
            ),
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        d = manifest.default
        assert d.remote is not None, "Expected default.remote to be set but got None"
        assert d.remote.name == "origin", f"Expected default.remote.name='origin' but got: {d.remote.name!r}"
        assert d.revisionExpr == "refs/heads/main", (
            f"Expected default.revisionExpr='refs/heads/main' but got: {d.revisionExpr!r}"
        )
        assert d.destBranchExpr == "release", f"Expected default.destBranchExpr='release' but got: {d.destBranchExpr!r}"
        assert d.upstreamExpr == "main", f"Expected default.upstreamExpr='main' but got: {d.upstreamExpr!r}"
        assert d.sync_j == 8, f"Expected default.sync_j=8 but got: {d.sync_j!r}"
        assert d.sync_c is True, f"Expected default.sync_c=True but got: {d.sync_c!r}"
        assert d.sync_s is False, f"Expected default.sync_s=False but got: {d.sync_s!r}"
        assert d.sync_tags is False, f"Expected default.sync_tags=False but got: {d.sync_tags!r}"

    @pytest.mark.parametrize(
        "sync_j_value",
        [1, 2, 4, 8, 16],
    )
    def test_default_sync_j_various_values_parse(
        self,
        tmp_path: pathlib.Path,
        sync_j_value: int,
    ) -> None:
        """Parameterized: various sync-j integer values are parsed correctly.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_remote_and_default(
            remote_name="origin",
            fetch_url="https://example.com",
            revision="main",
            extra_default_attrs=f'sync-j="{sync_j_value}"',
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.sync_j == sync_j_value, (
            f"Expected default.sync_j={sync_j_value} but got: {manifest.default.sync_j!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <default> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultAttributeDefaults:
    """Verify that documented default values on <default> attributes behave per spec.

    When optional attributes are absent from the <default> element, the parsed
    _Default instance must reflect these documented defaults:
    - remote: None
    - revisionExpr: None
    - destBranchExpr: None
    - upstreamExpr: None
    - sync_j: None
    - sync_c: False
    - sync_s: False
    - sync_tags: True
    """

    def test_sync_c_defaults_to_false_when_absent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When sync-c is absent from <default>, default.sync_c is False.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default()
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.sync_c is False, (
            f"Expected default.sync_c=False when sync-c absent but got: {manifest.default.sync_c!r}"
        )

    def test_sync_s_defaults_to_false_when_absent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When sync-s is absent from <default>, default.sync_s is False.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default()
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.sync_s is False, (
            f"Expected default.sync_s=False when sync-s absent but got: {manifest.default.sync_s!r}"
        )

    def test_sync_tags_defaults_to_true_when_absent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When sync-tags is absent from <default>, default.sync_tags is True.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default()
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.sync_tags is True, (
            f"Expected default.sync_tags=True when sync-tags absent but got: {manifest.default.sync_tags!r}"
        )

    def test_all_optional_attrs_absent_yields_all_class_defaults(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An empty <default /> element yields all class-level defaults on the parsed object.

        AC-TEST-003, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default()
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        d = manifest.default
        assert d.remote is None, f"Expected default.remote=None but got: {d.remote!r}"
        assert d.revisionExpr is None, f"Expected default.revisionExpr=None but got: {d.revisionExpr!r}"
        assert d.destBranchExpr is None, f"Expected default.destBranchExpr=None but got: {d.destBranchExpr!r}"
        assert d.upstreamExpr is None, f"Expected default.upstreamExpr=None but got: {d.upstreamExpr!r}"
        assert d.sync_j is None, f"Expected default.sync_j=None but got: {d.sync_j!r}"
        assert d.sync_c is False, f"Expected default.sync_c=False but got: {d.sync_c!r}"
        assert d.sync_s is False, f"Expected default.sync_s=False but got: {d.sync_s!r}"
        assert d.sync_tags is True, f"Expected default.sync_tags=True but got: {d.sync_tags!r}"

    def test_sync_c_false_explicit_matches_default(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An explicit sync-c="false" matches the documented default (False).

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default(default_attrs='sync-c="false"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.sync_c is False, (
            f"Expected default.sync_c=False for explicit sync-c='false' but got: {manifest.default.sync_c!r}"
        )

    def test_sync_s_false_explicit_matches_default(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An explicit sync-s="false" matches the documented default (False).

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default(default_attrs='sync-s="false"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.sync_s is False, (
            f"Expected default.sync_s=False for explicit sync-s='false' but got: {manifest.default.sync_s!r}"
        )

    def test_sync_tags_true_explicit_matches_default(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An explicit sync-tags="true" matches the documented default (True).

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default(default_attrs='sync-tags="true"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.default.sync_tags is True, (
            f"Expected default.sync_tags=True for explicit sync-tags='true' but got: {manifest.default.sync_tags!r}"
        )

    def test_no_default_element_still_yields_defaults(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with no <default> element at all still provides a _Default with class defaults.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        d = manifest.default
        assert d is not None, "Expected a _Default object even when no <default> element present"
        assert d.revisionExpr is None, f"Expected default.revisionExpr=None but got: {d.revisionExpr!r}"
        assert d.sync_c is False, f"Expected default.sync_c=False but got: {d.sync_c!r}"
        assert d.sync_tags is True, f"Expected default.sync_tags=True but got: {d.sync_tags!r}"

    @pytest.mark.parametrize(
        "bool_attr,attr_name,expected",
        [
            ("sync-c", "sync_c", False),
            ("sync-s", "sync_s", False),
        ],
    )
    def test_boolean_attrs_default_to_false_when_absent(
        self,
        tmp_path: pathlib.Path,
        bool_attr: str,
        attr_name: str,
        expected: bool,
    ) -> None:
        """Parameterized: sync-c and sync-s default to False when not present on <default>.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default()
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        actual = getattr(manifest.default, attr_name)
        assert actual is expected, (
            f"Expected default.{attr_name}={expected} when {bool_attr!r} absent but got: {actual!r}"
        )

    def test_invalid_sync_j_zero_raises_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <default sync-j="0"> must raise ManifestParseError (sync-j must be > 0).

        AC-TEST-003: documented constraint -- sync-j must be greater than 0.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_default(default_attrs='sync-j="0"')
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError, match="sync-j must be greater than 0"):
            _load_manifest(repodir, manifest_file)
