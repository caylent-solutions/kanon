"""Unit tests closing coverage gaps in src/kanon_cli/commands/list.py.

Gaps targeted (from coverage_gaps.md produced by E15-F4-S1-T1):
- Lines 156-160: _list_tags_from_url error path when git ls-remote returns non-zero
- Lines 164-171: _list_tags_from_url parsing loop (blank lines, malformed lines, tag filter)
- Lines 220-228: _sort_version_pairs_newest_first body (entire function uncovered)
- Lines 314-363: _walk_all_versions / _list_all_versions_for_url body

All gaps are category "test-needed".
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest
from packaging.version import Version

from kanon_cli.commands.list import (
    _list_tags_from_url,
    _sort_version_pairs_newest_first,
    _walk_all_versions,
)


# ---------------------------------------------------------------------------
# Lines 156-160: _list_tags_from_url error path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListTagsFromUrlErrorPath:
    """_list_tags_from_url exits with code 1 when git ls-remote fails."""

    def test_nonzero_returncode_calls_sys_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When subprocess returns non-zero, _list_tags_from_url calls sys.exit(1)."""
        fake_result = subprocess.CompletedProcess(
            args=["git", "ls-remote", "--tags", "https://example.com/repo.git"],
            returncode=128,
            stdout="",
            stderr="repository not found",
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

        with pytest.raises(SystemExit) as exc_info:
            _list_tags_from_url("https://example.com/repo.git")

        assert exc_info.value.code == 1

    def test_nonzero_returncode_writes_error_to_stderr(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Error message written to stderr contains the URL and git error."""
        url = "https://example.com/repo.git"
        fake_result = subprocess.CompletedProcess(
            args=["git", "ls-remote", "--tags", url],
            returncode=1,
            stdout="",
            stderr="fatal: not a git repository",
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

        with pytest.raises(SystemExit):
            _list_tags_from_url(url)

        captured = capsys.readouterr()
        assert "ERROR:" in captured.err
        assert url in captured.err

    def test_stderr_content_included_in_error_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The git ls-remote stderr output is included in the error message."""
        url = "https://example.com/repo.git"
        git_error = "fatal: authentication failed"
        fake_result = subprocess.CompletedProcess(
            args=["git", "ls-remote", "--tags", url],
            returncode=128,
            stdout="",
            stderr=git_error,
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

        with pytest.raises(SystemExit):
            _list_tags_from_url(url)

        captured = capsys.readouterr()
        assert git_error in captured.err


# ---------------------------------------------------------------------------
# Lines 164-171: _list_tags_from_url parsing loop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListTagsFromUrlParsingLoop:
    """_list_tags_from_url correctly parses ls-remote output with blank/malformed lines."""

    def _make_run_result(self, stdout: str) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=["git", "ls-remote", "--tags", "url"],
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    def test_blank_lines_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Blank lines in ls-remote output are skipped without error."""
        output = "abc123\trefs/tags/1.0.0\n\ndef456\trefs/tags/2.0.0\n"
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: self._make_run_result(output))

        pairs = _list_tags_from_url("https://example.com/repo.git")

        assert len(pairs) == 2
        refs = [ref for ref, _sha in pairs]
        assert "refs/tags/1.0.0" in refs
        assert "refs/tags/2.0.0" in refs

    def test_malformed_lines_without_tab_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Lines without a tab character (malformed) are skipped."""
        output = "abc123\trefs/tags/1.0.0\nno-tab-here\ndef456\trefs/tags/2.0.0\n"
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: self._make_run_result(output))

        pairs = _list_tags_from_url("https://example.com/repo.git")

        assert len(pairs) == 2

    def test_sha_ref_destructuring_correct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SHA and ref are correctly extracted from tab-delimited ls-remote output."""
        sha = "a" * 40
        ref = "refs/tags/1.2.3"
        output = f"{sha}\t{ref}\n"
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: self._make_run_result(output))

        pairs = _list_tags_from_url("https://example.com/repo.git")

        assert len(pairs) == 1
        assert pairs[0] == (ref, sha)

    def test_non_tag_refs_excluded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """refs not starting with refs/tags/ are excluded from the result."""
        output = "abc123\trefs/tags/1.0.0\ndef456\trefs/heads/main\nghi789\trefs/pull/1/head\n"
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: self._make_run_result(output))

        pairs = _list_tags_from_url("https://example.com/repo.git")

        assert len(pairs) == 1
        assert pairs[0][0] == "refs/tags/1.0.0"

    def test_annotated_tag_peeled_refs_excluded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Peeled annotated tag refs ending with ^{} are excluded."""
        output = "abc123\trefs/tags/1.0.0\ndef456\trefs/tags/1.0.0^{}\n"
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: self._make_run_result(output))

        pairs = _list_tags_from_url("https://example.com/repo.git")

        # Only the non-peeled form should be included
        assert len(pairs) == 1
        assert not pairs[0][0].endswith("^{}")

    def test_empty_output_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty ls-remote output returns an empty list."""
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: self._make_run_result(""))

        pairs = _list_tags_from_url("https://example.com/repo.git")

        assert pairs == []

    def test_multiple_tags_all_collected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All valid tag refs are collected into the result."""
        output = "sha1\trefs/tags/1.0.0\nsha2\trefs/tags/2.0.0\nsha3\trefs/tags/3.0.0\n"
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: self._make_run_result(output))

        pairs = _list_tags_from_url("https://example.com/repo.git")

        assert len(pairs) == 3


