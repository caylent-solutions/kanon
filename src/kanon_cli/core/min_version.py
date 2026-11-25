"""Enforce the minimum kanon version a .kanon file or catalog entry declares.

A repository pins the oldest kanon that may operate on it with a global line::

    KANON_MIN_VERSION=3.4.2

Commands that read or rewrite ``.kanon`` (``install``, ``add``, ``remove``,
``clean``) call :func:`enforce_min_version` before doing any work. A catalog
entry may also declare ``<min-kanon-version>`` in its ``<catalog-metadata>``;
``kanon add`` checks it with :func:`require_kanon_version` and carries the
highest minimum into ``.kanon``. A running kanon below a minimum fails fast with
the upgrade command; a value that is not a single PEP 440 version fails fast
too, rather than being skipped.
"""

import pathlib

from packaging.version import InvalidVersion, Version

from kanon_cli import __version__
from kanon_cli.constants import (
    KANON_MIN_VERSION_INVALID_TEMPLATE,
    KANON_MIN_VERSION_KEY,
    KANON_MIN_VERSION_TOO_OLD_TEMPLATE,
    KANON_UPDATE_UPGRADE_COMMAND,
)
from kanon_cli.core.kanonenv import read_raw_value


class KanonVersionTooOldError(ValueError):
    """Raised when the running kanon is older than a declared minimum version.

    Subclasses ``ValueError`` so the CLI user-error boundary prints it as a
    plain ``ERROR:`` line and exits 1.
    """


def parse_min_version(value: str, *, key: str, origin: str) -> Version:
    """Parse a declared minimum version, failing loudly on anything malformed.

    Args:
        value: The declared text.
        key: The name the value was declared under, for the error message.
        origin: Where the value was declared (a file path), for the error message.

    Returns:
        The parsed version.

    Raises:
        ValueError: If ``value`` is not a single PEP 440 version.
    """
    try:
        return Version(value)
    except InvalidVersion as exc:
        raise ValueError(KANON_MIN_VERSION_INVALID_TEMPLATE.format(key=key, value=value, origin=origin)) from exc


def require_kanon_version(required: Version, *, origin: str, running_version: str = __version__) -> None:
    """Fail when the running kanon is older than ``required``.

    Args:
        required: The minimum kanon version.
        origin: What declared the minimum, named in the error message.
        running_version: The kanon version to check. Defaults to this package's
            version.

    Raises:
        KanonVersionTooOldError: If ``running_version`` is below ``required``.
    """
    if Version(running_version) < required:
        raise KanonVersionTooOldError(
            KANON_MIN_VERSION_TOO_OLD_TEMPLATE.format(
                origin=origin,
                required=required,
                running=running_version,
                upgrade_command=KANON_UPDATE_UPGRADE_COMMAND,
            )
        )


def enforce_min_version(kanon_file: pathlib.Path, running_version: str = __version__) -> Version | None:
    """Fail when the running kanon is older than the .kanon's declared minimum.

    A missing ``.kanon`` or one without ``KANON_MIN_VERSION`` imposes no
    minimum. The value is read verbatim from the file: OS environment variables
    can neither lower nor impose it.

    Args:
        kanon_file: Path to the .kanon file.
        running_version: The kanon version to check. Defaults to this package's
            version.

    Returns:
        The declared minimum, or None when the file declares none.

    Raises:
        KanonVersionTooOldError: If ``running_version`` is below the minimum.
        ValueError: If ``KANON_MIN_VERSION`` is not a single PEP 440 version, or
            the key is declared more than once.
    """
    declared = read_raw_value(kanon_file, KANON_MIN_VERSION_KEY)
    if declared is None:
        return None
    required = parse_min_version(declared, key=KANON_MIN_VERSION_KEY, origin=str(kanon_file))
    require_kanon_version(required, origin=str(kanon_file), running_version=running_version)
    return required
