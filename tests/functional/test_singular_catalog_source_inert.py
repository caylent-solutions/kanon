"""Functional tests: the removed singular ``KANON_CATALOG_SOURCE`` is inert.

Change-inventory item 2 (Area A): discovery now reads the plural
``KANON_CATALOG_SOURCES`` env var. The pre-3.0 singular ``KANON_CATALOG_SOURCE``
is gone with no fallback. Setting only the singular variable (with the plural
UNSET) must therefore have NO effect: a command that requires a catalog source
still fails fast with the canonical missing-source error and a non-zero exit.

These black-box subprocess tests run ``kanon search`` and ``kanon add`` with an
environment in which ONLY the singular variable is populated. They assert the
canonical :data:`MISSING_CATALOG_ERROR_TEMPLATE` text on stderr and a non-zero
exit, proving the singular variable is not consulted as a source. The assertion
is anchored to the shared constants (not a hard-coded literal) so it tracks the
production error text.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from kanon_cli.constants import (
    CATALOG_SOURCES_ENV_VAR,
    MISSING_CATALOG_ERROR_TEMPLATE,
)
from tests.functional.conftest import _run_kanon

_SINGULAR_CATALOG_SOURCE_ENV = "KANON_CATALOG_SOURCE"

_SINGULAR_SOURCE_VALUE = "file:///does/not/matter@main"

_ADD_ENTRY = "some-entry"

_TRACEBACK_MARKER = "Traceback (most recent call last)"


def _env_with_only_singular_source() -> dict:
    """Return an environment with only the singular catalog-source var set.

    Copies the current process environment, removes the plural
    ``KANON_CATALOG_SOURCES`` so no real source is configured, and sets the
    removed singular ``KANON_CATALOG_SOURCE`` to a non-empty value. If the
    singular variable were still honoured the command would attempt to use it;
    because it is inert, the command must instead emit the missing-source error.

    Returns:
        A full replacement environment dict for the subprocess.
    """
    env = dict(os.environ)
    env.pop(CATALOG_SOURCES_ENV_VAR, None)
    env[_SINGULAR_CATALOG_SOURCE_ENV] = _SINGULAR_SOURCE_VALUE
    return env


def _assert_missing_source(result, *, command: str) -> None:
    """Assert the result is the canonical missing-source failure.

    Args:
        result: The CompletedProcess returned by :func:`_run_kanon`.
        command: The subcommand name, embedded in the canonical error text and
            used in failure diagnostics.
    """
    assert result.returncode != 0, (
        f"'kanon {command}' with only the singular {_SINGULAR_CATALOG_SOURCE_ENV} set "
        f"must exit non-zero (the singular var is inert); got {result.returncode}.\n"
        f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
    )
    expected = MISSING_CATALOG_ERROR_TEMPLATE.format(command=command)
    assert expected in result.stderr, (
        f"'kanon {command}' did not emit the canonical missing-source error; "
        f"the singular {_SINGULAR_CATALOG_SOURCE_ENV} appears to still have an effect.\n"
        f"  expected stderr to contain: {expected!r}\n"
        f"  actual stderr: {result.stderr!r}"
    )
    assert _TRACEBACK_MARKER not in result.stderr, (
        f"'kanon {command}' leaked a Python traceback to stderr:\n{result.stderr}"
    )
    assert _TRACEBACK_MARKER not in result.stdout, (
        f"'kanon {command}' leaked a Python traceback to stdout:\n{result.stdout}"
    )


@pytest.mark.functional
class TestSingularCatalogSourceInert:
    """Only-singular ``KANON_CATALOG_SOURCE`` does not configure discovery."""

    def test_search_singular_only_errors_missing_source(self) -> None:
        result = _run_kanon(
            "search",
            "foo",
            env=_env_with_only_singular_source(),
        )
        _assert_missing_source(result, command="search")

    def test_add_singular_only_errors_missing_source(self, tmp_path: pathlib.Path) -> None:
        result = _run_kanon(
            "add",
            _ADD_ENTRY,
            "--kanon-file",
            str(tmp_path / ".kanon"),
            env=_env_with_only_singular_source(),
        )
        _assert_missing_source(result, command="add")