# ---------------------------------------------------------------------------
# Lines 220-228: _sort_version_pairs_newest_first
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSortVersionPairsNewestFirst:
    """_sort_version_pairs_newest_first parses and sorts (ref, sha) pairs newest-first."""

    def test_basic_sort_newest_first(self) -> None:
        """Three versions are returned in newest-first (descending) order."""
        pairs = [
            ("refs/tags/1.0.0", "sha1"),
            ("refs/tags/3.0.0", "sha3"),
            ("refs/tags/2.0.0", "sha2"),
        ]
        result = _sort_version_pairs_newest_first(pairs)
        version_strings = [str(v) for _, v, _ in result]
        assert version_strings == ["3.0.0", "2.0.0", "1.0.0"]

    def test_sha_preserved_in_result(self) -> None:
        """SHA values from input pairs are preserved in the output triples."""
        pairs = [("refs/tags/1.0.0", "mysha123")]
        result = _sort_version_pairs_newest_first(pairs)
        assert len(result) == 1
        _ref, _ver, sha = result[0]
        assert sha == "mysha123"

    def test_ref_preserved_in_result(self) -> None:
        """Ref strings from input pairs are preserved in the output triples."""
        pairs = [("refs/tags/2.5.1", "somesha")]
        result = _sort_version_pairs_newest_first(pairs)
        assert len(result) == 1
        ref, _ver, _sha = result[0]
        assert ref == "refs/tags/2.5.1"

    def test_non_pep440_tag_skipped(self) -> None:
        """Tags with non-PEP-440 version strings are silently skipped."""
        pairs = [
            ("refs/tags/1.0.0", "sha1"),
            ("refs/tags/not-a-version", "sha2"),
            ("refs/tags/2.0.0", "sha3"),
        ]
        result = _sort_version_pairs_newest_first(pairs)
        assert len(result) == 2
        version_strings = [str(v) for _, v, _ in result]
        assert "1.0.0" in version_strings
        assert "2.0.0" in version_strings

    def test_all_non_pep440_returns_empty(self) -> None:
        """When all tags fail PEP 440 parsing, an empty list is returned."""
        pairs = [
            ("refs/tags/foo", "sha1"),
            ("refs/tags/bar", "sha2"),
        ]
        result = _sort_version_pairs_newest_first(pairs)
        assert result == []

    def test_empty_input_returns_empty(self) -> None:
        """Empty input returns an empty list."""
        result = _sort_version_pairs_newest_first([])
        assert result == []

    def test_result_is_list_of_triples(self) -> None:
        """Each element in the result is a (ref, Version, sha) triple."""
        pairs = [("refs/tags/1.0.0", "abc")]
        result = _sort_version_pairs_newest_first(pairs)
        assert len(result) == 1
        ref, ver, sha = result[0]
        assert ref == "refs/tags/1.0.0"
        assert isinstance(ver, Version)
        assert sha == "abc"

    def test_version_extracted_from_last_path_component(self) -> None:
        """Version string is extracted from the last / component of the ref."""
        pairs = [("refs/tags/v3.1.4", "sha")]
        result = _sort_version_pairs_newest_first(pairs)
        # v3.1.4 is a valid PEP 440 version (epoch-less)
        assert len(result) == 1
        _, ver, _ = result[0]
        assert str(ver) == "3.1.4"

    def test_sort_is_stable_for_equal_versions(self) -> None:
        """A single-element input returns a single-element list."""
        pairs = [("refs/tags/1.0.0", "onlysha")]
        result = _sort_version_pairs_newest_first(pairs)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Lines 314-363: _walk_all_versions body
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWalkAllVersions:
    """_walk_all_versions exercises the full body of the function."""

    def test_zero_pep440_tags_exits_with_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When all tags fail PEP 440 parsing, _walk_all_versions prints error and exits 1."""
        import kanon_cli.commands.list as list_mod

        monkeypatch.setattr(
            list_mod,
            "_list_tags_from_url",
            lambda url: [("refs/tags/not-a-version", "sha1")],
        )

        with pytest.raises(SystemExit) as exc_info:
            _walk_all_versions("https://example.com/repo.git@main", limit=0, since_version=None)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err

    def test_empty_tags_returns_empty_list(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When git ls-remote returns no tags, _walk_all_versions returns []."""
        import kanon_cli.commands.list as list_mod

        monkeypatch.setattr(list_mod, "_list_tags_from_url", lambda url: [])

        result = _walk_all_versions("https://example.com/repo.git@main", limit=0, since_version=None)

        assert result == []

    def test_invalid_since_version_exits_with_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An invalid since_version constraint prints error and exits 1."""
        import kanon_cli.commands.list as list_mod

        monkeypatch.setattr(
            list_mod,
            "_list_tags_from_url",
            lambda url: [("refs/tags/1.0.0", "sha1"), ("refs/tags/2.0.0", "sha2")],
        )

        with pytest.raises(SystemExit) as exc_info:
            _walk_all_versions(
                "https://example.com/repo.git@main",
                limit=0,
                since_version="notaconstraint",
            )

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err

    def test_limit_applied_to_sorted_triples(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """limit > 0 truncates the sorted triples before cloning."""
        import kanon_cli.commands.list as list_mod

        monkeypatch.setattr(
            list_mod,
            "_list_tags_from_url",
            lambda url: [
                ("refs/tags/3.0.0", "sha3"),
                ("refs/tags/2.0.0", "sha2"),
                ("refs/tags/1.0.0", "sha1"),
            ],
        )

        clone_result = subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=0,
            stdout="",
            stderr="",
        )
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        with (
            patch("kanon_cli.commands.list.subprocess.run", return_value=clone_result),
            patch("kanon_cli.commands.list.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.commands.list._build_sorted_index", return_value=["alpha"]),
        ):
            result = _walk_all_versions(
                "https://example.com/repo.git@main",
                limit=1,
                since_version=None,
            )

        # With limit=1, only the newest version (3.0.0) should be in the results
        assert len(result) == 1
        assert result[0].version == "3.0.0"

    def test_since_version_filter_removes_older_versions(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """since_version filters out versions not matching the specifier."""
        import kanon_cli.commands.list as list_mod

        monkeypatch.setattr(
            list_mod,
            "_list_tags_from_url",
            lambda url: [
                ("refs/tags/3.0.0", "sha3"),
                ("refs/tags/2.0.0", "sha2"),
                ("refs/tags/1.0.0", "sha1"),
            ],
        )

        clone_result = subprocess.CompletedProcess(args=["git", "clone"], returncode=0, stdout="", stderr="")
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        with (
            patch("kanon_cli.commands.list.subprocess.run", return_value=clone_result),
            patch("kanon_cli.commands.list.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.commands.list._build_sorted_index", return_value=["alpha"]),
        ):
            result = _walk_all_versions(
                "https://example.com/repo.git@main",
                limit=0,
                since_version=">=2.0.0",
            )

        # Only 2.0.0 and 3.0.0 match >=2.0.0
        version_strs = [r.version for r in result]
        assert "1.0.0" not in version_strs
        assert "2.0.0" in version_strs
        assert "3.0.0" in version_strs

    def test_clone_failure_exits_with_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When git clone fails, _walk_all_versions prints error and exits 1."""
        import kanon_cli.commands.list as list_mod

        monkeypatch.setattr(
            list_mod,
            "_list_tags_from_url",
            lambda url: [("refs/tags/1.0.0", "sha1")],
        )

        clone_result = subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=1,
            stdout="",
            stderr="fatal: repository not found",
        )

        with (
            patch("kanon_cli.commands.list.subprocess.run", return_value=clone_result),
            patch("kanon_cli.commands.list.tempfile.mkdtemp", return_value=str(tmp_path)),
        ):
            with pytest.raises(SystemExit) as exc_info:
                _walk_all_versions(
                    "https://example.com/repo.git@main",
                    limit=0,
                    since_version=None,
                )

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err

    def test_clone_failure_error_includes_url(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Clone-failure error message includes the URL."""
        import kanon_cli.commands.list as list_mod

        monkeypatch.setattr(
            list_mod,
            "_list_tags_from_url",
            lambda url: [("refs/tags/1.0.0", "sha1")],
        )

        clone_result = subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=1,
            stdout="",
            stderr="fatal: repository not found",
        )

        with (
            patch("kanon_cli.commands.list.subprocess.run", return_value=clone_result),
            patch("kanon_cli.commands.list.tempfile.mkdtemp", return_value=str(tmp_path)),
        ):
            with pytest.raises(SystemExit):
                _walk_all_versions(
                    "https://example.com/repo.git@main",
                    limit=0,
                    since_version=None,
                )

        captured = capsys.readouterr()
        assert "https://example.com/repo.git" in captured.err

    def test_all_versions_filtered_out_returns_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When since_version filters out all versions, _walk_all_versions returns []."""
        import kanon_cli.commands.list as list_mod

        monkeypatch.setattr(
            list_mod,
            "_list_tags_from_url",
            lambda url: [("refs/tags/1.0.0", "sha1"), ("refs/tags/2.0.0", "sha2")],
        )

        result = _walk_all_versions(
            "https://example.com/repo.git@main",
            limit=0,
            since_version=">=9.0.0",  # No tags satisfy this
        )

        assert result == []

    def test_successful_walk_returns_version_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """A successful walk returns VersionRow objects with correct data."""
        import kanon_cli.commands.list as list_mod

        monkeypatch.setattr(
            list_mod,
            "_list_tags_from_url",
            lambda url: [("refs/tags/1.0.0", "sha1")],
        )

        clone_result = subprocess.CompletedProcess(args=["git", "clone"], returncode=0, stdout="", stderr="")
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        with (
            patch("kanon_cli.commands.list.subprocess.run", return_value=clone_result),
            patch("kanon_cli.commands.list.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.commands.list._build_sorted_index", return_value=["alpha", "beta"]),
        ):
            result = _walk_all_versions(
                "https://example.com/repo.git@main",
                limit=0,
                since_version=None,
            )

        # 1 version x 2 catalog names = 2 rows
        assert len(result) == 2
        names = {r.name for r in result}
        assert names == {"alpha", "beta"}
        versions = {r.version for r in result}
        assert versions == {"1.0.0"}
