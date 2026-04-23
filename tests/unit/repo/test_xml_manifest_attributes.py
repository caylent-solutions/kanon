"""Unit tests for <manifest> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <manifest> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <manifest> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestInvalidPathError
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers (mirrors the pattern used in test_xml_manifest_happy.py)
# ---------------------------------------------------------------------------

_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest.

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


def _write_and_load(tmp_path: pathlib.Path, xml_content: str) -> manifest_xml.XmlManifest:
    """Write xml_content to a manifest file and load it.

    Args:
        tmp_path: Pytest tmp_path for isolation.
        xml_content: Full XML content for the manifest file.

    Returns:
        A loaded XmlManifest instance.
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


# ---------------------------------------------------------------------------
# AC-TEST-001: valid-value tests -- one per documented <manifest> attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestAttributeValidValues:
    """AC-TEST-001: Every attribute has at least one valid-value test.

    Covers: <remote> name, fetch, alias, pushurl, review, revision;
    <default> revision, remote, sync-j, sync-c, sync-s, sync-tags,
    dest-branch, upstream; <project> name, path, remote, revision,
    groups, rebase, sync-c, sync-s, sync-tags, clone-depth, dest-branch,
    upstream; <notice>; <manifest-server>; <contactinfo>.
    """

    def test_remote_name_valid(self, tmp_path: pathlib.Path) -> None:
        """A <remote name="..."> with a plain ASCII name parses without error.

        AC-TEST-001, AC-FUNC-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="valid-name" fetch="https://example.com" />\n'
            '  <default revision="main" remote="valid-name" />\n'
            "</manifest>\n",
        )
        assert "valid-name" in manifest.remotes, (
            f"Expected remote 'valid-name' in manifest.remotes but got: {list(manifest.remotes.keys())!r}"
        )

    def test_remote_fetch_valid(self, tmp_path: pathlib.Path) -> None:
        """A <remote fetch="https://..."> with a well-formed URL parses without error.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://git.example.com/base" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n",
        )
        remote = manifest.remotes["origin"]
        assert remote.fetchUrl is not None, "Expected fetchUrl to be non-None"
        assert "https://git.example.com/base" in remote.fetchUrl, (
            f"Expected 'https://git.example.com/base' in fetchUrl but got: {remote.fetchUrl!r}"
        )

    def test_remote_alias_valid(self, tmp_path: pathlib.Path) -> None:
        """A <remote alias="..."> sets remoteAlias on the parsed remote.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" alias="my-alias" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n",
        )
        remote = manifest.remotes["origin"]
        assert remote.remoteAlias == "my-alias", (
            f"Expected remote.remoteAlias='my-alias' but got: {remote.remoteAlias!r}"
        )

    def test_remote_pushurl_valid(self, tmp_path: pathlib.Path) -> None:
        """A <remote pushurl="..."> sets pushUrl on the parsed remote.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" pushurl="https://push.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n",
        )
        remote = manifest.remotes["origin"]
        assert remote.pushUrl == "https://push.example.com", (
            f"Expected remote.pushUrl='https://push.example.com' but got: {remote.pushUrl!r}"
        )

    def test_remote_review_valid(self, tmp_path: pathlib.Path) -> None:
        """A <remote review="..."> sets reviewUrl on the parsed remote.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" review="https://review.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n",
        )
        remote = manifest.remotes["origin"]
        assert remote.reviewUrl == "https://review.example.com", (
            f"Expected remote.reviewUrl='https://review.example.com' but got: {remote.reviewUrl!r}"
        )

    def test_remote_revision_valid(self, tmp_path: pathlib.Path) -> None:
        """A <remote revision="..."> sets revision on the parsed remote.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" revision="refs/heads/stable" />\n'
            '  <default remote="origin" />\n'
            '  <project name="foo/bar" path="bar" />\n'
            "</manifest>\n",
        )
        remote = manifest.remotes["origin"]
        assert remote.revision == "refs/heads/stable", (
            f"Expected remote.revision='refs/heads/stable' but got: {remote.revision!r}"
        )

    def test_default_revision_valid(self, tmp_path: pathlib.Path) -> None:
        """A <default revision="..."> sets revisionExpr on manifest.default.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="refs/heads/main" remote="origin" />\n'
            "</manifest>\n",
        )
        assert manifest.default.revisionExpr == "refs/heads/main", (
            f"Expected default.revisionExpr='refs/heads/main' but got: {manifest.default.revisionExpr!r}"
        )

    def test_default_remote_valid(self, tmp_path: pathlib.Path) -> None:
        """A <default remote="..."> sets the default remote by name.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="upstream" fetch="https://example.com" />\n'
            '  <default revision="main" remote="upstream" />\n'
            "</manifest>\n",
        )
        assert manifest.default.remote is not None, "Expected default.remote to be set"
        assert manifest.default.remote.name == "upstream", (
            f"Expected default.remote.name='upstream' but got: {manifest.default.remote.name!r}"
        )

    def test_default_sync_j_positive_integer_valid(self, tmp_path: pathlib.Path) -> None:
        """A <default sync-j="4"> with a positive integer parses as integer 4.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" sync-j="4" />\n'
            "</manifest>\n",
        )
        assert manifest.default.sync_j == 4, f"Expected default.sync_j=4 but got: {manifest.default.sync_j!r}"

    @pytest.mark.parametrize(
        "attr_value,expected",
        [
            ("true", True),
            ("false", False),
            ("1", True),
            ("0", False),
            ("yes", True),
            ("no", False),
        ],
    )
    def test_default_sync_c_valid_boolean_values(
        self,
        tmp_path: pathlib.Path,
        attr_value: str,
        expected: bool,
    ) -> None:
        """A <default sync-c="..."> with each valid boolean string parses correctly.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            f'  <default revision="main" remote="origin" sync-c="{attr_value}" />\n'
            "</manifest>\n",
        )
        assert manifest.default.sync_c is expected, (
            f"Expected default.sync_c={expected!r} for sync-c='{attr_value}' but got: {manifest.default.sync_c!r}"
        )

    @pytest.mark.parametrize(
        "attr_value,expected",
        [
            ("true", True),
            ("false", False),
            ("1", True),
            ("0", False),
        ],
    )
    def test_default_sync_s_valid_boolean_values(
        self,
        tmp_path: pathlib.Path,
        attr_value: str,
        expected: bool,
    ) -> None:
        """A <default sync-s="..."> with each valid boolean string parses correctly.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            f'  <default revision="main" remote="origin" sync-s="{attr_value}" />\n'
            "</manifest>\n",
        )
        assert manifest.default.sync_s is expected, (
            f"Expected default.sync_s={expected!r} for sync-s='{attr_value}' but got: {manifest.default.sync_s!r}"
        )

    @pytest.mark.parametrize(
        "attr_value,expected",
        [
            ("true", True),
            ("false", False),
        ],
    )
    def test_default_sync_tags_valid_boolean_values(
        self,
        tmp_path: pathlib.Path,
        attr_value: str,
        expected: bool,
    ) -> None:
        """A <default sync-tags="..."> with a valid boolean string parses correctly.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            f'  <default revision="main" remote="origin" sync-tags="{attr_value}" />\n'
            "</manifest>\n",
        )
        assert manifest.default.sync_tags is expected, (
            f"Expected default.sync_tags={expected!r} for sync-tags='{attr_value}' "
            f"but got: {manifest.default.sync_tags!r}"
        )

    def test_default_dest_branch_valid(self, tmp_path: pathlib.Path) -> None:
        """A <default dest-branch="..."> sets destBranchExpr on manifest.default.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" dest-branch="refs/heads/stable" />\n'
            "</manifest>\n",
        )
        assert manifest.default.destBranchExpr == "refs/heads/stable", (
            f"Expected default.destBranchExpr='refs/heads/stable' but got: {manifest.default.destBranchExpr!r}"
        )

    def test_default_upstream_valid(self, tmp_path: pathlib.Path) -> None:
        """A <default upstream="..."> sets upstreamExpr on manifest.default.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" upstream="refs/heads/upstream" />\n'
            "</manifest>\n",
        )
        assert manifest.default.upstreamExpr == "refs/heads/upstream", (
            f"Expected default.upstreamExpr='refs/heads/upstream' but got: {manifest.default.upstreamExpr!r}"
        )

    def test_project_name_valid(self, tmp_path: pathlib.Path) -> None:
        """A <project name="platform/core"> with a slash-separated path parses correctly.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" />\n'
            "</manifest>\n",
        )
        names = [p.name for p in manifest.projects]
        assert "platform/core" in names, f"Expected 'platform/core' in project names but got: {names!r}"

    def test_project_path_valid(self, tmp_path: pathlib.Path) -> None:
        """A <project path="sub/dir"> with a valid relative path sets relpath correctly.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="sub/dir" />\n'
            "</manifest>\n",
        )
        projects = {p.name: p for p in manifest.projects}
        assert projects["platform/core"].relpath == "sub/dir", (
            f"Expected relpath='sub/dir' but got: {projects['platform/core'].relpath!r}"
        )

    def test_project_remote_valid(self, tmp_path: pathlib.Path) -> None:
        """A <project remote="..."> overrides the default remote for that project.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <remote name="mirror" fetch="https://mirror.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" remote="mirror" />\n'
            "</manifest>\n",
        )
        projects = {p.name: p for p in manifest.projects}
        assert "platform/core" in projects, f"Expected 'platform/core' in projects but got: {list(projects.keys())!r}"

    def test_project_revision_valid(self, tmp_path: pathlib.Path) -> None:
        """A <project revision="refs/tags/v1.0.0"> sets revisionExpr on the project.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" revision="refs/tags/v1.0.0" />\n'
            "</manifest>\n",
        )
        projects = {p.name: p for p in manifest.projects}
        assert projects["platform/core"].revisionExpr == "refs/tags/v1.0.0", (
            f"Expected revisionExpr='refs/tags/v1.0.0' but got: {projects['platform/core'].revisionExpr!r}"
        )

    def test_project_groups_valid(self, tmp_path: pathlib.Path) -> None:
        """A <project groups="pdk,tools"> sets the groups list on the project.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" groups="pdk,tools" />\n'
            "</manifest>\n",
        )
        projects = {p.name: p for p in manifest.projects}
        assert "pdk" in projects["platform/core"].groups, (
            f"Expected 'pdk' in project.groups but got: {projects['platform/core'].groups!r}"
        )
        assert "tools" in projects["platform/core"].groups, (
            f"Expected 'tools' in project.groups but got: {projects['platform/core'].groups!r}"
        )

    def test_project_sync_c_valid(self, tmp_path: pathlib.Path) -> None:
        """A <project sync-c="true"> sets sync_c=True on the project.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" sync-c="true" />\n'
            "</manifest>\n",
        )
        projects = {p.name: p for p in manifest.projects}
        assert projects["platform/core"].sync_c is True, (
            f"Expected project.sync_c=True but got: {projects['platform/core'].sync_c!r}"
        )

    def test_project_sync_s_valid(self, tmp_path: pathlib.Path) -> None:
        """A <project sync-s="true"> sets sync_s=True on the project.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" sync-s="true" />\n'
            "</manifest>\n",
        )
        projects = {p.name: p for p in manifest.projects}
        assert projects["platform/core"].sync_s is True, (
            f"Expected project.sync_s=True but got: {projects['platform/core'].sync_s!r}"
        )

    def test_project_sync_tags_valid(self, tmp_path: pathlib.Path) -> None:
        """A <project sync-tags="false"> sets sync_tags=False on the project.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" sync-tags="false" />\n'
            "</manifest>\n",
        )
        projects = {p.name: p for p in manifest.projects}
        assert projects["platform/core"].sync_tags is False, (
            f"Expected project.sync_tags=False but got: {projects['platform/core'].sync_tags!r}"
        )

    def test_project_clone_depth_valid(self, tmp_path: pathlib.Path) -> None:
        """A <project clone-depth="1"> sets clone_depth=1 on the project.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" clone-depth="1" />\n'
            "</manifest>\n",
        )
        projects = {p.name: p for p in manifest.projects}
        assert projects["platform/core"].clone_depth == 1, (
            f"Expected project.clone_depth=1 but got: {projects['platform/core'].clone_depth!r}"
        )

    def test_project_rebase_valid(self, tmp_path: pathlib.Path) -> None:
        """A <project rebase="false"> sets rebase=False on the project.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" path="core" rebase="false" />\n'
            "</manifest>\n",
        )
        projects = {p.name: p for p in manifest.projects}
        assert projects["platform/core"].rebase is False, (
            f"Expected project.rebase=False but got: {projects['platform/core'].rebase!r}"
        )

    def test_notice_element_text_valid(self, tmp_path: pathlib.Path) -> None:
        """A <notice> element with text content sets manifest.notice correctly.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice>Release manifest for project foo.</notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n",
        )
        assert manifest.notice is not None, "Expected manifest.notice to be non-None"
        assert "Release manifest" in manifest.notice, (
            f"Expected 'Release manifest' in manifest.notice but got: {manifest.notice!r}"
        )

    def test_manifest_server_url_valid(self, tmp_path: pathlib.Path) -> None:
        """A <manifest-server url="..."> sets manifest.manifest_server correctly.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <manifest-server url="https://manifest-server.example.com" />\n'
            "</manifest>\n",
        )
        assert manifest.manifest_server == "https://manifest-server.example.com", (
            f"Expected manifest_server='https://manifest-server.example.com' but got: {manifest.manifest_server!r}"
        )

    def test_contactinfo_bugurl_valid(self, tmp_path: pathlib.Path) -> None:
        """A <contactinfo bugurl="..."> sets manifest.contactinfo.bugurl correctly.

        AC-TEST-001
        """
        manifest = _write_and_load(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <contactinfo bugurl="https://bugs.example.com/report" />\n'
            "</manifest>\n",
        )
        assert manifest.contactinfo.bugurl == "https://bugs.example.com/report", (
            f"Expected contactinfo.bugurl='https://bugs.example.com/report' but got: {manifest.contactinfo.bugurl!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: invalid-value tests -- each raises ManifestParseError or
#              ManifestInvalidPathError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestAttributeInvalidValues:
    """AC-TEST-002: Every attribute has invalid-value tests.

    Each invalid input must raise ManifestParseError or
    ManifestInvalidPathError with a non-empty message.
    """

    def test_remote_missing_fetch_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """A <remote> without a fetch attribute raises ManifestParseError naming 'fetch'.

        AC-TEST-002, AC-TEST-003
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" />\n'
                '  <default revision="main" remote="origin" />\n'
                "</manifest>\n",
            )
        assert "fetch" in str(exc_info.value).lower(), (
            f"Expected error message to mention 'fetch' but got: {exc_info.value!r}"
        )

    def test_default_sync_j_non_integer_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """A <default sync-j="not-a-number"> raises ManifestParseError.

        AC-TEST-002
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" sync-j="not-a-number" />\n'
                "</manifest>\n",
            )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError"

    @pytest.mark.parametrize("sync_j_value", ["0", "-1", "-100"])
    def test_default_sync_j_zero_or_negative_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
        sync_j_value: str,
    ) -> None:
        """A <default sync-j="0"> or negative raises ManifestParseError.

        AC-TEST-002
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                f'  <default revision="main" remote="origin" sync-j="{sync_j_value}" />\n'
                "</manifest>\n",
            )
        assert "sync-j" in str(exc_info.value), f"Expected 'sync-j' in error message but got: {exc_info.value!r}"

    def test_project_invalid_name_double_dotdot_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A <project name="../escape"> with path traversal raises ManifestInvalidPathError.

        AC-TEST-002
        """
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="../escape" path="escape" />\n'
                "</manifest>\n",
            )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestInvalidPathError"

    def test_project_invalid_path_dotgit_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A <project path=".git/something"> raises ManifestInvalidPathError.

        AC-TEST-002
        """
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path=".git/bad" />\n'
                "</manifest>\n",
            )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestInvalidPathError"

    def test_project_invalid_path_absolute_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A <project path="/absolute/path"> raises ManifestInvalidPathError.

        AC-TEST-002
        """
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="/absolute/path" />\n'
                "</manifest>\n",
            )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestInvalidPathError"

    def test_project_invalid_path_tilde_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A <project path="~/home"> with tilde raises ManifestInvalidPathError.

        AC-TEST-002
        """
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="~/home" />\n'
                "</manifest>\n",
            )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestInvalidPathError"

    def test_project_invalid_name_tilde_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A <project name="~bad"> with tilde raises ManifestInvalidPathError.

        AC-TEST-002
        """
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="~bad" path="bad" />\n'
                "</manifest>\n",
            )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestInvalidPathError"

    def test_project_no_remote_and_no_default_remote_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """A <project> without a remote, and no <default remote>, raises ManifestParseError.

        AC-TEST-002
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" />\n'
                '  <project name="platform/core" path="core" />\n'
                "</manifest>\n",
            )
        assert "remote" in str(exc_info.value).lower(), (
            f"Expected error message to mention 'remote' but got: {exc_info.value!r}"
        )

    def test_project_no_revision_and_no_default_revision_raises_manifest_parse_error(
        self, tmp_path: pathlib.Path
    ) -> None:
        """A <project> without revision, no <default revision>, raises ManifestParseError.

        AC-TEST-002
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default remote="origin" />\n'
                '  <project name="platform/core" path="core" />\n'
                "</manifest>\n",
            )
        assert "revision" in str(exc_info.value).lower(), (
            f"Expected error message to mention 'revision' but got: {exc_info.value!r}"
        )

    def test_project_unknown_remote_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """A <project remote="nonexistent"> referencing an undeclared remote raises ManifestParseError.

        AC-TEST-002
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" remote="nonexistent" />\n'
                "</manifest>\n",
            )
        assert "nonexistent" in str(exc_info.value) or "remote" in str(exc_info.value).lower(), (
            f"Expected error message to mention the unknown remote but got: {exc_info.value!r}"
        )

    @pytest.mark.parametrize("clone_depth", ["0", "-1", "-50"])
    def test_project_clone_depth_zero_or_negative_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
        clone_depth: str,
    ) -> None:
        """A <project clone-depth="0"> or negative raises ManifestParseError.

        AC-TEST-002
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                f'  <project name="platform/core" path="core" clone-depth="{clone_depth}" />\n'
                "</manifest>\n",
            )
        assert "clone-depth" in str(exc_info.value), (
            f"Expected 'clone-depth' in error message but got: {exc_info.value!r}"
        )

    def test_project_clone_depth_non_integer_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """A <project clone-depth="abc"> with a non-integer raises ManifestParseError.

        AC-TEST-002
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/core" path="core" clone-depth="abc" />\n'
                "</manifest>\n",
            )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError"

    def test_project_invalid_name_dotrepo_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A <project name=".repo"> uses a reserved name and raises ManifestInvalidPathError.

        AC-TEST-002
        """
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name=".repo" path="repo-dir" />\n'
                "</manifest>\n",
            )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestInvalidPathError"

    def test_duplicate_default_element_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """Two <default> elements in the same manifest raises ManifestParseError.

        AC-TEST-002
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <default revision="develop" remote="origin" />\n'
                "</manifest>\n",
            )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError"

    def test_duplicate_manifest_server_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """Two <manifest-server> elements in the same manifest raises ManifestParseError.

        AC-TEST-002
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <manifest-server url="https://server1.example.com" />\n'
                '  <manifest-server url="https://server2.example.com" />\n'
                "</manifest>\n",
            )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError"

    def test_duplicate_project_path_raises_manifest_parse_error(self, tmp_path: pathlib.Path) -> None:
        """Two <project> elements with the same path raises ManifestParseError.

        AC-TEST-002
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project name="platform/a" path="shared" />\n'
                '  <project name="platform/b" path="shared" />\n'
                "</manifest>\n",
            )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError"


# ---------------------------------------------------------------------------
# AC-TEST-003: required attribute omission raises with message naming attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestRequiredAttributeOmission:
    """AC-TEST-003: Omitting a required attribute raises with the attribute name.

    Each test omits exactly one required attribute and verifies that
    ManifestParseError is raised with a message that names the missing field.
    """

    def test_remote_missing_name_raises_with_attribute_name(self, tmp_path: pathlib.Path) -> None:
        """A <remote> without name raises ManifestParseError mentioning 'name'.

        AC-TEST-003
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote fetch="https://example.com" />\n'
                '  <default revision="main" />\n'
                "</manifest>\n",
            )
        error_text = str(exc_info.value).lower()
        assert "name" in error_text, f"Expected error message to contain 'name' but got: {exc_info.value!r}"

    def test_remote_missing_fetch_raises_with_attribute_name(self, tmp_path: pathlib.Path) -> None:
        """A <remote name="x"> without fetch raises ManifestParseError mentioning 'fetch'.

        AC-TEST-003
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" />\n'
                '  <default revision="main" remote="origin" />\n'
                "</manifest>\n",
            )
        error_text = str(exc_info.value).lower()
        assert "fetch" in error_text, f"Expected error message to contain 'fetch' but got: {exc_info.value!r}"

    def test_project_missing_name_raises_with_attribute_name(self, tmp_path: pathlib.Path) -> None:
        """A <project> without name raises ManifestParseError mentioning 'name'.

        AC-TEST-003
        """
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                '  <project path="core" />\n'
                "</manifest>\n",
            )
        error_text = str(exc_info.value).lower()
        assert "name" in error_text, f"Expected error message to contain 'name' but got: {exc_info.value!r}"

    @pytest.mark.parametrize(
        "remote_attr,expected_attr_in_msg",
        [
            ("name", "name"),
            ("fetch", "fetch"),
        ],
    )
    def test_remote_required_attribute_omission_names_attribute(
        self,
        tmp_path: pathlib.Path,
        remote_attr: str,
        expected_attr_in_msg: str,
    ) -> None:
        """Parametrized: each required <remote> attribute omission names the attribute.

        AC-TEST-003
        """
        if remote_attr == "name":
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote fetch="https://example.com" />\n'
                '  <default revision="main" />\n'
                "</manifest>\n"
            )
        else:
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" />\n'
                '  <default revision="main" remote="origin" />\n'
                "</manifest>\n"
            )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml)
        assert expected_attr_in_msg in str(exc_info.value).lower(), (
            f"Expected '{expected_attr_in_msg}' in error message but got: {exc_info.value!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestAttributeChannelDiscipline:
    """AC-CHANNEL-001: Attribute validation errors surface as exceptions, not stdout.

    Verifies that parse errors for attribute validation are raised as
    ManifestParseError or ManifestInvalidPathError rather than written to
    stdout and swallowed.
    """

    def test_valid_attribute_manifest_does_not_raise(self, tmp_path: pathlib.Path) -> None:
        """Parsing a fully valid manifest with all attributes does not raise.

        AC-CHANNEL-001
        """
        try:
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin"\n'
                '          fetch="https://example.com"\n'
                '          alias="orig"\n'
                '          pushurl="https://push.example.com"\n'
                '          review="https://review.example.com"\n'
                '          revision="refs/heads/stable" />\n'
                '  <default revision="main"\n'
                '           remote="origin"\n'
                '           sync-j="4"\n'
                '           sync-c="true"\n'
                '           sync-s="false"\n'
                '           sync-tags="true" />\n'
                '  <project name="platform/core"\n'
                '           path="core"\n'
                '           revision="refs/tags/v1.0"\n'
                '           groups="pdk"\n'
                '           sync-c="true"\n'
                '           sync-s="false"\n'
                '           clone-depth="5" />\n'
                "</manifest>\n",
            )
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid attribute manifest to parse without error but got: {exc!r}")
        except ManifestInvalidPathError as exc:
            pytest.fail(f"Expected valid attribute manifest to parse without path error but got: {exc!r}")

    def test_invalid_attribute_raises_exception_not_stdout(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Invalid attributes raise an exception rather than silently writing to stdout.

        AC-CHANNEL-001
        """
        with pytest.raises((ManifestParseError, ManifestInvalidPathError)):
            _write_and_load(
                tmp_path,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" />\n'
                '  <default revision="main" remote="origin" />\n'
                "</manifest>\n",
            )
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout output for attribute error but got: {captured.out!r}"
