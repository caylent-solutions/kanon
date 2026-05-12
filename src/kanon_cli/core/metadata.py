"""Shared catalog-metadata reader for kanon commands.

Parses the ``<catalog-metadata>`` block from ``*-marketplace.xml`` files and
returns a :class:`CatalogMetadata` dataclass.

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

import sys
from typing import cast

import defusedxml.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree.ElementTree import Element, ParseError as XMLParseError

from kanon_cli.constants import RECOMMENDED_CHAR_RE


class CatalogMetadataParseError(ValueError):
    """Raised when a ``*-marketplace.xml`` catalog-metadata block is invalid.

    The error message always names the source file path and the specific
    problem so the operator knows exactly what to fix.
    """


# Tags that map to required fields on CatalogMetadata.
_REQUIRED_TAGS: tuple[str, ...] = ("name", "display-name", "description", "version")

# Tags that map to recommended (optional) fields on CatalogMetadata.
# "keywords" is included here because its absence should emit a warning.
_RECOMMENDED_TAGS: tuple[str, ...] = ("type", "owner-name", "owner-email", "keywords")


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


def derive_source_name(entry_name: str) -> str:
    """Normalise ``<catalog-metadata><name>`` to a ``KANON_SOURCE_<name>_*`` token.

    Applies soft-spot rule 2 from ``spec/kanon-list-add-lock-features-spec.md``
    Section 3.5 unconditionally:

    1. Lowercase the input.
    2. Replace every ``-`` with ``_``.

    No other transformation is applied. The function is deterministic, pure,
    and idempotent: ``derive_source_name(derive_source_name(x))`` equals
    ``derive_source_name(x)`` for every legal input.

    If the input contains any character outside the set ``[a-zA-Z0-9_-]``, a
    single-line warning is emitted to stderr noting that the entry name
    contains characters outside the recommended set and the normalised form
    may not survive shell quoting cleanly. The transformation is still applied
    and the result is returned. Empty strings produce empty strings; the empty
    string is not considered outside the recommended set and emits no warning.

    Downstream consumers: ``kanon add``, ``kanon remove``, ``kanon why``,
    ``kanon install --refresh-lock-source``.

    Args:
        entry_name: The raw ``<name>`` value from a ``<catalog-metadata>`` block.

    Returns:
        The lowercased, hyphen-to-underscore-converted source name token.
    """
    if entry_name and not RECOMMENDED_CHAR_RE.fullmatch(entry_name):
        print(
            f"WARNING: entry name {entry_name!r} contains characters outside the "
            "recommended set [a-zA-Z0-9_-]; the normalised form may not survive "
            "shell quoting cleanly.",
            file=sys.stderr,
        )
    return entry_name.lower().replace("-", "_")
