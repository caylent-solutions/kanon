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


def _collect(marker_expression: str, *extra_args: str) -> subprocess.CompletedProcess:
    """Return the result of collecting the tests matching *marker_expression*.

    Collection only -- no test in the selection is executed, so this cannot
    recurse into the suite that invokes it.

    Args:
        marker_expression: A pytest ``-m`` expression.
        *extra_args: Further pytest arguments, so a caller can reproduce a CI
            tier's exact selection rather than an approximation of it.

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
            *extra_args,
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


VENDORED_TESTS_PATH = "tests/unit/repo"


@pytest.mark.unit
def test_ci_unit_tiers_collect_every_unit_test() -> None:
    """The two CI unit jobs together must collect every unit-marked test.

    Carrying a tier marker is not enough: a test also has to be *selected by a job
    that runs*. The unit tier is split in two -- ``make test-unit-cov`` excludes the
    vendored tree and ``make test-unit-vendored`` runs only that tree -- so their
    selections must partition ``-m unit`` exactly.

    They once did not. ``test-unit-cov`` additionally took a positional ``tests/unit``
    argument, which narrowed collection to that directory and silently dropped 193
    unit-marked tests living elsewhere, including every test in ``tests/security``.
    Those tests then ran in no pull-request job at all, and nothing reported it: the
    marker guard above still passed, because the tests did carry a marker.

    This asserts the property that was actually missing -- that the tiers sum to the
    whole -- rather than the weaker property that each test is labelled.
    """
    everything = _collected_node_ids(_collect("unit"))
    first_party = _collected_node_ids(_collect("unit", f"--ignore={VENDORED_TESTS_PATH}"))
    vendored = _collected_node_ids(_collect("unit", VENDORED_TESTS_PATH))

    assert everything, "Expected the unit tier to collect at least one test."

    covered = set(first_party) | set(vendored)
    missed = sorted(set(everything) - covered)

    assert not missed, (
        f"{len(missed)} unit-marked test(s) are collected by neither CI unit job, so they run "
        f"in no pull-request job:\n  " + "\n  ".join(missed[:20]) + ("\n  ..." if len(missed) > 20 else "")
    )

    overlap = sorted(set(first_party) & set(vendored))
    assert not overlap, (
        f"{len(overlap)} unit-marked test(s) are collected by BOTH CI unit jobs, so they run "
        f"twice and their coverage is double-counted:\n  " + "\n  ".join(overlap[:20])
    )
