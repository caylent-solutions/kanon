"""Unit tests: provider-agnosticism invariant for ``src/``.

Scans every ``*.py`` file under ``<repo_root>/src/`` via ``pathlib.Path.rglob``
for forbidden provider-specific CLI invocations and provider-specific REST /
GraphQL hostnames, enforcing spec Section 3.6 R99 and impl-gaps-spec Section 4.5
(AC-5.1 through AC-5.3).

No subprocess calls, no ``git`` invocations, no allowlist file dependency.
The day-one expectation is that the current branch has zero matches.

Test structure
--------------
- ``_scan_lines`` helper tested with parametrized in-memory cases for every
  forbidden pattern (positive) and word-boundary false-positive guard
  (negative).
- Tree-scan integration test enumerates ``src/**/*.py`` and asserts zero
  findings across all forbidden patterns.
- Self-inspection test asserts that the banned literal strings in this module
  appear only inside the ``_PATTERN_LITERALS_BLOCK`` region.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from typing import Iterable

import pytest

# ---------------------------------------------------------------------------
# Repository root resolution
# ---------------------------------------------------------------------------


def _find_repo_root() -> pathlib.Path:
    """Walk parents of this file upward until an ancestor containing ``pyproject.toml`` is found.

    Returns:
        Absolute path to the repository root.

    Raises:
        FileNotFoundError: When no ancestor contains ``pyproject.toml``.
    """
    current = pathlib.Path(__file__).resolve().parent
    while True:
        if (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            raise FileNotFoundError("Could not locate repository root: no ancestor directory contains pyproject.toml")
        current = parent


_REPO_ROOT: pathlib.Path = _find_repo_root()

# ---------------------------------------------------------------------------
# _PATTERN_LITERALS_BLOCK -- all banned pattern literals are confined here.
# The self-inspection test enforces that they appear nowhere else in this file.
# ---------------------------------------------------------------------------

# BEGIN _PATTERN_LITERALS_BLOCK

# Forbidden CLI patterns (regex -- word boundary + trailing whitespace).
FORBIDDEN_CLI_PATTERNS: list[str] = [
    r"\bgh\s+",
    r"\bglab\s+",
    r"\bbb\s+",
    r"\btea\s+",
    r"aws\s+codecommit",
    r"az\s+repos",
]

# Forbidden hostname patterns (regex).
FORBIDDEN_HOST_PATTERNS: list[str] = [
    r"api\.github\.com",
    r"gitlab\.com/api",
    r"bitbucket\.org/!api",
    r"dev\.azure\.com/_apis",
]

# END _PATTERN_LITERALS_BLOCK

_ALL_PATTERNS: list[str] = FORBIDDEN_CLI_PATTERNS + FORBIDDEN_HOST_PATTERNS

# Remediation line appended to every failure message.
_REMEDIATION = "Remediation: remove the provider-specific reference from src/ before merging this branch."

# ---------------------------------------------------------------------------
# Data class for scan findings
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A single forbidden-pattern match."""

    path: str
    line_number: int
    pattern: str
    line_text: str

    def message(self) -> str:
        """Return a human-readable description of the finding."""
        return (
            f"{self.path}:{self.line_number}: "
            f"matched pattern '{self.pattern}' in line: {self.line_text!r}\n"
            f"{_REMEDIATION}"
        )


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------


