"""Unit tests for <linkfile> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <linkfile> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <linkfile> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified (no cross-channel
                  leakage)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <linkfile> element documented attributes:
  Required: src   -- relative path within the project checkout (or "." for
                     the whole worktree). Validated at parse time:
                     cwd_dot_ok=True and dir_ok=True so src="." and
                     trailing-slash dir paths are accepted; '..'-traversal
                     and absolute paths are rejected unless abs_ok=True (not
                     set for src).
  Required: dest  -- relative path from the workspace root where the symlink
                     is created. Unlike <copyfile dest>, ABSOLUTE paths are
                     ALLOWED for <linkfile dest> (abs_ok=True).
  Optional: exclude -- comma-separated list of immediate child names to omit
                     when linking a directory source. Stored as a frozenset
                     on the model; absent means an empty frozenset.

Documented constraints for invalid-value tests:
  - src omitted (or blank)  -> ManifestParseError naming "src"
  - dest omitted (or blank) -> ManifestParseError naming "dest"
  - src contains '..'       -> ManifestInvalidPathError mentioning "src"
  - dest contains '..'      -> ManifestInvalidPathError mentioning "dest"
  - src is absolute         -> ManifestInvalidPathError mentioning "src"
  - src contains '~'        -> ManifestInvalidPathError mentioning "src"
  - dest contains '~'       -> ManifestInvalidPathError mentioning "dest"
  - src contains '.git'     -> ManifestInvalidPathError mentioning "src"
  - dest contains '.git'    -> ManifestInvalidPathError mentioning "dest"
  - dest contains '.repo'   -> ManifestInvalidPathError mentioning "dest"

Unique to <linkfile> (different from <copyfile>):
  - dest may be an absolute path (abs_ok=True) -- this IS valid for linkfile
  - src="." is accepted (cwd_dot_ok=True)
  - src may be a directory (dir_ok=True)

Note: When IsMirror is True, _ValidateFilePaths is not called and linkfiles
are not added. These tests operate in the default non-mirror mode.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestInvalidPathError
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
        ManifestParseError: If the manifest is syntactically or structurally invalid.
        ManifestInvalidPathError: If an attribute contains an invalid path.
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


def _manifest_with_linkfile(src: str, dest: str, exclude: str = "") -> str:
    """Build a complete manifest XML string containing a <linkfile> element.

    Args:
        src: Value for the src attribute of <linkfile>.
        dest: Value for the dest attribute of <linkfile>.
        exclude: Optional value for the exclude attribute of <linkfile>.

    Returns:
        Full manifest XML string with a project containing one linkfile.
    """
    exclude_attr = f' exclude="{exclude}"' if exclude else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core">\n'
        f'    <linkfile src="{src}" dest="{dest}"{exclude_attr} />\n'
        "  </project>\n"
        "</manifest>\n"
    )


def _manifest_without_src(dest: str) -> str:
    """Build a manifest XML string with a <linkfile> element missing the src attribute.

    Args:
        dest: Value for the dest attribute of <linkfile>.

    Returns:
        Full manifest XML string with a project containing a linkfile without src.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core">\n'
        f'    <linkfile dest="{dest}" />\n'
        "  </project>\n"
        "</manifest>\n"
    )


