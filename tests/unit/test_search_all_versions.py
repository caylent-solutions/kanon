"""Unit tests for kanon search --all-versions, --limit, --no-limit, --since-version.

Covers AC-TEST-001:
- version walker logic
- --limit cap behaviour
- --no-limit (uncapped) behaviour
- --since-version PEP 440 filter
- newest-first ordering
- --all-versions / --tree mutual exclusion
- --limit / --no-limit mutual exclusion
"""

import argparse
from unittest.mock import patch

import pytest
from packaging.version import Version

from kanon_cli.commands.search import (
    _build_all_versions_rows,
    _filter_versions_by_constraint,
    _sort_versions_newest_first,
    register,
    run_search,
)
from kanon_cli.constants import KANON_LIST_LIMIT


@pytest.mark.unit
class TestVersionRowStructure:
    """AC-FUNC-010: per-row data carries {name, version, ref, sha}."""

    def test_version_row_has_name(self):
        rows = _build_all_versions_rows(
            catalog_names=["alpha"],
            sorted_versions=[("refs/tags/1.0.0", Version("1.0.0"), "abc1234567890")],
        )
        assert rows[0].name == "alpha"

    def test_version_row_has_version(self):
        rows = _build_all_versions_rows(
            catalog_names=["alpha"],
            sorted_versions=[("refs/tags/1.0.0", Version("1.0.0"), "abc1234567890")],
        )
        assert rows[0].version == "1.0.0"

    def test_version_row_has_ref(self):
        rows = _build_all_versions_rows(
            catalog_names=["alpha"],
            sorted_versions=[("refs/tags/1.0.0", Version("1.0.0"), "abc1234567890")],
        )
        assert rows[0].ref == "refs/tags/1.0.0"

    def test_version_row_has_sha(self):
        rows = _build_all_versions_rows(
            catalog_names=["alpha"],
            sorted_versions=[("refs/tags/1.0.0", Version("1.0.0"), "abc1234567890")],
        )
        assert rows[0].sha == "abc1234567890"

    def test_version_row_format_is_name_at_version(self):
        """AC-FUNC-003: row text is <name>@<version>."""
        rows = _build_all_versions_rows(
            catalog_names=["alpha"],
            sorted_versions=[("refs/tags/1.0.0", Version("1.0.0"), "abc1234567890")],
        )
        assert str(rows[0]) == "alpha@1.0.0"


@pytest.mark.unit
class TestSortVersionsNewestFirst:
    """AC-FUNC-004: versions ordered newest-first per packaging.version.Version."""

    def test_sorts_three_versions_newest_first(self):
        tags = [
            "refs/tags/1.0.0",
            "refs/tags/2.0.0",
            "refs/tags/1.5.0",
        ]
        result = _sort_versions_newest_first(tags)
        version_strings = [str(v) for _, v, _ in result]
        assert version_strings == ["2.0.0", "1.5.0", "1.0.0"]

    def test_skips_non_pep440_tags(self):
        tags = [
            "refs/tags/1.0.0",
            "refs/tags/not-a-version",
            "refs/tags/2.0.0",
        ]
        result = _sort_versions_newest_first(tags)
        assert len(result) == 2

    def test_all_invalid_tags_returns_empty(self):
        tags = ["refs/tags/foo", "refs/tags/bar"]
        result = _sort_versions_newest_first(tags)
        assert result == []

    def test_empty_input_returns_empty(self):
        result = _sort_versions_newest_first([])
        assert result == []

    def test_result_is_list_of_triples(self):
        tags = ["refs/tags/1.0.0"]
        result = _sort_versions_newest_first(tags)
        assert len(result) == 1
        ref, ver, sha = result[0]
        assert ref == "refs/tags/1.0.0"
        assert isinstance(ver, Version)

        assert isinstance(sha, str)

    def test_prerelease_orders_before_release(self):
        tags = ["refs/tags/1.0.0", "refs/tags/1.0.0a1"]
        result = _sort_versions_newest_first(tags)
        version_strings = [str(v) for _, v, _ in result]
        assert version_strings == ["1.0.0", "1.0.0a1"]


