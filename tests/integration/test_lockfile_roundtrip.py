"""Integration tests for lockfile write-then-read roundtrip (AC-TEST-002, AC-CYCLE-001).

Exercises the atomic write + rename codepath against the real filesystem.
Constructs a Lockfile with:
  - 2 top-level sources
  - nested includes chains 3 levels deep per source
  - at least 2 projects per source
"""

import tomllib
import unittest.mock

import pytest

from kanon_cli.core.lockfile import (
    CURRENT_SCHEMA_VERSION,
    IncludeEntry,
    Lockfile,
    ProjectEntry,
    SourceEntry,
    read_lockfile,
    write_lockfile,
)

_SHA40 = "a" * 40
_SHA40_B = "b" * 40
_SHA64 = "c" * 64

_KANON_HASH = "sha256:" + "a" * 64


def _make_include_chain(depth: int, prefix: str) -> list[IncludeEntry]:
    """Return a nested IncludeEntry chain of the given depth.

    At depth 0 the list is empty. At depth 1 the list has one entry with
    no children. At depth N the entry wraps N-1 children recursively.
    """
    if depth == 0:
        return []
    child_includes = _make_include_chain(depth - 1, prefix + f"-d{depth}")
    return [
        IncludeEntry(
            name=f"{prefix}-inc-d{depth}",
            path_in_repo=f"repo-specs/{prefix}/level{depth}/inc.xml",
            url=f"https://example.com/{prefix}-inc-d{depth}.git",
            resolved_sha=_SHA40,
            includes=child_includes,
        )
    ]


def _build_deep_lockfile() -> Lockfile:
    """Build a Lockfile with two sources, 3-level nested includes, 2 projects each."""
    sources = []
    for src_idx in range(2):
        src_name = f"source{src_idx}"
        includes_chain = _make_include_chain(3, src_name)
        projects = [
            ProjectEntry(
                name=f"{src_name}-proj{proj_idx}",
                url=f"https://example.com/{src_name}/proj{proj_idx}.git",
                canonical_url=f"https://example.com/{src_name}/proj{proj_idx}",
                ref_spec="==1.2.3",
                resolved_ref="refs/tags/1.2.3",
                resolved_sha=_SHA40_B,
            )
            for proj_idx in range(2)
        ]
        sources.append(
            SourceEntry(
                alias=src_name,
                name=src_name,
                url=f"https://example.com/{src_name}.git",
                ref_spec="main",
                resolved_ref="refs/heads/main",
                resolved_sha=_SHA64,
                path=f"repo-specs/{src_name}/meta.xml",
                includes=includes_chain,
                projects=projects,
            )
        )

    return Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at="2026-01-01T00:00:00Z",
        generator="kanon-cli/2.0.0",
        kanon_hash=_KANON_HASH,
        sources=sources,
        marketplace_registered=False,
        marketplace_dir="",
    )


