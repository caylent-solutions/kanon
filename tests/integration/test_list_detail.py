"""Integration tests for 'kanon search --detail'.

Builds temporary local file:// manifest-repo fixtures (committed git repos
with *-marketplace.xml files) and invokes 'kanon search --detail --catalog-source
<file>@<ref>' via subprocess.run.

Covers:
- Three-entry catalog: one record per entry, name header + four field lines.
- Per-entry record shape matches spec Section 2.1 step 2.
- Missing recommended field (type) renders as ``<missing>``; stderr warning surfaces.
- Lexicographic ordering: detail records are sorted by entry name.
- AC-CYCLE-001: end-to-end cycle with full and partial entries.
- Exit codes and stderr behaviour.

AC-TEST-002, AC-TEST-003, AC-CYCLE-001.
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Git helper constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"

# Full marketplace XML template (all recommended fields included).
_FULL_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{display_name}</display-name>
        <description>{description}</description>
        <version>{version}</version>
        <type>{pkg_type}</type>
        <owner-name>Integration Tester</owner-name>
        <owner-email>integration@example.com</owner-email>
        <keywords>integration, test</keywords>
      </catalog-metadata>
    </manifest>
""")

# Partial XML: omits type, owner-name, owner-email, keywords (triggers WARNING).
_PARTIAL_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{display_name}</display-name>
        <description>{description}</description>
        <version>{version}</version>
      </catalog-metadata>
    </manifest>
