"""Unit tests for the filter framework added to ``kanon search``.

Covers:
- Substring matcher (case-sensitive, all four default fields, parameterised).
- Regex matcher across the four default fields.
- ``--match-fields`` narrowing.
- Every mutual-exclusion error (substring+regex, match-fields without filter,
  unknown field name in match-fields).
- Zero-match stderr note ("0 entries match filter").

AC-TEST-001, AC-TEST-004, AC-TEST-006
"""

import argparse
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from kanon_cli.commands.search import (
    LIST_FILTER_ZERO_MATCH_NOTE,
    MATCH_FIELDS_LEGAL,
    _apply_filter,
    _build_filter_predicate,
    _check_tree_guardrail,
    register,
    run_search,
)
from kanon_cli.core.metadata import CatalogMetadata


def _make_entry(
    name: str = "my-entry",
    display_name: str = "My Entry",
    description: str = "A short description.",
    keywords: list[str] | None = None,
) -> CatalogMetadata:
    """Build a CatalogMetadata instance for testing.

    Args:
        name: Catalog entry name.
        display_name: Human-readable display name.
        description: Short prose description.
        keywords: Optional keyword list. Defaults to an empty list.

    Returns:
        Populated :class:`CatalogMetadata` instance.
    """
    return CatalogMetadata(
        name=name,
        display_name=display_name,
        description=description,
        version="1.0.0",
        keywords=keywords if keywords is not None else [],
    )


@pytest.mark.unit
class TestBuildFilterPredicateSubstring:
    """Tests for the substring filter path in ``_build_filter_predicate``."""

    @pytest.mark.parametrize(
        "field_name,field_value,substring,should_match",
        [
            ("name", "foo-lib", "foo", True),
            ("name", "other-lib", "foo", False),
            ("display_name", "Foo Library", "Foo", True),
            ("display_name", "Other Library", "Foo", False),
            ("description", "A foo widget for testing", "foo", True),
            ("description", "A bar widget for testing", "foo", False),
            ("keywords", ["alpha", "foo", "beta"], "foo", True),
            ("keywords", ["alpha", "bar", "beta"], "foo", False),
        ],
    )
    def test_substring_matches_each_default_field(
        self,
        field_name: str,
        field_value: Any,
        substring: str,
        should_match: bool,
    ) -> None:
        """Substring filter is case-sensitive and checks each default field."""
        kwargs: dict[str, Any] = {
            "name": "name-val",
            "display_name": "Display Val",
            "description": "desc val",
            "keywords": [],
        }
        kwargs[field_name] = field_value
        entry = _make_entry(**kwargs)

        predicate = _build_filter_predicate(substring=substring, regex=None, match_fields=None)
        assert predicate(entry) is should_match

    def test_substring_case_sensitive(self) -> None:
        """Substring filter is case-sensitive: 'Foo' does not match 'foo'."""
        entry = _make_entry(name="foo-lib")
        predicate = _build_filter_predicate(substring="Foo", regex=None, match_fields=None)
        assert predicate(entry) is False

    def test_substring_matches_if_any_field_matches(self) -> None:
        """Filter returns True when the substring is found in at least one field."""
        entry = _make_entry(
            name="unrelated",
            display_name="Unrelated",
            description="Contains foo here",
            keywords=[],
        )
        predicate = _build_filter_predicate(substring="foo", regex=None, match_fields=None)
        assert predicate(entry) is True

    def test_substring_no_match_returns_false(self) -> None:
        """Filter returns False when no field contains the substring."""
        entry = _make_entry(
            name="bar-lib",
            display_name="Bar Library",
            description="Nothing here.",
            keywords=["baz"],
        )
        predicate = _build_filter_predicate(substring="foo", regex=None, match_fields=None)
        assert predicate(entry) is False


