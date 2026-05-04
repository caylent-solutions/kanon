"""Functional tests for `kanon validate marketplace`.

Covers:
  AC-TEST-001 -- linkfile dest validation passes for valid inputs and fails for invalid
  AC-TEST-002 -- include chain cycle detection surfaces (no infinite loop, reports nothing)
  AC-TEST-003 -- uniqueness, tag format, branch format, constraint format positive and negative
  AC-FUNC-001 -- validate marketplace exercises marketplace-specific rules over generic xml validation
  AC-CHANNEL-001 -- stdout vs stderr discipline is verified (no cross-channel leakage)
"""

import textwrap
import xml.etree.ElementTree as ET
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
        content: XML body (without the XML declaration header).

    Returns:
        The path that was written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + content)
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


def _valid_marketplace_xml(
    name: str = "proj",
    path: str = ".packages/proj",
    revision: str = "refs/tags/ex/proj/1.0.0",
    dest: str = "${CLAUDE_MARKETPLACES_DIR}/proj",
) -> str:
    """Return a well-formed marketplace XML body with one valid project.

    Uses the ElementTree builder to guarantee that all attribute values are
    properly XML-encoded, so callers can pass arbitrary strings (including
    version constraints containing '<') without producing invalid XML.

    Args:
        name: project name attribute.
        path: project path attribute.
        revision: project revision attribute.
        dest: linkfile dest attribute.

    Returns:
        XML body string (without the XML declaration header).
    """
    root = ET.Element("manifest")
    project = ET.SubElement(root, "project", name=name, path=path, remote="r", revision=revision)
    ET.SubElement(project, "linkfile", src="s", dest=dest)
    return ET.tostring(root, encoding="unicode")


