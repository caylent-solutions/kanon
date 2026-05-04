"""Unit tests for <copyfile> attribute validation (positive + negative).

Covers:
  AC-TEST-001  Every attribute of <copyfile> has a valid-value test
  AC-TEST-002  Every attribute has invalid-value tests that raise
               ManifestParseError or ManifestInvalidPathError
  AC-TEST-003  Required attribute omission raises with message naming
               the attribute
  AC-FUNC-001  Every documented attribute of <copyfile> is validated
               at parse time
  AC-CHANNEL-001  stdout vs stderr discipline is verified (no cross-channel
                  leakage)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

The <copyfile> element documented attributes:
  Required: src   -- relative path within the project checkout to read from.
                     Validated at parse time: must not traverse outside the
                     project (no '..', no absolute, no '~', no '.git',
                     no '.repo*', no bad Unicode codepoints, no newlines).
  Required: dest  -- relative path from the workspace root to write to.
                     Same path-safety rules as src, except absolute paths
                     are NOT allowed (unlike linkfile dest).

Documented constraints for invalid-value tests:
  - src omitted (or blank)  -> ManifestParseError naming "src"
  - dest omitted (or blank) -> ManifestParseError naming "dest"
  - src contains '..'       -> ManifestInvalidPathError mentioning "src"
  - dest contains '..'      -> ManifestInvalidPathError mentioning "dest"
  - src is absolute         -> ManifestInvalidPathError mentioning "src"
  - dest is absolute        -> ManifestInvalidPathError mentioning "dest"
  - src contains '~'        -> ManifestInvalidPathError mentioning "src"
  - dest contains '~'       -> ManifestInvalidPathError mentioning "dest"
  - src contains '.git'     -> ManifestInvalidPathError mentioning "src"
  - dest contains '.repo'   -> ManifestInvalidPathError mentioning "dest"

Note: When IsMirror is True, _ValidateFilePaths is not called and copyfiles
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
        ManifestParseError: If the manifest is invalid.
        ManifestInvalidPathError: If an attribute contains an invalid path.
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


def _manifest_with_copyfile(src: str, dest: str) -> str:
    """Build a complete manifest XML string containing a <copyfile> element.

    Args:
        src: Value for the src attribute of <copyfile>.
        dest: Value for the dest attribute of <copyfile>.

    Returns:
        Full manifest XML string with a project containing one copyfile.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core">\n'
        f'    <copyfile src="{src}" dest="{dest}" />\n'
        "  </project>\n"
        "</manifest>\n"
    )


def _manifest_without_src(dest: str) -> str:
    """Build a manifest XML string with a <copyfile> element missing the src attribute.

    Args:
        dest: Value for the dest attribute of <copyfile>.

    Returns:
        Full manifest XML string with a project containing a copyfile without src.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core">\n'
        f'    <copyfile dest="{dest}" />\n'
        "  </project>\n"
        "</manifest>\n"
    )


def _manifest_without_dest(src: str) -> str:
    """Build a manifest XML string with a <copyfile> element missing the dest attribute.

    Args:
        src: Value for the src attribute of <copyfile>.

    Returns:
        Full manifest XML string with a project containing a copyfile without dest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="platform/core">\n'
        f'    <copyfile src="{src}" />\n'
        "  </project>\n"
        "</manifest>\n"
    )