@pytest.mark.unit
class TestBuildFilterPredicateRegex:
    """Tests for the regex filter path in ``_build_filter_predicate``."""

    @pytest.mark.parametrize(
        "field_name,field_value,pattern,should_match",
        [
            ("name", "foobar", "^foo", True),
            ("name", "barfoo", "^foo", False),
            ("display_name", "Foo Library", "^Foo", True),
            ("display_name", "Library Foo", "^Foo", False),
            ("description", "fooish entry", "foo", True),
            ("description", "bar entry", "foo", False),
            ("keywords", ["alpha", "foobar"], "foo", True),
            ("keywords", ["alpha", "bar"], "foo", False),
        ],
    )
    def test_regex_matches_each_default_field(
        self,
        field_name: str,
        field_value: Any,
        pattern: str,
        should_match: bool,
    ) -> None:
        """Regex filter uses re.search and checks each default field."""
        kwargs: dict[str, Any] = {
            "name": "name-val",
            "display_name": "Display Val",
            "description": "desc val",
            "keywords": [],
        }
        kwargs[field_name] = field_value
        entry = _make_entry(**kwargs)

        predicate = _build_filter_predicate(substring=None, regex=pattern, match_fields=None)
        assert predicate(entry) is should_match

    def test_regex_keywords_matches_any_element(self) -> None:
        """Regex matches when any single keyword element satisfies re.search."""
        entry = _make_entry(keywords=["alpha", "beta", "gamma"])

        predicate = _build_filter_predicate(substring=None, regex="bet", match_fields=None)
        assert predicate(entry) is True

    def test_regex_keywords_no_match_when_none_match(self) -> None:
        """Regex returns False when no keyword element satisfies re.search."""
        entry = _make_entry(keywords=["alpha", "beta", "gamma"])
        predicate = _build_filter_predicate(substring=None, regex="delta", match_fields=None)
        assert predicate(entry) is False

    def test_regex_anchored_start(self) -> None:
        """Regex with '^' anchor matches only when field starts with pattern."""
        entry_match = _make_entry(name="foobar")
        entry_no_match = _make_entry(name="barfoo")
        predicate = _build_filter_predicate(substring=None, regex="^foo", match_fields=None)
        assert predicate(entry_match) is True
        assert predicate(entry_no_match) is False


@pytest.mark.unit
class TestBuildFilterPredicateMatchFields:
    """Tests for the ``--match-fields`` narrowing logic."""

    def test_match_fields_name_only(self) -> None:
        """Filter checks only 'name' when match_fields=['name']."""
        entry = _make_entry(
            name="foobar",
            display_name="Other Display",
            description="Other desc",
            keywords=["other"],
        )
        predicate = _build_filter_predicate(substring="foo", regex=None, match_fields=["name"])
        assert predicate(entry) is True

    def test_match_fields_name_only_no_match_on_other_fields(self) -> None:
        """When match_fields=['name'], a match in description does not count."""
        entry = _make_entry(
            name="bar",
            display_name="Other Display",
            description="Contains foo",
            keywords=["foo"],
        )
        predicate = _build_filter_predicate(substring="foo", regex=None, match_fields=["name"])
        assert predicate(entry) is False

    def test_match_fields_description_only(self) -> None:
        """Filter checks only 'description' when match_fields=['description']."""
        entry = _make_entry(
            name="bar",
            display_name="bar display",
            description="Foo related entry",
            keywords=[],
        )
        predicate = _build_filter_predicate(substring="Foo", regex=None, match_fields=["description"])
        assert predicate(entry) is True

    def test_match_fields_keywords_only(self) -> None:
        """Filter checks only keywords when match_fields=['keywords']."""
        entry = _make_entry(
            name="bar",
            display_name="bar display",
            description="nothing",
            keywords=["foo", "baz"],
        )
        predicate = _build_filter_predicate(substring="foo", regex=None, match_fields=["keywords"])
        assert predicate(entry) is True

    def test_match_fields_keywords_only_no_match_on_name(self) -> None:
        """When match_fields=['keywords'], a match in name does not count."""
        entry = _make_entry(
            name="foo",
            display_name="bar display",
            description="nothing",
            keywords=["bar"],
        )
        predicate = _build_filter_predicate(substring="foo", regex=None, match_fields=["keywords"])
        assert predicate(entry) is False

    def test_match_fields_multiple_fields(self) -> None:
        """match_fields with two fields restricts search to both."""
        entry = _make_entry(
            name="bar",
            display_name="Foo Library",
            description="nothing",
            keywords=[],
        )
        predicate = _build_filter_predicate(substring="foo", regex=None, match_fields=["name", "display-name"])

        assert predicate(entry) is False

    def test_match_fields_regex_narrowed(self) -> None:
        """--match-fields works with regex filter too."""
        entry = _make_entry(
            name="my-entry",
            display_name="nothing",
            description="nothing",
            keywords=["foobaz"],
        )
        predicate = _build_filter_predicate(substring=None, regex="^foo", match_fields=["keywords"])
        assert predicate(entry) is True


