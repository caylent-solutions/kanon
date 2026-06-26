"""Unit tests for 'kanon why --format json' output.

Covers:
- (a) Single-chain tree -> JSON array with one chain (list of 3 nodes for source/include/project).
- (b) Multi-chain tree -> array length matches chain count.
- (c) Each node object has exactly the five keys: kind, name, ref, sha, url.
- (d) 'kind' values are exactly one of {source, include, project}.
- (e) 'url' field is the canonicalized URL (not raw form); nodes with no URL serialize null.
- (f) Optional 'ref' correctly null when absent (source nodes and project nodes).
- (g) JSON output well-formed (round-trips through json.loads).
- (h) Env-var KANON_WHY_FORMAT=json selects JSON when --format not passed explicitly.
- (i) CLI --format json overrides env KANON_WHY_FORMAT=text.
- (j) Not-found and ambiguity errors emit plain-text to stderr regardless of format.
- (k) Full 40-char SHA in every node.

AC-TEST-001
"""

from __future__ import annotations

import argparse
import json
import pathlib

import pytest

from kanon_cli.commands.why import (
    ChainNode,
    ResolvedTree,
    _build_why_payload,
    _render_json,
    run,
)


def _make_args(
    target: str,
    kanon_file: str = "/fake/.kanon",
    lock_file: str | None = None,
    catalog_source: str | None = "file:///fake/catalog@HEAD",
    fmt: str = "json",
) -> argparse.Namespace:
    """Build a minimal argparse Namespace matching the why subcommand signature."""
    return argparse.Namespace(
        target=target,
        kanon_file=kanon_file,
        lock_file=lock_file,
        catalog_source=catalog_source,
        format=fmt,
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
) -> "object":
    """Construct a minimal Lockfile dataclass with one source and one project."""
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


def _write_lockfile_to_tmp(tmp_path: pathlib.Path, lockfile: "object") -> pathlib.Path:
    """Write a Lockfile to tmp_path/.kanon.lock and return the path."""
    from kanon_cli.core.lockfile import write_lockfile

    lock_path = tmp_path / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return lock_path


@pytest.mark.unit
class TestRenderJsonShape:
    """Tests for the _render_json function -- shape, keys, kinds, field values."""

    def test_single_chain_produces_array_length_one(self) -> None:
        """Single-chain tree -> JSON array with exactly one nested list."""
        source = _make_source_node(name="src")
        include = _make_include_node(name="bar", path_in_repo="repo-specs/bar.xml", sha="c" * 40)
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)

        chains = [[source, include, project]]
        result = _render_json(chains)

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_multi_chain_array_length_matches_chain_count(self) -> None:
        """Multi-chain tree -> array length equals number of chains."""
        source1 = _make_source_node(name="src1", sha="a" * 40)
        source2 = _make_source_node(name="src2", sha="a" * 40)
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)

        chains = [[source1, project], [source2, project]]
        result = _render_json(chains)

        parsed = json.loads(result)
        assert len(parsed) == 2

    def test_each_node_has_exactly_five_keys(self) -> None:
        """Each node object in the JSON has exactly five keys: kind, name, ref, sha, url."""
        source = _make_source_node(name="src")
        include = _make_include_node(name="bar", path_in_repo="repo-specs/bar.xml", sha="c" * 40)
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)

        chains = [[source, include, project]]
        result = _render_json(chains)

        parsed = json.loads(result)
        for chain in parsed:
            for node in chain:
                assert set(node.keys()) == {"kind", "name", "ref", "sha", "url"}, (
                    f"Node has unexpected keys: {set(node.keys())}"
                )

    def test_kind_values_restricted_to_domain(self) -> None:
        """'kind' values are exactly one of {source, include, project}."""
        allowed_kinds = {"source", "include", "project"}
        source = _make_source_node(name="src")
        include = _make_include_node(name="bar", path_in_repo="repo-specs/bar.xml", sha="c" * 40)
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)

        chains = [[source, include, project]]
        result = _render_json(chains)

        parsed = json.loads(result)
        for chain in parsed:
            for node in chain:
                assert node["kind"] in allowed_kinds, f"Unexpected kind: {node['kind']}"

    def test_source_node_kind_value(self) -> None:
        """Source node serializes as kind='source'."""
        source = _make_source_node(name="src")
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)

        result = _render_json([[source, project]])
        parsed = json.loads(result)
        assert parsed[0][0]["kind"] == "source"

    def test_include_node_kind_value(self) -> None:
        """Include node serializes as kind='include'."""
        source = _make_source_node(name="src")
        include = _make_include_node(name="bar", path_in_repo="repo-specs/bar.xml", sha="c" * 40)
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)

        result = _render_json([[source, include, project]])
        parsed = json.loads(result)
        assert parsed[0][1]["kind"] == "include"

    def test_project_node_kind_value(self) -> None:
        """Project node serializes as kind='project'."""
        source = _make_source_node(name="src")
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)

        result = _render_json([[source, project]])
        parsed = json.loads(result)
        assert parsed[0][-1]["kind"] == "project"


