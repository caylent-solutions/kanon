"""Shared catalog-metadata reader for kanon commands.

Parses the ``<catalog-metadata>`` block from catalog entry manifests and
returns a :class:`CatalogMetadata` dataclass. A *catalog entry* is any
``repo-specs/**/*.xml`` manifest that declares a ``<catalog-metadata>`` block
(see :func:`find_catalog_entry_files`); the entry's filename is unrestricted.
Every entry -- whether a packaged Claude marketplace or a plain package --
carries the same required metadata fields.

Every command that consumes marketplace metadata (``kanon list``,
``kanon add``, ``kanon outdated``, ``kanon why``, ``kanon catalog audit``,
``kanon validate metadata``) uses this module to avoid schema-check drift.

Soft-spot rule 1 semantics
--------------------------
Per ``spec/kanon-list-add-lock-features-spec.md`` Section 3.5, the
``<version>`` field is the author-claimed, informational version string. It
is not validated against semver or PEP-440 here; callers that need
version semantics (e.g. the resolver) are responsible for further parsing.

Required fields: ``name``, ``display-name``, ``description``, ``version``.
Recommended fields: ``type``, ``owner-name``, ``owner-email``, ``keywords``.

Soft-spot rule 2 semantics -- :func:`derive_source_name`
---------------------------------------------------------
:func:`derive_source_name` normalises a ``<catalog-metadata><name>`` value
into a ``KANON_SOURCE_<name>_*`` shell-variable token by unconditionally
lowercasing the input and replacing every ``-`` with ``_``. No other
transformation is applied. If the input contains any character outside the
recommended set ``[a-zA-Z0-9_-]``, a single-line warning is emitted to
stderr; the transformation is still applied and the result is returned.
Empty strings produce empty strings without a warning. The function is
deterministic, pure, and idempotent. Downstream consumers include
``kanon add``, ``kanon remove``, ``kanon why``, and
``kanon install --refresh-lock-source``.
"""

import re
import sys
from typing import cast

import defusedxml.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree.ElementTree import Element, ParseError as XMLParseError

from kanon_cli.constants import (
    KANON_CATALOG_METADATA_RECOMMENDED_FIELDS,
    KANON_CATALOG_METADATA_REQUIRED_FIELDS,
    RECOMMENDED_CHAR_RE,
)

# A catalog *entry* is any manifest that declares a <catalog-metadata> block.
# Entries are identified by this content marker rather than by a filename
# convention: an entry manifest may use ANY name (e.g. widget-pkg.xml,
# my-tool.xml, foo-marketplace.xml). Manifests without the marker -- shared
# <include> targets such as remote.xml -- are not entries (but remain valid
# manifests: `validate xml` still checks them and entries still <include> them).
_CATALOG_METADATA_MARKER = "<catalog-metadata"

# The marker is ignored when it appears only inside an XML comment -- e.g. an
# <include> file (remote.xml) whose comment documents the scheme in prose. Such
# a file is not a catalog entry, so comments are stripped before the check.
_XML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def find_catalog_entry_files(repo_root: Path) -> list[Path]:
    """Return the sorted catalog-entry manifests under ``repo_root/repo-specs/``.

    A *catalog entry* is any ``*.xml`` manifest under ``repo-specs/`` whose text
    contains a ``<catalog-metadata>`` element. Manifests without that block --
    shared ``<include>`` targets such as ``remote.xml`` -- are excluded from the
    entry set (they are still validated by ``kanon validate xml`` and are still
    resolved when an entry ``<include>``\\ s them). Entry manifests may use any
    filename; the legacy ``*-marketplace.xml`` suffix is no longer required
    (files so named still match because they carry the block).

    Files that cannot be read are skipped. A file that contains the marker but
    is otherwise malformed is still returned, so downstream parsing surfaces the
    error rather than silently dropping an intended entry.

    Args:
        repo_root: Root of the manifest repo (the directory that contains
            ``repo-specs/``).

    Returns:
        Sorted list of entry-manifest paths. Empty when ``repo-specs/`` is
        absent or contains no entry manifests.
    """
    repo_specs = repo_root / "repo-specs"
    if not repo_specs.is_dir():
        return []
    entries: list[Path] = []
    for xml_path in repo_specs.rglob("*.xml"):
        try:
            text = xml_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _CATALOG_METADATA_MARKER in _XML_COMMENT_RE.sub("", text):
            entries.append(xml_path)
    return sorted(entries)