@pytest.mark.unit
class TestApplyFilter:
    """Tests for ``_apply_filter`` that applies a predicate to a list."""

    def test_returns_matching_subset(self) -> None:
        """_apply_filter keeps only entries matching the predicate."""
        entries = [
            _make_entry(name="foo-a"),
            _make_entry(name="bar-b"),
            _make_entry(name="foo-c"),
        ]
        predicate = _build_filter_predicate(substring="foo", regex=None, match_fields=None)
        result = _apply_filter(entries, predicate)
        assert [e.name for e in result] == ["foo-a", "foo-c"]

    def test_returns_empty_list_when_none_match(self) -> None:
        """_apply_filter returns an empty list when no entries match."""
        entries = [_make_entry(name="bar"), _make_entry(name="baz")]
        predicate = _build_filter_predicate(substring="foo", regex=None, match_fields=None)
        result = _apply_filter(entries, predicate)
        assert result == []

    def test_preserves_order(self) -> None:
        """_apply_filter preserves the order of matching entries."""
        entries = [
            _make_entry(name="foo-z"),
            _make_entry(name="foo-a"),
            _make_entry(name="foo-m"),
        ]
        predicate = _build_filter_predicate(substring="foo", regex=None, match_fields=None)
        result = _apply_filter(entries, predicate)
        assert [e.name for e in result] == ["foo-z", "foo-a", "foo-m"]


@pytest.mark.unit
class TestMatchFieldsLegalConstant:
    """Tests for the MATCH_FIELDS_LEGAL exported constant."""

    def test_contains_all_four_fields(self) -> None:
        """MATCH_FIELDS_LEGAL contains the four spec-defined field names."""
        assert set(MATCH_FIELDS_LEGAL) == {"name", "display-name", "description", "keywords"}


@pytest.mark.unit
class TestZeroMatchNote:
    """Tests for the LIST_FILTER_ZERO_MATCH_NOTE constant (spec canonical phrasing)."""

    def test_zero_match_note_exact_text(self) -> None:
        """LIST_FILTER_ZERO_MATCH_NOTE matches the spec canonical phrasing."""
        assert LIST_FILTER_ZERO_MATCH_NOTE == "0 entries match filter"


@pytest.mark.unit
class TestCheckTreeGuardrailFilterPresent:
    """Tests that _check_tree_guardrail respects the filter_present flag."""

    def test_guardrail_skipped_when_filter_present(self) -> None:
        """Guardrail returns None when filter_present=True even above threshold."""

        result = _check_tree_guardrail(
            entry_count=999,
            max_depth=None,
            no_filter_required=False,
            filter_present=True,
        )
        assert result is None

    def test_guardrail_fires_when_no_filter_and_above_threshold(self) -> None:
        """Guardrail returns an error string when no filter and count exceeds threshold."""
        result = _check_tree_guardrail(
            entry_count=999,
            max_depth=None,
            no_filter_required=False,
            filter_present=False,
        )
        assert result is not None
        assert "ERROR:" in result


@pytest.mark.unit
class TestBuildFilterPredicateDefensiveGuard:
    """Tests for the defensive guard when both substring and regex are None."""

    def test_raises_value_error_when_both_none(self) -> None:
        """_build_filter_predicate raises ValueError when both substring and regex are None."""
        with pytest.raises(ValueError, match="exactly one of substring or regex"):
            _build_filter_predicate(substring=None, regex=None, match_fields=None)


