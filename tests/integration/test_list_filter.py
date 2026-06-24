"""Integration tests for the ``kanon search`` filter framework.

Builds a temporary local file:// manifest-repo fixture (committed git repo
with five ``*-marketplace.xml`` files with varied display-names, descriptions,
and keywords) and invokes ``kanon search`` end-to-end via subprocess.

Covers:
- ``kanon search <substring>`` -- only matching entries appear.
- ``kanon search --regex <pattern>`` -- only regex-matching entries appear.
- ``kanon search <substring> --match-fields description`` -- narrowed field set.
- ``kanon search --match-fields name`` -- hard error (no filter supplied).
- ``kanon search foo --regex bar`` -- hard error (both substring and regex).
- ``kanon search xyz-no-match`` -- exit 0, empty stdout, stderr note.
- Filter + ``--tree`` interaction: a large-enough catalog unblocked by filter.

AC-TEST-002, AC-TEST-003, AC-CYCLE-001, AC-FUNC-009
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Git helper constants and utilities
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"


# Marketplace XML template with configurable metadata fields.
# All recommended fields are present to suppress spurious WARNING: stderr output.
_MARKETPLACE_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{display_name}</display-name>
        <description>{description}</description>
        <version>1.0.0</version>
        <type>plugin</type>
        <owner-name>Integration Tester</owner-name>
        <owner-email>integration@example.com</owner-email>
        <keywords>{keywords}</keywords>
      </catalog-metadata>
    </manifest>
""")


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
    """Initialise a git working directory with test user config.

    Args:
        work_dir: The directory to initialise as a git repo.
    """
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into a bare repository and return the bare path.

    Args:
        work_dir: Non-bare working directory to clone from.
        bare_dir: Destination path for the bare clone.

    Returns:
        The resolved absolute path to the bare clone.
    """
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


# ---------------------------------------------------------------------------
# Fixture: manifest repo with varied entries
# ---------------------------------------------------------------------------

# Five catalog entries with varied metadata used in AC-CYCLE-001.
# Entry names and fields are chosen so that:
#   - "foo" substring matches entries 1 and 2 by name/display-name/description/keywords.
#   - "^foo" regex matches entries starting with "foo" in name.
#   - "--match-fields keywords" with "foo" matches entry 3 (only in keywords).
#   - "xyz-no-match" matches nobody.
_FIVE_ENTRIES = [
    {
        "name": "foo-alpha",
        "display_name": "Foo Alpha Widget",
        "description": "A widget in the foo category.",
        "keywords": "widget, alpha",
    },
    {
        "name": "foo-beta",
        "display_name": "Beta Foo Gadget",
        "description": "A gadget related to beta work.",
        "keywords": "gadget, beta",
    },
    {
        "name": "gamma-lib",
        "display_name": "Gamma Library",
        "description": "Core library for gamma operations.",
        "keywords": "foo, library, gamma",
    },
    {
        "name": "delta-tool",
        "display_name": "Delta Tool",
        "description": "Tool for delta processing.",
        "keywords": "tool, delta",
    },
    {
        "name": "epsilon-svc",
        "display_name": "Epsilon Service",
        "description": "Service for epsilon tasks.",
        "keywords": "service, epsilon",
    },
]


def _create_manifest_repo(
    base: pathlib.Path,
    entries: list[dict],
    dir_suffix: str = "manifest",
) -> pathlib.Path:
    """Create a bare manifest repo from a list of entry dicts.

    Each dict must contain: name, display_name, description, keywords (str).

    Args:
        base: Parent directory under which work and bare dirs are created.
        entries: List of dicts with marketplace XML field values.
        dir_suffix: Unique suffix for this repo's work/bare directories.

    Returns:
        The absolute path to the bare repo.
    """
    work_dir = base / f"{dir_suffix}-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    repo_specs_dir = work_dir / "repo-specs"
    repo_specs_dir.mkdir()
    (repo_specs_dir / ".gitkeep").write_text("")

    for entry in entries:
        xml_path = repo_specs_dir / f"{entry['name']}-marketplace.xml"
        xml_path.write_text(_MARKETPLACE_XML_TEMPLATE.format(**entry))

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Add marketplace entries"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, base / f"{dir_suffix}-bare.git")
    return bare_dir


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


def _run_kanon(
    args: list[str],
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon entry point via the same Python interpreter.

    Uses sys.executable -m kanon_cli so no separate installation is needed.

    Args:
        args: Additional arguments to pass after 'kanon_cli'.
        extra_env: Extra environment variable overrides.

    Returns:
        :class:`subprocess.CompletedProcess` with stdout and stderr captured.
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
# Tests: substring filter
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSubstringFilter:
    """Integration tests for the positional substring filter."""

    def test_substring_foo_matches_name_fields(self, tmp_path: pathlib.Path) -> None:
        """'kanon search foo' returns only entries whose default fields contain 'foo'."""
        bare = _create_manifest_repo(tmp_path, _FIVE_ENTRIES, dir_suffix="sub-foo")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(["search", "foo", "--catalog-source", catalog_source])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        output_names = result.stdout.strip().splitlines()
        # foo-alpha: name contains 'foo'
        # foo-beta: name contains 'foo'
        # gamma-lib: keywords contain 'foo'
        assert "foo-alpha" in output_names
        assert "foo-beta" in output_names
        assert "gamma-lib" in output_names
        # delta-tool and epsilon-svc have no 'foo' anywhere
        assert "delta-tool" not in output_names
        assert "epsilon-svc" not in output_names

    def test_substring_no_match_exit_0(self, tmp_path: pathlib.Path) -> None:
        """'kanon search xyz-no-match' exits 0 when no entries match."""
        bare = _create_manifest_repo(tmp_path, _FIVE_ENTRIES, dir_suffix="sub-nomatch")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(["search", "xyz-no-match", "--catalog-source", catalog_source])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"

    def test_substring_no_match_empty_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon search xyz-no-match' produces empty stdout when no entries match."""
        bare = _create_manifest_repo(tmp_path, _FIVE_ENTRIES, dir_suffix="sub-nomatch-stdout")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(["search", "xyz-no-match", "--catalog-source", catalog_source])

        assert result.stdout == ""

    def test_substring_no_match_stderr_note(self, tmp_path: pathlib.Path) -> None:
        """'kanon search xyz-no-match' writes the spec zero-match note to stderr."""
        bare = _create_manifest_repo(tmp_path, _FIVE_ENTRIES, dir_suffix="sub-nomatch-note")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(["search", "xyz-no-match", "--catalog-source", catalog_source])

        assert "0 entries match filter" in result.stderr


