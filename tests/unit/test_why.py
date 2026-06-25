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
- Live-resolve raises LiveResolveError -> run() converts to clean error message.
- _live_resolve_tree returns ResolvedTree with source ChainNodes on success.
- _live_resolve_tree raises LiveResolveError when _resolve_ref_to_sha fails.
- _live_resolve_tree raises LiveResolveError when _enforce_remote_url_policy rejects URL.

AC-TEST-001, AC-TEST-002, AC-FUNC-005
"""

import argparse
import pathlib
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from kanon_cli.commands.why import (
    _build_project_nodes_from_xml,
    _build_tree_from_lockfile,
    _collect_leaf_include_nodes,
    _include_entry_to_node,
    _live_resolve_tree,
    _match_by_url,
    _match_by_xml_path,
    _substitute_fetch_url,
    _walk_chains,
    _render_text,
    run,
    ChainNode,
    LiveResolveError,
    ResolvedTree,
)

if TYPE_CHECKING:
    from kanon_cli.core.lockfile import Lockfile


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


def _make_minimal_kanon_file(tmp_path: pathlib.Path, source_name: str = "FOO") -> pathlib.Path:
    """Write a minimal .kanon file and return its path."""
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(
        f"GITBASE=https://github.com\n"
        f"CLAUDE_MARKETPLACES_DIR=/tmp/mkts\n"
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{source_name}_URL=https://github.com/org/catalog\n"
        f"KANON_SOURCE_{source_name}_REF=main\n"
        f"KANON_SOURCE_{source_name}_PATH=./foo\n"
        f"KANON_SOURCE_{source_name}_NAME={source_name}\n"
        f"KANON_SOURCE_{source_name}_GITBASE=https://github.com/org\n"
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
        CURRENT_SCHEMA_VERSION,
        Lockfile,
        ProjectEntry,
        SourceEntry,
    )
    from kanon_cli.core.url import canonicalize_repo_url

    return Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash="sha256:" + "a" * 64,
        sources=[
            SourceEntry(
                alias=source_name,
                name=source_name,
                url="https://github.com/org/catalog",
                ref_spec="main",
                resolved_ref="main",
                resolved_sha="a" * 40,
                path="./foo",
                includes=include_entries or [],
                projects=[
                    ProjectEntry(
                        name=project_name,
                        url=project_url,
                        canonical_url=canonicalize_repo_url(project_url),
                        ref_spec="main",
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

        assert line.startswith("foo")

        assert "repo-specs/bar.xml@" in line

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

        include_nodes = [c for c in source_node.children if c.kind == "include"]
        assert len(include_nodes) == 1
        assert include_nodes[0].sha == include_sha

        direct_project_nodes = [c for c in source_node.children if c.kind == "project"]
        assert len(direct_project_nodes) == 0

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

        assert len(chain) == 3
        assert chain[0].kind == "source"
        assert chain[1].kind == "include"
        assert chain[1].sha == include_sha
        assert chain[2].kind == "project"
        assert chain[2].sha == project_sha


@pytest.mark.unit
@pytest.mark.parametrize(
    "arg_url, project_url",
    [
        ("git@github.com:org/repo.git", "https://github.com/org/repo"),
        ("https://github.com/org/repo/", "https://github.com/org/repo"),
        ("https://github.com/org/repo.git", "https://github.com/org/repo"),
        ("ssh://github.com/org/repo.git", "https://github.com/org/repo"),
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
            catalog_source="file:///fake/catalog@HEAD",
        )

        with patch("kanon_cli.commands.why._live_resolve_tree") as mock_live:
            exit_code = run(args)

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

    def test_live_resolve_error_produces_clean_error(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """When _live_resolve_tree raises LiveResolveError, run() exits with clean structured message.

        Replaces test_live_resolve_not_implemented_produces_clean_error (AC-FIX-002).
        Monkeypatches _live_resolve_tree directly so no real git calls are made.
        """
        kanon_file = _make_minimal_kanon_file(tmp_path)

        args = _make_args(
            target="https://github.com/org/baz",
            kanon_file=str(kanon_file),
            lock_file=None,
            catalog_source="file:///fake/catalog@HEAD",
        )

        with patch("kanon_cli.commands.why._live_resolve_tree") as mock_live:
            mock_live.side_effect = LiveResolveError(
                "FOO",
                "ref 'main' not found in remote https://github.com/org/catalog",
            )
            with pytest.raises(SystemExit) as exc_info:
                run(args)

        assert exc_info.value.code != 0
        captured = capsys.readouterr()

        assert "ERROR: cannot resolve" in captured.err
        assert "FOO" in captured.err

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
    """Tests for _live_resolve_tree -- verifies LiveResolveError-based implementation.

    AC-FIX-001, AC-FIX-003, AC-FIX-004
    """

    def _make_kanonenv_for_source(
        self,
        source_name: str = "FOO",
        url: str = "https://github.com/org/catalog",
        revision: str = "main",
    ) -> dict:
        """Build a minimal parse_kanonenv return dict for a single source."""
        return {
            "KANON_SOURCES": [source_name],
            "sources": {
                source_name: {
                    "url": url,
                    "ref": revision,
                    "path": "./foo",
                    "name": source_name,
                    "marketplace": False,
                    "env": {"GITBASE": "https://github.com/org"},
                }
            },
            "globals": {},
        }

    def test_raises_live_resolve_error_when_ref_resolution_fails(self, tmp_path: pathlib.Path) -> None:
        """_live_resolve_tree raises LiveResolveError when _resolve_ref_to_sha raises ValueError.

        Replaces test_raises_not_implemented_error (AC-FIX-001).
        Monkeypatches parse_kanonenv and _resolve_ref_to_sha; no real git calls.
        """
        kanon_file = _make_minimal_kanon_file(tmp_path)
        fake_kanonenv = self._make_kanonenv_for_source()

        with (
            patch("kanon_cli.commands.why.parse_kanonenv", return_value=fake_kanonenv),
            patch("kanon_cli.commands.why._enforce_remote_url_policy"),
            patch(
                "kanon_cli.commands.why._resolve_ref_to_sha",
                side_effect=ValueError("ref 'main' not found"),
            ),
        ):
            with pytest.raises(LiveResolveError) as exc_info:
                _live_resolve_tree(kanon_file, "file:///fake/catalog@HEAD")

        err = exc_info.value
        assert err.name == "FOO"
        assert "cannot resolve" in str(err)
        assert "Remediation" in str(err)

    @pytest.mark.parametrize(
        "source_name, url, sha",
        [
            ("FOO", "https://github.com/org/catalog", "a" * 40),
            ("BAR", "https://github.com/org/other", "b" * 40),
        ],
    )
    def test_returns_resolved_tree_with_source_chain_nodes(
        self,
        tmp_path: pathlib.Path,
        source_name: str,
        url: str,
        sha: str,
    ) -> None:
        """_live_resolve_tree returns a ResolvedTree with source ChainNodes on success.

        AC-FIX-003: Parametrized over different source names, URLs and SHAs.
        Node kind must be 'source', SHA and URL must match the resolved values.

        _resolve_ref_to_sha and _clone_source_repo are patched at their use
        site in kanon_cli.commands.why so no real network access occurs.
        _populate_source_children_from_manifest is patched as the manifest-walk
        boundary; the source-node structure is asserted from the mocked SHA and
        URL values set before that call.
        """
        from kanon_cli.core.install import _RefResolution

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name=source_name)
        fake_kanonenv = self._make_kanonenv_for_source(source_name=source_name, url=url)

        with (
            patch("kanon_cli.commands.why.parse_kanonenv", return_value=fake_kanonenv),
            patch("kanon_cli.commands.why._enforce_remote_url_policy"),
            patch(
                "kanon_cli.commands.why._resolve_ref_to_sha",
                return_value=_RefResolution(sha=sha, resolved_ref="main"),
            ),
            patch("kanon_cli.commands.why._clone_source_repo"),
            patch("kanon_cli.commands.why._populate_source_children_from_manifest"),
        ):
            tree = _live_resolve_tree(kanon_file, "file:///fake/catalog@HEAD")

        assert len(tree.sources) == 1
        node = tree.sources[0]
        assert node.kind == "source"
        assert node.name == source_name
        assert node.sha == sha
        assert node.url == url

    def test_raises_live_resolve_error_when_url_policy_rejects(self, tmp_path: pathlib.Path) -> None:
        """_live_resolve_tree raises LiveResolveError when _enforce_remote_url_policy raises.

        AC-FIX-004: Verifies that policy violations are wrapped as LiveResolveError.
        """
        from kanon_cli.core.remote_url import InsecureRemoteUrlError

        kanon_file = _make_minimal_kanon_file(tmp_path)
        fake_kanonenv = self._make_kanonenv_for_source(url="http://insecure.example.com/org/catalog")

        with (
            patch("kanon_cli.commands.why.parse_kanonenv", return_value=fake_kanonenv),
            patch(
                "kanon_cli.commands.why._enforce_remote_url_policy",
                side_effect=InsecureRemoteUrlError(
                    "http://insecure.example.com/org/catalog",
                    "FOO",
                    "FOO",
                ),
            ),
        ):
            with pytest.raises(LiveResolveError) as exc_info:
                _live_resolve_tree(kanon_file, "file:///fake/catalog@HEAD")

        err = exc_info.value
        assert err.name == "FOO"
        assert "cannot resolve" in str(err)


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


@pytest.mark.unit
class TestSubstituteFetchUrl:
    """Unit tests for ``_substitute_fetch_url`` placeholder substitution helper.

    Covers: substitution via globals_map, passthrough for concrete URLs,
    and fail-fast on unresolved placeholders (AC-9).
    """

    def test_concrete_url_returned_unchanged(self) -> None:
        """A URL with no ``${...}`` patterns is returned without modification."""
        url = "https://github.com/org"
        result = _substitute_fetch_url(
            url,
            globals_map={"GITBASE": "file:///tmp/pkgs"},
            source_name="SRC",
            kanon_file=pathlib.Path(".kanon"),
        )
        assert result == url

    def test_placeholder_substituted_from_globals(self) -> None:
        """``${GITBASE}`` is replaced by the GITBASE value in globals_map."""
        result = _substitute_fetch_url(
            "${GITBASE}",
            globals_map={"GITBASE": "file:///tmp/pkgs"},
            source_name="SRC",
            kanon_file=pathlib.Path(".kanon"),
        )
        assert result == "file:///tmp/pkgs"

    def test_placeholder_in_composite_url_substituted(self) -> None:
        """``${GITBASE}/subdir`` resolves to the substituted value with the suffix."""
        result = _substitute_fetch_url(
            "${GITBASE}/org",
            globals_map={"GITBASE": "https://github.com"},
            source_name="SRC",
            kanon_file=pathlib.Path(".kanon"),
        )
        assert result == "https://github.com/org"

    def test_unresolved_placeholder_raises_live_resolve_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A ``${VAR}`` placeholder with no matching global raises LiveResolveError.

        The error message names the missing variable and the .kanon file path
        (AC-9: fail fast on missing global).
        """
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_SOURCE_SRC_URL=file:///fake\n")

        with pytest.raises(LiveResolveError) as exc_info:
            _substitute_fetch_url(
                "${MISSING_VAR}",
                globals_map={},
                source_name="SRC",
                kanon_file=kanon_file,
            )

        err_msg = str(exc_info.value)
        assert "MISSING_VAR" in err_msg, f"Error must name the missing variable; got: {err_msg!r}"
        assert str(kanon_file) in err_msg, f"Error must name the .kanon path; got: {err_msg!r}"

    def test_env_not_mutated_after_substitution(self) -> None:
        """Process environment is unchanged after _substitute_fetch_url returns.

        Verifies that the temporary env injection does not leak into os.environ.
        """
        import os

        key = "KANON_TEST_GITBASE_GUARD_9812"
        assert key not in os.environ, f"Test prereq failed: {key!r} already in env"

        _substitute_fetch_url(
            f"${{{key}}}",
            globals_map={key: "file:///tmp/guard"},
            source_name="SRC",
            kanon_file=pathlib.Path(".kanon"),
        )

        assert key not in os.environ, f"_substitute_fetch_url leaked {key!r} into os.environ after returning"

    def test_env_not_mutated_when_error_raised(self) -> None:
        """Process environment is restored even when a LiveResolveError is raised."""
        import os

        env_var_name = "KANON_TEST_PRESENT_VAR"
        sentinel = "original_value"
        os.environ[env_var_name] = sentinel

        try:
            with pytest.raises(LiveResolveError):
                _substitute_fetch_url(
                    "${UNRESOLVED_X}",
                    globals_map={env_var_name: "overwritten"},
                    source_name="SRC",
                    kanon_file=pathlib.Path(".kanon"),
                )

            assert os.environ.get(env_var_name) == sentinel, (
                f"_substitute_fetch_url did not restore {env_var_name!r} to {sentinel!r} "
                f"after raising LiveResolveError; got {os.environ.get(env_var_name)!r}"
            )
        finally:
            os.environ.pop(env_var_name, None)


