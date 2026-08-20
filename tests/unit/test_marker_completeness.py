"""Guards that every test belongs to exactly one tier.

CI selects tests by tier marker: `-m unit`, `-m integration`, `-m functional`,
`-m scenario`. A test carrying none of them is collected by no tiered job. It ran
only because one job executed the whole suite with no marker filter at all, which
made the omission invisible -- seven tests were in that state, including six that
looked like ordinary unit tests sitting beside marked siblings in the same file.

Once tiers are gated on which paths a change touches, an unmarked test stops
running anywhere and reports nothing. Its absence looks exactly like success. This
module makes that state a failure instead.

Collection runs in a subprocess rather than through a hook so the invariant is
asserted with pytest's own marker-selection semantics on the real test tree. A
``pytest_collection_modifyitems`` hook would have to observe items before the mark
plugin deselects them, which depends on hook ordering between two plugins --
exactly the kind of implicit coupling this suite has been bitten by before.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

from tests.conftest import subprocess_timeout


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

TIER_MARKERS = ("unit", "integration", "functional", "scenario")

_NO_TIER_EXPRESSION = " and ".join(f"not {marker}" for marker in TIER_MARKERS)

_MULTIPLE_TIERS_EXPRESSION = " or ".join(
    f"({first} and {second})" for index, first in enumerate(TIER_MARKERS) for second in TIER_MARKERS[index + 1 :]
)

_EXIT_NO_TESTS_COLLECTED = 5


def _collect(marker_expression: str) -> subprocess.CompletedProcess:
    """Return the result of collecting the tests matching *marker_expression*.

    Collection only -- no test in the selection is executed, so this cannot
    recurse into the suite that invokes it.

    Args:
        marker_expression: A pytest ``-m`` expression.

    Returns:
        The completed ``pytest --collect-only`` process.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-m",
            marker_expression,
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=subprocess_timeout(),
    )


def _collected_node_ids(result: subprocess.CompletedProcess) -> list[str]:
    """Return the node ids listed by a ``--collect-only -q`` run, ignoring its summary."""
    return [line for line in result.stdout.splitlines() if "::" in line]


@pytest.mark.unit
def test_every_test_carries_a_tier_marker() -> None:
    """Verify no test escapes tier selection.

    Given: the whole test tree
    When: it is collected with every tier marker excluded
    Then: nothing is collected

    A test matching this selection runs in no tiered CI job. Add the marker for the
    tier it belongs to -- do not widen a job's selection to catch it, which would
    reintroduce the unfiltered run that hid these in the first place.
    """
    result = _collect(_NO_TIER_EXPRESSION)

    assert result.returncode == _EXIT_NO_TESTS_COLLECTED, (
        f"These tests carry none of the tier markers {TIER_MARKERS}, so no tiered CI job "
        f"collects them:\n  " + "\n  ".join(_collected_node_ids(result) or [result.stdout.strip()])
    )


@pytest.mark.unit
def test_no_test_carries_more_than_one_tier_marker() -> None:
    """Verify tiers stay disjoint.

    Given: the whole test tree
    When: it is collected with every pair of tier markers required together
    Then: nothing is collected

    A test in two tiers runs twice, and its cost is charged to a tier whose budget
    it does not belong to -- a functional test marked ``unit`` makes the fast tier
    slow for no benefit.
    """
    result = _collect(_MULTIPLE_TIERS_EXPRESSION)

    assert result.returncode == _EXIT_NO_TESTS_COLLECTED, (
        "These tests carry more than one tier marker, so they run in more than one "
        "tiered job:\n  " + "\n  ".join(_collected_node_ids(result) or [result.stdout.strip()])
    )
