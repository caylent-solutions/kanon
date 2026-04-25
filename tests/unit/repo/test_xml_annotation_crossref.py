"""Unit tests for <annotation> cross-element and duplicate-element rules.

Covers:
  AC-TEST-001  Cross-element references involving <annotation> are validated
               (remote name resolution -- an <annotation> lives inside a parent
               element whose remote attribute must reference a declared <remote>
               element; an undeclared remote on the parent project raises
               ManifestParseError; when the parent project uses the default
               remote, <annotation> is parsed correctly; for <remote> parents,
               the annotation is processed only when the remote itself is valid)
  AC-TEST-002  Duplicate-element rules for <annotation> surface clear behavior
               (two <annotation> elements with the same name and same value in
               the same <project> are accepted silently -- the parser does not
               deduplicate; two <annotation> elements with the same name but
               different values are accepted; two <annotation> elements with
               different names are accepted; the same name/value pair in
               different parent elements is valid)
  AC-TEST-003  <annotation> in an unexpected parent raises or is ignored per
               spec (a manifest file whose root element is not <manifest>
               raises ManifestParseError before any children are examined;
               an <annotation> element placed directly under <manifest> as a
               top-level child -- not inside any <project>, <remote>, or
               <submanifest> -- is silently ignored by the parser loop)

  AC-FUNC-001  The parser enforces all cross-element and uniqueness rules
               documented for <annotation> at parse time (during
               XmlManifest.Load())
  AC-CHANNEL-001  stdout vs stderr discipline is verified (errors raise
                  ManifestParseError, not stdout writes; valid parses produce
                  no stdout output)

All tests are marked @pytest.mark.unit via the conftest auto-marker.
Tests use real manifest files written to tmp_path -- no mocking of
parser internals.

Cross-element rules for <annotation>:
- <annotation> is a child element of <project>, <remote>, or <submanifest>.
- When <annotation> is a child of <project>, the parent <project> must have
  a resolvable remote (explicit remote attribute referencing a declared
  <remote>, or a <default> remote). An unresolvable parent project raises
  ManifestParseError before <annotation> is processed.
- When <annotation> is a child of <remote>, it is processed as part of the
  <remote> parse; an invalid remote definition raises ManifestParseError
  before any annotation children are reached.
- Duplicate <annotation> elements (identical name and value) inside the same
  parent are accepted by the parser; all entries appear in the annotations
  list (no deduplication).
- An <annotation> element placed at the <manifest> root level (outside any
  parent) is silently ignored -- the parser loop in _ParseManifest does not
  handle 'annotation' node names at that level.
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
# AC-TEST-001: Cross-element reference validation for <annotation>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnnotationCrossElementReferences:
    """AC-TEST-001: Cross-element references involving <annotation> are validated.

    An <annotation> element lives inside a <project>, <remote>, or <submanifest>
    parent. The cross-element reference is the parent element's remote attribute,
    which must resolve to a declared <remote> element. When the parent project
    references an undeclared remote, ManifestParseError is raised before the
    <annotation> child is processed.

    When the parent element's remote resolves correctly, the <annotation> is
    parsed and the annotations list on the parent is populated.
    """

    def test_annotation_parent_project_with_declared_remote_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <annotation> inside a <project remote="..."> naming a declared remote parses.

        The parent project's remote resolves correctly, so the <annotation>
        is processed and appears in the project's annotations list.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" remote="origin">\n'
            '    <annotation name="team" value="platform-eng" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert len(project.annotations) == 1, (
            f"AC-TEST-001: expected 1 annotation when parent project's remote resolves "
            f"but got: {len(project.annotations)}"
        )
        assert project.annotations[0].name == "team", (
            f"AC-TEST-001: expected annotation.name='team' but got: {project.annotations[0].name!r}"
        )

    def test_annotation_parent_project_with_undeclared_remote_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <annotation> inside a <project> with an undeclared remote raises ManifestParseError.

        The parent project's remote cannot be resolved, so ManifestParseError
        is raised before the <annotation> child is processed.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core" remote="ghost-remote">\n'
            '    <annotation name="team" value="eng" />\n'
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
    def test_annotation_parent_project_various_undeclared_remotes_raise(
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
            '    <annotation name="k" value="v" />\n'
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

    def test_annotation_parent_project_inherits_default_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <annotation> inside a <project> that inherits the default remote parses.

        When the parent project has no explicit remote, it inherits the <default>
        remote. The <annotation> child is then processed correctly.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="upstream" fetch="https://upstream.example.com" />\n'
            '  <default revision="main" remote="upstream" />\n'
            '  <project name="platform/core">\n'
            '    <annotation name="region" value="us-west" />\n'
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
        assert len(project.annotations) == 1, (
            f"AC-TEST-001: expected <annotation> to be parsed when parent inherits "
            f"default remote but got {len(project.annotations)} annotations"
        )

    def test_annotation_remote_name_reflected_via_parent_project(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The parent project's remote name is accessible via the project model.

        The annotation model itself does not store a remote; the remote is on the
        parent project. This test verifies that two projects each with an
        <annotation> use their respective declared remotes.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://origin.example.com" />\n'
            '  <remote name="mirror" fetch="https://mirror.example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <annotation name="tier" value="gold" />\n'
            "  </project>\n"
            '  <project name="platform/lib" path="lib" remote="mirror">\n'
            '    <annotation name="tier" value="silver" />\n'
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
        assert len(core.annotations) == 1, (
            f"AC-TEST-001: expected 1 annotation on platform/core but got: {len(core.annotations)}"
        )
        assert lib.remote.name == "mirror", (
            f"AC-TEST-001: expected platform/lib remote='mirror' (explicit) but got: {lib.remote.name!r}"
        )
        assert len(lib.annotations) == 1, (
            f"AC-TEST-001: expected 1 annotation on platform/lib but got: {len(lib.annotations)}"
        )

    def test_annotation_on_remote_element_is_parsed_with_valid_remote(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <annotation> inside a valid <remote> element is parsed correctly.

        When the <remote> itself is valid (has name and fetch), the <annotation>
        child is processed and stored in remote.annotations.

        AC-TEST-001, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com">\n'
            '    <annotation name="geo" value="us-east" />\n'
            "  </remote>\n"
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        assert "origin" in manifest.remotes, (
            f"AC-TEST-001: expected 'origin' in manifest.remotes but got: {list(manifest.remotes.keys())!r}"
        )
        remote = manifest.remotes["origin"]
        assert len(remote.annotations) == 1, (
            f"AC-TEST-001: expected 1 annotation on remote 'origin' but got: {len(remote.annotations)}"
        )
        assert remote.annotations[0].name == "geo", (
            f"AC-TEST-001: expected annotation.name='geo' on remote but got: {remote.annotations[0].name!r}"
        )

    def test_annotation_on_remote_with_missing_fetch_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <annotation> inside a <remote> missing its required fetch attribute raises.

        The remote parse fails before processing any <annotation> children.

        AC-TEST-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin">\n'
            '    <annotation name="geo" value="us-east" />\n'
            "  </remote>\n"
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError) as exc_info:
            _write_and_load(tmp_path, xml_content)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-001: expected a non-empty ManifestParseError when remote is missing fetch but got an empty string"
        )

    def test_annotation_fetch_url_resolved_via_parent_remote(
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
            '    <annotation name="env" value="prod" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert project.remote.fetchUrl == "https://partner.example.com", (
            f"AC-TEST-001: expected project.remote.fetchUrl='https://partner.example.com' "
            f"but got: {project.remote.fetchUrl!r}"
        )
        assert len(project.annotations) == 1, (
            f"AC-TEST-001: expected 1 annotation after resolved remote cross-reference but got: "
            f"{len(project.annotations)}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Duplicate-element rules for <annotation>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnnotationDuplicateElementRules:
    """AC-TEST-002: Duplicate-element rules for <annotation> surface clear behavior.

    The manifest parser does not deduplicate <annotation> elements. When two
    <annotation> elements with identical name and value appear in the same parent
    element, both are appended to the annotations list without raising an error.

    Two <annotation> elements with the same name but different values are also
    accepted -- there is no uniqueness constraint on name alone or value alone.

    These are the parser's documented duplicate rules for <annotation>: no
    deduplication, no error, silent accumulation.
    """

    def test_duplicate_annotation_same_name_and_value_both_accepted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two identical <annotation name='...' value='...'> in one <project> are both accepted.

        The parser appends both without raising ManifestParseError. The
        annotations list has two entries.

        AC-TEST-002, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <annotation name="team" value="platform-eng" />\n'
            '    <annotation name="team" value="platform-eng" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert len(project.annotations) == 2, (
            f"AC-TEST-002: expected 2 annotation entries when the same name+value appears "
            f"twice (no deduplication) but got: {len(project.annotations)}"
        )
        names = [a.name for a in project.annotations]
        values = [a.value for a in project.annotations]
        assert names.count("team") == 2, (
            f"AC-TEST-002: expected name='team' to appear twice in annotations but got: {names!r}"
        )
        assert values.count("platform-eng") == 2, (
            f"AC-TEST-002: expected value='platform-eng' to appear twice in annotations but got: {values!r}"
        )

    def test_duplicate_annotation_same_name_different_value_both_accepted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <annotation> elements sharing name but different values are both accepted.

        No uniqueness constraint applies to name alone. Both entries are
        appended to the parent element's annotations list.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <annotation name="env" value="staging" />\n'
            '    <annotation name="env" value="prod" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert len(project.annotations) == 2, (
            f"AC-TEST-002: expected 2 annotation entries when same name but different "
            f"values but got: {len(project.annotations)}"
        )
        values = {a.value for a in project.annotations}
        assert "staging" in values, f"AC-TEST-002: expected 'staging' in annotation values but got: {values!r}"
        assert "prod" in values, f"AC-TEST-002: expected 'prod' in annotation values but got: {values!r}"

    def test_duplicate_annotation_different_name_same_value_both_accepted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two <annotation> elements with different names but same value are both accepted.

        No uniqueness constraint applies to value alone. Both entries are
        appended to the parent element's annotations list.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <annotation name="owner" value="team-a" />\n'
            '    <annotation name="tech-lead" value="team-a" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert len(project.annotations) == 2, (
            f"AC-TEST-002: expected 2 annotation entries when different names but "
            f"same value but got: {len(project.annotations)}"
        )
        ann_names = {a.name for a in project.annotations}
        assert "owner" in ann_names, f"AC-TEST-002: expected 'owner' in annotation names but got: {ann_names!r}"
        assert "tech-lead" in ann_names, f"AC-TEST-002: expected 'tech-lead' in annotation names but got: {ann_names!r}"

    @pytest.mark.parametrize(
        "count",
        [2, 3],
    )
    def test_many_duplicate_annotations_all_accepted(
        self,
        tmp_path: pathlib.Path,
        count: int,
    ) -> None:
        """Parameterized: multiple identical <annotation> entries are all accepted silently.

        The parser appends each entry without checking for duplicates. The
        resulting annotations list contains exactly as many entries as were declared.

        AC-TEST-002
        """
        annotation_lines = "\n".join('    <annotation name="label" value="release" />' for _ in range(count))
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            f"{annotation_lines}\n"
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert len(project.annotations) == count, (
            f"AC-TEST-002: expected {count} annotation entries (one per declaration) "
            f"but got: {len(project.annotations)}"
        )

    def test_duplicate_annotation_across_different_projects_is_valid(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The same name+value pair in two different <project> elements is valid.

        Duplicate-element rules apply within a single parent element's annotations
        list. Across projects, any name+value combination is legal.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <annotation name="team" value="platform-eng" />\n'
            "  </project>\n"
            '  <project name="platform/lib" path="lib">\n'
            '    <annotation name="team" value="platform-eng" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        projects = {p.name: p for p in manifest.projects}
        assert len(projects["platform/core"].annotations) == 1, (
            f"AC-TEST-002: expected 1 annotation on platform/core but got: {len(projects['platform/core'].annotations)}"
        )
        assert len(projects["platform/lib"].annotations) == 1, (
            f"AC-TEST-002: expected 1 annotation on platform/lib but got: {len(projects['platform/lib'].annotations)}"
        )

    def test_duplicate_annotation_same_name_value_on_remote_both_accepted(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two identical <annotation> children on the same <remote> are both accepted.

        The parser does not deduplicate annotations on <remote> elements either.

        AC-TEST-002
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com">\n'
            '    <annotation name="geo" value="us-east" />\n'
            '    <annotation name="geo" value="us-east" />\n'
            "  </remote>\n"
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        remote = manifest.remotes["origin"]
        assert len(remote.annotations) == 2, (
            f"AC-TEST-002: expected 2 annotation entries on remote when the same "
            f"name+value appears twice but got: {len(remote.annotations)}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <annotation> in an unexpected parent raises or is ignored
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnnotationUnexpectedParent:
    """AC-TEST-003: <annotation> in an unexpected parent raises or is ignored per spec.

    The parser processes <annotation> only when it appears as a child of
    a <project>, <remote>, or <submanifest> element. Behavior when the parent
    is unexpected:

    - A manifest file whose root element is not <manifest> raises
      ManifestParseError before any children (including any <project> or
      <annotation>) are examined. The error message mentions 'manifest'.
    - An <annotation> element placed directly as a child of the <manifest>
      root (not inside any <project>, <remote>, or <submanifest>) is silently
      ignored by the _ParseManifest loop, which only dispatches known top-level
      elements (remote, default, project, etc.).
    """

    def test_annotation_in_non_manifest_root_file_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A file whose root element is not <manifest> raises ManifestParseError.

        The parser rejects the file at root-element validation time; the
        <annotation> child is never reached.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<repository>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <project name="platform/core">\n'
            '    <annotation name="team" value="eng" />\n'
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
    def test_annotation_under_various_non_manifest_roots_raises(
        self,
        tmp_path: pathlib.Path,
        non_manifest_root: str,
    ) -> None:
        """Parameterized: <annotation> under any non-manifest root causes ManifestParseError.

        The error must be non-empty because the parser rejects the file at
        root-element validation before any <annotation> is examined.

        AC-TEST-003
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<{non_manifest_root}>\n"
            '  <project name="platform/core">\n'
            '    <annotation name="team" value="eng" />\n'
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
            f"AC-TEST-003: expected a non-empty error message when <annotation> "
            f"appears under <{non_manifest_root}> but got an empty string"
        )

    def test_annotation_at_manifest_root_level_is_silently_ignored(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <annotation> placed directly under <manifest> (not inside a parent) is ignored.

        The _ParseManifest loop dispatches on known top-level element names
        (remote, default, project, etc.). An <annotation> at the root level is
        not a known top-level element and is silently skipped.

        The manifest loads without error, and no annotations appear on any project.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <annotation name="global-key" value="some-value" />\n'
            '  <project name="platform/core" />\n'
            "</manifest>\n"
        )
        try:
            manifest = _write_and_load(tmp_path, xml_content)
        except ManifestParseError as exc:
            pytest.fail(
                f"AC-TEST-003: expected <annotation> at root level to be silently "
                f"ignored but got ManifestParseError: {exc!r}"
            )

        project = _get_project(manifest, "platform/core")
        assert project.annotations == [], (
            f"AC-TEST-003: expected no annotations on project when <annotation> appears "
            f"at root level (not inside parent element) but got: {project.annotations!r}"
        )

    def test_annotation_valid_in_project_parent_resolves_correctly(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <annotation> inside a valid <project> registers correctly in the annotations list.

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
            '    <annotation name="tier" value="gold" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert len(project.annotations) == 1, (
            f"AC-TEST-003: expected 1 annotation when <annotation> is inside a valid "
            f"<project> but got: {len(project.annotations)}"
        )
        assert project.annotations[0].name == "tier", (
            f"AC-TEST-003: expected annotation.name='tier' but got: {project.annotations[0].name!r}"
        )

    def test_unknown_sibling_at_manifest_root_does_not_interfere_with_annotation(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An unknown element sibling to <project> inside <manifest> is silently ignored.

        Unknown elements in a valid <manifest> root are skipped by the parser
        loop. The <annotation> inside the <project> sibling must still be
        processed and appear in the project's annotations list.

        AC-TEST-003, AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <unknown-element attr="ignored" />\n'
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <annotation name="team" value="eng" />\n'
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
        assert len(project.annotations) == 1, (
            f"AC-TEST-003: expected 1 annotation on project when unknown sibling is "
            f"present alongside <project> but got: {len(project.annotations)}"
        )
        assert project.annotations[0].name == "team", (
            f"AC-TEST-003: expected annotation.name='team' after ignoring unknown "
            f"sibling but got: {project.annotations[0].name!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Parser enforces cross-element and uniqueness rules at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnnotationCrossRefParseTimeEnforcement:
    """AC-FUNC-001: All cross-element and uniqueness rules are enforced at parse time.

    Validation must occur during XmlManifest.Load(), not lazily on first use
    of manifest.projects or project.annotations. Tests confirm that errors fire
    during Load() and that the manifest state is consistent after a successful
    parse.
    """

    def test_undeclared_parent_remote_detected_at_parse_not_later(
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
            '    <annotation name="team" value="eng" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)

    def test_valid_crossref_produces_populated_annotations_at_parse_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Valid cross-element reference populates annotations during Load(), not later.

        After Load() returns, the annotations list must already be populated.
        No additional method call is needed to trigger parsing.

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <annotation name="team" value="platform-eng" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        project = _get_project(manifest, "platform/core")
        assert len(project.annotations) == 1, (
            f"AC-FUNC-001: expected annotations to be populated immediately after "
            f"Load() but got {len(project.annotations)} entries"
        )

    @pytest.mark.parametrize(
        "remote_name,fetch_url",
        [
            ("origin", "https://origin.example.com"),
            ("upstream", "https://upstream.example.com"),
            ("partner", "https://partner.example.com"),
        ],
    )
    def test_various_declared_remotes_allow_annotation_parse(
        self,
        tmp_path: pathlib.Path,
        remote_name: str,
        fetch_url: str,
    ) -> None:
        """Parameterized: any valid declared remote on parent project allows <annotation> to parse.

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
            f'  <default revision="main" remote="{remote_name}" />\n'
            '  <project name="platform/core">\n'
            '    <annotation name="k" value="v" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)
        project = _get_project(manifest, "platform/core")
        assert len(project.annotations) == 1, (
            f"AC-FUNC-001: expected 1 annotation with remote='{remote_name}' but got: {len(project.annotations)}"
        )
        assert project.remote.fetchUrl == fetch_url, (
            f"AC-FUNC-001: expected remote.fetchUrl='{fetch_url}' but got: {project.remote.fetchUrl!r}"
        )

    def test_annotation_on_remote_populated_at_parse_time(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <annotation> on a <remote> is populated in remote.annotations at parse time.

        AC-FUNC-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com">\n'
            '    <annotation name="provider" value="self-hosted" />\n'
            "  </remote>\n"
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest = _write_and_load(tmp_path, xml_content)

        remote = manifest.remotes["origin"]
        assert len(remote.annotations) == 1, (
            f"AC-FUNC-001: expected remote.annotations to be populated immediately "
            f"after Load() but got {len(remote.annotations)} entries"
        )
        assert remote.annotations[0].name == "provider", (
            f"AC-FUNC-001: expected annotation.name='provider' but got: {remote.annotations[0].name!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnnotationCrossRefChannelDiscipline:
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
        """Parsing a valid <annotation> cross-element reference produces no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <annotation name="team" value="eng" />\n'
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
            '    <annotation name="team" value="eng" />\n'
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
            '    <annotation name="team" value="eng" />\n'
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

    def test_annotation_at_root_level_ignored_produces_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """An <annotation> at manifest root level is silently ignored with no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <annotation name="global-key" value="v" />\n'
            '  <project name="platform/core" />\n'
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout when <annotation> at root is silently "
            f"ignored but got: {captured.out!r}"
        )

    def test_duplicate_annotations_accepted_silently_no_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Duplicate <annotation> elements are accepted silently with no stdout output.

        AC-CHANNEL-001
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/core">\n'
            '    <annotation name="team" value="eng" />\n'
            '    <annotation name="team" value="eng" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for duplicate annotation parse but got: {captured.out!r}"
        )