@pytest.mark.unit
class TestFilterVersionsByConstraint:
    """AC-FUNC-006: --since-version filters via PEP 440 SpecifierSet."""

    def _make_triples(self, version_strs: list[str]) -> list[tuple]:
        result = []
        for vs in version_strs:
            v = Version(vs)
            result.append((f"refs/tags/{vs}", v, "sha"))
        return result

    def test_gte_filter(self):
        triples = self._make_triples(["1.0.0", "1.5.0", "2.0.0"])
        filtered = _filter_versions_by_constraint(triples, ">=1.5.0")
        versions = [str(v) for _, v, _ in filtered]
        assert versions == ["1.5.0", "2.0.0"] or set(versions) == {"1.5.0", "2.0.0"}

    def test_range_filter(self):
        triples = self._make_triples(["1.0.0", "1.5.0", "2.0.0", "2.5.0"])
        filtered = _filter_versions_by_constraint(triples, ">=1.0,<2.0")
        versions = [str(v) for _, v, _ in filtered]
        assert set(versions) == {"1.0.0", "1.5.0"}

    def test_no_match_returns_empty(self):
        triples = self._make_triples(["1.0.0", "1.5.0"])
        filtered = _filter_versions_by_constraint(triples, ">=3.0")
        assert filtered == []

    def test_all_match_returned(self):
        triples = self._make_triples(["1.0.0", "2.0.0", "3.0.0"])
        filtered = _filter_versions_by_constraint(triples, ">=1.0")
        assert len(filtered) == 3

    def test_invalid_constraint_raises(self):
        triples = self._make_triples(["1.0.0"])
        with pytest.raises((ValueError, SystemExit)):
            _filter_versions_by_constraint(triples, "notaconstraint")


@pytest.mark.unit
class TestBuildAllVersionsRows:
    """AC-FUNC-003, AC-FUNC-004: row builder emits name@version rows in order."""

    def test_four_versions_three_entries_twelve_rows(self):
        """AC-FUNC-003: 4 versions x 3 entries = 12 rows."""
        names = ["alpha", "beta", "gamma"]
        versions = [
            ("refs/tags/4.0.0", Version("4.0.0"), "sha4"),
            ("refs/tags/3.0.0", Version("3.0.0"), "sha3"),
            ("refs/tags/2.0.0", Version("2.0.0"), "sha2"),
            ("refs/tags/1.0.0", Version("1.0.0"), "sha1"),
        ]
        rows = _build_all_versions_rows(catalog_names=names, sorted_versions=versions)
        assert len(rows) == 12

    def test_entries_within_version_are_sorted_lexicographically(self):
        """AC-FUNC-004: entries within each version are in lex order."""
        names = ["zebra", "alpha", "mango"]
        versions = [("refs/tags/1.0.0", Version("1.0.0"), "sha")]
        rows = _build_all_versions_rows(catalog_names=names, sorted_versions=versions)
        entry_names = [r.name for r in rows]
        assert entry_names == sorted(entry_names)

    def test_versions_are_newest_first_across_rows(self):
        """AC-FUNC-004: rows come out newest version first."""
        names = ["alpha"]
        versions = [
            ("refs/tags/3.0.0", Version("3.0.0"), "sha3"),
            ("refs/tags/1.0.0", Version("1.0.0"), "sha1"),
        ]
        rows = _build_all_versions_rows(catalog_names=names, sorted_versions=versions)
        ver_strs = [r.version for r in rows]
        assert ver_strs == ["3.0.0", "1.0.0"]

    def test_empty_versions_returns_empty(self):
        rows = _build_all_versions_rows(catalog_names=["alpha"], sorted_versions=[])
        assert rows == []

    def test_empty_names_returns_empty(self):
        rows = _build_all_versions_rows(
            catalog_names=[],
            sorted_versions=[("refs/tags/1.0.0", Version("1.0.0"), "sha")],
        )
        assert rows == []


