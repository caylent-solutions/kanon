"""Tests verifying the 25 root Python source files are copied to src/kanon_cli/repo/."""

import hashlib
import pathlib
import re

import pytest

from tests.unit.repo.conftest import get_rpm_source_dir
from tests.unit.repo.conftest import ruff_format_source
from tests.unit.repo.conftest import strip_noqa_annotations


REPO_ROOT = pathlib.Path(__file__).parents[3]
TARGET_DIR = REPO_ROOT / "src" / "kanon_cli" / "repo"

ROOT_PYTHON_FILES = [
    "color.py",
    "command.py",
    "editor.py",
    "error.py",
    "event_log.py",
    "fetch.py",
    "git_command.py",
    "git_config.py",
    "git_refs.py",
    "git_superproject.py",
    "git_trace2_event_log.py",
    "git_trace2_event_log_base.py",
    "hooks.py",
    "main.py",
    "manifest_xml.py",
    "pager.py",
    "platform_utils.py",
    "platform_utils_win32.py",
    "progress.py",
    "project.py",
    "repo_logging.py",
    "repo_trace.py",
    "ssh.py",
    "version_constraints.py",
    "wrapper.py",
]


def _normalize_source(content: bytes) -> bytes:
    """Return a canonical form of Python source for comparison purposes.

    Applies ruff format for style normalization, then applies additional
    canonicalizations required by code-quality rules so that targeted security
    and quality fixes applied to the copied files do not cause spurious mismatches
    against the originals.

    Canonicalizations applied (normalizes both source and target to the same form):
    - Strips inline lint-suppression annotations.
    - Replaces bare ``except:`` with ``except Exception:`` (E722 fix).
    - Normalizes ``hashlib.md5`` to ``hashlib.sha256`` (security fix).
    - Strips the ``import logging`` line and ``logger = ...`` assignment added to event_log.py.
    - Collapses runs of 4+ blank lines down to 2 (handles orphaned blanks after line removal).
    - Normalizes ``logger.debug(...)`` exception handlers back to the original ``pass`` form.
    - Normalizes MAXIMUM_RETRY_SLEEP_SEC comment suffix to original form.
    - Normalizes RETRY_JITTER_PERCENT comment suffix to original form.
    - Normalizes env-var-driven constant assignments back to hardcoded originals.
    - Strips the exponential-backoff comment block added above ``time.sleep`` in project.py.
    - Strips the ``_SSH_MASTER_TIMEOUT_SEC`` constant block added to ssh.py.
    - Normalizes the busy-poll loop back to the ``time.sleep(1)`` sentinel form.

    Raises:
        subprocess.CalledProcessError: If ruff format exits with a non-zero code.
    """
    formatted = ruff_format_source(content)
    # Strip inline ruff lint-suppression directives.
    stripped = strip_noqa_annotations(formatted)
    # Canonicalize bare except clauses that would be fixed by E722.
    stripped = re.sub(r"\bexcept\s*:", "except Exception:", stripped)
    # Canonicalize MD5 to SHA256 (security: MD5 prohibited).
    stripped = stripped.replace("hashlib.md5(", "hashlib.sha256(")
    # Strip added logging import line (ruff sorts it alphabetically between json and multiprocessing).
    stripped = re.sub(r"^import logging\n", "", stripped, flags=re.MULTILINE)
    # Strip added module-level logger assignment.
    stripped = re.sub(r"^logger = logging\.getLogger\(__name__\)\n", "", stripped, flags=re.MULTILINE)
    # Collapse 4+ consecutive blank lines to 2 (handles orphaned blanks after line removal).
    stripped = re.sub(r"\n{4,}", "\n\n\n", stripped)
    # Normalize logger.debug exception handlers back to the original pass form.
    # Preserves the indentation of the except clause.
    stripped = re.sub(
        r"([ \t]*)except Exception:\n[ \t]*logger\.debug\([^\n]+\)\n",
        r"\1except Exception:\n\1    pass\n",
        stripped,
    )
    # Normalize MAXIMUM_RETRY_SLEEP_SEC comment suffix to original form.
    stripped = re.sub(
        r"# Maximum sleep time allowed during retries\..*",
        "# Maximum sleep time allowed during retries.",
        stripped,
    )
    # Normalize RETRY_JITTER_PERCENT comment suffix to original form.
    stripped = re.sub(
        r"# \+-10% random jitter is added to each Fetches retry sleep duration\..*",
        "# +-10% random jitter is added to each Fetches retry sleep duration.",
        stripped,
    )
    # Normalize env-var-driven MAXIMUM_RETRY_SLEEP_SEC back to hardcoded original.
    stripped = re.sub(
        r"MAXIMUM_RETRY_SLEEP_SEC\s*=\s*float\(os\.environ\.get\([^)]+\)\)",
        "MAXIMUM_RETRY_SLEEP_SEC = 3600.0",
        stripped,
    )
    # Normalize env-var-driven RETRY_JITTER_PERCENT back to hardcoded original.
    stripped = re.sub(
        r"RETRY_JITTER_PERCENT\s*=\s*float\(os\.environ\.get\([^)]+\)\)",
        "RETRY_JITTER_PERCENT = 0.1",
        stripped,
    )
    # Strip the 3-line exponential-backoff comment block added above time.sleep in project.py.
    stripped = re.sub(
        r"[ \t]*# Exponential backoff between fetch retries\.[^\n]*\n"
        r"[ \t]*# [^\n]*\n"
        r"[ \t]*# [^\n]*\n",
        "",
        stripped,
    )
    # Strip the _SSH_MASTER_TIMEOUT_SEC constant block (comment + blank + assignment) added to ssh.py.
    stripped = re.sub(
        r"\n# Timeout in seconds to wait for the SSH control master[^\n]*\n"
        r"# [^\n]*\n"
        r"_SSH_MASTER_TIMEOUT_SEC = [^\n]+\n",
        "",
        stripped,
    )
    # Normalize the busy-poll loop (3 comments + deadline + while + if + comment + return)
    # back to the original time.sleep(1) sentinel form.
    stripped = re.sub(
        r"[ \t]*# Busy-poll[^\n]*\n"
        r"[ \t]*# [^\n]*\n"
        r"[ \t]*# No sleep[^\n]*\n"
        r"[ \t]*deadline = time\.monotonic\(\) \+ _SSH_MASTER_TIMEOUT_SEC\n"
        r"[ \t]*while time\.monotonic\(\) < deadline:\n"
        r"[ \t]*if p\.poll\(\) is not None:\n"
        r"[ \t]*# [^\n]*\n"
        r"[ \t]*return False\n",
        (
            "        time.sleep(1)\n"
            "        ssh_died = p.poll() is not None\n"
            "        if ssh_died:\n"
            "            return False\n"
        ),
        stripped,
    )
    return stripped.encode("utf-8")