def _scan_lines(lines: Iterable[str], path: str) -> list[Finding]:
    """Scan *lines* for any forbidden pattern and return all findings.

    Args:
        lines: Iterable of text lines (trailing newlines are acceptable).
        path: Repo-relative file path used in ``Finding`` objects.

    Returns:
        List of ``Finding`` objects, one per (line, pattern) hit.
        An empty list means the file is clean.
    """
    findings: list[Finding] = []
    for lineno, line in enumerate(lines, start=1):
        for pattern in _ALL_PATTERNS:
            if re.search(pattern, line):
                findings.append(
                    Finding(
                        path=path,
                        line_number=lineno,
                        pattern=pattern,
                        line_text=line,
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Parametrized positive cases -- forbidden CLI patterns
#
# Sample lines are defined without repeating the pattern regex strings so that
# the banned literal substrings appear only in _PATTERN_LITERALS_BLOCK and
# _SELF_INSPECTION_LITERALS (the self-inspection test enforces this).
# The sample lines contain matching invocations (the text that would appear
# in real provider shellouts), not the regex patterns themselves.
# ---------------------------------------------------------------------------

# One sample line per FORBIDDEN_CLI_PATTERNS entry, in the same order.
_CLI_SAMPLE_LINES: list[str] = [
    "gh repo list",
    "glab repo list",
    "bb pull-requests list",
    "tea issues create",
    "aws codecommit get-repository --repo-name foo",
    "az repos list --output json",
]

_CLI_PATTERN_POSITIVE_CASES: list[tuple[str, str]] = list(zip(FORBIDDEN_CLI_PATTERNS, _CLI_SAMPLE_LINES))


@pytest.mark.unit
@pytest.mark.parametrize("pattern,line", _CLI_PATTERN_POSITIVE_CASES)
def test_scan_lines_detects_forbidden_cli_pattern(pattern: str, line: str) -> None:
    """``_scan_lines`` returns exactly one finding for each forbidden CLI pattern."""
    findings = _scan_lines([line], path="src/example.py")
    matched = [f for f in findings if f.pattern == pattern]
    assert len(matched) == 1, (
        f"Expected exactly one finding for pattern {pattern!r} in line {line!r}; got {len(matched)}: {matched}"
    )
    assert matched[0].line_number == 1
    assert matched[0].path == "src/example.py"


# ---------------------------------------------------------------------------
# Parametrized positive cases -- forbidden hostname patterns
#
# Sample lines are defined without repeating the pattern regex strings.
# ---------------------------------------------------------------------------

# One sample line per FORBIDDEN_HOST_PATTERNS entry, in the same order.
_HOST_SAMPLE_LINES: list[str] = [
    "url = 'https://api.github.com/repos'",
    "url = 'https://gitlab.com/api/v4/projects'",
    "url = 'https://bitbucket.org/!api/2.0/repositories'",
    "url = 'https://dev.azure.com/_apis/git/repositories'",
]

_HOST_PATTERN_POSITIVE_CASES: list[tuple[str, str]] = list(zip(FORBIDDEN_HOST_PATTERNS, _HOST_SAMPLE_LINES))


@pytest.mark.unit
@pytest.mark.parametrize("pattern,line", _HOST_PATTERN_POSITIVE_CASES)
def test_scan_lines_detects_forbidden_hostname_pattern(pattern: str, line: str) -> None:
    """``_scan_lines`` returns exactly one finding for each forbidden hostname pattern."""
    findings = _scan_lines([line], path="src/example.py")
    matched = [f for f in findings if f.pattern == pattern]
    assert len(matched) == 1, (
        f"Expected exactly one finding for pattern {pattern!r} in line {line!r}; got {len(matched)}: {matched}"
    )
    assert matched[0].line_number == 1
    assert matched[0].path == "src/example.py"


# ---------------------------------------------------------------------------
# Negative word-boundary cases
#
# Each case is (index-into-FORBIDDEN_CLI_PATTERNS, non-matching word).
# The pattern is retrieved from FORBIDDEN_CLI_PATTERNS by index at runtime so
# the literal pattern string does not appear outside _PATTERN_LITERALS_BLOCK.
# ---------------------------------------------------------------------------

# (pattern_index, non_matching_word) -- pattern retrieved from FORBIDDEN_CLI_PATTERNS[idx].
_NEGATIVE_WORD_BOUNDARY_RAW: list[tuple[int, str]] = [
    (0, "right"),
    (0, "weight"),
    (0, "freight"),
    (1, "rubber"),
    (2, "rubber"),
    (3, "tearing"),
    (3, "steak"),
]

_NEGATIVE_WORD_BOUNDARY_CASES: list[tuple[str, str]] = [
    (FORBIDDEN_CLI_PATTERNS[idx], word) for idx, word in _NEGATIVE_WORD_BOUNDARY_RAW
]


@pytest.mark.unit
@pytest.mark.parametrize("pattern,word", _NEGATIVE_WORD_BOUNDARY_CASES)
def test_scan_lines_word_boundary_no_false_positive(pattern: str, word: str) -> None:
    """Word-boundary regex does not fire on common English words containing the token as a substring."""
    findings = _scan_lines([word], path="src/example.py")
    matched = [f for f in findings if f.pattern == pattern]
    assert matched == [], f"False positive: pattern {pattern!r} matched word {word!r} unexpectedly; findings: {matched}"


# ---------------------------------------------------------------------------
# Clean line produces no findings
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_scan_lines_clean_line_returns_no_findings() -> None:
    """A line with no forbidden content produces no findings."""
    findings = _scan_lines(["result = git.clone(url)"], path="src/clean.py")
    assert findings == []


# ---------------------------------------------------------------------------
# Multi-line correct line-number reporting
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_scan_lines_reports_correct_line_number() -> None:
    """``_scan_lines`` reports the 1-based line number of the hit, not the first line."""
    # Use the first CLI pattern (index 0) -- the gh pattern -- with a matching sample line.
    gh_pattern = FORBIDDEN_CLI_PATTERNS[0]
    lines = [
        "import os",
        "gh repo list",
        "pass",
    ]
    findings = _scan_lines(lines, path="src/scripts/check.py")
    matching = [f for f in findings if f.pattern == gh_pattern]
    assert len(matching) >= 1, f"Expected at least one finding on line 2; got: {findings}"
    assert matching[0].line_number == 2


# ---------------------------------------------------------------------------
# Finding message format
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_finding_message_contains_path_lineno_pattern_and_remediation() -> None:
    """``Finding.message()`` includes the file path, line number, pattern, and remediation."""
    # Use the first CLI pattern (index 0) retrieved from the constants block.
    gh_pattern = FORBIDDEN_CLI_PATTERNS[0]
    finding = Finding(
        path="src/example.py",
        line_number=42,
        pattern=gh_pattern,
        line_text="gh repo list",
    )
    msg = finding.message()
    assert "src/example.py" in msg
    assert "42" in msg
    assert gh_pattern in msg
    assert _REMEDIATION in msg


# ---------------------------------------------------------------------------
# Tree-scan integration test: src/**/*.py must have zero findings
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_forbidden_pattern_in_src_tree() -> None:
    """End-to-end: ``src/**/*.py`` contains no forbidden provider-specific patterns.

    Enumerates every ``*.py`` file under ``<repo_root>/src/`` via
    ``pathlib.Path.rglob``, reads each as UTF-8 (errors replaced), and asserts
    zero findings across the combined forbidden-pattern set.

    Failure message reports every (file, line, pattern) tuple plus the
    remediation line.
    """
    src_root = _REPO_ROOT / "src"
    all_findings: list[Finding] = []

    for py_file in sorted(src_root.rglob("*.py")):
        rel_path = py_file.relative_to(_REPO_ROOT).as_posix()
        content = py_file.read_bytes().decode("utf-8", errors="replace")
        file_findings = _scan_lines(content.splitlines(), path=rel_path)
        all_findings.extend(file_findings)

    assert not all_findings, "Forbidden provider-specific patterns found in src/**/*.py:\n" + "\n".join(
        f.message() for f in all_findings
    )


# ---------------------------------------------------------------------------
# Self-inspection: banned literals must only appear inside _PATTERN_LITERALS_BLOCK
# ---------------------------------------------------------------------------

_BLOCK_START_MARKER = "# BEGIN _PATTERN_LITERALS_BLOCK"
_BLOCK_END_MARKER = "# END _PATTERN_LITERALS_BLOCK"

# The raw string tokens as they appear literally in this source file --
# used only by the self-inspection test below.
_SELF_INSPECTION_LITERALS: list[str] = [
    "gh\\s+",
    "glab\\s+",
    "bb\\s+",
    "tea\\s+",
    "aws\\s+codecommit",
    "az\\s+repos",
    "api\\.github\\.com",
    "gitlab\\.com/api",
    "bitbucket\\.org/!api",
    "dev\\.azure\\.com/_apis",
]


@pytest.mark.unit
def test_module_source_literals_only_in_pattern_block() -> None:
    """Banned pattern literals appear only inside the ``_PATTERN_LITERALS_BLOCK`` region.

    Reads this module's own source, locates the region delimited by
    ``# BEGIN _PATTERN_LITERALS_BLOCK`` and ``# END _PATTERN_LITERALS_BLOCK``,
    and asserts that every banned literal string appears only within that region
    (or in this self-inspection test's own ``_SELF_INSPECTION_LITERALS`` list)
    and not in any other part of the file.
    """
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    lines = source.splitlines()

    # Locate the block boundaries -- match only actual comment lines (stripped to start with #).
    block_start: int | None = None
    block_end: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == _BLOCK_START_MARKER:
            block_start = idx
        elif stripped == _BLOCK_END_MARKER:
            block_end = idx

    assert block_start is not None, f"Marker {_BLOCK_START_MARKER!r} not found in module source"
    assert block_end is not None, f"Marker {_BLOCK_END_MARKER!r} not found in module source"
    assert block_start < block_end, "Block start marker must precede block end marker"

    # Locate the self-inspection list boundaries (lines containing _SELF_INSPECTION_LITERALS).
    self_inspect_start: int | None = None
    self_inspect_end: int | None = None
    for idx, line in enumerate(lines):
        if "_SELF_INSPECTION_LITERALS" in line and "=" in line:
            self_inspect_start = idx
        if self_inspect_start is not None and idx > self_inspect_start and line.strip() == "]":
            self_inspect_end = idx
            break

    assert self_inspect_start is not None, "_SELF_INSPECTION_LITERALS definition not found"
    assert self_inspect_end is not None, "_SELF_INSPECTION_LITERALS closing bracket not found"

    violations: list[str] = []
    for lineno, line in enumerate(lines):
        stripped = line.strip()
        # Skip comment lines.
        if stripped.startswith("#"):
            continue
        # Skip lines inside the pattern literals block.
        if block_start <= lineno <= block_end:
            continue
        # Skip lines inside the self-inspection literals list.
        if self_inspect_start <= lineno <= self_inspect_end:
            continue
        for literal in _SELF_INSPECTION_LITERALS:
            if literal in line:
                violations.append(
                    f"Line {lineno + 1}: literal {literal!r} appears outside "
                    f"_PATTERN_LITERALS_BLOCK and _SELF_INSPECTION_LITERALS: {line!r}"
                )

    assert not violations, (
        "Banned pattern literals found outside the designated blocks in module source:\n" + "\n".join(violations)
    )