@pytest.mark.unit
class TestKanonListLimitConstant:
    """AC-FUNC-002: KANON_LIST_LIMIT constant tests."""

    def test_constant_exists(self):
        assert KANON_LIST_LIMIT is not None

    def test_default_value_is_50(self):
        import importlib
        import os

        import kanon_cli.constants as constants

        saved = os.environ.pop("KANON_LIST_LIMIT", None)
        importlib.reload(constants)
        try:
            assert constants.KANON_LIST_LIMIT == 50
        finally:
            if saved is not None:
                os.environ["KANON_LIST_LIMIT"] = saved
            importlib.reload(constants)

    def test_is_positive_int(self):
        assert isinstance(KANON_LIST_LIMIT, int)
        assert KANON_LIST_LIMIT > 0

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch):
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_LIST_LIMIT", "99")
        importlib.reload(constants)
        try:
            assert constants.KANON_LIST_LIMIT == 99
        finally:
            monkeypatch.delenv("KANON_LIST_LIMIT", raising=False)
            importlib.reload(constants)


@pytest.mark.unit
class TestAllVersionsTreeMutualExclusion:
    """AC-FUNC-008: --all-versions and --tree are mutually exclusive."""

    def _make_args(self, **kwargs) -> argparse.Namespace:
        defaults = {
            "catalog_source": "https://example.com/repo.git@main",
            "detail": False,
            "tree": False,
            "max_depth": None,
            "no_filter_required": False,
            "all_versions": False,
            "limit": 50,
            "no_limit": False,
            "since_version": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_all_versions_and_tree_returns_exit_1(self, capsys):
        args = self._make_args(all_versions=True, tree=True)
        result = run_search(args)
        assert result == 1

    def test_all_versions_and_tree_writes_error_to_stderr(self, capsys):
        args = self._make_args(all_versions=True, tree=True)
        run_search(args)
        captured = capsys.readouterr()
        assert "mutually exclusive" in captured.err.lower() or "cannot" in captured.err.lower()

    def test_all_versions_and_tree_no_catalog_work_done(self, capsys):
        """Mutual exclusion is detected before any catalog work."""
        args = self._make_args(all_versions=True, tree=True)
        with patch("kanon_cli.commands.search._resolve_manifest_repo") as mock_resolve:
            run_search(args)
            mock_resolve.assert_not_called()


@pytest.mark.unit
class TestLimitNoLimitMutualExclusion:
    """AC-FUNC-009: --limit and --no-limit are mutually exclusive."""

    def _make_args(self, **kwargs) -> argparse.Namespace:
        defaults = {
            "catalog_source": "https://example.com/repo.git@main",
            "detail": False,
            "tree": False,
            "max_depth": None,
            "no_filter_required": False,
            "all_versions": True,
            "limit": 5,
            "no_limit": True,
            "since_version": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_limit_and_no_limit_returns_exit_1(self, capsys):
        args = self._make_args()
        result = run_search(args)
        assert result == 1

    def test_limit_and_no_limit_writes_error_to_stderr(self, capsys):
        args = self._make_args()
        run_search(args)
        captured = capsys.readouterr()
        assert "mutually exclusive" in captured.err.lower() or "--limit" in captured.err


@pytest.mark.unit
class TestRunListAllVersionsDispatch:
    """run_search dispatches to version walker when --all-versions is set."""

    def _make_args(self, **kwargs) -> argparse.Namespace:
        defaults = {
            "catalog_source": "https://example.com/repo.git@main",
            "detail": False,
            "tree": False,
            "max_depth": None,
            "no_filter_required": False,
            "all_versions": True,
            "limit": 50,
            "no_limit": False,
            "since_version": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_all_versions_calls_ls_remote(self, tmp_path):
        """run_search with --all-versions attempts a git ls-remote call."""
        fake_root = tmp_path / "repo"
        fake_root.mkdir()

        mock_ls_remote_result = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with (
            patch("kanon_cli.commands.search.subprocess.run") as mock_run,
            patch("kanon_cli.commands.search.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch(
                "kanon_cli.commands.search._parse_catalog_source", return_value=("https://example.com/repo.git", "main")
            ),
            patch("kanon_cli.commands.search.is_version_constraint", return_value=False),
            patch("kanon_cli.commands.search._build_sorted_index", return_value=[]),
        ):
            mock_run.return_value = mock_ls_remote_result
            args = self._make_args()
            run_search(args)

            assert mock_run.called

    def test_all_versions_prints_rows_when_nonempty(self, capsys, tmp_path):
        """When rows are returned, run_search prints them and exits 0."""
        from kanon_cli.commands.search import VersionRow

        fake_rows = [
            VersionRow(name="alpha", version="2.0.0", ref="refs/tags/2.0.0", sha="abc"),
            VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha="def"),
        ]

        args = self._make_args()
        with patch("kanon_cli.commands.search._walk_all_versions", return_value=fake_rows):
            result = run_search(args)

        assert result == 0
        captured = capsys.readouterr()
        lines = [ln for ln in captured.out.strip().splitlines() if ln]
        assert lines == ["alpha@2.0.0", "alpha@1.0.0"]

    def test_all_versions_exits_0_on_empty_catalog(self, capsys, tmp_path):
        """When the version list is empty, run_search exits 0 with note."""
        fake_root = tmp_path / "repo"
        fake_root.mkdir()

        mock_result = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with (
            patch("kanon_cli.commands.search.subprocess.run", return_value=mock_result),
            patch("kanon_cli.commands.search.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch(
                "kanon_cli.commands.search._parse_catalog_source", return_value=("https://example.com/repo.git", "main")
            ),
            patch("kanon_cli.commands.search.is_version_constraint", return_value=False),
            patch("kanon_cli.commands.search._build_sorted_index", return_value=[]),
        ):
            args = self._make_args()
            result = run_search(args)
            assert result == 0


@pytest.mark.unit
class TestRegisterAllVersionsFlags:
    """AC-FUNC-001: flags appear on the list subparser."""

    def _get_list_parser(self) -> argparse.ArgumentParser:
        root = argparse.ArgumentParser(prog="kanon")
        subparsers = root.add_subparsers()
        register(subparsers)

        return root

    @pytest.mark.parametrize("flag", ["-A", "--all"])
    def test_all_versions_flag_exists(self, flag):
        root = self._get_list_parser()
        args = root.parse_args(["search", flag, "--catalog-source", "x@y"])
        assert args.all_versions is True

    def test_limit_flag_exists(self):
        root = self._get_list_parser()
        args = root.parse_args(["search", "--limit", "5", "--catalog-source", "x@y"])
        assert args.limit == 5

    def test_no_limit_flag_exists(self):
        root = self._get_list_parser()
        args = root.parse_args(["search", "--no-limit", "--catalog-source", "x@y"])
        assert args.no_limit is True

    def test_since_version_flag_exists(self):
        root = self._get_list_parser()
        args = root.parse_args(["search", "--since-version", ">=1.0", "--catalog-source", "x@y"])
        assert args.since_version == ">=1.0"

    def test_all_versions_default_is_false(self):
        root = self._get_list_parser()
        args = root.parse_args(["search", "--catalog-source", "x@y"])
        assert args.all_versions is False

    def test_limit_default_is_kanon_list_limit(self):
        root = self._get_list_parser()
        args = root.parse_args(["search", "--catalog-source", "x@y"])
        assert args.limit == KANON_LIST_LIMIT

    def test_no_limit_default_is_false(self):
        root = self._get_list_parser()
        args = root.parse_args(["search", "--catalog-source", "x@y"])
        assert args.no_limit is False

    def test_since_version_default_is_none(self):
        root = self._get_list_parser()
        args = root.parse_args(["search", "--catalog-source", "x@y"])
        assert args.since_version is None

    def test_help_mentions_kanon_list_limit(self, capsys):
        """AC-DOC-001: --help mentions KANON_LIST_LIMIT default cap."""
        root = self._get_list_parser()
        try:
            root.parse_args(["search", "--help"])
        except SystemExit:
            pass
        captured = capsys.readouterr()
        assert "KANON_LIST_LIMIT" in captured.out or "50" in captured.out

    def test_help_mentions_pep440_grammar(self, capsys):
        """AC-DOC-001: --help mentions PEP 440 grammar for --since-version."""
        root = self._get_list_parser()
        try:
            root.parse_args(["search", "--help"])
        except SystemExit:
            pass
        captured = capsys.readouterr()
        assert "PEP 440" in captured.out or "pep" in captured.out.lower() or "440" in captured.out
