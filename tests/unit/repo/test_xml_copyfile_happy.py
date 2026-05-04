"""Unit tests for the <copyfile> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <copyfile> XML elements parse correctly when given
minimum required attributes, all documented attributes, and that default
attribute values behave as documented.

The <copyfile> element is a child of <project> and declares a file to be
copied from the project checkout into the workspace root. Documented
attributes:
  Required: src  (relative path within the project checkout to read from)
  Required: dest (relative path from the workspace root to write to)

<copyfile> has no optional attributes beyond src and dest.
Multiple <copyfile> children may be nested inside one <project> element.
When no <copyfile> children are present, project.copyfiles is empty.

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


def _build_manifest_with_copyfile(
    src: str,
    dest: str,
    project_name: str = "platform/core",
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
) -> str:
    """Build a manifest XML string with a <project> containing one <copyfile>.

    Args:
        src: The src attribute for the <copyfile> element.
        dest: The dest attribute for the <copyfile> element.
        project_name: The name attribute for the <project> element.
        remote_name: The name attribute for the <remote> element.
        fetch_url: The fetch attribute for the <remote> element.
        default_revision: The revision on the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        f'  <project name="{project_name}">\n'
        f'    <copyfile src="{src}" dest="{dest}" />\n'
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
# AC-TEST-001: Valid <copyfile> with minimum required attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCopyfileMinimumAttributes:
    """Verify that a <copyfile> element with only required attributes parses correctly.

    The minimum valid <copyfile> requires src and dest. Both are required and
    there are no optional attributes beyond them.
    """

    def test_copyfile_minimum_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with a <copyfile src='...' dest='...'> parses without error.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_copyfile(
            src="VERSION",
            dest="out/VERSION",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest is not None, "Expected XmlManifest instance but got None"

    def test_copyfile_appears_in_project_copyfiles(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing, the <copyfile> appears in the parent project's copyfiles list.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_copyfile(
            src="VERSION",
            dest="out/VERSION",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) == 1, f"Expected exactly 1 copyfile on project but got: {len(project.copyfiles)}"

    def test_copyfile_src_attribute_stored_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The parsed copyfile model stores the src attribute from the XML.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_copyfile(
            src="VERSION",
            dest="out/VERSION",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        copyfile = project.copyfiles[0]
        assert copyfile.src == "VERSION", f"Expected copyfile.src='VERSION' but got: {copyfile.src!r}"

    def test_copyfile_dest_attribute_stored_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The parsed copyfile model stores the dest attribute from the XML.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_copyfile(
            src="VERSION",
            dest="out/VERSION",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        copyfile = project.copyfiles[0]
        assert copyfile.dest == "out/VERSION", f"Expected copyfile.dest='out/VERSION' but got: {copyfile.dest!r}"

    @pytest.mark.parametrize(
        "src,dest",
        [
            ("VERSION", "out/VERSION"),
            ("build/config.h", "include/config.h"),
            ("LICENSE", "THIRD_PARTY/license.txt"),
            ("scripts/setup.sh", "tools/setup.sh"),
        ],
    )
    def test_copyfile_src_and_dest_parsed_for_various_values(
        self,
        tmp_path: pathlib.Path,
        src: str,
        dest: str,
    ) -> None:
        """Parameterized: various src and dest path values are parsed and stored correctly.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_copyfile(src=src, dest=dest)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) == 1, (
            f"Expected 1 copyfile for src={src!r}, dest={dest!r} but got: {len(project.copyfiles)}"
        )
        copyfile = project.copyfiles[0]
        assert copyfile.src == src, f"Expected copyfile.src={src!r} but got: {copyfile.src!r}"
        assert copyfile.dest == dest, f"Expected copyfile.dest={dest!r} but got: {copyfile.dest!r}"

    def test_copyfile_missing_src_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <copyfile> missing the required src attribute raises ManifestParseError.

        AC-TEST-001: required attributes have no default and must be provided.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), (
            "Expected a non-empty error message from ManifestParseError for missing src but got empty string"
        )

    def test_copyfile_missing_dest_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <copyfile> missing the required dest attribute raises ManifestParseError.

        AC-TEST-001: required attributes have no default and must be provided.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" />\n'
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
# AC-TEST-002: Valid <copyfile> with all documented attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCopyfileAllDocumentedAttributes:
    """Verify that a <copyfile> element with all documented attributes parses correctly.

    The <copyfile> element documents two attributes:
    - src:  required, the relative path within the project checkout to read
    - dest: required, the relative path from the workspace root to write to

    Multiple <copyfile> elements may appear as children of the same <project>.
    """

    def test_copyfile_with_src_and_dest_parses_model_with_both(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <copyfile src='...' dest='...'> parses both attributes into the model.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_copyfile(
            src="scripts/build.sh",
            dest="tools/build.sh",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) == 1, f"Expected 1 copyfile but got: {len(project.copyfiles)}"
        copyfile = project.copyfiles[0]
        assert copyfile.src == "scripts/build.sh", f"Expected copyfile.src='scripts/build.sh' but got: {copyfile.src!r}"
        assert copyfile.dest == "tools/build.sh", f"Expected copyfile.dest='tools/build.sh' but got: {copyfile.dest!r}"

    def test_multiple_copyfile_elements_in_one_project_parse_all(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Multiple <copyfile> children in one <project> are all parsed correctly.

        AC-TEST-002: multiple copyfiles in a project populate copyfiles list in order.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            '    <copyfile src="LICENSE" dest="THIRD_PARTY/LICENSE" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) == 2, f"Expected 2 copyfiles but got: {len(project.copyfiles)}"
        srcs = [cf.src for cf in project.copyfiles]
        dests = [cf.dest for cf in project.copyfiles]
        assert "VERSION" in srcs, f"Expected 'VERSION' in copyfile srcs but got: {srcs!r}"
        assert "LICENSE" in srcs, f"Expected 'LICENSE' in copyfile srcs but got: {srcs!r}"
        assert "out/VERSION" in dests, f"Expected 'out/VERSION' in copyfile dests but got: {dests!r}"
        assert "THIRD_PARTY/LICENSE" in dests, f"Expected 'THIRD_PARTY/LICENSE' in copyfile dests but got: {dests!r}"

    def test_copyfile_in_different_projects_are_isolated(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """<copyfile> elements in different <project> elements are correctly isolated.

        AC-TEST-002: copyfiles from project A must not appear on project B.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            '  <project name="platform/tools" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        core = _get_project(manifest, "platform/core")
        tools = _get_project(manifest, "platform/tools")
        assert len(core.copyfiles) == 1, f"Expected 1 copyfile on platform/core but got: {len(core.copyfiles)}"
        assert len(tools.copyfiles) == 0, (
            f"Expected 0 copyfiles on platform/tools (no <copyfile> child) but got: {len(tools.copyfiles)}"
        )

    def test_copyfile_git_worktree_stored_from_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The parsed copyfile stores the parent project's git_worktree path.

        AC-TEST-002: the copyfile model retains the project worktree for use
        during the actual file copy operation.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_copyfile(
            src="VERSION",
            dest="out/VERSION",
            project_name="platform/core",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        copyfile = project.copyfiles[0]
        assert copyfile.git_worktree is not None, "Expected copyfile.git_worktree to be set but got None"
        assert "platform" in copyfile.git_worktree or "core" in copyfile.git_worktree, (
            f"Expected copyfile.git_worktree to reference project path but got: {copyfile.git_worktree!r}"
        )

    def test_copyfile_topdir_stored_from_manifest(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The parsed copyfile stores the manifest topdir for resolving dest paths.

        AC-TEST-002: the copyfile model retains the topdir for use during the
        actual file copy operation.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_copyfile(
            src="VERSION",
            dest="out/VERSION",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        copyfile = project.copyfiles[0]
        assert copyfile.topdir is not None, "Expected copyfile.topdir to be set but got None"


# ---------------------------------------------------------------------------
# AC-TEST-003: <copyfile> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCopyfileDefaultAttributeValues:
    """Verify that default attribute values on <copyfile> behave as documented.

    The <copyfile> element documents no optional attributes. The relevant
    default behaviors are:
    - When no <copyfile> children are present, project.copyfiles is empty.
    - A project with <copyfile> has a non-empty copyfiles list.
    - Paths with directory separators are stored verbatim.
    - An invalid (path-traversal) src raises ManifestInvalidPathError.
    - An invalid (path-traversal) dest raises ManifestInvalidPathError.
    """

    def test_no_copyfile_child_means_empty_copyfiles_list(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When a <project> has no <copyfile> children, project.copyfiles is empty.

        AC-TEST-003: the default state is an empty copyfiles list.
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
        assert project.copyfiles == [], (
            f"Expected project.copyfiles=[] when no <copyfile> children but got: {project.copyfiles!r}"
        )

    def test_copyfile_dest_with_nested_dirs_stored_verbatim(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A dest with nested directory separators is stored as-is in the model.

        AC-TEST-003: dest paths with slashes are accepted and stored verbatim.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_copyfile(
            src="config/build.mk",
            dest="output/build/config/build.mk",
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        copyfile = project.copyfiles[0]
        assert copyfile.dest == "output/build/config/build.mk", (
            f"Expected copyfile.dest='output/build/config/build.mk' (verbatim) but got: {copyfile.dest!r}"
        )

    def test_copyfile_invalid_src_traversal_raises_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <copyfile> with src containing '..' (path traversal) raises ManifestInvalidPathError.

        AC-TEST-003: path validation rejects src that escapes the project checkout.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="../escape/secret" dest="out/secret" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert "src" in str(exc_info.value), f"Expected error message to mention 'src' but got: {str(exc_info.value)!r}"

    def test_copyfile_invalid_dest_traversal_raises_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <copyfile> with dest containing '..' (path traversal) raises ManifestInvalidPathError.

        AC-TEST-003: path validation rejects dest that escapes the workspace root.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="../escape/secret" />\n'
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
            ("VERSION", "VERSION"),
            ("README.md", "docs/README.md"),
            ("include/types.h", "sdk/include/types.h"),
        ],
    )
    def test_copyfile_project_with_copyfile_has_nonempty_list(
        self,
        tmp_path: pathlib.Path,
        src: str,
        dest: str,
    ) -> None:
        """Parameterized: a project with a <copyfile> always has at least one entry.

        AC-TEST-003: the default is zero copyfiles; any <copyfile> child changes that.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_copyfile(src=src, dest=dest)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) >= 1, (
            f"Expected at least 1 copyfile after <copyfile src={src!r} dest={dest!r}> but got 0"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCopyfileChannelDiscipline:
    """Verify that parse errors raise exceptions rather than writing to stdout.

    The <copyfile> parser must report errors exclusively through exceptions;
    it must not write error information to stdout. Tests here verify that a
    valid parse is error-free and that parse failures produce the appropriate
    exception type.

    AC-CHANNEL-001 (parser tasks: no stdout leakage for success/failure paths)
    """

    def test_valid_copyfile_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest with a valid <copyfile> does not raise any exception.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_copyfile(
            src="VERSION",
            dest="out/VERSION",
        )
        manifest_file = _write_manifest(repodir, xml_content)

        try:
            _load_manifest(repodir, manifest_file)
        except (ManifestParseError, ManifestInvalidPathError) as exc:
            pytest.fail(f"Expected valid <copyfile> manifest to parse without error but got: {exc!r}")

    def test_copyfile_missing_src_raises_exception_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Parsing a <copyfile> with missing src raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile dest="out/VERSION" />\n'
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
