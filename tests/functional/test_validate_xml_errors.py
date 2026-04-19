"""Functional tests for `kanon validate xml` error surfacing.

Covers:
  AC-TEST-001 -- Well-formedness error (unclosed tag) is reported with file name and line
  AC-TEST-002 -- Missing required attribute produces actionable error
  AC-TEST-003 -- Broken include reference is reported
  AC-FUNC-001 -- Every ManifestParseError surfaces through validate xml with file:line context
  AC-CHANNEL-001 -- stdout vs stderr discipline is verified (no cross-channel leakage)
"""

import textwrap
from pathlib import Path

import pytest

from tests.functional.conftest import _run_kanon

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_xml(path: Path, content: str) -> Path:
    """Write an XML file, creating parent directories as needed.

    Args:
        path: Target file path.
        content: XML body written verbatim (no prolog added automatically).

    Returns:
        The path that was written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _make_repo(tmp_path: Path) -> Path:
    """Return a repo_root with a repo-specs/ subdirectory already created.

    Args:
        tmp_path: Base temp directory from pytest.

    Returns:
        The repo root directory.
    """
    repo_root = tmp_path / "repo"
    (repo_root / "repo-specs").mkdir(parents=True)
    return repo_root


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestValidateXmlErrorSurfacing:
    """Verify that parse errors are surfaced through `kanon validate xml`."""

    def test_unclosed_tag_reports_filename_and_line(self, tmp_path: Path) -> None:
        """AC-TEST-001 + AC-FUNC-001: unclosed tag error includes file name and line.

        The CLI must surface an XML parse error message that contains both the
        file name and a line reference. xml.etree.ElementTree.ParseError always
        includes "line N" in its string representation, and validate_manifest
        prefixes the filepath, so the full error contains both.

        AC-CHANNEL-001: the error summary ("Found N error(s)") and the parse
        error detail must appear on stderr; progress messages ("Validating ...")
        correctly appear on stdout.
        """
        repo_root = _make_repo(tmp_path)
        manifest = repo_root / "repo-specs" / "broken.xml"
        _write_xml(manifest, "<manifest><unclosed")

        result = _run_kanon("validate", "xml", "--repo-root", str(repo_root))

        assert result.returncode == 1, (
            f"Expected exit 1 for malformed XML.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        # AC-TEST-001 + AC-FUNC-001: error message in stderr must name the file and include a line reference.
        assert "broken.xml" in result.stderr, (
            f"AC-TEST-001: expected file name 'broken.xml' in stderr.\nstderr: {result.stderr!r}"
        )
        assert "line" in result.stderr, (
            f"AC-TEST-001 + AC-FUNC-001: expected line reference in stderr.\nstderr: {result.stderr!r}"
        )
        # AC-CHANNEL-001: the error summary must be on stderr, not on stdout.
        assert "error" in result.stderr.lower(), (
            f"AC-CHANNEL-001: expected error summary on stderr.\nstderr: {result.stderr!r}"
        )
        assert "error" not in result.stdout.lower(), (
            f"AC-CHANNEL-001: error summary must not appear on stdout.\nstdout: {result.stdout!r}"
        )

    def test_missing_required_attribute_produces_actionable_error(self, tmp_path: Path) -> None:
        """AC-TEST-002: missing required attribute produces an actionable error.

        The error message must name the attribute that is missing so the user
        knows exactly what to fix.

        AC-CHANNEL-001: the attribute error must appear on stderr; progress
        messages ("Validating ...") correctly appear on stdout.
        """
        repo_root = _make_repo(tmp_path)
        # A <project> element without 'path', 'remote', and 'revision' attributes.
        content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <remote name="origin" fetch="https://example.com" />
              <project name="proj" />
            </manifest>
        """)
        _write_xml(repo_root / "repo-specs" / "missing_attr.xml", content)

        result = _run_kanon("validate", "xml", "--repo-root", str(repo_root))

        assert result.returncode == 1, (
            f"Expected exit 1 for manifest with missing attributes.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        # AC-TEST-002: error message in stderr must name the file and the missing attribute.
        assert "missing_attr.xml" in result.stderr, (
            f"AC-TEST-002: expected file name in stderr.\nstderr: {result.stderr!r}"
        )
        # The error message must name at least one missing attribute
        assert "path" in result.stderr or "remote" in result.stderr or "revision" in result.stderr, (
            f"AC-TEST-002: expected a missing attribute name in stderr.\nstderr: {result.stderr!r}"
        )
        # AC-CHANNEL-001: the error summary must be on stderr, not on stdout.
        assert "error" in result.stderr.lower(), (
            f"AC-CHANNEL-001: expected error summary on stderr.\nstderr: {result.stderr!r}"
        )
        assert "error" not in result.stdout.lower(), (
            f"AC-CHANNEL-001: error summary must not appear on stdout.\nstdout: {result.stdout!r}"
        )

    def test_broken_include_reference_is_reported(self, tmp_path: Path) -> None:
        """AC-TEST-003: broken <include> reference is reported with file context.

        When a manifest includes a file that does not exist, the CLI must
        surface an error that names the referencing file and the missing target.
        """
        repo_root = _make_repo(tmp_path)
        content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <include name="nonexistent.xml" />
            </manifest>
        """)
        _write_xml(repo_root / "repo-specs" / "with_include.xml", content)

        result = _run_kanon("validate", "xml", "--repo-root", str(repo_root))

        assert result.returncode == 1, (
            f"Expected exit 1 for broken include reference.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        # AC-CHANNEL-001: error must appear on stderr
        assert "nonexistent.xml" in result.stderr, (
            f"AC-TEST-003: expected missing include name in stderr.\nstderr: {result.stderr!r}"
        )
        assert "with_include.xml" in result.stderr, (
            f"AC-TEST-003: expected referencing file name in stderr.\nstderr: {result.stderr!r}"
        )
        assert "nonexistent.xml" not in result.stdout, (
            f"AC-CHANNEL-001: error must not leak to stdout.\nstdout: {result.stdout!r}"
        )

    def test_valid_manifest_produces_no_stderr(self, tmp_path: Path) -> None:
        """AC-CHANNEL-001: a valid manifest produces output only on stdout.

        Verifies the inverse of the error-channel checks: success messages must
        not bleed onto stderr.
        """
        repo_root = _make_repo(tmp_path)
        content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <remote name="origin" fetch="https://example.com" />
              <project name="proj" path=".packages/proj" remote="origin" revision="main" />
            </manifest>
        """)
        _write_xml(repo_root / "repo-specs" / "valid.xml", content)

        result = _run_kanon("validate", "xml", "--repo-root", str(repo_root))

        assert result.returncode == 0, (
            f"Expected exit 0 for valid manifest.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert result.stderr == "", f"AC-CHANNEL-001: expected no stderr output on success.\nstderr: {result.stderr!r}"
        assert "valid" in result.stdout.lower(), (
            f"AC-CHANNEL-001: expected success message on stdout.\nstdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "missing_attr,xml_body",
        [
            (
                "path",
                '<manifest><remote name="o" fetch="u" /><project name="p" remote="o" revision="main" /></manifest>',
            ),
            (
                "remote",
                '<manifest><remote name="o" fetch="u" /><project name="p" path=".packages/p" revision="main" /></manifest>',
            ),
            (
                "revision",
                '<manifest><remote name="o" fetch="u" /><project name="p" path=".packages/p" remote="o" /></manifest>',
            ),
            (
                "fetch",
                '<manifest><remote name="o" /><project name="p" path=".packages/p" remote="o" revision="main" /></manifest>',
            ),
        ],
    )
    def test_each_missing_attribute_named_in_error(self, tmp_path: Path, missing_attr: str, xml_body: str) -> None:
        """AC-TEST-002 parametrized: each missing required attribute is named in the error.

        Args:
            tmp_path: Pytest temp directory.
            missing_attr: The attribute name expected to appear in the error.
            xml_body: The XML body missing that attribute.
        """
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "manifest.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body,
        )

        result = _run_kanon("validate", "xml", "--repo-root", str(repo_root))

        assert result.returncode == 1, (
            f"Expected exit 1 for missing '{missing_attr}'.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert missing_attr in result.stderr, (
            f"AC-TEST-002: expected attribute name '{missing_attr}' in stderr.\nstderr: {result.stderr!r}"
        )
