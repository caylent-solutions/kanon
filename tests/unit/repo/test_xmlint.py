"""Unit tests for the XmlInt utility function in manifest_xml.

Covers:
  AC-TEST-001  non-integer string raises ManifestParseError with "invalid" and attribute name
  AC-TEST-002  sync-j=0 and sync-j=-1 raise ManifestParseError with "must be greater than 0"
  AC-TEST-003  clone-depth=0 and clone-depth=-5 raise ManifestParseError with "must be greater than 0"

  AC-FUNC-001  Integer attributes enforce documented positivity constraints at parse time
  AC-CHANNEL-001  Errors are raised as exceptions; stdout is not polluted

All tests are marked @pytest.mark.unit.
AC-TEST-001 tests XmlInt directly using real xml.dom.minidom nodes.
AC-TEST-002 and AC-TEST-003 use real manifest files written to tmp_path -- no mocking.
"""

import pathlib
import xml.dom.minidom

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError
from kanon_cli.repo.manifest_xml import XmlInt


# ---------------------------------------------------------------------------
# Helpers for direct XmlInt tests (AC-TEST-001)
# ---------------------------------------------------------------------------


def _node(attr_value: str):
    """Return a real DOM element with ``attr`` set to *attr_value*.

    Args:
        attr_value: The string value to assign to the ``attr`` attribute.

    Returns:
        A DOM element node with the given attribute value.
    """
    doc = xml.dom.minidom.parseString(f'<item attr="{attr_value}"/>'.encode())
    return doc.documentElement


def _node_no_attr():
    """Return a real DOM element that has no ``attr`` attribute at all.

    Returns:
        A DOM element node with no attributes.
    """
    doc = xml.dom.minidom.parseString(b"<item/>")
    return doc.documentElement


# ---------------------------------------------------------------------------
# Helpers for full manifest parsing tests (AC-TEST-002, AC-TEST-003)
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
    """
    repodir = _make_repo_dir(tmp_path)
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


def _build_manifest_with_default(default_attrs: str = "") -> str:
    """Build a minimal manifest XML with one <remote> and one <default> element.

    Args:
        default_attrs: Attribute string placed on the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    default_elem = f"  <default {default_attrs} />\n" if default_attrs else "  <default />\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        f"{default_elem}"
        "</manifest>\n"
    )


def _build_manifest_with_project(extra_project_attrs: str = "") -> str:
    """Build a minimal valid manifest XML containing one <project> element.

    Args:
        extra_project_attrs: Additional attribute string appended to <project>.

    Returns:
        Full XML string for the manifest.
    """
    project_attrs = 'name="platform/core"'
    if extra_project_attrs:
        project_attrs = f"{project_attrs} {extra_project_attrs}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        '  <default revision="main" remote="origin" />\n'
        f"  <project {project_attrs} />\n"
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: non-integer string raises ManifestParseError with "invalid"
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_value",
    [
        "abc",
        "not_a_number",
        "1.5",
        "1e3",
        "  ",
        "none",
        "true",
        "null",
    ],
)
def test_xmlint_non_integer_string_raises_manifest_parse_error(bad_value):
    """AC-TEST-001: A non-integer string attribute raises ManifestParseError.

    XmlInt must raise ManifestParseError when the attribute value cannot be
    converted to a Python int. The error message must identify the attribute
    by name and include the word "invalid".
    """
    node = _node(bad_value)
    with pytest.raises(ManifestParseError) as exc_info:
        XmlInt(node, "attr")
    error_msg = str(exc_info.value)
    assert "invalid" in error_msg.lower(), (
        f"AC-TEST-001: expected 'invalid' in error message for {bad_value!r}, got: {error_msg!r}"
    )
    assert "attr" in error_msg, (
        f"AC-TEST-001: expected attribute name 'attr' in error message for {bad_value!r}, got: {error_msg!r}"
    )


@pytest.mark.unit
def test_xmlint_valid_positive_integer_returns_int():
    """AC-TEST-001: A valid positive integer string returns the integer value.

    XmlInt must parse a positive integer string and return it as a Python int.
    """
    node = _node("4")
    result = XmlInt(node, "attr")
    assert result == 4, f"AC-TEST-001: expected 4 but got {result!r}"
    assert isinstance(result, int), f"AC-TEST-001: expected int type but got {type(result)!r}"


@pytest.mark.unit
def test_xmlint_missing_attr_returns_default():
    """AC-TEST-001: A missing attribute returns the supplied default without raising.

    XmlInt returns the default when the attribute is absent from the node.
    """
    node = _node_no_attr()
    result = XmlInt(node, "attr", default=None)
    assert result is None, f"AC-TEST-001: expected None default for missing attr but got {result!r}"


@pytest.mark.unit
@pytest.mark.parametrize("default", [None, 0, 7])
def test_xmlint_empty_attr_returns_default(default):
    """AC-TEST-001: An empty attribute value returns the supplied default without raising.

    XmlInt treats an empty string as absent and returns the default value.
    """
    node = _node("")
    result = XmlInt(node, "attr", default=default)
    assert result == default, f"AC-TEST-001: expected default {default!r} for empty attr but got {result!r}"


