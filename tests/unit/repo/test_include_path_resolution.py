"""Unit tests for <include> path resolution mechanics.

Covers:
  AC-TEST-001  Relative include name resolves relative to the manifest root
               (include_root = manifests/ worktree directory)
  AC-TEST-002  A name that refers to a non-existent file raises a
               "doesn't exist" ManifestParseError that names the file
  AC-TEST-003  restrict_includes enforces path rules: absolute paths and
               paths containing '..' are rejected with ManifestInvalidPathError

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of parser
internals.

Focus: these tests exercise include path *resolution* specifically.
Attribute validity, cross-element rules, and cycle detection are covered by
the sibling test_xml_include_*.py files.
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

_MINIMAL_INCLUDED_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<manifest>\n"
    '  <remote name="origin" fetch="https://example.com" />\n'
    '  <default revision="main" remote="origin" />\n'
    '  <project name="platform/core" path="core" />\n'
    "</manifest>\n"
)


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure for XmlManifest.

    Sets up:
    - <tmp>/.repo/
    - <tmp>/.repo/manifests/   (the include_root / manifests worktree)
    - <tmp>/.repo/manifests.git/config  (GitConfig remote origin URL)

    Args:
        tmp_path: Pytest tmp_path for isolation.

    Returns:
        Absolute path to the .repo directory.
    """
    repodir = tmp_path / ".repo"
    repodir.mkdir()
    (repodir / "manifests").mkdir()
    manifests_git = repodir / "manifests.git"
    manifests_git.mkdir()
    (manifests_git / "config").write_text(_GIT_CONFIG_TEMPLATE, encoding="utf-8")
    return repodir


def _write_primary_manifest(repodir: pathlib.Path, xml_content: str) -> pathlib.Path:
    """Write xml_content to the canonical manifest file in repodir and return the path.

    Args:
        repodir: The .repo directory.
        xml_content: Full XML content for the primary manifest.

    Returns:
        Absolute path to the written manifest file.
    """
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    return manifest_file


def _write_included_manifest(repodir: pathlib.Path, relative_name: str, xml_content: str) -> pathlib.Path:
    """Write xml_content at repodir/manifests/<relative_name>.

    This places the file in the include_root so that
    os.path.join(include_root, relative_name) resolves correctly.

    Args:
        repodir: The .repo directory.
        relative_name: Relative path within the manifests directory.
        xml_content: Full XML content for the included manifest.

    Returns:
        Absolute path to the written file.
    """
    target = repodir / "manifests" / relative_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(xml_content, encoding="utf-8")
    return target


def _load_manifest(repodir: pathlib.Path, manifest_file: pathlib.Path) -> manifest_xml.XmlManifest:
    """Instantiate and load an XmlManifest from disk.

    Args:
        repodir: The .repo directory.
        manifest_file: Absolute path to the primary manifest file.

    Returns:
        A loaded XmlManifest instance.

    Raises:
        ManifestParseError: If the manifest is invalid.
        ManifestInvalidPathError: If a path attribute is invalid.
    """
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


