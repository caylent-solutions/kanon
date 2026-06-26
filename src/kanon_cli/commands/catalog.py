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
  <KANON_HOME>/cache/catalog-audit/<sha256(canonicalized url@ref)>/
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

from kanon_cli import __version__ as _kanon_version

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

import defusedxml.ElementTree as ET
from packaging.version import InvalidVersion, Version

from kanon_cli.completions.cache import cache_dir
from kanon_cli.constants import (
    KANON_CATALOG_AUDIT_CACHE_SUBDIR,
    KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS,
    KANON_CATALOG_AUDIT_FORMAT_DEFAULT,
    KANON_CATALOG_AUDIT_FORMAT_ENV,
    KANON_CATALOG_AUDIT_FORMAT_JSON,
    KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE,
    KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE,
    KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE,
    KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT,
    KANON_CATALOG_AUDIT_VALID_CHECKS,
    KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE,
    KANON_HOME_CACHE_DIR_MODE,
)
from kanon_cli.core.manifest import collect_remote_url_findings
from kanon_cli.core.marketplace_validator import (
    _INVALID_REVISION_HINT,
    _is_pinnable_revision,
    _iter_project_revisions,
)
from kanon_cli.core.metadata import audit_catalog_metadata, derive_source_name, find_catalog_entry_files
from kanon_cli.core.url import canonicalize_repo_url


XMLParseError = ET.ParseError


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


AUDIT_CHECK_REGISTRY: dict[str, Callable[[pathlib.Path], list[AuditFinding]]] = {}


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

    if "@" not in target:
        return False

    idx = target.rfind("@")
    url_part = target[:idx]

    if "://" in url_part:
        return True

    if "@" in url_part:
        return True

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
        SystemExit: If the ref is empty, the clone fails, or the cloned repo
            lacks a repo-specs/ subdirectory.
    """
    idx = source.rfind("@")
    url = source[:idx]
    ref = source[idx + 1 :]

    if not ref:
        print(
            f"ERROR: Empty ref in audit source: '{source}'. Expected '<git_url>@<ref>'.",
            file=sys.stderr,
        )
        sys.exit(1)

    canonical_url = canonicalize_repo_url(url)
    cache_key = hashlib.sha256(f"{canonical_url}@{ref}".encode()).hexdigest()

    audit_cache_root = cache_dir() / KANON_CATALOG_AUDIT_CACHE_SUBDIR
    clone_path = audit_cache_root / cache_key

    if clone_path.exists():
        mtime = clone_path.stat().st_mtime
        age_seconds = time.time() - mtime
        if age_seconds <= KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS:
            _check_repo_specs_dir(clone_path)
            return clone_path

    audit_cache_root.mkdir(parents=True, exist_ok=True)
    audit_cache_root.chmod(KANON_HOME_CACHE_DIR_MODE)

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


def _build_findings_payload(findings: list[AuditFinding]) -> dict:
    """Build the JSON-serialisable payload for a list of :class:`AuditFinding`.

    Returns a dict with a single ``findings`` key whose value is a list of
    finding dicts (via ``dataclasses.asdict``).

    Args:
        findings: The findings to convert.

    Returns:
        A dict ready for JSON serialisation.
    """
    return {"findings": [asdict(f) for f in findings]}


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
        return json.dumps(_build_findings_payload(findings))

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


def _iter_entry_names(
    target_path: pathlib.Path,
) -> Iterator[tuple[pathlib.Path, str]]:
    """Yield ``(xml_file, entry_name)`` pairs for every parseable catalog entry.

    Walks every catalog entry manifest (any ``repo-specs/**/*.xml`` that carries a
    ``<catalog-metadata>`` block) via
    :func:`kanon_cli.core.metadata.find_catalog_entry_files`.  For each file the function:

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
    for xml_file in find_catalog_entry_files(target_path):
        try:
            tree = ET.parse(xml_file)
        except XMLParseError:
            continue

        root = cast("Element", tree.getroot())
        blocks = root.findall("catalog-metadata")
        if len(blocks) != 1:
            continue

        block = blocks[0]
        name_el = block.find("name")
        if name_el is None or not name_el.text or not name_el.text.strip():
            continue

        yield xml_file, name_el.text.strip()


