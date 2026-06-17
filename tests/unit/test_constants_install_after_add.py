"""Unit tests for the .kanon [catalog] block constants and hermetic install rejection.

Verifies AC-FUNC-001: KANON_CATALOG_BLOCK_HEADER and KANON_CATALOG_BLOCK_KEY
are defined in kanon_cli.constants with the exact string values expected by
spec Section 5 (data format).  These constants remain in use by ``kanon add``
to write the ``.kanon`` [catalog] block (a source-config artifact distinct from
the now-removed lockfile [catalog] block).

Schema v4 (FR-7) made ``kanon install`` HERMETIC: the install-side
``_parse_catalog_block`` and ``CatalogBlockParseError`` were removed and
replaced by ``_reject_catalog_source_on_install`` /
``HermeticInstallCatalogSourceError``.  The catalog-source-on-install tests below
exercise that hermetic rejection contract.
"""

from __future__ import annotations

import pytest

from kanon_cli.constants import (
    KANON_CATALOG_BLOCK_HEADER,
    KANON_CATALOG_BLOCK_KEY,
)
from kanon_cli.core.install import (
    HermeticInstallCatalogSourceError,
    InstallError,
    _reject_catalog_source_on_install,
)


@pytest.mark.unit
class TestCatalogBlockConstants:
    """AC-FUNC-001: constants are defined with the correct values."""

    def test_kanon_catalog_block_header_value(self) -> None:
        assert KANON_CATALOG_BLOCK_HEADER == "[catalog]"

    def test_kanon_catalog_block_key_value(self) -> None:
        assert KANON_CATALOG_BLOCK_KEY == "KANON_CATALOG_SOURCE"

    def test_kanon_catalog_block_header_is_string(self) -> None:
        assert isinstance(KANON_CATALOG_BLOCK_HEADER, str)

    def test_kanon_catalog_block_key_is_string(self) -> None:
        assert isinstance(KANON_CATALOG_BLOCK_KEY, str)


@pytest.mark.unit
class TestRejectCatalogSourceOnInstall:
    """FR-7: hermetic install rejects a catalog source from the CLI flag or env var.

    ``_reject_catalog_source_on_install(cli_arg, env_value)`` is the hermetic
    guard that replaced the removed install-side ``_parse_catalog_block``.  It
    raises ``HermeticInstallCatalogSourceError`` when either input is non-None,
    attributing the CLI flag in preference to the env var.
    """

    def test_both_none_does_not_raise(self) -> None:
        """The hermetic happy path: no CLI flag and no env var -> no error."""
        # Must complete without raising; returns None.
        assert _reject_catalog_source_on_install(None, None) is None

    def test_cli_arg_set_raises(self) -> None:
        """A non-None CLI flag value is rejected fail-fast."""
        with pytest.raises(HermeticInstallCatalogSourceError) as exc_info:
            _reject_catalog_source_on_install("https://cli.example.com/repo.git@main", None)
        assert exc_info.value.origin == "the --catalog-source flag"

    def test_env_value_set_raises(self) -> None:
        """A non-None KANON_CATALOG_SOURCE env value is rejected fail-fast."""
        with pytest.raises(HermeticInstallCatalogSourceError) as exc_info:
            _reject_catalog_source_on_install(None, "https://env.example.com/repo.git@main")
        assert exc_info.value.origin == "the KANON_CATALOG_SOURCE environment variable"

    def test_cli_arg_takes_precedence_over_env_in_origin(self) -> None:
        """When BOTH are set, the error attributes the CLI flag, not the env var."""
        with pytest.raises(HermeticInstallCatalogSourceError) as exc_info:
            _reject_catalog_source_on_install(
                "https://cli.example.com/repo.git@main",
                "https://env.example.com/repo.git@main",
            )
        assert exc_info.value.origin == "the --catalog-source flag"

    def test_empty_string_cli_arg_is_rejected(self) -> None:
        """An empty-string CLI flag is still non-None and must be rejected.

        Only ``None`` means "no catalog source supplied"; an empty string is a
        supplied (if degenerate) value and must fail fast rather than be treated
        as absent.
        """
        with pytest.raises(HermeticInstallCatalogSourceError):
            _reject_catalog_source_on_install("", None)


@pytest.mark.unit
class TestHermeticInstallCatalogSourceError:
    """AC-FUNC-005: HermeticInstallCatalogSourceError message and type contract."""

    def test_is_install_error_subclass(self) -> None:
        err = HermeticInstallCatalogSourceError(origin="the --catalog-source flag")
        assert isinstance(err, InstallError)

    def test_origin_attribute_accessible(self) -> None:
        err = HermeticInstallCatalogSourceError(origin="the KANON_CATALOG_SOURCE environment variable")
        assert err.origin == "the KANON_CATALOG_SOURCE environment variable"

    def test_str_has_error_prefix(self) -> None:
        """The rendered message starts with the verbatim ERROR header (spec text)."""
        err = HermeticInstallCatalogSourceError(origin="the --catalog-source flag")
        assert str(err).startswith("ERROR: 'kanon install' does not accept a catalog source")

    def test_str_names_the_origin(self) -> None:
        """The message includes the origin so the operator knows where the value came from."""
        err = HermeticInstallCatalogSourceError(origin="the --catalog-source flag")
        assert "the --catalog-source flag" in str(err)

    def test_str_includes_remediation(self) -> None:
        """The message tells the operator how to re-run install correctly."""
        err = HermeticInstallCatalogSourceError(origin="the --catalog-source flag")
        text = str(err)
        assert "Remediation" in text
        assert "KANON_CATALOG_SOURCE unset" in text
