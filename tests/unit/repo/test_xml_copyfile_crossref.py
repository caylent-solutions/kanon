"""Unit tests for <copyfile> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <copyfile> are validated
               (remote name resolution -- a <copyfile> lives inside a
               <project> whose remote attribute must reference a declared
               <remote> element; an undeclared remote on the parent project
               raises ManifestParseError; when the parent project uses the
               default remote, <copyfile> is parsed correctly; the copyfile
               model reflects the parent project's resolved remote)
  AC-TEST-002  Duplicate-element rules for <copyfile> surface clear errors
               (two <copyfile> elements with identical src and dest in the
               same <project> are accepted silently and both appear in the
               copyfiles list -- the parser does not deduplicate; two
               <copyfile> elements with the same dest but different srcs are
               accepted; two <copyfile> elements with the same src but
               different dests are accepted)
  AC-TEST-003  <copyfile> in an unexpected parent raises or is ignored per
               spec (a manifest file whose root element is not <manifest>
               raises ManifestParseError before any children are examined;
               a <copyfile> element at the <manifest> root level -- not
               inside a <project> -- is silently ignored by the parser loop)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules
               documented for <copyfile> at parse time (during
               XmlManifest.Load())
  AC-CHANNEL-001  stdout vs stderr discipline is verified (errors raise
                  ManifestParseError, not stdout writes; valid parses
                  produce no stdout output)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

Cross-element rules for <copyfile>:
- <copyfile> is a child element of <project>.
- The parent <project> must have a resolvable remote (explicit remote
  attribute referencing a declared <remote>, or a <default> remote).
  An unresolvable parent project raises ManifestParseError before
  <copyfile> is processed.
- Duplicate <copyfile> elements (identical src and dest) inside the same
  <project> are accepted by the parser; both entries appear in the
  copyfiles list.
- A <copyfile> element placed at the <manifest> root level (outside any
  <project>) is silently ignored -- the parser loop in _ParseManifest
  does not handle 'copyfile' node names at that level.
- A manifest file whose root element is not <manifest> raises
  ManifestParseError before any children are examined.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers -- same pattern as other test_xml_*_crossref.py files
# ---------------------------------------------------------------------------

_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest.

    Args:
        tmp_path: Pytest-provided temporary directory for test isolation.

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


def _write_and_load(tmp_path: pathlib.Path, xml_content: str) -> manifest_xml.XmlManifest:
    """Write xml_content to a manifest file and load it.

    Args:
        tmp_path: Pytest-provided temporary directory for test isolation.
        xml_content: Full XML content for the manifest file.

    Returns:
        A loaded XmlManifest instance.

    Raises:
        ManifestParseError: If the manifest is invalid.
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = _write_manifest(repodir, xml_content)
    return _load_manifest(repodir, manifest_file)


def _get_project(manifest: manifest_xml.XmlManifest, project_name: str):
    """Return the project with the given name from the manifest.

    Args:
        manifest: A loaded XmlManifest instance.
        project_name: The name attribute of the target project.

    Returns:
        The Project object with the given name.
    """
    return {p.name: p for p in manifest.projects}[project_name]