# ---------------------------------------------------------------------------
# Tests: regex filter
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRegexFilter:
    """Integration tests for the --regex filter."""

    def test_regex_anchored_start_matches_name(self, tmp_path: pathlib.Path) -> None:
        """'kanon search --regex ^foo' matches only entries whose name starts with 'foo'."""
        bare = _create_manifest_repo(tmp_path, _FIVE_ENTRIES, dir_suffix="regex-anchor")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(["search", "--regex", "^foo", "--catalog-source", catalog_source])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        output_names = result.stdout.strip().splitlines()
        # Only foo-alpha and foo-beta start with 'foo' in name
        # gamma-lib has 'foo' in keywords but NOT at start of name
        assert "foo-alpha" in output_names
        assert "foo-beta" in output_names
        # gamma-lib name doesn't start with foo; check display-name and description too
        # "Gamma Library" - no "foo"; "Core library for gamma operations." - no "foo"
        # But keywords "foo, library, gamma" -- re.search("^foo", "foo") -> matches!
        assert "gamma-lib" in output_names
        assert "delta-tool" not in output_names
        assert "epsilon-svc" not in output_names

    def test_regex_no_match_exit_0(self, tmp_path: pathlib.Path) -> None:
        """'kanon search --regex ^xyz-no-match$' exits 0 when no entries match."""
        bare = _create_manifest_repo(tmp_path, _FIVE_ENTRIES, dir_suffix="regex-nomatch")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(["search", "--regex", "^xyz-no-match$", "--catalog-source", catalog_source])

        assert result.returncode == 0
        assert result.stdout == ""
        assert "0 entries match filter" in result.stderr


# ---------------------------------------------------------------------------
# Tests: --match-fields narrowing
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMatchFieldsFilter:
    """Integration tests for the --match-fields flag."""

    def test_match_fields_keywords_with_substring(self, tmp_path: pathlib.Path) -> None:
        """'kanon search foo --match-fields keywords' only checks keywords field."""
        bare = _create_manifest_repo(tmp_path, _FIVE_ENTRIES, dir_suffix="mf-keywords")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(["search", "foo", "--match-fields", "keywords", "--catalog-source", catalog_source])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        output_names = result.stdout.strip().splitlines()
        # gamma-lib has 'foo' in keywords
        assert "gamma-lib" in output_names
        # foo-alpha: name 'foo-alpha' has 'foo' but we only check keywords -- "widget, alpha"
        assert "foo-alpha" not in output_names
        # foo-beta: keywords "gadget, beta" -- no 'foo'
        assert "foo-beta" not in output_names

    def test_match_fields_description_with_substring(self, tmp_path: pathlib.Path) -> None:
        """'kanon search foo --match-fields description' only checks description field."""
        bare = _create_manifest_repo(tmp_path, _FIVE_ENTRIES, dir_suffix="mf-desc")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(["search", "foo", "--match-fields", "description", "--catalog-source", catalog_source])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        output_names = result.stdout.strip().splitlines()
        # foo-alpha: description "A widget in the foo category." -- has 'foo'
        assert "foo-alpha" in output_names
        # foo-beta: description "A gadget related to beta work." -- no 'foo'
        assert "foo-beta" not in output_names