@pytest.mark.unit
class TestRenderJsonFieldValues:
    """Tests for specific field values in _render_json output."""

    def test_url_field_is_canonicalized(self) -> None:
        """The url field carries the canonicalized URL, not the raw form."""
        from kanon_cli.core.url import canonicalize_repo_url

        raw_url = "git@github.com:org/baz.git"
        canonical = canonicalize_repo_url(raw_url)

        source = _make_source_node(name="src")

        project = ChainNode(
            kind="project",
            name="baz",
            ref=None,
            sha="b" * 40,
            url=canonical,
            canonical_url=canonical,
        )

        result = _render_json([[source, project]])
        parsed = json.loads(result)

        project_node = parsed[0][-1]
        assert project_node["url"] == canonical

    def test_sha_field_is_full_40_char_hex(self) -> None:
        """The sha field is the full 40-char hex SHA (not truncated)."""
        sha_40 = "b" * 40
        source = _make_source_node(name="src")
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha=sha_40)

        result = _render_json([[source, project]])
        parsed = json.loads(result)

        for chain in parsed:
            for node in chain:
                assert len(node["sha"]) == 40, f"SHA not 40 chars: {node['sha']!r}"

    def test_ref_is_null_for_source_nodes(self) -> None:
        """Source nodes have ref=null (source nodes have no explicit ref/revision)."""
        source = _make_source_node(name="src")
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)

        result = _render_json([[source, project]])
        parsed = json.loads(result)

        source_node = parsed[0][0]
        assert source_node["ref"] is None

    def test_ref_is_null_for_project_nodes(self) -> None:
        """Project nodes have ref=null."""
        source = _make_source_node(name="src")
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)

        result = _render_json([[source, project]])
        parsed = json.loads(result)

        project_node = parsed[0][-1]
        assert project_node["ref"] is None

    def test_ref_is_path_for_include_nodes(self) -> None:
        """Include nodes have ref equal to their path_in_repo value."""
        source = _make_source_node(name="src")
        include = _make_include_node(name="bar", path_in_repo="repo-specs/bar.xml", sha="c" * 40)
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)

        result = _render_json([[source, include, project]])
        parsed = json.loads(result)

        include_node = parsed[0][1]
        assert include_node["ref"] == "repo-specs/bar.xml"

    def test_url_is_null_for_include_nodes(self) -> None:
        """Include nodes have url=null (includes have no associated URL)."""
        source = _make_source_node(name="src")
        include = _make_include_node(name="bar", path_in_repo="repo-specs/bar.xml", sha="c" * 40)
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)

        result = _render_json([[source, include, project]])
        parsed = json.loads(result)

        include_node = parsed[0][1]
        assert include_node["url"] is None

    def test_node_order_matches_text_format(self) -> None:
        """Nodes in each chain are ordered top-level source first, target node last."""
        source = _make_source_node(name="src")
        include = _make_include_node(name="bar", path_in_repo="repo-specs/bar.xml", sha="c" * 40)
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)

        result = _render_json([[source, include, project]])
        parsed = json.loads(result)

        chain = parsed[0]
        assert chain[0]["kind"] == "source"
        assert chain[0]["name"] == "src"
        assert chain[1]["kind"] == "include"
        assert chain[2]["kind"] == "project"
        assert chain[2]["name"] == "baz"

    def test_name_field_present_for_all_nodes(self) -> None:
        """'name' field is present and non-empty for all node kinds."""
        source = _make_source_node(name="my-source")
        include = _make_include_node(name="my-include", path_in_repo="specs/foo.xml", sha="c" * 40)
        project = _make_project_node(name="my-project", url="https://github.com/org/proj", sha="b" * 40)

        result = _render_json([[source, include, project]])
        parsed = json.loads(result)

        chain = parsed[0]
        assert chain[0]["name"] == "my-source"
        assert chain[1]["name"] == "my-include"
        assert chain[2]["name"] == "my-project"