# ---------------------------------------------------------------------------
# AC-TEST-001: Cross-element reference validation for <copyfile>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCopyfileCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <copyfile> are validated.

    A <copyfile> element lives inside a <project>. The cross-element reference
    is the parent <project>'s remote attribute, which must resolve to a declared
    <remote> element. When the parent project references an undeclared remote,
    ManifestParseError is raised before <copyfile> is processed.

    When the parent project's remote resolves correctly, the <copyfile> is
    parsed and the copyfiles list on the project is populated.
    """

    def test_copyfile_parent_project_with_declared_remote_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <copyfile> inside a <project remote="..."> naming a declared remote parses.

        The parent project's remote resolves correctly, so the <copyfile>
        is processed and appears in the project's copyfiles list.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" remote="origin">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) == 1, (
            f"AC-TEST-001: expected 1 copyfile when parent project's remote resolves but got: {len(project.copyfiles)}"
        )
        assert project.copyfiles[0].src == "VERSION", (
            f"AC-TEST-001: expected copyfile.src='VERSION' but got: {project.copyfiles[0].src!r}"
        )

    def test_copyfile_parent_project_with_undeclared_remote_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <copyfile> inside a <project> with an undeclared remote raises ManifestParseError.

        The parent project's remote cannot be resolved, so ManifestParseError
        is raised before the <copyfile> child is processed.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" remote="ghost-remote">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-001: expected a non-empty ManifestParseError when parent project's "
            "remote is undeclared but got an empty string"
        )
        assert "ghost-remote" in error_message or "not defined" in error_message, (
            f"AC-TEST-001: expected error to name 'ghost-remote' or 'not defined' but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "undeclared_remote",
        [
            "missing-remote",
            "phantom",
            "ORIGIN",
        ],
    )
    def test_copyfile_parent_project_various_undeclared_remotes_raise(
        self,
        tmp_path: pathlib.Path,
        undeclared_remote: str,
    ) -> None:
        """Parameterized: each undeclared remote on the parent project raises ManifestParseError.

        The error must be non-empty so the developer knows what is wrong.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <project name="platform/core" remote="{undeclared_remote}">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-001: expected non-empty ManifestParseError for undeclared "
            f"parent project remote='{undeclared_remote}' but got an empty string"
        )

    def test_copyfile_parent_project_inherits_default_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <copyfile> inside a <project> that inherits the default remote parses.

        When the parent project has no explicit remote, it inherits the <default>
        remote. The <copyfile> child is then processed correctly.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="upstream" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert project.remote is not None, (
            "AC-TEST-001: expected project.remote set via default remote inheritance but got None"
        )
        assert project.remote.name == "upstream", (
            f"AC-TEST-001: expected project.remote.name='upstream' via default "
            f"inheritance but got: {project.remote.name!r}"
        )
        assert len(project.copyfiles) == 1, (
            f"AC-TEST-001: expected <copyfile> to be parsed when parent inherits "
            f"default remote but got {len(project.copyfiles)} copyfiles"
        )

    def test_copyfile_remote_name_reflected_via_parent_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The parent project's remote name is accessible via the project model.

        The copyfile model itself does not store a remote; the remote is on the
        parent project. This test verifies that two projects each with a
        <copyfile> use their respective declared remotes.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="mirror" fetch="https://mirror.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            '  <project name="platform/lib" remote="mirror">\n'
            '    <copyfile src="README" dest="docs/README" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        projects = {p.name: p for p in manifest.projects}
        core = projects["platform/core"]
        lib = projects["platform/lib"]

        assert core.remote.name == "origin", (
            f"AC-TEST-001: expected platform/core remote='origin' (default) but got: {core.remote.name!r}"
        )
        assert len(core.copyfiles) == 1, (
            f"AC-TEST-001: expected 1 copyfile on platform/core but got: {len(core.copyfiles)}"
        )
        assert lib.remote.name == "mirror", (
            f"AC-TEST-001: expected platform/lib remote='mirror' (explicit) but got: {lib.remote.name!r}"
        )
        assert len(lib.copyfiles) == 1, (
            f"AC-TEST-001: expected 1 copyfile on platform/lib but got: {len(lib.copyfiles)}"
        )

    def test_copyfile_fetch_url_resolved_via_parent_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The parent project's remote fetchUrl reflects the declared remote fetch attribute.

        This confirms that the remote cross-reference resolves all the way through
        to the URL stored on the project model.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="partner" fetch="https://partner.example.com" />\n'
            '  <default revision="main" remote="partner" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert project.remote.fetchUrl == "https://partner.example.com", (
            f"AC-TEST-001: expected project.remote.fetchUrl='https://partner.example.com' "
            f"but got: {project.remote.fetchUrl!r}"
        )
        assert len(project.copyfiles) == 1, (
            f"AC-TEST-001: expected 1 copyfile after resolved remote cross-reference but got: {len(project.copyfiles)}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules for <copyfile>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCopyfileDuplicateElementRules:
    """AC-TEST-002: Duplicate-element rules for <copyfile> surface clear behavior.

    The manifest parser does not deduplicate <copyfile> elements. When two
    <copyfile> elements with identical src and dest appear in the same <project>,
    both are appended to the project's copyfiles list without raising an error.

    Two <copyfile> elements with the same dest but different srcs are also
    accepted -- there is no uniqueness constraint on dest alone or src alone.

    These are the parser's documented duplicate rules for <copyfile>: no
    deduplication, no error, silent accumulation.
    """

    def test_duplicate_copyfile_same_src_and_dest_both_accepted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two identical <copyfile src='...' dest='...'> in one <project> are both accepted.

        The parser appends both without raising ManifestParseError. The
        copyfiles list has two entries.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) == 2, (
            f"AC-TEST-002: expected 2 copyfile entries when the same src+dest appears "
            f"twice (no deduplication) but got: {len(project.copyfiles)}"
        )
        srcs = [cf.src for cf in project.copyfiles]
        dests = [cf.dest for cf in project.copyfiles]
        assert srcs.count("VERSION") == 2, (
            f"AC-TEST-002: expected src='VERSION' to appear twice in copyfiles but got: {srcs!r}"
        )
        assert dests.count("out/VERSION") == 2, (
            f"AC-TEST-002: expected dest='out/VERSION' to appear twice in copyfiles but got: {dests!r}"
        )

    def test_duplicate_copyfile_same_dest_different_src_both_accepted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <copyfile> elements sharing dest but different srcs are both accepted.

        No uniqueness constraint applies to dest alone. Both entries are
        appended to the project's copyfiles list.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/file.txt" />\n'
            '    <copyfile src="CHANGELOG" dest="out/file.txt" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) == 2, (
            f"AC-TEST-002: expected 2 copyfile entries when same dest but different "
            f"srcs but got: {len(project.copyfiles)}"
        )
        srcs = {cf.src for cf in project.copyfiles}
        assert "VERSION" in srcs, f"AC-TEST-002: expected 'VERSION' in copyfile srcs but got: {srcs!r}"
        assert "CHANGELOG" in srcs, f"AC-TEST-002: expected 'CHANGELOG' in copyfile srcs but got: {srcs!r}"

    def test_duplicate_copyfile_same_src_different_dest_both_accepted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <copyfile> elements sharing src but different dests are both accepted.

        No uniqueness constraint applies to src alone. Both entries are
        appended to the project's copyfiles list.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION-a" />\n'
            '    <copyfile src="VERSION" dest="out/VERSION-b" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) == 2, (
            f"AC-TEST-002: expected 2 copyfile entries when same src but different "
            f"dests but got: {len(project.copyfiles)}"
        )
        dests = {cf.dest for cf in project.copyfiles}
        assert "out/VERSION-a" in dests, f"AC-TEST-002: expected 'out/VERSION-a' in copyfile dests but got: {dests!r}"
        assert "out/VERSION-b" in dests, f"AC-TEST-002: expected 'out/VERSION-b' in copyfile dests but got: {dests!r}"

    @pytest.mark.parametrize(
        "count",
        [2, 3],
    )
    def test_many_duplicate_copyfiles_all_accepted(
        self,
        tmp_path: pathlib.Path,
        count: int,
    ) -> None:
        """Parameterized: multiple identical <copyfile> entries are all accepted silently.

        The parser appends each entry without checking for duplicates. The
        resulting copyfiles list contains exactly as many entries as were declared.

        AC-TEST-002
        """
        copyfile_lines = "\n".join('    <copyfile src="VERSION" dest="out/VERSION" />' for _ in range(count))
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            f"{copyfile_lines}\n"
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) == count, (
            f"AC-TEST-002: expected {count} copyfile entries (one per declaration) but got: {len(project.copyfiles)}"
        )

    def test_duplicate_copyfile_across_different_projects_is_valid(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The same src+dest pair in two different <project> elements is valid.

        Duplicate-element rules apply within a single project's copyfiles list.
        Across projects, any src+dest combination is legal.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            '  <project name="platform/lib" path="lib">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        projects = {p.name: p for p in manifest.projects}
        assert len(projects["platform/core"].copyfiles) == 1, (
            f"AC-TEST-002: expected 1 copyfile on platform/core but got: {len(projects['platform/core'].copyfiles)}"
        )
        assert len(projects["platform/lib"].copyfiles) == 1, (
            f"AC-TEST-002: expected 1 copyfile on platform/lib but got: {len(projects['platform/lib'].copyfiles)}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <copyfile> in an unexpected parent raises or is ignored
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCopyfileUnexpectedParent:
    """AC-TEST-003: <copyfile> in an unexpected parent raises or is ignored per spec.

    The parser processes <copyfile> only when it appears as a child of a
    <project> element. Behavior when the parent is unexpected:

    - A manifest file whose root element is not <manifest> raises
      ManifestParseError before any children (including any <project> or
      <copyfile>) are examined. The error message mentions 'manifest'.
    - A <copyfile> element placed directly as a child of the <manifest>
      root (not inside any <project>) is silently ignored by the
      _ParseManifest loop, which only dispatches known top-level elements
      (remote, default, project, etc.).
    """

    def test_copyfile_in_non_manifest_root_file_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A file whose root element is not <manifest> raises ManifestParseError.

        The parser rejects the file at root-element validation time; the
        <copyfile> child is never reached.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<repository>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</repository>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert "manifest" in error_message.lower(), (
            f"AC-TEST-003: expected 'manifest' in error message for non-manifest root but got: {error_message!r}"
        )

    @pytest.mark.parametrize(
        "non_manifest_root",
        [
            "repository",
            "config",
            "root",
            "repo",
        ],
    )
    def test_copyfile_under_various_non_manifest_roots_raises(
        self,
        tmp_path: pathlib.Path,
        non_manifest_root: str,
    ) -> None:
        """Parameterized: <copyfile> under any non-manifest root causes ManifestParseError.

        The error must be non-empty because the parser rejects the file at
        root-element validation before any <copyfile> is examined.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{non_manifest_root}>\n"
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            f"</{non_manifest_root}>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError) as exc_info:
            m.Load()

        error_message = str(exc_info.value)
        assert error_message, (
            f"AC-TEST-003: expected a non-empty error message when <copyfile> "
            f"appears under <{non_manifest_root}> but got an empty string"
        )

    def test_copyfile_at_manifest_root_level_is_silently_ignored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <copyfile> placed directly under <manifest> (not inside <project>) is ignored.

        The _ParseManifest loop dispatches on known top-level element names
        (remote, default, project, etc.). An unexpected <copyfile> at the root
        level is not a known top-level element and is silently skipped.

        The manifest loads without error, and no copyfiles appear on any project.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <copyfile src="VERSION" dest="out/VERSION" />\n'
            '  <project name="platform/core" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected <copyfile> at root level to be silently "
                f"ignored but got ManifestParseError: {exc!r}"
            )

        project = _get_project(manifest, "platform/core")
        assert project.copyfiles == [], (
            f"AC-TEST-003: expected no copyfiles on project when <copyfile> appears "
            f"at root level (not inside <project>) but got: {project.copyfiles!r}"
        )

    def test_copyfile_valid_in_project_parent_resolves_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <copyfile> inside a valid <project> registers correctly in the copyfiles list.

        This positive test confirms that when the parent IS a <project>,
        everything resolves normally.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="infra" fetch="https://infra.example.com" />\n'
            '  <default revision="refs/heads/main" remote="infra" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) == 1, (
            f"AC-TEST-003: expected 1 copyfile when <copyfile> is inside a valid "
            f"<project> but got: {len(project.copyfiles)}"
        )
        assert project.copyfiles[0].src == "VERSION", (
            f"AC-TEST-003: expected copyfile.src='VERSION' but got: {project.copyfiles[0].src!r}"
        )

    def test_unknown_sibling_at_manifest_root_does_not_interfere_with_copyfile(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An unknown element sibling to <project> inside <manifest> is silently ignored.

        Unknown elements in a valid <manifest> root are skipped by the parser
        loop. The <copyfile> inside the <project> sibling must still be
        processed and appear in the project's copyfiles list.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <unknown-element attr="ignored" />\n'
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected unknown sibling element to be silently "
                f"ignored but got ManifestParseError: {exc!r}"
            )

        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) == 1, (
            f"AC-TEST-003: expected 1 copyfile on project when unknown sibling is "
            f"present alongside <project> but got: {len(project.copyfiles)}"
        )
        assert project.copyfiles[0].src == "VERSION", (
            f"AC-TEST-003: expected copyfile.src='VERSION' after ignoring unknown "
            f"sibling but got: {project.copyfiles[0].src!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parser enforces cross-element and uniqueness rules at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCopyfileCrossRefParseTimeEnforcement:
    """AC-FUNC-001: All cross-element and uniqueness rules are enforced at parse time.

    Validation must occur during XmlManifest.Load(), not lazily on first use
    of manifest.projects or project.copyfiles. Tests confirm that errors fire
    during Load() and that the manifest state is consistent after a successful
    parse.
    """

    def test_undeclared_parent_remote_detected_at_parse_not_sync(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Undeclared parent remote is detected and raised during manifest load, not later.

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" remote="nonexistent">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_valid_crossref_produces_populated_copyfiles_at_parse_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Valid cross-element reference populates copyfiles during Load(), not later.

        After Load() returns, the copyfiles list must already be populated.
        No additional method call is needed to trigger parsing.

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) == 1, (
            f"AC-FUNC-001: expected copyfiles to be populated immediately after "
            f"Load() but got {len(project.copyfiles)} entries"
        )

    @pytest.mark.parametrize(
        "remote_name,fetch_url",
        [
            ("origin", "https://origin.example.com"),
            ("upstream", "https://upstream.example.com"),
            ("partner", "https://partner.example.com"),
        ],
    )
    def test_various_declared_remotes_allow_copyfile_parse(
        self,
        tmp_path: pathlib.Path,
        remote_name: str,
        fetch_url: str,
    ) -> None:
        """Parameterized: any valid declared remote on parent project allows <copyfile> to parse.

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
            f'  <default revision="main" remote="{remote_name}" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)
        project = _get_project(manifest, "platform/core")
        assert len(project.copyfiles) == 1, (
            f"AC-FUNC-001: expected 1 copyfile with remote='{remote_name}' but got: {len(project.copyfiles)}"
        )
        assert project.remote.fetchUrl == fetch_url, (
            f"AC-FUNC-001: expected remote.fetchUrl='{fetch_url}' but got: {project.remote.fetchUrl!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCopyfileCrossRefChannelDiscipline:
    """AC-CHANNEL-001: Parse errors must not write to stdout.

    Error information for invalid cross-element references must be conveyed
    exclusively through raised exceptions. Successful parses must not produce
    any stdout output.
    """

    def test_valid_crossref_produces_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Parsing a valid <copyfile> cross-element reference produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for valid crossref parse but got: {captured.out!r}"
        )

    def test_undeclared_parent_remote_raises_exception_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Undeclared parent remote raises ManifestParseError; no error written to stdout.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" remote="ghost">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when ManifestParseError is raised but got: {captured.out!r}"
        )

    def test_non_manifest_root_raises_exception_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Non-manifest root element raises ManifestParseError; no error written to stdout.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<repository>\n"
            '  <project name="platform/core">\n'
            '    <copyfile src="VERSION" dest="out/VERSION" />\n'
            "  </project>\n"
            "</repository>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = _write_manifest(repodir, xml_content)
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when non-manifest root raises "
            f"ManifestParseError but got: {captured.out!r}"
        )

    def test_copyfile_at_root_level_ignored_produces_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """A <copyfile> at manifest root level is silently ignored with no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <copyfile src="VERSION" dest="out/VERSION" />\n'
            '  <project name="platform/core" />\n'
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when <copyfile> at root is silently ignored but got: {captured.out!r}"
        )
