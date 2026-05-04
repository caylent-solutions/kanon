"""Unit tests for the <annotation> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <annotation> XML elements parse correctly when given
minimum required attributes, all documented attributes, and that default
attribute values behave per docs.

The <annotation> element is a child of <project>, <remote>, or <submanifest>
elements. It carries structured metadata as name/value pairs.

Documented attributes:
  Required: name (annotation key)
  Required: value (annotation value)
  Optional: keep (boolean string "true" or "false"; default "true")

Documented behavior:
  - name and value are required; missing either raises ManifestParseError
  - keep defaults to "true" when absent
  - keep must be "true" or "false"; any other value raises ManifestParseError
  - Annotations are appended to the parent element's annotations list
  - Multiple <annotation> children are supported (one per name/value pair)

All tests use real manifest files written to tmp_path via shared helpers.
The conftest in tests/unit/repo/ auto-applies @pytest.mark.unit to every
item collected under that directory.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError
from kanon_cli.repo.project import Annotation


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern used in test_xml_notice_happy.py
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


def _build_manifest_with_annotated_project(
    annotation_attrs: str,
    project_name: str = "platform/tools",
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
) -> str:
    """Build a manifest XML string with a <project> containing an <annotation> child.

    Args:
        annotation_attrs: Raw attribute string for the <annotation> element (e.g. 'name="k" value="v"').
        project_name: The name attribute of the <project> element.
        remote_name: The name attribute of the <remote> element.
        fetch_url: The fetch attribute of the <remote> element.
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
        f"    <annotation {annotation_attrs} />\n"
        "  </project>\n"
        "</manifest>\n"
    )


