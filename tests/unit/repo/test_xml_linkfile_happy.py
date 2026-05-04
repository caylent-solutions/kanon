"""Unit tests for the <linkfile> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <linkfile> XML elements parse correctly when given
minimum required attributes, all documented attributes, and that default
attribute values behave as documented.

The <linkfile> element is a child of <project> and declares a symlink to be
created from the project checkout into the workspace root. Documented
attributes:
  Required: src  (target of symlink relative to project worktree; or "." for
                  the whole worktree)
  Required: dest (relative path from workspace root where symlink is created;
                  absolute paths are also allowed per spec)
  Optional: exclude (comma-separated child names to omit when linking a
                     directory source)

Multiple <linkfile> children may be nested inside one <project> element.
When no <linkfile> children are present, project.linkfiles is empty.

All tests use real manifest files written to tmp_path via shared helpers.
The conftest in tests/unit/repo/ auto-applies @pytest.mark.unit to every
item collected under that directory.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestInvalidPathError
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


def _build_manifest_with_linkfile(
    src: str,
    dest: str,
    project_name: str = "platform/core",
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
    exclude: str = "",
) -> str:
    """Build a manifest XML string with a <project> containing one <linkfile>.

    Args:
        src: The src attribute for the <linkfile> element.
        dest: The dest attribute for the <linkfile> element.
        project_name: The name attribute for the <project> element.
        remote_name: The name attribute for the <remote> element.
        fetch_url: The fetch attribute for the <remote> element.
        default_revision: The revision on the <default> element.
        exclude: Optional exclude attribute for the <linkfile> element.

    Returns:
        Full XML string for the manifest.
    """
    exclude_attr = f' exclude="{exclude}"' if exclude else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f'  <project name="{project_name}">\n'
        f'    <linkfile src="{src}" dest="{dest}"{exclude_attr} />\n'
        "  </project>\n"
        "</manifest>\n"
    )


def _get_project(manifest: manifest_xml.XmlManifest, project_name: str):
    """Return the project with the given name from the manifest.

    Args:
        manifest: A loaded XmlManifest instance.
        project_name: The name of the project to retrieve.

    Returns:
        The Project object with the given name.
    """
    projects_by_name = {p.name: p for p in manifest.projects}
    return projects_by_name[project_name]


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid <linkfile> with minimum required attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinkfileMinimumAttributes:
    """Verify that a <linkfile> element with only required attributes parses correctly.

    The minimum valid <linkfile> requires src and dest. The exclude attribute
    is optional and defaults to empty.
    """

    def test_linkfile_minimum_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with a <linkfile src='...' dest='...'> parses without error.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(
            src="scripts",
            dest="tools/scripts",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest is not None, "Expected XmlManifest instance but got None"

    def test_linkfile_appears_in_project_linkfiles(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing, the <linkfile> appears in the parent project's linkfiles list.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(
            src="scripts",
            dest="tools/scripts",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert len(project.linkfiles) == 1, f"Expected exactly 1 linkfile on project but got: {len(project.linkfiles)}"

    def test_linkfile_src_attribute_stored_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The parsed linkfile model stores the src attribute from the XML.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(
            src="scripts",
            dest="tools/scripts",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        linkfile = project.linkfiles[0]
        assert linkfile.src == "scripts", f"Expected linkfile.src='scripts' but got: {linkfile.src!r}"

    def test_linkfile_dest_attribute_stored_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The parsed linkfile model stores the dest attribute from the XML.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(
            src="scripts",
            dest="tools/scripts",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        linkfile = project.linkfiles[0]
        assert linkfile.dest == "tools/scripts", f"Expected linkfile.dest='tools/scripts' but got: {linkfile.dest!r}"

    @pytest.mark.parametrize(
        "src,dest",
        [
            ("scripts", "tools/scripts"),
            ("include", "sdk/include"),
            ("bin/tool", "usr/local/bin/tool"),
            ("README.md", "docs/README.md"),
        ],
    )
    def test_linkfile_src_and_dest_parsed_for_various_values(
        self,
        tmp_path: pathlib.Path,
        src: str,
        dest: str,
    ) -> None:
        """Parameterized: various src and dest path values are parsed and stored correctly.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(src=src, dest=dest)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert len(project.linkfiles) == 1, (
            f"Expected 1 linkfile for src={src!r}, dest={dest!r} but got: {len(project.linkfiles)}"
        )
        linkfile = project.linkfiles[0]
        assert linkfile.src == src, f"Expected linkfile.src={src!r} but got: {linkfile.src!r}"
        assert linkfile.dest == dest, f"Expected linkfile.dest={dest!r} but got: {linkfile.dest!r}"

    def test_linkfile_missing_src_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <linkfile> missing the required src attribute raises ManifestParseError.

        AC-TEST-001: required attributes have no default and must be provided.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <linkfile dest="tools/scripts" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), (
            "Expected a non-empty error message from ManifestParseError for missing src but got empty string"
        )

    def test_linkfile_missing_dest_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <linkfile> missing the required dest attribute raises ManifestParseError.

        AC-TEST-001: required attributes have no default and must be provided.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <linkfile src="scripts" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), (
            "Expected a non-empty error message from ManifestParseError for missing dest but got empty string"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <linkfile> with all documented attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinkfileAllDocumentedAttributes:
    """Verify that a <linkfile> element with all documented attributes parses correctly.

    The <linkfile> element documents three attributes:
    - src:     required, the relative path (or ".") within the project worktree
    - dest:    required, the path from workspace root where the symlink is created;
               absolute paths are permitted for <linkfile>
    - exclude: optional, comma-separated child names to omit when linking a dir

    Multiple <linkfile> elements may appear as children of the same <project>.
    """

    def test_linkfile_with_src_and_dest_parses_model_with_both(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <linkfile src='...' dest='...'> parses both attributes into the model.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(
            src="include",
            dest="sdk/include",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert len(project.linkfiles) == 1, f"Expected 1 linkfile but got: {len(project.linkfiles)}"
        linkfile = project.linkfiles[0]
        assert linkfile.src == "include", f"Expected linkfile.src='include' but got: {linkfile.src!r}"
        assert linkfile.dest == "sdk/include", f"Expected linkfile.dest='sdk/include' but got: {linkfile.dest!r}"

    def test_linkfile_with_exclude_attribute_parses_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <linkfile> with the optional exclude attribute parses without error.

        AC-TEST-002: the exclude attribute is optional and may contain a
        comma-separated list of child names to omit when linking a directory.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(
            src="tools",
            dest="workspace/tools",
            exclude=".git,build",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert len(project.linkfiles) == 1, f"Expected 1 linkfile but got: {len(project.linkfiles)}"

    def test_linkfile_exclude_stored_as_frozenset(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The parsed linkfile model stores the exclude attribute as a frozenset.

        AC-TEST-002: the exclude value is split on comma and stored so that
        individual child names can be looked up efficiently.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(
            src="tools",
            dest="workspace/tools",
            exclude=".git,build",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        linkfile = project.linkfiles[0]
        assert ".git" in linkfile.exclude, (
            f"Expected '.git' in linkfile.exclude frozenset but got: {linkfile.exclude!r}"
        )
        assert "build" in linkfile.exclude, (
            f"Expected 'build' in linkfile.exclude frozenset but got: {linkfile.exclude!r}"
        )

    def test_linkfile_dot_src_parses_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <linkfile src='.'> (whole worktree) parses without error.

        AC-TEST-002: the spec allows src='.' to create a stable link to the
        whole project worktree directory.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(
            src=".",
            dest="link/platform-core",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert len(project.linkfiles) == 1, f"Expected 1 linkfile but got: {len(project.linkfiles)}"
        linkfile = project.linkfiles[0]
        assert linkfile.src == ".", f"Expected linkfile.src='.' but got: {linkfile.src!r}"

    def test_multiple_linkfile_elements_in_one_project_parse_all(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Multiple <linkfile> children in one <project> are all parsed correctly.

        AC-TEST-002: multiple linkfiles in a project populate linkfiles list in order.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <linkfile src="scripts" dest="tools/scripts" />\n'
            '    <linkfile src="include" dest="sdk/include" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert len(project.linkfiles) == 2, f"Expected 2 linkfiles but got: {len(project.linkfiles)}"
        srcs = [lf.src for lf in project.linkfiles]
        dests = [lf.dest for lf in project.linkfiles]
        assert "scripts" in srcs, f"Expected 'scripts' in linkfile srcs but got: {srcs!r}"
        assert "include" in srcs, f"Expected 'include' in linkfile srcs but got: {srcs!r}"
        assert "tools/scripts" in dests, f"Expected 'tools/scripts' in linkfile dests but got: {dests!r}"
        assert "sdk/include" in dests, f"Expected 'sdk/include' in linkfile dests but got: {dests!r}"

    def test_linkfile_in_different_projects_are_isolated(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<linkfile> elements in different <project> elements are correctly isolated.

        AC-TEST-002: linkfiles from project A must not appear on project B.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <linkfile src="scripts" dest="tools/scripts" />\n'
            "  </project>\n"
            '  <project name="platform/tools" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        core = _get_project(manifest, "platform/core")
        tools = _get_project(manifest, "platform/tools")
        assert len(core.linkfiles) == 1, f"Expected 1 linkfile on platform/core but got: {len(core.linkfiles)}"
        assert len(tools.linkfiles) == 0, (
            f"Expected 0 linkfiles on platform/tools (no <linkfile> child) but got: {len(tools.linkfiles)}"
        )

    def test_linkfile_git_worktree_stored_from_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The parsed linkfile stores the parent project's git_worktree path.

        AC-TEST-002: the linkfile model retains the project worktree for use
        during the actual symlink creation operation.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(
            src="scripts",
            dest="tools/scripts",
            project_name="platform/core",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        linkfile = project.linkfiles[0]
        assert linkfile.git_worktree is not None, "Expected linkfile.git_worktree to be set but got None"
        assert "platform" in linkfile.git_worktree or "core" in linkfile.git_worktree, (
            f"Expected linkfile.git_worktree to reference project path but got: {linkfile.git_worktree!r}"
        )

    def test_linkfile_topdir_stored_from_manifest(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The parsed linkfile stores the manifest topdir for resolving dest paths.

        AC-TEST-002: the linkfile model retains the topdir for use during the
        actual symlink creation operation.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(
            src="scripts",
            dest="tools/scripts",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        linkfile = project.linkfiles[0]
        assert linkfile.topdir is not None, "Expected linkfile.topdir to be set but got None"


# ---------------------------------------------------------------------------
# AC-TEST-003: <linkfile> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinkfileDefaultAttributeValues:
    """Verify that default attribute values on <linkfile> behave as documented.

    The <linkfile> element documents one optional attribute (exclude). The
    relevant default behaviors are:
    - When no <linkfile> children are present, project.linkfiles is empty.
    - A project with <linkfile> has a non-empty linkfiles list.
    - When exclude is absent, linkfile.exclude is an empty frozenset.
    - Paths with directory separators are stored verbatim.
    - An invalid (path-traversal) src raises ManifestInvalidPathError.
    - An invalid (path-traversal) dest raises ManifestInvalidPathError.
    """

    def test_no_linkfile_child_means_empty_linkfiles_list(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When a <project> has no <linkfile> children, project.linkfiles is empty.

        AC-TEST-003: the default state is an empty linkfiles list.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert project.linkfiles == [], (
            f"Expected project.linkfiles=[] when no <linkfile> children but got: {project.linkfiles!r}"
        )

    def test_linkfile_without_exclude_has_empty_frozenset(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <linkfile> with no exclude attribute has an empty frozenset for exclude.

        AC-TEST-003: when exclude is absent, the default is an empty frozenset.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(
            src="scripts",
            dest="tools/scripts",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        linkfile = project.linkfiles[0]
        assert linkfile.exclude == frozenset(), (
            f"Expected linkfile.exclude=frozenset() when no exclude attribute but got: {linkfile.exclude!r}"
        )

    def test_linkfile_dest_with_nested_dirs_stored_verbatim(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A dest with nested directory separators is stored as-is in the model.

        AC-TEST-003: dest paths with slashes are accepted and stored verbatim.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(
            src="config",
            dest="output/build/config",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        linkfile = project.linkfiles[0]
        assert linkfile.dest == "output/build/config", (
            f"Expected linkfile.dest='output/build/config' (verbatim) but got: {linkfile.dest!r}"
        )

    def test_linkfile_invalid_src_traversal_raises_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <linkfile> with src containing '..' (path traversal) raises ManifestInvalidPathError.

        AC-TEST-003: path validation rejects src that escapes the project worktree.
        Note: src='.' is valid but '..'-based traversal is rejected.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <linkfile src="../escape/secret" dest="out/secret" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert "src" in str(exc_info.value), f"Expected error message to mention 'src' but got: {str(exc_info.value)!r}"

    def test_linkfile_invalid_dest_traversal_raises_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <linkfile> with dest containing '..' (path traversal) raises ManifestInvalidPathError.

        AC-TEST-003: path validation rejects dest that escapes the workspace root.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <linkfile src="scripts" dest="../escape/secret" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert "dest" in str(exc_info.value), (
            f"Expected error message to mention 'dest' but got: {str(exc_info.value)!r}"
        )

    @pytest.mark.parametrize(
        "src,dest",
        [
            ("scripts", "tools/scripts"),
            ("include", "sdk/include"),
            ("bin/tool", "usr/local/bin/tool"),
        ],
    )
    def test_linkfile_project_with_linkfile_has_nonempty_list(
        self,
        tmp_path: pathlib.Path,
        src: str,
        dest: str,
    ) -> None:
        """Parameterized: a project with a <linkfile> always has at least one entry.

        AC-TEST-003: the default is zero linkfiles; any <linkfile> child changes that.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(src=src, dest=dest)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert len(project.linkfiles) >= 1, (
            f"Expected at least 1 linkfile after <linkfile src={src!r} dest={dest!r}> but got 0"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinkfileChannelDiscipline:
    """Verify that parse errors raise exceptions rather than writing to stdout.

    The <linkfile> parser must report errors exclusively through exceptions;
    it must not write error information to stdout. Tests here verify that a
    valid parse is error-free and that parse failures produce the appropriate
    exception type.

    AC-CHANNEL-001 (parser tasks: no stdout leakage for success/failure paths)
    """

    def test_valid_linkfile_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest with a valid <linkfile> does not raise any exception.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_linkfile(
            src="scripts",
            dest="tools/scripts",
        )
        manifest_file = _write_manifest(repodir, xml_content)

        try:
            _load_manifest(repodir, manifest_file)
        except (ManifestParseError, ManifestInvalidPathError) as exc:
            pytest.fail(f"Expected valid <linkfile> manifest to parse without error but got: {exc!r}")

    def test_linkfile_missing_src_raises_exception_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Parsing a <linkfile> with missing src raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <linkfile dest="tools/scripts" />\n'
            "  </project>\n"
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
