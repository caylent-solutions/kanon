"""Integration tests for Unicode / encoding boundary handling.

Exercises UTF-8 support across .kanon parsing, version resolution, manifest
path handling, and XML project-name parsing.

AC-TEST-001: Unicode branch name in .kanon REVISION works
AC-TEST-002: Unicode tag revision resolves correctly
AC-TEST-003: Unicode path in manifest parses and installs
AC-TEST-004: Unicode project name in XML parses and installs
AC-FUNC-001: UTF-8 end-to-end throughout the CLI and parser
AC-CHANNEL-001: stdout vs stderr discipline
"""

import pathlib
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.core.kanonenv import parse_kanonenv
from kanon_cli.core.install import install
from kanon_cli.core.xml_validator import validate_manifest
from kanon_cli.version import resolve_version


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _write_kanonenv(directory: pathlib.Path, content: str) -> pathlib.Path:
    """Write a .kanon file with UTF-8 encoding and return its absolute path.

    Args:
        directory: Directory in which to place the .kanon file.
        content: File body text.

    Returns:
        Resolved absolute path to the .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(content, encoding="utf-8")
    return kanonenv.resolve()


def _minimal_kanonenv_with_revision(revision: str) -> str:
    """Return minimal .kanon content with the given revision string.

    Args:
        revision: REVISION value to embed.

    Returns:
        .kanon file body as a string.
    """
    return (
        f"KANON_SOURCE_s_URL=https://example.com/s.git\nKANON_SOURCE_s_REVISION={revision}\nKANON_SOURCE_s_PATH=m.xml\n"
    )


def _minimal_kanonenv_with_path(manifest_path: str) -> str:
    """Return minimal .kanon content with the given manifest path string.

    Args:
        manifest_path: PATH value to embed.

    Returns:
        .kanon file body as a string.
    """
    return (
        "KANON_SOURCE_s_URL=https://example.com/s.git\n"
        "KANON_SOURCE_s_REVISION=main\n"
        f"KANON_SOURCE_s_PATH={manifest_path}\n"
    )


def _write_xml_manifest(path: pathlib.Path, body: str) -> pathlib.Path:
    """Write an XML manifest file at path and return it.

    Args:
        path: Full target file path (parent dirs created as needed).
        body: XML content to write.

    Returns:
        Written file path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + body, encoding="utf-8")
    return path


def _install_patched(kanonenv: pathlib.Path) -> None:
    """Run install() with all external repo operations patched to no-ops.

    Args:
        kanonenv: Path to the .kanon configuration file.
    """
    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync"),
        patch("kanon_cli.core.install.resolve_version", side_effect=lambda url, rev: rev),
    ):
        install(kanonenv)