def _check_metadata(target_path: pathlib.Path) -> list[AuditFinding]:
    """Check every catalog entry manifest under ``repo-specs/`` for metadata issues.

    Walks every catalog entry manifest (any ``repo-specs/**/*.xml`` that carries a
    ``<catalog-metadata>`` block) via
    :func:`kanon_cli.core.metadata.find_catalog_entry_files` and calls
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

    for xml_file in find_catalog_entry_files(target_path):
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
        with contextlib.redirect_stderr(io.StringIO()):
            derived = derive_source_name(entry_name)

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


def _check_remote_url(
    target_path: pathlib.Path,
    env: dict[str, str] | None = None,
) -> list[AuditFinding]:
    """Check every ``*-marketplace.xml`` under ``repo-specs/`` for remote-URL issues.

    Walks every ``<include>`` chain reachable from each marketplace XML
    (depth-first, cycle-safe) and resolves every ``<project remote="X">``
    to a concrete fetch URL via the corresponding ``<remote name="X">``
    definition.  Produces one of three error codes:

    - R001: ``<remote name="X">`` cannot be resolved anywhere in the
      reachable include chain.
    - R002: The resolved fetch URL uses a non-HTTPS/non-SSH scheme and
      ``KANON_ALLOW_INSECURE_REMOTES`` is not ``"1"`` in ``env``.
    - R003: The resolved fetch URL contains a query string (``?``) or
      fragment (``#``); URL canonicalization is undefined for such values.

    The ``env`` parameter is used instead of ``os.environ`` so unit tests
    can inject ``KANON_ALLOW_INSECURE_REMOTES`` without mutating the
    process environment.  When ``env`` is ``None``, ``os.environ`` is used
    as the effective environment.

    Args:
        target_path: Root of the manifest repo (must contain ``repo-specs/``).
        env: Environment dict to read ``KANON_ALLOW_INSECURE_REMOTES`` from.
            Defaults to a copy of ``os.environ`` when ``None``.

    Returns:
        List of :class:`AuditFinding` objects (possibly empty).
    """
    effective_env: dict[str, str] = dict(os.environ) if env is None else env
    raw_findings = collect_remote_url_findings(target_path, env=effective_env)
    return [
        AuditFinding(
            kind=rf.kind,
            code=rf.code,
            message=rf.message,
            remediation=rf.remediation,
        )
        for rf in raw_findings
    ]


def _check_remote_url_with_os_env(target_path: pathlib.Path) -> list[AuditFinding]:
    """Registry-compatible wrapper: calls _check_remote_url with os.environ.

    This wrapper satisfies the ``Callable[[pathlib.Path], list[AuditFinding]]``
    signature required by ``AUDIT_CHECK_REGISTRY``.  The underlying
    ``_check_remote_url`` function accepts an ``env`` parameter for testability.

    Args:
        target_path: Root of the manifest repo (must contain ``repo-specs/``).

    Returns:
        List of :class:`AuditFinding` objects produced by ``_check_remote_url``.
    """
    return _check_remote_url(target_path, env=None)


AUDIT_CHECK_REGISTRY["remote-url"] = _check_remote_url_with_os_env


def _check_project_revision_exact_tags(target_path: pathlib.Path) -> list[AuditFinding]:
    """Check that every ``<project revision>`` in the catalog is pinnable.

    Scans every catalog-entry manifest under ``target_path/repo-specs/`` and
    validates each ``<project>`` element's effective revision -- its own
    ``revision`` attribute, or the ``<default revision>`` it inherits when the
    attribute is omitted -- against the SAME pinnable rule that
    ``kanon validate marketplace`` enforces, by reusing the shared
    :func:`kanon_cli.core.marketplace_validator._is_pinnable_revision`
    predicate (DRY: the pinnable grammar is never duplicated).

    A deep-path tag, a ``refs/heads/<name>`` branch ref, and a 40-hex commit SHA
    are accepted; the ``*`` wildcard, a bare branch name, and a single or
    compound version-range constraint (e.g. ``>=0.1.0,<1.0.0``) are rejected as
    ERROR findings (code ``T002``) so that catalog audit and validate
    marketplace agree: a revision validate marketplace rejects is rejected here
    identically (AMENDED 2026-06-25).

    Args:
        target_path: Root of the manifest repo (must contain ``repo-specs/``).

    Returns:
        List of :class:`AuditFinding` objects (kind ``error``; possibly empty).
    """
    findings: list[AuditFinding] = []
    for xml_file in find_catalog_entry_files(target_path):
        for project_name, revision, inherited in _iter_project_revisions(xml_file, target_path):
            if _is_pinnable_revision(revision):
                continue
            source = "inherited <default revision>" if inherited else "revision"
            findings.append(
                AuditFinding(
                    kind="error",
                    code="T002",
                    message=(
                        f"{xml_file}: <project name={project_name!r}> has invalid {source}"
                        f"={revision!r}: {_INVALID_REVISION_HINT}. "
                        "kanon validate marketplace rejects this revision; catalog audit "
                        "rejects it identically."
                    ),
                    remediation=(
                        f"Pin {project_name!r} to an exact tag refs/tags/<path>/<pep440> "
                        "(e.g. refs/tags/my-plugin/1.0.0), a branch ref refs/heads/<name>, "
                        "or a 40-hex commit SHA. "
                        "Run 'kanon validate marketplace' to confirm the manifest is clean."
                    ),
                )
            )
    return findings


def _check_tag_format(
    target_path: pathlib.Path,
    ls_remote_callable: "Callable[[pathlib.Path], str]",
) -> list[AuditFinding]:
    """Check manifest tag formatting two ways: repo tag PEP 440-ness and project-revision exactness.

    Two complementary checks are run and their findings concatenated:

    1. Manifest-repo tag surface (code ``T001``, WARN): calls
       ``ls_remote_callable(target_path)`` to obtain the raw stdout of
       ``git ls-remote --tags <target_path>`` (one ``<sha>\\trefs/tags/<name>``
       line per tag).  For each tag, takes the last ``/``-delimited component
       and attempts to parse it as a ``packaging.version.Version``.  Tags whose
       last path component fails PEP 440 parsing emit one WARN finding each.
       Findings are capped at ``KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT``; when
       more non-PEP-440 tags exist, a single additional WARN finding summarises
       the remaining count.  Warning-only (never error) per spec Section 0.4:
       manifest repos with legitimate non-version tags still work; the warning
       surfaces unaddressability.  Monorepo-style tags (``subpackage/1.0.0``)
       are handled correctly -- only the last ``/``-delimited component is
       tested.

    2. ``<project revision>`` pinnability (code ``T002``, ERROR): every
       ``<project>`` element's effective revision is validated against the same
       pinnable rule ``kanon validate marketplace`` enforces, via the shared
       :func:`_check_project_revision_exact_tags` helper (which reuses the
       :func:`_is_pinnable_revision` predicate).  A revision validate
       marketplace rejects (the ``*`` wildcard, a bare branch name, a
       version-range constraint) is rejected here identically, so the two
       commands agree.

    Args:
        target_path: Root of the manifest repo (must contain ``repo-specs/``).
        ls_remote_callable: A callable accepting ``target_path`` and returning
            the raw stdout of ``git ls-remote --tags <target_path>``.  Injected
            to allow unit tests to avoid real network calls.

    Returns:
        List of :class:`AuditFinding` objects (``T001`` WARN + ``T002`` ERROR;
        possibly empty).
    """
    raw_output = ls_remote_callable(target_path)

    non_pep440_tags: list[str] = []

    for line in raw_output.splitlines():
        line = line.strip()
        if not line:
            continue

        if "\t" not in line:
            continue
        _, ref = line.split("\t", 1)
        ref = ref.strip()
        if not ref.startswith("refs/tags/"):
            continue

        if ref.endswith("^{}"):
            continue
        tag_name = ref[len("refs/tags/") :]
        if not tag_name:
            continue

        last_component = tag_name.rsplit("/", 1)[-1]
        try:
            parsed = Version(last_component)

            if str(parsed) != last_component:
                non_pep440_tags.append(tag_name)
        except InvalidVersion:
            non_pep440_tags.append(tag_name)

    findings: list[AuditFinding] = []

    for tag_name in non_pep440_tags[:KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT]:
        findings.append(
            AuditFinding(
                kind="warn",
                code="T001",
                message=(
                    f"Tag {tag_name!r} is unaddressable: the last path component "
                    f"{tag_name.rsplit('/', 1)[-1]!r} is not a valid PEP 440 version. "
                    "kanon's resolver ignores tags whose last component does not parse "
                    "as a PEP 440 version."
                ),
                remediation=(
                    "Rename the tag so its last path component is a valid PEP 440 version "
                    "(e.g. '1.0.0', '1.0.0a1'). "
                    "See https://peps.python.org/pep-0440/ for PEP 440 version syntax."
                ),
            )
        )

    remaining = len(non_pep440_tags) - KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT
    if remaining > 0:
        findings.append(
            AuditFinding(
                kind="warn",
                code="T001",
                message=KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE.format(remaining=remaining),
                remediation=(
                    "Run 'kanon catalog audit --check tag-format' against the full repo "
                    "to see all non-PEP-440 tag findings."
                ),
            )
        )

    findings.extend(_check_project_revision_exact_tags(target_path))

    return findings


def _check_tag_format_with_subprocess(target_path: pathlib.Path) -> list[AuditFinding]:
    """Registry-compatible wrapper: calls _check_tag_format with a real git ls-remote subprocess.

    Runs ``git ls-remote --tags <target_path>`` as a subprocess and feeds its
    stdout to :func:`_check_tag_format`.  Fails loudly on subprocess error.

    Args:
        target_path: Root of the manifest repo (must contain ``repo-specs/``).

    Returns:
        List of :class:`AuditFinding` objects produced by ``_check_tag_format``.

    Raises:
        SystemExit: If ``git ls-remote --tags`` exits non-zero.
    """

    def _run_ls_remote(path: pathlib.Path) -> str:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(
                f"ERROR: 'git ls-remote --tags {path}' failed (exit {result.returncode}):\n{result.stderr}",
                file=sys.stderr,
            )
            sys.exit(1)
        return result.stdout

    return _check_tag_format(target_path, _run_ls_remote)


AUDIT_CHECK_REGISTRY["tag-format"] = _check_tag_format_with_subprocess


def _check_legacy_catalog_dir(
    target_path: pathlib.Path,
    version: str,
) -> list[AuditFinding]:
    """Detect a legacy catalog/<name>/ directory tree inside the audit target.

    Runs unconditionally on every ``kanon catalog audit`` invocation regardless
    of the ``--check`` value; the check is NOT one of the selectable check names.

    Detection rule:
    - If ``catalog/`` exists AND contains at least one immediate subdirectory =>
      emit one WARN finding (code L001) using the message template from
      ``KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE``.
    - If ``catalog/`` exists but contains no subdirectories (files only) =>
      no finding (empty residual is harmless).
    - If ``catalog/`` does not exist => no finding.

    The warning is not a hard error during the deprecation window; it will be
    promoted to an error in a future release (spec Section 15).

    Args:
        target_path: Root of the manifest repo (must contain ``repo-specs/``).
        version: The running kanon CLI version string, interpolated into the
            warning message so users see which release removed the directory.

    Returns:
        A list containing zero or one ``AuditFinding`` with kind ``"warn"``
        and code ``"L001"``.
    """
    catalog_dir = target_path / "catalog"
    if not catalog_dir.is_dir():
        return []

    child_dirs = [p for p in catalog_dir.iterdir() if p.is_dir()]
    if not child_dirs:
        return []

    message = KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE.format(version=version)
    return [
        AuditFinding(
            kind="warn",
            code="L001",
            message=message,
            remediation="",
        )
    ]


def audit_command(args: argparse.Namespace) -> int:
    """Execute the kanon catalog audit subcommand.

    Resolves the audit target, dispatches the selected checks, prints findings
    in the requested format, and returns an exit code.

    Default mode:
        Returns exit code 1 when any error-level finding is produced.
        Returns exit code 0 when only warn-level or no findings are present.

    --strict mode:
        Returns exit code 1 when any error-level OR warn-level finding is produced.
        Prints a one-line summary to stderr naming the warning count when warnings
        exist: "strict mode: <count> warning(s) treated as errors".
        Findings are NOT mutated; the display still shows WARN: prefixes.

    Args:
        args: Parsed argument namespace. Expected attributes:
            target (str): The <dir-or-source> positional argument.
            check_subset (frozenset[str]): Normalized frozenset of check names.
            format (str): Output format ("text" or "json").
            no_color (bool): Whether to suppress ANSI color.
            strict (bool): When True, promotes warnings to errors for exit-code
                computation and prints a strict-mode summary to stderr.

    Returns:
        Integer exit code.
    """
    target_path = _resolve_audit_target(args.target)

    findings: list[AuditFinding] = []
    for check_name in sorted(args.check_subset):
        check_fn = AUDIT_CHECK_REGISTRY.get(check_name)
        if check_fn is not None:
            findings.extend(check_fn(target_path))

    findings.extend(_check_legacy_catalog_dir(target_path, _kanon_version))

    if args.format == KANON_CATALOG_AUDIT_FORMAT_JSON:
        from kanon_cli.cli import _emit_json_payload

        _emit_json_payload(_build_findings_payload(findings))
    else:
        formatted = _format_findings(findings, args.format)
        if formatted:
            print(formatted)

    errors = [f for f in findings if f.kind == "error"]
    warns = [f for f in findings if f.kind == "warn"]

    if args.strict and warns:
        print(
            KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE.format(count=len(warns)),
            file=sys.stderr,
        )

    if args.strict:
        return 1 if (errors or warns) else 0
    return 1 if errors else 0


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the 'catalog' subcommand group on the top-level argparse subparsers.

    Creates the 'catalog' subparser and registers 'audit' as its sub-subcommand.

    Args:
        subparsers: The subparsers action from the top-level parser.
    """
    catalog_parser: argparse.ArgumentParser = subparsers.add_parser(
        "catalog",
        add_help=True,
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
        add_help=True,
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
            "Cache layout: <KANON_HOME>/cache/catalog-audit/<sha256>/ -- remote "
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
            "WARN-level finding is present. Prints a one-line summary to stderr "
            "naming the warning count when warnings exist."
        ),
    )

    def _run_audit(args: argparse.Namespace) -> int:
        args.check_subset = args.check
        return audit_command(args)

    audit_parser.set_defaults(func=_run_audit)
