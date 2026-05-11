"""URL canonicalisation utilities for kanon.

Implements the canonical-URL contract described in spec Section 4.0
"Repo URL canonicalization". The public entry-point is
``canonicalize_repo_url``.

Transformation rules (applied in order):
  1. Validate input is non-empty and non-whitespace.
  2. Detect the input scheme: https://, ssh://, or SCP shorthand
     (``[user@]host:path`` with no scheme prefix).
  3. Reject inputs that contain a query string (``?``) or fragment (``#``).
  4. Strip embedded user-info from the authority (the ``user@`` prefix).
  5. Lowercase the host; preserve path case verbatim.
  6. Strip exactly one trailing ``/`` from the path (if present).
  7. Strip exactly one trailing ``.git`` suffix from the path (if present,
     applied after the trailing-slash strip).
  8. Normalise the scheme to ``https://`` regardless of input scheme.
  9. Preserve the port when present.
"""

import re
from urllib.parse import urlsplit

# Pattern for the SCP shorthand: [user@]host:path
# The host must not contain ``/`` or ``:``, and the path follows the colon.
_SCP_RE = re.compile(r"^(?P<user>[^@/:]+@)?(?P<host>[^@/:]+):(?P<path>.+)$")


def _reject_query_and_fragment(url: str) -> None:
    """Raise ``ValueError`` if ``url`` contains a query string or fragment.

    Args:
        url: The raw input URL string to inspect.

    Raises:
        ValueError: If ``?`` (query string) or ``#`` (fragment) is present.
    """
    if "?" in url:
        raise ValueError(
            f"ERROR: Canonicalisation is undefined for URLs with a query string.\n"
            f"  Input: {url!r}\n"
            f"  Remove the query string before canonicalising."
        )
    if "#" in url:
        raise ValueError(
            f"ERROR: Canonicalisation is undefined for URLs with a fragment.\n"
            f"  Input: {url!r}\n"
            f"  Remove the fragment before canonicalising."
        )


def _parse_scp(url: str) -> tuple[str, str]:
    """Return ``(host, path)`` parsed from an SCP-shorthand URL.

    Args:
        url: A string in ``[user@]host:path`` form.

    Returns:
        A tuple of ``(host, path)`` with user-info already stripped.

    Raises:
        ValueError: If the URL does not match the SCP pattern.
    """
    m = _SCP_RE.match(url)
    if m is None:
        raise ValueError(
            f"ERROR: Cannot parse SCP-shorthand URL.\n  Input: {url!r}\n  Expected format: [user@]host:path"
        )
    return m.group("host"), m.group("path")


def _parse_scheme_url(url: str) -> tuple[str, str]:
    """Return ``(authority, path)`` from an ``https://`` or ``ssh://`` URL.

    The authority includes the lowercased host and the port (when present).
    User-info is stripped. Query strings and fragments are rejected before
    parsing.

    Args:
        url: A URL beginning with ``https://`` or ``ssh://``.

    Returns:
        A tuple of ``(authority, path)`` ready for canonical assembly.

    Raises:
        ValueError: If the URL contains a query string or fragment.
    """
    _reject_query_and_fragment(url)
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    port = parsed.port
    authority = f"{host}:{port}" if port else host
    return authority, parsed.path


def canonicalize_repo_url(url: str) -> str:
    """Return the canonical form of a git repository URL.

    Two URLs identify the same repository iff
    ``canonicalize_repo_url(a) == canonicalize_repo_url(b)``.

    Transformation rules applied (spec Section 4.0):
      1. Empty or whitespace-only input raises ``ValueError``.
      2. Inputs with a query string or fragment raise ``ValueError``.
      3. User-info (``user@``) is stripped from the authority.
      4. Host is lowercased; path case is preserved verbatim.
      5. Trailing ``/`` is stripped from the path.
      6. Trailing ``.git`` suffix is stripped from the path.
      7. Output scheme is always ``https://``.
      8. Port is preserved when present.

    Accepted input shapes:
      - ``https://[user@]host[:port]/path``
      - ``ssh://[user@]host[:port]/path``
      - ``[user@]host:path`` (SCP shorthand, no scheme prefix)

    Args:
        url: A git repository URL in any of the accepted shapes.

    Returns:
        The canonical ``https://host[:port]/path`` string.

    Raises:
        ValueError: If the URL is empty, whitespace-only, contains a
            query string, or contains a fragment.
    """
    if not url or not url.strip():
        raise ValueError(
            f"ERROR: Repository URL must not be empty.\n"
            f"  Input: {url!r}\n"
            f"  Provide a valid https://, ssh://, or SCP-shorthand URL."
        )

    stripped = url.strip()

    if stripped.startswith(("https://", "ssh://")):
        authority, path = _parse_scheme_url(stripped)
    else:
        # SCP shorthand -- no scheme prefix.
        _reject_query_and_fragment(stripped)
        host_raw, path_raw = _parse_scp(stripped)
        authority = host_raw.lower()
        # SCP path does not start with ``/``; normalise for uniform processing.
        path = "/" + path_raw.lstrip("/")

    # Strip exactly one trailing slash (rule 6), then .git suffix (rule 7).
    if path.endswith("/"):
        path = path[:-1]
    if path.endswith(".git"):
        path = path[:-4]

    return f"https://{authority}{path}"