# New-scheme-only: catalog metadata MUST be carried as nested child elements of
# <catalog-metadata>. The legacy "flat-attribute" scheme put these fields as
# attributes ON the element (e.g. <catalog-metadata name="..." display-name="..."/>)
# and is no longer supported. Any of these keys present as an *attribute* on the
# <catalog-metadata> element identifies the old scheme.
_OLD_FLAT_ATTRIBUTE_KEYS = frozenset(KANON_CATALOG_METADATA_REQUIRED_FIELDS) | frozenset(
    KANON_CATALOG_METADATA_RECOMMENDED_FIELDS
)


def _old_flat_attribute_message(xml_path: Path, flat_attrs: set[str]) -> str:
    """Build the explicit migration error for the unsupported old flat-attribute scheme."""
    return (
        f"{xml_path}: <catalog-metadata> uses the unsupported old flat-attribute "
        f"scheme (metadata as attributes: {', '.join(sorted(flat_attrs))}). "
        "Only the nested scheme is supported -- migrate to "
        "<catalog-metadata><name>...</name><display-name>...</display-name>"
        "<description>...</description><version>...</version>...</catalog-metadata>."
    )


class CatalogMetadataParseError(ValueError):
    """Raised when a ``*-marketplace.xml`` catalog-metadata block is invalid.

    The error message always names the source file path and the specific
    problem so the operator knows exactly what to fix.
    """


@dataclass
class CatalogMetadata:
    """Structured representation of a ``<catalog-metadata>`` XML block.

    Required fields (missing or whitespace-only raises
    :class:`CatalogMetadataParseError`):

    - ``name`` -- machine-readable package identifier.
    - ``display_name`` -- human-readable label.
    - ``description`` -- short prose description.
    - ``version`` -- author-claimed version string (informational only per
      spec Section 1.1; not validated against any versioning scheme here).

    Recommended fields (missing fields emit a consolidated ``WARNING`` to
    stderr; the slot holds ``None`` or ``[]``):

    - ``type`` -- package type string (e.g. ``plugin``, ``library``).
    - ``owner_name`` -- primary owner display name.
    - ``owner_email`` -- primary owner contact address.
    - ``keywords`` -- list of keyword strings, empty when absent.

    See ``spec/kanon-list-add-lock-features-spec.md`` Section 3.5 for the
    soft-spot rule 1 semantics that govern this dataclass.
    """

    name: str
    display_name: str
    description: str
    version: str
    type: str | None = None
    owner_name: str | None = None
    owner_email: str | None = None
    keywords: list[str] = field(default_factory=list)


def _check_duplicate_children(block: Element, xml_path: Path) -> None:
    """Raise :class:`CatalogMetadataParseError` if any child tag appears twice.

    Args:
        block: The ``<catalog-metadata>`` XML element.
        xml_path: Source file path, included in any error message.

    Raises:
        CatalogMetadataParseError: When a duplicate child tag is detected.
    """
    seen: set[str] = set()
    for child in block:
        if child.tag in seen:
            raise CatalogMetadataParseError(
                f"{xml_path}: duplicate <{child.tag}> element inside "
                "<catalog-metadata>; each child tag must appear at most once."
            )
        seen.add(child.tag)


