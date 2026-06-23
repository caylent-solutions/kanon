"""Unit tests for the hermetic-install catalog-source contract.

``kanon install`` is hermetic (spec Section 4.3 / FR-14): it is driven solely by
the committed ``.kanon`` (+ ``.kanon.lock``).  A populated ``KANON_CATALOG_SOURCES``
env var has **no effect** on install (it is ignored, never read), and the install
subparser does **not** register ``--catalog-source`` -- passing it exits non-zero.

A prior schema iteration instead made install REJECT a catalog source via
``_reject_catalog_source_on_install`` / ``HermeticInstallCatalogSourceError``;
both are removed.  These tests pin the current ignore-the-env / reject-the-flag
contract and assert the removed symbols are no longer importable.
"""

from __future__ import annotations

import argparse
import pathlib
from unittest.mock import patch

import pytest

import kanon_cli.core.install as install_module
from kanon_cli.commands.install import register
from kanon_cli.core.include_walker import IncludeTree
from kanon_cli.core.install import _RefResolution, install

_KANON_SINGLE_SOURCE = """\
GITBASE=https://git.example.com
CLAUDE_MARKETPLACES_DIR=/tmp/mktplc
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_alpha_URL=https://git.example.com/alpha.git
KANON_SOURCE_alpha_REVISION=main
KANON_SOURCE_alpha_PATH=manifest.xml
"""


def _write_kanon(directory: pathlib.Path) -> pathlib.Path:
    """Write a minimal single-source .kanon file and return its path."""
    kanon_path = directory / ".kanon"
    kanon_path.write_text(_KANON_SINGLE_SOURCE, encoding="utf-8")
    return kanon_path


@pytest.mark.unit
class TestRemovedRejectSymbolsAreGone:
    """The reject-the-catalog-source machinery was removed (complete replacement)."""

    def test_reject_helper_is_not_importable(self) -> None:
        """``_reject_catalog_source_on_install`` no longer exists on the install module."""
        assert not hasattr(install_module, "_reject_catalog_source_on_install")

    def test_hermetic_error_class_is_not_importable(self) -> None:
        """``HermeticInstallCatalogSourceError`` no longer exists on the install module."""
        assert not hasattr(install_module, "HermeticInstallCatalogSourceError")

    def test_install_signature_has_no_catalog_source_param(self) -> None:
        """``install()`` no longer threads a ``catalog_source`` parameter."""
        import inspect

        params = inspect.signature(install).parameters
        assert "catalog_source" not in params


@pytest.mark.unit
class TestInstallParserRejectsCatalogSourceFlag:
    """The install subparser does not register --catalog-source (FR-14)."""

    @pytest.mark.parametrize(
        "catalog_value",
        [
            "https://cli.example.com/repo.git@main",
            "https://example.com/catalog.git",  # malformed (no @ref) -- still rejected
            "latest",
        ],
    )
    def test_install_subparser_rejects_catalog_source(self, catalog_value: str) -> None:
        """Passing --catalog-source to install exits non-zero (unrecognized argument)."""
        parser = argparse.ArgumentParser(prog="kanon")
        subparsers = parser.add_subparsers()
        register(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["install", "--catalog-source", catalog_value])
        assert exc_info.value.code != 0

    def test_install_subparser_has_no_catalog_source_option(self) -> None:
        """The install subparser exposes no --catalog-source option string."""
        parser = argparse.ArgumentParser(prog="kanon")
        subparsers = parser.add_subparsers()
        register(subparsers)

        install_parser = subparsers.choices["install"]
        option_strings = {opt for action in install_parser._actions for opt in action.option_strings}
        assert "--catalog-source" not in option_strings


@pytest.mark.unit
class TestInstallIgnoresCatalogSourceEnv:
    """A populated KANON_CATALOG_SOURCES env var is ignored by install (FR-14)."""

    def test_install_ignores_env_catalog_source_and_writes_lockfile(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install() ignores KANON_CATALOG_SOURCES, resolves from .kanon, and writes the lock."""
        monkeypatch.setenv("KANON_CATALOG_SOURCES", "https://env.example.com/catalog.git@main")

        kanon_path = _write_kanon(tmp_path)
        lock_path = tmp_path / ".kanon.lock"
        assert not lock_path.exists()

        mock_ref = _RefResolution(sha="a" * 40, resolved_ref="refs/heads/main")
        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=mock_ref),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("manifest.xml"))),
        ):
            install(
                kanonenv_path=kanon_path,
                lock_file_path=lock_path,
            )

        # The env var did not abort install: the lockfile records the committed
        # .kanon source, not the ignored env-var URL.
        assert lock_path.exists()
        lock_text = lock_path.read_text(encoding="utf-8")
        assert "https://git.example.com/alpha.git" in lock_text
        assert "https://env.example.com/catalog.git" not in lock_text