def _get_copyfile(manifest: manifest_xml.XmlManifest, project_name: str):
    """Return the first copyfile from the named project.

    Args:
        manifest: A loaded XmlManifest instance.
        project_name: The name attribute of the target project.

    Returns:
        The first _CopyFile model object attached to the project.
    """
    by_name = {p.name: p for p in manifest.projects}
    project = by_name[project_name]
    return project.copyfiles[0]


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every documented attribute of <copyfile>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCopyfileSrcValidValues:
    """AC-TEST-001 -- valid values accepted for the src attribute.

    src must be a path that is relative to the project checkout, free from
    path-traversal components and other disallowed patterns. Valid paths
    include simple filenames, nested relative paths with forward slashes,
    and paths containing underscores, dots-within-filenames, and hyphens.
    """

    @pytest.mark.parametrize(
        "src",
        [
            "VERSION",
            "build/config.mk",
            "include/types.h",
            "scripts/setup.sh",
            "a/b/c/deep.txt",
            "README.md",
            "src/main.py",
        ],
    )
    def test_src_valid_relative_paths_accepted(self, tmp_path: pathlib.Path, src: str) -> None:
        """Valid relative src paths parse without error and are stored on the model.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = _manifest_with_copyfile(src=src, dest="out/file.txt")
        manifest = _write_and_load(tmp_path, xml_content)
        copyfile = _get_copyfile(manifest, "platform/core")
        assert copyfile.src == src, f"Expected copyfile.src={src!r} but got: {copyfile.src!r}"

    def test_src_filename_with_hyphen_accepted(self, tmp_path: pathlib.Path) -> None:
        """A src path containing a hyphen is accepted and stored verbatim.

        AC-TEST-001
        """
        src = "my-script.sh"
        xml_content = _manifest_with_copyfile(src=src, dest="tools/my-script.sh")
        manifest = _write_and_load(tmp_path, xml_content)
        copyfile = _get_copyfile(manifest, "platform/core")
        assert copyfile.src == src, f"Expected copyfile.src={src!r} but got: {copyfile.src!r}"

    def test_src_filename_with_underscore_accepted(self, tmp_path: pathlib.Path) -> None:
        """A src path containing an underscore is accepted and stored verbatim.

        AC-TEST-001
        """
        src = "build_config.h"
        xml_content = _manifest_with_copyfile(src=src, dest="include/build_config.h")
        manifest = _write_and_load(tmp_path, xml_content)
        copyfile = _get_copyfile(manifest, "platform/core")
        assert copyfile.src == src, f"Expected copyfile.src={src!r} but got: {copyfile.src!r}"


@pytest.mark.unit
class TestCopyfileDestValidValues:
    """AC-TEST-001 -- valid values accepted for the dest attribute.

    dest must be a relative path from the workspace root. Valid paths
    include simple filenames and nested relative paths with forward slashes.
    Absolute paths are NOT valid for dest (unlike linkfile).
    """

    @pytest.mark.parametrize(
        "dest",
        [
            "VERSION",
            "out/VERSION",
            "output/build/config/build.mk",
            "docs/README.md",
            "sdk/include/types.h",
            "tools/setup.sh",
        ],
    )
    def test_dest_valid_relative_paths_accepted(self, tmp_path: pathlib.Path, dest: str) -> None:
        """Valid relative dest paths parse without error and are stored on the model.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = _manifest_with_copyfile(src="VERSION", dest=dest)
        manifest = _write_and_load(tmp_path, xml_content)
        copyfile = _get_copyfile(manifest, "platform/core")
        assert copyfile.dest == dest, f"Expected copyfile.dest={dest!r} but got: {copyfile.dest!r}"

    def test_dest_with_deeply_nested_path_accepted(self, tmp_path: pathlib.Path) -> None:
        """A deeply nested dest path is accepted and stored verbatim.

        AC-TEST-001
        """
        dest = "a/b/c/d/e/file.txt"
        xml_content = _manifest_with_copyfile(src="VERSION", dest=dest)
        manifest = _write_and_load(tmp_path, xml_content)
        copyfile = _get_copyfile(manifest, "platform/core")
        assert copyfile.dest == dest, f"Expected copyfile.dest={dest!r} but got: {copyfile.dest!r}"


# ---------------------------------------------------------------------------
# AC-TEST-002: Invalid-value tests for every documented attribute of <copyfile>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCopyfileSrcInvalidValues:
    """AC-TEST-002 -- invalid values for the src attribute raise ManifestInvalidPathError.

    The _ValidateFilePaths helper validates src with _CheckLocalPath and
    raises ManifestInvalidPathError naming the "src" attribute on failure.
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
        xml_content = _manifest_with_copyfile(src=bad_src, dest="out/file.txt")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "src" in str(exc_info.value), f"Expected error message to mention 'src' but got: {str(exc_info.value)!r}"

    def test_src_absolute_path_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """An absolute src path (starting with /) raises ManifestInvalidPathError.

        AC-TEST-002: absolute paths are not allowed for copyfile src.
        """
        xml_content = _manifest_with_copyfile(src="/etc/passwd", dest="out/file.txt")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "src" in str(exc_info.value), f"Expected error message to mention 'src' but got: {str(exc_info.value)!r}"

    def test_src_tilde_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A src path containing '~' raises ManifestInvalidPathError.

        AC-TEST-002: ~ is rejected to prevent 8.3 filesystem naming issues.
        """
        xml_content = _manifest_with_copyfile(src="~/secret", dest="out/file.txt")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "src" in str(exc_info.value), f"Expected error message to mention 'src' but got: {str(exc_info.value)!r}"

    def test_src_dotgit_component_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A src path with a '.git' component raises ManifestInvalidPathError.

        AC-TEST-002: .git components are rejected to prevent accessing git internals.
        """
        xml_content = _manifest_with_copyfile(src=".git/config", dest="out/file.txt")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "src" in str(exc_info.value), f"Expected error message to mention 'src' but got: {str(exc_info.value)!r}"

    def test_src_dotrepo_component_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A src path with a '.repo' component raises ManifestInvalidPathError.

        AC-TEST-002: .repo components are rejected to prevent accessing repo internals.
        """
        xml_content = _manifest_with_copyfile(src=".repo/manifest.xml", dest="out/file.txt")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "src" in str(exc_info.value), f"Expected error message to mention 'src' but got: {str(exc_info.value)!r}"