def _parse_catalog_metadata(xml_path: Path) -> CatalogMetadata:
    """Parse the single ``<catalog-metadata>`` block in a marketplace XML file.

    Reads ``xml_path`` using :mod:`defusedxml.ElementTree`, validates the
    structure, and returns a populated :class:`CatalogMetadata` dataclass.

    Validation rules (all failures raise :class:`CatalogMetadataParseError`):

    - Malformed XML -- wraps the parser error and names the file.
    - Zero ``<catalog-metadata>`` blocks -- names the file.
    - More than one ``<catalog-metadata>`` block -- names the file and count.
    - Old flat-attribute scheme (metadata carried as attributes on the
      ``<catalog-metadata>`` element) -- new-scheme-only; raises an explicit
      "migrate to the nested scheme" error rather than a generic missing-field error.
    - Duplicate child elements inside the block -- names the tag and file.
    - Missing required field -- names the field and the file.
    - Whitespace-only required field text -- treated as missing (same error).

    Missing recommended fields (``type``, ``owner-name``, ``owner-email``,
    ``keywords``) emit a single consolidated ``WARNING:`` line to stderr; the
    returned dataclass holds ``None`` (or ``[]`` for ``keywords``) in those
    slots.

    ``keywords`` is parsed from the text content of a single ``<keywords>``
    child element whose text is comma-separated. Whitespace around each token
    is stripped. An empty ``<keywords>`` element yields ``[]``, not ``None``.

    See ``spec/kanon-list-add-lock-features-spec.md`` Section 3.5 for the
    soft-spot rule 1 semantics (``version`` is author-claimed and
    informational only).

    Args:
        xml_path: Path to the ``*-marketplace.xml`` file.

    Returns:
        Populated :class:`CatalogMetadata` dataclass.

    Raises:
        CatalogMetadataParseError: On any structural or content validation
            failure described above.
    """
    try:
        tree = ET.parse(xml_path)
    except XMLParseError as exc:
        raise CatalogMetadataParseError(f"{xml_path}: malformed XML -- {exc}") from exc

    root = tree.getroot()
    # defusedxml.ElementTree.parse() guarantees a non-None root on success;
    # XMLParseError (caught above) handles every failure path.  The cast
    # narrows the type for mypy without runtime cost or -O brittleness.
    root = cast(Element, root)
    blocks = root.findall("catalog-metadata")

    if len(blocks) == 0:
        raise CatalogMetadataParseError(f"{xml_path}: no <catalog-metadata> block found; exactly one is required.")
    if len(blocks) > 1:
        raise CatalogMetadataParseError(
            f"{xml_path}: {len(blocks)} <catalog-metadata> blocks found; exactly one is required."
        )

    block = blocks[0]
    _check_duplicate_children(block, xml_path)

    # New-scheme-only: reject the legacy flat-attribute scheme explicitly so the
    # operator gets a clear migration message instead of a generic missing-field error.
    flat_attrs = set(block.attrib) & _OLD_FLAT_ATTRIBUTE_KEYS
    if flat_attrs:
        raise CatalogMetadataParseError(_old_flat_attribute_message(xml_path, flat_attrs))

    # Build a tag -> text mapping for quick lookup.
    children: dict[str, str | None] = {}
    for child in block:
        children[child.tag] = child.text

    # Validate and read required fields.
    def _require(tag: str) -> str:
        raw = children.get(tag)
        if raw is None or not raw.strip():
            raise CatalogMetadataParseError(
                f"{xml_path}: required <catalog-metadata> field <{tag}> is missing or contains only whitespace."
            )
        return raw.strip()

    name = _require("name")
    display_name = _require("display-name")
    description = _require("description")
    version = _require("version")

    # Gather recommended fields; collect absent ones for the warning.
    missing_recommended: list[str] = []

    def _optional(tag: str) -> str | None:
        if tag not in children:
            missing_recommended.append(tag)
            return None
        raw = children[tag]
        if raw is None or not raw.strip():
            return None
        return raw.strip()

    pkg_type = _optional("type")
    owner_name = _optional("owner-name")
    owner_email = _optional("owner-email")

    # Keywords handling: comma-separated text from <keywords> element.
    if "keywords" not in children:
        missing_recommended.append("keywords")
        keywords: list[str] = []
    else:
        raw_kw = children["keywords"]
        if raw_kw is None or not raw_kw.strip():
            keywords = []
        else:
            keywords = [token.strip() for token in raw_kw.split(",") if token.strip()]

    if missing_recommended:
        print(
            f"WARNING: {xml_path}: recommended <catalog-metadata> fields missing: " + ", ".join(missing_recommended),
            file=sys.stderr,
        )

    return CatalogMetadata(
        name=name,
        display_name=display_name,
        description=description,
        version=version,
        type=pkg_type,
        owner_name=owner_name,
        owner_email=owner_email,
        keywords=keywords,
    )


