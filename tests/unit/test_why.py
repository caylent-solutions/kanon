"""Unit tests for the kanon why command.

Covers:
- Single-chain tree: one top-level source -> one matching project -> one line printed.
- Multi-chain same source: project reachable via two different include paths -> two lines.
- Multi-chain different sources: two top-level sources each reaching the same project -> two lines.
- Not-found: project URL not in tree -> hard error with non-zero exit.
- Missing .kanon file -> hard error naming missing path.
- Missing catalog source when no lockfile -> hard error.
- Lockfile present -> skips live-resolve, reads SHAs from lockfile.
- URL canonicalization equivalence: git@github.com and https forms match same project.
- Include-chain placement: projects placed under leaf includes in tree.
- Live-resolve raises NotImplementedError -> run() converts to clean error message.

AC-TEST-001
"""

import argparse
import pathlib
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from kanon_cli.commands.why import (
    _build_tree_from_lockfile,
    _collect_leaf_include_nodes,
    _include_entry_to_node,
    _live_resolve_tree,
    _walk_chains,
    _render_text,
    run,
    ChainNode,
    ResolvedTree,
)

if TYPE_CHECKING:
    from kanon_cli.core.lockfile import Lockfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(
    target: str,
    kanon_file: str = "/fake/.kanon",
    lock_file: str | None = None,
    catalog_source: str | None = "file:///fake/catalog@HEAD",
    format: str = "text",
) -> argparse.Namespace:
    """Build a minimal argparse Namespace matching the why subcommand signature."""
    return argparse.Namespace(
        target=target,
        kanon_file=kanon_file,
        lock_file=lock_file,
        catalog_source=catalog_source,
        format=format,
    )


# ---------------------------------------------------------------------------
# ChainNode and ResolvedTree construction helpers
# ---------------------------------------------------------------------------


def _make_source_node(
    name: str,
    url: str = "https://github.com/org/catalog",
    sha: str = "a" * 40,
) -> ChainNode:
    """Create a top-level source ChainNode."""
    return ChainNode(kind="source", name=name, ref=None, sha=sha, url=url)


def _make_include_node(
    name: str,
    path_in_repo: str,
    sha: str,
    children: "list[ChainNode] | None" = None,
) -> ChainNode:
    """Create an include ChainNode (XML manifest path node)."""
    node = ChainNode(
        kind="include",
        name=name,
        ref=path_in_repo,
        sha=sha,
        url=None,
    )
    if children:
        node.children = children
    return node


def _make_project_node(
    name: str,
    url: str,
    sha: str,
    canonical_url: str | None = None,
) -> ChainNode:
    """Create a project ChainNode."""
    from kanon_cli.core.url import canonicalize_repo_url

    return ChainNode(
        kind="project",
        name=name,
        ref=None,
        sha=sha,
        url=url,
        canonical_url=canonical_url or canonicalize_repo_url(url),
    )


# ---------------------------------------------------------------------------
# Shared lockfile / .kanon fixture factory
# ---------------------------------------------------------------------------


def _make_minimal_kanon_file(tmp_path: pathlib.Path, source_name: str = "FOO") -> pathlib.Path:
    """Write a minimal .kanon file and return its path."""
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(
        f"GITBASE=https://github.com\n"
        f"CLAUDE_MARKETPLACES_DIR=/tmp/mkts\n"
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{source_name}_URL=https://github.com/org/catalog\n"
        f"KANON_SOURCE_{source_name}_REVISION=main\n"
        f"KANON_SOURCE_{source_name}_PATH=./foo\n"
    )
    kanon_file.chmod(0o644)
    return kanon_file


