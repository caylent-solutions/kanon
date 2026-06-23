"""Unit tests for the hermetic install catalog-source rejection contract.

Schema 3.0.0 (FR-1 / FR-7) removed the global ``.kanon`` ``[catalog]`` block and
the singular ``KANON_CATALOG_SOURCE`` env var.  ``kanon add`` no longer writes a
``[catalog]`` block, and ``kanon install`` is HERMETIC: the install-side
``_parse_catalog_block`` / ``CatalogBlockParseError`` were removed and replaced
by ``_reject_catalog_source_on_install`` / ``HermeticInstallCatalogSourceError``.
The catalog discovery set is now the plural ``KANON_CATALOG_SOURCES`` env var.

The tests below exercise the hermetic rejection contract against the plural
mechanism.
"""

from __future__ import annotations

import pytest

from kanon_cli.core.install import (
    HermeticInstallCatalogSourceError,
    InstallError,
    _reject_catalog_source_on_install,
)


@pytest.mark.unit
class TestRejectCatalogSourceOnInstall:
    """FR-7: hermetic install rejects a catalog source from the CLI flag or env var.

    ``_reject_catalog_source_on_install(cli_arg, env_configured)`` is the
    hermetic guard that replaced the removed install-side ``_parse_catalog_block``.
    It raises ``HermeticInstallCatalogSourceError`` when the CLI flag is non-None
    or ``KANON_CATALOG_SOURCES`` configures at least one source, attributing the
    CLI flag in preference to the env var.
    """

    def test_no_source_does_not_raise(self) -> None:
        """The hermetic happy path: no CLI flag and no configured env source -> no error."""
        # Must complete without raising; returns None.
        assert _reject_catalog_source_on_install(None, False) is None

    def test_cli_arg_set_raises(self) -> None:
        """A non-None CLI flag value is rejected fail-fast."""
        with pytest.raises(HermeticInstallCatalogSourceError) as exc_info:
            _reject_catalog_source_on_install("https://cli.example.com/repo.git@main", False)
        assert exc_info.value.origin == "the --catalog-source flag"

    def test_env_configured_raises(self) -> None:
        """A populated KANON_CATALOG_SOURCES env var is rejected fail-fast."""
        with pytest.raises(HermeticInstallCatalogSourceError) as exc_info:
            _reject_catalog_source_on_install(None, True)
        assert exc_info.value.origin == "the KANON_CATALOG_SOURCES environment variable"

    def test_cli_arg_takes_precedence_over_env_in_origin(self) -> None:
        """When BOTH are set, the error attributes the CLI flag, not the env var."""
        with pytest.raises(HermeticInstallCatalogSourceError) as exc_info:
            _reject_catalog_source_on_install(
                "https://cli.example.com/repo.git@main",
                True,
            )
        assert exc_info.value.origin == "the --catalog-source flag"

    def test_empty_string_cli_arg_is_rejected(self) -> None:
        """An empty-string CLI flag is still non-None and must be rejected.

        Only ``None`` means "no catalog source supplied"; an empty string is a
        supplied (if degenerate) value and must fail fast rather than be treated
        as absent.
        """
        with pytest.raises(HermeticInstallCatalogSourceError):
            _reject_catalog_source_on_install("", False)


@pytest.mark.unit
class TestHermeticInstallCatalogSourceError:
    """AC-FUNC-005: HermeticInstallCatalogSourceError message and type contract."""

    def test_is_install_error_subclass(self) -> None:
        err = HermeticInstallCatalogSourceError(origin="the --catalog-source flag")
        assert isinstance(err, InstallError)

    def test_origin_attribute_accessible(self) -> None:
        err = HermeticInstallCatalogSourceError(origin="the KANON_CATALOG_SOURCES environment variable")
        assert err.origin == "the KANON_CATALOG_SOURCES environment variable"

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
        assert "KANON_CATALOG_SOURCES unset" in text
