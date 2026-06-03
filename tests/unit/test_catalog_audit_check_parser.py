"""Parametrized unit tests for the --check parser in kanon catalog audit.

Tests every valid and invalid --check value and asserts the parser produces
the expected frozenset OR raises the documented argparse error.

AC-TEST-001: Parametrized unit tests covering every valid and invalid --check value.
"""

from __future__ import annotations

import argparse

import pytest

from kanon_cli.commands.catalog import _parse_check_subset
from kanon_cli.constants import KANON_CATALOG_AUDIT_VALID_CHECKS


@pytest.mark.unit
class TestParseCheckSubsetValid:
    """Tests that valid --check values produce the expected normalized frozensets."""

    def test_all_default_produces_all_checks(self) -> None:
        """'all' expands to the full set of valid checks."""
        result = _parse_check_subset("all")
        assert result == KANON_CATALOG_AUDIT_VALID_CHECKS

    def test_single_metadata(self) -> None:
        """Single valid check name produces a singleton frozenset."""
        result = _parse_check_subset("metadata")
        assert result == frozenset({"metadata"})

    def test_single_tag_format(self) -> None:
        """Single 'tag-format' produces a singleton frozenset."""
        result = _parse_check_subset("tag-format")
        assert result == frozenset({"tag-format"})

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("metadata,tag-format", frozenset({"metadata", "tag-format"})),
            (
                "metadata,source-name-derivation",
                frozenset({"metadata", "source-name-derivation"}),
            ),
            (
                "entry-name-uniqueness,remote-url",
                frozenset({"entry-name-uniqueness", "remote-url"}),
            ),
            (
                "metadata,source-name-derivation,entry-name-uniqueness,remote-url,tag-format",
                frozenset(
                    {
                        "metadata",
                        "source-name-derivation",
                        "entry-name-uniqueness",
                        "remote-url",
                        "tag-format",
                    }
                ),
            ),
        ],
    )
    def test_comma_separated_valid_subsets(self, value: str, expected: frozenset[str]) -> None:
        """Comma-separated valid check names map to the expected frozenset."""
        result = _parse_check_subset(value)
        assert result == expected

    @pytest.mark.parametrize(
        "check_name",
        [
            "metadata",
            "source-name-derivation",
            "entry-name-uniqueness",
            "remote-url",
            "tag-format",
        ],
    )
    def test_each_individual_valid_check(self, check_name: str) -> None:
        """Every individual valid check name is accepted."""
        result = _parse_check_subset(check_name)
        assert result == frozenset({check_name})


@pytest.mark.unit
class TestParseCheckSubsetInvalid:
    """Tests that invalid --check values raise argparse.ArgumentTypeError."""

    def test_empty_string_is_hard_error(self) -> None:
        """Empty string raises ArgumentTypeError with ERROR-shape message."""
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            _parse_check_subset("")
        assert "ERROR:" in str(exc_info.value)

    def test_unknown_subset_name_is_hard_error(self) -> None:
        """Unknown subset name raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            _parse_check_subset("unknown")
        assert "ERROR:" in str(exc_info.value)
        assert "unknown" in str(exc_info.value)

    def test_all_mixed_with_other_subset_is_hard_error(self) -> None:
        """'all' mixed with another value raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            _parse_check_subset("all,metadata")
        assert "ERROR:" in str(exc_info.value)
        assert "all" in str(exc_info.value)

    def test_all_mixed_with_multiple_subsets_is_hard_error(self) -> None:
        """'all' mixed with multiple other values raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            _parse_check_subset("all,metadata,tag-format")
        assert "ERROR:" in str(exc_info.value)

    def test_valid_and_unknown_mixed_is_hard_error(self) -> None:
        """A mix of a valid and unknown subset name raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            _parse_check_subset("metadata,nonsense")
        assert "ERROR:" in str(exc_info.value)
        assert "nonsense" in str(exc_info.value)

    @pytest.mark.parametrize(
        "invalid_value",
        [
            "METADATA",
            "Metadata",
            "TAG-FORMAT",
            "remote_url",
        ],
    )
    def test_wrong_case_or_separator_is_hard_error(self, invalid_value: str) -> None:
        """Wrong case or separator variants raise ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            _parse_check_subset(invalid_value)
        assert "ERROR:" in str(exc_info.value)