@pytest.mark.unit
class TestInvalidRegexPattern:
    """Tests for the fail-fast error when an invalid --regex pattern is supplied."""

    def test_invalid_regex_returns_1(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search returns 1 when --regex receives a syntactically invalid pattern."""
        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            regex="[unclosed",
        )
        result = run_search(args)
        assert result == 1

    def test_invalid_regex_writes_error_to_stderr(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search writes ERROR: to stderr when --regex receives an invalid pattern."""
        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            regex="[unclosed",
        )
        result = run_search(args)
        captured = capsys.readouterr()
        assert result == 1
        assert "ERROR:" in captured.err
        assert "[unclosed" in captured.err

    def test_invalid_regex_fires_before_catalog_work(self, capsys: pytest.CaptureFixture) -> None:
        """The invalid-regex check fires without a catalog source (before catalog resolution)."""
        args = _make_args(
            catalog_source=None,
            regex="[unclosed",
        )
        result = run_search(args)
        captured = capsys.readouterr()
        assert result == 1
        assert "ERROR:" in captured.err


_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>Description for {name}.</description>
        <version>1.0.0</version>
        <type>plugin</type>
        <owner-name>Tester</owner-name>
        <owner-email>tester@example.com</owner-email>
        <keywords>test</keywords>
      </catalog-metadata>
    </manifest>
""")


def _write_xml(directory: Path, name: str) -> Path:
    """Write a minimal marketplace XML for ``name`` in ``directory``.

    Args:
        directory: Target directory.
        name: Catalog entry name.

    Returns:
        Path to the written XML file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}-marketplace.xml"
    path.write_text(_XML_TEMPLATE.format(name=name))
    return path


