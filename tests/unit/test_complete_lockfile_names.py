"""Unit tests for kanon_cli.completions.lockfile_names -- AC-TEST-001.

Covers: happy path, missing lockfile, malformed TOML, prefix filter,
deep recursion, KANON_COMPLETION_ENABLED=0.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.completions.lockfile_names import (
    _extract_names,
    _handle,
    complete,
)
from kanon_cli.utils.lock_file_path import derive_lock_file_path
from kanon_cli.core.lockfile import (
    CURRENT_SCHEMA_VERSION,
    IncludeEntry,
    Lockfile,
    ProjectEntry,
    SourceEntry,
    write_lockfile,
)


_DUMMY_SHA = "a" * 40
_DUMMY_SHA2 = "b" * 40
_DUMMY_SHA3 = "c" * 40


def _make_lockfile(
    sources: list[SourceEntry] | None = None,
) -> Lockfile:
    """Build a minimal valid schema-v4 Lockfile with the supplied sources."""
    return Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-cli/test",
        kanon_hash="sha256:" + "a" * 64,
        sources=sources or [],
    )


def _make_source(
    name: str,
    includes: list[IncludeEntry] | None = None,
    projects: list[ProjectEntry] | None = None,
) -> SourceEntry:
    return SourceEntry(
        alias=name,
        name=name,
        url="https://github.com/org/repo",
        ref_spec="main",
        resolved_ref="refs/heads/main",
        resolved_sha=_DUMMY_SHA,
        path=f"vendor/{name}",
        includes=includes or [],
        projects=projects or [],
    )


def _make_include(
    name: str,
    path_in_repo: str,
    includes: list[IncludeEntry] | None = None,
) -> IncludeEntry:
    return IncludeEntry(
        name=name,
        path_in_repo=path_in_repo,
        url="https://github.com/org/repo",
        resolved_sha=_DUMMY_SHA,
        includes=includes or [],
    )


def _make_project(
    name: str,
    url: str,
) -> ProjectEntry:
    from kanon_cli.core.url import canonicalize_repo_url

    canonical = canonicalize_repo_url(url)
    return ProjectEntry(
        name=name,
        url=url,
        canonical_url=canonical,
        ref_spec="main",
        resolved_ref="refs/heads/main",
        resolved_sha=_DUMMY_SHA,
    )


@pytest.mark.unit
class TestResolveLockfilePath:
    """derive_lock_file_path() implements the three-level precedence chain used by the completer."""

    def test_env_lock_file_wins(self, tmp_path: Path) -> None:
        """KANON_LOCK_FILE env var (env_lock_file) is returned when set."""
        explicit = str(tmp_path / "explicit.lock")
        result = derive_lock_file_path(
            kanon_file_path=Path("./.kanon"),
            cli_lock_file=None,
            env_lock_file=explicit,
        )
        assert result == Path(explicit)

    def test_derived_from_kanon_file_env(self, tmp_path: Path) -> None:
        """When env_lock_file absent, derives path from kanon_file_path + .lock."""
        kanon_file = tmp_path / ".kanon"
        result = derive_lock_file_path(
            kanon_file_path=kanon_file,
            cli_lock_file=None,
            env_lock_file=None,
        )
        assert result == Path(str(kanon_file) + ".lock")

    def test_default_dot_kanon_lock(self) -> None:
        """When no overrides, derives from the default kanon file path."""
        result = derive_lock_file_path(
            kanon_file_path=Path("./.kanon"),
            cli_lock_file=None,
            env_lock_file=None,
        )
        assert result == Path("./.kanon.lock")

    def test_env_lock_file_takes_precedence_over_kanon_file(self, tmp_path: Path) -> None:
        """env_lock_file takes precedence over kanon_file_path-derived path."""
        explicit = str(tmp_path / "explicit.lock")
        kanon_file = tmp_path / ".kanon"
        result = derive_lock_file_path(
            kanon_file_path=kanon_file,
            cli_lock_file=None,
            env_lock_file=explicit,
        )
        assert result == Path(explicit)


@pytest.mark.unit
class TestExtractNames:
    """_extract_names() enumerates source names, include paths, and project URLs."""

    def test_happy_path_all_five_names(self) -> None:
        """AC-FUNC-001: two top-level sources + one include + two projects -> five names."""
        lockfile = _make_lockfile(
            sources=[
                _make_source(
                    "foo",
                    includes=[_make_include("inc_x", "subpkg/x")],
                    projects=[_make_project("proj1", "https://example.com/proj1.git")],
                ),
                _make_source(
                    "bar",
                    projects=[_make_project("proj2", "https://example.com/proj2.git")],
                ),
            ]
        )
        result = _extract_names(lockfile)
        assert result == [
            "bar",
            "foo",
            "https://example.com/proj1.git",
            "https://example.com/proj2.git",
            "subpkg/x",
        ]

    def test_deduplication(self) -> None:
        """Duplicate names across sources are deduplicated."""
        lockfile = _make_lockfile(
            sources=[
                _make_source(
                    "alpha",
                    projects=[_make_project("p", "https://example.com/shared.git")],
                ),
                _make_source(
                    "beta",
                    projects=[_make_project("p2", "https://example.com/shared.git")],
                ),
            ]
        )
        result = _extract_names(lockfile)
        assert result.count("https://example.com/shared.git") == 1

    def test_empty_lockfile_returns_empty(self) -> None:
        """No sources -> empty list."""
        lockfile = _make_lockfile(sources=[])
        assert _extract_names(lockfile) == []

    def test_source_only_returns_name(self) -> None:
        """Source with no includes or projects returns just the source name."""
        lockfile = _make_lockfile(sources=[_make_source("only_source")])
        assert _extract_names(lockfile) == ["only_source"]

    def test_project_url_extracted(self) -> None:
        """Project URL (not name) is extracted from ProjectEntry."""
        lockfile = _make_lockfile(
            sources=[
                _make_source(
                    "src",
                    projects=[_make_project("myname", "https://github.com/org/repo.git")],
                )
            ]
        )
        result = _extract_names(lockfile)
        assert "https://github.com/org/repo.git" in result

        assert "myname" not in result

    def test_include_path_in_repo_extracted(self) -> None:
        """path_in_repo (not name) is extracted from IncludeEntry."""
        lockfile = _make_lockfile(
            sources=[
                _make_source(
                    "src",
                    includes=[_make_include("human_name", "repo-specs/foo.xml")],
                )
            ]
        )
        result = _extract_names(lockfile)
        assert "repo-specs/foo.xml" in result

        assert "human_name" not in result

    def test_deep_recursion_depth_3(self) -> None:
        """AC-FUNC-008: nested includes at depth 3 are extracted (recursion exercised)."""

        include_l3 = _make_include("name_l3", "deep/path/level3.xml")
        include_l2 = _make_include("name_l2", "deep/path/level2.xml", includes=[include_l3])
        include_l1 = _make_include("name_l1", "deep/path/level1.xml", includes=[include_l2])
        lockfile = _make_lockfile(sources=[_make_source("root_source", includes=[include_l1])])
        result = _extract_names(lockfile)
        assert "root_source" in result
        assert "deep/path/level1.xml" in result
        assert "deep/path/level2.xml" in result
        assert "deep/path/level3.xml" in result

    def test_sorted_output(self) -> None:
        """Results are sorted deterministically."""
        lockfile = _make_lockfile(
            sources=[
                _make_source("zzz"),
                _make_source("aaa"),
                _make_source("mmm"),
            ]
        )
        result = _extract_names(lockfile)
        assert result == sorted(result)


@pytest.mark.unit
class TestCompleteDisabled:
    """KANON_COMPLETION_ENABLED=0 causes complete() to return [] without reading lockfile."""

    def test_disabled_returns_empty(self, tmp_path: Path) -> None:
        """KANON_COMPLETION_ENABLED=0 -> empty list, no file read attempted."""
        lock_path = tmp_path / ".kanon.lock"

        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "0",
                "KANON_LOCK_FILE": str(lock_path),
            },
        ):
            result = complete("")
        assert result == []

    def test_disabled_does_not_write_log(self, tmp_path: Path) -> None:
        """KANON_COMPLETION_ENABLED=0 does not touch completion-errors.log."""
        log_path = tmp_path / "completion-errors.log"
        lock_path = tmp_path / ".kanon.lock"
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "0",
                "KANON_LOCK_FILE": str(lock_path),
                "KANON_COMPLETION_LOG": str(log_path),
                "KANON_HOME": str(tmp_path),
            },
        ):
            complete("")
        assert not log_path.exists()


@pytest.mark.unit
class TestCompleteHappyPath:
    """complete() reads lockfile and returns sorted, prefix-filtered names."""

    def test_five_names_empty_prefix(self, tmp_path: Path) -> None:
        """AC-FUNC-001: all five names returned with empty prefix."""
        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile(
            sources=[
                _make_source(
                    "foo",
                    includes=[_make_include("inc_x", "subpkg/x")],
                    projects=[_make_project("proj1", "https://example.com/proj1.git")],
                ),
                _make_source(
                    "bar",
                    projects=[_make_project("proj2", "https://example.com/proj2.git")],
                ),
            ]
        )
        write_lockfile(lockfile, lock_path)
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_LOCK_FILE": str(lock_path),
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete("")
        assert result == [
            "bar",
            "foo",
            "https://example.com/proj1.git",
            "https://example.com/proj2.git",
            "subpkg/x",
        ]

    def test_prefix_filter_source_name(self, tmp_path: Path) -> None:
        """AC-FUNC-002: prefix 'foo' returns only 'foo'."""
        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile(
            sources=[
                _make_source(
                    "foo",
                    projects=[_make_project("p1", "https://example.com/proj1.git")],
                ),
                _make_source("bar"),
            ]
        )
        write_lockfile(lockfile, lock_path)
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_LOCK_FILE": str(lock_path),
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete("foo")
        assert result == ["foo"]

    def test_prefix_filter_https(self, tmp_path: Path) -> None:
        """AC-FUNC-002: prefix 'https' returns only the two project URLs."""
        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile(
            sources=[
                _make_source(
                    "foo",
                    projects=[
                        _make_project("p1", "https://example.com/proj1.git"),
                        _make_project("p2", "https://example.com/proj2.git"),
                    ],
                ),
            ]
        )
        write_lockfile(lockfile, lock_path)
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_LOCK_FILE": str(lock_path),
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete("https")
        assert result == [
            "https://example.com/proj1.git",
            "https://example.com/proj2.git",
        ]

    @pytest.mark.parametrize(
        "prefix,expected",
        [
            ("", ["bar", "foo", "https://example.com/proj1.git"]),
            ("f", ["foo"]),
            ("b", ["bar"]),
            ("https", ["https://example.com/proj1.git"]),
            ("x", []),
        ],
        ids=["empty", "f-prefix", "b-prefix", "https-prefix", "no-match"],
    )
    def test_prefix_filter_parametrized(self, tmp_path: Path, prefix: str, expected: list[str]) -> None:
        """Parametrized prefix-filter coverage."""
        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile(
            sources=[
                _make_source(
                    "foo",
                    projects=[_make_project("p1", "https://example.com/proj1.git")],
                ),
                _make_source("bar"),
            ]
        )
        write_lockfile(lockfile, lock_path)
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_LOCK_FILE": str(lock_path),
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete(prefix)
        assert result == expected


@pytest.mark.unit
class TestCompleteMissingLockfile:
    """complete() returns empty and logs when the lockfile does not exist."""

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """AC-FUNC-004: missing lockfile -> empty list, no exception raised."""
        lock_path = tmp_path / "nonexistent.lock"
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_LOCK_FILE": str(lock_path),
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete("")
        assert result == []

    def test_missing_file_writes_log_entry(self, tmp_path: Path) -> None:
        """AC-FUNC-004: missing lockfile writes FileNotFoundError to completion-errors.log."""
        lock_path = tmp_path / "nonexistent.lock"
        log_path = tmp_path / "completion-errors.log"
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_LOCK_FILE": str(lock_path),
                "KANON_COMPLETION_LOG": str(log_path),
                "KANON_HOME": str(tmp_path),
            },
        ):
            complete("")
        assert log_path.exists()
        content = log_path.read_text()
        assert "__complete_names_in_lockfile" in content
        assert "FileNotFoundError" in content
        assert str(lock_path) in content


@pytest.mark.unit
class TestCompleteMalformedLockfile:
    """complete() returns empty and logs when the lockfile contains malformed TOML."""

    def test_malformed_toml_returns_empty(self, tmp_path: Path) -> None:
        """AC-FUNC-005: malformed TOML -> empty list, no exception raised."""
        lock_path = tmp_path / ".kanon.lock"
        lock_path.write_text("this is not valid toml {{{")
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_LOCK_FILE": str(lock_path),
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete("")
        assert result == []

    def test_malformed_toml_writes_log_entry(self, tmp_path: Path) -> None:
        """AC-FUNC-005: malformed TOML writes structured log entry naming error class."""
        lock_path = tmp_path / ".kanon.lock"
        lock_path.write_text("this is not valid toml {{{")
        log_path = tmp_path / "completion-errors.log"
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_LOCK_FILE": str(lock_path),
                "KANON_COMPLETION_LOG": str(log_path),
                "KANON_HOME": str(tmp_path),
            },
        ):
            complete("")
        assert log_path.exists()
        content = log_path.read_text()
        assert "__complete_names_in_lockfile" in content

        assert "Error" in content or "error" in content

    def test_valid_toml_invalid_lockfile_schema_returns_empty(self, tmp_path: Path) -> None:
        """Valid TOML that fails lockfile schema validation -> empty + log entry."""
        lock_path = tmp_path / ".kanon.lock"

        lock_path.write_text("schema_version = 5\nfoo = 'bar'\n")
        log_path = tmp_path / "completion-errors.log"
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_LOCK_FILE": str(lock_path),
                "KANON_COMPLETION_LOG": str(log_path),
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete("")
        assert result == []
        assert log_path.exists()


@pytest.mark.unit
class TestCompleteDeepRecursion:
    """complete() extracts include paths from deeply nested lockfile structures."""

    def test_depth_3_includes_extracted(self, tmp_path: Path) -> None:
        """AC-FUNC-008: depth-3 nested includes are all extracted."""
        lock_path = tmp_path / ".kanon.lock"
        include_l3 = _make_include("n3", "deep/level3/spec.xml")
        include_l2 = _make_include("n2", "deep/level2/spec.xml", includes=[include_l3])
        include_l1 = _make_include("n1", "deep/level1/spec.xml", includes=[include_l2])
        lockfile = _make_lockfile(sources=[_make_source("root", includes=[include_l1])])
        write_lockfile(lockfile, lock_path)
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_LOCK_FILE": str(lock_path),
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete("")
        assert "root" in result
        assert "deep/level1/spec.xml" in result
        assert "deep/level2/spec.xml" in result
        assert "deep/level3/spec.xml" in result


@pytest.mark.unit
class TestCompleteLockfilePathResolution:
    """complete() respects the lockfile path resolution precedence."""

    def test_kanon_lock_file_env_used(self, tmp_path: Path) -> None:
        """KANON_LOCK_FILE env var points to the lockfile."""
        lock_path = tmp_path / "custom.lock"
        lockfile = _make_lockfile(sources=[_make_source("mysource")])
        write_lockfile(lockfile, lock_path)
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_LOCK_FILE": str(lock_path),
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = complete("")
        assert result == ["mysource"]

    def test_derived_from_kanon_file_env(self, tmp_path: Path) -> None:
        """When KANON_LOCK_FILE absent, derives path from KANON_KANON_FILE + .lock."""
        kanon_file = tmp_path / ".kanon"
        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile(sources=[_make_source("derived_source")])
        write_lockfile(lockfile, lock_path)
        env = {k: v for k, v in os.environ.items() if k not in ("KANON_LOCK_FILE", "KANON_KANON_FILE")}
        env["KANON_KANON_FILE"] = str(kanon_file)
        env["KANON_COMPLETION_ENABLED"] = "1"
        env["KANON_HOME"] = str(tmp_path)
        with patch.dict(os.environ, env, clear=True):
            result = complete("")
        assert result == ["derived_source"]


@pytest.mark.unit
class TestHandle:
    """_handle() calls complete() and writes one name per line to stdout."""

    def test_handle_prints_names(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """_handle() with valid lockfile prints sorted names to stdout."""
        lock_path = tmp_path / ".kanon.lock"
        lockfile = _make_lockfile(
            sources=[
                _make_source("foo"),
                _make_source("bar"),
            ]
        )
        write_lockfile(lockfile, lock_path)
        args = argparse.Namespace(current_token="")
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_LOCK_FILE": str(lock_path),
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = _handle(args)
        assert result == 0
        captured = capsys.readouterr()
        assert captured.out == "bar\nfoo\n"

    def test_handle_returns_zero(self, tmp_path: Path) -> None:
        """_handle() always returns 0 even when lockfile is missing."""
        lock_path = tmp_path / "missing.lock"
        args = argparse.Namespace(current_token="")
        with patch.dict(
            os.environ,
            {
                "KANON_COMPLETION_ENABLED": "1",
                "KANON_LOCK_FILE": str(lock_path),
                "KANON_HOME": str(tmp_path),
            },
        ):
            result = _handle(args)
        assert result == 0