def _manifest_without_dest(src: str) -> str:
    """Build a manifest XML string with a <linkfile> element missing the dest attribute.

    Args:
        src: Value for the src attribute of <linkfile>.

    Returns:
        Full manifest XML string with a project containing a linkfile without dest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core">\n'
        f'    <linkfile src="{src}" />\n'
        "  </project>\n"
        "</manifest>\n"
    )


def _get_linkfile(manifest: manifest_xml.XmlManifest, project_name: str):
    """Return the first linkfile from the named project.

    Args:
        manifest: A loaded XmlManifest instance.
        project_name: The name attribute of the target project.

    Returns:
        The first _LinkFile model object attached to the project.
    """
    by_name = {p.name: p for p in manifest.projects}
    project = by_name[project_name]
    return project.linkfiles[0]


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every documented attribute of <linkfile>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinkfileSrcValidValues:
    """AC-TEST-001 -- valid values accepted for the src attribute.

    src must be a path relative to the project checkout, free from
    path-traversal components and other disallowed patterns. Valid paths
    include simple filenames, nested relative paths with forward slashes,
    paths containing underscores/dots-within-filenames/hyphens, and the
    special value "." (whole worktree).
    """

    @pytest.mark.parametrize(
        "src",
        [
            "scripts",
            "include/types.h",
            "bin/tool",
            "README.md",
            "a/b/c/deep.txt",
            "src/main.py",
        ],
    )
    def test_src_valid_relative_paths_accepted(self, tmp_path: pathlib.Path, src: str) -> None:
        """Valid relative src paths parse without error and are stored on the model.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = _manifest_with_linkfile(src=src, dest="tools/output")
        manifest = _write_and_load(tmp_path, xml_content)
        linkfile = _get_linkfile(manifest, "platform/core")
        assert linkfile.src == src, f"Expected linkfile.src={src!r} but got: {linkfile.src!r}"

    def test_src_dot_accepted_as_whole_worktree(self, tmp_path: pathlib.Path) -> None:
        """src='.' (whole worktree) is accepted and stored verbatim.

        AC-TEST-001: the spec allows src='.' as a stable link to the whole
        project worktree. cwd_dot_ok=True is set for linkfile src validation.
        """
        src = "."
        xml_content = _manifest_with_linkfile(src=src, dest="link/platform-core")
        manifest = _write_and_load(tmp_path, xml_content)
        linkfile = _get_linkfile(manifest, "platform/core")
        assert linkfile.src == src, f"Expected linkfile.src={src!r} but got: {linkfile.src!r}"

    def test_src_filename_with_hyphen_accepted(self, tmp_path: pathlib.Path) -> None:
        """A src path containing a hyphen is accepted and stored verbatim.

        AC-TEST-001
        """
        src = "my-script.sh"
        xml_content = _manifest_with_linkfile(src=src, dest="tools/my-script.sh")
        manifest = _write_and_load(tmp_path, xml_content)
        linkfile = _get_linkfile(manifest, "platform/core")
        assert linkfile.src == src, f"Expected linkfile.src={src!r} but got: {linkfile.src!r}"

    def test_src_filename_with_underscore_accepted(self, tmp_path: pathlib.Path) -> None:
        """A src path containing an underscore is accepted and stored verbatim.

        AC-TEST-001
        """
        src = "build_config.h"
        xml_content = _manifest_with_linkfile(src=src, dest="include/build_config.h")
        manifest = _write_and_load(tmp_path, xml_content)
        linkfile = _get_linkfile(manifest, "platform/core")
        assert linkfile.src == src, f"Expected linkfile.src={src!r} but got: {linkfile.src!r}"