@pytest.mark.unit
class TestRenderJsonWellFormed:
    """Tests for JSON well-formedness and round-trip parsing."""

    def test_output_parses_with_json_loads(self) -> None:
        """JSON output is well-formed and round-trips through json.loads."""
        source = _make_source_node(name="src")
        include = _make_include_node(name="bar", path_in_repo="repo-specs/bar.xml", sha="c" * 40)
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)

        result = _render_json([[source, include, project]])

        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_output_ends_with_newline(self) -> None:
        """JSON output ends with a newline character."""
        source = _make_source_node(name="src")
        project = _make_project_node(name="baz", url="https://github.com/org/baz", sha="b" * 40)

        result = _render_json([[source, project]])
        assert result.endswith("\n")

    def test_empty_chains_produces_empty_array(self) -> None:
        """Empty chains list produces a JSON empty array."""
        result = _render_json([])
        parsed = json.loads(result)
        assert parsed == []


def _build_why_parser(monkeypatch: pytest.MonkeyPatch) -> argparse.ArgumentParser:
    """Build a real argparse parser by invoking register() on a fresh top-level parser.

    Uses the real register() code path so that env-var defaults set via monkeypatch
    are picked up by os.environ.get() inside register().
    """
    import argparse as _argparse
    from kanon_cli.commands.why import register as _register

    top = _argparse.ArgumentParser(prog="kanon")
    subparsers = top.add_subparsers(dest="command")
    _register(subparsers)
    return top