def _make_minimal_lockfile(
    project_url: str,
    project_sha: str,
    project_name: str = "baz",
    source_name: str = "FOO",
    include_entries: "list | None" = None,
) -> "Lockfile":
    """Construct a minimal Lockfile dataclass with one source and one project.

    Args:
        project_url: URL of the project to include.
        project_sha: SHA to assign to the project.
        project_name: Display name for the project.
        source_name: Name for the KANON_SOURCE_* block.
        include_entries: Optional list of IncludeEntry instances to include.

    Returns:
        A Lockfile dataclass instance.
    """
    from kanon_cli.core.lockfile import (
        CatalogBlock,
        Lockfile,
        ProjectEntry,
        SourceEntry,
    )
    from kanon_cli.core.url import canonicalize_repo_url

    return Lockfile(
        schema_version=1,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash="sha256:" + "a" * 64,
        catalog=CatalogBlock(
            source="catalog@HEAD",
            url="https://github.com/org/catalog",
            revision_spec="HEAD",
            resolved_ref="HEAD",
            resolved_sha="f" * 40,
        ),
        sources=[
            SourceEntry(
                name=source_name,
                url="https://github.com/org/catalog",
                revision_spec="main",
                resolved_ref="main",
                resolved_sha="a" * 40,
                path="./foo",
                includes=include_entries or [],
                projects=[
                    ProjectEntry(
                        name=project_name,
                        url=project_url,
                        canonical_url=canonicalize_repo_url(project_url),
                        revision_spec="main",
                        resolved_ref="main",
                        resolved_sha=project_sha,
                    )
                ],
            )
        ],
    )


def _write_lockfile_to_tmp(tmp_path: pathlib.Path, lockfile: "Lockfile") -> pathlib.Path:
    """Write a Lockfile to tmp_path/.kanon.lock and return the path."""
    from kanon_cli.core.lockfile import write_lockfile

    lock_path = tmp_path / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return lock_path


# ---------------------------------------------------------------------------
# _walk_chains unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWalkChains:
    """Tests for DFS chain enumeration."""

    def test_single_chain_direct_project(self) -> None:
        """Single source -> direct project (no include) produces one chain."""
        project = _make_project_node(
            name="baz",
            url="https://github.com/org/baz",
            sha="b" * 40,
        )
        source = _make_source_node(name="foo")
        source.children = [project]

        tree = ResolvedTree(sources=[source])
        target_canonical = project.canonical_url
        assert target_canonical is not None

        chains = _walk_chains(tree, target_canonical)
        assert len(chains) == 1
        assert chains[0][-1].name == "baz"
        assert chains[0][0].name == "foo"

    def test_single_chain_with_include(self) -> None:
        """Source -> include -> project produces one chain with three nodes."""
        project = _make_project_node(
            name="baz",
            url="https://github.com/org/baz",
            sha="b" * 40,
        )
        include = _make_include_node(
            name="bar",
            path_in_repo="repo-specs/bar.xml",
            sha="c" * 40,
            children=[project],
        )
        source = _make_source_node(name="foo")
        source.children = [include]

        tree = ResolvedTree(sources=[source])
        target_canonical = project.canonical_url
        assert target_canonical is not None

        chains = _walk_chains(tree, target_canonical)
        assert len(chains) == 1
        assert chains[0][0].name == "foo"
        assert chains[0][1].name == "bar"
        assert chains[0][2].name == "baz"

    def test_multi_chain_same_source_two_includes(self) -> None:
        """One source with two include paths both reaching the same project -> two chains."""
        sha_p = "b" * 40
        project_url = "https://github.com/org/baz"

        project1 = _make_project_node(name="baz", url=project_url, sha=sha_p)
        project2 = _make_project_node(name="baz", url=project_url, sha=sha_p)

        include_a = _make_include_node(name="path-a", path_in_repo="a.xml", sha="c" * 40, children=[project1])
        include_b = _make_include_node(name="path-b", path_in_repo="b.xml", sha="d" * 40, children=[project2])

        source = _make_source_node(name="top")
        source.children = [include_a, include_b]

        tree = ResolvedTree(sources=[source])
        target_canonical = project1.canonical_url
        assert target_canonical is not None

        chains = _walk_chains(tree, target_canonical)
        assert len(chains) == 2

    def test_multi_chain_two_top_level_sources(self) -> None:
        """Two top-level sources each reaching the same project -> two chains."""
        sha_p = "b" * 40
        project_url = "https://github.com/org/shared"

        proj1 = _make_project_node(name="shared", url=project_url, sha=sha_p)
        proj2 = _make_project_node(name="shared", url=project_url, sha=sha_p)

        source1 = _make_source_node(name="src1")
        source1.children = [proj1]

        source2 = _make_source_node(name="src2")
        source2.children = [proj2]

        tree = ResolvedTree(sources=[source1, source2])
        target_canonical = proj1.canonical_url
        assert target_canonical is not None

        chains = _walk_chains(tree, target_canonical)
        assert len(chains) == 2
        source_names = {c[0].name for c in chains}
        assert source_names == {"src1", "src2"}

    def test_not_found_returns_empty_list(self) -> None:
        """Project URL not in tree produces an empty chain list (caller raises error)."""
        project = _make_project_node(
            name="present",
            url="https://github.com/org/present",
            sha="b" * 40,
        )
        source = _make_source_node(name="foo")
        source.children = [project]

        tree = ResolvedTree(sources=[source])
        chains = _walk_chains(tree, "https://github.com/org/absent")
        assert chains == []


