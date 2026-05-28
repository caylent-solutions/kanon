"""Composition test: 9 ``kanon list`` variants against one shared 6-entry synthetic catalog.

Exercises all nine list variants (rows 7/8/9/11/16/17/18/19 in findings.md)
against a single shared fixture built once at module scope so the composition
aspect -- every variant tested against the same catalog -- is asserted.

Per AC-FUNC-004, each method asserts shape-level expectations only.  Per-field
assertions remain in the existing per-variant test files:
  tests/integration/test_list_default.py
  tests/integration/test_list_format_json.py
  tests/integration/test_list_detail.py
  tests/unit/test_list_tree.py
  tests/integration/test_list_filter.py

Covers: AC-FUNC-001 through AC-FUNC-005, AC-TEST-001 through AC-TEST-004.
"""

from __future__ import annotations

import json
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

# Marketplace XML template matching the shape used by _create_manifest_repo_with_tags
# in test_add_core.py (spec §3.1).  All recommended fields are populated to
# suppress recommended-field warnings on stderr.
_MARKETPLACE_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>Integration test entry for {name}.</description>
        <version>1.0.0</version>
        <type>plugin</type>
        <owner-name>Integration Tester</owner-name>
        <owner-email>integration@example.com</owner-email>
        <keywords>integration, test</keywords>
      </catalog-metadata>
    </manifest>