@pytest.mark.unit
class TestFormatEnvVarAndCliOverride:
    """Tests for KANON_WHY_FORMAT env var and --format json CLI flag interactions."""

    def test_env_var_json_selects_json_output(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_WHY_FORMAT=json selects JSON output when --format not passed.

        Sets the env var, then calls register() to build a real argparse parser,
        parses WITHOUT --format, and verifies the default resolves to 'json'.
        """
        monkeypatch.setenv("KANON_WHY_FORMAT", "json")
        parser = _build_why_parser(monkeypatch)

        args, _ = parser.parse_known_args(["why", "some-target"])
        assert args.format == "json", f"Expected args.format == 'json' when KANON_WHY_FORMAT=json, got {args.format!r}"

    def test_format_json_cli_flag_overrides_text_env(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI --format json overrides KANON_WHY_FORMAT=text.

        Sets the env var to 'text', then calls register() and parses WITH
        --format json. Verifies CLI wins (args.format == 'json').
        """
        monkeypatch.setenv("KANON_WHY_FORMAT", "text")
        parser = _build_why_parser(monkeypatch)

        args, _ = parser.parse_known_args(["why", "some-target", "--format", "json"])
        assert args.format == "json", (
            f"Expected CLI --format json to win over env KANON_WHY_FORMAT=text, got {args.format!r}"
        )

    def test_env_var_json_run_produces_json_output(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """KANON_WHY_FORMAT=json with no --format flag produces JSON stdout via run().

        Omits --format from the parsed args (env-var path), builds a lockfile tree,
        and asserts that run() emits parseable JSON with the new shape:
        {"matched": {"category": ..., "token": ...}, "chains": [...]}.
        """
        project_url = "https://github.com/org/baz"
        project_sha = "b" * 40

        kanon_file = _make_minimal_kanon_file(tmp_path)
        lockfile = _make_minimal_lockfile(
            project_url=project_url,
            project_sha=project_sha,
        )
        lock_file = _write_lockfile_to_tmp(tmp_path, lockfile)

        monkeypatch.setenv("KANON_WHY_FORMAT", "json")
        parser = _build_why_parser(monkeypatch)
        args, _ = parser.parse_known_args(
            [
                "why",
                project_url,
                "--kanon-file",
                str(kanon_file),
                "--lock-file",
                str(lock_file),
            ]
        )

        assert args.format == "json"

        exit_code = run(args)
        assert exit_code == 0

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, dict), f"Expected dict, got {type(parsed).__name__}: {parsed!r}"
        assert "matched" in parsed, f"Expected 'matched' key, got keys: {list(parsed.keys())}"
        assert "chains" in parsed, f"Expected 'chains' key, got keys: {list(parsed.keys())}"
        assert len(parsed["chains"]) == 1

    def test_env_var_text_cli_json_run_produces_json_output(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """CLI --format json wins over KANON_WHY_FORMAT=text and produces JSON stdout.

        Passes --format json explicitly while env var is 'text'. Verifies run()
        emits parseable JSON with the new shape (CLI flag takes precedence):
        {"matched": {"category": ..., "token": ...}, "chains": [...]}.
        """
        project_url = "https://github.com/org/baz"
        project_sha = "b" * 40

        kanon_file = _make_minimal_kanon_file(tmp_path)
        lockfile = _make_minimal_lockfile(
            project_url=project_url,
            project_sha=project_sha,
        )
        lock_file = _write_lockfile_to_tmp(tmp_path, lockfile)

        monkeypatch.setenv("KANON_WHY_FORMAT", "text")
        parser = _build_why_parser(monkeypatch)
        args, _ = parser.parse_known_args(
            [
                "why",
                project_url,
                "--kanon-file",
                str(kanon_file),
                "--lock-file",
                str(lock_file),
                "--format",
                "json",
            ]
        )
        assert args.format == "json"

        exit_code = run(args)
        assert exit_code == 0

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, dict), f"Expected dict, got {type(parsed).__name__}: {parsed!r}"
        assert "matched" in parsed, f"Expected 'matched' key, got keys: {list(parsed.keys())}"
        assert "chains" in parsed, f"Expected 'chains' key, got keys: {list(parsed.keys())}"

    def test_format_text_default_produces_text_output(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Default format='text' still produces text (arrow-separated) output."""
        project_url = "https://github.com/org/baz"
        project_sha = "b" * 40

        kanon_file = _make_minimal_kanon_file(tmp_path)
        lockfile = _make_minimal_lockfile(
            project_url=project_url,
            project_sha=project_sha,
        )
        lock_file = _write_lockfile_to_tmp(tmp_path, lockfile)

        args = _make_args(
            target=project_url,
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
            fmt="text",
        )

        exit_code = run(args)
        assert exit_code == 0

        captured = capsys.readouterr()

        assert " -> " in captured.out


@pytest.mark.unit
class TestErrorPathsPlainText:
    """Tests for error-path messages remaining plain-text even when --format json."""

    def test_not_found_error_is_plain_text_regardless_of_format(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Not-found error emits plain-text to stderr even when --format json."""
        project_url = "https://github.com/org/present"

        kanon_file = _make_minimal_kanon_file(tmp_path)
        lockfile = _make_minimal_lockfile(
            project_url=project_url,
            project_sha="b" * 40,
        )
        lock_file = _write_lockfile_to_tmp(tmp_path, lockfile)

        absent_url = "https://github.com/org/absent"
        args = _make_args(
            target=absent_url,
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
            fmt="json",
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)
        assert exc_info.value.code != 0

        captured = capsys.readouterr()

        assert "not found" in captured.err.lower() or "ERROR" in captured.err

        assert captured.out == ""

    def test_ambiguity_error_is_plain_text_regardless_of_format(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Ambiguity error emits plain-text to stderr even when --format json.

        Creates a tree where the argument matches both XML-path and source-name
        categories, triggering the ambiguity error path.
        """
        from kanon_cli.core.lockfile import (
            CURRENT_SCHEMA_VERSION,
            IncludeEntry,
            Lockfile,
            ProjectEntry,
            SourceEntry,
        )
        from kanon_cli.core.url import canonicalize_repo_url

        ambiguous_value = "FOO"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name="FOO")

        include = IncludeEntry(
            name="foo-include",
            path_in_repo="FOO",
            url="https://github.com/org/catalog",
            resolved_sha="c" * 40,
            includes=[],
        )

        project_url = "https://github.com/org/baz"

        lockfile = Lockfile(
            schema_version=CURRENT_SCHEMA_VERSION,
            generated_at="2024-01-01T00:00:00Z",
            generator="kanon-test",
            kanon_hash="sha256:" + "a" * 64,
            sources=[
                SourceEntry(
                    alias="FOO",
                    name="FOO",
                    url="https://github.com/org/catalog",
                    ref_spec="main",
                    resolved_ref="main",
                    resolved_sha="a" * 40,
                    path="./foo",
                    includes=[include],
                    projects=[
                        ProjectEntry(
                            name="baz",
                            url=project_url,
                            canonical_url=canonicalize_repo_url(project_url),
                            ref_spec="main",
                            resolved_ref="main",
                            resolved_sha="b" * 40,
                        )
                    ],
                )
            ],
        )
        lock_file = _write_lockfile_to_tmp(tmp_path, lockfile)

        args = _make_args(
            target=ambiguous_value,
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
            fmt="json",
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)
        assert exc_info.value.code != 0

        captured = capsys.readouterr()

        assert "ERROR" in captured.err

        assert captured.out == ""

    def test_missing_kanon_file_is_plain_text_regardless_of_format(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Missing .kanon file error is plain-text even when --format json."""
        args = _make_args(
            target="https://github.com/org/baz",
            kanon_file=str(tmp_path / ".kanon"),
            fmt="json",
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)
        assert exc_info.value.code != 0

        captured = capsys.readouterr()

        assert "ERROR" in captured.err or ".kanon" in captured.err

        assert captured.out == ""


@pytest.mark.unit
class TestRunJsonOutput:
    """Tests for run() JSON output via lockfile-backed tree."""

    def test_run_json_single_chain_three_nodes(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """run() with --format json emits dict with 'matched' + 'chains'; chain length 3.

        The new JSON shape is {"matched": {"category": ..., "token": ...}, "chains": [...]}.
        The chains array contains the same node dicts as before.
        """
        from kanon_cli.core.lockfile import IncludeEntry

        project_url = "https://github.com/org/baz"
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
            project_name="baz",
            include_entries=[include],
        )
        lock_file = _write_lockfile_to_tmp(tmp_path, lockfile)

        args = _make_args(
            target=project_url,
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
            fmt="json",
        )

        exit_code = run(args)
        assert exit_code == 0

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)

        assert isinstance(parsed, dict), f"Expected dict, got {type(parsed).__name__}: {parsed!r}"
        assert "matched" in parsed, f"Expected 'matched' key in output, got: {list(parsed.keys())}"
        assert "chains" in parsed, f"Expected 'chains' key in output, got: {list(parsed.keys())}"

        assert parsed["matched"]["category"] == "url", (
            f"Expected category 'url', got: {parsed['matched']['category']!r}"
        )
        assert project_url in parsed["matched"]["token"], (
            f"Expected project URL in token, got: {parsed['matched']['token']!r}"
        )

        assert len(parsed["chains"]) == 1
        chain = parsed["chains"][0]
        assert len(chain) == 3

        assert chain[0]["kind"] == "source"
        assert chain[0]["name"] == "FOO"
        assert chain[0]["ref"] is None

        assert chain[1]["kind"] == "include"
        assert chain[1]["ref"] == "repo-specs/bar.xml"
        assert chain[1]["sha"] == include_sha
        assert chain[1]["url"] is None

        assert chain[2]["kind"] == "project"
        assert chain[2]["name"] == "baz"
        assert chain[2]["sha"] == project_sha
        assert chain[2]["ref"] is None

        for node in chain:
            assert set(node.keys()) == {"kind", "name", "ref", "sha", "url"}

    def test_run_json_sha_is_full_40_chars(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """run() JSON output has 40-char SHA on every node in chains (AC-FUNC-006)."""
        project_url = "https://github.com/org/baz"
        project_sha = "b" * 40

        kanon_file = _make_minimal_kanon_file(tmp_path)
        lockfile = _make_minimal_lockfile(
            project_url=project_url,
            project_sha=project_sha,
        )
        lock_file = _write_lockfile_to_tmp(tmp_path, lockfile)

        args = _make_args(
            target=project_url,
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
            fmt="json",
        )

        exit_code = run(args)
        assert exit_code == 0

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, dict), f"Expected dict from run() JSON mode, got {type(parsed).__name__}"
        for chain in parsed["chains"]:
            for node in chain:
                assert len(node["sha"]) == 40

    def test_run_json_url_field_is_canonical(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """run() JSON output url field in chains carries the canonicalized URL."""
        from kanon_cli.core.url import canonicalize_repo_url

        project_url = "https://github.com/org/baz"
        expected_canonical = canonicalize_repo_url(project_url)
        project_sha = "b" * 40

        kanon_file = _make_minimal_kanon_file(tmp_path)
        lockfile = _make_minimal_lockfile(
            project_url=project_url,
            project_sha=project_sha,
        )
        lock_file = _write_lockfile_to_tmp(tmp_path, lockfile)

        args = _make_args(
            target=project_url,
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
            fmt="json",
        )

        exit_code = run(args)
        assert exit_code == 0

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, dict), f"Expected dict from run() JSON mode, got {type(parsed).__name__}"

        project_node = parsed["chains"][0][-1]
        assert project_node["url"] == expected_canonical

    def test_argparse_choices_reject_invalid_format(self, tmp_path: pathlib.Path) -> None:
        """Argparse --format choices reject any value not in ('text', 'json')."""
        import subprocess
        import sys

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("GITBASE=https://github.com\n")

        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "why", "target", "--format", "invalid"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "invalid choice" in result.stderr or "error" in result.stderr.lower()


@pytest.mark.unit
class TestBuildWhyPayload:
    """_build_why_payload returns a list-of-lists of dicts consumed by _emit_json_payload."""

    def _make_chain_node(
        self,
        *,
        kind: str = "project",
        name: str = "example",
        ref: str | None = None,
        sha: str = "a" * 40,
        url: str | None = "https://github.com/org/example",
        canonical_url: str | None = None,
    ) -> ChainNode:
        """Build a minimal ChainNode for testing."""
        return ChainNode(
            kind=kind,
            name=name,
            ref=ref,
            sha=sha,
            url=url,
            canonical_url=canonical_url or url,
        )

    def test_single_chain_single_node(self) -> None:
        """One chain with one node produces [[{...}]]."""
        node = self._make_chain_node()
        payload = _build_why_payload([[node]])
        assert isinstance(payload, list)
        assert len(payload) == 1
        assert len(payload[0]) == 1

    def test_node_has_five_keys(self) -> None:
        """Each node dict has exactly the five spec-canonical keys."""
        node = self._make_chain_node()
        payload = _build_why_payload([[node]])
        node_dict = payload[0][0]
        assert set(node_dict.keys()) == {"kind", "name", "ref", "sha", "url"}

    def test_empty_chains_produces_empty_list(self) -> None:
        """Empty chains input produces an empty list."""
        assert _build_why_payload([]) == []

    def test_result_is_json_serialisable(self) -> None:
        """The payload round-trips through json.dumps / json.loads without error."""
        node = self._make_chain_node(kind="project", name="alpha", sha="b" * 40)
        payload = _build_why_payload([[node]])
        serialised = json.dumps(payload)
        parsed = json.loads(serialised)
        assert parsed[0][0]["name"] == "alpha"

    def test_multiple_chains_preserved(self) -> None:
        """Multiple chains produce multiple inner lists."""
        node_a = self._make_chain_node(name="a")
        node_b = self._make_chain_node(name="b")
        payload = _build_why_payload([[node_a], [node_b]])
        assert len(payload) == 2


@pytest.mark.unit
class TestRunJsonMultiplicity:
    """JSON output for a multiply-present node: one matched object, every chain."""

    def test_shared_include_emits_single_matched_object_and_all_chains(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A transitive include shared by 3 sources emits one matched object and 3 chains."""
        from unittest.mock import patch

        shared_path = "repo-specs/git-connection/remote.xml"
        shared_sha = "d" * 40
        sources = []
        for index in range(3):
            include = _make_include_node("remote", shared_path, sha=shared_sha)
            source = _make_source_node(f"src{index}")
            source.children = [include]
            sources.append(source)
        tree = ResolvedTree(sources=sources)

        kanon_file = _make_minimal_kanon_file(tmp_path, "src0")
        lockfile = _make_minimal_lockfile(project_url="https://github.com/org/baz", project_sha="b" * 40)
        lock_file = _write_lockfile_to_tmp(tmp_path, lockfile)
        args = _make_args(target=shared_path, kanon_file=str(kanon_file), lock_file=str(lock_file), fmt="json")

        with patch("kanon_cli.commands.why._build_tree_from_lockfile", return_value=tree):
            exit_code = run(args)

        assert exit_code == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed["matched"], dict)
        assert parsed["matched"]["category"] == "xml_path"
        assert parsed["matched"]["token"] == shared_path
        assert len(parsed["chains"]) == 3