# ---------------------------------------------------------------------------
# _render_text unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRenderText:
    """Tests for chain-to-text formatting."""

    def test_single_chain_three_nodes(self) -> None:
        """Three-node chain renders as 'src -> include@sha -> project@sha'."""
        source = _make_source_node(name="foo")
        include = _make_include_node(name="bar", path_in_repo="repo-specs/bar.xml", sha="c" * 40)
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)
        lines = _render_text([[source, include, project]])
        assert len(lines) == 1
        line = lines[0]
        # top source name at start
        assert line.startswith("foo")
        # include reference with sha
        assert "repo-specs/bar.xml@" in line
        # project name with sha at end
        assert "baz@" + "b" * 40 in line

    def test_arrow_separated(self) -> None:
        """Nodes in a chain are separated by ' -> '."""
        source = _make_source_node(name="s1")
        project = _make_project_node(name="p1", url="https://github.com/org/p1", sha="d" * 40)
        lines = _render_text([[source, project]])
        assert " -> " in lines[0]

    def test_multiple_chains_produce_multiple_lines(self) -> None:
        """Two chains produce two output lines."""
        source1 = _make_source_node(name="src1")
        source2 = _make_source_node(name="src2")
        proj = _make_project_node(name="shared", url="https://github.com/org/shared", sha="e" * 40)
        lines = _render_text([[source1, proj], [source2, proj]])
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# _build_tree_from_lockfile unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildTreeFromLockfile:
    """Tests for lockfile-to-ResolvedTree conversion."""

    def test_builds_tree_with_direct_project(self, tmp_path: pathlib.Path) -> None:
        """Lockfile with one source and one project (no includes) builds tree correctly.

        When no includes are present, the project is a direct child of the source.
        """
        project_url = "https://github.com/org/baz"
        project_sha = "b" * 40

        lockfile = _make_minimal_lockfile(
            project_url=project_url,
            project_sha=project_sha,
        )
        lock_path = _write_lockfile_to_tmp(tmp_path, lockfile)

        from kanon_cli.core.lockfile import read_lockfile

        loaded = read_lockfile(lock_path)
        tree = _build_tree_from_lockfile(loaded)

        assert len(tree.sources) == 1
        source_node = tree.sources[0]
        assert source_node.name == "FOO"
        project_nodes = [c for c in source_node.children if c.kind == "project"]
        assert len(project_nodes) == 1
        assert project_nodes[0].sha == project_sha

    def test_builds_tree_with_include_chain(self, tmp_path: pathlib.Path) -> None:
        """Lockfile with include builds a tree where project is under the include.

        When includes are present, projects are placed under the leaf include nodes
        so the chain output contains the include-node segment.
        """
        from kanon_cli.core.lockfile import IncludeEntry

        project_url = "https://github.com/org/child"
        project_sha = "b" * 40
        include_sha = "c" * 40

        include = IncludeEntry(
            name="bar",
            path_in_repo="repo-specs/bar.xml",
            url="https://github.com/org/catalog",
            resolved_sha=include_sha,
            includes=[],
        )

        lockfile = _make_minimal_lockfile(
            project_url=project_url,
            project_sha=project_sha,
            project_name="child",
            include_entries=[include],
        )
        lock_path = _write_lockfile_to_tmp(tmp_path, lockfile)

        from kanon_cli.core.lockfile import read_lockfile

        loaded = read_lockfile(lock_path)
        tree = _build_tree_from_lockfile(loaded)

        assert len(tree.sources) == 1
        source_node = tree.sources[0]

        # Source's direct children should be include nodes only
        include_nodes = [c for c in source_node.children if c.kind == "include"]
        assert len(include_nodes) == 1
        assert include_nodes[0].sha == include_sha

        # No direct project children on the source (project is under the include)
        direct_project_nodes = [c for c in source_node.children if c.kind == "project"]
        assert len(direct_project_nodes) == 0

        # Project should be under the include node (leaf include placement)
        include_node = include_nodes[0]
        child_projects = [c for c in include_node.children if c.kind == "project"]
        assert len(child_projects) == 1
        assert child_projects[0].sha == project_sha

    def test_walk_chains_produces_include_segment(self, tmp_path: pathlib.Path) -> None:
        """_walk_chains on a lockfile-built tree returns a chain with the include node.

        This verifies AC-CYCLE-001: the chain from lockfile contains the include node.
        """
        from kanon_cli.core.lockfile import IncludeEntry, read_lockfile
        from kanon_cli.core.url import canonicalize_repo_url

        project_url = "https://github.com/org/child"
        project_sha = "b" * 40
        include_sha = "c" * 40

        include = IncludeEntry(
            name="bar",
            path_in_repo="repo-specs/bar.xml",
            url="https://github.com/org/catalog",
            resolved_sha=include_sha,
            includes=[],
        )
        lockfile = _make_minimal_lockfile(
            project_url=project_url,
            project_sha=project_sha,
            project_name="child",
            include_entries=[include],
        )
        lock_path = _write_lockfile_to_tmp(tmp_path, lockfile)
        loaded = read_lockfile(lock_path)
        tree = _build_tree_from_lockfile(loaded)

        target = canonicalize_repo_url(project_url)
        chains = _walk_chains(tree, target)
        assert len(chains) == 1

        chain = chains[0]
        # Chain: source -> include -> project
        assert len(chain) == 3
        assert chain[0].kind == "source"
        assert chain[1].kind == "include"
        assert chain[1].sha == include_sha
        assert chain[2].kind == "project"
        assert chain[2].sha == project_sha


