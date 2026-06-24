"""Fail on any disallowed '#' comment in kanon-owned Python.

A stdlib-only, ``tokenize``-based command-line check that detects disallowed
``#`` comments in first-party Python. This is the no-comments GATE that the
python-comment-purge depends on (spec ``ruff-forbid-comments.md`` Section 4.1).

The check tokenizes each in-scope ``*.py`` file with
``tokenize.tokenize(fp.readline)`` and flags every ``tokenize.COMMENT`` token
UNLESS it is a line-1 shebang (``#!``) or a PEP 263 encoding cookie on line 1 or
2. Because a docstring tokenizes as a ``STRING`` token and a ``#`` inside a
string literal is part of a ``STRING`` token, neither is ever flagged -- this is
a property of ``tokenize``, not special-case code.

Usage::

    python tools/lint/check_no_comments.py [PATH ...] [--exclude DIR ...]

When ``PATH`` is omitted the check scans its default roots ``src/kanon_cli`` and
``tests``; the default ``--exclude`` is the vendored ``src/kanon_cli/repo``
subtree. Supplying ``--exclude`` replaces the default exclusion set. The exit
code contract is binary: ``0`` means clean, non-zero means at least one offense
or an operational error. The check is read-only: it never imports or executes
the scanned files and writes no files.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import tokenize

DEFAULT_ROOTS: tuple[str, ...] = ("src/kanon_cli", "tests")
DEFAULT_EXCLUDES: tuple[str, ...] = ("src/kanon_cli/repo",)

# Canonical generated / vendored directory names skipped during a directory walk.
SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".venv",
        ".git",
        "dist",
        "build",
        ".ruff_cache",
        ".pytest_cache",
    }
)

PYTHON_SUFFIX = ".py"
SHEBANG_PREFIX = "#!"

# PEP 263 encoding-cookie pattern, allowed only on line 1 or line 2.
ENCODING_COOKIE_PATTERN = re.compile(r"coding[:=]\s*[-\w.]+")
ENCODING_COOKIE_MAX_LINE = 2

SUCCESS_MESSAGE = "check_no_comments: no disallowed comments found"


class Offense:
    """A single disallowed ``#`` comment found in a scanned file."""

    def __init__(self, path: pathlib.Path, line: int, text: str) -> None:
        self.path = path
        self.line = line
        self.text = text

    def sort_key(self) -> tuple[str, int]:
        """Order offenders by path then line for deterministic output."""
        return (str(self.path), self.line)

    def render(self) -> str:
        """Render the canonical offender line printed to stderr."""
        return f"{self.path}:{self.line}: disallowed comment: {self.text}"


def _is_allowed_comment(text: str, line: int) -> bool:
    """Return True if a COMMENT token is an allowed shebang or encoding cookie."""
    if line == 1 and text.startswith(SHEBANG_PREFIX):
        return True
    if line <= ENCODING_COOKIE_MAX_LINE and ENCODING_COOKIE_PATTERN.search(text):
        return True
    return False


def _is_excluded(path: pathlib.Path, excludes: list[pathlib.Path]) -> bool:
    """Return True if ``path`` is one of, or lives under, an excluded prefix."""
    for prefix in excludes:
        if path == prefix or path.is_relative_to(prefix):
            return True
    return False


def _iter_python_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Recursively collect ``*.py`` files under a directory, skipping generated dirs.

    Directory names in ``SKIP_DIR_NAMES`` (and anything under them) are pruned so
    generated / vendored trees are never tokenized.
    """
    collected: list[pathlib.Path] = []
    for candidate in sorted(root.rglob(f"*{PYTHON_SUFFIX}")):
        if any(part in SKIP_DIR_NAMES for part in candidate.parts):
            continue
        if candidate.is_file():
            collected.append(candidate)
    return collected


def _resolve_targets(paths: list[pathlib.Path], excludes: list[pathlib.Path]) -> list[pathlib.Path]:
    """Resolve path arguments to a deduplicated, sorted list of in-scope files.

    A directory argument is walked recursively for ``*.py`` files; a file
    argument is taken directly when it is a ``*.py`` file and ignored otherwise.
    Files under an excluded prefix are dropped. A non-existent path argument
    raises ``FileNotFoundError`` (fail-fast; no silent skip).
    """
    files: set[pathlib.Path] = set()
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        if path.is_dir():
            candidates = _iter_python_files(path)
        elif path.suffix == PYTHON_SUFFIX:
            candidates = [path]
        else:
            candidates = []
        for candidate in candidates:
            if not _is_excluded(candidate, excludes):
                files.add(candidate)
    return sorted(files)


def _scan_file(path: pathlib.Path) -> list[Offense]:
    """Tokenize one file and return its disallowed-comment offenses.

    Raises ``tokenize.TokenError`` or ``SyntaxError`` when the file is not valid
    Python; the caller converts that into a fail-fast operational error.
    """
    offenses: list[Offense] = []
    with open(path, "rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type != tokenize.COMMENT:
                continue
            line = token.start[0]
            text = token.string
            if _is_allowed_comment(text, line):
                continue
            offenses.append(Offense(path, line, text))
    return offenses


def run_check(argv: list[str]) -> int:
    """Run the no-comments check over ``argv`` and return the process exit code.

    This is the importable entry point used by both the CLI ``main`` handler and
    the unit tests. It never calls ``sys.exit`` (library code); it returns ``0``
    when no disallowed comment is found and a non-zero code on any offense or
    operational error. All diagnostics go to stderr; the success line goes to
    stdout.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    paths = [pathlib.Path(p) for p in args.paths]
    excludes = [pathlib.Path(d) for d in args.exclude]

    try:
        targets = _resolve_targets(paths, excludes)
    except FileNotFoundError as error:
        print(f"check_no_comments: error: path not found: {error}", file=sys.stderr)
        return 1

    offenses: list[Offense] = []
    for target in targets:
        try:
            offenses.extend(_scan_file(target))
        except (tokenize.TokenError, SyntaxError, UnicodeDecodeError) as error:
            print(
                f"check_no_comments: error: {target}: could not tokenize ({error})",
                file=sys.stderr,
            )
            return 1

    if offenses:
        offenses.sort(key=Offense.sort_key)
        for offense in offenses:
            print(offense.render(), file=sys.stderr)
        print(
            f"check_no_comments: {len(offenses)} disallowed comment(s) found",
            file=sys.stderr,
        )
        return 1

    print(SUCCESS_MESSAGE)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse CLI for the check."""
    parser = argparse.ArgumentParser(
        prog="check_no_comments.py",
        description=(
            "Fail on any disallowed '#' comment in kanon-owned Python. Allowed "
            "exceptions: a line-1 shebang and a PEP 263 encoding cookie. "
            "Docstrings and '#' inside string literals are never flagged."
        ),
    )
    parser.add_argument(
        "paths",
        metavar="PATH",
        nargs="*",
        default=list(DEFAULT_ROOTS),
        help="Files or directories to scan (default: %s)" % " ".join(DEFAULT_ROOTS),
    )
    parser.add_argument(
        "--exclude",
        metavar="DIR",
        nargs="+",
        default=list(DEFAULT_EXCLUDES),
        help="Directory prefixes to skip (default: %s)" % " ".join(DEFAULT_EXCLUDES),
    )
    return parser


def main() -> int:
    """CLI entry point: run the check and return its exit code."""
    return run_check(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