""")

# Six catalog entries used by the shared fixture.
# Naming conventions chosen so that:
#   - regex ``^alpha`` matches alpha-core and alpha-utils (2 entries)
#   - positional substring ``beta`` matches beta-svc (1 entry)
#   - ``--match-fields name`` + substring ``alpha`` matches alpha-core and alpha-utils (2 entries)
_SIX_ENTRY_NAMES: list[str] = [
    "alpha-core",
    "alpha-utils",
    "beta-svc",
    "gamma-lib",
    "delta-tool",
    "epsilon-pkg",
]

# One PEP 440-valid tag applied to the initial commit.
_CATALOG_TAG = "1.0.0"


# ---------------------------------------------------------------------------
# Low-level git helpers (self-contained copy matching test_add_core.py §3.1)
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
        raise RuntimeError(
            f"git {args!r} failed in {cwd!r}:\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with deterministic test user config.

    Args:
        work_dir: The directory to initialise as a git repo.
    """
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into a bare repository and return the resolved bare path.

    Args:
        work_dir: Non-bare working directory to clone from.
        bare_dir: Destination path for the bare clone.

    Returns:
        Resolved absolute path to the bare clone.
    """
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def _create_manifest_repo_with_tags(
    base: pathlib.Path,
    entry_names: list[str],
    tags: list[str],
) -> pathlib.Path:
    """Create a bare manifest repo with marketplace XML files and git tags.

    Matches the spec §3.1 synthetic-fixture helper shape from test_add_core.py.
    Each entry in entry_names gets its own <name>-marketplace.xml under
    repo-specs/.  Each string in tags is applied as an annotated tag on the
    same commit.

    Args:
        base: Parent directory under which work and bare dirs are created.
        entry_names: Catalog entry names.
        tags: PEP 440-valid tag names to apply to the initial commit.

    Returns:
        Absolute path to the bare repo directory.
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    repo_specs_dir = work_dir / "repo-specs"
    repo_specs_dir.mkdir()
    (repo_specs_dir / ".gitkeep").write_text("")

    for name in entry_names:
        xml_path = repo_specs_dir / f"{name}-marketplace.xml"
        xml_path.write_text(_MARKETPLACE_XML_TEMPLATE.format(name=name))

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Add marketplace entries"], cwd=work_dir)

    for tag in tags:
        _git(["tag", "-a", tag, "-m", f"Release {tag}"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, base / "manifest-bare.git")
    return bare_dir.resolve()


# ---------------------------------------------------------------------------
# Module-scope shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def six_entry_synthetic_catalog(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Build a 6-entry synthetic catalog once and share it across all 9 tests.

    Returns the bare repo directory path.  Callers build the catalog-source
    URL as ``file://<path>@main``.
    """
    base = tmp_path_factory.mktemp("six_entry_catalog")
    return _create_manifest_repo_with_tags(
        base,
        entry_names=_SIX_ENTRY_NAMES,
        tags=[_CATALOG_TAG],
    )


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


def _run_kanon(
    args: list[str],
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run kanon via the same Python interpreter and capture stdout/stderr.

    Args:
        args: Arguments passed to kanon_cli (e.g. ``["list", "--format", "json"]``).
        extra_env: Environment variable overrides merged onto os.environ.

    Returns:
        Completed subprocess result with text stdout and stderr.
    """
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# 9-variant composition test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListSyntheticCatalogVariants:
    """9 kanon list variants against one shared 6-entry synthetic catalog.

    Findings.md rows covered: 7, 8, 9, 11, 16, 17, 18, 19.
    Shape-level assertions only -- per-field detail is owned by the
    per-variant test files.
    """

    def test_default_lists_six_entries_one_per_line_sorted_lex(
        self,
        six_entry_synthetic_catalog: pathlib.Path,
    ) -> None:
        """Default kanon list emits exactly 6 names, one per line, lexicographically sorted.

        Covers findings.md row 7.
        """
        catalog_source = f"file://{six_entry_synthetic_catalog}@main"
        result = _run_kanon(["list", "--catalog-source", catalog_source])

        assert result.returncode == 0, (
            f"Expected exit 0; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        lines = result.stdout.strip().splitlines()
        assert len(lines) == 6, (
            f"Expected exactly 6 output lines; got {len(lines)}.\n  lines: {lines!r}"
        )
        assert lines == sorted(lines), (
            f"Expected lexicographic sort; got: {lines!r}"
        )
        assert lines == sorted(_SIX_ENTRY_NAMES), (
            f"Expected sorted entry names; got: {lines!r}"
        )

    def test_format_json_emits_six_entry_array(
        self,
        six_entry_synthetic_catalog: pathlib.Path,
    ) -> None:
        """kanon list --format json emits a valid 6-element JSON array.

        Covers findings.md row 8.
        """
        catalog_source = f"file://{six_entry_synthetic_catalog}@main"
        result = _run_kanon(["list", "--format", "json", "--catalog-source", catalog_source])

        assert result.returncode == 0, (
            f"Expected exit 0; got {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, list), (
            f"Expected JSON array; got type {type(parsed).__name__}."
        )
        assert len(parsed) == 6, (
            f"Expected 6-element JSON array; got {len(parsed)} elements."
        )

    def test_detail_emits_six_entries_with_detail_fields(
        self,
        six_entry_synthetic_catalog: pathlib.Path,
    ) -> None:
        """kanon list --detail emits 6 name-header records with indented field lines.

        Covers findings.md row 9.
        """
        catalog_source = f"file://{six_entry_synthetic_catalog}@main"
        result = _run_kanon(["list", "--detail", "--catalog-source", catalog_source])

        assert result.returncode == 0, (
            f"Expected exit 0; got {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        # Name-header lines are non-indented, non-empty lines.
        header_lines = [
            ln for ln in result.stdout.splitlines() if ln and not ln.startswith(" ")
        ]
        assert len(header_lines) == 6, (
            f"Expected 6 name-header lines in --detail output; got {len(header_lines)}.\n"
            f"  headers: {header_lines!r}"
        )
        assert sorted(header_lines) == sorted(_SIX_ENTRY_NAMES), (
            f"Header names do not match expected entry names.\n"
            f"  headers: {header_lines!r}"
        )
        # Each detail record has 4 indented field lines: display-name, description, version, type.
        indented_lines = [ln for ln in result.stdout.splitlines() if ln.startswith("  ")]
        assert len(indented_lines) == 6 * 4, (
            f"Expected {6 * 4} indented field lines (6 entries x 4 fields); "
            f"got {len(indented_lines)}."
        )

    def test_tree_emits_root_with_six_children(
        self,
        six_entry_synthetic_catalog: pathlib.Path,
    ) -> None:
        """kanon list --tree emits one root line per entry (6 lines total) for simple XMLs.

        Simple marketplace XMLs (no <include> or <project>) render as a single
        root line each.  The 6-entry catalog therefore produces exactly 6 lines.
        """
        catalog_source = f"file://{six_entry_synthetic_catalog}@main"
        result = _run_kanon(["list", "--tree", "--catalog-source", catalog_source])

        assert result.returncode == 0, (
            f"Expected exit 0; got {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert len(lines) == 6, (
            f"Expected 6 tree root lines (one per entry); got {len(lines)}.\n"
            f"  lines: {lines!r}"
        )
        # Every line must begin with 'entry ' (the tree root-node prefix).
        for line in lines:
            assert line.startswith("entry "), (
                f"Expected tree root line to start with 'entry '; got: {line!r}"
            )

    def test_tree_max_depth_1_truncates_below_root(
        self,
        six_entry_synthetic_catalog: pathlib.Path,
    ) -> None:
        """kanon list --tree --max-depth 1 produces one root line per entry.

        For simple XMLs with no includes, max-depth 1 is the same as unlimited
        depth (no layer-b XML includes exist), so the output is still 6 lines.
        Covers findings.md row 11.
        """
        catalog_source = f"file://{six_entry_synthetic_catalog}@main"
        result = _run_kanon(
            ["list", "--tree", "--max-depth", "1", "--catalog-source", catalog_source]
        )

        assert result.returncode == 0, (
            f"Expected exit 0; got {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert len(lines) == 6, (
            f"Expected 6 root lines with --max-depth 1; got {len(lines)}.\n"
            f"  lines: {lines!r}"
        )
        # With max-depth 1, no project-level (+--) or continuation (|  ) lines appear.
        for line in lines:
            assert not line.startswith("+--") and not line.startswith("|"), (
                f"Unexpected child-node line at max-depth 1: {line!r}"
            )

    def test_regex_filter_matches_subset(
        self,
        six_entry_synthetic_catalog: pathlib.Path,
    ) -> None:
        """kanon list --regex ^alpha returns only the 2 entries whose names start with 'alpha'.

        Covers findings.md row 16.
        """
        catalog_source = f"file://{six_entry_synthetic_catalog}@main"
        result = _run_kanon(
            ["list", "--regex", "^alpha", "--catalog-source", catalog_source]
        )

        assert result.returncode == 0, (
            f"Expected exit 0; got {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        lines = result.stdout.strip().splitlines()
        # alpha-core and alpha-utils start with 'alpha' in their name field.
        assert len(lines) == 2, (
            f"Expected 2 entries matching '^alpha'; got {len(lines)}.\n  lines: {lines!r}"
        )
        for name in lines:
            assert name.startswith("alpha"), (
                f"Entry {name!r} does not start with 'alpha' -- regex filter leaked."
            )

    def test_match_fields_filter_matches_subset(
        self,
        six_entry_synthetic_catalog: pathlib.Path,
    ) -> None:
        """kanon list alpha --match-fields name returns 2 entries whose name contains 'alpha'.

        Restricting the search to the name field means only entries whose
        <name> element contains 'alpha' match, which is alpha-core and alpha-utils.
        Covers findings.md row 17.
        """
        catalog_source = f"file://{six_entry_synthetic_catalog}@main"
        result = _run_kanon(
            [
                "list",
                "alpha",
                "--match-fields",
                "name",
                "--catalog-source",
                catalog_source,
            ]
        )

        assert result.returncode == 0, (
            f"Expected exit 0; got {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        lines = result.stdout.strip().splitlines()
        assert len(lines) == 2, (
            f"Expected 2 entries with 'alpha' in name field; got {len(lines)}.\n"
            f"  lines: {lines!r}"
        )
        for name in lines:
            assert "alpha" in name, (
                f"Entry {name!r} does not contain 'alpha' -- match-fields filter leaked."
            )

    def test_positional_substring_filter_matches_subset(
        self,
        six_entry_synthetic_catalog: pathlib.Path,
    ) -> None:
        """kanon list beta returns only entries containing 'beta' in the default match fields.

        Of the 6 entries, only beta-svc has 'beta' in name/display-name/description/keywords.
        Covers findings.md row 18.
        """
        catalog_source = f"file://{six_entry_synthetic_catalog}@main"
        result = _run_kanon(["list", "beta", "--catalog-source", catalog_source])

        assert result.returncode == 0, (
            f"Expected exit 0; got {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        lines = result.stdout.strip().splitlines()
        assert len(lines) == 1, (
            f"Expected exactly 1 entry matching substring 'beta'; got {len(lines)}.\n"
            f"  lines: {lines!r}"
        )
        assert lines[0] == "beta-svc", (
            f"Expected 'beta-svc'; got {lines[0]!r}."
        )

    def test_format_json_tree_mutex_errors(
        self,
        six_entry_synthetic_catalog: pathlib.Path,
    ) -> None:
        """kanon list --format json --tree exits non-zero with the mutex-error on stderr.

        AC-FUNC-005: asserts both the non-zero exit code AND the documented
        stderr substring ('--format json and --tree are mutually exclusive').
        Covers findings.md row 19.
        """
        catalog_source = f"file://{six_entry_synthetic_catalog}@main"
        result = _run_kanon(
            [
                "list",
                "--format",
                "json",
                "--tree",
                "--no-filter-required",
                "--catalog-source",
                catalog_source,
            ]
        )

        assert result.returncode != 0, (
            f"Expected non-zero exit for --format json --tree; got {result.returncode}."
        )
        assert "--format json and --tree are mutually exclusive" in result.stderr, (
            f"Expected mutex-error substring in stderr; got: {result.stderr!r}"
        )