# ---------------------------------------------------------------------------
# URL canonicalization equivalence tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "arg_url, project_url",
    [
        # SCP shorthand vs https
        ("git@github.com:org/repo.git", "https://github.com/org/repo"),
        # Trailing slash normalization
        ("https://github.com/org/repo/", "https://github.com/org/repo"),
        # .git suffix normalization
        ("https://github.com/org/repo.git", "https://github.com/org/repo"),
        # ssh:// scheme
        ("ssh://github.com/org/repo.git", "https://github.com/org/repo"),
        # Both with .git
        ("git@github.com:org/repo.git", "https://github.com/org/repo.git"),
    ],
)
class TestUrlCanonicalizationEquivalence:
    def test_url_canonicalization_match(self, arg_url: str, project_url: str) -> None:
        """arg_url and project_url canonicalize to the same value and match in walk."""
        from kanon_cli.core.url import canonicalize_repo_url

        sha_p = "b" * 40
        project = _make_project_node(name="baz", url=project_url, sha=sha_p)
        source = _make_source_node(name="foo")
        source.children = [project]

        tree = ResolvedTree(sources=[source])
        target_canonical = canonicalize_repo_url(arg_url)
        chains = _walk_chains(tree, target_canonical)
        assert len(chains) == 1, (
            f"Expected 1 chain for arg_url={arg_url!r} matching project_url={project_url!r}, got {len(chains)}"
        )