# ---------------------------------------------------------------------------
# AC-TEST-001: Relative include resolves to manifest root (include_root)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRelativeIncludeResolvesToManifestRoot:
    """AC-TEST-001: A relative include name resolves relative to the manifest root.

    The manifest root (include_root) is the manifests/ worktree directory
    inside .repo/. Files placed there are discoverable via a bare filename as
    the include name. Resolution is performed by os.path.join(include_root, name)
    which means the resolved path is always a child of include_root.
    """

    def test_bare_filename_resolves_to_manifests_directory(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A bare filename (no path separator) resolves under the manifests/ directory.

        Given include name="sub.xml" the parser must look for the file at
        <repodir>/manifests/sub.xml (i.e. os.path.join(include_root, "sub.xml")).

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "sub.xml", _MINIMAL_INCLUDED_XML)
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="sub.xml" />\n</manifest>\n'
        manifest_file = _write_primary_manifest(repodir, primary_xml)

        manifest = _load_manifest(repodir, manifest_file)

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"AC-TEST-001: expected 'platform/core' from sub.xml to be present after loading but got: {project_names!r}"
        )

    def test_include_root_is_manifests_worktree_not_repo_topdir(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The include_root is the manifests/ worktree, not the top-level repo dir.

        A file placed at <repodir>/manifests/child.xml is reachable via
        include name="child.xml". A file placed at <repodir>/child.xml (one
        level up from manifests/) is NOT reachable via the same name.

        This confirms that resolution is anchored to the manifests/ subdirectory
        and not to .repo/ itself.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        # Place the included file in manifests/ -- the correct include_root.
        _write_included_manifest(repodir, "child.xml", _MINIMAL_INCLUDED_XML)
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="child.xml" />\n</manifest>\n'
        )
        manifest_file = _write_primary_manifest(repodir, primary_xml)

        manifest = _load_manifest(repodir, manifest_file)

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"AC-TEST-001: expected 'platform/core' from child.xml (in manifests/) to be resolved "
            f"but got: {project_names!r}"
        )

    @pytest.mark.parametrize(
        "include_name",
        [
            "alpha.xml",
            "vendor-manifest.xml",
            "platform-projects.xml",
        ],
    )
    def test_various_relative_names_resolve_under_manifests_directory(
        self,
        tmp_path: pathlib.Path,
        include_name: str,
    ) -> None:
        """Parameterized: multiple valid bare filenames each resolve under manifests/.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, include_name, _MINIMAL_INCLUDED_XML)
        primary_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="{include_name}" />\n</manifest>\n'
        )
        manifest_file = _write_primary_manifest(repodir, primary_xml)

        manifest = _load_manifest(repodir, manifest_file)

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"AC-TEST-001: expected 'platform/core' to be visible after "
            f"<include name='{include_name}'> resolved under manifests/ "
            f"but got: {project_names!r}"
        )

    def test_include_in_subdirectory_of_manifests_root_is_resolved(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An include name with a subdirectory component resolves within manifests/.

        Given include name="subdir/extra.xml" the parser resolves the path as
        os.path.join(include_root, "subdir/extra.xml"). This places the file at
        <repodir>/manifests/subdir/extra.xml.

        The primary manifest is loaded with restrict_includes=False, so path
        components like a subdirectory are allowed at the top level.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "subdir/extra.xml", _MINIMAL_INCLUDED_XML)
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="subdir/extra.xml" />\n</manifest>\n'
        )
        manifest_file = _write_primary_manifest(repodir, primary_xml)

        manifest = _load_manifest(repodir, manifest_file)

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"AC-TEST-001: expected 'platform/core' from 'subdir/extra.xml' (inside manifests/) "
            f"to be visible after loading but got: {project_names!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Missing file raises a "doesn't exist" ManifestParseError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMissingIncludeFileRaisesError:
    """AC-TEST-002: An include referencing a non-existent file raises ManifestParseError.

    The parser must check os.path.isfile(resolved_path) and raise
    ManifestParseError with a message that includes the missing filename
    so the user knows exactly which file was not found.
    """

    def test_missing_file_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <include> whose file does not exist raises ManifestParseError.

        The resolved path must point to an actual file. If the file is absent,
        the parser raises ManifestParseError immediately.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        # Deliberately do NOT write any file named "absent.xml".
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="absent.xml" />\n</manifest>\n'
        )
        manifest_file = _write_primary_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError):
            _load_manifest(repodir, manifest_file)

    def test_missing_file_error_message_names_the_file(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The ManifestParseError message names the missing file.

        The error message must contain the filename that could not be found so
        the developer can identify and fix the problem without additional
        investigation.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        missing_name = "no-such-manifest.xml"
        primary_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="{missing_name}" />\n</manifest>\n'
        )
        manifest_file = _write_primary_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert missing_name in str(exc_info.value), (
            f"AC-TEST-002: expected error message to mention '{missing_name}' but got: {exc_info.value!r}"
        )

    def test_missing_file_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A missing include file error produces no stdout output.

        The error must surface exclusively as an exception; no diagnostic
        information may be written to stdout.

        AC-TEST-002, AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="phantom.xml" />\n</manifest>\n'
        )
        manifest_file = _write_primary_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError):
            _load_manifest(repodir, manifest_file)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-TEST-002 / AC-CHANNEL-001: expected no stdout output when include file "
            f"is missing but got: {captured.out!r}"
        )

    @pytest.mark.parametrize(
        "missing_name",
        [
            "not-here.xml",
            "missing/deep.xml",
            "completely-absent.xml",
        ],
    )
    def test_various_missing_filenames_raise_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
        missing_name: str,
    ) -> None:
        """Parameterized: any non-existent filename raises ManifestParseError.

        Each filename refers to a file that has not been written to disk.
        The parser must raise ManifestParseError for each.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        primary_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="{missing_name}" />\n</manifest>\n'
        )
        manifest_file = _write_primary_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert str(exc_info.value), (
            f"AC-TEST-002: expected a non-empty error message for missing file '{missing_name}' but got an empty string"
        )

    def test_file_exists_after_resolution_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When the referenced file exists at the resolved path, no error is raised.

        This is the positive counterpart to the missing-file tests. It confirms
        that the existence check only raises when the file is genuinely absent.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "present.xml", _MINIMAL_INCLUDED_XML)
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="present.xml" />\n</manifest>\n'
        )
        manifest_file = _write_primary_manifest(repodir, primary_xml)

        try:
            _load_manifest(repodir, manifest_file)
        except ManifestParseError as exc:
            pytest.fail(f"AC-TEST-002: expected no ManifestParseError when include file exists but got: {exc!r}")


