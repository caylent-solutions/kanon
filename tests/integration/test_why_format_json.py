"""Integration tests for 'kanon why --format json' end-to-end.

Builds a real file:// fixture catalog with a source -> include -> project chain.
Invokes 'kanon why <project-url> --format json' via subprocess.
Captures stdout and parses with json.loads.
Asserts array length 1, chain length 3 (source/include/project), each node
has the five required keys, and resolved SHAs match the lockfile values.

AC-TEST-002, AC-CYCLE-001
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import textwrap

import pytest

from kanon_cli.core.lockfile import (
    CatalogBlock,
    IncludeEntry,
    Lockfile,
    ProjectEntry,
    SourceEntry,
    write_lockfile,
)
from kanon_cli.core.url import canonicalize_repo_url


# ---------------------------------------------------------------------------
# Fixture constants
# ---------------------------------------------------------------------------

_SOURCE_NAME = "FOO"
_PROJECT_NAME = "baz"
_PROJECT_URL = "https://github.com/org/baz"
_INCLUDE_NAME = "bar"
_INCLUDE_PATH = "repo-specs/bar.xml"

# Fixed SHAs used throughout the fixture -- 40 hex chars each
_SOURCE_SHA = "a" * 40
_INCLUDE_SHA = "c" * 40
_PROJECT_SHA = "b" * 40
_CATALOG_SHA = "f" * 40
_KANON_HASH = "sha256:" + "a" * 64


# ---------------------------------------------------------------------------
# Override conftest autouse fixtures (not needed for this test)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_resolve_ref_to_sha():
    """Override: this test does not install anything -- no git calls needed."""
    yield


@pytest.fixture(autouse=True)
def _mock_check_sha_reachable():
    """Override: this test does not install anything -- no git calls needed."""
    yield


# ---------------------------------------------------------------------------
# Fixture: .kanon and .kanon.lock in a tmp directory
# ---------------------------------------------------------------------------


@pytest.fixture()
def why_json_fixture(tmp_path: pathlib.Path):
    """Create a .kanon file and a .kanon.lock with a single include chain.

    Tree structure in the lockfile:
      FOO (source, sha=_SOURCE_SHA)
        bar (include, path_in_repo=_INCLUDE_PATH, sha=_INCLUDE_SHA)
          (no nested includes)
        baz (project, url=_PROJECT_URL, sha=_PROJECT_SHA)

    Returns:
        A dict with keys 'kanon_file', 'lock_file', 'project_url', 'project_sha',
        'include_sha', 'include_path', 'source_name'.
    """
    kanon_file = tmp_path / ".kanon"
    kanon_content = textwrap.dedent(f"""\
        GITBASE=https://github.com
        CLAUDE_MARKETPLACES_DIR=/tmp/mkts
        KANON_MARKETPLACE_INSTALL=false
        KANON_SOURCE_{_SOURCE_NAME}_URL=https://github.com/org/catalog
        KANON_SOURCE_{_SOURCE_NAME}_REVISION=main
        KANON_SOURCE_{_SOURCE_NAME}_PATH=./foo
    """)
    kanon_file.write_text(kanon_content)
    kanon_file.chmod(0o644)

    lockfile = Lockfile(
        schema_version=1,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash=_KANON_HASH,
        catalog=CatalogBlock(
            source="https://github.com/org/catalog@main",
            url="https://github.com/org/catalog",
            revision_spec="main",
            resolved_ref="refs/heads/main",
            resolved_sha=_CATALOG_SHA,
        ),
        sources=[
            SourceEntry(
                name=_SOURCE_NAME,
                url="https://github.com/org/catalog",
                revision_spec="main",
                resolved_ref="refs/heads/main",
                resolved_sha=_SOURCE_SHA,
                path="./foo",
                includes=[
                    IncludeEntry(
                        name=_INCLUDE_NAME,
                        path_in_repo=_INCLUDE_PATH,
                        url="https://github.com/org/catalog",
                        resolved_sha=_INCLUDE_SHA,
                        includes=[],
                    )
                ],
                projects=[
                    ProjectEntry(
                        name=_PROJECT_NAME,
                        url=_PROJECT_URL,
                        canonical_url=canonicalize_repo_url(_PROJECT_URL),
                        revision_spec="main",
                        resolved_ref="refs/heads/main",
                        resolved_sha=_PROJECT_SHA,
                    )
                ],
            )
        ],
    )

    lock_file = tmp_path / ".kanon.lock"
    write_lockfile(lockfile, lock_file)

    return {
        "kanon_file": kanon_file,
        "lock_file": lock_file,
        "project_url": _PROJECT_URL,
        "project_sha": _PROJECT_SHA,
        "include_sha": _INCLUDE_SHA,
        "include_path": _INCLUDE_PATH,
        "source_name": _SOURCE_NAME,
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run_why_json(
    fixture: dict,
    target: str,
    extra_args: "list[str] | None" = None,
) -> "subprocess.CompletedProcess[str]":
    """Invoke 'kanon why <target> --format json' via subprocess and return the result."""
    cmd = [
        sys.executable,
        "-m",
        "kanon_cli",
        "why",
        target,
        "--kanon-file",
        str(fixture["kanon_file"]),
        "--lock-file",
        str(fixture["lock_file"]),
        "--format",
        "json",
    ]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# End-to-end integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWhyFormatJsonIntegration:
    """End-to-end integration tests for 'kanon why --format json' via subprocess."""

    def test_json_output_is_well_formed(self, why_json_fixture: dict) -> None:
        """Output from --format json is parseable by json.loads (AC-FUNC-001)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}. stderr: {result.stderr}"
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, list), f"Expected list from json.loads, got {type(parsed).__name__}: {parsed!r}"

    def test_json_array_length_one(self, why_json_fixture: dict) -> None:
        """JSON output is a top-level array with one chain for a single-chain tree (AC-FUNC-001)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_chain_length_three_source_include_project(self, why_json_fixture: dict) -> None:
        """The single chain has exactly 3 nodes: source, include, project (AC-CYCLE-001)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        chain = parsed[0]
        assert len(chain) == 3

    def test_node_zero_is_source(self, why_json_fixture: dict) -> None:
        """node[0].kind == 'source' (AC-CYCLE-001, AC-FUNC-004)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert parsed[0][0]["kind"] == "source"

    def test_node_one_is_include(self, why_json_fixture: dict) -> None:
        """node[1].kind == 'include' (AC-CYCLE-001, AC-FUNC-004)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert parsed[0][1]["kind"] == "include"

    def test_node_two_is_project(self, why_json_fixture: dict) -> None:
        """node[2].kind == 'project' (AC-CYCLE-001, AC-FUNC-004)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert parsed[0][2]["kind"] == "project"

    def test_all_nodes_have_exactly_five_keys(self, why_json_fixture: dict) -> None:
        """Every node object has exactly 5 keys: kind, name, ref, sha, url (AC-FUNC-003)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        for chain in parsed:
            for node in chain:
                assert set(node.keys()) == {"kind", "name", "ref", "sha", "url"}, (
                    f"Node keys mismatch: {set(node.keys())}"
                )

    def test_source_sha_matches_lockfile(self, why_json_fixture: dict) -> None:
        """Source node SHA matches the lockfile value (AC-FUNC-006, AC-CYCLE-001)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        source_node = parsed[0][0]
        assert source_node["sha"] == _SOURCE_SHA

    def test_include_sha_matches_lockfile(self, why_json_fixture: dict) -> None:
        """Include node SHA matches the lockfile value (AC-FUNC-006, AC-CYCLE-001)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        include_node = parsed[0][1]
        assert include_node["sha"] == why_json_fixture["include_sha"]

    def test_project_sha_matches_lockfile(self, why_json_fixture: dict) -> None:
        """Project node SHA matches the lockfile value (AC-FUNC-006, AC-CYCLE-001)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        project_node = parsed[0][2]
        assert project_node["sha"] == why_json_fixture["project_sha"]

    def test_all_shas_are_40_chars(self, why_json_fixture: dict) -> None:
        """All SHA fields are full 40-char hex strings (AC-FUNC-006)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        for chain in parsed:
            for node in chain:
                assert len(node["sha"]) == 40, f"SHA not 40 chars: {node['sha']!r}"

    def test_project_url_is_canonical(self, why_json_fixture: dict) -> None:
        """Project node url field is the canonicalized URL (AC-FUNC-005)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        project_node = parsed[0][2]
        expected_canonical = canonicalize_repo_url(why_json_fixture["project_url"])
        assert project_node["url"] == expected_canonical

    def test_include_url_is_null(self, why_json_fixture: dict) -> None:
        """Include node url field is null (include nodes have no URL) (AC-FUNC-005)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        include_node = parsed[0][1]
        assert include_node["url"] is None

    def test_include_ref_is_path_in_repo(self, why_json_fixture: dict) -> None:
        """Include node ref field equals the path_in_repo value (AC-FUNC-003)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        include_node = parsed[0][1]
        assert include_node["ref"] == why_json_fixture["include_path"]

    def test_source_ref_is_null(self, why_json_fixture: dict) -> None:
        """Source node ref field is null (sources have no explicit ref) (AC-FUNC-003)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        source_node = parsed[0][0]
        assert source_node["ref"] is None

    def test_project_ref_is_null(self, why_json_fixture: dict) -> None:
        """Project node ref field is null (AC-FUNC-003)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        project_node = parsed[0][2]
        assert project_node["ref"] is None

    def test_source_name_matches_lockfile(self, why_json_fixture: dict) -> None:
        """Source node name matches the lockfile source name (AC-FUNC-002)."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        source_node = parsed[0][0]
        assert source_node["name"] == why_json_fixture["source_name"]

    def test_exit_code_zero_on_success(self, why_json_fixture: dict) -> None:
        """CLI exits with code 0 on a successful --format json invocation."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0

    def test_no_error_on_stderr_on_success(self, why_json_fixture: dict) -> None:
        """No ERROR message emitted to stderr on a successful --format json invocation."""
        result = _run_why_json(why_json_fixture, why_json_fixture["project_url"])
        assert result.returncode == 0
        # Warnings (e.g., about recommended character set) are acceptable; hard errors are not
        assert "ERROR:" not in result.stderr

    def test_not_found_error_exits_nonzero_with_json_format(self, why_json_fixture: dict) -> None:
        """--format json does not change the non-zero exit on not-found (AC-FUNC-010)."""
        result = _run_why_json(why_json_fixture, "https://github.com/org/nonexistent-repo")
        assert result.returncode != 0

    def test_not_found_error_emits_to_stderr_not_stdout(self, why_json_fixture: dict) -> None:
        """Not-found error appears on stderr, not stdout, even with --format json (AC-FUNC-010)."""
        result = _run_why_json(why_json_fixture, "https://github.com/org/nonexistent-repo")
        assert result.returncode != 0
        assert "not found" in result.stderr.lower() or "ERROR" in result.stderr
        assert result.stdout == ""

    def test_project_url_emits_canonical_not_raw_scp_form(self, tmp_path: pathlib.Path) -> None:
        """JSON url field is the canonical HTTPS URL even when lockfile stores a raw SCP URL.

        Uses git@github.com:org/baz.git (non-canonical SCP form) as the raw URL in the
        lockfile ProjectEntry. Asserts that the JSON output carries the canonicalized
        https:// form, not the raw SCP form. Regression guard for _chain_to_node_dicts
        using node.canonical_url instead of node.url.
        """
        raw_url = "git@github.com:org/baz.git"
        expected_canonical = canonicalize_repo_url(raw_url)

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=https://github.com\n"
            "CLAUDE_MARKETPLACES_DIR=/tmp/mkts\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_FOO_URL=https://github.com/org/catalog\n"
            "KANON_SOURCE_FOO_REVISION=main\n"
            "KANON_SOURCE_FOO_PATH=./foo\n"
        )
        kanon_file.chmod(0o644)

        lockfile = Lockfile(
            schema_version=1,
            generated_at="2024-01-01T00:00:00Z",
            generator="kanon-test",
            kanon_hash=_KANON_HASH,
            catalog=CatalogBlock(
                source="https://github.com/org/catalog@main",
                url="https://github.com/org/catalog",
                revision_spec="main",
                resolved_ref="refs/heads/main",
                resolved_sha=_CATALOG_SHA,
            ),
            sources=[
                SourceEntry(
                    name="FOO",
                    url="https://github.com/org/catalog",
                    revision_spec="main",
                    resolved_ref="refs/heads/main",
                    resolved_sha=_SOURCE_SHA,
                    path="./foo",
                    includes=[],
                    projects=[
                        ProjectEntry(
                            name="baz",
                            url=raw_url,
                            canonical_url=expected_canonical,
                            revision_spec="main",
                            resolved_ref="refs/heads/main",
                            resolved_sha=_PROJECT_SHA,
                        )
                    ],
                )
            ],
        )
        lock_file = tmp_path / ".kanon.lock"
        write_lockfile(lockfile, lock_file)

        fixture = {
            "kanon_file": kanon_file,
            "lock_file": lock_file,
        }
        result = _run_why_json(fixture, expected_canonical)
        assert result.returncode == 0, f"Expected exit 0. stderr: {result.stderr}"

        parsed = json.loads(result.stdout)
        project_node = parsed[0][-1]
        assert project_node["url"] == expected_canonical, (
            f"Expected canonical URL {expected_canonical!r}, got {project_node['url']!r}. "
            "This is a regression: _chain_to_node_dicts must use node.canonical_url for project nodes."
        )
        assert project_node["url"] != raw_url, f"url field must not be the raw SCP form {raw_url!r}"


# ---------------------------------------------------------------------------
# JSON parity test for url match on live-resolve path (no lockfile)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWhyJsonLiveResolveUrlMatch:
    """JSON parity: ``kanon why <project-url> --format json`` on the live-resolve path.

    After ``kanon add <entry> --catalog-source <synthetic>`` (no install, no lockfile),
    ``kanon why <project-url> --format json`` should exit 0 and emit a valid JSON
    array where the first chain starts with the source entry name.

    This is the json-parity assertion for E49-F1 (findings row 68, url match on
    live-resolve path).
    """

    def test_json_url_match_on_live_path(self, tmp_path: pathlib.Path) -> None:
        """``kanon why <project-url> --format json`` exits 0 on live-resolve path.

        Flow:
          1. Build a synthetic catalog with entry ``epsilon`` whose marketplace XML
             contains a ``<project remote="origin" name="liveproject">`` element and
             ``<remote name="origin" fetch="https://github.com/livetestorg">``.
          2. Run ``kanon add epsilon --catalog-source <url>`` (no install, no lockfile).
          3. Assert ``.kanon.lock`` is absent (live-resolve path confirmed).
          4. Run ``kanon why https://github.com/livetestorg/liveproject
             --format json --catalog-source <url>``.
          5. Assert exit code 0.
          6. Assert JSON is a list.
          7. Assert the first chain's first node has ``kind == "source"`` and
             ``name`` contains the derived source name ``EPSILON``.

        Args:
            tmp_path: pytest per-test temp directory.
        """
        from tests.integration.test_why_live_resolve import _create_catalog_with_project_and_include

        entry_name = "epsilon"
        project_name = "liveproject"
        project_fetch_url = "https://github.com/livetestorg"
        project_url = f"{project_fetch_url}/{project_name}"

        catalog_dir = tmp_path / "catalog"
        bare_repo = _create_catalog_with_project_and_include(
            catalog_dir,
            entry_name=entry_name,
            project_name=project_name,
            project_fetch_url=project_fetch_url,
            tags=["1.0.0"],
        )
        catalog_source_url = f"file://{bare_repo}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        add_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kanon_cli",
                "add",
                entry_name,
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            capture_output=True,
            text=True,
            cwd=str(workspace),
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (exit {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\n"
            f"stderr: {add_result.stderr!r}"
        )

        lock_file = workspace / ".kanon.lock"
        assert not lock_file.exists(), f"Expected .kanon.lock to be absent but found it at {lock_file}"

        why_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kanon_cli",
                "why",
                project_url,
                "--format",
                "json",
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            capture_output=True,
            text=True,
            cwd=str(workspace),
        )

        assert why_result.returncode == 0, (
            f"Expected exit 0 from 'kanon why {project_url} --format json' "
            f"(live-resolve, url match), got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        import json as _json

        parsed = _json.loads(why_result.stdout)
        assert isinstance(parsed, list), (
            f"Expected JSON list from --format json, got {type(parsed).__name__}: {parsed!r}"
        )
        assert len(parsed) >= 1, "Expected at least one chain in JSON output, got empty list"

        source_node = parsed[0][0]
        assert source_node["kind"] == "source", f"Expected first node kind='source', got {source_node['kind']!r}"
        assert source_node["name"] == entry_name, f"Expected source name {entry_name!r}, got {source_node['name']!r}"
