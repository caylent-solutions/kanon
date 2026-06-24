"""Deterministic SHA-256 hash over the sources declared in a .kanon file.

The ``kanon_hash`` function computes a stable, deterministic digest that
covers only the KANON_SOURCE_<name>_{URL,REVISION,PATH} triples declared
in a ``.kanon`` file. All comments, blank lines, ordering differences,
workspace-environment keys (GITBASE, CLAUDE_MARKETPLACES_DIR), and the
per-dependency KANON_SOURCE_<alias>_MARKETPLACE flag are excluded from the
hash (the marketplace flag is an install-time side-effect, not a version pin,
so it never perturbs the digest).

Spec reference: spec/kanon-list-add-lock-features-spec.md Section 5.1.
"""

import hashlib
import pathlib

from kanon_cli.core.kanonenv import parse_kanonenv

# Characters forbidden inside any field value used in the hash serialisation.
# A literal tab (0x09) is the field delimiter; a literal newline (0x0A) is
# the record delimiter; a literal NUL (0x00) is rejected because it cannot
# be represented safely in many downstream consumers.
_FORBIDDEN_CHARS: tuple[str, ...] = ("\t", "\n", "\x00")

# Human-readable names for each forbidden character, keyed by the character.
_CHAR_CODEPOINT: dict[str, str] = {
    "\t": "0x09",
    "\n": "0x0A",
    "\x00": "0x00",
}


class KanonHashError(Exception):
    """Raised when a .kanon source field contains a character that cannot be serialised.

    The error message includes the source name, the field name (URL, REVISION,
    or PATH), and the codepoint of the offending character in hex notation.
    """


def kanon_hash(kanon_path: pathlib.Path) -> str:
    """Return a deterministic SHA-256 digest of the .kanon source triples.

    Reads the .kanon file at ``kanon_path`` via ``parse_kanonenv``, extracts
    every ``KANON_SOURCE_<name>_{URL,REVISION,PATH}`` triple, sorts them by
    source name (lexicographic, case-sensitive), serialises as
    ``name\\turl\\trevision\\tpath\\n`` per source, and returns the SHA-256
    digest of those bytes prefixed with ``sha256:``.

    Only the source triples contribute to the digest. Comments, blank lines,
    declaration order, workspace-environment keys (GITBASE,
    CLAUDE_MARKETPLACES_DIR), and the per-dependency
    KANON_SOURCE_<alias>_MARKETPLACE flag are excluded.

    Args:
        kanon_path: Path to the .kanon file to hash.

    Returns:
        A string of the form ``sha256:<64 lowercase hex chars>``.

    Raises:
        FileNotFoundError: If ``kanon_path`` does not exist.
        ValueError: If the .kanon file fails ``parse_kanonenv`` validation
            (e.g. missing required variables, unsafe permissions, symlink).
        KanonHashError: If any source name, URL, REVISION, or PATH value
            contains a literal tab (U+0009), newline (U+000A), or NUL
            (U+0000) that would corrupt the serialised form.
    """
    parsed = parse_kanonenv(kanon_path)
    serialised = _serialise_sources(parsed["sources"])
    digest = hashlib.sha256(serialised)
    return f"sha256:{digest.hexdigest()}"


def _serialise_sources(sources: dict[str, dict[str, str]]) -> bytes:
    """Serialise the alias-keyed source blocks to bytes for hashing.

    Sorts sources by alias (lexicographic, case-sensitive) and encodes each
    as ``alias\\turl\\tref\\tpath\\n`` in UTF-8. Raises ``KanonHashError``
    if any field value contains a tab, newline, or NUL byte.

    Args:
        sources: Dict mapping source alias to a dict with ``url``,
            ``ref``, and ``path`` keys, as returned by
            ``parse_kanonenv``.

    Returns:
        UTF-8 encoded bytes ready for SHA-256 hashing.

    Raises:
        KanonHashError: If any field value contains a forbidden character.
    """
    parts: list[bytes] = []
    for alias in sorted(sources.keys()):
        source = sources[alias]
        url = source["url"]
        ref = source["ref"]
        path = source["path"]
        _check_field(alias, "ALIAS", alias)
        _check_field(alias, "URL", url)
        _check_field(alias, "REF", ref)
        _check_field(alias, "PATH", path)
        parts.append(f"{alias}\t{url}\t{ref}\t{path}\n".encode("utf-8"))
    return b"".join(parts)


def _check_field(source_name: str, field_name: str, value: str) -> None:
    """Raise KanonHashError if ``value`` contains any forbidden character.

    Args:
        source_name: The KANON_SOURCE_<alias> identifier, used in the error.
        field_name: One of ``ALIAS``, ``URL``, ``REF``, or ``PATH``.
        value: The field value to validate.

    Raises:
        KanonHashError: If ``value`` contains a tab, newline, or NUL byte.
    """
    for char in _FORBIDDEN_CHARS:
        if char in value:
            codepoint = _CHAR_CODEPOINT[char]
            if field_name == "ALIAS":
                remediation = (
                    f"Rename the source alias '{source_name}' in the "
                    f"KANON_SOURCE_<alias>_* keys to remove the character."
                )
            else:
                remediation = f"Remove the character from the KANON_SOURCE_{source_name}_{field_name} value."
            msg = (
                f"Source '{source_name}' field {field_name} contains "
                f"forbidden character {codepoint}: the value cannot be "
                f"serialised for hashing. {remediation}"
            )
            raise KanonHashError(msg)