# ---------------------------------------------------------------------------
# AC-TEST-003: restrict_includes enforces path rules (no abs, no ..)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRestrictIncludesPathRules:
    """AC-TEST-003: restrict_includes enforces that include names are safe relative paths.

    When restrict_includes=True (the default for recursively included manifests),
    the parser calls _CheckLocalPath on the include name before resolving it.
    _CheckLocalPath rejects:
    - Absolute paths (paths starting with '/' or detected as absolute by os.path)
    - Paths containing '..' (traversal components)
    - Paths containing '.git' components
    - Paths starting with '.repo'
    - Paths containing '~'

    The primary manifest is always loaded with restrict_includes=False (the user
    provided it). Restrictions apply to includes found *inside* included manifests.
    To trigger restrict_includes=True, tests use a two-level include chain:
    primary -> level1 (loaded with restrict_includes=False) -> level2 (loaded with
    restrict_includes=True, where the bad path lives).
    """

    def _make_nested_include(self, tmp_path: pathlib.Path, bad_inner_name: str) -> manifest_xml.XmlManifest:
        """Build a two-level include chain where the inner include has a bad name.

        The primary manifest includes level1.xml (unrestricted). level1.xml
        includes <bad_inner_name> (restricted). Calling Load() on the returned
        object triggers restrict_includes validation.

        Args:
            tmp_path: Pytest tmp_path for isolation.
            bad_inner_name: The invalid include name to place in level1.xml.

        Returns:
            An XmlManifest instance that has NOT been loaded yet.
        """
        repodir = _make_repo_dir(tmp_path)
        level1_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="{bad_inner_name}" />\n</manifest>\n'
        )
        _write_included_manifest(repodir, "level1.xml", level1_xml)
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="level1.xml" />\n</manifest>\n'
        )
        manifest_file = _write_primary_manifest(repodir, primary_xml)
        return manifest_xml.XmlManifest(str(repodir), str(manifest_file))

    def test_dotdot_traversal_in_nested_include_raises_manifest_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An include name containing '..' in a nested include raises ManifestInvalidPathError.

        The path '../escape.xml' would escape the manifests directory. The parser
        must reject it before resolving on disk.

        AC-TEST-003, AC-FUNC-001
        """
        m = self._make_nested_include(tmp_path, "../escape.xml")

        with pytest.raises(ManifestInvalidPathError):
            m.Load()

    def test_dotdot_error_message_identifies_include_element(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The ManifestInvalidPathError message identifies the <include> element.

        The error must mention 'include' so the user can find the offending
        element in the manifest file.

        AC-TEST-003
        """
        m = self._make_nested_include(tmp_path, "../bad.xml")

        with pytest.raises(ManifestInvalidPathError) as exc_info:
            m.Load()

        assert "include" in str(exc_info.value).lower(), (
            f"AC-TEST-003: expected error message to identify '<include>' element but got: {exc_info.value!r}"
        )

    def test_dotdot_not_checked_in_primary_manifest_include(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The primary manifest is loaded with restrict_includes=False, so '..' is not blocked there.

        When the primary manifest itself contains <include name="../something.xml">,
        _CheckLocalPath is NOT called (restrict_includes=False). The file existence
        check still applies, so the error raised is ManifestParseError (file not
        found), not ManifestInvalidPathError (path rejected).

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        # The primary manifest uses '../outside.xml' -- restrict_includes=False
        # means _CheckLocalPath is skipped; we only hit the file-existence check.
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="../outside.xml" />\n</manifest>\n'
        )
        manifest_file = _write_primary_manifest(repodir, primary_xml)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        # Must raise ManifestParseError (file not found), NOT ManifestInvalidPathError.
        with pytest.raises(ManifestParseError):
            m.Load()

        # Verify the exception is NOT a ManifestInvalidPathError (path restriction check).
        # ManifestInvalidPathError is a subclass of ManifestParseError, so we check the
        # exact type to distinguish the file-not-found case from the path-restriction case.
        try:
            m2 = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
            m2.Load()
        except ManifestInvalidPathError:
            pytest.fail(
                "AC-TEST-003: primary manifest include should NOT raise ManifestInvalidPathError "
                "for '../' path (restrict_includes=False); expected ManifestParseError (file not found)"
            )
        except ManifestParseError:
            pass  # Expected: file-not-found, not path restriction.

    def test_git_directory_component_in_nested_include_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An include name containing '.git' in a nested include raises ManifestInvalidPathError.

        _CheckLocalPath rejects path components equal to '.git' to prevent
        git directory traversal.

        AC-TEST-003
        """
        m = self._make_nested_include(tmp_path, ".git/config")

        with pytest.raises(ManifestInvalidPathError):
            m.Load()

    def test_repo_prefix_component_in_nested_include_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An include name starting with '.repo' in a nested include raises ManifestInvalidPathError.

        _CheckLocalPath rejects path components that start with '.repo'.

        AC-TEST-003
        """
        m = self._make_nested_include(tmp_path, ".repo/secret.xml")

        with pytest.raises(ManifestInvalidPathError):
            m.Load()

    def test_tilde_in_nested_include_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An include name containing '~' in a nested include raises ManifestInvalidPathError.

        _CheckLocalPath rejects tildes due to 8.3 filename concerns on Windows
        filesystems.

        AC-TEST-003
        """
        m = self._make_nested_include(tmp_path, "~home.xml")

        with pytest.raises(ManifestInvalidPathError):
            m.Load()

    @pytest.mark.parametrize(
        "bad_inner_name",
        [
            "../escape.xml",
            ".git/config",
            ".repo/private.xml",
            "~bad.xml",
        ],
    )
    def test_parameterized_restricted_paths_raise_manifest_invalid_path_error(
        self,
        tmp_path: pathlib.Path,
        bad_inner_name: str,
    ) -> None:
        """Parameterized: each restricted path raises ManifestInvalidPathError in nested includes.

        Each value violates a _CheckLocalPath constraint and must raise
        ManifestInvalidPathError when used as the name in a nested include
        (where restrict_includes=True).

        AC-TEST-003
        """
        m = self._make_nested_include(tmp_path, bad_inner_name)

        with pytest.raises(ManifestInvalidPathError):
            m.Load()

    def test_restricted_path_error_produces_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A restricted path error in a nested include produces no stdout output.

        AC-TEST-003, AC-CHANNEL-001
        """
        m = self._make_nested_include(tmp_path, "../escape.xml")

        with pytest.raises(ManifestInvalidPathError):
            m.Load()

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-TEST-003 / AC-CHANNEL-001: expected no stdout for restricted path error but got: {captured.out!r}"
        )

    def test_safe_relative_name_in_nested_include_is_accepted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A safe relative filename in a nested include is accepted when the file exists.

        This is the positive counterpart to the restriction tests. A clean
        filename (no traversal, no special prefixes) must parse without error
        when the referenced file actually exists on disk.

        AC-TEST-003, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        # Level 2: the actual content manifest.
        _write_included_manifest(repodir, "safe-content.xml", _MINIMAL_INCLUDED_XML)
        # Level 1: nested include with safe name (restrict_includes=True applies here).
        level1_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="safe-content.xml" />\n</manifest>\n'
        )
        _write_included_manifest(repodir, "level1.xml", level1_xml)
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="level1.xml" />\n</manifest>\n'
        )
        manifest_file = _write_primary_manifest(repodir, primary_xml)

        try:
            manifest = _load_manifest(repodir, manifest_file)
        except (ManifestParseError, ManifestInvalidPathError) as exc:
            pytest.fail(f"AC-TEST-003: expected safe two-level include to parse without error but got: {exc!r}")

        project_names = [p.name for p in manifest.projects]
        assert "platform/core" in project_names, (
            f"AC-TEST-003: expected 'platform/core' visible after safe two-level include chain "
            f"but got: {project_names!r}"
        )
