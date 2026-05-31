"""Guard test: matrix-traceability completeness for findings-rerun-2026-05-30.

Mechanically asserts that ``docs/testing/matrix-traceability.md`` cites a
named, collectable test for every scenario row in
``test-fixtures/findings-rerun-2026-05-30.md``. A future FAIL row cannot
exist without a mapped test -- this is the guardrail that would have caught
the Section 1.3 gaps (spec Section 4 EPIC E50 / E50-F2).

The guard:
1. Parses the findings-rerun matrix to extract the full scenario-row set
   (row number, scenario name, type).
2. Parses the traceability doc to extract the "covered by" citations for
   each row.
3. Asserts every matrix row has at least one citation (or a documented
   manual-only annotation).
4. Asserts every cited test node is collectable via pytest collection.

Note: the 2026-05-30 matrix uses grouped rows (e.g. ``| 20-26 |``) for
bulk-PASS ranges; the row parser only matches individually-numbered rows.
The parsed row count for 2026-05-30 is 55 (rows 20-26 and 37-59 are
grouped and excluded from the numeric scan).

Paths are resolved at runtime from the repository root -- no hard-coded
absolute paths.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Path resolution (runtime, no hard-coded absolute paths)
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """Return the kanon project root by walking up from this file's location.

    This file lives at <project_root>/tests/functional/..., so the root is
    three levels up.

    Raises:
        FileNotFoundError: When pyproject.toml is not found at the expected
            location, indicating this file has been moved out of place.
    """
    here = Path(__file__).resolve()
    root = here.parent.parent.parent
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise FileNotFoundError(
            f"ERROR: pyproject.toml not found at expected location {pyproject}. "
            "The project root could not be determined from this file's path. "
            "Ensure this file lives at <project_root>/tests/functional/."
        )
    return root


def _resolve_matrix_path(project_root: Path) -> Path:
    """Resolve the findings-rerun matrix path from the project root.

    The matrix lives at ``test-fixtures/findings-rerun-2026-05-30.md``
    relative to the workspace root (parent of the kanon repo). The workspace
    root is determined by probing the following candidates in order:

    1. ``$DEVBENCH_WORKSPACE_ROOT/../test-fixtures/...`` when the env var is set.
    2. ``<project_root>/../test-fixtures/...`` (layout-derived: the kanon repo
       lives one level below the workspace root in the standard checkout layout).

    Args:
        project_root: Absolute path to the kanon project root.

    Returns:
        Absolute path to the findings-rerun matrix Markdown file.

    Raises:
        FileNotFoundError: When the matrix file cannot be found at any of the
            probed locations.
    """
    import os

    matrix_filename = "findings-rerun-2026-05-30.md"
    candidates: list[Path] = []

    workspace_env = os.environ.get("DEVBENCH_WORKSPACE_ROOT")
    if workspace_env:
        # DEVBENCH_WORKSPACE_ROOT is the devbench workspace; test-fixtures
        # lives one level above it at the rpm-migration root.
        candidates.append(Path(workspace_env).resolve().parent / "test-fixtures" / matrix_filename)
    # Layout-derived: workspace root is one level above the kanon project root.
    candidates.append(project_root.parent / "test-fixtures" / matrix_filename)

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved

    raise FileNotFoundError(
        "ERROR: findings-rerun matrix not found. Searched: " + ", ".join(str(c.resolve()) for c in candidates) + ". "
        "Ensure the matrix file exists at "
        "<workspace-root>/test-fixtures/findings-rerun-2026-05-30.md. "
        "Set DEVBENCH_WORKSPACE_ROOT or place the kanon repo one level below "
        "the workspace root."
    )


def _resolve_traceability_doc(project_root: Path) -> Path:
    """Resolve the traceability doc path from the project root.

    The doc lives at ``docs/testing/matrix-traceability.md`` inside the
    kanon project root.

    Args:
        project_root: Absolute path to the kanon project root.

    Returns:
        Absolute path to the traceability Markdown document.

    Raises:
        FileNotFoundError: When the document is not present.
    """
    doc_path = project_root / "docs" / "testing" / "matrix-traceability.md"
    if not doc_path.is_file():
        raise FileNotFoundError(
            f"ERROR: Traceability doc not found at {doc_path}. "
            "Ensure docs/testing/matrix-traceability.md exists (authored in "
            "E50-F2-S1-T1). Run 'ls docs/testing/' from the project root to "
            "diagnose the missing file."
        )
    return doc_path


# ---------------------------------------------------------------------------
# Matrix / doc parsers
# ---------------------------------------------------------------------------

# Pattern for scenario rows in the findings-rerun matrix.
# Matches lines like: | 1 | per-entry / builders-plugins | lifecycle | FAIL | ...
_MATRIX_ROW_PATTERN = re.compile(r"^\|\s*(?P<num>\d+)\s*\|\s*(?P<scenario>[^|]+?)\s*\|\s*(?P<type>[^|]+?)\s*\|")

# Pattern for traceability doc rows.
# Matches lines like: | 1 | ... | ... | ... | `tests/...::TestX::test_y`, `...` |
_DOC_ROW_PATTERN = re.compile(
    r"^\|\s*(?P<num>\d+)\s*\|\s*(?P<scenario>[^|]+?)\s*\|\s*(?P<type>[^|]+?)\s*"
    r"\|\s*(?P<result>[^|]+?)\s*\|\s*(?P<covered_by>[^|]*?)\s*\|"
)

# Sentinel token used when a row is acknowledged as manual-only (no automated test).
_MANUAL_ONLY_ANNOTATION = "manual-only"

# Spec-anchored row count for the 2026-05-30 findings-rerun matrix (spec Section 4 EPIC E52).
# The 2026-05-30 matrix uses grouped rows (| 20-26 |, | 37-45 |, | 46-52 |, | 53-59 |) for
# bulk-PASS ranges; those lines do not match the single-number pattern. Only individually-
# numbered rows are counted: 55 parsed rows from the 85-scenario matrix.
_EXPECTED_MATRIX_ROW_COUNT = 55

# Pattern to extract test node IDs from backtick-quoted citations, e.g.
# `tests/integration/test_foo.py::TestBar::test_baz`
_CITATION_BACKTICK_PATTERN = re.compile(r"`([^`]+)`")


def _parse_matrix_rows(matrix_text: str) -> list[tuple[int, str]]:
    """Extract (row_number, scenario_name) pairs from the findings-rerun matrix.

    Parses every table row that starts with a leading pipe and a row number.
    Header and separator rows are excluded. Grouped rows (e.g. ``| 20-26 |``)
    do not match the single-number pattern and are excluded from the result.

    Args:
        matrix_text: Full text of findings-rerun-2026-05-30.md.

    Returns:
        Sorted list of (row_number, scenario_name) tuples for individually-
        numbered scenario rows (55 rows for the 2026-05-30 matrix).

    Raises:
        ValueError: When no scenario rows are found (indicates a parse failure
            due to an unexpected document format).
    """
    rows: list[tuple[int, str]] = []
    for line in matrix_text.splitlines():
        match = _MATRIX_ROW_PATTERN.match(line.strip())
        if match:
            rows.append((int(match.group("num")), match.group("scenario").strip()))
    if not rows:
        raise ValueError(
            "ERROR: No scenario rows found in the findings-rerun matrix. "
            "Expected rows of the form '| <number> | <scenario> | ... |'. "
            "Confirm the matrix file format has not changed."
        )
    return sorted(rows, key=lambda t: t[0])


def _parse_doc_citations(doc_text: str) -> dict[int, list[str]]:
    """Extract per-row citations from the traceability doc.

    Parses the Scenario Traceability Table and returns a mapping from row
    number to the list of cited test node strings extracted from the
    "Covered By" column.

    Args:
        doc_text: Full text of docs/testing/matrix-traceability.md.

    Returns:
        Dict mapping row_number -> list of raw citation strings (may be empty
        if the Covered By cell is blank, which is the failure signal for the
        completeness guard).

    Raises:
        ValueError: When no traceability rows are found in the document.
    """
    citations: dict[int, list[str]] = {}
    for line in doc_text.splitlines():
        match = _DOC_ROW_PATTERN.match(line.strip())
        if match:
            row_num = int(match.group("num"))
            covered_by_cell = match.group("covered_by").strip()
            nodes = _CITATION_BACKTICK_PATTERN.findall(covered_by_cell)
            citations[row_num] = nodes
    if not citations:
        raise ValueError(
            "ERROR: No citation rows found in the traceability doc. "
            "Expected rows of the form '| <number> | ... | ... | ... | `tests/...` |'. "
            "Confirm the traceability doc format has not changed."
        )
    return citations


def _project_python(project_root: Path) -> str:
    """Return the path to the Python interpreter for the project's own venv.

    Prefers the project's local ``.venv/bin/python`` (created by ``uv sync``)
    so that subprocess collection runs with the same installed packages that
    the project's test suite uses. Falls back to ``sys.executable`` when no
    local venv is found (e.g. in a CI environment that activates the venv
    before pytest).

    Args:
        project_root: Absolute path to the kanon project root.

    Returns:
        Absolute path string to the Python interpreter.
    """
    venv_python = project_root / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return str(venv_python)
    return sys.executable


def _is_collectable(node_id: str, project_root: Path) -> tuple[bool, str]:
    """Check whether a pytest node ID is collectable.

    Runs ``pytest --collect-only -q <node_id>`` as a subprocess and returns
    whether collection succeeded.

    Args:
        node_id: A pytest node ID string, e.g.
            ``tests/integration/test_foo.py::TestBar::test_baz``.
        project_root: Absolute path to the kanon project root (used as the
            subprocess cwd so pytest picks up pyproject.toml).

    Returns:
        A (is_collectable, diagnostic) tuple where ``is_collectable`` is True
        when the node is found and ``diagnostic`` is a human-readable string
        suitable for inclusion in an assertion message.
    """
    python = _project_python(project_root)
    result = subprocess.run(
        [python, "-m", "pytest", "--collect-only", "-q", node_id],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    test_name = node_id.split("::")[-1]
    if result.returncode == 0 and test_name in result.stdout:
        return True, f"collected OK (exit {result.returncode})"
    # Provide a diagnostic that names the node and the exit code.
    snippet = (result.stdout + result.stderr).strip().splitlines()
    first_error = next(
        (ln for ln in snippet if ln.strip() and not ln.startswith("warning")),
        "<no output>",
    )
    return (
        False,
        f"exit {result.returncode} -- first relevant output line: {first_error!r}",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def project_root() -> Path:
    """Return the kanon project root derived at runtime."""
    return _project_root()


@pytest.fixture(scope="module")
def matrix_rows(project_root: Path) -> list[tuple[int, str]]:
    """Parse and return the sorted scenario rows from the findings-rerun matrix."""
    matrix_path = _resolve_matrix_path(project_root)
    text = matrix_path.read_text(encoding="utf-8")
    return _parse_matrix_rows(text)


@pytest.fixture(scope="module")
def doc_citations(project_root: Path) -> dict[int, list[str]]:
    """Parse and return the per-row citations from the traceability doc."""
    doc_path = _resolve_traceability_doc(project_root)
    text = doc_path.read_text(encoding="utf-8")
    return _parse_doc_citations(text)


# ---------------------------------------------------------------------------
# Guard tests
# ---------------------------------------------------------------------------


@pytest.mark.functional
def test_every_findings_row_has_a_mapped_existing_test(
    matrix_rows: list[tuple[int, str]],
    doc_citations: dict[int, list[str]],
    project_root: Path,
) -> None:
    """Every scenario row in the findings-rerun matrix must have a citation.

    For each (row_number, scenario_name) in the matrix:
    - The traceability doc must contain an entry for that row number.
    - The entry must carry at least one citation (or a manual-only annotation).
    - Each cited test node must be collectable via pytest.

    Failure modes this test catches:
    1. A matrix row with no entry in the traceability doc (uncited row).
    2. A matrix row whose "Covered By" cell is blank (uncited row).
    3. A citation that names a test node pytest cannot collect (dangling citation).

    Spec reference: E50-F2-S1-T2 AC-FUNC-001, AC-FUNC-002, AC-FUNC-003,
    AC-FUNC-004, AC-TEST-001.
    """
    uncited_rows: list[str] = []
    dangling_citations: list[str] = []

    for row_num, scenario_name in matrix_rows:
        citations = doc_citations.get(row_num)
        if citations is None:
            uncited_rows.append(f"Row {row_num} ({scenario_name!r}): no entry in traceability doc")
            continue
        if not citations:
            uncited_rows.append(f"Row {row_num} ({scenario_name!r}): 'Covered By' cell is blank")
            continue
        # Accept manual-only annotation as a valid coverage declaration.
        if any(_MANUAL_ONLY_ANNOTATION in c for c in citations):
            continue
        # Every other citation must be a collectable pytest node.
        for node_id in citations:
            collectable, diagnostic = _is_collectable(node_id, project_root)
            if not collectable:
                dangling_citations.append(
                    f"Row {row_num} ({scenario_name!r}): citation {node_id!r} is not collectable -- {diagnostic}"
                )

    if uncited_rows or dangling_citations:
        problems = uncited_rows + dangling_citations
        problem_list = "\n  ".join(problems)
        raise AssertionError(
            f"ERROR: Matrix-traceability completeness guard FAILED.\n"
            f"  {len(uncited_rows)} uncited row(s), "
            f"{len(dangling_citations)} dangling citation(s).\n"
            f"  Offending entries:\n  {problem_list}\n"
            "Remediation: update docs/testing/matrix-traceability.md to add a "
            "valid 'Covered By' citation for each uncited row and ensure each "
            "cited test node is collectable via 'pytest --collect-only'."
        )


@pytest.mark.functional
def test_matrix_row_count_matches_expected(
    matrix_rows: list[tuple[int, str]],
) -> None:
    """The findings-rerun matrix must contain exactly the expected scenario-row count.

    The 2026-05-30 re-run covers 85 scenarios total (spec Section 4 EPIC E52),
    but 30 of those are expressed as grouped range rows (| 20-26 |, | 37-45 |,
    | 46-52 |, | 53-59 |) which the single-number parser does not match. The
    expected individually-numbered row count is 55.
    Catches accidental truncation of the matrix or a format change that
    causes the parser to miss rows.

    Spec reference: E50-F2-S1-T2 AC-FUNC-002, E52-F2-S1-T1 AC-DOC-003.
    """
    # Spec-anchored count for the 2026-05-30 findings-rerun matrix (individually-numbered rows).
    expected_count = _EXPECTED_MATRIX_ROW_COUNT
    actual_count = len(matrix_rows)
    assert actual_count == expected_count, (
        f"ERROR: Expected {expected_count} individually-numbered scenario rows in "
        f"the findings-rerun matrix but parsed {actual_count}. "
        "Either the matrix file has been truncated, rows have been added/removed, "
        "or the row-pattern parser failed to match all rows. "
        "Inspect findings-rerun-2026-05-30.md and confirm the row count."
    )


@pytest.mark.functional
def test_traceability_doc_covers_all_matrix_rows(
    matrix_rows: list[tuple[int, str]],
    doc_citations: dict[int, list[str]],
) -> None:
    """Every row number in the matrix must appear in the traceability doc.

    This is a structural completeness check separate from the citation-content
    check in ``test_every_findings_row_has_a_mapped_existing_test``. It fails
    if any row number is missing from the traceability doc's table entirely,
    which means the doc has structural gaps even before citations are checked.

    Spec reference: E50-F2-S1-T2 AC-FUNC-003.
    """
    matrix_row_nums = {row_num for row_num, _ in matrix_rows}
    doc_row_nums = set(doc_citations.keys())
    missing = sorted(matrix_row_nums - doc_row_nums)
    assert not missing, (
        f"ERROR: Traceability doc is missing entries for row number(s): {missing}. "
        "Each row number from the findings-rerun matrix (1-85) must have a "
        "corresponding entry in docs/testing/matrix-traceability.md. "
        "Add the missing row(s) to the Scenario Traceability Table."
    )