@pytest.mark.unit
class TestLinkfileDestValidValues:
    """AC-TEST-001 -- valid values accepted for the dest attribute.

    dest is the path from the workspace root where the symlink is created.
    Unlike <copyfile>, <linkfile> dest allows absolute paths (abs_ok=True).
    Relative paths are also accepted.
    """

    @pytest.mark.parametrize(
        "dest",
        [
            "tools/scripts",
            "sdk/include",
            "usr/local/bin/tool",
            "docs/README.md",
            "output/build/config",
        ],
    )
    def test_dest_valid_relative_paths_accepted(self, tmp_path: pathlib.Path, dest: str) -> None:
        """Valid relative dest paths parse without error and are stored on the model.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = _manifest_with_linkfile(src="scripts", dest=dest)
        manifest = _write_and_load(tmp_path, xml_content)
        linkfile = _get_linkfile(manifest, "platform/core")
        assert linkfile.dest == dest, f"Expected linkfile.dest={dest!r} but got: {linkfile.dest!r}"

    def test_dest_absolute_path_accepted(self, tmp_path: pathlib.Path) -> None:
        """An absolute dest path is accepted for <linkfile> (unlike <copyfile>).

        AC-TEST-001: abs_ok=True is set for linkfile dest validation per spec 17.1.
        """
        dest = "/opt/workspace/tools"
        xml_content = _manifest_with_linkfile(src="scripts", dest=dest)
        manifest = _write_and_load(tmp_path, xml_content)
        linkfile = _get_linkfile(manifest, "platform/core")
        assert linkfile.dest == dest, f"Expected linkfile.dest={dest!r} but got: {linkfile.dest!r}"

    def test_dest_with_deeply_nested_path_accepted(self, tmp_path: pathlib.Path) -> None:
        """A deeply nested dest path is accepted and stored verbatim.

        AC-TEST-001
        """
        dest = "a/b/c/d/e/link_target"
        xml_content = _manifest_with_linkfile(src="scripts", dest=dest)
        manifest = _write_and_load(tmp_path, xml_content)
        linkfile = _get_linkfile(manifest, "platform/core")
        assert linkfile.dest == dest, f"Expected linkfile.dest={dest!r} but got: {linkfile.dest!r}"


@pytest.mark.unit
class TestLinkfileExcludeValidValues:
    """AC-TEST-001 -- valid values accepted for the optional exclude attribute.

    exclude is a comma-separated string of immediate child names to omit when
    linking a directory source. When absent, the model stores an empty frozenset.
    When present, each comma-delimited name (after stripping whitespace) is
    included in the frozenset.
    """

    def test_exclude_absent_produces_empty_frozenset(self, tmp_path: pathlib.Path) -> None:
        """When exclude is absent, linkfile.exclude is an empty frozenset.

        AC-TEST-001
        """
        xml_content = _manifest_with_linkfile(src="scripts", dest="tools/scripts")
        manifest = _write_and_load(tmp_path, xml_content)
        linkfile = _get_linkfile(manifest, "platform/core")
        assert linkfile.exclude == frozenset(), (
            f"Expected linkfile.exclude=frozenset() when exclude absent but got: {linkfile.exclude!r}"
        )

    def test_exclude_single_entry_stored_as_frozenset(self, tmp_path: pathlib.Path) -> None:
        """A single exclude entry is stored as a single-element frozenset.

        AC-TEST-001
        """
        xml_content = _manifest_with_linkfile(src="tools", dest="workspace/tools", exclude=".git")
        manifest = _write_and_load(tmp_path, xml_content)
        linkfile = _get_linkfile(manifest, "platform/core")
        assert ".git" in linkfile.exclude, (
            f"Expected '.git' in linkfile.exclude frozenset but got: {linkfile.exclude!r}"
        )

    def test_exclude_multiple_entries_stored_as_frozenset(self, tmp_path: pathlib.Path) -> None:
        """Multiple comma-separated exclude entries are each stored in the frozenset.

        AC-TEST-001
        """
        xml_content = _manifest_with_linkfile(src="tools", dest="workspace/tools", exclude=".git,build,dist")
        manifest = _write_and_load(tmp_path, xml_content)
        linkfile = _get_linkfile(manifest, "platform/core")
        assert ".git" in linkfile.exclude, (
            f"Expected '.git' in linkfile.exclude frozenset but got: {linkfile.exclude!r}"
        )
        assert "build" in linkfile.exclude, (
            f"Expected 'build' in linkfile.exclude frozenset but got: {linkfile.exclude!r}"
        )
        assert "dist" in linkfile.exclude, (
            f"Expected 'dist' in linkfile.exclude frozenset but got: {linkfile.exclude!r}"
        )

    @pytest.mark.parametrize(
        "exclude,expected_members",
        [
            (".git,build", {".git", "build"}),
            ("node_modules", {"node_modules"}),
            ("tmp,cache,dist", {"tmp", "cache", "dist"}),
        ],
    )
    def test_exclude_parametrized_values_stored_correctly(
        self, tmp_path: pathlib.Path, exclude: str, expected_members: set
    ) -> None:
        """Parameterized: exclude values are split on comma and stored in frozenset.

        AC-TEST-001
        """
        xml_content = _manifest_with_linkfile(src="tools", dest="workspace/tools", exclude=exclude)
        manifest = _write_and_load(tmp_path, xml_content)
        linkfile = _get_linkfile(manifest, "platform/core")
        for member in expected_members:
            assert member in linkfile.exclude, (
                f"Expected {member!r} in linkfile.exclude for exclude={exclude!r} but got: {linkfile.exclude!r}"
            )


# ---------------------------------------------------------------------------
# AC-TEST-002: Invalid-value tests for every documented attribute of <linkfile>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinkfileSrcInvalidValues:
    """AC-TEST-002 -- invalid values for the src attribute raise ManifestInvalidPathError.

    The _ValidateFilePaths helper validates src with _CheckLocalPath using
    dir_ok=True and cwd_dot_ok=True, and raises ManifestInvalidPathError naming
    the "src" attribute on failure.
    """

    @pytest.mark.parametrize(
        "bad_src",
        [
            "../escape/secret",
            "../../root/shadow",
            "a/../../../etc/passwd",
        ],
    )
    def test_src_path_traversal_raises_invalid_path_error(self, tmp_path: pathlib.Path, bad_src: str) -> None:
        """src values containing '..' (path traversal) raise ManifestInvalidPathError.

        AC-TEST-002
        """
        xml_content = _manifest_with_linkfile(src=bad_src, dest="out/link")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "src" in str(exc_info.value), f"Expected error message to mention 'src' but got: {str(exc_info.value)!r}"

    def test_src_absolute_path_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """An absolute src path (starting with /) raises ManifestInvalidPathError.

        AC-TEST-002: absolute paths are not allowed for linkfile src (abs_ok is
        not set for src, only for dest).
        """
        xml_content = _manifest_with_linkfile(src="/etc/secret", dest="out/link")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "src" in str(exc_info.value), f"Expected error message to mention 'src' but got: {str(exc_info.value)!r}"

    def test_src_tilde_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A src path containing '~' raises ManifestInvalidPathError.

        AC-TEST-002: ~ is rejected to prevent 8.3 filesystem naming issues.
        """
        xml_content = _manifest_with_linkfile(src="~/secret", dest="out/link")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "src" in str(exc_info.value), f"Expected error message to mention 'src' but got: {str(exc_info.value)!r}"

    def test_src_dotgit_component_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A src path with a '.git' component raises ManifestInvalidPathError.

        AC-TEST-002: .git components are rejected to prevent accessing git internals.
        """
        xml_content = _manifest_with_linkfile(src=".git/config", dest="out/link")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "src" in str(exc_info.value), f"Expected error message to mention 'src' but got: {str(exc_info.value)!r}"

    def test_src_dotrepo_component_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A src path with a '.repo' component raises ManifestInvalidPathError.

        AC-TEST-002: .repo components are rejected to prevent accessing repo internals.
        """
        xml_content = _manifest_with_linkfile(src=".repo/manifest.xml", dest="out/link")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "src" in str(exc_info.value), f"Expected error message to mention 'src' but got: {str(exc_info.value)!r}"


