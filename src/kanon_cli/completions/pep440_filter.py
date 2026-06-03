"""Shared PEP 440 tag-name filter helpers for shell-completion dynamic completers.

Implements the filtering described in spec Section 0.4: tab-completion silently
drops non-PEP-440 tag names. The filter applies to the LAST path component of
a tag ref name (e.g. ``refs/tags/release/v3`` is filtered on ``v3``).

Public API::

    is_pep440_tag(ref_last_component: str) -> bool
    filter_pep440_tags(refs: Iterable[str]) -> list[str]

Reused by:
- E7-F2-S1-T4: ``kanon_cli.completions.catalog_versions``
- E7-F2-S1-T5: ``kanon_cli.completions.project_versions``
"""

from __future__ import annotations

from collections.abc import Iterable

from packaging.version import InvalidVersion, Version


def is_pep440_tag(ref_last_component: str) -> bool:
    """Return True if *ref_last_component* parses as a valid PEP 440 version.

    Applies ``packaging.version.Version`` to the string. Empty strings and
    strings that raise ``InvalidVersion`` return False.

    Args:
        ref_last_component: The last path component of a tag ref name (the
            portion after the final ``/`` in the full ref string, or the full
            tag name when there is no ``/``).

    Returns:
        True when the string is a valid PEP 440 version; False otherwise.
    """
    if not ref_last_component:
        return False
    try:
        Version(ref_last_component)
    except InvalidVersion:
        return False
    return True


def filter_pep440_tags(refs: Iterable[str]) -> list[str]:
    """Return the subset of *refs* that are valid PEP 440 version strings.

    Each element of *refs* is treated as a last-path-component tag name (the
    caller is responsible for extracting the last component before passing).
    Elements that fail ``is_pep440_tag()`` are silently dropped. Relative
    ordering of the surviving elements is preserved.

    Args:
        refs: Iterable of tag name strings (last path components only).

    Returns:
        List of PEP 440-valid strings, in the same relative order they
        appeared in *refs*.
    """
    return [ref for ref in refs if is_pep440_tag(ref)]
