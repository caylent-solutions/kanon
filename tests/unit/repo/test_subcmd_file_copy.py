"""Tests verifying the 28 subcmd Python source files are copied to src/kanon_cli/repo/subcmds/."""

import hashlib
import pathlib

import pytest

from tests.unit.repo.conftest import get_rpm_source_dir
from tests.unit.repo.conftest import ruff_format_source
from tests.unit.repo.conftest import strip_noqa_annotations


REPO_ROOT = pathlib.Path(__file__).parents[3]
TARGET_DIR = REPO_ROOT / "src" / "kanon_cli" / "repo" / "subcmds"

SUBCMD_PYTHON_FILES = [
    "__init__.py",
    "abandon.py",
    "branches.py",
    "checkout.py",
    "cherry_pick.py",
    "diff.py",
    "diffmanifests.py",
    "download.py",
    "envsubst.py",
    "forall.py",
    "gc.py",
    "grep.py",
    "help.py",
    "info.py",
    "init.py",
    "list.py",
    "manifest.py",
    "overview.py",
    "prune.py",
    "rebase.py",
    "selfupdate.py",
    "smartsync.py",
    "stage.py",
    "start.py",
    "status.py",
    "sync.py",
    "upload.py",
    "version.py",
]


def _normalize_source(content: bytes) -> bytes:
    """Return a canonical form of Python source for comparison purposes.

    Applies ruff format for style normalization, then strips inline
    lint-suppression annotations (noqa comments) so that required code-quality
    cleanup of the copied files does not cause spurious mismatches against the
    originals.

    Raises:
        subprocess.CalledProcessError: If ruff format exits with a non-zero code.
    """
    formatted = ruff_format_source(content)
    stripped = strip_noqa_annotations(formatted)
    return stripped.encode("utf-8")


@pytest.mark.unit
@pytest.mark.parametrize("filename", SUBCMD_PYTHON_FILES)
def test_subcmd_python_files_exist(filename: str) -> None:
    """Verify each of the 28 subcmd Python files exists under src/kanon_cli/repo/subcmds/."""
    target = TARGET_DIR / filename
    assert target.is_file(), (
        f"Expected file {target} to exist but it does not. "
        f"Copy {filename} from rpm-git-repo/subcmds/ to src/kanon_cli/repo/subcmds/."
    )


@pytest.mark.unit
@pytest.mark.parametrize("filename", SUBCMD_PYTHON_FILES)
def test_subcmd_python_files_content_matches_source(filename: str) -> None:
    """Verify each copied subcmd file contains the same logical content as the source file.

    Both the source and target are normalized through ruff format before comparison
    so that formatting differences do not cause false failures. Inline
    lint-suppression annotations are stripped from both sides before comparison
    so that required code-quality cleanup of the copies does not cause spurious mismatches.
    A mismatch after normalization indicates actual content was altered beyond
    permitted code-quality cleanup.

    This test is skipped when RPM_GIT_REPO_PATH is not set.
    """
    source_dir = get_rpm_source_dir("subcmds")
    source_file = source_dir / filename
    target_file = TARGET_DIR / filename

    assert source_file.is_file(), (
        f"Source file {source_file} does not exist. Verify RPM_GIT_REPO_PATH={source_dir.parent!r} is correct."
    )
    assert target_file.is_file(), (
        f"Target file {target_file} does not exist. "
        f"Copy {filename} from rpm-git-repo/subcmds/ to src/kanon_cli/repo/subcmds/."
    )

    source_normalized = _normalize_source(source_file.read_bytes())
    target_normalized = _normalize_source(target_file.read_bytes())

    source_checksum = hashlib.sha256(source_normalized).hexdigest()
    target_checksum = hashlib.sha256(target_normalized).hexdigest()

    assert source_checksum == target_checksum, (
        f"Content mismatch for {filename} after format normalization: "
        f"source SHA256={source_checksum}, target SHA256={target_checksum}. "
        f"Ensure {filename} was copied without altering its logical content."
    )