@dataclass
class MetadataAuditIssue:
    """A single structured issue found by :func:`audit_catalog_metadata`.

    Used by ``kanon catalog audit --check metadata`` to collect per-field
    findings without re-parsing the XML or raising exceptions.

    Attributes:
        severity: ``"error"`` or ``"warn"``.
        code: Short machine-readable identifier for the issue type.
        message: Human-readable description including the XML file path,
            the affected field name, and a clear remediation hint.
    """

    severity: str
    code: str
    message: str


def audit_catalog_metadata(xml_path: Path) -> list[MetadataAuditIssue]:
    """Inspect one ``*-marketplace.xml`` for catalog-metadata soft-spot rule 1 issues.

    Returns a list of :class:`MetadataAuditIssue` objects (possibly empty).
    Never raises; all structural and content problems are returned as issues.

    Issues produced (in discovery order):

    - ``"error"`` / ``M003``: malformed XML (parse failure).
    - ``"error"`` / ``M004``: zero ``<catalog-metadata>`` blocks.
    - ``"error"`` / ``M005``: more than one ``<catalog-metadata>`` block (names count).
    - ``"error"`` / ``M007``: unsupported old flat-attribute scheme (metadata carried as
      attributes on the ``<catalog-metadata>`` element instead of nested children).
    - ``"error"`` / ``M006``: duplicate child tag within the single block.
    - ``"error"`` / ``M001``: required field missing or whitespace-only.
    - ``"warn"``  / ``M002``: recommended field absent.

    Args:
        xml_path: Path to the ``*-marketplace.xml`` file.

    Returns:
        List of :class:`MetadataAuditIssue` objects describing every issue
        found.  An empty list means the file is fully compliant.
    """
    issues: list[MetadataAuditIssue] = []

    try:
        tree = ET.parse(xml_path)
    except XMLParseError as exc:
        issues.append(
            MetadataAuditIssue(
                severity="error",
                code="M003",
                message=(f"{xml_path}: malformed XML -- {exc}. Repair or regenerate the XML file."),
            )
        )
        return issues

    root = cast(Element, tree.getroot())
    blocks = root.findall("catalog-metadata")

    if len(blocks) == 0:
        issues.append(
            MetadataAuditIssue(
                severity="error",
                code="M004",
                message=(
                    f"{xml_path}: no <catalog-metadata> block found; "
                    "exactly one is required. "
                    "Add a <catalog-metadata> element to the XML file."
                ),
            )
        )
        return issues

    if len(blocks) > 1:
        issues.append(
            MetadataAuditIssue(
                severity="error",
                code="M005",
                message=(
                    f"{xml_path}: {len(blocks)} <catalog-metadata> blocks found; "
                    "exactly one is required. "
                    "Remove the extra <catalog-metadata> elements."
                ),
            )
        )
        return issues

    block = blocks[0]

    # New-scheme-only: flag the unsupported old flat-attribute scheme explicitly
    # (metadata as attributes on <catalog-metadata>) instead of reporting it as a
    # set of generic missing-required-field errors.
    flat_attrs = set(block.attrib) & _OLD_FLAT_ATTRIBUTE_KEYS
    if flat_attrs:
        issues.append(
            MetadataAuditIssue(
                severity="error",
                code="M007",
                message=_old_flat_attribute_message(xml_path, flat_attrs),
            )
        )
        return issues

    # Check for duplicate child tags.
    seen_tags: set[str] = set()
    for child in block:
        if child.tag in seen_tags:
            issues.append(
                MetadataAuditIssue(
                    severity="error",
                    code="M006",
                    message=(
                        f"{xml_path}: duplicate <{child.tag}> element inside "
                        "<catalog-metadata>; each child tag must appear at most once. "
                        f"Remove the extra <{child.tag}> element."
                    ),
                )
            )
        seen_tags.add(child.tag)

    # If duplicate tags were found, field-level checks are unreliable -- return early.
    if any(i.code == "M006" for i in issues):
        return issues

    # Build tag -> stripped text mapping.
    children: dict[str, str | None] = {child.tag: child.text for child in block}

    # Check required fields.
    for tag_name in KANON_CATALOG_METADATA_REQUIRED_FIELDS:
        raw = children.get(tag_name)
        if raw is None or not raw.strip():
            issues.append(
                MetadataAuditIssue(
                    severity="error",
                    code="M001",
                    message=(
                        f"{xml_path}: required <catalog-metadata> field <{tag_name}> "
                        "is missing or contains only whitespace. "
                        f"Add a non-empty <{tag_name}> element to the <catalog-metadata> block."
                    ),
                )
            )

    # Check recommended fields.
    for tag_name in KANON_CATALOG_METADATA_RECOMMENDED_FIELDS:
        if tag_name not in children:
            issues.append(
                MetadataAuditIssue(
                    severity="warn",
                    code="M002",
                    message=(
                        f"{xml_path}: recommended <catalog-metadata> field <{tag_name}> "
                        "is absent. "
                        f"Consider adding <{tag_name}> to improve catalog discoverability."
                    ),
                )
            )

    return issues