""")


# ---------------------------------------------------------------------------
# Low-level git helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit.

    Args:
        args: Git subcommand and arguments (without 'git' prefix).
        cwd: Working directory for the git command.

    Raises:
        RuntimeError: When the git command exits with non-zero exit code.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with test user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into a bare repository and return the bare path."""
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _create_manifest_repo(
    base: pathlib.Path,
    entries: list[dict],
) -> pathlib.Path:
    """Create a bare manifest repo with entries under repo-specs/.

    Each entry dict must have keys: name, display_name, description, version,
    and optionally pkg_type (None triggers partial XML with missing type).

    Args:
        base: Parent directory under which work and bare dirs are created.
        entries: List of dicts describing each catalog entry.

    Returns:
        Absolute path to the bare git repository.
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    repo_specs_dir = work_dir / "repo-specs"
    repo_specs_dir.mkdir()
    (repo_specs_dir / ".gitkeep").write_text("")

    for entry in entries:
        xml_path = repo_specs_dir / f"{entry['name']}-marketplace.xml"
        pkg_type = entry.get("pkg_type")
        if pkg_type is None:
            xml_path.write_text(
                _PARTIAL_XML_TEMPLATE.format(
                    name=entry["name"],
                    display_name=entry["display_name"],
                    description=entry["description"],
                    version=entry["version"],
                )
            )
        else:
            xml_path.write_text(
                _FULL_XML_TEMPLATE.format(
                    name=entry["name"],
                    display_name=entry["display_name"],
                    description=entry["description"],
                    version=entry["version"],
                    pkg_type=pkg_type,
                )
            )

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Add marketplace entries"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / "manifest-bare.git")


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


def _run_kanon(
    args: list[str],
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run kanon via the same Python interpreter used by pytest.

    Args:
        args: Arguments to pass after the interpreter (e.g. ["search", "--detail", ...]).
        extra_env: Environment variables to overlay onto os.environ.

    Returns:
        The completed subprocess result.
    """
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# Integration test: --detail with a three-entry catalog
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListDetailThreeEntries:
    """kanon search --detail with three marketplace XMLs: per-entry records."""

    def _build_three_entry_repo(self, tmp_path: pathlib.Path) -> str:
        """Create a three-entry bare repo and return the catalog-source string."""
        entries = [
            {
                "name": "gamma",
                "display_name": "Gamma Package",
                "description": "Gamma description.",
                "version": "3.0.0",
                "pkg_type": "plugin",
            },
            {
                "name": "alpha",
                "display_name": "Alpha Package",
                "description": "Alpha description.",
                "version": "1.0.0",
                "pkg_type": "library",
            },
            {
                "name": "beta",
                "display_name": "Beta Package",
                "description": "Beta description.",
                "version": "2.0.0",
                "pkg_type": "plugin",
            },
        ]
        bare = _create_manifest_repo(tmp_path, entries)
        return f"file://{bare}@main"

    def test_exits_0(self, tmp_path: pathlib.Path) -> None:
        """kanon search --detail exits 0 for a three-entry catalog."""
        catalog_source = self._build_three_entry_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert result.returncode == 0, (
            f"Expected exit 0; got {result.returncode}.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_stdout_has_three_name_headers(self, tmp_path: pathlib.Path) -> None:
        """kanon search --detail stdout contains one name header per entry."""
        catalog_source = self._build_three_entry_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        # Header lines are non-indented, non-empty lines.
        header_lines = [ln for ln in result.stdout.splitlines() if ln and not ln.startswith(" ")]
        assert sorted(header_lines) == ["alpha", "beta", "gamma"], (
            f"Expected headers ['alpha', 'beta', 'gamma']; got {header_lines!r}.\n  stdout: {result.stdout!r}"
        )

    def test_headers_sorted_lexicographically(self, tmp_path: pathlib.Path) -> None:
        """kanon search --detail emits records in lexicographic order by name."""
        catalog_source = self._build_three_entry_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        header_lines = [ln for ln in result.stdout.splitlines() if ln and not ln.startswith(" ")]
        assert header_lines == ["alpha", "beta", "gamma"], f"Expected lexicographic order; got {header_lines!r}"

    def test_each_record_contains_field_lines(self, tmp_path: pathlib.Path) -> None:
        """Each record block contains indented field lines."""
        catalog_source = self._build_three_entry_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        indented_lines = [ln for ln in result.stdout.splitlines() if ln.startswith("  ")]
        # 3 entries x 4 fields each = 12 indented lines.
        assert len(indented_lines) == 12, (
            f"Expected 12 indented lines (3 entries x 4 fields); got {len(indented_lines)}.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_field_lines_contain_colon_separator(self, tmp_path: pathlib.Path) -> None:
        """All indented field lines contain the ' : ' separator."""
        catalog_source = self._build_three_entry_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        indented_lines = [ln for ln in result.stdout.splitlines() if ln.startswith("  ")]
        for line in indented_lines:
            assert " : " in line, f"Line missing ' : ' separator: {line!r}"

    def test_alpha_entry_contains_correct_fields(self, tmp_path: pathlib.Path) -> None:
        """The 'alpha' entry record contains its correct display-name and version."""
        catalog_source = self._build_three_entry_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        stdout = result.stdout
        # Find the alpha record (lines from 'alpha' header to the next blank/header).
        lines = stdout.splitlines()
        alpha_block = []
        in_alpha = False
        for line in lines:
            if line == "alpha":
                in_alpha = True
                alpha_block.append(line)
            elif in_alpha and line.startswith("  "):
                alpha_block.append(line)
            elif in_alpha:
                break
        alpha_text = "\n".join(alpha_block)
        assert "Alpha Package" in alpha_text
        assert "1.0.0" in alpha_text

    def test_no_error_lines_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """No ERROR: lines appear in stderr for a well-formed three-entry catalog."""
        catalog_source = self._build_three_entry_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "ERROR:" not in result.stderr, f"Unexpected ERROR: in stderr: {result.stderr!r}"


# ---------------------------------------------------------------------------
# Integration test: AC-CYCLE-001 -- full + partial entries
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListDetailAcCycle001:
    """AC-CYCLE-001: one full entry + one entry missing type/owner-email.

    Verifies:
    - Both records render.
    - Full entry has its field values; partial shows <missing> for type.
    - Recommended-field WARNING surfaces exactly once on stderr for partial entry.
    """

    def _build_mixed_repo(self, tmp_path: pathlib.Path) -> str:
        """Two-entry repo: full-entry (all fields) + partial-entry (type missing)."""
        entries = [
            {
                "name": "full-entry",
                "display_name": "Full Entry",
                "description": "Has all recommended fields.",
                "version": "1.0.0",
                "pkg_type": "library",
            },
            {
                "name": "partial-entry",
                "display_name": "Partial Entry",
                "description": "Missing type and owner fields.",
                "version": "0.5.0",
                "pkg_type": None,  # Omit type, owner-name, owner-email, keywords.
            },
        ]
        bare = _create_manifest_repo(tmp_path, entries)
        return f"file://{bare}@main"

    def test_exits_0_mixed_repo(self, tmp_path: pathlib.Path) -> None:
        """kanon search --detail exits 0 for a repo with both full and partial entries."""
        catalog_source = self._build_mixed_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert result.returncode == 0, (
            f"Expected exit 0; got {result.returncode}.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_both_entry_headers_present(self, tmp_path: pathlib.Path) -> None:
        """Both 'full-entry' and 'partial-entry' headers appear in output."""
        catalog_source = self._build_mixed_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        header_lines = [ln for ln in result.stdout.splitlines() if ln and not ln.startswith(" ")]
        assert "full-entry" in header_lines, f"'full-entry' not found in headers: {header_lines!r}"
        assert "partial-entry" in header_lines, f"'partial-entry' not found in headers: {header_lines!r}"

    def test_full_entry_shows_type_value(self, tmp_path: pathlib.Path) -> None:
        """full-entry record contains 'library' for the type field."""
        catalog_source = self._build_mixed_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "library" in result.stdout, f"Expected 'library' in full-entry record; stdout: {result.stdout!r}"

    def test_partial_entry_shows_missing_placeholder(self, tmp_path: pathlib.Path) -> None:
        """partial-entry record shows '<missing>' for the type field."""
        catalog_source = self._build_mixed_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "<missing>" in result.stdout, f"Expected '<missing>' placeholder in output; stdout: {result.stdout!r}"

    def test_warning_appears_once_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Exactly one WARNING: line appears on stderr -- for the partial entry."""
        catalog_source = self._build_mixed_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        warning_count = result.stderr.count("WARNING:")
        assert warning_count == 1, (
            f"Expected exactly 1 WARNING: in stderr; got {warning_count}.\n  stderr: {result.stderr!r}"
        )

    def test_no_error_lines_for_mixed_repo(self, tmp_path: pathlib.Path) -> None:
        """No ERROR: lines appear in stderr for a mixed repo (full + partial entries)."""
        catalog_source = self._build_mixed_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "ERROR:" not in result.stderr, f"Unexpected ERROR: in stderr: {result.stderr!r}"

    def test_entries_in_lexicographic_order(self, tmp_path: pathlib.Path) -> None:
        """Records appear sorted: 'full-entry' before 'partial-entry' alphabetically."""
        catalog_source = self._build_mixed_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        header_lines = [ln for ln in result.stdout.splitlines() if ln and not ln.startswith(" ")]
        assert header_lines == ["full-entry", "partial-entry"], (
            f"Expected ['full-entry', 'partial-entry']; got {header_lines!r}"
        )


# ---------------------------------------------------------------------------
# Integration test: record shape matches spec Section 2.1 step 2
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListDetailRecordShape:
    """The per-entry record shape matches the spec Section 2.1 step 2 worked example."""

    def _build_spec_example_repo(self, tmp_path: pathlib.Path) -> str:
        """Build a repo with one entry that matches the spec Section 2.1 example."""
        entries = [
            {
                "name": "package-a",
                "display_name": "Package A",
                "description": "Example dependency",
                "version": "1.4.2",
                "pkg_type": "library",
            }
        ]
        bare = _create_manifest_repo(tmp_path, entries)
        return f"file://{bare}@main"

    def test_first_line_is_entry_name(self, tmp_path: pathlib.Path) -> None:
        """First line of the record is the entry name with no indent."""
        catalog_source = self._build_spec_example_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        lines = result.stdout.splitlines()
        assert lines[0] == "package-a"

    def test_display_name_field_present(self, tmp_path: pathlib.Path) -> None:
        """Record contains 'display-name' label with 'Package A' value."""
        catalog_source = self._build_spec_example_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "display-name" in result.stdout
        assert "Package A" in result.stdout

    def test_description_field_present(self, tmp_path: pathlib.Path) -> None:
        """Record contains 'description' label with 'Example dependency' value."""
        catalog_source = self._build_spec_example_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "description" in result.stdout
        assert "Example dependency" in result.stdout

    def test_version_field_present(self, tmp_path: pathlib.Path) -> None:
        """Record contains 'version' label with '1.4.2' value."""
        catalog_source = self._build_spec_example_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "version" in result.stdout
        assert "1.4.2" in result.stdout

    def test_type_field_present(self, tmp_path: pathlib.Path) -> None:
        """Record contains 'type' label with 'library' value."""
        catalog_source = self._build_spec_example_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert "type" in result.stdout
        assert "library" in result.stdout

    def test_field_lines_have_two_space_indent(self, tmp_path: pathlib.Path) -> None:
        """All field lines start with two spaces per spec format."""
        catalog_source = self._build_spec_example_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        lines = result.stdout.splitlines()
        for line in lines[1:]:  # Skip name header.
            if line:  # Skip blank separators if any.
                assert line.startswith("  "), f"Field line missing two-space indent: {line!r}"

    def test_record_has_five_lines(self, tmp_path: pathlib.Path) -> None:
        """Single-entry output has exactly 5 lines: name + 4 fields."""
        catalog_source = self._build_spec_example_repo(tmp_path)
        result = _run_kanon(
            ["search", "--detail", "--catalog-source", catalog_source],
            extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        non_blank_lines = [ln for ln in result.stdout.splitlines() if ln]
        assert len(non_blank_lines) == 5, (
            f"Expected 5 non-blank lines (name + 4 fields); got {len(non_blank_lines)}.\n  stdout: {result.stdout!r}"
        )
