"""Tests for _discover_source_names missing-URL validation.

Covers:
- AC-TEST-001: KANON_SOURCE_<name>_REF or _PATH present without _URL
  raises ValueError naming the exact missing KANON_SOURCE_<name>_URL variable.
- AC-FUNC-001: The raised ValueError message includes the full variable name
  (e.g. KANON_SOURCE_testsource_URL) so the caller can surface it verbatim.
"""

import pytest

from kanon_cli.core.kanonenv import _discover_source_names


@pytest.mark.unit
class TestDiscoverSourceNamesMissingUrl:
    """AC-TEST-001 / AC-FUNC-001: missing URL raises ValueError naming the variable."""

    def test_revision_without_url_raises_naming_url_variable(self) -> None:
        """KANON_SOURCE_<name>_REF without _URL raises ValueError naming _URL var."""
        expanded = {
            "KANON_SOURCE_testsource_REF": "main",
        }
        with pytest.raises(ValueError, match="KANON_SOURCE_testsource_URL"):
            _discover_source_names(expanded)

    def test_path_without_url_raises_naming_url_variable(self) -> None:
        """KANON_SOURCE_<name>_PATH without _URL raises ValueError naming _URL var."""
        expanded = {
            "KANON_SOURCE_myrepo_PATH": "meta.xml",
        }
        with pytest.raises(ValueError, match="KANON_SOURCE_myrepo_URL"):
            _discover_source_names(expanded)

    def test_revision_and_path_without_url_raises_naming_url_variable(self) -> None:
        """Both REF and PATH without URL raises ValueError naming the URL variable."""
        expanded = {
            "KANON_SOURCE_alpha_REF": "v1.0",
            "KANON_SOURCE_alpha_PATH": "meta.xml",
        }
        with pytest.raises(ValueError, match="KANON_SOURCE_alpha_URL"):
            _discover_source_names(expanded)

    def test_error_message_includes_full_variable_name(self) -> None:
        """The ValueError message includes the full KANON_SOURCE_<name>_URL string."""
        expanded = {
            "KANON_SOURCE_testsource_REF": "main",
        }
        with pytest.raises(ValueError) as exc_info:
            _discover_source_names(expanded)
        assert "KANON_SOURCE_testsource_URL" in str(exc_info.value)

    def test_source_with_all_structural_variables_does_not_raise(self) -> None:
        """A source with all required structural keys (plus an optional env var)
        does not raise.
        """
        expanded = {
            "KANON_SOURCE_good_URL": "https://example.com",
            "KANON_SOURCE_good_REF": "main",
            "KANON_SOURCE_good_PATH": "meta.xml",
            "KANON_SOURCE_good_NAME": "good",
            "KANON_SOURCE_good_GITBASE": "https://example.com",
        }
        names = _discover_source_names(expanded)
        assert names == ["good"]

    def test_lone_optional_env_var_does_not_imply_a_source(self) -> None:
        """An optional env-var key alone (no structural suffix) infers no source.

        _GITBASE (and any other non-structural suffix) is an optional
        per-dependency env var, so it must NOT be treated as a partial source
        that requires a _URL. A lone env-var key yields zero sources, which
        raises NoSourcesError (not a missing-URL error for that alias).
        """
        from kanon_cli.core.kanonenv import NoSourcesError

        for suffix in ("_GITBASE", "_MYBASE"):
            expanded = {f"KANON_SOURCE_lonely{suffix}": "https://example.com"}
            with pytest.raises(NoSourcesError):
                _discover_source_names(expanded)

    def test_missing_url_for_one_source_among_multiple_raises(self) -> None:
        """When one source among multiple is missing URL, ValueError names the missing variable."""
        expanded = {
            "KANON_SOURCE_good_URL": "https://example.com/good",
            "KANON_SOURCE_good_REF": "main",
            "KANON_SOURCE_good_PATH": "meta.xml",
            "KANON_SOURCE_good_NAME": "good",
            "KANON_SOURCE_good_GITBASE": "https://example.com",
            "KANON_SOURCE_bad_REF": "main",
        }
        with pytest.raises(ValueError, match="KANON_SOURCE_bad_URL"):
            _discover_source_names(expanded)

    @pytest.mark.parametrize(
        "suffix",
        ["_REF", "_PATH", "_NAME"],
    )
    def test_parametrized_single_structural_suffix_without_url_raises(self, suffix: str) -> None:
        """Each required structural non-URL suffix alone without URL raises
        ValueError naming the URL var.
        """
        name = "paramtest"
        expanded = {f"KANON_SOURCE_{name}{suffix}": "value"}
        with pytest.raises(ValueError, match=f"KANON_SOURCE_{name}_URL"):
            _discover_source_names(expanded)