def _make_args(**kwargs: Any) -> argparse.Namespace:
    """Build an argparse Namespace with default values appropriate for run_search tests.

    Keyword arguments override the defaults.

    Args:
        **kwargs: Overrides for specific namespace fields.

    Returns:
        :class:`argparse.Namespace` suitable for calling ``run_search``.
    """
    defaults: dict[str, Any] = {
        "catalog_source": None,
        "detail": False,
        "tree": False,
        "max_depth": None,
        "no_filter_required": False,
        "all_versions": False,
        "limit": 50,
        "no_limit": False,
        "since_version": None,
        "list_format": None,
        "substring": None,
        "regex": None,
        "match_fields": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


@pytest.mark.unit
class TestMutualExclusionSubstringRegex:
    """Tests for the hard error when both positional substring and --regex are supplied."""

    def test_substring_and_regex_together_returns_1(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search returns 1 when both substring and --regex are supplied."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs, "alpha")

        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            substring="foo",
            regex="bar",
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        assert result == 1

    def test_substring_and_regex_together_writes_error_to_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """run_search writes ERROR: to stderr when both substring and --regex are given."""
        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            substring="foo",
            regex="bar",
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        captured = capsys.readouterr()
        assert result == 1
        assert "ERROR:" in captured.err

    def test_substring_and_regex_error_before_catalog_work(self, capsys: pytest.CaptureFixture) -> None:
        """The mutual-exclusion check fires without consulting the catalog source."""
        args = _make_args(
            catalog_source=None,
            substring="foo",
            regex="bar",
        )
        result = run_search(args)
        captured = capsys.readouterr()
        assert result == 1
        assert "ERROR:" in captured.err


@pytest.mark.unit
class TestMutualExclusionMatchFieldsWithoutFilter:
    """Tests for the hard error when --match-fields is supplied without a filter."""

    def test_match_fields_alone_returns_1(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search returns 1 when --match-fields is given with no filter."""
        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            match_fields=["name"],
        )
        result = run_search(args)
        assert result == 1

    def test_match_fields_alone_writes_error_to_stderr(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search writes ERROR: to stderr when --match-fields is given alone."""
        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            match_fields=["name"],
        )
        result = run_search(args)
        captured = capsys.readouterr()
        assert result == 1
        assert "ERROR:" in captured.err

    def test_match_fields_without_filter_error_before_catalog_work(self, capsys: pytest.CaptureFixture) -> None:
        """The match-fields-without-filter check fires without a catalog source."""
        args = _make_args(
            catalog_source=None,
            match_fields=["description"],
        )
        result = run_search(args)
        captured = capsys.readouterr()
        assert result == 1
        assert "ERROR:" in captured.err


@pytest.mark.unit
class TestUnknownMatchField:
    """Tests for the hard error when an unknown field name appears in --match-fields."""

    @pytest.mark.parametrize(
        "bad_fields",
        [
            ["owner"],
            ["name", "owner"],
            ["unknownfield"],
            ["name", "display-name", "bad"],
        ],
    )
    def test_unknown_field_returns_1(self, bad_fields: list[str], capsys: pytest.CaptureFixture) -> None:
        """run_search returns 1 when an unknown field name is present in --match-fields."""
        args = _make_args(
            catalog_source="file:///irrelevant@main",
            substring="foo",
            match_fields=bad_fields,
        )
        result = run_search(args)
        assert result == 1

    def test_unknown_field_writes_error_naming_legal_set(self, capsys: pytest.CaptureFixture) -> None:
        """run_search writes ERROR: listing the legal set when an unknown field is given."""
        args = _make_args(
            catalog_source="file:///irrelevant@main",
            substring="foo",
            match_fields=["name", "owner"],
        )
        result = run_search(args)
        captured = capsys.readouterr()
        assert result == 1
        assert "ERROR:" in captured.err

        for legal in MATCH_FIELDS_LEGAL:
            assert legal in captured.err


@pytest.mark.unit
class TestZeroMatchBehaviour:
    """Tests for exit 0 + empty stdout + stderr note when the filter matches nothing."""

    def test_zero_match_exit_0(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search exits 0 when filter matches nothing."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs, "alpha")
        _write_xml(repo_specs, "beta")

        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            substring="xyz-no-match",
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        assert result == 0

    def test_zero_match_empty_stdout(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search prints nothing to stdout when filter matches nothing."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs, "alpha")

        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            substring="xyz-no-match",
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_zero_match_stderr_note(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search writes the spec canonical note to stderr on zero-match."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs, "alpha")

        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            substring="xyz-no-match",
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)

        captured = capsys.readouterr()
        assert LIST_FILTER_ZERO_MATCH_NOTE in captured.err

    def test_zero_match_with_regex(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Zero-match path works the same way with --regex."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs, "alpha")

        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            regex="^xyz",
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        captured = capsys.readouterr()
        assert result == 0
        assert captured.out == ""
        assert LIST_FILTER_ZERO_MATCH_NOTE in captured.err


@pytest.mark.unit
class TestFilterAppliedBeforeRenderers:
    """Tests that the filter runs before each output renderer."""

    def test_filter_applied_before_detail_mode(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Substring filter is applied before --detail rendering."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs, "foo-entry")
        _write_xml(repo_specs, "bar-entry")

        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            substring="foo",
            detail=True,
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        captured = capsys.readouterr()
        assert result == 0
        assert "foo-entry" in captured.out
        assert "bar-entry" not in captured.out

    def test_filter_applied_before_json_format(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Substring filter is applied before --format json rendering."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs, "foo-entry")
        _write_xml(repo_specs, "bar-entry")

        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            substring="foo",
            list_format="json",
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        captured = capsys.readouterr()
        assert result == 0
        assert "foo-entry" in captured.out
        assert "bar-entry" not in captured.out

    def test_filter_applied_before_default_names(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Substring filter is applied before the default names renderer."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs, "foo-entry")
        _write_xml(repo_specs, "bar-entry")

        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            substring="foo",
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        captured = capsys.readouterr()
        assert result == 0
        assert "foo-entry" in captured.out
        assert "bar-entry" not in captured.out


@pytest.mark.unit
class TestArgparseRegistration:
    """Tests that ``register`` wires up the new arguments correctly."""

    def _make_subparsers(self) -> tuple[argparse.ArgumentParser, Any]:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        return parser, subparsers

    def test_substring_is_optional_positional(self) -> None:
        """Positional <substring> is optional (nargs='?')."""
        parser, subparsers = self._make_subparsers()
        register(subparsers)
        args = parser.parse_args(["search"])
        assert args.substring is None

    def test_substring_is_captured_when_supplied(self) -> None:
        """Positional <substring> is captured when supplied."""
        parser, subparsers = self._make_subparsers()
        register(subparsers)
        args = parser.parse_args(["search", "mysearch"])
        assert args.substring == "mysearch"

    def test_regex_flag_registered(self) -> None:
        """--regex flag is registered and defaults to None."""
        parser, subparsers = self._make_subparsers()
        register(subparsers)
        args = parser.parse_args(["search"])
        assert args.regex is None

    def test_regex_flag_captured_when_supplied(self) -> None:
        """--regex flag value is captured when supplied."""
        parser, subparsers = self._make_subparsers()
        register(subparsers)
        args = parser.parse_args(["search", "--regex", "^foo"])
        assert args.regex == "^foo"

    def test_match_fields_flag_registered(self) -> None:
        """--match-fields flag is registered and defaults to None."""
        parser, subparsers = self._make_subparsers()
        register(subparsers)
        args = parser.parse_args(["search"])
        assert args.match_fields is None

    def test_match_fields_flag_parsed_as_list(self) -> None:
        """--match-fields CSV is parsed into a list of field names."""
        parser, subparsers = self._make_subparsers()
        register(subparsers)
        args = parser.parse_args(["search", "--match-fields", "name,description"])
        assert args.match_fields == ["name", "description"]

    def test_match_fields_single_value(self) -> None:
        """--match-fields with a single value parses to a one-element list."""
        parser, subparsers = self._make_subparsers()
        register(subparsers)
        args = parser.parse_args(["search", "--match-fields", "keywords"])
        assert args.match_fields == ["keywords"]


@pytest.mark.unit
class TestTreeModeWithFilter:
    """Tests for tree mode filter paths to ensure full coverage."""

    def test_tree_filter_zero_match_exit_0(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search --tree exits 0 and prints zero-match note when filter matches nothing."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs, "alpha")

        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            tree=True,
            substring="xyz-no-match",
            no_filter_required=True,
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        captured = capsys.readouterr()
        assert result == 0
        assert captured.out == ""
        assert LIST_FILTER_ZERO_MATCH_NOTE in captured.err

    def test_tree_filter_returns_matching_entries(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search --tree applies the filter and renders only matching entries."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs, "foo-entry")
        _write_xml(repo_specs, "bar-entry")

        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            tree=True,
            substring="foo",
            no_filter_required=True,
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        captured = capsys.readouterr()
        assert result == 0
        assert "foo-entry" in captured.out
        assert "bar-entry" not in captured.out


@pytest.mark.unit
class TestZeroMatchJsonFormat:
    """Tests for zero-match + --format json path."""

    def test_zero_match_with_json_format_prints_empty_array(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Zero-match + --format json prints '[]' to stdout and note to stderr."""
        repo_specs = tmp_path / "repo-specs"
        _write_xml(repo_specs, "alpha")

        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            substring="xyz-no-match",
            list_format="json",
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        captured = capsys.readouterr()
        assert result == 0
        assert "[]" in captured.out
        assert LIST_FILTER_ZERO_MATCH_NOTE in captured.err


@pytest.mark.unit
class TestEmptyCatalogWithJsonFormat:
    """Tests for empty catalog + --format json path (pre-existing coverage gap)."""

    def test_empty_catalog_json_prints_empty_array(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Empty catalog + --format json prints '[]' to stdout."""

        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)

        args = _make_args(
            catalog_source=f"file://{tmp_path}@main",
            list_format="json",
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        captured = capsys.readouterr()
        assert result == 0
        assert "[]" in captured.out
