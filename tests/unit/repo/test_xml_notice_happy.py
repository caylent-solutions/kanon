"""Unit tests for the <notice> element happy path.

Covers AC-TEST-001, AC-TEST-002, AC-TEST-003, and AC-FUNC-001.

Tests verify that valid <notice> XML elements parse correctly when given
minimum required content, all documented content forms, and that default
behavior (no element present) is as documented.

The <notice> element is distinct from other manifest elements: it conveys
its data as text content between opening and closing tags rather than as
attributes. It is used to display informational messages to the user.

Documented behavior:
  - Text content between tags is the notice message
  - Leading and trailing blank lines are stripped
  - Indentation is normalized using a PEP-257-style algorithm
  - A duplicate <notice> element raises ManifestParseError
  - When absent, manifest.notice is None

All tests use real manifest files written to tmp_path via shared helpers.
The conftest in tests/unit/repo/ auto-applies @pytest.mark.unit to every
item collected under that directory.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared setup helpers -- mirrors the pattern used in test_xml_manifest_happy.py
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


def _build_notice_manifest(
    notice_text: str,
    remote_name: str = "origin",
    fetch_url: str = "https://example.com",
    default_revision: str = "main",
) -> str:
    """Build manifest XML that includes a <notice> element with the given text.

    Args:
        notice_text: The text content to embed inside the <notice> tags.
        remote_name: Name of the remote to define.
        fetch_url: Fetch URL for the remote.
        default_revision: The revision for the <default> element.

    Returns:
        Full XML string for the manifest.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f"  <notice>{notice_text}</notice>\n"
        f'  <remote name="{remote_name}" fetch="{fetch_url}" />\n'
        f'  <default revision="{default_revision}" remote="{remote_name}" />\n'
        "</manifest>\n"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid <notice> with minimum required content parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoticeMinimumRequired:
    """Verify that a <notice> element with minimum content parses correctly.

    The <notice> element has no required attributes. Its entire content is the
    text node between the opening and closing tags. The minimum form is a single
    non-empty line of text.
    """

    def test_notice_minimum_parses_without_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with a single-line <notice> parses without raising an error.

        AC-TEST-001, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_notice_manifest(notice_text="This is a notice.")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest is not None, "Expected XmlManifest instance but got None"

    def test_notice_is_set_after_parse(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """After parsing a manifest with <notice>, manifest.notice is not None.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_notice_manifest(notice_text="This is a notice.")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.notice is not None, "Expected manifest.notice to be set after parsing <notice> but got None"

    def test_notice_is_a_string(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """manifest.notice is a str after parsing a <notice> element.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_notice_manifest(notice_text="This is a notice.")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert isinstance(manifest.notice, str), (
            f"Expected manifest.notice to be a str but got: {type(manifest.notice)!r}"
        )

    def test_notice_single_line_content_preserved(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A single-line notice text is preserved in manifest.notice after parse.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_notice_manifest(notice_text="Single line notice text")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.notice == "Single line notice text", (
            f"Expected notice='Single line notice text' but got: {manifest.notice!r}"
        )

    @pytest.mark.parametrize(
        "notice_text",
        [
            "Simple notice",
            "Notice with numbers 12345",
            "Notice with special chars: @#$%",
            "Notice-with-hyphens and underscores_here",
        ],
    )
    def test_notice_single_line_parses_for_various_texts(
        self,
        tmp_path: pathlib.Path,
        notice_text: str,
    ) -> None:
        """Parameterized: various single-line notice texts parse and are stored.

        AC-TEST-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_notice_manifest(notice_text=notice_text)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.notice is not None, (
            f"Expected manifest.notice to be set for notice_text={notice_text!r} but got None"
        )
        assert manifest.notice == notice_text, f"Expected notice={notice_text!r} but got: {manifest.notice!r}"


# ---------------------------------------------------------------------------
# AC-TEST-002: Valid <notice> with all documented attributes parses correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoticeAllDocumentedAttributes:
    """Verify that a <notice> element with its full documented content surface parses correctly.

    The <notice> element has no XML attributes. Its entire content is conveyed
    as text between the tags. Multi-line content, leading/trailing blank lines,
    and indentation are all normalized per the PEP-257-style algorithm.
    """

    def test_notice_multiline_content_parsed(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A <notice> with multi-line text content parses without error.

        AC-TEST-002, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice>\n"
            "    First line of notice.\n"
            "    Second line of notice.\n"
            "  </notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.notice is not None, "Expected manifest.notice to be set but got None"
        assert isinstance(manifest.notice, str), (
            f"Expected manifest.notice to be a str but got: {type(manifest.notice)!r}"
        )
        assert "First line of notice." in manifest.notice, (
            f"Expected 'First line of notice.' in manifest.notice but got: {manifest.notice!r}"
        )
        assert "Second line of notice." in manifest.notice, (
            f"Expected 'Second line of notice.' in manifest.notice but got: {manifest.notice!r}"
        )

    def test_notice_leading_trailing_blank_lines_stripped(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Leading and trailing blank lines in <notice> text are stripped after parsing.

        AC-TEST-002: the PEP-257-style algorithm removes leading/trailing blank lines.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice>\n"
            "\n"
            "    Actual notice content here.\n"
            "\n"
            "  </notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.notice is not None, "Expected manifest.notice to be set but got None"
        assert not manifest.notice.startswith("\n"), (
            f"Expected no leading newline in manifest.notice but got: {manifest.notice!r}"
        )
        assert not manifest.notice.endswith("\n"), (
            f"Expected no trailing newline in manifest.notice but got: {manifest.notice!r}"
        )
        assert "Actual notice content here." in manifest.notice, (
            f"Expected 'Actual notice content here.' in manifest.notice but got: {manifest.notice!r}"
        )

    def test_notice_indentation_normalized(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Common leading indentation is stripped from <notice> text lines.

        AC-TEST-002: the PEP-257-style algorithm strips minimum indentation from all
        non-first lines.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice>\n"
            "    Line one.\n"
            "    Line two.\n"
            "  </notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.notice is not None, "Expected manifest.notice to be set but got None"
        lines = manifest.notice.splitlines()
        for line in lines:
            assert not line.startswith("    "), (
                f"Expected indentation to be normalized but line still has 4-space indent: {line!r}"
            )

    def test_notice_duplicate_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest with two <notice> elements raises ManifestParseError.

        AC-TEST-002: the parser enforces that <notice> appears at most once.
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice>First notice.</notice>\n"
            "  <notice>Second notice.</notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        assert "duplicate notice" in str(exc_info.value).lower(), (
            f"Expected 'duplicate notice' in error message but got: {exc_info.value!r}"
        )

    @pytest.mark.parametrize(
        "notice_lines,expected_fragment",
        [
            (["Line A.", "Line B."], "Line A."),
            (["First.", "Second.", "Third."], "Second."),
            (["Single."], "Single."),
        ],
    )
    def test_notice_multiline_content_for_various_inputs(
        self,
        tmp_path: pathlib.Path,
        notice_lines: list,
        expected_fragment: str,
    ) -> None:
        """Parameterized: various multi-line notice texts parse and contain expected content.

        AC-TEST-002
        """
        indented_text = "\n" + "".join(f"    {line}\n" for line in notice_lines) + "  "
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f"  <notice>{indented_text}</notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.notice is not None, (
            f"Expected manifest.notice to be set for lines={notice_lines!r} but got None"
        )
        assert expected_fragment in manifest.notice, (
            f"Expected fragment {expected_fragment!r} in manifest.notice but got: {manifest.notice!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: <notice> with default attribute values behaves per docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoticeDefaultBehavior:
    """Verify that the default behavior of <notice> is as documented.

    When no <notice> element is present, manifest.notice is None. When a
    <notice> element is present, manifest.notice is a non-empty string.
    """

    def test_notice_absent_is_none(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When no <notice> element is present, manifest.notice is None.

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

        assert manifest.notice is None, (
            f"Expected manifest.notice to be None when <notice> is absent but got: {manifest.notice!r}"
        )

    def test_notice_present_is_nonempty_string(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When a <notice> element is present with content, manifest.notice is non-empty.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_notice_manifest(notice_text="Important notice here")
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.notice is not None, (
            "Expected manifest.notice to be a non-empty str when <notice> is present but got None"
        )
        assert manifest.notice, "Expected manifest.notice to be non-empty but got an empty string"

    def test_notice_reset_on_reload(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """When a manifest with <notice> is loaded, notice is set; a separate manifest without it has None.

        AC-TEST-003: verifies that notice state is per-manifest, not global.
        """
        path_with = tmp_path / "with_notice"
        path_with.mkdir()
        repodir_with = _make_repo_dir(path_with)
        xml_with = _build_notice_manifest(notice_text="Has a notice")
        manifest_file_with = _write_manifest(repodir_with, xml_with)
        manifest_with = _load_manifest(repodir_with, manifest_file_with)

        path_without = tmp_path / "no_notice"
        path_without.mkdir()
        repodir_without = _make_repo_dir(path_without)
        xml_without = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            "</manifest>\n"
        )
        manifest_file_without = _write_manifest(repodir_without, xml_without)
        manifest_without = _load_manifest(repodir_without, manifest_file_without)

        assert manifest_with.notice is not None, "Expected manifest_with.notice to be set but got None"
        assert manifest_without.notice is None, (
            f"Expected manifest_without.notice to be None but got: {manifest_without.notice!r}"
        )

    @pytest.mark.parametrize(
        "notice_text",
        [
            "Short notice",
            "Multi-word notice with details",
            "Notice: please read the contributing guide",
        ],
    )
    def test_notice_various_single_line_values_are_non_none(
        self,
        tmp_path: pathlib.Path,
        notice_text: str,
    ) -> None:
        """Parameterized: various notice texts all result in a non-None manifest.notice.

        AC-TEST-003
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_notice_manifest(notice_text=notice_text)
        manifest_file = _write_manifest(repodir, xml_content)
        manifest = _load_manifest(repodir, manifest_file)

        assert manifest.notice is not None, (
            f"Expected manifest.notice to be non-None for text={notice_text!r} but got None"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoticeChannelDiscipline:
    """Verify that parse errors raise exceptions rather than writing to stdout.

    The <notice> parser must report errors exclusively through exceptions;
    it must not write error information to stdout.

    AC-CHANNEL-001 (parser tasks: no stdout leakage for success/failure paths)
    """

    def test_valid_notice_does_not_raise(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Parsing a manifest with a valid <notice> does not raise ManifestParseError.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = _build_notice_manifest(notice_text="This is a valid notice.")
        manifest_file = _write_manifest(repodir, xml_content)

        try:
            _load_manifest(repodir, manifest_file)
        except ManifestParseError as exc:
            pytest.fail(f"Expected valid <notice> manifest to parse without ManifestParseError but got: {exc!r}")

    def test_duplicate_notice_raises_manifest_parse_error_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys,
    ) -> None:
        """Parsing a duplicate <notice> raises ManifestParseError; stdout is empty.

        AC-CHANNEL-001
        """
        repodir = _make_repo_dir(tmp_path)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <notice>First notice.</notice>\n"
            "  <notice>Second notice.</notice>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
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