def derive_source_name(entry_name: str, *, warn: bool = True) -> str:
    """Normalise ``<catalog-metadata><name>`` to a ``KANON_SOURCE_<name>_*`` token.

    Applies soft-spot rule 2 from ``spec/kanon-list-add-lock-features-spec.md``
    Section 3.5 unconditionally:

    1. Lowercase the input.
    2. Replace every ``-`` with ``_``.

    No other transformation is applied. The function is deterministic, pure,
    and idempotent: ``derive_source_name(derive_source_name(x))`` equals
    ``derive_source_name(x)`` for every legal input.

    If the input contains any character outside the set ``[a-zA-Z0-9_-]`` and
    ``warn`` is ``True`` (the default), a single-line warning is emitted to
    stderr noting that the entry name contains characters outside the recommended
    set and the normalised form may not survive shell quoting cleanly. The
    transformation is still applied and the result is returned. Empty strings
    produce empty strings; the empty string is not considered outside the
    recommended set and emits no warning.

    Pass ``warn=False`` when calling from query paths (e.g. ``kanon why``) where
    the argument is a URL or file path rather than a catalog entry name being
    authored; the normalisation is still performed but no spurious warning is
    printed for the user's query argument.

    Downstream consumers: ``kanon add``, ``kanon remove``, ``kanon why``,
    ``kanon install --refresh-lock-source``.

    Args:
        entry_name: The raw ``<name>`` value from a ``<catalog-metadata>`` block,
            or a query argument (URL, path) when called from ``kanon why``.
        warn: When ``True`` (default), emit a stderr WARNING if ``entry_name``
            contains characters outside ``[a-zA-Z0-9_-]``. Authoring paths
            (``kanon add``, ``kanon remove``, ``kanon install
            --refresh-lock-source``) keep the default. Query paths (``kanon
            why``) pass ``False`` to suppress spurious warnings on URL/path
            arguments.

    Returns:
        The lowercased, hyphen-to-underscore-converted source name token.
    """
    if warn and entry_name and not RECOMMENDED_CHAR_RE.fullmatch(entry_name):
        print(
            f"WARNING: entry name {entry_name!r} contains characters outside the "
            "recommended set [a-zA-Z0-9_-]; the normalised form may not survive "
            "shell quoting cleanly.",
            file=sys.stderr,
        )
    return entry_name.lower().replace("-", "_")
