"""Shared test helpers for tests/unit/repo/.

Provides reusable utilities for content-match tests that verify copied
rpm-git-repo source files against their originals.

Also configures sys.path so that the verbatim-copied rpm-git-repo test files
(which use relative bare imports like ``from test_manifest_xml import ...``)
can locate sibling test modules during collection.  Import fixes for these
files happen in E0-F5-S1-T3; this path entry is the minimal change needed to
prevent collection errors while those files are still unmodified.
"""

import os
import pathlib
import re
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).parents[3]
"""Root of the kanon repository (3 levels up from tests/unit/repo/)."""

TARGET_DIR = REPO_ROOT / "src" / "kanon_cli" / "repo"
"""Target directory where rpm-git-repo source files are copied."""

_THIS_DIR = str(pathlib.Path(__file__).parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)


def get_rpm_source_dir(subdirectory: str | None = None) -> pathlib.Path:
    """Return the rpm-git-repo source directory from the RPM_GIT_REPO_PATH env var.

    Skips the calling test via pytest.skip() if RPM_GIT_REPO_PATH is not set,
    so tests are skipped gracefully rather than erroring when the env var is absent.

    Args:
        subdirectory: Optional subdirectory name to append to the source root
            (e.g. ``"subcmds"`` to get the subcmds directory).

    Returns:
        The resolved source directory path.

    Raises:
        RuntimeError: If RPM_GIT_REPO_PATH is set but does not point to an
            existing directory, or if the requested subdirectory does not exist.
    """
    raw = os.environ.get("RPM_GIT_REPO_PATH")
    if not raw:
        pytest.skip("RPM_GIT_REPO_PATH is not set -- skipping content-match tests")
    source_root = pathlib.Path(raw)
    if not source_root.is_dir():
        raise RuntimeError(f"RPM_GIT_REPO_PATH={raw!r} does not point to an existing directory.")
    if subdirectory is None:
        return source_root
    source_dir = source_root / subdirectory
    if not source_dir.is_dir():
        raise RuntimeError(f"Expected {subdirectory!r} directory at {source_dir} but it does not exist.")
    return source_dir


def ruff_format_source(content: bytes) -> str:
    """Run ruff format on the given source bytes and return the formatted string.

    Args:
        content: Raw Python source bytes to format.

    Returns:
        The formatted source as a UTF-8 string.

    Raises:
        subprocess.CalledProcessError: If ruff format exits with a non-zero code.
    """
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--quiet", "-"],
        input=content,
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8")


def strip_noqa_annotations(source: str) -> str:
    """Strip inline ruff lint-suppression annotations from formatted source.

    Args:
        source: Formatted Python source string.

    Returns:
        Source with all ``# noqa`` inline comments removed.
    """
    return re.sub(r"[ \t]+#[ \t]*noqa[^\n]*", "", source)