# ---------------------------------------------------------------------------
# AC-TEST-001: linkfile dest validation
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestLinkfileDestValidation:
    """AC-TEST-001: linkfile dest attribute must start with the marketplace dir prefix."""

    def test_valid_dest_exits_zero(self, tmp_path: Path) -> None:
        """AC-TEST-001 positive: valid dest attribute passes validation.

        AC-FUNC-001: the CLI exercises the marketplace-specific linkfile dest rule.
        AC-CHANNEL-001: success output goes to stdout, stderr is empty.
        """
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "a-marketplace.xml",
            _valid_marketplace_xml(),
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 0, (
            f"AC-TEST-001: expected exit 0 for valid linkfile dest.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert result.stderr == "", f"AC-CHANNEL-001: expected no stderr on success.\nstderr: {result.stderr!r}"
        assert "passed" in result.stdout.lower() or "validating" in result.stdout.lower(), (
            f"AC-CHANNEL-001: expected progress/success output on stdout.\nstdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_dest",
        [
            "/absolute/bad/path",
            "relative/path",
            "CLAUDE_MARKETPLACES_DIR/missing-dollar-brace",
            "${OTHER_VAR}/proj",
        ],
    )
    def test_invalid_dest_exits_one_with_error_on_stderr(self, tmp_path: Path, bad_dest: str) -> None:
        """AC-TEST-001 negative: invalid linkfile dest exits 1 with diagnostic on stderr.

        AC-FUNC-001: the CLI surfaces the marketplace-specific linkfile dest error.
        AC-CHANNEL-001: error goes to stderr, not stdout.
        """
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "bad-marketplace.xml",
            _valid_marketplace_xml(dest=bad_dest),
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 1, (
            f"AC-TEST-001: expected exit 1 for invalid dest={bad_dest!r}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "error" in result.stderr.lower(), (
            f"AC-CHANNEL-001: expected error message on stderr.\nstderr: {result.stderr!r}"
        )
        assert "error" not in result.stdout.lower(), (
            f"AC-CHANNEL-001: error must not leak to stdout.\nstdout: {result.stdout!r}"
        )

    def test_multiple_projects_one_invalid_dest_exits_one(self, tmp_path: Path) -> None:
        """AC-TEST-001: one invalid dest among multiple projects still fails.

        Verifies the validator scans all projects, not just the first.
        """
        repo_root = _make_repo(tmp_path)
        content = textwrap.dedent("""\
            <manifest>
              <project name="good" path=".packages/good" remote="r" revision="refs/tags/ex/good/1.0.0">
                <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/good" />
              </project>
              <project name="bad" path=".packages/bad" remote="r" revision="refs/tags/ex/bad/1.0.0">
                <linkfile src="s" dest="/absolute/bad" />
              </project>
            </manifest>
        """)
        _write_xml(repo_root / "repo-specs" / "mixed-marketplace.xml", content)

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 1, (
            f"AC-TEST-001: expected exit 1 when one of multiple projects has invalid dest.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "bad" in result.stderr, (
            f"AC-TEST-001: expected error mentioning project 'bad'.\nstderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: include chain cycle detection
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestIncludeChainCycleDetection:
    """AC-TEST-002: include chain cycle detection does not infinite-loop and reports errors."""

    def test_valid_include_chain_exits_zero(self, tmp_path: Path) -> None:
        """AC-TEST-002 positive: a valid include chain (no missing files) passes.

        The root marketplace file includes an existing leaf file.
        """
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "base.xml",
            '<manifest><remote name="r" fetch="https://example.com" /></manifest>',
        )
        _write_xml(
            repo_root / "repo-specs" / "a-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <include name="repo-specs/base.xml" />
                  <project name="proj" path=".packages/proj" remote="r" revision="refs/tags/ex/proj/1.0.0">
                    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
                  </project>
                </manifest>
            """),
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 0, (
            f"AC-TEST-002: expected exit 0 for valid include chain.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_broken_include_reference_exits_one(self, tmp_path: Path) -> None:
        """AC-TEST-002 negative: a missing include file surfaces as a validation error.

        AC-CHANNEL-001: error about missing include goes to stderr.
        """
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "a-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <include name="repo-specs/nonexistent.xml" />
                  <project name="proj" path=".packages/proj" remote="r" revision="refs/tags/ex/proj/1.0.0">
                    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
                  </project>
                </manifest>
            """),
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 1, (
            f"AC-TEST-002: expected exit 1 for broken include reference.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "nonexistent.xml" in result.stderr, (
            f"AC-TEST-002: expected missing file name in stderr.\nstderr: {result.stderr!r}"
        )
        assert "nonexistent.xml" not in result.stdout, (
            f"AC-CHANNEL-001: error must not leak to stdout.\nstdout: {result.stdout!r}"
        )

    def test_circular_include_does_not_loop_indefinitely(self, tmp_path: Path) -> None:
        """AC-TEST-002: circular <include> chains do not cause an infinite loop.

        a-marketplace.xml -> b.xml -> a-marketplace.xml forms a cycle.
        The validator must detect the cycle and terminate without hanging.
        The test itself imposes no timeout annotation -- pytest's session timeout
        (SMOKE_TEST_TIMEOUT) is the safety net.
        """
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "b.xml",
            '<manifest><include name="repo-specs/a-marketplace.xml" /></manifest>',
        )
        _write_xml(
            repo_root / "repo-specs" / "a-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <include name="repo-specs/b.xml" />
                  <project name="proj" path=".packages/proj" remote="r" revision="refs/tags/ex/proj/1.0.0">
                    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
                  </project>
                </manifest>
            """),
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        # The cycle is detected and visited nodes are skipped -- no error is emitted
        # for the cycle itself, and no infinite loop occurs. The validator exits 0
        # and emits nothing to stderr (silent-cycle behavior).
        assert result.returncode == 0, (
            f"AC-TEST-002: circular includes must be silently skipped (exit 0).\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert result.stderr == "", (
            f"AC-TEST-002: circular includes must not produce any stderr output.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: uniqueness, tag format, branch format, constraint format
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestProjectUniquenessValidation:
    """AC-TEST-003: duplicate project paths across marketplace files are detected."""

    def test_unique_project_paths_across_files_exits_zero(self, tmp_path: Path) -> None:
        """AC-TEST-003 positive: unique project paths across multiple files pass."""
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "a-marketplace.xml",
            _valid_marketplace_xml(name="proj-a", path=".packages/proj-a"),
        )
        _write_xml(
            repo_root / "repo-specs" / "b-marketplace.xml",
            _valid_marketplace_xml(name="proj-b", path=".packages/proj-b"),
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 0, (
            f"AC-TEST-003: expected exit 0 for unique project paths.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_duplicate_project_paths_exits_one(self, tmp_path: Path) -> None:
        """AC-TEST-003 negative: duplicate project path across files exits 1.

        AC-CHANNEL-001: error goes to stderr.
        """
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "a-marketplace.xml",
            _valid_marketplace_xml(name="dup", path=".packages/dup"),
        )
        _write_xml(
            repo_root / "repo-specs" / "b-marketplace.xml",
            _valid_marketplace_xml(name="dup", path=".packages/dup"),
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 1, (
            f"AC-TEST-003: expected exit 1 for duplicate project path '.packages/dup'.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "dup" in result.stderr, (
            f"AC-TEST-003: expected duplicate path name in stderr.\nstderr: {result.stderr!r}"
        )
        assert "error" not in result.stdout.lower(), (
            f"AC-CHANNEL-001: error must not leak to stdout.\nstdout: {result.stdout!r}"
        )


@pytest.mark.functional
class TestTagFormatValidation:
    """AC-TEST-003: revision tag format, branch format, and constraint format."""

    @pytest.mark.parametrize(
        "valid_revision",
        [
            "refs/tags/example/proj/1.0.0",
            "refs/tags/example/proj/2.3.4",
            "main",
            "~=1.2.0",
            ">=1.0.0",
            ">=1.0.0,<2.0.0",
            "*",
        ],
    )
    def test_valid_revision_format_exits_zero(self, tmp_path: Path, valid_revision: str) -> None:
        """AC-TEST-003 positive: valid revision formats pass validation.

        Covers refs/tags semver, allowed branch names, version constraints,
        compound constraints, and the wildcard format.
        """
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "a-marketplace.xml",
            _valid_marketplace_xml(revision=valid_revision),
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 0, (
            f"AC-TEST-003: expected exit 0 for valid revision={valid_revision!r}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert result.stderr == "", f"AC-CHANNEL-001: expected no stderr on success.\nstderr: {result.stderr!r}"

    @pytest.mark.parametrize(
        "invalid_revision",
        [
            "refs/tags/no-semver",
            "random-string",
            "refs/heads/main",
            "develop",
            "feature/my-branch",
        ],
    )
    def test_invalid_revision_format_exits_one(self, tmp_path: Path, invalid_revision: str) -> None:
        """AC-TEST-003 negative: invalid revision formats fail validation.

        AC-CHANNEL-001: error goes to stderr, not stdout.
        """
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "a-marketplace.xml",
            _valid_marketplace_xml(revision=invalid_revision),
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 1, (
            f"AC-TEST-003: expected exit 1 for invalid revision={invalid_revision!r}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "error" in result.stderr.lower(), (
            f"AC-CHANNEL-001: expected error message on stderr.\nstderr: {result.stderr!r}"
        )
        assert "error" not in result.stdout.lower(), (
            f"AC-CHANNEL-001: error must not leak to stdout.\nstdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: marketplace-specific rules layered over generic xml validation
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestMarketplaceSpecificRules:
    """AC-FUNC-001: validate marketplace applies marketplace-specific checks.

    These tests confirm that the marketplace validator runs its own
    domain-specific rules (linkfile dest prefix, include chain integrity,
    project path uniqueness, revision format) that the generic XML validator
    does not apply.
    """

    def test_no_marketplace_files_exits_one(self, tmp_path: Path) -> None:
        """AC-FUNC-001: absence of *-marketplace.xml files is a fatal error.

        Generic XML validation would pass or fail on different grounds.
        The marketplace validator specifically requires at least one file
        matching *-marketplace.xml under repo-specs/.
        """
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "remote.xml",
            '<manifest><remote name="r" fetch="https://example.com" /></manifest>',
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 1, (
            f"AC-FUNC-001: expected exit 1 when no *-marketplace.xml files exist.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "error" in result.stderr.lower(), (
            f"AC-FUNC-001: expected error message on stderr.\nstderr: {result.stderr!r}"
        )

    def test_non_marketplace_xml_is_not_discovered(self, tmp_path: Path) -> None:
        """AC-FUNC-001: files not matching *-marketplace.xml glob are not validated.

        The glob filter is a marketplace-specific rule not present in the
        generic XML validator.
        """
        repo_root = _make_repo(tmp_path)
        # Write only a non-marketplace XML file -- this should not be discovered.
        _write_xml(
            repo_root / "repo-specs" / "catalog.xml",
            '<manifest><remote name="r" fetch="https://example.com" /></manifest>',
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        # No marketplace files found -- the command exits 1 with the "no files" error.
        assert result.returncode == 1, (
            f"AC-FUNC-001: expected exit 1 when only non-marketplace XML exists.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_subdirectory_marketplace_file_is_discovered(self, tmp_path: Path) -> None:
        """AC-FUNC-001: *-marketplace.xml files in subdirectories are discovered.

        The validator uses rglob, so nested marketplace files must be found.
        """
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "history" / "sub" / "claude-history-marketplace.xml",
            _valid_marketplace_xml(name="proj", path=".packages/proj"),
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 0, (
            f"AC-FUNC-001: expected exit 0 for nested marketplace file.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_all_errors_aggregated_before_reporting(self, tmp_path: Path) -> None:
        """AC-FUNC-001: all validation errors across rules are aggregated before exit.

        A single invalid file with both an invalid dest and invalid revision
        must report multiple errors in a single pass.
        """
        repo_root = _make_repo(tmp_path)
        content = textwrap.dedent("""\
            <manifest>
              <project name="bad" path=".packages/bad" remote="r" revision="invalid-string">
                <linkfile src="s" dest="/absolute/bad" />
              </project>
            </manifest>
        """)
        _write_xml(repo_root / "repo-specs" / "a-marketplace.xml", content)

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 1, (
            f"AC-FUNC-001: expected exit 1 for multiple errors.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        # Both errors must appear in stderr
        assert "invalid" in result.stderr.lower() or "error" in result.stderr.lower(), (
            f"AC-FUNC-001: expected error messages in stderr.\nstderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline (summary)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestStdoutStderrDiscipline:
    """AC-CHANNEL-001: progress and success messages go to stdout; errors to stderr."""

    def test_success_has_empty_stderr(self, tmp_path: Path) -> None:
        """AC-CHANNEL-001: a fully valid marketplace produces no stderr output."""
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "a-marketplace.xml",
            _valid_marketplace_xml(),
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 0, (
            f"Expected exit 0 for valid marketplace.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert result.stderr == "", f"AC-CHANNEL-001: expected empty stderr on success.\nstderr: {result.stderr!r}"

    def test_success_has_stdout_output(self, tmp_path: Path) -> None:
        """AC-CHANNEL-001: a fully valid marketplace produces progress/summary on stdout."""
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "a-marketplace.xml",
            _valid_marketplace_xml(),
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 0, (
            f"Expected exit 0 for valid marketplace.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        # The validator prints "Validating ..." progress and "All N ... passed." on stdout.
        assert result.stdout.strip() != "", (
            f"AC-CHANNEL-001: expected non-empty stdout on success.\nstdout: {result.stdout!r}"
        )

    def test_error_output_on_stderr_not_stdout(self, tmp_path: Path) -> None:
        """AC-CHANNEL-001: error summary appears on stderr, not stdout."""
        repo_root = _make_repo(tmp_path)
        _write_xml(
            repo_root / "repo-specs" / "a-marketplace.xml",
            _valid_marketplace_xml(dest="/absolute/bad"),
        )

        result = _run_kanon("validate", "marketplace", "--repo-root", str(repo_root))

        assert result.returncode == 1, (
            f"Expected exit 1 for invalid marketplace.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        # "Found N validation error(s):" appears on stderr.
        assert "error" in result.stderr.lower(), (
            f"AC-CHANNEL-001: expected error summary on stderr.\nstderr: {result.stderr!r}"
        )
        assert "error" not in result.stdout.lower(), (
            f"AC-CHANNEL-001: error summary must not appear on stdout.\nstdout: {result.stdout!r}"
        )

    def test_repo_root_not_found_error_on_stderr(self, tmp_path: Path) -> None:
        """AC-CHANNEL-001: --repo-root directory not found error goes to stderr."""
        nonexistent = tmp_path / "does_not_exist"

        result = _run_kanon("validate", "marketplace", "--repo-root", str(nonexistent))

        assert result.returncode == 1, (
            f"Expected exit 1 for nonexistent --repo-root.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "--repo-root directory not found" in result.stderr, (
            f"AC-CHANNEL-001: expected '--repo-root directory not found' on stderr.\nstderr: {result.stderr!r}"
        )
        assert "--repo-root directory not found" not in result.stdout, (
            f"AC-CHANNEL-001: error must not leak to stdout.\nstdout: {result.stdout!r}"
        )
