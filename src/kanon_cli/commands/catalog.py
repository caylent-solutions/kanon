"""kanon catalog subcommand group and kanon catalog audit sub-subcommand.

Provides:
  kanon catalog audit [<dir-or-source>] [--check <subset>] [--format {text,json}]
    [--no-color] [--strict]

The catalog audit command performs a series of configurable soft-spot checks
against a manifest repo. The manifest repo is either a local directory (must
contain a repo-specs/ subdirectory) or a remote <git_url>@<ref> source that
is cloned into a local cache.

Check dispatch (T1 framework):
  The check registry AUDIT_CHECK_REGISTRY maps check-name -> callable.
  T2-T7 register their individual check functions into this registry.
  T1 wires the framework: the registry exists and is iterated, but starts empty.

Cache layout:
  ${KANON_CACHE_DIR}/catalog-audit/<sha256(canonicalized url@ref)>/
  Cached clones are reused when their mtime is within
  KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS seconds of now.

Output formats:
  text (default): one finding per line, prefixed with ERROR:, WARN:, or INFO:.
  json: a single JSON object {"findings": [{...}, ...]} written to stdout.

Spec reference: spec/kanon-list-add-lock-features-spec.md Section 4.8.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import pathlib
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

import defusedxml.ElementTree as ET
from kanon_cli.constants import (
    KANON_CACHE_DIR_ENV,
    KANON_CACHE_DIR_MODE,
    KANON_CATALOG_AUDIT_CACHE_SUBDIR,
    KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS,
    KANON_CATALOG_AUDIT_FORMAT_DEFAULT,
    KANON_CATALOG_AUDIT_FORMAT_ENV,
    KANON_CATALOG_AUDIT_FORMAT_JSON,
    KANON_CATALOG_AUDIT_VALID_CHECKS,
    KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE,
)
from kanon_cli.core.metadata import audit_catalog_metadata, derive_source_name
from kanon_cli.core.url import canonicalize_repo_url

# Alias for the XML parse error type from defusedxml to avoid importing from the
# standard xml.etree.ElementTree (which triggers bandit B405).
XMLParseError = ET.ParseError


# ---------------------------------------------------------------------------
# AuditFinding dataclass
# ---------------------------------------------------------------------------


@dataclass
class AuditFinding:
    """A single finding produced by one kanon catalog audit check.

    Attributes:
        kind: Severity -- one of "info", "warn", or "error".
        code: Short machine-readable identifier for the finding type.
        message: Human-readable description of the finding.
        remediation: Suggested command or action to resolve the finding.
    """

    kind: str
    code: str
    message: str
    remediation: str


# ---------------------------------------------------------------------------
# Check registry (T2-T7 populate this dict)
# ---------------------------------------------------------------------------

# Maps check-name to a callable accepting (target_path: pathlib.Path) and
# returning a list[AuditFinding].  T1 ships with an empty registry;
# subsequent tasks register their check functions here.
AUDIT_CHECK_REGISTRY: dict[str, Callable[[pathlib.Path], list[AuditFinding]]] = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_check_subset(value: str) -> frozenset[str]:
    """Parse and validate a --check value into a normalized frozenset of check names.

    Accepts the single token "all" (expands to the full set) or a
    comma-separated list of valid individual check names.

    Args:
        value: The raw string from the --check argument.

    Returns:
        A frozenset of check names to run.

    Raises:
        argparse.ArgumentTypeError: If the value is empty, contains an unknown
            check name, or mixes "all" with other values.
    """
    if not value:
        raise argparse.ArgumentTypeError(
            "ERROR: --check requires a non-empty value. "
            f"Valid values: all, {', '.join(sorted(KANON_CATALOG_AUDIT_VALID_CHECKS))}."
        )

    parts = [p.strip() for p in value.split(",")]

    if "all" in parts and len(parts) > 1:
        raise argparse.ArgumentTypeError(
            "ERROR: 'all' cannot be combined with other --check values. "
            "Use '--check all' alone to run every check, "
            "or list individual check names without 'all'."
        )

    if "all" in parts:
        return KANON_CATALOG_AUDIT_VALID_CHECKS

    unknown = [p for p in parts if p not in KANON_CATALOG_AUDIT_VALID_CHECKS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"ERROR: Unknown --check value(s): {', '.join(unknown)}. "
            f"Valid values: all, {', '.join(sorted(KANON_CATALOG_AUDIT_VALID_CHECKS))}."
        )

    return frozenset(parts)


def _resolve_audit_target(target: str) -> pathlib.Path:
    """Resolve the <dir-or-source> argument to a local directory path.

    If the target contains '@' and looks like a <git_url>@<ref> source,
    clone it into the catalog-audit cache directory and return the clone path.
    Otherwise, treat the target as a local filesystem path.

    Args:
        target: Either a local directory path or a <git_url>@<ref> string.

    Returns:
        Absolute path to the local directory containing the manifest repo.

    Raises:
        SystemExit: If the target is a local path that does not exist, does
            not contain a repo-specs/ subdirectory, or if a remote clone fails.
    """
    # Determine whether this looks like a remote source.
    # A remote source must contain '@' AND either '://' or another '@' before
    # the last '@' (SSH-style: git@host:org/repo.git@ref).
    # We use the same last-'@' split logic as core/catalog.py.
    is_remote = _looks_like_remote_source(target)

    if is_remote:
        return _clone_audit_target(target)

    local_path = pathlib.Path(target).resolve()
    if not local_path.exists():
        print(
            f"ERROR: Audit target path does not exist: {local_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    _check_repo_specs_dir(local_path)
    return local_path


def _looks_like_remote_source(target: str) -> bool:
    """Return True if target looks like a <git_url>@<ref> remote source.

    Args:
        target: The raw target string from the CLI.

    Returns:
        True if the target should be treated as a remote git source.
    """
    # Fast-path: no '@' at all means it cannot be a remote source.
    if "@" not in target:
        return False

    # Find the last '@' -- that is the ref delimiter.
    idx = target.rfind("@")
    url_part = target[:idx]

    # If the URL part contains '://' it is a scheme URL (https://, ssh://, etc.)
    if "://" in url_part:
        return True

    # If the URL part itself contains '@' it is SSH shorthand (git@host:org/repo.git)
    if "@" in url_part:
        return True

    # Otherwise the single '@' might just be a Windows path or unusual local path;
    # do not treat as remote.
    return False


def _clone_audit_target(source: str) -> pathlib.Path:
    """Clone a <git_url>@<ref> source into the catalog-audit cache and return its path.

    Reuses a cached clone if present and fresh (mtime within
    KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS).

    Args:
        source: The raw <git_url>@<ref> string.

    Returns:
        Path to the cloned repo directory.

    Raises:
        SystemExit: If KANON_CACHE_DIR is unset, the clone fails, or the
            cloned repo lacks a repo-specs/ subdirectory.
    """
    cache_dir_env = os.environ.get(KANON_CACHE_DIR_ENV)
    if not cache_dir_env:
        print(
            "ERROR: KANON_CACHE_DIR must be set to use a remote audit target. "
            "Set the environment variable to a writable directory path.",
            file=sys.stderr,
        )
        sys.exit(1)

    idx = source.rfind("@")
    url = source[:idx]
    ref = source[idx + 1 :]

    if not ref:
        print(
            f"ERROR: Empty ref in audit source: '{source}'. Expected '<git_url>@<ref>'.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Canonicalize the URL before hashing to ensure consistent cache keys.
    canonical_url = canonicalize_repo_url(url)
    cache_key = hashlib.sha256(f"{canonical_url}@{ref}".encode()).hexdigest()

    audit_cache_root = pathlib.Path(cache_dir_env) / KANON_CATALOG_AUDIT_CACHE_SUBDIR
    clone_path = audit_cache_root / cache_key

    # Reuse existing clone if it is fresh enough.
    if clone_path.exists():
        mtime = clone_path.stat().st_mtime
        age_seconds = time.time() - mtime
        if age_seconds <= KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS:
            _check_repo_specs_dir(clone_path)
            return clone_path

    # Create the cache directory with owner-only permissions (spec Section 3.6).
    audit_cache_root.mkdir(parents=True, exist_ok=True)
    audit_cache_root.chmod(KANON_CACHE_DIR_MODE)

    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, url, str(clone_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"ERROR: Failed to clone audit target {url}@{ref}:\n{result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)

    _check_repo_specs_dir(clone_path)
    return clone_path


def _check_repo_specs_dir(path: pathlib.Path) -> None:
    """Verify that path contains a repo-specs/ subdirectory.

    Args:
        path: The local directory to check.

    Raises:
        SystemExit: If path does not contain a repo-specs/ subdirectory.
    """
    repo_specs = path / "repo-specs"
    if not repo_specs.is_dir():
        print(
            f"ERROR: Audit target '{path}' does not contain a 'repo-specs/' directory. "
            "Provide a path to a manifest repo (a git repository whose "
            "repo-specs/ directory exposes installable kanon dependencies).",
            file=sys.stderr,
        )
        sys.exit(1)


def _format_findings(findings: list[AuditFinding], fmt: str) -> str:
    """Format a list of AuditFinding objects for output.

    Args:
        findings: The findings to format.
        fmt: Output format -- "text" or "json".

    Returns:
        A string ready to write to stdout. For "text", one finding per line
        with ERROR:/WARN:/INFO: prefix. For "json", a single JSON object
        {"findings": [...]}.

    Raises:
        ValueError: If fmt is not "text" or "json".
    """
    if fmt == KANON_CATALOG_AUDIT_FORMAT_JSON:
        return json.dumps({"findings": [asdict(f) for f in findings]})

    if fmt == KANON_CATALOG_AUDIT_FORMAT_DEFAULT:
        if not findings:
            return ""
        prefix_map = {"error": "ERROR", "warn": "WARN", "info": "INFO"}
        lines = []
        for finding in findings:
            if finding.kind not in prefix_map:
                raise ValueError(
                    f"ERROR: Unknown AuditFinding.kind: '{finding.kind}'. Valid values: error, info, warn."
                )
            prefix = prefix_map[finding.kind]
            line = f"{prefix}: [{finding.code}] {finding.message}"
            if finding.remediation:
                line = f"{line} -- {finding.remediation}"
            lines.append(line)
        return "\n".join(lines)

    raise ValueError(
        f"ERROR: Unknown output format: '{fmt}'. "
        f"Valid values: {KANON_CATALOG_AUDIT_FORMAT_DEFAULT}, {KANON_CATALOG_AUDIT_FORMAT_JSON}."
    )


# ---------------------------------------------------------------------------
# Shared XML walker (used by metadata and source-name-derivation checks)
# ---------------------------------------------------------------------------


def _iter_marketplace_xml(target_path: pathlib.Path) -> Iterator[pathlib.Path]:
    """Yield every ``*-marketplace.xml`` file under ``<target_path>/repo-specs/``.

    Files are yielded in sorted order for deterministic output.

    Args:
        target_path: Root of the manifest repo (must contain ``repo-specs/``).

    Yields:
        Absolute paths to ``*-marketplace.xml`` files.
    """
    repo_specs = target_path / "repo-specs"
    yield from sorted(repo_specs.rglob("*-marketplace.xml"))


def _iter_entry_names(
    target_path: pathlib.Path,
) -> Iterator[tuple[pathlib.Path, str]]:
    """Yield ``(xml_file, entry_name)`` pairs for every parseable marketplace XML.

    Walks ``<target_path>/repo-specs/**/*-marketplace.xml`` via
    :func:`_iter_marketplace_xml`.  For each file the function:

    1. Parses the XML, silently skipping files that raise
       :exc:`XMLParseError` (malformed-XML errors are the ``metadata``
       check's responsibility).
    2. Locates the single ``<catalog-metadata>`` block; skips files with
       zero or more than one such block (structural errors are the
       ``metadata`` check's responsibility).
    3. Reads ``<catalog-metadata><name>``; skips files where the element
       is absent or contains only whitespace (missing-name errors are the
       ``metadata`` check's responsibility).
    4. Yields ``(xml_file, stripped_entry_name)`` for every file that
       passes all three guards.

    Args:
        target_path: Root of the manifest repo (must contain ``repo-specs/``).

    Yields:
        Tuples of ``(xml_file, entry_name)`` where ``entry_name`` is the
        stripped text content of the ``<name>`` element.
    """
    for xml_file in _iter_marketplace_xml(target_path):
        try:
            tree = ET.parse(xml_file)
        except XMLParseError:
            # Malformed XML is the metadata check's responsibility (M003).
            continue

        root = cast("Element", tree.getroot())
        blocks = root.findall("catalog-metadata")
        if len(blocks) != 1:
            # Missing or multiple blocks are the metadata check's responsibility.
            continue

        block = blocks[0]
        name_el = block.find("name")
        if name_el is None or not name_el.text or not name_el.text.strip():
            # Missing or empty name is the metadata check's responsibility (M001).
            continue

        yield xml_file, name_el.text.strip()


# ---------------------------------------------------------------------------
# Metadata check (T2 -- soft-spot rule 1)
# ---------------------------------------------------------------------------


def _check_metadata(target_path: pathlib.Path) -> list[AuditFinding]:
    """Check every ``*-marketplace.xml`` under ``repo-specs/`` for metadata issues.

    Walks ``<target_path>/repo-specs/**/*-marketplace.xml`` via
    :func:`_iter_marketplace_xml` and calls
    :func:`kanon_cli.core.metadata.audit_catalog_metadata` on each file.

    Converts each :class:`MetadataAuditIssue` returned into an
    :class:`AuditFinding` using the severity as ``kind`` and the structured
    ``code`` / ``message`` fields.

    Args:
        target_path: Root of the manifest repo (must contain ``repo-specs/``).

    Returns:
        List of :class:`AuditFinding` objects (possibly empty).
    """
    findings: list[AuditFinding] = []

    for xml_file in _iter_marketplace_xml(target_path):
        for issue in audit_catalog_metadata(xml_file):
            findings.append(
                AuditFinding(
                    kind=issue.severity,
                    code=issue.code,
                    message=issue.message,
                    remediation="",
                )
            )

    return findings


AUDIT_CHECK_REGISTRY["metadata"] = _check_metadata


# ---------------------------------------------------------------------------
# Source-name-derivation check (T3 -- soft-spot rule 2)
# ---------------------------------------------------------------------------


def _check_source_name_derivation(target_path: pathlib.Path) -> list[AuditFinding]:
    """Check every ``*-marketplace.xml`` under ``repo-specs/`` for soft-spot rule 2 issues.

    For each file:
    - Reads ``<catalog-metadata><name>`` (the entry name).
    - Computes the normalised source name via ``derive_source_name(entry_name)``.
    - Emits a WARN finding (S001) when the normalised form differs from the
      original entry name (normalisation drift).
    - Emits a WARN finding (S002) when the entry name contains characters
      outside ``[a-zA-Z0-9_-]`` (out-of-charset).

    Both findings are independent and can both fire for the same entry.

    Args:
        target_path: Root of the manifest repo (must contain ``repo-specs/``).

    Returns:
        List of :class:`AuditFinding` objects (possibly empty).
    """
    findings: list[AuditFinding] = []

    for xml_file, entry_name in _iter_entry_names(target_path):
        # Suppress derive_source_name's stderr side-effect (it prints a raw WARNING
        # when chars are outside [a-zA-Z0-9_-]). The structured S002 finding below
        # already surfaces that information; the raw print would duplicate it.
        with contextlib.redirect_stderr(io.StringIO()):
            derived = derive_source_name(entry_name)

        # Check 1: normalisation drift (S001).
        if derived != entry_name:
            findings.append(
                AuditFinding(
                    kind="warn",
                    code="S001",
                    message=(
                        f"{xml_file}: entry name {entry_name!r} normalises to "
                        f"{derived!r} via derive_source_name. "
                        "Consider renaming the entry to match the derived form "
                        "to avoid surprises in shell variable names and .kanon files."
                    ),
                    remediation=(
                        f"Rename <name>{entry_name}</name> to <name>{derived}</name> in the <catalog-metadata> block."
                    ),
                )
            )

        # Check 2: out-of-charset (S002).
        if not KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE.fullmatch(entry_name):
            findings.append(
                AuditFinding(
                    kind="warn",
                    code="S002",
                    message=(
                        f"{xml_file}: entry name {entry_name!r} contains characters "
                        "outside the recommended set [a-zA-Z0-9_-]. "
                        "Characters outside this set may not survive shell quoting "
                        "cleanly and can cause unexpected behaviour in shell variable names."
                    ),
                    remediation=(
                        f"Rename <name>{entry_name}</name> to use only [a-zA-Z0-9_-] "
                        "characters in the <catalog-metadata> block."
                    ),
                )
            )

    return findings


AUDIT_CHECK_REGISTRY["source-name-derivation"] = _check_source_name_derivation


# ---------------------------------------------------------------------------
# Entry-name-uniqueness check (T4 -- soft-spot rule 3)
# ---------------------------------------------------------------------------


def _check_entry_name_uniqueness(target_path: pathlib.Path) -> list[AuditFinding]:
    """Check that every ``<catalog-metadata><name>`` is unique across all XML files.

    Walks ``<target_path>/repo-specs/**/*-marketplace.xml`` via
    :func:`_iter_entry_names` and builds a mapping from entry name to the
    list of XML paths that declare that name.

    Emits one ERROR finding (U001) per entry name that appears in two or more
    files.  The single finding lists all offending file paths so the author
    can see the full collision at a glance.

    Edge-case handling:

    - An entry name that appears only once produces no finding.
    - An entry name that appears in N > 1 files produces ONE finding (not N),
      listing all N paths.
    - XML files that fail to parse or that have no parseable ``<name>`` element
      are silently skipped -- their errors are the ``metadata`` check's
      responsibility (T2).  The uniqueness check never contributes duplicate
      errors for structural XML problems.
    - Comparison is case-sensitive: ``Foo`` and ``foo`` are distinct names and
      do not collide here.

    Args:
        target_path: Root of the manifest repo (must contain ``repo-specs/``).

    Returns:
        List of :class:`AuditFinding` objects (possibly empty).
    """
    name_to_paths: dict[str, list[pathlib.Path]] = {}

    for xml_file, entry_name in _iter_entry_names(target_path):
        name_to_paths.setdefault(entry_name, []).append(xml_file)

    findings: list[AuditFinding] = []
    for entry_name, paths in sorted(name_to_paths.items()):
        if len(paths) < 2:
            continue
        sorted_paths = sorted(str(p) for p in paths)
        paths_display = ", ".join(sorted_paths)
        findings.append(
            AuditFinding(
                kind="error",
                code="U001",
                message=(
                    f"Entry name {entry_name!r} is declared in {len(paths)} files: "
                    f"{paths_display}. "
                    "Entry names must be unique across every repo-specs/**/*-marketplace.xml file."
                ),
                remediation=(
                    f"Rename <name>{entry_name}</name> to a unique value in all but one of the "
                    "listed files, or remove the duplicate catalog entries."
                ),
            )
        )

    return findings


AUDIT_CHECK_REGISTRY["entry-name-uniqueness"] = _check_entry_name_uniqueness


# ---------------------------------------------------------------------------
# audit_command entrypoint
# ---------------------------------------------------------------------------


def audit_command(args: argparse.Namespace) -> int:
    """Execute the kanon catalog audit subcommand.

    Resolves the audit target, dispatches the selected checks, prints findings
    in the requested format, and returns an exit code.

    Returns exit code 1 when any error-level finding is produced.
    Returns exit code 0 when only warn-level or no findings are present.
    The --strict flag (not yet active) will promote warnings to errors in a
    future release.

    Args:
        args: Parsed argument namespace. Expected attributes:
            target (str): The <dir-or-source> positional argument.
            check_subset (frozenset[str]): Normalized frozenset of check names.
            format (str): Output format ("text" or "json").
            no_color (bool): Whether to suppress ANSI color.
            strict (bool): Parsed but not yet acted upon.

    Returns:
        Integer exit code.
    """
    target_path = _resolve_audit_target(args.target)

    findings: list[AuditFinding] = []
    for check_name in sorted(args.check_subset):
        check_fn = AUDIT_CHECK_REGISTRY.get(check_name)
        if check_fn is not None:
            findings.extend(check_fn(target_path))

    formatted = _format_findings(findings, args.format)
    if formatted:
        print(formatted)

    has_error = any(f.kind == "error" for f in findings)
    return 1 if has_error else 0


# ---------------------------------------------------------------------------
# argparse registration
# ---------------------------------------------------------------------------


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the 'catalog' subcommand group on the top-level argparse subparsers.

    Creates the 'catalog' subparser and registers 'audit' as its sub-subcommand.

    Args:
        subparsers: The subparsers action from the top-level parser.
    """
    catalog_parser: argparse.ArgumentParser = subparsers.add_parser(
        "catalog",
        help="Catalog management subcommands.",
        description="Subcommands for inspecting and auditing manifest repos.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    catalog_subparsers = catalog_parser.add_subparsers(
        dest="catalog_command",
        title="catalog subcommands",
        description="Available catalog operations",
    )

    _register_audit(catalog_subparsers)

    # If no catalog subcommand is given, print help.
    def _catalog_help(args: argparse.Namespace) -> int:
        catalog_parser.print_help()
        return 2

    catalog_parser.set_defaults(func=_catalog_help)


def _register_audit(
    catalog_subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    """Register the 'audit' sub-subcommand on the catalog subparsers.

    Args:
        catalog_subparsers: The subparsers action from the catalog parser.
    """
    valid_checks_list = ", ".join(sorted(KANON_CATALOG_AUDIT_VALID_CHECKS))
    audit_parser: argparse.ArgumentParser = catalog_subparsers.add_parser(
        "audit",
        help="Audit a manifest repo for catalog soft-spot violations.",
        description=(
            "Audit a manifest repo for catalog soft-spot violations.\n\n"
            "TARGET is either a local directory path (must contain repo-specs/) "
            "or a remote <git_url>@<ref> source. Defaults to '.' (current directory).\n\n"
            f"Valid --check values: all, {valid_checks_list}.\n\n"
            "Output format 'text' (default): one finding per line with ERROR:, WARN:, "
            "or INFO: prefix.\n"
            "Output format 'json': a single JSON object {\"findings\": [...]} "
            "written to stdout.\n\n"
            "Cache layout: ${KANON_CACHE_DIR}/catalog-audit/<sha256>/ -- remote "
            "sources are cloned once and reused within KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    audit_parser.add_argument(
        "target",
        nargs="?",
        default=".",
        metavar="<dir-or-source>",
        help=(
            "Path to a local manifest repo directory (must contain repo-specs/) "
            "or a remote '<git_url>@<ref>' catalog source. Defaults to '.' (cwd)."
        ),
    )

    audit_parser.add_argument(
        "--check",
        dest="check",
        default="all",
        type=_parse_check_subset,
        metavar="<subset>",
        help=(
            f"Comma-separated list of checks to run, or 'all' (default). "
            f"Valid values: all, {valid_checks_list}. "
            "Cannot mix 'all' with individual check names."
        ),
    )

    _format_env_val = os.environ.get(KANON_CATALOG_AUDIT_FORMAT_ENV)
    _valid_formats = (KANON_CATALOG_AUDIT_FORMAT_DEFAULT, KANON_CATALOG_AUDIT_FORMAT_JSON)
    if _format_env_val is not None and _format_env_val not in _valid_formats:
        print(
            f"ERROR: {KANON_CATALOG_AUDIT_FORMAT_ENV} has invalid value '{_format_env_val}'. "
            f"Valid values: {KANON_CATALOG_AUDIT_FORMAT_DEFAULT}, {KANON_CATALOG_AUDIT_FORMAT_JSON}.",
            file=sys.stderr,
        )
        sys.exit(1)
    _format_default = _format_env_val if _format_env_val is not None else KANON_CATALOG_AUDIT_FORMAT_DEFAULT

    audit_parser.add_argument(
        "--format",
        dest="format",
        choices=_valid_formats,
        default=_format_default,
        metavar="{text,json}",
        help=(
            "Output format. 'text' prints one finding per line with ERROR:/WARN:/INFO: "
            "prefix. 'json' prints a single JSON object {\"findings\": [...]}. "
            f"Default: text. Env: {KANON_CATALOG_AUDIT_FORMAT_ENV}."
        ),
    )

    audit_parser.add_argument(
        "--strict",
        dest="strict",
        action="store_true",
        default=False,
        help=(
            "Promotes warnings to errors when enabled; exits non-zero when any "
            "WARN-level finding is present (currently parsed but not yet active)."
        ),
    )

    def _run_audit(args: argparse.Namespace) -> int:
        # Normalize the check_subset attribute from the parsed --check value.
        # _parse_check_subset is used as the argparse type function, so args.check
        # already holds the frozenset; store it as check_subset for audit_command.
        args.check_subset = args.check
        return audit_command(args)

    audit_parser.set_defaults(func=_run_audit)
