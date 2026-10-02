"""Enforce the minimum kanon version a .kanon file declares.

A repository pins the oldest kanon that may operate on it with a global line::

    KANON_MIN_VERSION=3.4.2

Commands that read or rewrite ``.kanon`` (``install``, ``add``, ``remove``,
``clean``) call :func:`enforce_min_version` before doing any work. A running
kanon below the declared minimum fails fast with the upgrade command; a value
that is not a single PEP 440 version fails fast too, rather than being skipped.
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
    """Raised when the running kanon is older than the .kanon's KANON_MIN_VERSION.

    Subclasses ``ValueError`` so the CLI user-error boundary prints it as a
    plain ``ERROR:`` line and exits 1.
    """


def enforce_min_version(kanon_file: pathlib.Path, running_version: str = __version__) -> None:
    """Fail when the running kanon is older than the .kanon's declared minimum.

    A missing ``.kanon`` or one without ``KANON_MIN_VERSION`` imposes no
    minimum. The value is read verbatim from the file: OS environment variables
    can neither lower nor impose it.

    Args:
        kanon_file: Path to the .kanon file.
        running_version: The kanon version to check. Defaults to this package's
            version.

    Raises:
        KanonVersionTooOldError: If ``running_version`` is below the minimum.
        ValueError: If ``KANON_MIN_VERSION`` is not a single PEP 440 version, or
            the key is declared more than once.
    """
    declared = read_raw_value(kanon_file, KANON_MIN_VERSION_KEY)
    if declared is None:
        return
    required = _parse_declared(kanon_file, declared)
    if Version(running_version) < required:
        raise KanonVersionTooOldError(
            KANON_MIN_VERSION_TOO_OLD_TEMPLATE.format(
                path=kanon_file,
                required=required,
                running=running_version,
                upgrade_command=KANON_UPDATE_UPGRADE_COMMAND,
            )
        )


def _parse_declared(kanon_file: pathlib.Path, declared: str) -> Version:
    try:
        return Version(declared)
    except InvalidVersion as exc:
        raise ValueError(
            KANON_MIN_VERSION_INVALID_TEMPLATE.format(key=KANON_MIN_VERSION_KEY, value=declared, path=kanon_file)
        ) from exc