# ---------------------------------------------------------------------------
# AC-TEST-002: sync-j=0 and sync-j=-1 raise must-be-greater-than-0
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "sync_j_value",
    [0, -1],
)
def test_sync_j_non_positive_raises_must_be_greater_than_0(tmp_path, sync_j_value):
    """AC-TEST-002: sync-j=0 and sync-j=-1 raise ManifestParseError with "must be greater than 0".

    The <default> element enforces sync-j > 0. Zero and negative values must
    be rejected at parse time. The error message must name "sync-j" and
    contain the constraint phrase.
    """
    xml_content = _build_manifest_with_default(default_attrs=f'sync-j="{sync_j_value}"')
    with pytest.raises(ManifestParseError) as exc_info:
        _write_and_load(tmp_path, xml_content)
    error_msg = str(exc_info.value)
    assert "sync-j" in error_msg, (
        f"AC-TEST-002: expected 'sync-j' in error message for sync-j={sync_j_value}, got: {error_msg!r}"
    )
    assert "greater than 0" in error_msg, (
        f"AC-TEST-002: expected 'greater than 0' in error message for sync-j={sync_j_value}, got: {error_msg!r}"
    )


@pytest.mark.unit
def test_sync_j_non_integer_string_raises_parse_error(tmp_path):
    """AC-TEST-002: A non-integer sync-j value raises ManifestParseError naming the attribute.

    XmlInt raises when sync-j cannot be parsed as an integer. The error
    message must include "sync-j".
    """
    xml_content = _build_manifest_with_default(default_attrs='sync-j="not_a_number"')
    with pytest.raises(ManifestParseError) as exc_info:
        _write_and_load(tmp_path, xml_content)
    assert "sync-j" in str(exc_info.value), (
        f"AC-TEST-002: expected 'sync-j' in error for non-integer sync-j, got: {str(exc_info.value)!r}"
    )


@pytest.mark.unit
def test_sync_j_positive_integer_parses_successfully(tmp_path):
    """AC-TEST-002: A valid positive sync-j parses without raising.

    A sync-j value of 1 or greater must be accepted and stored as an integer
    on the default object.
    """
    xml_content = _build_manifest_with_default(default_attrs='sync-j="4"')
    manifest = _write_and_load(tmp_path, xml_content)
    assert manifest.default.sync_j == 4, f"AC-TEST-002: expected default.sync_j=4 but got {manifest.default.sync_j!r}"


# ---------------------------------------------------------------------------
# AC-TEST-003: clone-depth=0 and clone-depth=-5 raise must-be-greater-than-0
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "clone_depth_value",
    [0, -5],
)
def test_clone_depth_non_positive_raises_must_be_greater_than_0(tmp_path, clone_depth_value):
    """AC-TEST-003: clone-depth=0 and clone-depth=-5 raise ManifestParseError with "must be greater than 0".

    The <project> element enforces clone-depth > 0. Zero and negative values
    must be rejected at parse time. The error message must name "clone-depth"
    and contain the constraint phrase.
    """
    xml_content = _build_manifest_with_project(extra_project_attrs=f'clone-depth="{clone_depth_value}"')
    with pytest.raises(ManifestParseError) as exc_info:
        _write_and_load(tmp_path, xml_content)
    error_msg = str(exc_info.value)
    assert "clone-depth" in error_msg, (
        f"AC-TEST-003: expected 'clone-depth' in error for clone-depth={clone_depth_value}, got: {error_msg!r}"
    )
    assert "greater than 0" in error_msg, (
        f"AC-TEST-003: expected 'greater than 0' in error for clone-depth={clone_depth_value}, got: {error_msg!r}"
    )


@pytest.mark.unit
def test_clone_depth_non_integer_raises_parse_error(tmp_path):
    """AC-TEST-003: A non-integer clone-depth value raises ManifestParseError naming the attribute.

    XmlInt raises when clone-depth cannot be parsed as an integer. The error
    message must include "clone-depth".
    """
    xml_content = _build_manifest_with_project(extra_project_attrs='clone-depth="not_a_number"')
    with pytest.raises(ManifestParseError) as exc_info:
        _write_and_load(tmp_path, xml_content)
    assert "clone-depth" in str(exc_info.value), (
        f"AC-TEST-003: expected 'clone-depth' in error for non-integer clone-depth, got: {str(exc_info.value)!r}"
    )


@pytest.mark.unit
def test_clone_depth_positive_integer_parses_successfully(tmp_path):
    """AC-TEST-003: A valid positive clone-depth parses without raising.

    A clone-depth value of 1 or greater must be accepted and stored on the
    parsed project object.
    """
    xml_content = _build_manifest_with_project(extra_project_attrs='clone-depth="10"')
    manifest = _write_and_load(tmp_path, xml_content)
    projects_by_name = {p.name: p for p in manifest.projects}
    project = projects_by_name["platform/core"]
    assert project.clone_depth == 10, f"AC-TEST-003: expected project.clone_depth=10 but got {project.clone_depth!r}"