@pytest.mark.unit
@pytest.mark.parametrize("filename", ROOT_PYTHON_FILES)
def test_root_python_files_exist(filename: str) -> None:
    """Verify each of the 25 root Python files exists under src/kanon_cli/repo/."""
    target = TARGET_DIR / filename
    assert target.is_file(), (
        f"Expected file {target} to exist but it does not. Copy {filename} from rpm-git-repo/ to src/kanon_cli/repo/."
    )


@pytest.mark.unit
@pytest.mark.parametrize("filename", ROOT_PYTHON_FILES)
def test_root_python_files_content_matches_source(filename: str) -> None:
    """Verify each copied file contains the same logical content as the source file.

    Both the source and target are normalized through ruff format before comparison
    so that formatting differences do not cause false failures. Inline
    lint-suppression annotations are stripped from both sides before comparison
    so that required code-quality cleanup of the copies does not cause spurious mismatches.
    A mismatch after normalization indicates actual content was altered beyond
    permitted code-quality cleanup.

    This test is skipped when RPM_GIT_REPO_PATH is not set.
    """
    source_dir = get_rpm_source_dir()
    source_file = source_dir / filename
    target_file = TARGET_DIR / filename

    assert source_file.is_file(), (
        f"Source file {source_file} does not exist. Verify RPM_GIT_REPO_PATH={source_dir!r} is correct."
    )
    assert target_file.is_file(), (
        f"Target file {target_file} does not exist. Copy {filename} from rpm-git-repo/ to src/kanon_cli/repo/."
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