def _build_manifest_with_annotated_remote(
    annotation_attrs: str,
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
) -> str:
    """Build a manifest XML string with a <remote> containing an <annotation> child.

    Args:
        annotation_attrs: Raw attribute string for the <annotation> element.
        remote_name: The name attribute of the <remote> element.
        fetch_url: The fetch attribute of the <remote> element.
        default_revision: The revision on the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}">\n'
        f"    <annotation {annotation_attrs} />\n"
        "  </remote>\n"
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        "</manifest>\n"
    )


def _get_project(manifest: manifest_xml.XmlManifest, project_name: str):
    """Return the first project from the manifest whose name matches project_name.

    Args:
        manifest: A loaded XmlManifest instance.
        project_name: The project name to look up.

    Returns:
        The matching Project object.

    Raises:
        AssertionError: If no project with that name is found.
    """
    projects = {p.name: p for p in manifest.projects}
    assert project_name in projects, (
        f"Expected project '{project_name}' in manifest but found: {list(projects.keys())!r}"
    )
    return projects[project_name]


def _get_remote(manifest: manifest_xml.XmlManifest, remote_name: str):
    """Return the remote from the manifest whose name matches remote_name.

    Args:
        manifest: A loaded XmlManifest instance.
        remote_name: The remote name to look up.

    Returns:
        The matching _XmlRemote object.

    Raises:
        AssertionError: If no remote with that name is found.
    """
    remotes = manifest.remotes
    assert remote_name in remotes, f"Expected remote '{remote_name}' in manifest but found: {list(remotes.keys())!r}"
    return remotes[remote_name]


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid <annotation> with minimum required attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnnotationMinimumRequired:
    """Verify that an <annotation> element with minimum required attributes parses correctly.

    The minimum required attributes are name and value. When keep is absent
    it defaults to "true".
    """

    def test_annotation_minimum_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with a project annotated using only name and value parses without error.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(annotation_attrs='name="team" value="platform-eng"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest is not None, "Expected XmlManifest instance but got None"

    def test_annotation_name_attribute_is_preserved(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing, annotation.name matches the name attribute in the XML.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(annotation_attrs='name="team" value="platform-eng"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        project = _get_project(manifest, "platform/tools")

        assert len(project.annotations) == 1, f"Expected 1 annotation on project but got: {len(project.annotations)}"
        assert project.annotations[0].name == "team", (
            f"Expected annotation.name='team' but got: {project.annotations[0].name!r}"
        )

    def test_annotation_value_attribute_is_preserved(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing, annotation.value matches the value attribute in the XML.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(annotation_attrs='name="team" value="platform-eng"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        project = _get_project(manifest, "platform/tools")

        assert len(project.annotations) == 1, f"Expected 1 annotation on project but got: {len(project.annotations)}"
        assert project.annotations[0].value == "platform-eng", (
            f"Expected annotation.value='platform-eng' but got: {project.annotations[0].value!r}"
        )

    def test_annotation_keep_defaults_to_true_when_absent(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When keep is absent, annotation.keep defaults to 'true'.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(annotation_attrs='name="owner" value="team-a"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        project = _get_project(manifest, "platform/tools")

        assert len(project.annotations) == 1, f"Expected 1 annotation on project but got: {len(project.annotations)}"
        assert project.annotations[0].keep == "true", (
            f"Expected annotation.keep='true' when absent but got: {project.annotations[0].keep!r}"
        )

    def test_annotation_result_is_annotation_instance(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsed annotation is an instance of the Annotation class.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(annotation_attrs='name="env" value="prod"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        project = _get_project(manifest, "platform/tools")

        assert len(project.annotations) == 1, f"Expected 1 annotation but got: {len(project.annotations)}"
        assert isinstance(project.annotations[0], Annotation), (
            f"Expected Annotation instance but got: {type(project.annotations[0])!r}"
        )

    @pytest.mark.parametrize(
        "ann_name,ann_value",
        [
            ("team", "platform-eng"),
            ("owner", "alice"),
            ("env", "staging"),
            ("priority", "high"),
        ],
    )
    def test_annotation_minimum_attributes_for_various_values(
        self,
        tmp_path: pathlib.Path,
        ann_name: str,
        ann_value: str,
    ) -> None:
        """Parameterized: various name/value pairs parse and are stored correctly.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(annotation_attrs=f'name="{ann_name}" value="{ann_value}"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        project = _get_project(manifest, "platform/tools")

        assert len(project.annotations) == 1, (
            f"Expected 1 annotation for name={ann_name!r} value={ann_value!r} but got: {len(project.annotations)}"
        )
        assert project.annotations[0].name == ann_name, (
            f"Expected annotation.name={ann_name!r} but got: {project.annotations[0].name!r}"
        )
        assert project.annotations[0].value == ann_value, (
            f"Expected annotation.value={ann_value!r} but got: {project.annotations[0].value!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <annotation> with all documented attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnnotationAllDocumentedAttributes:
    """Verify that an <annotation> element with all documented attributes parses correctly.

    The full documented attribute surface is: name, value, keep.
    """

    def test_annotation_with_keep_true_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <annotation> with keep='true' parses and stores keep='true'.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(annotation_attrs='name="tier" value="gold" keep="true"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        project = _get_project(manifest, "platform/tools")

        assert len(project.annotations) == 1, f"Expected 1 annotation but got: {len(project.annotations)}"
        assert project.annotations[0].keep == "true", (
            f"Expected annotation.keep='true' but got: {project.annotations[0].keep!r}"
        )

    def test_annotation_with_keep_false_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <annotation> with keep='false' parses and stores keep='false'.

        AC-TEST-002: keep='false' is explicitly supported by the parser.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(annotation_attrs='name="tier" value="bronze" keep="false"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        project = _get_project(manifest, "platform/tools")

        assert len(project.annotations) == 1, f"Expected 1 annotation but got: {len(project.annotations)}"
        assert project.annotations[0].keep == "false", (
            f"Expected annotation.keep='false' but got: {project.annotations[0].keep!r}"
        )

    def test_annotation_on_remote_element_parses(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <annotation> on a <remote> element parses with name, value, and keep.

        AC-TEST-002: annotations can be children of <remote> as well as <project>.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_remote(annotation_attrs='name="geo" value="us-east" keep="true"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        remote = _get_remote(manifest, "origin")

        assert len(remote.annotations) == 1, f"Expected 1 annotation on remote but got: {len(remote.annotations)}"
        assert remote.annotations[0].name == "geo", (
            f"Expected annotation.name='geo' but got: {remote.annotations[0].name!r}"
        )
        assert remote.annotations[0].value == "us-east", (
            f"Expected annotation.value='us-east' but got: {remote.annotations[0].value!r}"
        )
        assert remote.annotations[0].keep == "true", (
            f"Expected annotation.keep='true' but got: {remote.annotations[0].keep!r}"
        )

    def test_multiple_annotations_on_project_parse(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Multiple <annotation> children on a <project> all parse correctly.

        AC-TEST-002: a project may have more than one annotation child.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/tools">\n'
            '    <annotation name="team" value="platform-eng" keep="true" />\n'
            '    <annotation name="env" value="prod" keep="false" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        project = _get_project(manifest, "platform/tools")

        assert len(project.annotations) == 2, f"Expected 2 annotations on project but got: {len(project.annotations)}"
        names = {a.name for a in project.annotations}
        assert "team" in names, f"Expected 'team' in annotation names but got: {names!r}"
        assert "env" in names, f"Expected 'env' in annotation names but got: {names!r}"

    def test_annotation_keep_case_insensitive_stored_lowercase(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The keep attribute is lowercased before storage per _ParseAnnotation.

        AC-TEST-002: keep is stored as lowercase 'true' or 'false'.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(annotation_attrs='name="label" value="x" keep="TRUE"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        project = _get_project(manifest, "platform/tools")

        assert len(project.annotations) == 1, f"Expected 1 annotation but got: {len(project.annotations)}"
        assert project.annotations[0].keep == "true", (
            f"Expected annotation.keep='true' (lowercased) but got: {project.annotations[0].keep!r}"
        )

    @pytest.mark.parametrize(
        "keep_value,expected_keep",
        [
            ("true", "true"),
            ("false", "false"),
            ("TRUE", "true"),
            ("FALSE", "false"),
        ],
    )
    def test_annotation_keep_values_stored_lowercase(
        self,
        tmp_path: pathlib.Path,
        keep_value: str,
        expected_keep: str,
    ) -> None:
        """Parameterized: keep attribute values are normalized to lowercase.

        AC-TEST-002
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(annotation_attrs=f'name="k" value="v" keep="{keep_value}"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        project = _get_project(manifest, "platform/tools")

        assert len(project.annotations) == 1, (
            f"Expected 1 annotation for keep={keep_value!r} but got: {len(project.annotations)}"
        )
        assert project.annotations[0].keep == expected_keep, (
            f"Expected annotation.keep={expected_keep!r} for input {keep_value!r} "
            f"but got: {project.annotations[0].keep!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <annotation> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnnotationDefaultBehavior:
    """Verify that the default behavior of <annotation> is as documented.

    When no <annotation> children are present, project.annotations is an empty list.
    When a <annotation> is present with keep omitted, keep defaults to "true".
    """

    def test_no_annotation_gives_empty_list(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <annotation> child is present, project.annotations is an empty list.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/tools" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        project = _get_project(manifest, "platform/tools")

        assert project.annotations == [], (
            f"Expected project.annotations=[] when no annotation children but got: {project.annotations!r}"
        )

    def test_no_annotation_on_remote_gives_empty_list(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <annotation> child is present on a <remote>, remote.annotations is empty.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        remote = _get_remote(manifest, "origin")

        assert remote.annotations == [], (
            f"Expected remote.annotations=[] when no annotation children but got: {remote.annotations!r}"
        )

    def test_annotation_keep_absent_defaults_to_true(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When keep is absent, annotation.keep defaults to 'true' (documented default).

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(annotation_attrs='name="label" value="release"')
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        project = _get_project(manifest, "platform/tools")

        assert len(project.annotations) == 1, f"Expected 1 annotation but got: {len(project.annotations)}"
        assert project.annotations[0].keep == "true", (
            f"Expected annotation.keep default='true' but got: {project.annotations[0].keep!r}"
        )

    def test_invalid_keep_value_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An <annotation> with an invalid keep value raises ManifestParseError.

        AC-TEST-003: the parser enforces that keep must be 'true' or 'false'.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(annotation_attrs='name="label" value="x" keep="maybe"')
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert "keep" in str(exc_info.value).lower(), f"Expected 'keep' in error message but got: {exc_info.value!r}"

    def test_annotations_list_grows_per_child(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Each <annotation> child adds one entry to project.annotations.

        AC-TEST-003: the list accumulates one Annotation per child element.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="platform/tools">\n'
            '    <annotation name="a" value="1" />\n'
            '    <annotation name="b" value="2" />\n'
            '    <annotation name="c" value="3" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        project = _get_project(manifest, "platform/tools")

        assert len(project.annotations) == 3, f"Expected 3 annotations but got: {len(project.annotations)}"

    @pytest.mark.parametrize(
        "ann_name,ann_value,ann_keep",
        [
            ("team", "alpha", "true"),
            ("tier", "gold", "false"),
            ("region", "us-west", "true"),
        ],
    )
    def test_annotation_all_attributes_stored_correctly(
        self,
        tmp_path: pathlib.Path,
        ann_name: str,
        ann_value: str,
        ann_keep: str,
    ) -> None:
        """Parameterized: all three attributes of <annotation> are stored as parsed.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(
            annotation_attrs=f'name="{ann_name}" value="{ann_value}" keep="{ann_keep}"'
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)
        project = _get_project(manifest, "platform/tools")

        assert len(project.annotations) == 1, f"Expected 1 annotation but got: {len(project.annotations)}"
        ann = project.annotations[0]
        assert ann.name == ann_name, f"Expected name={ann_name!r} but got: {ann.name!r}"
        assert ann.value == ann_value, f"Expected value={ann_value!r} but got: {ann.value!r}"
        assert ann.keep == ann_keep, f"Expected keep={ann_keep!r} but got: {ann.keep!r}"


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnnotationChannelDiscipline:
    """Verify that parse errors raise exceptions rather than writing to stdout.

    The <annotation> parser must report errors exclusively through exceptions;
    it must not write error information to stdout.

    AC-CHANNEL-001 (parser tasks: no stdout leakage for success/failure paths)
    """

    def test_valid_annotation_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest with a valid <annotation> does not raise ManifestParseError.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(annotation_attrs='name="team" value="eng" keep="true"')
        manifest_file = _write_manifest(repodir, xml_content)

        try:
            _load_manifest(repodir, manifest_file)
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid <annotation> manifest to parse without ManifestParseError but got: {exc!r}")

    def test_invalid_keep_raises_manifest_parse_error_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Parsing an invalid keep value raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_manifest_with_annotated_project(annotation_attrs='name="label" value="x" keep="invalid"')
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"Expected no stdout output when ManifestParseError is raised but got: {captured.out!r}"
        )
        assert str(exc_info.value), "Expected a non-empty error message from ManifestParseError but got an empty string"