# ---------------------------------------------------------------------------
# AC-FUNC-001: Integer attributes enforce documented positivity at parse time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestXmlIntConstraintsEnforcedAtParseTime:
    """AC-FUNC-001: Integer attributes enforce documented positivity at parse time.

    Validation must be triggered during m.Load(), not deferred to a later
    pipeline stage. Tests verify that calling m.Load() is sufficient to
    surface all integer constraint errors immediately.
    """

    def test_sync_j_zero_raises_at_load_time(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-001: ManifestParseError for sync-j=0 is raised during m.Load().

        Constructing XmlManifest must not itself parse the XML.
        The error must appear only when m.Load() is called.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-j="0"')
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_sync_j_negative_raises_at_load_time(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-001: ManifestParseError for sync-j=-1 is raised during m.Load().

        Negative sync-j must be rejected when m.Load() is called.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-j="-1"')
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_clone_depth_zero_raises_at_load_time(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-001: ManifestParseError for clone-depth=0 is raised during m.Load().

        The constraint clone-depth > 0 must be enforced during m.Load(),
        not deferred to a later operation.
        """
        xml_content = _build_manifest_with_project(extra_project_attrs='clone-depth="0"')
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_clone_depth_negative_raises_at_load_time(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-001: ManifestParseError for clone-depth=-5 is raised during m.Load().

        Negative clone-depth must be rejected when m.Load() is called.
        """
        xml_content = _build_manifest_with_project(extra_project_attrs='clone-depth="-5"')
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))

        with pytest.raises(ManifestParseError):
            m.Load()

    def test_valid_sync_j_and_clone_depth_observable_after_load(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-001: Valid sync-j and clone-depth values are stored after m.Load().

        After a successful m.Load() with valid integer attributes, the values
        must be accessible on the parsed manifest and project objects.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" sync-j="8" />\n'
            '  <project name="platform/core" clone-depth="5" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
        manifest_file.write_text(xml_content, encoding="utf-8")
        m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
        m.Load()

        assert m.default.sync_j == 8, f"AC-FUNC-001: expected default.sync_j=8 but got {m.default.sync_j!r}"
        projects_by_name = {p.name: p for p in m.projects}
        project = projects_by_name["platform/core"]
        assert project.clone_depth == 5, f"AC-FUNC-001: expected project.clone_depth=5 but got {project.clone_depth!r}"


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestXmlIntChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr discipline verified (no cross-channel leakage).

    Integer constraint errors must be surfaced as exceptions, never written
    to stdout. Tests verify that parse failures produce ManifestParseError
    and leave stdout empty.
    """

    def test_sync_j_zero_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: sync-j=0 raises ManifestParseError; stdout is empty.

        No diagnostic text from the parser must reach stdout when sync-j
        violates the > 0 constraint.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-j="0"')
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"AC-CHANNEL-001: expected no stdout for sync-j=0 but got: {captured.out!r}"

    def test_sync_j_negative_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: sync-j=-1 raises ManifestParseError; stdout is empty.

        No diagnostic text from the parser must reach stdout when sync-j
        is negative.
        """
        xml_content = _build_manifest_with_default(default_attrs='sync-j="-1"')
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"AC-CHANNEL-001: expected no stdout for sync-j=-1 but got: {captured.out!r}"

    def test_clone_depth_zero_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: clone-depth=0 raises ManifestParseError; stdout is empty.

        No diagnostic text from the parser must reach stdout when clone-depth
        violates the > 0 constraint.
        """
        xml_content = _build_manifest_with_project(extra_project_attrs='clone-depth="0"')
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"AC-CHANNEL-001: expected no stdout for clone-depth=0 but got: {captured.out!r}"

    def test_clone_depth_negative_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: clone-depth=-5 raises ManifestParseError; stdout is empty.

        No diagnostic text from the parser must reach stdout when clone-depth
        is negative.
        """
        xml_content = _build_manifest_with_project(extra_project_attrs='clone-depth="-5"')
        with pytest.raises(ManifestParseError):
            _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"AC-CHANNEL-001: expected no stdout for clone-depth=-5 but got: {captured.out!r}"

    def test_non_integer_xmlint_does_not_write_to_stdout(
        self,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: XmlInt raising ManifestParseError for non-integer does not write to stdout.

        No diagnostic output must appear on stdout when XmlInt raises due to
        a non-integer attribute value.
        """
        node = _node("not_a_number")
        with pytest.raises(ManifestParseError):
            XmlInt(node, "attr")
        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout for XmlInt non-integer error but got: {captured.out!r}"
        )

    def test_valid_integer_attributes_do_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: Valid integer attributes produce no stdout output.

        A successful parse of sync-j and clone-depth must not write any
        diagnostic content to stdout.
        """
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" sync-j="4" />\n'
            '  <project name="platform/core" clone-depth="3" />\n'
            "</manifest>\n"
        )
        _write_and_load(tmp_path, xml_content)
        captured = capsys.readouterr()
        assert not captured.out, f"AC-CHANNEL-001: expected no stdout for valid integer attrs but got: {captured.out!r}"
