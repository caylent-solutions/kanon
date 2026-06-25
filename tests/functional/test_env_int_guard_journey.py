"""Functional (subprocess) coverage for guarded env-int parsing (inventory item 26).

Exercises the real ``python -m kanon_cli`` CLI through the shared ``_run_kanon``
subprocess helper to prove that the three previously-unguarded numeric env vars
fail fast with a clean, actionable message instead of an uncaught ``ValueError``
traceback when set to a non-integer value:

- ``KANON_LIST_LIMIT`` on ``kanon search`` (the version-walk cap),
- ``KANON_TREE_NO_FILTER_THRESHOLD`` on ``kanon search`` (the tree guardrail),
- ``KANON_OUTDATED_JSON_INDENT`` on ``kanon outdated`` (the JSON indent width).

Each var is read through the ``_env_int`` guard in ``kanon_cli.constants`` at
module-import time, so a malformed value surfaces before any catalog/git work and
the process exits non-zero with ``ERROR: <VAR> must be an integer; got <repr>`` on
stderr.

These three vars are int-parseability-only by design: ``KANON_LIST_LIMIT`` was
originally unguarded and that unguarded-range behaviour was preserved (no ``<0`` /
``<=0`` range guard fires for any of the three). The range guards live on other
vars (``KANON_CACHE_PRUNE_AGE_DAYS``, ``KANON_WHY_JSON_INDENT``), which are not
exercised here.
"""

from pathlib import Path

import pytest

from kanon_cli import constants

from .conftest import _run_kanon

_BAD_INT_VALUE = "notanint"
_EXPECTED_EXIT_CODE = 1
_INTEGER_ERROR_SUFFIX = "must be an integer"
_TRACEBACK_MARKER = "Traceback (most recent call last)"


def _assert_env_int_failure(
    result: "object",
    var_name: str,
) -> None:
    """Assert a malformed env-int run failed fast with the guarded message.

    Verifies the subprocess exited with ``_EXPECTED_EXIT_CODE``, that stderr
    carries the actionable ``<VAR> must be an integer`` message (and therefore
    names the offending variable plus the bad repr), that no Python traceback
    leaked, and that the error did not contaminate stdout.

    Args:
        result: The :class:`subprocess.CompletedProcess` returned by
            :func:`_run_kanon`.
        var_name: The environment variable expected to be named in the message.
    """
    assert result.returncode == _EXPECTED_EXIT_CODE, (
        f"Expected exit {_EXPECTED_EXIT_CODE} for malformed {var_name}; "
        f"got {result.returncode}.\n"
        f"  stdout: {result.stdout!r}\n"
        f"  stderr: {result.stderr!r}"
    )
    expected_message = f"{var_name} {_INTEGER_ERROR_SUFFIX}"
    assert expected_message in result.stderr, f"Expected stderr to contain {expected_message!r}; got {result.stderr!r}"
    assert var_name in result.stderr
    assert repr(_BAD_INT_VALUE) in result.stderr, (
        f"Expected stderr to echo the bad value repr {repr(_BAD_INT_VALUE)!r}; got {result.stderr!r}"
    )
    assert _TRACEBACK_MARKER not in result.stderr, (
        f"A malformed {var_name} must fail fast without a Python traceback; got {result.stderr!r}"
    )
    assert expected_message not in result.stdout, f"The env-int error must not leak onto stdout; got {result.stdout!r}"


@pytest.mark.functional
def test_malformed_list_limit_fails_fast_on_search(tmp_path: Path) -> None:
    """`KANON_LIST_LIMIT=notanint kanon search foo` exits non-zero with the guarded message."""
    result = _run_kanon(
        "search",
        "foo",
        extra_env={
            "KANON_LIST_LIMIT": _BAD_INT_VALUE,
            constants.KANON_HOME_ENV_VAR: str(tmp_path / "home-list-limit"),
        },
    )
    _assert_env_int_failure(result, "KANON_LIST_LIMIT")


@pytest.mark.functional
def test_malformed_tree_no_filter_threshold_fails_fast_on_search(tmp_path: Path) -> None:
    """`KANON_TREE_NO_FILTER_THRESHOLD=notanint kanon search foo` exits non-zero with the guarded message."""
    result = _run_kanon(
        "search",
        "foo",
        extra_env={
            "KANON_TREE_NO_FILTER_THRESHOLD": _BAD_INT_VALUE,
            constants.KANON_HOME_ENV_VAR: str(tmp_path / "home-tree-threshold"),
        },
    )
    _assert_env_int_failure(result, "KANON_TREE_NO_FILTER_THRESHOLD")


@pytest.mark.functional
def test_malformed_outdated_json_indent_fails_fast_on_outdated(tmp_path: Path) -> None:
    """`KANON_OUTDATED_JSON_INDENT=notanint kanon outdated` exits non-zero with the guarded message."""
    result = _run_kanon(
        "outdated",
        extra_env={
            "KANON_OUTDATED_JSON_INDENT": _BAD_INT_VALUE,
            constants.KANON_HOME_ENV_VAR: str(tmp_path / "home-outdated-indent"),
        },
    )
    _assert_env_int_failure(result, "KANON_OUTDATED_JSON_INDENT")