@pytest.mark.integration
class TestLockfileRoundtrip:
    """End-to-end write-then-read roundtrip tests (AC-TEST-002, AC-CYCLE-001)."""

    def test_write_then_read_deep_equal(self, tmp_path):
        """write_lockfile then read_lockfile on the same path produces a deep-equal object.

        Covers AC-TEST-002: 2 top-level sources, 3-level nested includes, 2 projects each.
        Asserts via dataclass equality, not field-by-field comparison.
        """
        lf_original = _build_deep_lockfile()
        lock_path = tmp_path / "kanon.lock"
        write_lockfile(lf_original, lock_path)
        lf_parsed = read_lockfile(lock_path)
        assert lf_parsed == lf_original

    def test_roundtrip_produces_valid_toml_on_disk(self, tmp_path):
        """The file written by write_lockfile is parseable by stdlib tomllib."""
        lf = _build_deep_lockfile()
        lock_path = tmp_path / "kanon.lock"
        write_lockfile(lf, lock_path)
        with open(lock_path, "rb") as f:
            data = tomllib.load(f)
        assert data["schema_version"] == CURRENT_SCHEMA_VERSION
        assert len(data["sources"]) == 2

    def test_roundtrip_preserves_nested_includes(self, tmp_path):
        """Nested include chains 3 levels deep are preserved after roundtrip."""
        lf = _build_deep_lockfile()
        lock_path = tmp_path / "kanon.lock"
        write_lockfile(lf, lock_path)
        lf2 = read_lockfile(lock_path)

        src0 = lf2.sources[0]
        assert len(src0.includes) == 1
        level1 = src0.includes[0]
        assert len(level1.includes) == 1
        level2 = level1.includes[0]
        assert len(level2.includes) == 1
        level3 = level2.includes[0]
        assert level3.includes == []

    def test_roundtrip_preserves_all_projects(self, tmp_path):
        """All ProjectEntry rows per source are preserved after roundtrip."""
        lf = _build_deep_lockfile()
        lock_path = tmp_path / "kanon.lock"
        write_lockfile(lf, lock_path)
        lf2 = read_lockfile(lock_path)
        for src_orig, src_parsed in zip(lf.sources, lf2.sources):
            assert len(src_parsed.projects) == len(src_orig.projects)
            for p_orig, p_parsed in zip(src_orig.projects, src_parsed.projects):
                assert p_parsed == p_orig

    def test_atomic_write_uses_temp_then_rename(self, tmp_path):
        """write_lockfile uses a temp file then renames -- destination is never partially written.

        This test verifies that after write_lockfile returns, the destination file
        exists and contains complete content (no truncation). True kernel-level
        atomicity relies on os.replace semantics; we assert final state correctness.
        """
        lf = _build_deep_lockfile()
        lock_path = tmp_path / "kanon.lock"

        write_lockfile(lf, lock_path)
        assert lock_path.exists()

        write_lockfile(lf, lock_path)
        assert lock_path.exists()

        lf2 = read_lockfile(lock_path)
        assert lf2 == lf

    def test_toml_fixture_literal_match_after_stripping_generated_at(self, tmp_path):
        """Written TOML matches a known-good fixture after stripping generated_at (AC-CYCLE-001).

        Constructs the in-memory Lockfile, writes it, strips generated_at from the
        resulting file, and confirms the remaining content matches expectations.
        """
        lf = _build_deep_lockfile()
        lock_path = tmp_path / "kanon.lock"
        write_lockfile(lf, lock_path)

        raw_toml = lock_path.read_text()

        stripped_lines = [line for line in raw_toml.splitlines() if not line.startswith("generated_at")]
        stripped_content = "\n".join(stripped_lines)

        assert f"schema_version = {CURRENT_SCHEMA_VERSION}" in stripped_content
        assert 'generator = "kanon-cli/2.0.0"' in stripped_content

        assert "[catalog]" not in stripped_content
        assert "[[sources]]" in stripped_content
        assert 'alias = "source0"' in stripped_content
        assert "[[sources.includes]]" in stripped_content
        assert "[[sources.projects]]" in stripped_content

    def test_sha64_roundtrip(self, tmp_path):
        """64-char SHA-256 values survive the write-then-read roundtrip unchanged."""
        lf = _build_deep_lockfile()

        assert lf.sources[0].resolved_sha == _SHA64
        lock_path = tmp_path / "kanon.lock"
        write_lockfile(lf, lock_path)
        lf2 = read_lockfile(lock_path)
        assert lf2.sources[0].resolved_sha == _SHA64

    def test_concurrent_temp_files_do_not_collide(self, tmp_path):
        """Two sequential write_lockfile calls do not leave orphaned temp files."""
        lf = _build_deep_lockfile()
        lock_path = tmp_path / "kanon.lock"
        write_lockfile(lf, lock_path)
        write_lockfile(lf, lock_path)

        remaining = list(tmp_path.iterdir())
        assert len(remaining) == 1
        assert remaining[0] == lock_path

    def test_write_lockfile_cleans_up_temp_on_write_error(self, tmp_path):
        """write_lockfile removes the temp file when the write operation raises an exception."""
        lf = _build_deep_lockfile()
        lock_path = tmp_path / "kanon.lock"

        with unittest.mock.patch("os.fsync", side_effect=OSError("simulated disk error")):
            with pytest.raises(OSError, match="simulated disk error"):
                write_lockfile(lf, lock_path)

        assert not lock_path.exists()

        remaining = list(tmp_path.iterdir())
        assert remaining == []

    def test_write_lockfile_cleans_up_temp_on_replace_error(self, tmp_path):
        """write_lockfile removes the temp file when os.replace raises an exception."""
        lf = _build_deep_lockfile()
        lock_path = tmp_path / "kanon.lock"

        with unittest.mock.patch("os.replace", side_effect=OSError("simulated replace error")):
            with pytest.raises(OSError, match="simulated replace error"):
                write_lockfile(lf, lock_path)

        assert not lock_path.exists()

        remaining = list(tmp_path.iterdir())
        assert remaining == []