# ---------------------------------------------------------------------------
# AC-TEST-001: Unicode branch name in .kanon REVISION works
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUnicodeBranchRevision:
    """AC-TEST-001: Unicode branch names in KANON_SOURCE_*_REVISION are parsed correctly.

    The .kanon parser reads the file as UTF-8 and must preserve non-ASCII
    characters in REVISION values without corruption or error.
    """

    @pytest.mark.parametrize(
        "revision",
        [
            "feature/日本語-branch",
            "release/été-2024",
            "зарелиз-branch",
            "feature/中文分支",
        ],
    )
    def test_unicode_revision_parsed_unchanged(self, tmp_path: pathlib.Path, revision: str) -> None:
        """Unicode REVISION value is read back from parse_kanonenv unchanged.

        The UTF-8 encoded branch name must round-trip through the file
        parser with no loss or mangling.
        """
        kanonenv = _write_kanonenv(tmp_path, _minimal_kanonenv_with_revision(revision))
        result = parse_kanonenv(kanonenv)
        assert result["sources"]["s"]["revision"] == revision, (
            f"Expected revision {revision!r} but got {result['sources']['s']['revision']!r}"
        )

    def test_ascii_revision_unchanged(self, tmp_path: pathlib.Path) -> None:
        """Plain ASCII revision passes through parse_kanonenv unchanged.

        Baseline: pure-ASCII revision 'main' must be unaffected by
        the UTF-8 reading path.
        """
        kanonenv = _write_kanonenv(tmp_path, _minimal_kanonenv_with_revision("main"))
        result = parse_kanonenv(kanonenv)
        assert result["sources"]["s"]["revision"] == "main"

    def test_unicode_revision_install_passes_to_repo_init(self, tmp_path: pathlib.Path) -> None:
        """Unicode REVISION is forwarded as-is to repo_init during install.

        install() must not modify or transcode the revision value when
        calling the underlying repo init.
        """
        unicode_revision = "feature/日本語-branch"
        content = (
            "KANON_SOURCE_s_URL=https://example.com/s.git\n"
            f"KANON_SOURCE_s_REVISION={unicode_revision}\n"
            "KANON_SOURCE_s_PATH=m.xml\n"
        )
        kanonenv = _write_kanonenv(tmp_path, content)

        captured_revision: list[str] = []

        def fake_repo_init(repo_dir: str, url: str, revision: str, manifest_path: str, repo_rev: str = "") -> None:
            captured_revision.append(revision)

        with (
            patch("kanon_cli.repo.repo_init", side_effect=fake_repo_init),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch(
                "kanon_cli.core.install.resolve_version",
                side_effect=lambda url, rev: rev,
            ),
        ):
            install(kanonenv)

        assert len(captured_revision) == 1, "repo_init must be called exactly once"
        assert captured_revision[0] == unicode_revision, (
            f"Expected repo_init revision {unicode_revision!r} but got {captured_revision[0]!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Unicode tag revision resolves correctly
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUnicodeTagResolution:
    """AC-TEST-002: Unicode tag revision values pass through resolve_version correctly.

    Plain (non-constraint) revision strings that contain Unicode characters
    must be returned unchanged by resolve_version() since they are not PEP 440
    constraints.
    """

    @pytest.mark.parametrize(
        "revision",
        [
            "refs/tags/v1.ö.0",
            "refs/tags/release-中文",
            "ブランチ",
            "feature/été",
        ],
    )
    def test_unicode_plain_ref_passes_through_unchanged(self, revision: str) -> None:
        """A Unicode plain (non-constraint) ref is returned unchanged by resolve_version.

        resolve_version must not call git ls-remote for plain refs and must
        return the value unchanged regardless of Unicode content.
        """
        result = resolve_version("https://example.com/repo.git", revision)
        assert result == revision, f"Expected revision {revision!r} to pass through unchanged but got {result!r}"

    def test_unicode_revision_from_kanonenv_resolves_to_itself(self, tmp_path: pathlib.Path) -> None:
        """A Unicode REVISION in .kanon is parsed then resolved to itself.

        End-to-end: parse_kanonenv returns the Unicode revision, then
        resolve_version returns it unchanged (it is not a PEP 440 constraint).
        """
        revision = "release/日本語-v2"
        kanonenv = _write_kanonenv(tmp_path, _minimal_kanonenv_with_revision(revision))
        parsed = parse_kanonenv(kanonenv)
        parsed_revision = parsed["sources"]["s"]["revision"]
        resolved = resolve_version("https://example.com/repo.git", parsed_revision)
        assert resolved == revision, f"Expected resolved revision {revision!r} but got {resolved!r}"

    def test_unicode_tag_in_ls_remote_output_does_not_raise(self) -> None:
        """A Unicode-containing tag in ls-remote output is parsed without error.

        The _list_tags parser splits on tabs and must handle Unicode characters
        in tag names gracefully.
        """
        from kanon_cli.version import _list_tags

        unicode_tag = "refs/tags/vété-1.0.0"
        mock_result = MagicMock(
            returncode=0,
            stdout=f"abc123\t{unicode_tag}\n",
            stderr="",
        )
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            tags = _list_tags("https://example.com/repo.git")

        assert unicode_tag in tags, f"Unicode tag {unicode_tag!r} must appear in parsed ls-remote output"


# ---------------------------------------------------------------------------
# AC-TEST-003: Unicode path in manifest parses and installs
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUnicodeManifestPath:
    """AC-TEST-003: Unicode manifest PATH values in .kanon are parsed and used correctly.

    KANON_SOURCE_*_PATH may contain non-ASCII characters (e.g., accented
    directory separators in repo-specs paths). The parser must preserve these.
    """

    @pytest.mark.parametrize(
        "manifest_path",
        [
            "repo-specs/manifésto.xml",
            "要約/default.xml",
            "repo-specs/répertoire/manifest.xml",
        ],
    )
    def test_unicode_path_parsed_correctly(self, tmp_path: pathlib.Path, manifest_path: str) -> None:
        """Unicode PATH value is preserved verbatim after parse_kanonenv.

        The file must be read as UTF-8 and the PATH value must match
        the original string exactly.
        """
        kanonenv = _write_kanonenv(tmp_path, _minimal_kanonenv_with_path(manifest_path))
        result = parse_kanonenv(kanonenv)
        assert result["sources"]["s"]["path"] == manifest_path, (
            f"Expected path {manifest_path!r} but got {result['sources']['s']['path']!r}"
        )

    def test_unicode_path_forwarded_to_repo_init(self, tmp_path: pathlib.Path) -> None:
        """Unicode manifest PATH is forwarded unchanged to repo_init during install.

        install() must pass the Unicode path directly to repo init without
        encoding or transforming it.
        """
        manifest_path = "repo-specs/manifésto.xml"
        kanonenv = _write_kanonenv(tmp_path, _minimal_kanonenv_with_path(manifest_path))

        captured_path: list[str] = []

        def fake_repo_init(repo_dir: str, url: str, revision: str, manifest_path: str, repo_rev: str = "") -> None:
            captured_path.append(manifest_path)

        with (
            patch("kanon_cli.repo.repo_init", side_effect=fake_repo_init),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch(
                "kanon_cli.core.install.resolve_version",
                side_effect=lambda url, rev: rev,
            ),
        ):
            install(kanonenv)

        assert len(captured_path) == 1, "repo_init must be called exactly once"
        assert captured_path[0] == manifest_path, (
            f"Expected repo_init manifest_path {manifest_path!r} but got {captured_path[0]!r}"
        )

    def test_kanonenv_with_utf8_bom_parsed_correctly(self, tmp_path: pathlib.Path) -> None:
        """A .kanon file with UTF-8 BOM is parsed without error or BOM corruption.

        Python's 'utf-8-sig' codec (used by the parser) strips the BOM before
        parsing. The resulting value must match the original without the BOM byte.
        """
        content = (
            "KANON_SOURCE_s_URL=https://example.com/s.git\nKANON_SOURCE_s_REVISION=main\nKANON_SOURCE_s_PATH=m.xml\n"
        )
        kanonenv = tmp_path / ".kanon"
        # Write with explicit BOM prefix (UTF-8 BOM = 0xEF, 0xBB, 0xBF)
        kanonenv.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
        result = parse_kanonenv(kanonenv.resolve())
        assert result["sources"]["s"]["path"] == "m.xml", (
            "BOM-prefixed .kanon file must be parsed without BOM corruption"
        )
        assert result["sources"]["s"]["revision"] == "main"


# ---------------------------------------------------------------------------
# AC-TEST-004: Unicode project name in XML parses and installs
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUnicodeXmlProjectName:
    """AC-TEST-004: XML manifests with Unicode project name attributes are validated.

    The xml_validator must parse UTF-8 encoded manifests with non-ASCII
    characters in <project name="..."> attributes without error, and must
    correctly validate that the required attributes are present.
    """

    @pytest.mark.parametrize(
        "project_name",
        [
            "日本語プロジェクト",
            "projet-été",
            "проект",
            "proiect-î",
        ],
    )
    def test_unicode_project_name_passes_validation(self, tmp_path: pathlib.Path, project_name: str) -> None:
        """An XML manifest with a Unicode project name passes validate_manifest.

        validate_manifest must parse the UTF-8 file, extract the project
        name attribute, and report no errors since all required attributes
        are present.
        """
        manifest_xml = textwrap.dedent(f"""\
            <manifest>
              <remote name="origin" fetch="https://example.com" />
              <project name="{project_name}" path=".packages/proj"
                       remote="origin" revision="main" />
            </manifest>
        """)
        manifest_file = _write_xml_manifest(tmp_path / "repo-specs" / "manifest.xml", manifest_xml)
        errors = validate_manifest(manifest_file, tmp_path)
        assert errors == [], f"Unicode project name {project_name!r} must not cause validation errors; got: {errors}"

    def test_unicode_project_name_attribute_is_non_empty_string(self, tmp_path: pathlib.Path) -> None:
        """A Unicode project name is treated as a non-empty string by validate_manifest.

        The presence check `if not project.get(attr)` must not evaluate a
        non-empty Unicode string as falsy.
        """
        project_name = "日本語"
        manifest_xml = textwrap.dedent(f"""\
            <manifest>
              <remote name="origin" fetch="https://example.com" />
              <project name="{project_name}" path=".packages/p"
                       remote="origin" revision="main" />
            </manifest>
        """)
        manifest_file = _write_xml_manifest(tmp_path / "repo-specs" / "manifest.xml", manifest_xml)
        errors = validate_manifest(manifest_file, tmp_path)
        # The name attribute is present and non-empty; no "missing attribute" error.
        missing_name_errors = [e for e in errors if "'name'" in e and "missing" in e]
        assert missing_name_errors == [], (
            f"Unicode project name must not be treated as missing; got: {missing_name_errors}"
        )

    def test_manifest_utf8_encoding_declaration_accepted(self, tmp_path: pathlib.Path) -> None:
        """An XML file with an explicit UTF-8 encoding declaration is parsed without error.

        Python's xml.etree.ElementTree handles UTF-8 encoding declarations in
        the XML prolog. The validator must not reject such files.
        """
        manifest_xml = textwrap.dedent("""\
            <manifest>
              <remote name="origin" fetch="https://example.com" />
              <project name="été-project" path=".packages/p"
                       remote="origin" revision="main" />
            </manifest>
        """)
        manifest_file = _write_xml_manifest(tmp_path / "repo-specs" / "manifest.xml", manifest_xml)
        errors = validate_manifest(manifest_file, tmp_path)
        assert errors == [], (
            f"Manifest with UTF-8 encoding declaration and Unicode name must pass validation; got: {errors}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: UTF-8 end-to-end throughout the CLI and parser
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUtf8EndToEnd:
    """AC-FUNC-001: UTF-8 values flow correctly end-to-end through the kanon pipeline.

    Verifies that Unicode values set in .kanon propagate intact through
    parse_kanonenv -> install -> repo_init without any transcoding or loss.
    """

    def test_unicode_url_revision_path_all_preserved(self, tmp_path: pathlib.Path) -> None:
        """Unicode values in URL, REVISION, and PATH are all preserved by the parser.

        Each field must round-trip through parse_kanonenv exactly.
        """
        url = "https://example.com/repo-日本.git"
        revision = "feature/été"
        path = "specs/要約.xml"
        content = f"KANON_SOURCE_s_URL={url}\nKANON_SOURCE_s_REVISION={revision}\nKANON_SOURCE_s_PATH={path}\n"
        kanonenv = _write_kanonenv(tmp_path, content)
        result = parse_kanonenv(kanonenv)

        assert result["sources"]["s"]["url"] == url, (
            f"Unicode URL {url!r} must be preserved; got {result['sources']['s']['url']!r}"
        )
        assert result["sources"]["s"]["revision"] == revision, (
            f"Unicode REVISION {revision!r} must be preserved; got {result['sources']['s']['revision']!r}"
        )
        assert result["sources"]["s"]["path"] == path, (
            f"Unicode PATH {path!r} must be preserved; got {result['sources']['s']['path']!r}"
        )

    def test_unicode_global_var_preserved(self, tmp_path: pathlib.Path) -> None:
        """A Unicode global variable value in .kanon is preserved by parse_kanonenv.

        Non-KANON_SOURCE variables (globals) must also survive UTF-8 decoding.
        """
        unicode_value = "https://日本.example.com/git/"
        content = (
            f"GITBASE={unicode_value}\n"
            "KANON_SOURCE_s_URL=https://example.com/s.git\n"
            "KANON_SOURCE_s_REVISION=main\n"
            "KANON_SOURCE_s_PATH=m.xml\n"
        )
        kanonenv = _write_kanonenv(tmp_path, content)
        result = parse_kanonenv(kanonenv)
        assert result["globals"]["GITBASE"] == unicode_value, (
            f"Unicode global GITBASE {unicode_value!r} must be preserved; got {result['globals'].get('GITBASE')!r}"
        )

    def test_multi_source_unicode_names_sorted_alphabetically(self, tmp_path: pathlib.Path) -> None:
        """Multiple sources with Unicode names are discovered and sorted correctly.

        Source names are the ASCII portion (KANON_SOURCE_<name>_URL). If names
        are ASCII the sorting is straightforward. This test uses two ASCII source
        names to confirm the ordering contract holds when the VALUE contains Unicode.
        """
        content = (
            "KANON_SOURCE_alpha_URL=https://日本.example.com/a.git\n"
            "KANON_SOURCE_alpha_REVISION=feature/été\n"
            "KANON_SOURCE_alpha_PATH=specs/要約-alpha.xml\n"
            "KANON_SOURCE_bravo_URL=https://example.com/b.git\n"
            "KANON_SOURCE_bravo_REVISION=main\n"
            "KANON_SOURCE_bravo_PATH=m.xml\n"
        )
        kanonenv = _write_kanonenv(tmp_path, content)
        result = parse_kanonenv(kanonenv)
        assert result["KANON_SOURCES"] == ["alpha", "bravo"], (
            f"Sources must be sorted alphabetically; got {result['KANON_SOURCES']!r}"
        )
        assert result["sources"]["alpha"]["revision"] == "feature/été"


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestChannelDiscipline:
    """AC-CHANNEL-001: install() writes progress to stdout only; errors go to stderr.

    No progress or informational output must bleed into stderr, and error
    messages must not appear on stdout.
    """

    def test_successful_install_writes_nothing_to_stderr(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A successful install with a Unicode revision emits nothing to stderr.

        All progress lines ('kanon install: ...') belong on stdout only.
        """
        content = (
            "KANON_SOURCE_s_URL=https://example.com/s.git\n"
            "KANON_SOURCE_s_REVISION=feature/日本語\n"
            "KANON_SOURCE_s_PATH=m.xml\n"
        )
        kanonenv = _write_kanonenv(tmp_path, content)
        _install_patched(kanonenv)

        captured = capsys.readouterr()
        assert captured.err == "", f"No output must appear on stderr during a successful install; got: {captured.err!r}"

    def test_successful_install_writes_progress_to_stdout(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A successful install with a Unicode revision writes progress to stdout.

        The 'kanon install: done.' marker must appear on stdout.
        """
        content = (
            "KANON_SOURCE_s_URL=https://example.com/s.git\n"
            "KANON_SOURCE_s_REVISION=feature/日本語\n"
            "KANON_SOURCE_s_PATH=m.xml\n"
        )
        kanonenv = _write_kanonenv(tmp_path, content)
        _install_patched(kanonenv)

        captured = capsys.readouterr()
        assert "kanon install: done." in captured.out, (
            f"'kanon install: done.' must appear on stdout; got stdout={captured.out!r}"
        )