# ---------------------------------------------------------------------------
# Tests: hard errors (mutual exclusion)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMutualExclusionErrors:
    """Integration tests for the mutual-exclusion hard errors."""

    def test_match_fields_without_filter_is_hard_error(self, tmp_path: pathlib.Path) -> None:
        """'kanon search --match-fields name' is a hard error (non-zero exit, ERROR: stderr)."""
        bare = _create_manifest_repo(tmp_path, _FIVE_ENTRIES[:1], dir_suffix="me-nofilter")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(["search", "--match-fields", "name", "--catalog-source", catalog_source])

        assert result.returncode != 0
        assert "ERROR:" in result.stderr

    def test_substring_and_regex_together_is_hard_error(self, tmp_path: pathlib.Path) -> None:
        """'kanon search foo --regex bar' is a hard error (non-zero exit, ERROR: stderr)."""
        bare = _create_manifest_repo(tmp_path, _FIVE_ENTRIES[:1], dir_suffix="me-both")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(["search", "foo", "--regex", "bar", "--catalog-source", catalog_source])

        assert result.returncode != 0
        assert "ERROR:" in result.stderr


# ---------------------------------------------------------------------------
# Tests: filter + --tree guardrail interaction
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFilterTreeInteraction:
    """Integration tests for filter + --tree: guardrail is bypassed when filter supplied.

    AC-TEST-003, AC-FUNC-009
    """

    def test_filter_unblocks_tree_guardrail(self, tmp_path: pathlib.Path) -> None:
        """Supplying a substring filter unblocks the --tree guardrail for large catalogs."""
        # Build a catalog with threshold+1 entries to trigger the guardrail.
        # Use KANON_TREE_NO_FILTER_THRESHOLD=3 so the test is cheap.
        threshold = 3
        entries = [
            {
                "name": f"entry-{i:02d}",
                "display_name": f"Entry {i:02d}",
                "description": f"Description for entry {i:02d}.",
                "keywords": "test, integration" if i == 0 else "other, misc",
            }
            for i in range(threshold + 1)
        ]
        bare = _create_manifest_repo(tmp_path, entries, dir_suffix="tree-filter")
        catalog_source = f"file://{bare}@main"

        # Without filter, guardrail fires.
        result_no_filter = _run_kanon(
            ["search", "--tree", "--catalog-source", catalog_source],
            extra_env={"KANON_TREE_NO_FILTER_THRESHOLD": str(threshold)},
        )
        assert result_no_filter.returncode != 0, "Expected guardrail to fire without filter"

        # With substring filter, guardrail does not fire.
        result_with_filter = _run_kanon(
            ["search", "--tree", "entry-00", "--catalog-source", catalog_source],
            extra_env={"KANON_TREE_NO_FILTER_THRESHOLD": str(threshold)},
        )
        assert result_with_filter.returncode == 0, (
            f"Expected filter to unblock guardrail. stderr: {result_with_filter.stderr!r}"
        )
        # Only the matched entry appears in the output
        assert "entry-00" in result_with_filter.stdout

    def test_regex_filter_unblocks_tree_guardrail(self, tmp_path: pathlib.Path) -> None:
        """Supplying --regex filter also unblocks the --tree guardrail."""
        threshold = 3
        entries = [
            {
                "name": f"target-{i:02d}",
                "display_name": f"Target {i:02d}",
                "description": f"Target entry {i:02d}.",
                "keywords": "test",
            }
            for i in range(threshold + 1)
        ]
        bare = _create_manifest_repo(tmp_path, entries, dir_suffix="tree-regex")
        catalog_source = f"file://{bare}@main"

        result = _run_kanon(
            ["search", "--tree", "--regex", "^target-00$", "--catalog-source", catalog_source],
            extra_env={"KANON_TREE_NO_FILTER_THRESHOLD": str(threshold)},
        )
        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert "target-00" in result.stdout
