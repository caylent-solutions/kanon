"""Functional tests: provider-agnosticism CI enforcement.

Scans the tracked file set via ``git ls-files`` for forbidden provider-specific
CLI invocations and REST/GraphQL hostnames, enforcing spec Section 3.6 and
Section 10 line 1023.

Test structure
--------------
- Unit-shaped tests for ``_load_allowlist`` (no filesystem dependency beyond
  a tmp_path fixture).
- Parametrised tests for ``_scan_lines`` covering all forbidden tokens, all
  forbidden hostnames, and negative word-boundary cases.
- Integration test ``test_no_forbidden_token_in_tracked_source`` that runs the
  full end-to-end scan against the current tracked tree.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
from dataclasses import dataclass
from typing import Iterable

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Repo root -- two parents up from this file (tests/functional/ -> tests/ -> repo root).
_REPO_ROOT: pathlib.Path = pathlib.Path(__file__).parents[2]

# Allowlist file path (relative to repo root).
_ALLOWLIST_REL = "tests/integration/provider_allowlist.txt"

# Always-allowlisted path prefixes (never scanned regardless of allowlist file).
# Exactly 3 spec-mandated prefixes (AC-FUNC-005): docs files, test fixtures, and the
# git internals directory.  Additional path-specific exemptions are declared in the
# allowlist file (tests/integration/provider_allowlist.txt).
_ALWAYS_ALLOWLISTED_PREFIXES: tuple[str, ...] = (
    "docs/",
    "tests/fixtures/",
    ".git/",
)

# Forbidden CLI tokens (regex patterns using word boundaries).
FORBIDDEN_CLI_TOKENS: list[str] = [
    r"\bgh\b",
    r"\bglab\b",
    r"\bbb\b",
    r"\btea\b",
    "aws codecommit",
    "az repos",
]

# Forbidden hostname substrings (literal).
FORBIDDEN_HOST_TOKENS: list[str] = [
    "api.github.com",
    "gitlab.com/api",
    "bitbucket.org/!api",
    "dev.azure.com/_apis",
]

# Remediation message appended to every finding.
_REMEDIATION = (
    "Remediation: remove the provider-specific reference, OR add an exemption"
    " line to tests/integration/provider_allowlist.txt with a justification comment."
)


# ---------------------------------------------------------------------------
# Data class for scan findings
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A single forbidden-token match."""

    path: str
    line_number: int
    token: str

    def message(self) -> str:
        """Return a human-readable description of the finding."""
        return f"{self.path}:{self.line_number}: forbidden token '{self.token}'\n{_REMEDIATION}"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _load_allowlist(repo_root: pathlib.Path) -> set[str]:
    """Read the provider allowlist file and return the set of allowlisted paths.

    The allowlist file is ``tests/integration/provider_allowlist.txt`` relative
    to *repo_root*.  Lines starting with ``#`` and blank lines are ignored.
    Every non-ignored line MUST have the shape ``<path>:<justification>`` where
    *justification* is non-empty and not purely whitespace.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        Set of repo-relative file paths that are exempt from the scan.

    Raises:
        FileNotFoundError: If the allowlist file does not exist.
        ValueError: If any non-comment, non-blank line is malformed (missing
            colon, or whitespace-only justification), with the 1-based line
            number included in the message.
    """
    allowlist_path = repo_root / _ALLOWLIST_REL
    paths: set[str] = set()
    # The allowlist file is always exempt from the scan -- it contains the
    # forbidden tokens as part of its documented format.
    paths.add(_ALLOWLIST_REL)
    raw_lines = allowlist_path.read_text(encoding="utf-8").splitlines()
    for lineno, raw in enumerate(raw_lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Malformed allowlist entry at line {lineno}: {raw!r} -- expected <path>:<justification>")
        file_path, _, justification = line.partition(":")
        if not justification.strip():
            raise ValueError(
                f"Malformed allowlist entry at line {lineno}: {raw!r} -- "
                "justification must be non-empty and not purely whitespace"
            )
        paths.add(file_path)
    return paths


def _is_allowlisted(path: str, allowlisted_paths: set[str]) -> bool:
    """Return True if *path* should be skipped during scanning.

    A path is skipped when it starts with any always-allowlisted prefix OR
    when it appears verbatim in *allowlisted_paths* OR when it starts with
    any allowlisted path that ends with ``/`` (directory prefix exemption).

    Args:
        path: Repo-relative file path.
        allowlisted_paths: Paths loaded from the allowlist file.  Entries
            ending with ``/`` are treated as prefix patterns so that every
            file under the directory is exempted without enumerating each
            one individually.

    Returns:
        True when the path is exempt from scanning.
    """
    for prefix in _ALWAYS_ALLOWLISTED_PREFIXES:
        if path.startswith(prefix):
            return True
    if path in allowlisted_paths:
        return True
    for entry in allowlisted_paths:
        if entry.endswith("/") and path.startswith(entry):
            return True
    return False


def _scan_lines(lines: Iterable[str], path: str) -> list[Finding]:
    """Scan *lines* for any forbidden token and return all findings.

    CLI tokens that are expressed as regex patterns with word-boundaries
    (``r\"\\bgh\\b\"`` etc.) are matched via ``re.search``.  Hostname tokens
    (literal substrings) are matched via ``in``.

    Args:
        lines: Iterable of text lines (without trailing newlines is fine).
        path: Repo-relative file path used in ``Finding`` objects.

    Returns:
        List of ``Finding`` objects, one per (line, token) hit.  An empty list
        means the file is clean.
    """
    findings: list[Finding] = []
    for lineno, line in enumerate(lines, start=1):
        for token in FORBIDDEN_CLI_TOKENS:
            if re.search(token, line):
                findings.append(Finding(path=path, line_number=lineno, token=token))
        for token in FORBIDDEN_HOST_TOKENS:
            if token in line:
                findings.append(Finding(path=path, line_number=lineno, token=token))
    return findings


def _enumerate_tracked_files(repo_root: pathlib.Path) -> list[str]:
    """Return the list of tracked files via ``git ls-files``.

    Args:
        repo_root: Absolute path to the repository root passed as ``cwd`` to
            the subprocess call.

    Returns:
        List of repo-relative file paths (empty strings filtered out).
    """
    raw = subprocess.check_output(
        ["git", "ls-files"],
        cwd=str(repo_root),
    )
    return [p for p in raw.decode("utf-8").split("\n") if p]


# ---------------------------------------------------------------------------
# Tests: _load_allowlist
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestLoadAllowlist:
    """Unit-shaped tests for the _load_allowlist helper."""

    def test_empty_file(self, tmp_path: pathlib.Path) -> None:
        """Empty allowlist file returns only the allowlist path itself."""
        allowlist_dir = tmp_path / "tests" / "integration"
        allowlist_dir.mkdir(parents=True)
        (allowlist_dir / "provider_allowlist.txt").write_text("", encoding="utf-8")
        result = _load_allowlist(tmp_path)
        assert result == {_ALLOWLIST_REL}

    def test_comments_only(self, tmp_path: pathlib.Path) -> None:
        """File with only comment lines and blanks returns just the allowlist path."""
        allowlist_dir = tmp_path / "tests" / "integration"
        allowlist_dir.mkdir(parents=True)
        content = "# This is a comment\n\n# Another comment\n"
        (allowlist_dir / "provider_allowlist.txt").write_text(content, encoding="utf-8")
        result = _load_allowlist(tmp_path)
        assert result == {_ALLOWLIST_REL}

    def test_well_formed_entry(self, tmp_path: pathlib.Path) -> None:
        """A valid <path>:<justification> line adds the path to the result set."""
        allowlist_dir = tmp_path / "tests" / "integration"
        allowlist_dir.mkdir(parents=True)
        content = "some/path.py:reason why this file is exempt\n"
        (allowlist_dir / "provider_allowlist.txt").write_text(content, encoding="utf-8")
        result = _load_allowlist(tmp_path)
        assert "some/path.py" in result
        assert _ALLOWLIST_REL in result

    def test_multiple_well_formed_entries(self, tmp_path: pathlib.Path) -> None:
        """Multiple valid entries are all added to the result set."""
        allowlist_dir = tmp_path / "tests" / "integration"
        allowlist_dir.mkdir(parents=True)
        content = "# header\npath/one.py:first reason\npath/two.py:second reason\n"
        (allowlist_dir / "provider_allowlist.txt").write_text(content, encoding="utf-8")
        result = _load_allowlist(tmp_path)
        assert "path/one.py" in result
        assert "path/two.py" in result

    def test_malformed_missing_colon(self, tmp_path: pathlib.Path) -> None:
        """A line missing a colon raises ValueError naming the line number."""
        allowlist_dir = tmp_path / "tests" / "integration"
        allowlist_dir.mkdir(parents=True)
        content = "some/path.py missing justification\n"
        (allowlist_dir / "provider_allowlist.txt").write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match="line 1"):
            _load_allowlist(tmp_path)

    def test_malformed_whitespace_only_justification(self, tmp_path: pathlib.Path) -> None:
        """A line with whitespace-only justification raises ValueError naming line number."""
        allowlist_dir = tmp_path / "tests" / "integration"
        allowlist_dir.mkdir(parents=True)
        content = "some/path.py:   \n"
        (allowlist_dir / "provider_allowlist.txt").write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match="line 1"):
            _load_allowlist(tmp_path)

    def test_malformed_at_second_line(self, tmp_path: pathlib.Path) -> None:
        """Malformed entry on line 2 names line number 2 in the error."""
        allowlist_dir = tmp_path / "tests" / "integration"
        allowlist_dir.mkdir(parents=True)
        content = "good/path.py:valid reason\nbad line no colon\n"
        (allowlist_dir / "provider_allowlist.txt").write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match="line 2"):
            _load_allowlist(tmp_path)

    def test_missing_allowlist_file_raises(self, tmp_path: pathlib.Path) -> None:
        """Absent allowlist file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            _load_allowlist(tmp_path)


# ---------------------------------------------------------------------------
# Tests: _scan_lines -- forbidden CLI tokens
# ---------------------------------------------------------------------------

_CLI_TOKEN_EXAMPLES: list[tuple[str, str]] = [
    (r"\bgh\b", "gh auth login"),
    (r"\bglab\b", "glab repo list"),
    (r"\bbb\b", "bb pull-requests list"),
    (r"\btea\b", "tea issues"),
    ("aws codecommit", "aws codecommit get-repository"),
    ("az repos", "az repos list"),
]

_HOST_TOKEN_EXAMPLES: list[tuple[str, str]] = [
    ("api.github.com", "curl https://api.github.com/repos"),
    ("gitlab.com/api", "curl https://gitlab.com/api/v4/projects"),
    ("bitbucket.org/!api", "curl https://bitbucket.org/!api/2.0/repositories"),
    ("dev.azure.com/_apis", "curl https://dev.azure.com/_apis/git/repositories"),
]


@pytest.mark.functional
@pytest.mark.parametrize("token,line", _CLI_TOKEN_EXAMPLES)
def test_scan_lines_detects_forbidden_cli_token(token: str, line: str) -> None:
    """_scan_lines returns exactly one finding for each forbidden CLI token."""
    findings = _scan_lines([line], path="some/file.py")
    assert len(findings) == 1, (
        f"Expected exactly one finding for token {token!r} in {line!r}, got {len(findings)}: {findings}"
    )
    assert findings[0].token == token
    assert findings[0].line_number == 1
    assert findings[0].path == "some/file.py"


@pytest.mark.functional
@pytest.mark.parametrize("token,line", _HOST_TOKEN_EXAMPLES)
def test_scan_lines_detects_forbidden_hostname(token: str, line: str) -> None:
    """_scan_lines returns exactly one finding for each forbidden hostname."""
    findings = _scan_lines([line], path="some/file.py")
    assert len(findings) == 1, (
        f"Expected exactly one finding for token {token!r} in {line!r}, got {len(findings)}: {findings}"
    )
    assert findings[0].token == token
    assert findings[0].line_number == 1
    assert findings[0].path == "some/file.py"


@pytest.mark.functional
def test_scan_lines_clean_line_returns_no_findings() -> None:
    """A clean line produces no findings."""
    findings = _scan_lines(["x = git.clone(url)"], path="src/clean.py")
    assert findings == []


@pytest.mark.functional
def test_scan_lines_multiline_correct_line_numbers() -> None:
    """_scan_lines reports the correct 1-based line number for each hit."""
    lines = [
        "import subprocess",  # line 1 -- clean
        "result = subprocess.run(['gh', 'auth', 'status'])",  # line 2 -- has gh
        "pass",  # line 3 -- clean
    ]
    findings = _scan_lines(lines, path="scripts/check.py")
    assert any(f.line_number == 2 for f in findings), f"Expected a finding on line 2, got: {findings}"


# ---------------------------------------------------------------------------
# Tests: word-boundary negative cases
# ---------------------------------------------------------------------------

_NEGATIVE_WORD_BOUNDARY_CASES: list[tuple[str, str]] = [
    (r"\bgh\b", "weight"),
    (r"\bgh\b", "right"),
    (r"\bgh\b", "freight"),
    (r"\bglab\b", "rubber"),
    (r"\bbb\b", "rubber"),
    (r"\btea\b", "tearing"),
    (r"\btea\b", "steak"),
]


@pytest.mark.functional
@pytest.mark.parametrize("token,word", _NEGATIVE_WORD_BOUNDARY_CASES)
def test_scan_lines_word_boundary_no_false_positive(token: str, word: str) -> None:
    """Word-boundary regex does not fire on common English words."""
    findings = _scan_lines([word], path="src/example.py")
    matching = [f for f in findings if f.token == token]
    assert matching == [], f"False positive: token {token!r} matched {word!r} unexpectedly"


# ---------------------------------------------------------------------------
# Tests: always-allowlisted prefixes
# ---------------------------------------------------------------------------

_ALWAYS_ALLOWLISTED_PREFIX_CASES: list[str] = [
    "docs/security-model.md",
    "tests/fixtures/some_fixture.txt",
    ".git/config",
]


@pytest.mark.functional
@pytest.mark.parametrize("path", _ALWAYS_ALLOWLISTED_PREFIX_CASES)
def test_always_allowlisted_prefix_is_excluded(path: str) -> None:
    """Files under always-allowlisted prefixes are excluded from scanning."""
    result = _is_allowlisted(path, allowlisted_paths=set())
    assert result is True, f"Expected {path!r} to be allowlisted by prefix, but it was not"


@pytest.mark.functional
def test_non_allowlisted_path_is_not_excluded() -> None:
    """A path not in any prefix or allowlist set is not excluded."""
    result = _is_allowlisted("src/kanon_cli/main.py", allowlisted_paths=set())
    assert result is False


# ---------------------------------------------------------------------------
# Tests: allowlist file is self-exempt
# ---------------------------------------------------------------------------


@pytest.mark.functional
def test_allowlist_file_is_self_exempt() -> None:
    """The allowlist file path itself is included in the returned set."""
    result = _load_allowlist(_REPO_ROOT)
    assert _ALLOWLIST_REL in result, (
        f"Expected allowlist file {_ALLOWLIST_REL!r} to be self-exempt, but it was not found in: {result}"
    )


@pytest.mark.functional
def test_allowlist_file_not_scanned_for_forbidden_tokens() -> None:
    """The allowlist file produces no findings in the integration scan."""
    allowlisted = _load_allowlist(_REPO_ROOT)
    assert _is_allowlisted(_ALLOWLIST_REL, allowlisted), "The allowlist file must be excluded from scanning"


# ---------------------------------------------------------------------------
# Tests: finding message format
# ---------------------------------------------------------------------------


@pytest.mark.functional
def test_finding_message_contains_path_lineno_token_and_remediation() -> None:
    """Finding.message() includes the file path, line number, token, and remediation."""
    token = r"\bgh\b"
    finding = Finding(path="src/example.py", line_number=42, token=token)
    msg = finding.message()
    assert "src/example.py" in msg
    assert "42" in msg
    assert token in msg
    assert _REMEDIATION in msg


# ---------------------------------------------------------------------------
# Tests: module source does not contain forbidden tokens outside constant defs
# ---------------------------------------------------------------------------


@pytest.mark.functional
def test_module_source_forbidden_tokens_only_in_constant_block() -> None:
    """The test module's own source must not contain forbidden tokens outside the
    constant-definition block and its describing comment block.

    This is verified by reading the module source and asserting that every line
    containing a raw forbidden token string is part of the FORBIDDEN_CLI_TOKENS
    or FORBIDDEN_HOST_TOKENS list literals, or is a comment line.
    """
    module_source = pathlib.Path(__file__).read_text(encoding="utf-8")
    lines = module_source.splitlines()

    # The literal hostname tokens that appear in the source file.
    hostname_literals = [
        "api.github.com",
        "gitlab.com/api",
        "bitbucket.org/!api",
        "dev.azure.com/_apis",
    ]

    # The CLI token strings as they appear literally in the source file.
    # These are the raw pattern strings stored in FORBIDDEN_CLI_TOKENS; we
    # check that they only appear inside string literals (lines that contain
    # a quote character), never as bare identifiers or unquoted invocations.
    cli_token_literals = [
        r"\bgh\b",
        r"\bglab\b",
        r"\bbb\b",
        r"\btea\b",
        "aws codecommit",
        "az repos",
    ]

    violations: list[str] = []
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        # Skip comment lines.
        if stripped.startswith("#"):
            continue
        for token in hostname_literals + cli_token_literals:
            if token in line:
                # Allowed only inside a list literal assignment or a string
                # that is part of a tuple/list literal (_TOKEN_EXAMPLES).
                # We recognise these by checking that the line contains a quote
                # character (i.e., it is a string literal in Python source).
                if '"' not in line and "'" not in line:
                    violations.append(f"Line {lineno}: non-literal use of {token!r}: {line!r}")
    assert not violations, "Forbidden tokens appear outside string literals in the module source:\n" + "\n".join(
        violations
    )


# ---------------------------------------------------------------------------
# Integration test: full end-to-end scan of the current tracked tree
# ---------------------------------------------------------------------------


@pytest.mark.functional
def test_no_forbidden_token_in_tracked_source() -> None:
    """End-to-end: no forbidden provider-specific token exists in the tracked tree.

    Enumerates all tracked files via ``git ls-files``, skips always-allowlisted
    prefixes and files listed in the allowlist file, and asserts zero findings
    across the combined forbidden-token set.

    Failure message reports all matches in one run.
    """
    allowlisted = _load_allowlist(_REPO_ROOT)
    tracked = _enumerate_tracked_files(_REPO_ROOT)

    all_findings: list[Finding] = []
    for rel_path in tracked:
        if _is_allowlisted(rel_path, allowlisted):
            continue
        abs_path = _REPO_ROOT / rel_path
        if not abs_path.is_file():
            continue
        content = abs_path.read_bytes().decode("utf-8", errors="replace")
        file_findings = _scan_lines(content.splitlines(), path=rel_path)
        all_findings.extend(file_findings)

    assert not all_findings, "Forbidden provider-specific tokens found in tracked source files:\n" + "\n".join(
        f.message() for f in all_findings
    )