@pytest.mark.unit
class TestBuildProjectNodesFromXmlPlaceholder:
    """Unit tests for ``_build_project_nodes_from_xml`` with placeholder remote fetch.

    Covers:
    - NON-EMPTY result for a ``${GITBASE}`` remote when GITBASE is supplied (AC-8).
    - EMPTY result (skip) for a remote that is genuinely unresolvable after
      substitution (the URL survives substitution but fails canonicalization) (AC-8).
    - Fail-fast on ``${VAR}`` with no matching global (AC-9).
    """

    def _write_manifest_xml(
        self,
        parent: pathlib.Path,
        remote_fetch: str,
        project_name: str = "myproject",
        remote_name: str = "origin",
    ) -> pathlib.Path:
        """Write a minimal manifest XML to a temp directory and return its path."""
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="{remote_name}" fetch="{remote_fetch}" />\n'
            f'  <project remote="{remote_name}" name="{project_name}" path="{project_name}" />\n'
            "</manifest>\n"
        )
        xml_path = parent / "default.xml"
        xml_path.write_text(xml_content)
        return xml_path

    def test_returns_non_empty_for_placeholder_when_gitbase_supplied(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """_build_project_nodes_from_xml returns a non-empty list for a ``${GITBASE}``
        remote when GITBASE is declared in globals_map.

        The returned ChainNode must have kind='project' and a canonical_url that
        incorporates the substituted GITBASE value (AC-8).
        """
        pkgs_dir = tmp_path / "pkgs"
        pkgs_dir.mkdir()
        manifest_repo = tmp_path / "repo"
        manifest_repo.mkdir()

        xml_path = self._write_manifest_xml(manifest_repo, remote_fetch="${GITBASE}")

        nodes = _build_project_nodes_from_xml(
            manifest_xml_path=xml_path,
            manifest_repo=manifest_repo,
            source_sha="a" * 40,
            source_name="SRC",
            globals_map={"GITBASE": pkgs_dir.as_uri()},
            kanon_file=tmp_path / ".kanon",
        )

        assert len(nodes) == 1, f"Expected 1 project node, got {len(nodes)}: {nodes}"
        node = nodes[0]
        assert node.kind == "project"
        assert node.name == "myproject"
        assert node.canonical_url is not None
        assert pkgs_dir.name in node.url or pkgs_dir.as_uri() in node.url

    def test_returns_empty_for_genuinely_unresolvable_remote_after_substitution(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """_build_project_nodes_from_xml returns an empty list when the remote fetch
        resolves to a non-URL value that canonicalize_repo_url cannot handle.

        This covers the ``except ValueError: continue`` branch that skips projects
        whose resolved fetch URL is syntactically invalid (AC-8: EMPTY for
        genuinely unresolvable).
        """
        manifest_repo = tmp_path / "repo"
        manifest_repo.mkdir()

        xml_path = self._write_manifest_xml(manifest_repo, remote_fetch="not-a-valid-url::??")

        nodes = _build_project_nodes_from_xml(
            manifest_xml_path=xml_path,
            manifest_repo=manifest_repo,
            source_sha="a" * 40,
            source_name="SRC",
            globals_map={},
            kanon_file=tmp_path / ".kanon",
        )

        assert nodes == [], f"Expected empty list for unresolvable remote, got {nodes}"

    def test_raises_live_resolve_error_when_placeholder_has_no_matching_global(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """_build_project_nodes_from_xml raises LiveResolveError when a ``${VAR}``
        placeholder has no matching entry in globals_map.

        The error message must name the missing variable and the .kanon file
        path (AC-9).
        """
        manifest_repo = tmp_path / "repo"
        manifest_repo.mkdir()
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_SOURCE_SRC_URL=file:///fake\n")

        xml_path = self._write_manifest_xml(manifest_repo, remote_fetch="${UNDECLARED_VAR}")

        with pytest.raises(LiveResolveError) as exc_info:
            _build_project_nodes_from_xml(
                manifest_xml_path=xml_path,
                manifest_repo=manifest_repo,
                source_sha="a" * 40,
                source_name="SRC",
                globals_map={},
                kanon_file=kanon_file,
            )

        err_msg = str(exc_info.value)
        assert "UNDECLARED_VAR" in err_msg, f"Error must name the missing variable; got: {err_msg!r}"
        assert str(kanon_file) in err_msg, f"Error must name the .kanon path; got: {err_msg!r}"


@pytest.mark.unit
class TestMatchByUrlSourceNode:
    """Unit tests for ``_match_by_url`` source-node URL matching.

    Covers: source node matched by its URL; project nodes still matched
    as before; no match when URL differs.
    """

    def test_source_node_matched_by_url(self) -> None:
        """_match_by_url returns the source node when the argument matches source.url."""
        source = ChainNode(
            kind="source",
            name="mysource",
            ref=None,
            sha="a" * 40,
            url="https://github.com/org/catalog",
        )
        tree = ResolvedTree(sources=[source])

        result = _match_by_url(tree, "https://github.com/org/catalog")

        assert len(result) == 1
        assert result[0] is source

    def test_source_node_not_matched_when_url_differs(self) -> None:
        """_match_by_url returns an empty list when the argument URL differs from source.url."""
        source = ChainNode(
            kind="source",
            name="mysource",
            ref=None,
            sha="a" * 40,
            url="https://github.com/org/catalog",
        )
        tree = ResolvedTree(sources=[source])

        result = _match_by_url(tree, "https://github.com/org/other")

        assert result == []

    def test_project_node_still_matched_by_url(self) -> None:
        """_match_by_url still matches project nodes correctly after source-node support added."""
        from kanon_cli.core.url import canonicalize_repo_url

        project_url = "https://github.com/org/myproject"
        canonical = canonicalize_repo_url(project_url)
        project = ChainNode(
            kind="project",
            name="myproject",
            ref=None,
            sha="b" * 40,
            url=project_url,
            canonical_url=canonical,
        )
        source = ChainNode(
            kind="source",
            name="mysource",
            ref=None,
            sha="a" * 40,
            url="https://github.com/org/catalog",
        )
        source.children.append(project)
        tree = ResolvedTree(sources=[source])

        result = _match_by_url(tree, project_url)

        assert len(result) == 1
        assert result[0] is project


@pytest.mark.unit
class TestMatchByXmlPathSourceNode:
    """Unit tests for ``_match_by_xml_path`` source root-manifest path matching.

    Covers: source node matched by its root manifest path (``node.ref``);
    include nodes still matched; no match when path differs.
    """

    def test_source_node_matched_by_manifest_path(self) -> None:
        """_match_by_xml_path returns the source node when ``node.ref`` matches the argument."""
        source = ChainNode(
            kind="source",
            name="mysource",
            ref="repo-specs/mysource-marketplace.xml",
            sha="a" * 40,
            url="https://github.com/org/catalog",
        )
        tree = ResolvedTree(sources=[source])

        result = _match_by_xml_path(tree, "repo-specs/mysource-marketplace.xml")

        assert len(result) == 1
        assert result[0] is source

    def test_source_node_not_matched_when_path_differs(self) -> None:
        """_match_by_xml_path returns an empty list when the argument path differs."""
        source = ChainNode(
            kind="source",
            name="mysource",
            ref="repo-specs/mysource-marketplace.xml",
            sha="a" * 40,
            url="https://github.com/org/catalog",
        )
        tree = ResolvedTree(sources=[source])

        result = _match_by_xml_path(tree, "repo-specs/other.xml")

        assert result == []

    def test_include_node_still_matched(self) -> None:
        """_match_by_xml_path still matches include nodes correctly."""
        source = ChainNode(
            kind="source",
            name="mysource",
            ref=None,
            sha="a" * 40,
            url=None,
        )
        include = ChainNode(
            kind="include",
            name="inc",
            ref="repo-specs/extra.xml",
            sha="b" * 40,
            url=None,
        )
        source.children.append(include)
        tree = ResolvedTree(sources=[source])

        result = _match_by_xml_path(tree, "repo-specs/extra.xml")

        assert len(result) == 1
        assert result[0] is include