# ---------------------------------------------------------------------------
# run() integration-style unit tests (filesystem + lockfile interaction)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunLockfilePresent:
    """Tests for run() with a lockfile present (skips live-resolve)."""

    def test_lockfile_present_skips_live_resolve(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """When .kanon.lock is present, run() must NOT call live-resolve."""
        project_url = "https://github.com/org/baz"
        project_sha = "b" * 40

        kanon_file = _make_minimal_kanon_file(tmp_path)
        lockfile = _make_minimal_lockfile(project_url=project_url, project_sha=project_sha)
        lock_file = _write_lockfile_to_tmp(tmp_path, lockfile)

        args = _make_args(
            target=project_url,
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
            # catalog_source is set but must NOT be called when lockfile present
            catalog_source="file:///fake/catalog@HEAD",
        )

        with patch("kanon_cli.commands.why._live_resolve_tree") as mock_live:
            exit_code = run(args)

        # Live-resolve must never be called when lockfile is present
        mock_live.assert_not_called()
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "baz@" + project_sha in captured.out

    def test_run_prints_chain_from_lockfile(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """run() with lockfile prints the chain in arrow-separated text format."""
        from kanon_cli.core.lockfile import IncludeEntry

        project_url = "https://github.com/org/child"
        project_sha = "b" * 40
        include_sha = "c" * 40

        include = IncludeEntry(
            name="bar",
            path_in_repo="repo-specs/bar.xml",
            url="https://github.com/org/catalog",
            resolved_sha=include_sha,
            includes=[],
        )
        kanon_file = _make_minimal_kanon_file(tmp_path)
        lockfile = _make_minimal_lockfile(
            project_url=project_url,
            project_sha=project_sha,
            project_name="child",
            include_entries=[include],
        )
        lock_file = _write_lockfile_to_tmp(tmp_path, lockfile)

        args = _make_args(
            target=project_url,
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
            catalog_source=None,
        )

        exit_code = run(args)
        assert exit_code == 0

        captured = capsys.readouterr()
        # Chain includes source name, include ref (with sha), and project sha
        assert "FOO" in captured.out
        assert " -> " in captured.out
        assert f"repo-specs/bar.xml@{include_sha}" in captured.out
        assert "child@" + project_sha in captured.out


@pytest.mark.unit
class TestRunErrors:
    """Tests for hard-error conditions in run()."""

    def test_missing_kanon_file_exits_nonzero(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """Missing .kanon file produces a hard error with non-zero exit."""
        args = _make_args(
            target="https://github.com/org/baz",
            kanon_file=str(tmp_path / ".kanon"),
        )
        with pytest.raises(SystemExit) as exc_info:
            run(args)
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower() or ".kanon" in captured.err

    def test_target_not_in_tree_exits_nonzero(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """Target URL not in resolved tree -> hard error with non-zero exit."""
        project_url = "https://github.com/org/present"

        kanon_file = _make_minimal_kanon_file(tmp_path)
        lockfile = _make_minimal_lockfile(project_url=project_url, project_sha="b" * 40, project_name="present")
        lock_file = _write_lockfile_to_tmp(tmp_path, lockfile)

        absent_url = "https://github.com/org/absent"
        args = _make_args(
            target=absent_url,
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "not found" in captured.err
        assert absent_url in captured.err

    def test_explicit_lock_file_not_found_exits_nonzero(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Explicit --lock-file pointing to a nonexistent path -> hard error, no fallback."""
        kanon_file = _make_minimal_kanon_file(tmp_path)
        nonexistent_lock = str(tmp_path / "does-not-exist.lock")

        args = _make_args(
            target="https://github.com/org/baz",
            kanon_file=str(kanon_file),
            lock_file=nonexistent_lock,
            catalog_source="file:///fake/catalog@HEAD",
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "ERROR: lock file not found:" in captured.err
        assert nonexistent_lock in captured.err

    def test_missing_catalog_source_when_no_lockfile_exits_nonzero(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """No lockfile + no catalog source -> hard error with non-zero exit."""
        kanon_file = _make_minimal_kanon_file(tmp_path)

        # No lock file, no catalog source
        args = _make_args(
            target="https://github.com/org/baz",
            kanon_file=str(kanon_file),
            lock_file=None,
            catalog_source=None,
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "catalog" in captured.err.lower()

    def test_invalid_target_url_exits_nonzero(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """An invalid target URL (e.g. with a query string) -> hard error with non-zero exit."""
        project_url = "https://github.com/org/present"

        kanon_file = _make_minimal_kanon_file(tmp_path)
        lockfile = _make_minimal_lockfile(project_url=project_url, project_sha="b" * 40, project_name="present")
        lock_file = _write_lockfile_to_tmp(tmp_path, lockfile)

        # An invalid URL that will cause canonicalize_repo_url to raise ValueError
        invalid_url = "https://github.com/org/repo?query=param"
        args = _make_args(
            target=invalid_url,
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)
        assert exc_info.value.code != 0

    def test_with_catalog_source_and_no_lockfile_calls_live_resolve(self, tmp_path: pathlib.Path) -> None:
        """With catalog source and no lockfile, run() calls _live_resolve_tree."""
        kanon_file = _make_minimal_kanon_file(tmp_path)

        # No lockfile -- live-resolve path
        args = _make_args(
            target="https://github.com/org/baz",
            kanon_file=str(kanon_file),
            lock_file=None,
            catalog_source="file:///fake/catalog@HEAD",
        )

        with patch("kanon_cli.commands.why._live_resolve_tree") as mock_live:
            project = ChainNode(
                kind="project",
                name="baz",
                ref=None,
                sha="b" * 40,
                url="https://github.com/org/baz",
                canonical_url="https://github.com/org/baz",
            )
            source = ChainNode(
                kind="source",
                name="FOO",
                ref=None,
                sha="a" * 40,
                url="https://github.com/org/catalog",
                children=[project],
            )
            mock_live.return_value = ResolvedTree(sources=[source])

            exit_code = run(args)

        mock_live.assert_called_once()
        assert exit_code == 0

    def test_live_resolve_not_implemented_produces_clean_error(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """When _live_resolve_tree raises NotImplementedError, run() exits with clean message."""
        kanon_file = _make_minimal_kanon_file(tmp_path)

        args = _make_args(
            target="https://github.com/org/baz",
            kanon_file=str(kanon_file),
            lock_file=None,
            catalog_source="file:///fake/catalog@HEAD",
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        # Must be a clean error message, not a Python traceback
        assert "ERROR:" in captured.err
        assert "Live-resolution is not yet implemented" in captured.err
        assert "kanon install" in captured.err
        # Must NOT expose a Python traceback
        assert "Traceback" not in captured.err
        assert "NotImplementedError" not in captured.err


@pytest.mark.unit
class TestIncludeEntryToNode:
    """Tests for _include_entry_to_node with nested includes."""

    def test_nested_include_converted_to_child(self) -> None:
        """An IncludeEntry with a nested include produces a ChainNode with a child."""
        from kanon_cli.core.lockfile import IncludeEntry

        child_entry = IncludeEntry(
            name="child",
            path_in_repo="child.xml",
            url="https://github.com/org/catalog",
            resolved_sha="c" * 40,
            includes=[],
        )
        parent_entry = IncludeEntry(
            name="parent",
            path_in_repo="parent.xml",
            url="https://github.com/org/catalog",
            resolved_sha="p" * 40,
            includes=[child_entry],
        )

        node = _include_entry_to_node(parent_entry)

        assert node.name == "parent"
        assert len(node.children) == 1
        assert node.children[0].name == "child"
        assert node.children[0].sha == "c" * 40


@pytest.mark.unit
class TestCollectLeafIncludeNodes:
    """Tests for _collect_leaf_include_nodes -- leaf-node extraction from include subtrees."""

    def test_flat_includes_are_all_leaves(self) -> None:
        """Two sibling include nodes with no nested includes are both leaves."""
        inc_a = _make_include_node(name="a", path_in_repo="a.xml", sha="a" * 40)
        inc_b = _make_include_node(name="b", path_in_repo="b.xml", sha="b" * 40)

        leaves = _collect_leaf_include_nodes([inc_a, inc_b])

        assert len(leaves) == 2
        leaf_names = {n.name for n in leaves}
        assert leaf_names == {"a", "b"}

    def test_two_level_deep_nesting_returns_only_child(self) -> None:
        """A parent include that has a child include returns only the child (deepest leaf).

        This covers the recursive branch at line ~126 in why.py where nested_includes
        is non-empty and _collect_leaf_include_nodes recurses into nested_includes.
        """
        child = _make_include_node(name="child", path_in_repo="child.xml", sha="c" * 40)
        parent = _make_include_node(
            name="parent",
            path_in_repo="parent.xml",
            sha="p" * 40,
            children=[child],
        )

        leaves = _collect_leaf_include_nodes([parent])

        # parent has a child include -- it is NOT a leaf; only child is returned
        assert len(leaves) == 1
        assert leaves[0].name == "child"

    def test_three_level_deep_nesting_returns_deepest_leaf(self) -> None:
        """Three levels: grandparent -> parent -> child; only child is the leaf."""
        grandchild = _make_include_node(name="gc", path_in_repo="gc.xml", sha="g" * 40)
        parent = _make_include_node(
            name="parent",
            path_in_repo="parent.xml",
            sha="p" * 40,
            children=[grandchild],
        )
        grandparent = _make_include_node(
            name="gp",
            path_in_repo="gp.xml",
            sha="r" * 40,
            children=[parent],
        )

        leaves = _collect_leaf_include_nodes([grandparent])

        assert len(leaves) == 1
        assert leaves[0].name == "gc"

    def test_mixed_flat_and_nested_returns_correct_leaves(self) -> None:
        """One flat include and one parent-child pair returns two leaves (flat + child)."""
        flat = _make_include_node(name="flat", path_in_repo="flat.xml", sha="f" * 40)
        child = _make_include_node(name="child", path_in_repo="child.xml", sha="c" * 40)
        nested_parent = _make_include_node(name="np", path_in_repo="np.xml", sha="n" * 40, children=[child])

        leaves = _collect_leaf_include_nodes([flat, nested_parent])

        assert len(leaves) == 2
        leaf_names = {n.name for n in leaves}
        assert leaf_names == {"flat", "child"}


@pytest.mark.unit
class TestLiveResolveTree:
    """Tests for _live_resolve_tree -- verifies it raises NotImplementedError in T1."""

    def test_raises_not_implemented_error(self, tmp_path: pathlib.Path) -> None:
        """_live_resolve_tree raises NotImplementedError in T1 (live-resolve not yet implemented)."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("# placeholder\n")

        with pytest.raises(NotImplementedError):
            _live_resolve_tree(kanon_file, "file:///fake/catalog@HEAD")


# ---------------------------------------------------------------------------
# Tests for add_help=True on the 'why' subparser
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWhySubparserHelp:
    """The 'why' subparser has add_help=True and accepts '-h'."""

    def test_why_short_dash_h_exits_0(self) -> None:
        """kanon why -h exits 0 (add_help=True on the why subparser)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["why", "-h"])
        assert exc_info.value.code == 0

    def test_why_subparser_has_add_help_true(self) -> None:
        """The 'why' subparser has add_help=True set explicitly."""
        from kanon_cli.commands.why import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        why_parser = subparsers.choices["why"]
        assert why_parser.add_help is True, "why subparser must have add_help=True so '-h' is accepted"