@pytest.mark.unit
class TestCopyfileDestInvalidValues:
    """AC-TEST-002 -- invalid values for the dest attribute raise ManifestInvalidPathError.

    The _ValidateFilePaths helper validates dest with _CheckLocalPath and
    raises ManifestInvalidPathError naming the "dest" attribute on failure.
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
        xml_content = _manifest_with_copyfile(src="VERSION", dest=bad_dest)
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "dest" in str(exc_info.value), (
            f"Expected error message to mention 'dest' but got: {str(exc_info.value)!r}"
        )

    def test_dest_absolute_path_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """An absolute dest path (starting with /) raises ManifestInvalidPathError.

        AC-TEST-002: absolute paths are not allowed for copyfile dest (unlike linkfile).
        """
        xml_content = _manifest_with_copyfile(src="VERSION", dest="/tmp/output/file.txt")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "dest" in str(exc_info.value), (
            f"Expected error message to mention 'dest' but got: {str(exc_info.value)!r}"
        )

    def test_dest_tilde_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A dest path containing '~' raises ManifestInvalidPathError.

        AC-TEST-002: ~ is rejected to prevent 8.3 filesystem naming issues.
        """
        xml_content = _manifest_with_copyfile(src="VERSION", dest="~/output/file.txt")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "dest" in str(exc_info.value), (
            f"Expected error message to mention 'dest' but got: {str(exc_info.value)!r}"
        )

    def test_dest_dotgit_component_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A dest path with a '.git' component raises ManifestInvalidPathError.

        AC-TEST-002: .git components are rejected to prevent writing into git internals.
        """
        xml_content = _manifest_with_copyfile(src="VERSION", dest=".git/config")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "dest" in str(exc_info.value), (
            f"Expected error message to mention 'dest' but got: {str(exc_info.value)!r}"
        )

    def test_dest_dotrepo_component_raises_invalid_path_error(self, tmp_path: pathlib.Path) -> None:
        """A dest path with a '.repo' component raises ManifestInvalidPathError.

        AC-TEST-002: .repo components are rejected to prevent writing into repo internals.
        """
        xml_content = _manifest_with_copyfile(src="VERSION", dest=".repo/manifest.xml")
        with pytest.raises(ManifestInvalidPathError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "dest" in str(exc_info.value), (
            f"Expected error message to mention 'dest' but got: {str(exc_info.value)!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Required attribute omission raises with message naming the attribute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCopyfileRequiredAttributeOmission:
    """AC-TEST-003 -- omitting a required attribute raises ManifestParseError
    with a message that names the missing attribute.

    The _reqatt helper raises ManifestParseError("no {attr} in <copyfile> within {file}")
    when an attribute is absent or blank.
    """

    def test_missing_src_raises_parse_error_naming_src(self, tmp_path: pathlib.Path) -> None:
        """Omitting the src attribute raises ManifestParseError mentioning 'src'.

        AC-TEST-003
        """
        xml_content = _manifest_without_src(dest="out/VERSION")
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "src" in str(exc_info.value), (
            f"Expected error message to name 'src' attribute but got: {str(exc_info.value)!r}"
        )

    def test_missing_dest_raises_parse_error_naming_dest(self, tmp_path: pathlib.Path) -> None:
        """Omitting the dest attribute raises ManifestParseError mentioning 'dest'.

        AC-TEST-003
        """
        xml_content = _manifest_without_dest(src="VERSION")
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert "dest" in str(exc_info.value), (
            f"Expected error message to name 'dest' attribute but got: {str(exc_info.value)!r}"
        )

    @pytest.mark.parametrize(
        "attr_name,xml_builder",
        [
            ("src", lambda: _manifest_without_src("out/file.txt")),
            ("dest", lambda: _manifest_without_dest("VERSION")),
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
        xml_content = _manifest_without_src(dest="out/VERSION")
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError for missing src"

    def test_missing_dest_error_message_is_nonempty(self, tmp_path: pathlib.Path) -> None:
        """The ManifestParseError raised for missing dest has a non-empty message.

        AC-TEST-003: error messages must be actionable -- not an empty string.
        """
        xml_content = _manifest_without_dest(src="VERSION")
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError for missing dest"


# ---------------------------------------------------------------------------
# AC-FUNC-001: Every documented attribute is validated at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCopyfileParseTimeValidation:
    """AC-FUNC-001 -- every documented attribute is validated during manifest load.

    Validation must occur at parse time (during m.Load()), not deferred to
    sync/copy time. Tests confirm that invalid values raise immediately on Load.
    """

    def test_invalid_src_detected_at_parse_not_sync_time(self, tmp_path: pathlib.Path) -> None:
        """Path-traversal src is detected and raised during manifest load, not later.

        AC-FUNC-001
        """
        xml_content = _manifest_with_copyfile(src="../evil", dest="out/file.txt")
        with pytest.raises((ManifestParseError, ManifestInvalidPathError)):
            _write_and_load(tmp_path, xml_content)

    def test_invalid_dest_detected_at_parse_not_sync_time(self, tmp_path: pathlib.Path) -> None:
        """Path-traversal dest is detected and raised during manifest load, not later.

        AC-FUNC-001
        """
        xml_content = _manifest_with_copyfile(src="VERSION", dest="../evil")
        with pytest.raises((ManifestParseError, ManifestInvalidPathError)):
            _write_and_load(tmp_path, xml_content)

    def test_valid_src_and_dest_produce_copyfile_model(self, tmp_path: pathlib.Path) -> None:
        """Both valid src and dest produce a populated copyfile on the project model.

        AC-FUNC-001: attributes are validated AND their values stored on the model.
        """
        src = "VERSION"
        dest = "out/VERSION"
        xml_content = _manifest_with_copyfile(src=src, dest=dest)
        manifest = _write_and_load(tmp_path, xml_content)

        by_name = {p.name: p for p in manifest.projects}
        project = by_name["platform/core"]
        assert len(project.copyfiles) == 1, (
            f"Expected exactly 1 copyfile after valid parse but got: {len(project.copyfiles)}"
        )
        copyfile = project.copyfiles[0]
        assert copyfile.src == src, f"Expected src={src!r} but got: {copyfile.src!r}"
        assert copyfile.dest == dest, f"Expected dest={dest!r} but got: {copyfile.dest!r}"

    @pytest.mark.parametrize(
        "src,dest",
        [
            ("VERSION", "out/VERSION"),
            ("build/config.h", "include/config.h"),
            ("scripts/run.sh", "tools/run.sh"),
        ],
    )
    def test_all_documented_attributes_accepted_for_various_paths(
        self, tmp_path: pathlib.Path, src: str, dest: str
    ) -> None:
        """Parameterized: all documented attribute combinations are accepted at parse time.

        AC-FUNC-001
        """
        xml_content = _manifest_with_copyfile(src=src, dest=dest)
        manifest = _write_and_load(tmp_path, xml_content)
        copyfile = _get_copyfile(manifest, "platform/core")
        assert copyfile.src == src, f"Expected src={src!r} but got: {copyfile.src!r}"
        assert copyfile.dest == dest, f"Expected dest={dest!r} but got: {copyfile.dest!r}"


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCopyfileChannelDiscipline:
    """AC-CHANNEL-001 -- parse errors must not write to stdout.

    Error information for invalid <copyfile> attributes must be conveyed
    exclusively through raised exceptions. No error text must appear on
    stdout. Successful parses must not produce any output on stdout either.
    """

    def test_valid_copyfile_produces_no_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Parsing a valid <copyfile> produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = _manifest_with_copyfile(src="VERSION", dest="out/VERSION")
        _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout for valid parse but got: {captured.out!r}"

    def test_missing_src_raises_exception_not_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Missing src attribute raises ManifestParseError; no error written to stdout.

        AC-CHANNEL-001
        """
        xml_content = _manifest_without_src(dest="out/VERSION")
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout when ManifestParseError is raised but got: {captured.out!r}"

    def test_missing_dest_raises_exception_not_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Missing dest attribute raises ManifestParseError; no error written to stdout.

        AC-CHANNEL-001
        """
        xml_content = _manifest_without_dest(src="VERSION")
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout when ManifestParseError is raised but got: {captured.out!r}"

    def test_invalid_src_path_raises_exception_not_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Invalid src path raises ManifestInvalidPathError; no error written to stdout.

        AC-CHANNEL-001
        """
        xml_content = _manifest_with_copyfile(src="../escape", dest="out/file.txt")
        with pytest.raises((ManifestParseError, ManifestInvalidPathError)):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout when ManifestInvalidPathError is raised but got: {captured.out!r}"

    def test_invalid_dest_path_raises_exception_not_stdout(self, tmp_path: pathlib.Path, capsys) -> None:
        """Invalid dest path raises ManifestInvalidPathError; no error written to stdout.

        AC-CHANNEL-001
        """
        xml_content = _manifest_with_copyfile(src="VERSION", dest="../escape")
        with pytest.raises((ManifestParseError, ManifestInvalidPathError)):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"Expected no stdout when ManifestInvalidPathError is raised but got: {captured.out!r}"
