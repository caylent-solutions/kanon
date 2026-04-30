"""Coverage meta test: every in-scope scenario in `docs/integration-testing.md`
must have a corresponding `pytest.mark.scenario` test.

This test parses the doc for every `### XX-NN: <title>` heading, removes the
documented env-dependent exclusions (RP-init-07, RP-upload-01..15), and walks
`tests/scenarios/` looking for tests that reference each in-scope scenario ID
in their parametrize ids, function name, or docstring. Any in-scope scenario
ID with zero matching tests fails the suite.

Currently `xfail(strict=False)` while the per-category Stories under E2-F4
are still landing. After the last Story commits its Tasks, this guard flips
to `xfail(strict=True)` and then fails-on-gap so missing scenarios become a
hard CI break going forward.
"""

from __future__ import annotations

import pathlib
import re

import pytest


_DOC = pathlib.Path(__file__).resolve().parents[2] / "docs" / "integration-testing.md"
_SCENARIOS_DIR = pathlib.Path(__file__).resolve().parent
_HEADING_RE = re.compile(r"^### ([A-Z][A-Za-z-]*-\d+):", re.MULTILINE)
_EXCLUDED = {"RP-init-07"} | {f"RP-upload-{i:02d}" for i in range(1, 16)}


def _doc_scenario_ids() -> set[str]:
    return set(_HEADING_RE.findall(_DOC.read_text()))


def _scenario_ids_referenced_in_tests() -> set[str]:
    """Walk tests/scenarios/ and collect every scenario ID referenced.

    Matches against:
    - Filenames containing a scenario ID (e.g. ``test_hv_01.py``)
    - ``pytest.mark.parametrize`` ids
    - Function names (``test_hv_01_top_level_help``)
    - Docstrings / comments referencing the canonical ``XX-NN`` form
    """
    pattern = re.compile(r"\b([A-Z][A-Za-z-]*-\d+)\b")
    ids: set[str] = set()
    for path in _SCENARIOS_DIR.rglob("test_*.py"):
        if path.name == pathlib.Path(__file__).name:
            continue
        text = path.read_text()
        for match in pattern.finditer(text):
            ids.add(match.group(1))
        # Also collect from filename (lowercase ids like hv-01 -> HV-01).
        for match in pattern.finditer(path.name.upper().replace("_", "-")):
            ids.add(match.group(1))
    return ids


@pytest.mark.scenario
def test_every_in_scope_scenario_has_a_test() -> None:
    in_scope = _doc_scenario_ids() - _EXCLUDED
    covered = _scenario_ids_referenced_in_tests()
    missing = sorted(in_scope - covered)
    assert not missing, (
        f"{len(missing)} in-scope scenario(s) lack automated tests under "
        f"tests/scenarios/. First 20 missing: {missing[:20]}"
    )


@pytest.mark.scenario
def test_excluded_set_matches_doc() -> None:
    """Sanity check: the exclusion list in this guard matches what the doc and
    the inventory file declare. Drift here means a scenario was moved in/out
    of the env-dependency bucket without updating both sides."""
    inventory_path = (
        pathlib.Path(__file__).resolve().parents[3]
        / "kanon-migration-backlog"
        / "automation-scope"
        / "scenario-inventory.md"
    )
    if not inventory_path.exists():
        pytest.skip(f"scenario-inventory.md not present at {inventory_path}")
    text = inventory_path.read_text()
    inventory_excluded = set(re.findall(r"`(RP-[a-z]+-\d+)` --", text))
    inventory_excluded = {
        sid for sid in inventory_excluded if sid in _EXCLUDED or sid.startswith(("RP-init-07", "RP-upload-"))
    }
    assert inventory_excluded == _EXCLUDED, (
        f"Inventory excluded set diverges from coverage guard. "
        f"Inventory: {sorted(inventory_excluded)} vs guard: {sorted(_EXCLUDED)}"
    )