@pytest.mark.unit
class TestLinkfileDestInvalidValues:
    """AC-TEST-002 -- invalid values for the dest attribute raise ManifestInvalidPathError.

    The _ValidateFilePaths helper validates dest with abs_ok=True (absolute paths
    allowed) and raises ManifestInvalidPathError naming the "dest" attribute on
    failure for other violations.
    """

    @pytest.mark.parametrize(
        "bad_dest",
        [
            "../escape/secret",
            "../../root/shadow",
            "a/../../../etc/passwd",
        ],
    )
    def test_dest_path_traversal_raises_invalid_path_error(self, tmp_path: pathlib.Path, bad_dest: str) -> None:
        """dest values containing '..' (path traversal) raise ManifestInvalidPathError.

        AC-TEST-002
        """
        xml_content = _manifest_with_linkfile(src="scripts", dest=bad_dest)
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "dest" in str(exc_info.value), (
            f"Expected error message to mention 'dest' but got: {str(exc_info.value)!r}"
        )

    def test_dest_tilde_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A dest path containing '~' raises ManifestInvalidPathError.

        AC-TEST-002: ~ is rejected to prevent 8.3 filesystem naming issues,
        even though abs_ok=True for linkfile dest.
        """
        xml_content = _manifest_with_linkfile(src="scripts", dest="~/output/link")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "dest" in str(exc_info.value), (
            f"Expected error message to mention 'dest' but got: {str(exc_info.value)!r}"
        )

    def test_dest_dotgit_component_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A dest path with a '.git' component raises ManifestInvalidPathError.

        AC-TEST-002: .git components are rejected to prevent writing into git internals.
        """
        xml_content = _manifest_with_linkfile(src="scripts", dest=".git/hooks")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "dest" in str(exc_info.value), (
            f"Expected error message to mention 'dest' but got: {str(exc_info.value)!r}"
        )

    def test_dest_dotrepo_component_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A dest path with a '.repo' component raises ManifestInvalidPathError.

        AC-TEST-002: .repo components are rejected to prevent writing into repo internals.
        """
        xml_content = _manifest_with_linkfile(src="scripts", dest=".repo/manifest.xml")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "dest" in str(exc_info.value), (
            f"Expected error message to mention 'dest' but got: {str(exc_info.value)!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Required attribute omission raises with message naming the attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinkfileRequiredAttributeOmission:
    """AC-TEST-003 -- omitting a required attribute raises ManifestParseError
    with a message that names the missing attribute.

    The _reqatt helper raises ManifestParseError("no {attr} in <linkfile> within {file}")
    when an attribute is absent or blank.
    """

    def test_missing_src_raises_parse_error_naming_src(self, tmp_path: pathlib.Path) -> None:
        """Omitting the src attribute raises ManifestParseError mentioning 'src'.

        AC-TEST-003
        """
        xml_content = _manifest_without_src(dest="tools/link")
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "src" in str(exc_info.value), (
            f"Expected error message to name 'src' attribute but got: {str(exc_info.value)!r}"
        )

    def test_missing_dest_raises_parse_error_naming_dest(self, tmp_path: pathlib.Path) -> None:
        """Omitting the dest attribute raises ManifestParseError mentioning 'dest'.

        AC-TEST-003
        """
        xml_content = _manifest_without_dest(src="scripts")
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "dest" in str(exc_info.value), (
            f"Expected error message to name 'dest' attribute but got: {str(exc_info.value)!r}"
        )

    @pytest.mark.parametrize(
        "attr_name,xml_builder",
        [
            ("src", lambda: _manifest_without_src("tools/link")),
            ("dest", lambda: _manifest_without_dest("scripts")),
        ],
    )
    def test_missing_required_attribute_raises_manifest_parse_error(
        self, tmp_path: pathlib.Path, attr_name: str, xml_builder
    ) -> None:
        """Parameterized: each required attribute, when omitted, raises ManifestParseError.

        AC-TEST-003: both required attributes are enforced; omitting either raises.
        """
        xml_content = xml_builder()
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert attr_name in str(exc_info.value), (
            f"Expected error message to name attribute '{attr_name}' but got: {str(exc_info.value)!r}"
        )

    def test_missing_src_error_message_is_nonempty(self, tmp_path: pathlib.Path) -> None:
        """The ManifestParseError raised for missing src has a non-empty message.

        AC-TEST-003: error messages must be actionable -- not an empty string.
        """
        xml_content = _manifest_without_src(dest="tools/link")
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError for missing src"

    def test_missing_dest_error_message_is_nonempty(self, tmp_path: pathlib.Path) -> None:
        """The ManifestParseError raised for missing dest has a non-empty message.

        AC-TEST-003: error messages must be actionable -- not an empty string.
        """
        xml_content = _manifest_without_dest(src="scripts")
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError for missing dest"


# ---------------------------------------------------------------------------
# AC-FUNC-001: Every documented attribute is validated at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinkfileParseTimeValidation:
    """AC-FUNC-001 -- every documented attribute is validated during manifest load.

    Validation must occur at parse time (during m.Load()), not deferred to
    sync/link time. Tests confirm that invalid values raise immediately on Load.
    """

    def test_invalid_src_detected_at_parse_not_sync_time(self, tmp_path: pathlib.Path) -> None:
        """Path-traversal src is detected and raised during manifest load, not later.

        AC-FUNC-001
        """
        xml_content = _manifest_with_linkfile(src="../evil", dest="out/link")
        with pytest.raises((ManifestParseError, ManifestInvalidPathError)):
            _write_and_load(tmp_path, xml_content)

    def test_invalid_dest_detected_at_parse_not_sync_time(self, tmp_path: pathlib.Path) -> None:
        """Path-traversal dest is detected and raised during manifest load, not later.

        AC-FUNC-001
        """
        xml_content = _manifest_with_linkfile(src="scripts", dest="../evil")
        with pytest.raises((ManifestParseError, ManifestInvalidPathError)):
            _write_and_load(tmp_path, xml_content)

    def test_valid_src_and_dest_produce_linkfile_model(self, tmp_path: pathlib.Path) -> None:
        """Both valid src and dest produce a populated linkfile on the project model.

        AC-FUNC-001: attributes are validated AND their values stored on the model.
        """
        src = "scripts"
        dest = "tools/scripts"
        xml_content = _manifest_with_linkfile(src=src, dest=dest)
        manifest = _write_and_load(tmp_path, xml_content)

        by_name = {p.name: p for p in manifest.projects}
        project = by_name["platform/core"]
        assert len(project.linkfiles) == 1, (
            f"Expected exactly 1 linkfile after valid parse but got: {len(project.linkfiles)}"
        )
        linkfile = project.linkfiles[0]
        assert linkfile.src == src, f"Expected src={src!r} but got: {linkfile.src!r}"
        assert linkfile.dest == dest, f"Expected dest={dest!r} but got: {linkfile.dest!r}"

    @pytest.mark.parametrize(
        "src,dest",
        [
            ("scripts", "tools/scripts"),
            ("include", "sdk/include"),
            ("bin/tool", "usr/local/bin/tool"),
            (".", "link/platform-core"),
        ],
    )
    def test_all_documented_attributes_accepted_for_various_paths(
        self, tmp_path: pathlib.Path, src: str, dest: str
    ) -> None:
        """Parameterized: all documented attribute combinations are accepted at parse time.

        AC-FUNC-001
        """
        xml_content = _manifest_with_linkfile(src=src, dest=dest)
        manifest = _write_and_load(tmp_path, xml_content)
        linkfile = _get_linkfile(manifest, "platform/core")
        assert linkfile.src == src, f"Expected src={src!r} but got: {linkfile.src!r}"
        assert linkfile.dest == dest, f"Expected dest={dest!r} but got: {linkfile.dest!r}"

    def test_exclude_attribute_does_not_prevent_parse(self, tmp_path: pathlib.Path) -> None:
        """The optional exclude attribute, when present with a valid value, does not prevent parse.

        AC-FUNC-001: the exclude attribute is accepted during parse even though
        validation of its values (child name existence) is deferred to sync time.
        """
        xml_content = _manifest_with_linkfile(src="tools", dest="workspace/tools", exclude=".git,build")
        manifest = _write_and_load(tmp_path, xml_content)
        linkfile = _get_linkfile(manifest, "platform/core")
        assert linkfile.src == "tools", f"Expected src='tools' but got: {linkfile.src!r}"
        assert linkfile.dest == "workspace/tools", f"Expected dest='workspace/tools' but got: {linkfile.dest!r}"


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinkfileChannelDiscipline:
    """AC-CHANNEL-001 -- parse errors must not write to stdout.

    Error information for invalid <linkfile> attributes must be conveyed
    exclusively through raised exceptions. No error text must appear on
    stdout. Successful parses must not produce any output on stdout either.
    """

    def test_valid_linkfile_produces_no_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Parsing a valid <linkfile> produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = _manifest_with_linkfile(src="scripts", dest="tools/scripts")
        _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout for valid parse but got: {captured.out!r}"

    def test_missing_src_raises_exception_not_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Missing src attribute raises ManifestParseError; no error written to stdout.

        AC-CHANNEL-001
        """
        xml_content = _manifest_without_src(dest="tools/link")
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout when ManifestParseError is raised but got: {captured.out!r}"

    def test_missing_dest_raises_exception_not_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Missing dest attribute raises ManifestParseError; no error written to stdout.

        AC-CHANNEL-001
        """
        xml_content = _manifest_without_dest(src="scripts")
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout when ManifestParseError is raised but got: {captured.out!r}"

    def test_invalid_src_path_raises_exception_not_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Invalid src path raises ManifestInvalidPathError; no error written to stdout.

        AC-CHANNEL-001
        """
        xml_content = _manifest_with_linkfile(src="../escape", dest="out/link")
        with pytest.raises((ManifestParseError, ManifestInvalidPathError)):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout when ManifestInvalidPathError is raised but got: {captured.out!r}"

    def test_invalid_dest_path_raises_exception_not_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Invalid dest path raises ManifestInvalidPathError; no error written to stdout.

        AC-CHANNEL-001
        """
        xml_content = _manifest_with_linkfile(src="scripts", dest="../escape")
        with pytest.raises((ManifestParseError, ManifestInvalidPathError)):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout when ManifestInvalidPathError is raised but got: {captured.out!r}"
